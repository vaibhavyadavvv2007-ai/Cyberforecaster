"""Early-warning lead time — the metric that actually distinguishes a forecaster.

Battle plan §6 names this as the pivot if the LSTM only ties the baseline on F1:
a temporal model's value is not that it is more accurate on a static snapshot,
it is that it crosses the alert threshold EARLIER. This module measures that.

Definition
----------
A sequence anchored at window `a` (its last input window) predicts windows
a+1 … a+K. So window `w` is forecast by K different sequences, at horizon
distances j = 1 … K.

An *onset* is a window with attack activity whose predecessor had none — the
moment a static detector would first have something to see.

    lead_time(onset w) = max { j : the sequence anchored at w-j assigned
                                    probability >= threshold to step j }

i.e. the earliest horizon distance at which the model was already warning.
0 means no warning fired before onset. Reported in windows and in minutes
(1 window = `bin_secs`, 30s by default — src.config.BIN_SECS).

Usage:
  python -m src.evaluation.lead_time --dir data/processed
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..config import BIN_SECS


def reconstruct_window_labels(ends: np.ndarray, y_prog: np.ndarray,
                              horizon: int) -> dict[int, int]:
    """Absolute window index → 1 if that window contains attack activity.

    Derived from the per-step labels themselves, so this needs no parquet read
    and cannot drift from what the model was trained against.
    """
    anchors = ends - horizon - 1
    attack: dict[int, int] = {}
    for i, a in enumerate(anchors):
        for k in range(horizon):
            w = int(a) + 1 + k
            attack[w] = max(attack.get(w, 0), int(y_prog[i, k]))
    return attack


def find_onsets(attack: dict[int, int]) -> list[int]:
    """Windows where attack activity begins (previous window observed as clean).

    `w - 1 in attack` is required, not merely falsy: at the split boundary the
    earliest covered window has no observed predecessor, and defaulting it to
    "clean" would count a mid-attack window as a fresh onset and inflate the
    denominator.
    """
    return sorted(w for w, v in attack.items()
                  if v == 1 and (w - 1) in attack and attack[w - 1] == 0)


def lead_times(ends: np.ndarray, proba: np.ndarray, y_prog: np.ndarray,
               horizon: int, threshold: float) -> dict:
    """Lead-time distribution over all onsets in this split."""
    anchors = (ends - horizon - 1).astype(int)
    idx_of_anchor = {int(a): i for i, a in enumerate(anchors)}
    attack = reconstruct_window_labels(ends, y_prog, horizon)
    onsets = find_onsets(attack)

    leads: list[int] = []
    for w in onsets:
        lead = 0
        for j in range(1, horizon + 1):
            i = idx_of_anchor.get(w - j)
            if i is not None and proba[i, j - 1] >= threshold:
                lead = j                      # keep the largest j that warned
        leads.append(lead)

    arr = np.array(leads, dtype=float)
    warned = arr > 0
    return {
        "n_onsets": int(len(arr)),
        "n_warned": int(warned.sum()),
        "warned_rate": float(warned.mean()) if len(arr) else 0.0,
        # distribution over onsets we DID warn about — the honest headline
        "median_lead_windows": float(np.median(arr[warned])) if warned.any() else 0.0,
        "mean_lead_windows": float(arr[warned].mean()) if warned.any() else 0.0,
        "max_lead_windows": float(arr.max()) if len(arr) else 0.0,
        "threshold": float(threshold),
        "_leads": [int(v) for v in arr],
    }


def to_minutes(stats: dict, bin_secs: int = BIN_SECS) -> dict:
    m = bin_secs / 60.0
    return {**stats,
            "median_lead_min": round(stats["median_lead_windows"] * m, 2),
            "mean_lead_min": round(stats["mean_lead_windows"] * m, 2),
            "max_lead_min": round(stats["max_lead_windows"] * m, 2)}


def _report(name: str, s: dict) -> None:
    print(f"\n{name}")
    print(f"  onsets in this split     : {s['n_onsets']}")
    print(f"  warned before onset       : {s['n_warned']} ({s['warned_rate']:.1%})")
    print(f"  median lead (when warned) : {s['median_lead_windows']:.1f} windows "
          f"= {s['median_lead_min']:.1f} min")
    print(f"  mean lead   (when warned) : {s['mean_lead_windows']:.1f} windows "
          f"= {s['mean_lead_min']:.1f} min")
    print(f"  max lead                  : {s['max_lead_windows']:.0f} windows "
          f"= {s['max_lead_min']:.1f} min")


def main(npz_dir: Path, bin_secs: int = BIN_SECS,
         out_json: Path | None = None) -> dict:
    from ..features.scaling import apply_scaler, load_scaler
    from ..features.window_builder import horizon_any
    from ..models.baseline_logreg import pick_threshold

    d_tr = np.load(npz_dir / "sequences_train.npz", allow_pickle=False)
    d_va = np.load(npz_dir / "sequences_val.npz", allow_pickle=False)
    d_te = np.load(npz_dir / "sequences_test.npz", allow_pickle=False)
    if "ends" not in d_te.files:
        raise SystemExit("sequences_test.npz has no `ends` — re-run the pipeline "
                         "(python -m src.preprocessing.pipeline)")
    sc = load_scaler(npz_dir / "scaler.npz")
    horizon = int(d_te["horizon"]) if "horizon" in d_te.files else d_te["y_prog"].shape[1]
    results: dict[str, dict] = {}

    # ---- logistic baseline (same transform, one model per horizon step) ----
    from sklearn.linear_model import LogisticRegression
    flat = lambda D: apply_scaler(D["X"], sc).reshape(len(D["X"]), -1)
    Xtr, Xva, Xte = flat(d_tr), flat(d_va), flat(d_te)
    ytr, yva = d_tr["y_prog"], d_va["y_prog"]
    p_va = np.zeros((len(Xva), horizon))
    p_te = np.zeros((len(Xte), horizon))
    for k in range(horizon):
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(Xtr, ytr[:, k].astype(int))
        p_va[:, k] = clf.predict_proba(Xva)[:, 1]
        p_te[:, k] = clf.predict_proba(Xte)[:, 1]
    thr_lr = pick_threshold(horizon_any(yva), p_va.max(axis=1))
    results["logistic_baseline"] = to_minutes(
        lead_times(d_te["ends"], p_te, d_te["y_prog"], horizon, thr_lr), bin_secs)
    _report("Logistic baseline (test split)", results["logistic_baseline"])
    # The test split can hold as few as ONE onset (a single continuous attack
    # day), which makes the headline metric statistically empty. The val split
    # carries more onsets, so we report it too — clearly labelled, because the
    # operating point (thr) was selected on val and is therefore optimistic.
    results["logistic_baseline_val"] = to_minutes(
        lead_times(d_va["ends"], p_va, d_va["y_prog"], horizon, thr_lr), bin_secs)
    _report("Logistic baseline (val split - thr picked here, optimistic)",
            results["logistic_baseline_val"])

    # ---- LSTM ----
    try:
        import torch
        from ..forecasting.rollout import load_model
        model, cfg = load_model()
        if model is None:
            raise RuntimeError(cfg)
        thr_lstm = float(cfg.get("threshold", 0.5))
        with torch.no_grad():
            Xt = torch.from_numpy(apply_scaler(d_te["X"], sc)).float()
            p = torch.sigmoid(model(Xt)[0]).numpy()
            Xv = torch.from_numpy(apply_scaler(d_va["X"], sc)).float()
            pv = torch.sigmoid(model(Xv)[0]).numpy()
        results["lstm_forecaster"] = to_minutes(
            lead_times(d_te["ends"], p, d_te["y_prog"], horizon, thr_lstm), bin_secs)
        _report("LSTM forecaster (test split)", results["lstm_forecaster"])
        results["lstm_forecaster_val"] = to_minutes(
            lead_times(d_va["ends"], pv, d_va["y_prog"], horizon, thr_lstm), bin_secs)
        _report("LSTM forecaster (val split - thr picked here, optimistic)",
                results["lstm_forecaster_val"])

        a = results["lstm_forecaster"]["median_lead_min"]
        b = results["logistic_baseline"]["median_lead_min"]
        print(f"\n>>> LEAD-TIME DELTA: LSTM {a:.1f} min vs logistic {b:.1f} min "
              f"({a - b:+.1f} min)")
        print("    This is the slide. If F1 ties, this is why the temporal model matters.")
    except Exception as exc:  # noqa: BLE001 — baseline result is still useful alone
        print(f"\n[LSTM lead-time skipped: {exc}]")

    out_json = out_json or (Path("models") / "metrics_lead_time.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {out_json}")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--bin-secs", type=int, default=BIN_SECS)
    a = ap.parse_args()
    main(a.dir, a.bin_secs)
