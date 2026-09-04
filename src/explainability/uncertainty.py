"""Uncertainty via MC-dropout ensemble — free epistemic bands on any forecast.

The TemporalForecaster already has dropout (p=0.2, two places). Running the
SAME weights T times with dropout ACTIVE samples the network's posterior
approximation: the spread across passes is an uncertainty estimate that costs
no extra parameters and no retraining. Seeded → deterministic (plan rule: no
nondeterminism a judge can't reproduce).

What the bands mean (and do NOT mean):
  std is NOT a probability of being wrong; it measures how sensitive the
  forecast is to which dropout mask the network wears — i.e. how far outside
  its training density this input might be. A high-std forecast should be
  shown as "low confidence" and routed to a human, which is exactly what the
  decision-support engine does with it.
"""
from __future__ import annotations

import numpy as np


def mc_dropout_forecast(model, x_scaled: np.ndarray, T: int = 32,
                        seed: int = 0) -> dict:
    """(L, F) SCALED input → mean/std forecast + confidence band.

    model: torch TemporalForecaster (eval mode is fine; dropout is re-enabled
    here and restored after). Deterministic for a fixed seed.
    """
    import torch
    import torch.nn as nn

    was_training = model.training
    model.eval()                       # keep batchnorm-free trunk deterministic
    dropout_states = {}
    for name, m in model.named_modules():
        if isinstance(m, nn.Dropout):
            dropout_states[name] = m.training
            m.train()                  # dropout ON at inference = MC sampling
    saved_rng = torch.random.get_rng_state()
    try:
        torch.manual_seed(seed)
        x = torch.from_numpy(np.asarray(x_scaled)[None].astype(np.float32))
        probs, stages = [], []
        with torch.no_grad():
            for _ in range(T):
                prog_logits, stage_logits = model(x)
                probs.append(torch.sigmoid(prog_logits)[0].numpy())
                stages.append(int(stage_logits[0].argmax()))
    finally:                           # ALWAYS restore the model untouched
        torch.random.set_rng_state(saved_rng)
        for name, m in model.named_modules():
            if name in dropout_states:
                m.training = dropout_states[name]
        model.train(was_training)

    probs = np.stack(probs)            # (T, K)
    mean = probs.mean(axis=0)
    std = probs.std(axis=0)
    return {
        "probs_mean": [round(float(v), 4) for v in mean],
        "probs_std": [round(float(v), 4) for v in std],
        "max_std": round(float(std.max()), 4),
        "confidence": confidence_band(float(std.max())),
        "T": int(T),
        "stage_votes": {str(s): stages.count(s) for s in set(stages)},
    }


def confidence_band(max_std: float) -> str:
    """Coarse, fixed thresholds — shown next to the number, never instead of it."""
    if max_std < 0.05:
        return "HIGH"
    if max_std < 0.15:
        return "MEDIUM"
    return "LOW"
