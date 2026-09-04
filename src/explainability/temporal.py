"""Temporal WHY — which parts of the HISTORY drove this forecast (W-9 .. NOW).

The feature-level attribution (IG) is per (window, feature): a full (L, F)
matrix. The existing path sums it over time and loses the time axis; this
module keeps it, so the WHY panel can answer "when did this start?" — the
question a judge actually asks about a *temporal* forecaster.

All labels are relative to NOW (the most recent window of the input
sequence): W-(L-1) ... W-1, W-0(=NOW). No LLM; pure arithmetic.
"""
from __future__ import annotations

import numpy as np


def window_labels(L: int) -> list[str]:
    """['W-9', ..., 'W-1', 'W-0'] — W-0 is NOW (the newest window)."""
    return [f"W-{L - 1 - i}" for i in range(L)]


def temporal_why(x_raw: np.ndarray, attrs: np.ndarray,
                 features: list[str] | None = None,
                 top_k: int = 3) -> dict:
    """(L, F) raw windows + (L, F) per-window attributions → timeline record.

    attrs is the UNSUMMED IG matrix (same shape as x_raw's feature axis).
    """
    x_raw = np.asarray(x_raw, dtype=np.float64)
    attrs = np.abs(np.asarray(attrs, dtype=np.float64))
    L, F = attrs.shape
    if x_raw.shape != (L, F):
        raise ValueError(f"x_raw {x_raw.shape} != attrs {(L, F)}")
    features = list(features) if features is not None else [f"f{j}" for j in range(F)]

    per_window = attrs.sum(axis=1)                  # (L,) importance per window
    total = per_window.sum() or 1.0
    # the model's overall top features — the ones to track across the timeline
    top_overall = np.argsort(-attrs.sum(axis=0))[:top_k]

    timeline = []
    for i in range(L):
        drivers = sorted(range(F), key=lambda j: -attrs[i, j])[:top_k]
        timeline.append({
            "label": window_labels(L)[i],
            "importance": round(float(per_window[i]), 5),
            "share": round(float(per_window[i] / total), 4),
            "drivers": [
                {"feature": features[j],
                 "attribution": round(float(attrs[i, j]), 5),
                 "observed": round(float(x_raw[i, j]), 4)}
                for j in drivers
            ],
        })

    # trend of the top driver across the whole history: is it rising toward NOW?
    j0 = int(top_overall[0])
    first, last = x_raw[0, j0], x_raw[-1, j0]
    return {
        "labels": window_labels(L),
        "timeline": timeline,
        "top_features": [
            {"feature": features[j], "total_attribution": round(float(attrs[:, j].sum()), 5)}
            for j in top_overall
        ],
        "trend": {
            "feature": features[j0],
            "first": round(float(first), 4), "now": round(float(last), 4),
            "direction": "rising" if last > first else
                         ("falling" if last < first else "flat"),
        },
    }
