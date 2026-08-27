"""Per-prediction feature attribution.

Primary: Captum IntegratedGradients on the sequence input, |attributions|
aggregated over the time axis → one importance value per window feature.
Fallback (no captum / no torch): permutation importance on flattened features
against any predict_fn — slower but dependency-free.

The PS rejects black-box outputs; every demo prediction must be able to show
this vector.
"""
from __future__ import annotations

import numpy as np


def integrated_gradients_attribution(model, x_seq: np.ndarray, target_step: int = -1) -> np.ndarray:
    """|IG| summed over time → (F,) feature importances for one sequence.

    target_step indexes which horizon step's progression logit to explain
    (default: the furthest, i.e. the headline forecast number).
    """
    try:
        import torch
        from captum.attr import IntegratedGradients
    except ImportError as exc:
        raise RuntimeError("captum/torch missing — use permutation fallback") from exc

    ig = IntegratedGradients(lambda inp: model(inp)[0][:, target_step])
    inp = torch.from_numpy(x_seq[None].astype(np.float32)).requires_grad_(True)
    attrs = ig.attribute(inp, n_steps=32)           # (1, L, F)
    return attrs.abs().sum(dim=1)[0].detach().numpy()


def permutation_fallback(predict_fn, X_flat: np.ndarray, y: np.ndarray,
                         n_repeats: int = 5, seed: int = 0) -> np.ndarray:
    """Global (not per-prediction) importances via sklearn permutation importance.

    predict_fn: (n_flat_samples, F_total) -> probabilities.
    """
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import average_precision_score

    scorer = lambda est, X, yy: average_precision_score(yy, est.predict_proba(X)[:, 1])
    class _Wrap:
        """Minimal sklearn-style wrapper so permutation_importance accepts predict_fn."""
        def fit(self, X, y=None):
            return self
        def predict(self, X):
            return (predict_fn(X) >= 0.5).astype(int)
        def predict_proba(self, X):
            p = predict_fn(X)
            return np.stack([1 - p, p], axis=1)

    rng = np.random.default_rng(seed)
    idx = rng.choice(len(X_flat), size=min(len(X_flat), 4000), replace=False)
    res = permutation_importance(_Wrap().fit(X_flat[idx]), X_flat[idx], y[idx],
                                 scoring=scorer, n_repeats=n_repeats, random_state=seed)
    return res.importances_mean


if __name__ == "__main__":
    # smoke test of the fallback with a dummy predictor
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 12)).astype(np.float32)
    w = rng.normal(size=(12,)).astype(np.float32)
    y = (X @ w + rng.normal(scale=0.1, size=200) > 0).astype(int)
    imp = permutation_fallback(lambda Z: 1 / (1 + np.exp(-(Z @ w))), X, y.astype(np.int64))
    print("fallback importances:", np.round(imp, 3))
