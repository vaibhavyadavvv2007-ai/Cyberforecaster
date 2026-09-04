"""Phase 6 tests — world-model state head.

Critical guarantees:
  1. make_world_sequences aligns EXACTLY with make_sequences (same X, same
     labels, same ends) → identical chrono_split → V1/V2 comparable.
  2. WorldModelForecaster is a strict superset: frozen V1 weights load with
     strict=False and produce BYTE-IDENTICAL prog/stage outputs (backward
     compatibility; the demo's V1 path is provably untouched by this change).
  3. state_metrics: perfect prediction scores 1.0 cosine / 0 MAE; degenerate
     features are excluded and the exclusion reported.
  4. end-to-end smoke train on synthetic data (wiring, not reported numbers).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from src.features.scaling import apply_scaler, fit_scaler
from src.features.window_builder import (WINDOW_FEATURES, build_windows,
                                         make_sequences, make_world_sequences)
from src.models.lstm_forecaster import TemporalForecaster
from src.models.world_model import (WorldModelForecaster, state_metrics,
                                    train_world_model)

# golden CIC fixture (2 real bins + 1 skipped bin) from the adapter tests
from tests.test_dataset_adapters import CIC_COLS, _row


@pytest.fixture(scope="module")
def windows_df(tmp_path_factory):
    # 90 minutes → 180 bins → 166 sequences: benign first 30 min, SSH after.
    # (A 70/15/15 chronological split needs every slice ≥ L+K = 15 windows.)
    rows = []
    for m in range(90):
        attack = m >= 30
        for s in range(0, 60, 10):
            rows.append(_row(f"14/02/2018 09:{m:02d}:{s:02d}",
                             "SSH-Brute-Force" if attack else "Benign",
                             port=22 if attack else 443, syn=1 if attack else 0))
    p = tmp_path_factory.mktemp("w") / "g.csv"
    pd.DataFrame(rows, columns=CIC_COLS).to_csv(p, index=False)

    from src.ingestion.csv_loader import load_many
    return build_windows(load_many([p]), bin_secs=30)


# ---------------------------------------------------- alignment with V1 path

def test_world_sequences_align_with_v1(windows_df):
    X, y_prog, y_stage, ends = make_sequences(windows_df)
    X2, Xf, y2_prog, y2_stage, ends2 = make_world_sequences(windows_df)
    assert np.array_equal(X, X2)
    assert np.array_equal(y_prog, y2_prog)
    assert np.array_equal(y_stage, y2_stage)
    assert np.array_equal(ends, ends2)
    # Xf must be the true future windows: sequence i's history is windows
    # [i, i+L), its future target is windows [i+L, i+L+K)
    feats = windows_df[WINDOW_FEATURES].to_numpy(dtype=np.float32)
    L, K = X.shape[1], y_prog.shape[1]
    for i in (0, len(X) // 2, len(X) - 1):
        assert np.array_equal(Xf[i], feats[i + L:i + L + K])
        assert np.array_equal(X[i, -1], feats[i + L - 1])


# ------------------------------------------------------ V1 compatibility

def test_v1_weights_load_and_reproduce_exactly(windows_df):
    """Frozen V1 weights inside WorldModelForecaster → identical prog/stage."""
    torch.manual_seed(0)
    n_feat, L, K = len(WINDOW_FEATURES), 10, 5
    v1 = TemporalForecaster(n_feat, horizon=K).eval()
    v2 = WorldModelForecaster(n_feat, horizon=K).eval()
    missing, unexpected = v2.load_state_dict(v1.state_dict(), strict=False)
    assert unexpected == []                       # nothing foreign
    assert [k for k in missing] == ["state_head.weight", "state_head.bias"]
    x = torch.randn(4, L, n_feat)
    with torch.no_grad():
        p1, s1 = v1(x)
        p2, s2, state = v2(x)
    assert torch.equal(p1, p2) and torch.equal(s1, s2)
    assert state.shape == (4, K, n_feat)


# ------------------------------------------------------------ state metrics

def test_state_metrics_perfect_and_degenerate():
    rng = np.random.default_rng(3)
    true = rng.normal(size=(50, 5, 6))
    names = [f"f{i}" for i in range(6)]
    degenerate = np.array([False] * 5 + [True])   # f5 is dead
    # perfect prediction on live features, garbage on the dead one
    pred = true.copy()
    pred[:, :, 5] = 999.0
    m = state_metrics(pred, true, names, degenerate)
    assert m["cosine_mean"] == pytest.approx(1.0)
    assert max(m["mae_per_horizon"]) == pytest.approx(0.0, abs=1e-9)
    assert m["excluded_degenerate_features"] == ["f5"]
    # zero prediction on a nonzero state: cosine ~0, MAE = E|S|
    m0 = state_metrics(np.zeros_like(true), true, names, degenerate)
    assert m0["cosine_mean"] < 0.05


def test_state_metrics_constant_state_is_honest():
    # predicting the MEAN (a constant) gets cosine ~0 against varied targets —
    # the metric must not reward constant outputs the way MAE alone can
    rng = np.random.default_rng(4)
    true = rng.normal(size=(200, 5, 4))
    m = state_metrics(np.zeros_like(true), true, [f"f{i}" for i in range(4)])
    assert m["cosine_mean"] < 0.05


# ------------------------------------------------------------ smoke training

def test_smoke_train_end_to_end(tmp_path: Path, windows_df):
    """2 epochs on a tiny synthetic dataset: wiring only, never reported."""
    out = tmp_path / "wm"
    out.mkdir()
    windows_df.to_parquet(out / "windows.parquet")
    X, Xf, y, s, e = make_world_sequences(windows_df)
    sc = fit_scaler(X, list(WINDOW_FEATURES))
    np.savez(out / "scaler.npz", **sc)

    payload = train_world_model(out, lambda_state=0.3, state_loss="huber",
                                epochs=2, out_dir=tmp_path / "model")
    assert payload["_state"]["horizon"] == 5
    assert len(payload["_state"]["cosine_per_horizon"]) == 5
    assert (tmp_path / "model" / "world_model.pt").exists()
    assert (tmp_path / "model" / "metrics.json").exists()
