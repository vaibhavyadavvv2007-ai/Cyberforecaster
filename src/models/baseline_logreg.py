"""PS-required benchmark: logistic regression on flattened sequence features.

Same information available to every model in the ladder — that's what makes the
comparison meaningful. Reports precision/recall/F1/FPR and writes a metrics JSON
the Streamlit app's Benchmark tab reads.

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
                             precision_score, recall_score)
from sklearn.preprocessing import StandardScaler


def _load(split_dir: Path, name: str):
    d = np.load(split_dir / f"sequences_{name}.npz", allow_pickle=False)
    return d["X"], d["y_prog"]


def evaluate(y_true: np.ndarray, proba: np.ndarray, threshold: float = 0.5) -> dict:
    pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true.astype(int), pred, labels=[0, 1]).ravel()
    return {
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "fpr": float(fp / max(fp + tn, 1)),
        "pr_auc": float(average_precision_score(y_true, proba)) if y_true.sum() > 0 else 0.0,
        "threshold": threshold,
    }


def main(npz_dir: Path, out_json: Path | None = None) -> dict:
    X_tr, y_tr = _load(npz_dir, "train")
    X_te, y_te = _load(npz_dir, "test")
    n, L, F = X_tr.shape
    Xtr, Xte = X_tr.reshape(n, -1), X_te.reshape(len(X_te), -1)

    scaler = StandardScaler().fit(Xtr)
    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    clf.fit(scaler.transform(Xtr), y_tr.astype(int))

    proba = clf.predict_proba(scaler.transform(Xte))[:, 1]
    metrics = evaluate(y_te, proba)

    print(f"\nLogistic Regression baseline ({n}→{L}×{F}) — test split, chronological:")
    for k, v in metrics.items():
        print(f"  {k:<10} {v:.4f}" if isinstance(v, float) else f"  {k:<10} {v}")
    print("\nNOTE: report these numbers exactly as produced. Never hand-edit.")

    out_json = out_json or (Path("models") / "metrics_baseline.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"logistic_baseline": metrics}, indent=2), encoding="utf-8")
    print(f"wrote {out_json}")
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    a = ap.parse_args()
    main(a.dir)
