"""Phase 11 tests — upload pipeline: detection, ColumnMapper, end-to-end.

Proves plan §29–32 on synthetic files:
  - detection by MAGIC BYTES / header, never by extension
  - CIC-style CSV, UNSW-style generic CSV, and PCAP all reach a forecast
    through the SAME windowing + conditioning as training/live
  - unknown schema raises (never a silent guess)
  - unavailable features are reported, not passed off as real zeros
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import BIN_SECS, SEQ_LEN
from src.ingestion.upload_pipeline import (AnalysisError, ColumnMapper,
                                           UnknownSchemaError, analyze_file,
                                           detect_format)

from tests.test_dataset_adapters import CIC_COLS, _row


# ------------------------------------------------------------------ fixtures

def _cic_csv(path: Path, n_bins: int = 15) -> Path:
    """n_bins x 30s of CIC-style traffic; SSH brute force in the last 3 bins."""
    rows = []
    for b in range(n_bins):
        minute, sec = divmod(b, 2)
        label = "SSH-Brute-Force" if b >= n_bins - 3 else "Benign"
        port, syn = (22, 1) if label != "Benign" else (443, 0)
        rows += [_row(f"14/02/2018 09:{minute:02d}:{sec * 30 + s:02d}", label,
                      port=port, syn=syn) for s in range(0, 10, 5)]
    path.write_text(pd.DataFrame(rows, columns=CIC_COLS).to_csv(index=False),
                    encoding="utf-8")
    return path


def _generic_csv(path: Path, n_bins: int = 15) -> Path:
    """UNSW-NB15-flavoured header — the ColumnMapper's whole point."""
    rows = []
    t0 = pd.Timestamp("2026-01-01 12:00:00")
    for b in range(n_bins):
        for s in range(0, 30, 10):
            rows.append({
                "StartTime": (t0 + pd.Timedelta(seconds=b * BIN_SECS + s)
                              ).strftime("%Y-%m-%d %H:%M:%S"),
                "srcaddr": "192.168.1.10", "dstaddr": "10.0.0.5",
                "sport": 40000, "dport": 22 if b >= n_bins - 3 else 443,
                "proto": "tcp",
                "bytes": 1500 + s, "pkts": 4, "dur": 0.5,
                "attack_cat": "" if b < n_bins - 3 else "Exploits",
            })
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


@pytest.fixture()
def real_forecaster():
    from src.forecasting.rollout import Forecaster
    fc, err = Forecaster.load()
    if fc is None:
        pytest.skip(f"frozen V1 model unavailable: {err}")
    return fc


@pytest.fixture()
def engines():
    from src.decision_support.engine import DecisionSupportEngine
    from src.explainability.evidence import EvidenceEngine
    baseline = Path("models/benign_baseline.json")
    ev = EvidenceEngine.load(baseline) if baseline.exists() else None
    return ev, DecisionSupportEngine()


# ---------------------------------------------------------------- detection

def test_detect_cic_csv(tmp_path):
    det = detect_format(_cic_csv(tmp_path / "up.csv"))
    assert det["format"] == "csv" and det["style"] == "cic-flow-csv"
    assert det["confidence"] >= 0.7


def test_detect_generic_csv(tmp_path):
    det = detect_format(_generic_csv(tmp_path / "unsw.csv"))
    assert det["format"] == "csv" and det["style"] == "generic-flow-csv"
    assert "srcaddr" not in det["matched"]            # canonical names only


def test_detect_unknown_schema_raises_with_report(tmp_path):
    p = tmp_path / "junk.csv"
    pd.DataFrame({"foo": [1], "bar": [2]}).to_csv(p, index=False)
    with pytest.raises(UnknownSchemaError) as ei:
        detect_format(p)
    assert "map columns" in str(ei.value)


def test_detection_ignores_extension(tmp_path):
    """Magic bytes decide, never the filename (parse-never-execute)."""
    scapy = pytest.importorskip("scapy")
    from scapy.all import IP, TCP, wrpcap
    p = tmp_path / "actually_pcap.csv"            # pcap content, csv name
    wrpcap(str(p), [IP(src="1.1.1.1", dst="2.2.2.2") / TCP()])
    assert detect_format(p)["format"] == "pcap"
    q = tmp_path / "actually_csv.pcap"            # csv content, pcap name
    _cic_csv(q)
    assert detect_format(q)["format"] == "csv"


# ------------------------------------------------------------- ColumnMapper

def test_column_mapper_aliases():
    rep = ColumnMapper().map_columns(
        ["StartTime", "srcaddr", "dstaddr", "sport", "dport", "proto",
         "bytes", "pkts", "dur", "attack_cat", "extra_col"])
    m = rep.mapping
    assert m["ts"] == "StartTime" and m["src_ip"] == "srcaddr"
    assert m["dst_port"] == "dport" and m["label"] == "attack_cat"
    assert "extra_col" in rep.unmapped


def test_column_mapper_explicit_beats_alias():
    rep = ColumnMapper({"ts": "event_time"}).map_columns(
        ["event_time", "StartTime", "dport"])
    assert rep.mapping["ts"] == "event_time"


def test_to_flows_requires_timestamp():
    with pytest.raises(UnknownSchemaError):
        ColumnMapper().to_flows(pd.DataFrame({"dport": [80]}))


def test_to_flows_unit_conversion():
    df = pd.DataFrame({
        "StartTime": ["2026-01-01 00:00:00"], "dport": [443],
        "bytes": [5000], "pkts": [10], "dur": [2.0], "proto": [6]})
    flows, rep = ColumnMapper().to_flows(df)
    assert flows["Flow Duration"].iloc[0] == pytest.approx(2_000_000.0)  # s→µs
    assert flows["TotLen Fwd Pkts"].iloc[0] == 5000
    assert flows["Label"].iloc[0] == "Benign"      # no label column → benign


# ------------------------------------------------------------------ end-to-end

def _assert_honest_record(out):
    from src.decision_support.levels import LEVELS
    assert out["n_forecasts"] == out["n_windows"] - (SEQ_LEN - 1)
    latest = out["latest"]
    assert len(latest["probs"]) == 5 and latest["threshold"] > 0
    assert 0 <= latest["peak"] <= 1
    ds = out["decision_support"]
    assert ds["level"] in LEVELS
    assert "NOT blocked" in ds["human_in_loop"]
    assert ds["recommendations"]
    unc = out["uncertainty"]
    assert unc and unc["confidence"] in ("HIGH", "MEDIUM", "LOW")


def test_analyze_cic_csv_end_to_end(tmp_path, real_forecaster, engines):
    out = analyze_file(_cic_csv(tmp_path / "up.csv"), real_forecaster,
                       evidence_engine=engines[0], ds_engine=engines[1])
    assert out["detection"]["style"] == "cic-flow-csv"
    _assert_honest_record(out)
    # IP features are honestly unavailable in CIC CSVs — reported, not faked
    assert "unique_src_ips" in out["unavailable_features"]
    assert "unique_dst_ips" in out["unavailable_features"]
    # evidence cites real numbers (baseline exists in this repo)
    if out["evidence"]:
        e = out["evidence"][0]
        assert e["feature"] and "benign_mean" in e


def test_analyze_generic_csv_end_to_end(tmp_path, real_forecaster, engines):
    out = analyze_file(_generic_csv(tmp_path / "unsw.csv"), real_forecaster,
                       evidence_engine=engines[0], ds_engine=engines[1])
    assert out["detection"]["style"] == "generic-flow-csv"
    _assert_honest_record(out)
    # flag/IAT/pkt-size columns absent from this source → reported unavailable
    for f in ("iat_mean", "avg_pkt_size", "syn_ratio"):
        assert f in out["unavailable_features"]


def test_analyze_pcap_end_to_end(tmp_path, real_forecaster, engines):
    scapy = pytest.importorskip("scapy")
    from scapy.all import IP, TCP, wrpcap
    t0 = int(pd.Timestamp("2026-01-01 12:00:00").timestamp())
    pkts = []
    for b in range(SEQ_LEN + 3):                      # 13 bins
        for s in range(3):
            p = IP(src="10.0.0.1", dst="10.0.0.2", ttl=64) / TCP(
                sport=40000 + s, dport=22 if b >= SEQ_LEN else 443,
                flags="S", window=8192, seq=100 + s)
            p.time = t0 + b * BIN_SECS + s * 5
            pkts.append(p)
    pth = tmp_path / "capture.pcap"
    wrpcap(str(pth), pkts)

    out = analyze_file(pth, real_forecaster,
                       evidence_engine=engines[0], ds_engine=engines[1])
    assert out["detection"]["format"] == "pcap"
    _assert_honest_record(out)
    # packets DO see IPs — they must NOT be in the unavailable list
    assert "unique_src_ips" not in out["unavailable_features"]
    assert "unique_dst_ips" not in out["unavailable_features"]
    # packet-level features arrived and are reported as provided
    assert "ttl_mean" not in out["unavailable_features"]


def test_analyze_too_short_raises(tmp_path, real_forecaster):
    with pytest.raises(AnalysisError, match="windows"):
        analyze_file(_cic_csv(tmp_path / "short.csv", n_bins=3), real_forecaster)


def test_trajectory_marches_through_time(tmp_path, real_forecaster):
    out = analyze_file(_cic_csv(tmp_path / "up.csv"), real_forecaster)
    peaks = [t["peak"] for t in out["trajectory"]]
    assert len(peaks) == out["n_forecasts"]
    # the model was trained on ~900-flow/min windows; this toy fixture
    # (2 flows/bin) legitimately reads as near-zero risk everywhere. We
    # assert STRUCTURE, not that the model must fire on a micro-burst.
    assert all(0 <= p <= 1 for p in peaks)
    # ts strictly increases
    ts = [t["ts"] for t in out["trajectory"]]
    assert all(b > a for a, b in zip(ts, ts[1:]))
