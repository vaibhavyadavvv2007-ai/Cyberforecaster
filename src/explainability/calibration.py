"""Calibration — does a 0.7 forecast mean "70% chance"?

A forecaster can have great ranking (AP) and still be badly calibrated (all
its probabilities systematically too high or too low). For a decision-support
system that routes alerts by predicted probability, calibration is not a
nicety — an analyst triaging "0.9" alerts that are right 40% of the time is
worse off than one with honest 0.4s.

Metrics (all on the TEST split, the frozen V1 protocol):
  brier     mean (p - y)^2 — 0 perfect, 0.25 = coin flip at 50/50 base rate
  ece       expected calibration error: Σ (bin share) × |bin accuracy − bin
            mean prob| over equal-width probability bins
  reliability  per-bin (mean prob, empirical accuracy, count) — the
            reliability-diagram data, for the benchmarks page

Per horizon step AND pooled over steps (forecast trajectory = K claims).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def brier_score(y: np.ndarray, p: np.ndarray) -> float:
    y, p = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    return float(((p - y) ** 2).mean())


def reliability_curve(y: np.ndarray, p: np.ndarray, n_bins: int = 10):
    """Equal-width bins over [0,1] → [(mean_p, accuracy, count), ...]."""
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi) if hi < 1 else (p >= lo) & (p <= hi)
        if mask.sum() == 0:
            out.append({"bin": round(lo, 2), "mean_p": None,
                        "accuracy": None, "count": 0})
            continue
        out.append({
            "bin": round(float(lo), 2),
            "mean_p": round(float(p[mask].mean()), 4),
            "accuracy": round(float(y[mask].mean()), 4),
            "count": int(mask.sum()),
        })
    return out


def expected_calibration_error(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece, n = 0.0, len(p)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi) if hi < 1 else (p >= lo) & (p <= hi)
        if mask.sum() == 0:
            continue
        ece += mask.sum() / n * abs(y[mask].mean() - p[mask].mean())
    return float(ece)


def calibration_report(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> dict:
    return {
        "n": int(len(y)),
        "brier": round(brier_score(y, p), 4),
        "ece": round(expected_calibration_error(y, p, n_bins), 4),
        "reliability": reliability_curve(y, p, n_bins),
    }


# ------------------------------------------------------------------ CLI

def evaluate_frozen_model(npz_dir: Path, target_step: int | None = None) -> dict:
    """Calibration of the frozen V1 model on its own test split.

    Pooled over all K horizon steps (each (sequence, step) pair is one
    probability claim), plus per-step reports. Uses the same loader/predict
    helpers as training — no third inference path.
    """
    import torch
    from ..features.scaling import load_scaler, apply_scaler
    from ..models.lstm_forecaster import TemporalForecaster, _predict

    sc = load_scaler(npz_dir / "scaler.npz")
    d = np.load(npz_dir / "sequences_test.npz", allow_pickle=False)
    X = apply_scaler(d["X"], sc)
    y = d["y_prog"]                                   # (n, K) per-step truth
    cfg = json.loads((Path("models") / "trained_models" / "lstm_config.json")
                     .read_text(encoding="utf-8"))
    model = TemporalForecaster(cfg["n_feat"], horizon=cfg["horizon"],
                               hidden=cfg.get("hidden", 64),
                               layers=cfg.get("layers", 2))
    model.load_state_dict(torch.load(Path("models") / "trained_models"
                                     / "lstm_forecaster.pt",
                                     map_location="cpu", weights_only=True))
    model.eval()
    p = _predict(model, torch.from_numpy(X).float(), "cpu")   # (n, K)

    K = y.shape[1]
    report = {
        "model": "cic2018_v1 (frozen)",
        "pooled": calibration_report(y.ravel(), p.ravel()),
        "per_step": [calibration_report(y[:, k], p[:, k]) for k in range(K)],
    }
    if target_step is not None:
        report["target_step"] = calibration_report(y[:, target_step],
                                                   p[:, target_step])
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--out", type=Path, default=Path("models/calibration_v1.json"))
    a = ap.parse_args()
    rep = evaluate_frozen_model(a.dir)
    a.out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(f"pooled: brier={rep['pooled']['brier']} ece={rep['pooled']['ece']} "
          f"n={rep['pooled']['n']} -> {a.out}")
