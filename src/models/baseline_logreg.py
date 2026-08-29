"""PS-required benchmark: logistic regression on flattened sequence features.

Same information, same transform, same split as every model in the ladder —
that's what makes the comparison meaningful. One logistic model per horizon step
so the baseline produces a K-step trajectory exactly like the LSTM does; a
single model predicting "attack anywhere in the horizon" would not be comparable.

Reports per-step and aggregate precision/recall/F1/FPR/PR-AUC and writes a
metrics JSON the Streamlit Benchmark tab reads.

Usage:
  python -m src.models.baseline_logreg --dir data/processed
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_curve)

from ..features.scaling import apply_scaler, load_scaler
from ..features.window_builder import horizon_any

# SOC-facing constraint: an analyst cannot triage a detector that fires on 29%
# of benign windows. We pick the operating point on VALIDATION subject to this
# ceiling and report it in the deck — a stated constraint beats an arbitrary 0.5.
MAX_FPR = 0.05


def _load(split_dir: Path, name: str):
    d = np.load(split_dir / f"sequences_{name}.npz", allow_pickle=False)
    return d["X"], d["y_prog"]


def evaluate(y_true: np.ndarray, proba: np.ndarray, threshold: float = 0.5) -> dict:
    """Binary metrics at a given threshold. y_true/proba are 1-D."""
    y_true = np.asarray(y_true).astype(int).ravel()
    proba = np.asarray(proba).ravel()
    pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "fpr": float(fp / max(fp + tn, 1)),
        "pr_auc": float(average_precision_score(y_true, proba)) if y_true.sum() > 0 else 0.0,
        "threshold": float(threshold),
    }


def pick_threshold(y_true: np.ndarray, proba: np.ndarray, max_fpr: float = MAX_FPR) -> float:
    """Highest-recall threshold whose FPR stays within `max_fpr`, chosen on VAL.

    Never call this on the test split — that is threshold-fitting on the test
    set and inflates every number downstream.
    """
    y_true = np.asarray(y_true).astype(int).ravel()
    proba = np.asarray(proba).ravel()
    if y_true.sum() == 0 or y_true.sum() == len(y_true):
        return 0.5
    fpr, tpr, thr = roc_curve(y_true, proba)
    admissible = fpr <= max_fpr
    if not admissible.any():
        idx = int(np.argmin(fpr))
    else:
        idx = int(np.argmax(np.where(admissible, tpr, -1.0)))
    t = float(thr[idx])
    if not np.isfinite(t):                      # roc_curve emits inf as thr[0]
        t = 1.0
    return float(min(max(t, 0.0), 1.0))


def report(name: str, agg: dict, per_step: list[dict]) -> None:
    print(f"\n{name} - chronological test split, threshold={agg['threshold']:.3f} "
          f"(picked on val at FPR<={MAX_FPR:.0%}):")
    print("  aggregate (attack anywhere in horizon):")
    for k, v in agg.items():
        print(f"    {k:<10} {v:.4f}")
    print("  per horizon step:")
    print(f"    {'step':<6}{'prec':>8}{'recall':>8}{'f1':>8}{'fpr':>8}{'pr_auc':>8}")
    for i, m in enumerate(per_step, start=1):
        print(f"    t+{i:<4}{m['precision']:>8.3f}{m['recall']:>8.3f}"
              f"{m['f1']:>8.3f}{m['fpr']:>8.3f}{m['pr_auc']:>8.3f}")
    print("\nNOTE: report these numbers exactly as produced. Never hand-edit.")


def main(npz_dir: Path, out_json: Path | None = None) -> dict:
    X_tr, y_tr = _load(npz_dir, "train")
    X_va, y_va = _load(npz_dir, "val")
    X_te, y_te = _load(npz_dir, "test")
    sc = load_scaler(npz_dir / "scaler.npz")

    def flat(X):
        return apply_scaler(X, sc).reshape(len(X), -1)

    Xtr, Xva, Xte = flat(X_tr), flat(X_va), flat(X_te)
    K = y_tr.shape[1]
    print(f"logistic baseline: {len(Xtr)} train x {Xtr.shape[1]} flat features, K={K}")

    p_va = np.zeros((len(Xva), K), dtype=np.float64)
    p_te = np.zeros((len(Xte), K), dtype=np.float64)
    for k in range(K):
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(Xtr, y_tr[:, k].astype(int))
        p_va[:, k] = clf.predict_proba(Xva)[:, 1]
        p_te[:, k] = clf.predict_proba(Xte)[:, 1]

    # one threshold for the whole model, chosen on the aggregate val task
    thr = pick_threshold(horizon_any(y_va), p_va.max(axis=1))
    agg = evaluate(horizon_any(y_te), p_te.max(axis=1), thr)
    per_step = [evaluate(y_te[:, k], p_te[:, k], thr) for k in range(K)]
    report("Logistic Regression baseline", agg, per_step)

    payload = {**agg, "_per_step": per_step, "_n_train": int(len(Xtr)),
               "_n_test": int(len(Xte)), "_max_fpr": MAX_FPR}
    out_json = out_json or (Path("models") / "metrics_baseline.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"logistic_baseline": payload}, indent=2),
                        encoding="utf-8")
    print(f"wrote {out_json}")
    return agg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    a = ap.parse_args()
    main(a.dir)
