"""Phase 9 tests — evidence, temporal WHY, uncertainty, calibration."""
from __future__ import annotations

import numpy as np
import pytest

from src.explainability.calibration import (brier_score,
                                            calibration_report,
                                            expected_calibration_error,
                                            reliability_curve)
from src.explainability.evidence import EvidenceEngine
from src.explainability.temporal import temporal_why, window_labels
from src.explainability.uncertainty import confidence_band, mc_dropout_forecast
from src.features.window_builder import WINDOW_FEATURES


# ----------------------------------------------------------------- evidence

BASELINE = {
    f: {"mean": 10.0, "std": 2.0, "p99": 15.0} for f in WINDOW_FEATURES
} | {"_n_benign_windows": 100}


def test_evidence_z_and_direction():
    eng = EvidenceEngine(BASELINE)
    x = np.full((10, len(WINDOW_FEATURES)), 10.0)   # exactly benign mean
    x[-1, 0] = 16.0                                  # flow_count: z = +3
    x[-1, 1] = 4.0                                   # bytes_total: z = -3
    attrs = np.zeros(len(WINDOW_FEATURES))
    attrs[0], attrs[1] = 0.9, 0.4
    ev = eng.explain(x, attrs)
    by = {e["feature"]: e for e in ev}
    fc = by["flow_count"]
    assert fc["z"] == pytest.approx(3.0)
    assert fc["direction"] == "elevated"
    assert fc["contribution"] == pytest.approx(0.9)  # attr * sign(z)
    assert by["bytes_total"]["direction"] == "suppressed"
    assert by["bytes_total"]["contribution"] == pytest.approx(-0.4)
    # ranked by |attribution|
    assert ev[0]["feature"] == "flow_count"


def test_evidence_normal_and_zero_std_make_no_claim():
    base = {f: {"mean": 5.0, "std": 0.0, "p99": 5.0} for f in WINDOW_FEATURES}
    eng = EvidenceEngine(base)
    x = np.full((10, len(WINDOW_FEATURES)), 7.0)
    ev = eng.explain(x, np.ones(len(WINDOW_FEATURES)))
    assert ev == []                       # std 0 → no honest claim possible

    base2 = {f: {"mean": 5.0, "std": 1.0, "p99": 8.0} for f in WINDOW_FEATURES}
    eng2 = EvidenceEngine(base2)
    ev2 = eng2.explain(np.full((10, len(WINDOW_FEATURES)), 5.5),
                       np.ones(len(WINDOW_FEATURES)))
    assert all(e["direction"] == "normal" for e in ev2)   # |z| = 0.5 < 2


def test_evidence_uses_last_window_not_history_mean():
    eng = EvidenceEngine(BASELINE)
    x = np.full((10, len(WINDOW_FEATURES)), 10.0)
    x[-1, 0] = 20.0                       # only NOW deviates
    ev = eng.explain(x, np.ones(len(WINDOW_FEATURES)))
    by = {e["feature"]: e for e in ev}
    assert by["flow_count"]["z"] == pytest.approx(5.0)


# ---------------------------------------------------------------- temporal

def test_temporal_why_labels_and_shares():
    L, F = 10, len(WINDOW_FEATURES)
    assert window_labels(L)[0] == "W-9" and window_labels(L)[-1] == "W-0"
    x = np.abs(np.random.default_rng(0).normal(size=(L, F)))
    attrs = np.zeros((L, F))
    attrs[3, 0] = 1.0                     # all importance in W-6
    t = temporal_why(x, attrs, WINDOW_FEATURES)
    assert t["timeline"][3]["label"] == "W-6"
    assert t["timeline"][3]["share"] == pytest.approx(1.0)
    assert all(w["share"] == pytest.approx(0.0) for i, w in enumerate(t["timeline"])
               if i != 3)
    assert t["top_features"][0]["feature"] == WINDOW_FEATURES[0]


def test_temporal_trend_direction():
    L, F = 10, len(WINDOW_FEATURES)
    x = np.zeros((L, F))
    x[:, 0] = np.linspace(1, 50, L)       # rising toward NOW
    attrs = np.zeros((L, F))
    attrs[:, 0] = 1.0
    t = temporal_why(x, attrs, WINDOW_FEATURES)
    assert t["trend"]["feature"] == WINDOW_FEATURES[0]
    assert t["trend"]["direction"] == "rising"


# -------------------------------------------------------------- uncertainty

def test_mc_dropout_deterministic_and_banded():
    torch = pytest.importorskip("torch")
    from src.models.lstm_forecaster import TemporalForecaster
    torch.manual_seed(0)
    model = TemporalForecaster(len(WINDOW_FEATURES), horizon=5).eval()
    x = np.random.default_rng(1).normal(size=(10, len(WINDOW_FEATURES))) \
        .astype(np.float32)
    r1 = mc_dropout_forecast(model, x, T=16, seed=7)
    r2 = mc_dropout_forecast(model, x, T=16, seed=7)
    assert r1["probs_mean"] == r2["probs_mean"] and r1["probs_std"] == r2["probs_std"]
    assert len(r1["probs_mean"]) == 5 and r1["T"] == 16
    assert r1["confidence"] in ("HIGH", "MEDIUM", "LOW")
    # std is non-negative and bounded
    assert all(0 <= s for s in r1["probs_std"])
    # model restored to eval afterwards
    assert not model.training
    for m in model.modules():
        import torch.nn as nn
        if isinstance(m, nn.Dropout):
            assert not m.training


def test_confidence_bands():
    assert confidence_band(0.01) == "HIGH"
    assert confidence_band(0.10) == "MEDIUM"
    assert confidence_band(0.30) == "LOW"


# -------------------------------------------------------------- calibration

def test_perfectly_calibrated_zero_ece():
    rng = np.random.default_rng(2)
    p = rng.uniform(0, 1, 20000)
    y = (rng.uniform(0, 1, 20000) < p).astype(float)   # y ~ Bernoulli(p)
    assert expected_calibration_error(y, p) < 0.02
    assert brier_score(y, p) < 0.30                    # ~0.25 + estimation noise


def test_miscalibrated_detected():
    p = np.full(400, 0.9)
    y = np.zeros(400)                                  # claims 0.9, truth 0
    assert brier_score(y, p) == pytest.approx(0.81)
    assert expected_calibration_error(y, p) == pytest.approx(0.9)


def test_reliability_curve_bins_cover_everything():
    p = np.array([0.0, 0.05, 0.15, 0.5, 0.95, 1.0])
    y = np.array([0, 0, 1, 1, 1, 1])
    rel = reliability_curve(y, p, n_bins=10)
    counts = [b["count"] for b in rel]
    assert sum(counts) == len(p)                       # every point in a bin
    assert rel[0]["count"] == 2 and rel[-1]["count"] == 2
    rep = calibration_report(y, p)
    assert rep["n"] == 6 and "brier" in rep and "ece" in rep
