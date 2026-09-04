"""Adapter contract tests + golden synthetic CIC CSV fixture.

The synthetic CSV exercises the real ingestion path (csv_loader →
build_windows → canonical slots) so the adapter can't silently drift from
the audited implementation.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.datasets.base import DatasetNotAvailableError
from src.datasets.registry import get_adapter, registered, status
from src.labels.attack_taxonomy import (BENIGN, INITIAL_ACCESS,
                                        canonicalize)

CIC_COLS = ["Timestamp", "Label", "Dst Port", "Protocol", "Flow Duration",
            "Tot Fwd Pkts", "Tot Bwd Pkts", "TotLen Fwd Pkts",
            "TotLen Bwd Pkts", "Flow IAT Mean", "Flow IAT Std",
            "Pkt Size Avg", "Down/Up Ratio", "FIN Flag Cnt", "SYN Flag Cnt",
            "RST Flag Cnt", "PSH Flag Cnt", "ACK Flag Cnt"]


def _row(ts: str, label: str, port: int = 443, syn: int = 0) -> list:
    return [ts, label, port, 6, 1_000_000, 3, 3, 400, 600, 2_000_000,
            500_000, 100, 1.0, 0, syn, 0, 1, 3]


@pytest.fixture()
def cic_csv(tmp_path: Path) -> Path:
    """Two 30-second bins: benign, then an SSH brute-force burst."""
    rows = (
        [_row(f"14/02/2018 09:00:{s:02d}", "Benign") for s in range(0, 30, 5)]
        + [_row(f"14/02/2018 09:01:{s:02d}", "Benign") for s in range(0, 20, 5)]
        + [_row(f"14/02/2018 09:01:{s:02d}", "SSH-Brute-Force", port=22,
                syn=1) for s in range(20, 30, 2)]
    )
    df = pd.DataFrame(rows, columns=CIC_COLS)
    p = tmp_path / "Wednesday-14-02-2018_TrafficForML_CICFlowMeter.csv"
    df.to_csv(p, index=False)
    return p


# ---------------------------------------------------------------- validation

def test_validate_detects_cic_format(cic_csv: Path):
    a = get_adapter("cic2018")
    rep = a.validate([cic_csv])
    assert rep.ok and rep.detected_format.startswith("CIC-style")
    assert rep.confidence >= 0.7


def test_validate_rejects_foreign_csv(tmp_path: Path):
    p = tmp_path / "other.csv"
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(p, index=False)
    rep = get_adapter("cic2018").validate([p])
    assert not rep.ok


# --------------------------------------------------------------- windows+slots

def test_to_window_slots_availability_and_labels(cic_csv: Path):
    a = get_adapter("cic2018")
    flows = a.load([cic_csv])
    slots, labels = a.to_window_slots(flows, bin_secs=30)

    assert len(slots) == len(labels) == 2          # two 30s bins
    # availability: the CSV's honest capability set, IPs absent
    for ws in slots:
        assert ws.get("flow_count").available
        assert not ws.get("unique_src_ips").available   # no IP columns
        assert not ws.get("unique_dst_ips").available
        assert not ws.get("ttl_mean").available         # no packet data
    # brute-force bin: original label preserved, canonical = INITIAL_ACCESS
    attack = [l for l in labels if l.is_attack]
    assert len(attack) == 1
    assert attack[0].dataset_label == "SSH-Brute-Force"
    assert attack[0].canonical_label == INITIAL_ACCESS
    assert attack[0].mapping_source == "verified"
    assert labels[0].canonical_label == BENIGN


def test_attack_metadata(cic_csv: Path):
    a = get_adapter("cic2018")
    flows = a.load([cic_csv])
    meta = a.attack_metadata(flows)
    assert meta.families == {"SSH-Brute-Force": INITIAL_ACCESS}
    assert meta.label_counts["Benign"] == 10


# ------------------------------------------------------------------ registry

def test_registry_has_all_planned_datasets():
    assert registered() == ["cic2017", "cic2018", "ciciot2023", "ctu13",
                            "darpa", "lanl", "unsw_nb15"]


def test_pending_adapters_refuse_to_load():
    # unsw_nb15 and ctu13 are now REAL adapters (wired 2026-09-04) — they
    # load empty nothing; the remaining unwired datasets must still refuse
    # loudly.
    for did in ("cic2017", "ciciot2023", "darpa", "lanl"):
        a = get_adapter(did)
        with pytest.raises(DatasetNotAvailableError):
            a.load([])


def test_ctu13_adapter_refuses_empty_file_list():
    """The wired adapter must not pretend an empty download is data."""
    with pytest.raises(ValueError):
        get_adapter("ctu13").load([])


def test_unsw_adapter_refuses_empty_file_list():
    """The wired adapter must not pretend an empty download is data."""
    a = get_adapter("unsw_nb15")
    assert a.discover(Path("nonexistent-root")) == []
    with pytest.raises(ValueError):
        a.load([])


def test_status_unknown_dataset_is_not_downloaded(tmp_path: Path):
    assert status("cic2017", tmp_path) == "NOT_DOWNLOADED"


# ------------------------------------------------------------------ taxonomy

def test_taxonomy_preserves_original_and_maps_verified():
    r = canonicalize("cic2018", "DDoS-LOIC")
    assert r.canonical_label == "IMPACT" and r.dataset_label == "DDoS-LOIC"
    r = canonicalize("cic2018", "Weird-New-Attack")
    assert r.canonical_label == "UNKNOWN_ATTACK"    # never guessed
