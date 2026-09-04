"""Evidence engine — WHY this alert, with numbers a judge can check.

Every evidence line is a fully-determined record:
  observed   the feature's actual value in the most recent window (raw units)
  baseline   what BENIGN traffic looks like (mean + p99 from the TRAIN split
             only — computing baselines on test/val data would leak)
  deviation  z = (observed − benign_mean) / benign_std  (std 0 → no claim)
  direction  elevated / suppressed / normal (|z| < 2)
  attribution IntegratedGradients importance for this prediction (already
             computed by explainability.attribution; passed in, never guessed)
  contribution = attribution × direction-sign, so a feature can only be
             positive evidence for THIS alert if the model used it AND the
             traffic deviates from benign in the direction the model expects

No LLM anywhere in this path (plan rule 8): the strings here are templates
filled with real numbers, not generated prose.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .attribution import integrated_gradients_attribution
from ..features.canonical_schema import FEATURE_INDEX
from ..features.window_builder import WINDOW_FEATURES, make_sequences, chrono_split

Z_NORMAL = 2.0        # |z| below this = "within benign range" (no claim)


def benign_baseline(windows: pd.DataFrame) -> dict:
    """Per-feature benign stats from the TRAIN split only.

    Splits come from the SAME chrono_split as model training, so the baseline
    can never have seen the val/test windows. Benign = attack_frac == 0.
    """
    _, _, _, ends = make_sequences(windows)
    tr, _, _ = chrono_split(windows, ends)
    train_bins = windows.index[: max(ends[tr]) if len(tr) else 0]
    sub = windows.loc[train_bins]
    benign = sub[sub["attack_frac"] == 0]
    if not len(benign):
        raise ValueError("no benign windows in the train split — baseline undefined")
    stats = {}
    for f in WINDOW_FEATURES:
        v = benign[f].to_numpy(dtype=np.float64)
        stats[f] = {"mean": float(v.mean()), "std": float(v.std()),
                    "p99": float(np.percentile(v, 99))}
    stats["_n_benign_windows"] = int(len(benign))
    return stats


class EvidenceEngine:
    """Deterministic evidence records for one prediction."""

    def __init__(self, baseline: dict):
        self.baseline = baseline

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path: str | Path) -> "EvidenceEngine":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.baseline, indent=2), encoding="utf-8")

    # -------------------------------------------------------------- explain
    def explain(self, x_raw: np.ndarray, attributions: np.ndarray,
                features: list[str] = WINDOW_FEATURES) -> list[dict]:
        """(L, F) raw window history + (F,) attributions → ranked evidence."""
        x_raw = np.asarray(x_raw, dtype=np.float64)
        attributions = np.asarray(attributions, dtype=np.float64)
        last = x_raw[-1]                       # most recent window = the state now
        out = []
        for j, name in enumerate(features):
            base = self.baseline.get(name)
            if base is None or base["std"] < 1e-12:
                continue                       # no benign reference → no claim
            z = (last[j] - base["mean"]) / base["std"]
            direction = ("normal" if abs(z) < Z_NORMAL
                         else "elevated" if z > 0 else "suppressed")
            spec = FEATURE_INDEX.get(name)
            out.append({
                "feature": name,
                "description": _describe(name),
                "observed": round(float(last[j]), 4),
                "benign_mean": round(base["mean"], 4),
                "benign_p99": round(base["p99"], 4),
                "z": round(float(z), 3),
                "direction": direction,
                "attribution": round(float(attributions[j]), 5),
                # signed: model used it AND traffic moved away from benign
                "contribution": round(float(attributions[j]) * np.sign(z), 5),
            })
        # rank by |attribution| — the model's own emphasis, evidence context below
        out.sort(key=lambda e: abs(e["attribution"]), reverse=True)
        return out

    def top(self, x_raw, attributions, k: int = 5, **kw) -> list[dict]:
        return self.explain(x_raw, attributions, **kw)[:k]


_DESCRIPTIONS = None


def _describe(name: str) -> str:
    """Human description from the canonical schema (V1 names are canonical)."""
    global _DESCRIPTIONS
    if _DESCRIPTIONS is None:
        from ..features.canonical_schema import CANONICAL_FEATURES
        _DESCRIPTIONS = {f.name: f.description for f in CANONICAL_FEATURES}
    return _DESCRIPTIONS.get(name, "")


def explain_prediction(model, x_raw: np.ndarray, scaler: dict,
                       baseline: dict, target_step: int = -1) -> dict:
    """One-call convenience: attribution + evidence for a raw (L, F) history.

    Deterministic (IG with fixed baseline zero); returns everything the WHY
    panel needs. `model` is the torch TemporalForecaster in eval mode.
    """
    from ..features.scaling import apply_scaler
    x_scaled = apply_scaler(np.asarray(x_raw)[None], scaler)
    attrs = integrated_gradients_attribution(model, x_scaled[0], target_step)
    eng = EvidenceEngine(baseline)
    return {
        "attributions": attrs.tolist(),
        "evidence": eng.explain(x_raw, attrs),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="fit + save the benign baseline")
    ap.add_argument("--windows", type=Path, default=Path("data/processed/windows.parquet"))
    ap.add_argument("--out", type=Path, default=Path("models/benign_baseline.json"))
    a = ap.parse_args()
    stats = benign_baseline(pd.read_parquet(a.windows))
    EvidenceEngine(stats).save(a.out)
    print(f"benign baseline over {stats['_n_benign_windows']} train windows -> {a.out}")
