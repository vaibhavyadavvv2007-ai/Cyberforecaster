"""UNSW-NB15 adapter tests.

The synthetic fixture writes headerless 49-column CSVs (column order IS the
schema, exactly like the real files) and drives the full adapter path:
validate → load → to_window_slots → labels → canonical sequences.

A separate smoke test runs against the REAL downloaded files when they exist
(data/raw/unsw_nb15/UNSW-NB15_1.csv) — skipped otherwise, so CI on a machine
without the 560 MB download still passes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.datasets.base import FLOW_COLUMNS
from src.datasets.registry import get_adapter, status
from src.datasets.unsw_nb15 import UNSW_COLUMNS
from src.features.canonical_schema import (FEATURE_NAMES,
                                           UNSW_NB15_AVAILABLE)
from src.features.sequence_engine import make_canonical_sequences
from src.labels.attack_taxonomy import (BENIGN, EXECUTION, IMPACT,
                                        INITIAL_ACCESS, RECONNAISSANCE,
                                        canonicalize)

EPOCH = 1421927400          # 2015-01-22 11:50:00 UTC — aligned to a 30s bin
                            # boundary so fixture rows land in exactly 2 bins


def _row(t_off: float, dst_ip="149.171.126.6", dst_port=53, proto="tcp",
         sbytes=132, dbytes=164, dur=0.001, attack="", **over) -> list:
    """One 49-column UNSW row, in file order. Defaults mirror a real benign
    DNS-ish flow from the actual UNSW-NB15_1.csv head."""
    v = {
        "srcip": "59.166.0.9", "sport": 1390, "dstip": dst_ip,
        "dsport": dst_port, "proto": proto, "state": "CON", "dur": dur,
        "sbytes": sbytes, "dbytes": dbytes, "sttl": 31, "dttl": 29,
        "sloss": 0, "dloss": 0, "service": "dns", "Sload": 500473.9,
        "Dload": 621800.9, "Spkts": 2, "Dpkts": 2, "swin": 66, "dwin": 82,
        "stcpb": 0, "dtcpb": 0, "smeansz": 66, "dmeansz": 82,
        "trans_depth": 0, "res_bdy_len": 0, "Sjit": 0.017, "Djit": 0.013,
        "Stime": EPOCH + t_off, "Ltime": EPOCH + t_off + dur,
        "Sintpkt": 2.0, "Dintpkt": 3.0, "tcprtt": 0.0, "synack": 0.0,
        "ackdat": 0.0, "is_sm_ips_ports": 0, "ct_state_ttl": 1,
        "ct_flw_http_mthd": 0, "is_ftp_login": 0, "ct_ftp_cmd": 0,
        "ct_srv_src": 3, "ct_srv_dst": 7, "ct_dst_ltm": 1, "ct_src_ltm": 3,
        "ct_src_dport_ltm": 1, "ct_dst_sport_ltm": 1, "ct_dst_src_ltm": 1,
        "attack_cat": attack, "Label": 1 if attack else 0,
    }
    v.update(over)
    return [v[c] for c in UNSW_COLUMNS]


@pytest.fixture()
def unsw_dir(tmp_path: Path) -> Path:
    """Two 30-second bins: benign DNS-ish traffic, then a Reconnaissance
    port-scan burst from one source to many ports."""
    d = tmp_path / "unsw_nb15"
    d.mkdir()
    rows = ([_row(s) for s in range(0, 30, 3)]                    # bin 1 benign
            + [_row(30 + s, dst_ip=f"10.0.0.{i}", dst_port=1000 + i,
                    attack="Reconnaissance", sport=4444, Spkts=1, Dpkts=0)
               for i, s in enumerate(range(0, 30, 3))])           # bin 2 attack
    for part in (1, 2, 3, 4):
        pd.DataFrame(rows if part == 1 else []).to_csv(
            d / f"UNSW-NB15_{part}.csv", header=False, index=False)
    return d


# ---------------------------------------------------------------- taxonomy

@pytest.mark.parametrize("label,stage", [
    ("Reconnaissance", RECONNAISSANCE),
    ("Analysis", RECONNAISSANCE),
    ("Fuzzers", RECONNAISSANCE),
    ("Backdoor", INITIAL_ACCESS),
    ("Backdoors", INITIAL_ACCESS),        # spelling variant, both mapped
    ("Exploits", INITIAL_ACCESS),
    ("Shellcode", EXECUTION),
    ("Worms", "LATERAL_MOVEMENT"),
    ("DoS", IMPACT),
    ("Generic", "UNKNOWN_ATTACK"),        # honest refusal to guess
])
def test_family_mapping(label, stage):
    rec = canonicalize("unsw_nb15", label)
    assert rec.canonical_label == stage
    assert rec.dataset_label == label          # original never discarded
    assert rec.mapping_source == "manual/research"


def test_benign_sentinels():
    for sent in ("", "NORMAL", "Normal"):
        assert canonicalize("unsw_nb15", sent).canonical_label == BENIGN


# -------------------------------------------------------------- validate

def test_validate_accepts_real_layout(unsw_dir: Path):
    a = get_adapter("unsw_nb15")
    files = a.discover(unsw_dir.parent)
    assert len(files) == 4
    rep = a.validate(files)
    assert rep.ok, rep.errors
    assert rep.detected_format.startswith("UNSW-NB15")
    assert rep.confidence == 1.0


def test_discover_ignores_auxiliary_files(unsw_dir: Path):
    (unsw_dir / "NUSW-NB15_GT.csv").write_text("x\n")
    (unsw_dir / "NUSW-NB15_features.csv").write_text("x\n")
    assert len(get_adapter("unsw_nb15").discover(unsw_dir.parent)) == 4


def test_validate_rejects_partial_download(unsw_dir: Path):
    a = get_adapter("unsw_nb15")
    (unsw_dir / "UNSW-NB15_4.csv").unlink()
    rep = a.validate(a.discover(unsw_dir.parent))
    assert not rep.ok
    assert any("partial" in v for v in rep.checks.values())


def test_validate_rejects_foreign_csv(tmp_path: Path):
    d = tmp_path / "unsw_nb15"
    d.mkdir()
    for part in (1, 2, 3, 4):
        pd.DataFrame({"a": [1], "b": [2]}).to_csv(
            d / f"UNSW-NB15_{part}.csv", index=False)
    a = get_adapter("unsw_nb15")
    rep = a.validate(a.discover(d.parent))
    assert not rep.ok


# ------------------------------------------------------------------- load

def test_load_produces_canonical_flow_record(unsw_dir: Path):
    a = get_adapter("unsw_nb15")
    flows = a.load(a.discover(unsw_dir.parent))
    for col in FLOW_COLUMNS:
        assert col in flows.columns, f"missing canonical column {col}"
    # unavailable quantities are NaN — never fabricated zeros
    for col in ("iat_std_s", "syn_cnt", "ack_cnt", "fin_cnt", "rst_cnt",
                "psh_cnt"):
        assert flows[col].isna().all(), f"{col} must be unavailable (NaN)"
    # benignant: label carried verbatim, empty → NORMAL
    assert set(flows["dataset_label"].unique()) == {"NORMAL", "Reconnaissance"}
    # iat_mean: mean of Sintpkt/Dintpkt (2.0/3.0 ms) → 0.0025 s
    assert flows["iat_mean_s"].iloc[0] == pytest.approx(0.0025)
    # timestamps parsed as UTC datetimes from epoch seconds
    assert flows["ts"].iloc[0].value // 10**9 == EPOCH


# ---------------------------------------------------------------- windows

def test_to_window_slots_availability_and_labels(unsw_dir: Path):
    a = get_adapter("unsw_nb15")
    flows = a.load(a.discover(unsw_dir.parent))
    slots, labels = a.to_window_slots(flows, bin_secs=30)
    assert len(slots) == len(labels) == 2

    benign, attack = slots
    # the honest capability set — IPs AVAILABLE (unlike cic2018)
    for ws in slots:
        for name in UNSW_NB15_AVAILABLE:
            assert ws.get(name).available, f"{name} must be available"
            assert ws.get(name).source == "unsw_csv"
        for name in ("syn_ratio", "ack_ratio", "fin_ratio", "rst_ratio",
                     "psh_ratio", "iat_std", "retransmission_rate",
                     "payload_size_mean", "burstiness", "iat_max"):
            assert not ws.get(name).available, f"{name} must be unavailable"

    # port-scan bin: 10 distinct destination ports from one source
    assert attack.get("unique_dst_ports").value == 10.0
    assert attack.get("unique_src_ips").value == 1.0
    assert attack.get("flow_count").value == 10.0
    # 49 columns → dst_port_entropy is real Shannon entropy, nonzero
    assert attack.get("dst_port_entropy").value > 0.0

    # labels: dominant original preserved, canonical stage mapped
    assert labels[0].canonical_label == BENIGN
    assert labels[0].dataset_label == "NORMAL"
    assert labels[1].canonical_label == RECONNAISSANCE
    assert labels[1].dataset_label == "Reconnaissance"


def test_slots_feed_the_canonical_sequence_engine(unsw_dir: Path):
    """The whole point of the adapter: its output must drive the ONE
    sequence engine (gap-filled, masked) without any glue code."""
    a = get_adapter("unsw_nb15")
    flows = a.load(a.discover(unsw_dir.parent))
    slots, labels = a.to_window_slots(flows, bin_secs=30)
    seq = make_canonical_sequences(slots, labels, seq_len=1, horizon=1,
                                   bin_secs=30, emit_empty=False)
    assert seq.n_sequences >= 1
    assert seq.X.shape[2] == 48          # canonical width
    # mask reflects availability exactly
    for j, name in enumerate(FEATURE_NAMES):
        assert bool(seq.mask[0, 0, j]) == (name in UNSW_NB15_AVAILABLE), name


def test_tcp_window_restricted_to_tcp_flows(unsw_dir: Path):
    """swin/dwin are 0 for non-TCP flows — the adapter must not average
    those zeros into a fabricated window size."""
    a = get_adapter("unsw_nb15")
    d = unsw_dir
    rows = ([_row(s, proto="udp", swin=0, dwin=0) for s in range(0, 30, 5)]
            + [_row(s, proto="tcp", swin=100, dwin=200) for s in range(0, 30, 5)])
    pd.DataFrame(rows).to_csv(d / "UNSW-NB15_1.csv", header=False, index=False)
    for part in (2, 3, 4):
        pd.DataFrame([]).to_csv(d / f"UNSW-NB15_{part}.csv",
                                header=False, index=False)
    slots, _ = a.to_window_slots(a.load(a.discover(d.parent)), bin_secs=30)
    # only the TCP rows count: (100+200)/2 = 150, not dragged toward 0
    assert slots[0].get("tcp_window_mean").value == pytest.approx(150.0)


def test_metadata(unsw_dir: Path):
    a = get_adapter("unsw_nb15")
    flows = a.load(a.discover(unsw_dir.parent))
    md = a.attack_metadata(flows)
    assert md.n_flows == 20
    assert md.families == {"Reconnaissance": RECONNAISSANCE}
    assert md.label_counts["NORMAL"] == 10


# ------------------------------------------------------- real-file smoke

REAL = Path("data/raw/unsw_nb15/UNSW-NB15_1.csv")


@pytest.mark.skipif(not REAL.exists(), reason="UNSW-NB15 not downloaded")
def test_real_file_smoke():
    """Validate + load a slice of the actual UNSW-NB15_1.csv: the schema,
    benign sentinel, label consistency and canonical record must all hold
    on real bytes, not just the synthetic fixture."""
    a = get_adapter("unsw_nb15")
    assert status("unsw_nb15") == "READY"
    files = a.discover(Path("data/raw"))
    assert len(files) == 4
    rep = a.validate(files)
    assert rep.ok, rep.errors

    flows = a.load([REAL])
    assert len(flows) > 500_000                       # file 1 alone: 700,001 rows
    assert flows["ts"].is_monotonic_increasing          # sorted by Stime
    # real labels observed 2026-09-04: benign + these families
    got = set(flows["dataset_label"].unique())
    assert "NORMAL" in got
    assert got <= {"NORMAL", "Generic", "Exploits", "Fuzzers", "DoS",
                   "Reconnaissance", "Analysis", "Backdoor", "Shellcode",
                   "Backdoors", "Worms"}, got - {"NORMAL"}
    # canonical record sanity on real values
    assert flows["pkts"].sum() > 0
    assert (flows["duration_s"].dropna() >= 0).all()
    # windowing a real 10-minute slice runs and yields honest slots
    sl = flows.iloc[:200_000]
    slots, labels = a.to_window_slots(sl, bin_secs=30)
    assert len(slots) > 50
    assert all(ws.get("unique_dst_ips").available for ws in slots)
    assert any(not ws.get("syn_ratio").available for ws in slots)
    fams = {l.dataset_label for l in labels if l.is_attack}
    assert fams <= {"Generic", "Exploits", "Fuzzers", "DoS", "Reconnaissance",
                    "Analysis", "Backdoor", "Shellcode", "Backdoors", "Worms"}
