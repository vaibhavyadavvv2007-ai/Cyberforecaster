"""K-step forecasting helpers used by the app.

Primary path: direct multi-horizon head — one forward pass returns p(t+1..t+K).
"""
from __future__ import annotations

import numpy as np

try:
    import torch
except ImportError:  # app must run without torch in cached/simulated mode
    torch = None

N_STAGES = 6


def load_model(model_path="models/trained_models/lstm_forecaster.pt"):
    """Load the trained TemporalForecaster; returns (model, config) or (None, reason)."""
    if torch is None:
        return None, "torch not installed"
    from ..models.lstm_forecaster import TemporalForecaster
    import json
    from pathlib import Path
    p = Path(model_path)
    if not p.exists():
        return None, f"no model file at {p}"
    cfg_p = p.with_name("lstm_config.json")
    cfg = json.loads(cfg_p.read_text()) if cfg_p.exists() else {}
    model = TemporalForecaster(cfg.get("n_feat", 18),
                               hidden=cfg.get("hidden", 64),
                               layers=cfg.get("layers", 2))
    model.load_state_dict(torch.load(p, map_location="cpu"))
    model.eval()
    return model, cfg


def forecast_probabilities(model, x: np.ndarray, stages: list[str]) -> dict:
    """x: (L, F) single sequence → {'probs': [K], 'stage': str}."""
    if torch is None or model is None:
        raise RuntimeError("model unavailable — use simulated mode in the app")
    with torch.no_grad():
        xt = torch.from_numpy(x[None].astype(np.float32))
        prog_logits, stage_logits = model(xt)
        probs = torch.sigmoid(prog_logits)[0].numpy()
        stage_idx = int(stage_logits[0].argmax())
    return {
        "probs": [round(float(p), 4) for p in probs],
        "stage": stages[stage_idx] if 0 <= stage_idx < len(stages) else "",
    }


def recursive_latent_rollout():
    """Tier-3 stretch: roll forward in latent space instead of direct heads.

    Deliberately unimplemented — do NOT start this before Gate 2.
    """
    raise NotImplementedError("recursive latent rollout is Tier-3; finish Tier 1 first")
