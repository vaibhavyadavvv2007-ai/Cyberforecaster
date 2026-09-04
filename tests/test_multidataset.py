"""Phase 7/8 — multi-dataset training artifacts (fast, NO training).

Covers:
  - the 9-feature intersection really is the 3-way DATASET_CAPABILITIES
    intersection of the legacy 18 (the plan draft said 11; CIC2018's ML CSVs
    ship no IP columns — this test freezes the honest number)
  - windows_<dataset>.parquet schema matches the frozen windows.parquet
    convention (attack_frac fraction semantics, dominant_stage_idx -1 =
    benign, 6 frac_ columns, split column present)
  - sequence formation never spans a split/scenario boundary
  - metrics_cross_dataset.json row structure (skip if not yet built)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.features.canonical_schema import DATASET_CAPABILITIES
from src.features.window_builder import WINDOW_FEATURES

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data/processed"

INTERSECTION = [
    "flow_count", "bytes_total", "pkts_total", "duration_mean",
    "avg_pkt_size", "unique_dst_ports", "dst_port_entropy",
    "down_up_ratio", "auth_port_share",
]


def test_intersection_is_honest_three_way():
    """The shared feature space must be exactly the verified 3-way overlap."""
    inter = set(WINDOW_FEATURES)
    for did in ("cic2018", "unsw_nb15", "ctu13"):
        inter &= DATASET_CAPABILITIES[did]
    assert sorted(inter) == sorted(INTERSECTION)
    # the plan's draft 11 included IP-count features CIC2018 cannot provide
    assert "unique_src_ips" not in INTERSECTION
    assert "unique_dst_ips" not in INTERSECTION


@pytest.mark.parametrize("dataset_id", ["unsw_nb15", "ctu13"])
def test_windows_parquet_schema(dataset_id: str):
    p = PROC / f"windows_{dataset_id}.parquet"
    if not p.exists():
        pytest.skip(f"{p.name} not built yet — run "
                    f"scripts/build_dataset_windows.py --dataset {dataset_id}")
    w = pd.read_parquet(p)
    # frozen windows.parquet convention: 18 features + supervision columns
    for c in WINDOW_FEATURES + ["attack_frac", "dominant_stage_idx", "split"]:
        assert c in w.columns, f"missing column {c}"
    for st in ("Reconnaissance", "Initial Access", "Lateral Movement",
               "Command & Control", "Exfiltration", "DoS"):
        assert f"frac_{st}" in w.columns
    # attack_frac is a FRACTION of flows, not a dominant-label binarisation
    assert ((w["attack_frac"] >= 0) & (w["attack_frac"] <= 1)).all()
    # benign bins carry -1; staged bins are valid 6-stage indices
    dom = w["dominant_stage_idx"]
    assert (dom >= -1).all() and (dom <= 5).all()
    assert ((w["attack_frac"] == 0) | (dom >= 0) | (dom == -1)).all()
    assert set(w["split"].unique()) <= {"train", "val", "test"}
    # every row has a split — sequence formation depends on it
    assert w["split"].notna().all()
    # unavailable features are NaN, never silently zero-filled
    unavail = set(WINDOW_FEATURES) - DATASET_CAPABILITIES[dataset_id]
    for f in unavail:
        assert w[f].isna().all(), f"{f} unavailable from {dataset_id} " \
                                  f"but carries values — fabrication"


@pytest.mark.parametrize("dataset_id", ["unsw_nb15", "ctu13"])
def test_splits_are_chronological(dataset_id: str):
    p = PROC / f"windows_{dataset_id}.parquet"
    if not p.exists():
        pytest.skip(f"{p.name} not built yet")
    w = pd.read_parquet(p).sort_index()
    codes = w["split"].map({"train": 0, "val": 1, "test": 2}).to_numpy()
    # per scenario (CTU-13) or globally: split codes never go backwards
    scen = (w["scenario"].to_numpy() if "scenario" in w.columns
            else np.zeros(len(w)))
    for s in np.unique(scen):
        c = codes[scen == s]
        assert (np.diff(c) >= 0).all(), \
            f"{dataset_id} scenario {s}: split order is not chronological"


def test_sequences_never_span_boundaries():
    """Synthetic windows -> the trainer's run logic must not emit sequences
    that cross a split or scenario boundary."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from train_multidataset import _sequences_from_parquet

    n = 40
    idx = pd.date_range("2026-01-01", periods=n, freq="30s")
    w = pd.DataFrame({
        "scenario": [1] * 20 + [2] * 20,
        "flow_count": np.arange(n, dtype=float),
    }, index=idx)
    # each scenario: 14 train / 3 val / 3 test — runs are short on purpose
    w["split"] = (["train"] * 14 + ["val"] * 3 + ["test"] * 3) * 2
    for c in WINDOW_FEATURES:
        if c not in w:
            w[c] = 1.0
    w["attack_frac"] = np.linspace(0, 0.5, n)
    w["dominant_stage_idx"] = 1

    seqs = _sequences_from_parquet(w, INTERSECTION)
    for split, (X, y, s) in seqs.items():
        assert X.shape[1:] == (10, len(INTERSECTION))
        assert y.shape[1] == 5
        # each run is 14/3/3 windows -> train 0, val 0, test 0 sequences
        # (14 < L+K-1 = 14 means exactly 14-10-5+1 = 0)... use 20-window
        # runs instead for the real assertion below
    # rerun with runs long enough to form sequences
    w2 = pd.DataFrame({
        "scenario": [1] * 30 + [2] * 30,
    }, index=pd.date_range("2026-01-01", periods=60, freq="30s"))
    w2["split"] = (["train"] * 25 + ["val"] * 3 + ["test"] * 2) * 2
    for c in WINDOW_FEATURES:
        w2[c] = 1.0
    w2["flow_count"] = np.arange(60, dtype=float)
    w2["attack_frac"] = 0.0
    w2.loc[w2.index[:5], "attack_frac"] = 0.5   # attack only in scenario-1 head
    w2["dominant_stage_idx"] = np.where(w2["attack_frac"] > 0, 1, -1)

    seqs = _sequences_from_parquet(w2, INTERSECTION)
    # 25-window train runs -> 25-10-5+1 = 11 sequences each; val 3 and
    # test 2 windows are too short to form any sequence
    assert len(seqs["train"][0]) == 22          # 11 per scenario
    assert len(seqs["val"][0]) == 0
    assert len(seqs["test"][0]) == 0
    # train sequences come only from within-run windows: every sequence's
    # 10-step history must be flow_count-contiguous within one run
    X = seqs["train"][0]
    for seq in X:
        diffs = np.diff(seq[:, INTERSECTION.index("flow_count")])
        assert (diffs == 1).all(), "sequence spans a run boundary"


def test_metrics_cross_dataset_structure():
    p = ROOT / "models/metrics_cross_dataset.json"
    if not p.exists():
        pytest.skip("models/metrics_cross_dataset.json not written yet — "
                    "run scripts/train_multidataset.py")
    reg = json.loads(p.read_text(encoding="utf-8"))
    assert "runs" in reg and "features" in reg
    assert sorted(reg["features"]) == sorted(INTERSECTION)
    for row in reg["runs"]:
        assert {"experiment", "trained_on", "tested_on"} <= set(row)
        # every row either carries full metrics or an honest error key —
        # never silent zeros
        if "error" not in row:
            for k in ("pr_auc", "precision", "recall", "fpr"):
                assert k in row, f"{row['experiment']}/{row['tested_on']} missing {k}"
                assert row[k] is not None


def test_api_metrics_namespacing():
    """models/metrics_*.json files surface under their stem in /api/metrics
    (api/state._load_metrics) — cross_dataset must not collide with existing
    keys like lstm."""
    from api.state import _load_metrics
    merged = _load_metrics()
    if (ROOT / "models/metrics_cross_dataset.json").exists():
        assert "cross_dataset" in merged
    assert "lstm" in merged or "baseline" in merged or not merged
