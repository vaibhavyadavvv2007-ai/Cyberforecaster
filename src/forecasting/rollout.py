"""K-step forecasting helpers used by the app.

Primary path: direct multi-horizon head — one forward pass returns p(t+1..t+K).

The `Forecaster` bundle exists so inference CANNOT diverge from training: it owns
the model, the fitted transform and the chosen threshold together. Feeding raw
(unscaled) features to a model trained on scaled ones produces confident
nonsense with no error, which is exactly the failure mode we cannot afford live.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import torch
except ImportError:  # app must run without torch in cached/simulated mode
    torch = None

N_STAGES = 6
# Anchored to the repo root, not the caller's cwd — otherwise `python
# scripts/build_demo_cache.py` from anywhere but the root silently finds nothing.
_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = _ROOT / "models" / "trained_models" / "lstm_forecaster.pt"
DEFAULT_SCALER = _ROOT / "data" / "processed" / "scaler.npz"


def load_model(model_path=DEFAULT_MODEL):
    """Load the trained TemporalForecaster; returns (model, config) or (None, reason)."""
    if torch is None:
        return None, "torch not installed"
    p = Path(model_path)
    if not p.exists():
        return None, f"no model file at {p}"
    cfg_p = p.with_name("lstm_config.json")
    cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.exists() else {}
    if cfg.get("architecture") == "transformer":
        from ..models.transformer_forecaster import TemporalTransformerForecaster
        model = TemporalTransformerForecaster(cfg.get("n_feat", 18),
                                  horizon=cfg.get("horizon", 5),
                                  d_model=cfg.get("hidden", 64),
                                  num_layers=cfg.get("layers", 2))
    else:
        from ..models.lstm_forecaster import TemporalForecaster
        model = TemporalForecaster(cfg.get("n_feat", 18),
                                  horizon=cfg.get("horizon", 5),
                                  hidden=cfg.get("hidden", 64),
                                  layers=cfg.get("layers", 2),
                                  predict_next_state=cfg.get("predict_next_state", False))
    # weights_only=True: we only ever save a state_dict (plain tensors), and the
    # default (False) unpickles arbitrary Python objects — arbitrary code
    # execution from a .pt we shuttle back from Colab. Not in a security project.
    state = torch.load(p, map_location="cpu", weights_only=True)
    try:
        model.load_state_dict(state)
    except RuntimeError as exc:
        # shape mismatch = weights trained on a different feature set. Fail loud;
        # a silently half-loaded model is worse than no model.
        return None, (f"weights do not match config (n_feat={cfg.get('n_feat')}): {exc}. "
                      "Re-run the pipeline and retrain.")
    model.eval()
    return model, cfg


@dataclass
class Forecaster:
    """Model + transform + threshold, loaded together or not at all."""
    model: object
    scaler: dict
    cfg: dict

    @property
    def threshold(self) -> float:
        return float(self.cfg.get("threshold", 0.5))

    @property
    def temperature(self) -> float:
        return float(self.cfg.get("temperature", 1.0))

    @property
    def horizon(self) -> int:
        return int(self.cfg.get("horizon", 5))

    @property
    def n_feat(self) -> int:
        return int(self.cfg.get("n_feat", 18))

    @classmethod
    def load(cls, model_path=DEFAULT_MODEL, scaler_path=DEFAULT_SCALER):
        """Returns (Forecaster, None) or (None, human-readable reason)."""
        from ..features.scaling import load_scaler
        model, cfg = load_model(model_path)
        if model is None:
            return None, str(cfg)
        try:
            scaler = load_scaler(scaler_path)
        except FileNotFoundError as exc:
            return None, str(exc)
        if len(scaler["feature_names"]) != int(cfg.get("n_feat", len(scaler["feature_names"]))):
            return None, (f"scaler has {len(scaler['feature_names'])} features but model "
                          f"expects {cfg.get('n_feat')} — retrain after the pipeline change")
        return cls(model=model, scaler=scaler, cfg=cfg), None

    def predict(self, x_raw: np.ndarray) -> dict:
        """x_raw: (L, F) UNSCALED window features → probs/stage/threshold/state_trajectory.

        state_trajectory: list of K feature vectors (each F-dim, scaled) when
        predict_next_state=True; None otherwise. These are the model's prediction
        of what the next K windows will look like — the literal world-model output.
        """
        from ..features.scaling import apply_scaler
        from ..attack_mapping.mitre_mapper import STAGES
        if torch is None:
            raise RuntimeError("torch unavailable")
        x = apply_scaler(np.asarray(x_raw, dtype=np.float64)[None], self.scaler)
        with torch.no_grad():
            prog_logits, stage_logits, state_pred = self.model(
                torch.from_numpy(x).float())
            # Apply temperature scaling for calibration
            T = self.temperature
            probs = torch.sigmoid(prog_logits / T)[0].numpy()
            stage_idx = int(stage_logits[0].argmax())
        result: dict = {
            "probs": [round(float(p), 4) for p in probs],
            "stage": STAGES[stage_idx] if 0 <= stage_idx < len(STAGES) else "",
            "threshold": self.threshold,
            # K × F scaled feature vectors; None when head is disabled.
            # Shape mirrors sequences_*.npz 'X' format for easy comparison.
            "state_trajectory": (state_pred[0].numpy().tolist()
                                 if state_pred is not None else None),
        }
        return result

    def scaled(self, x_raw: np.ndarray) -> np.ndarray:
        """(L, F) raw → (L, F) scaled float32 — for attribution, which needs the
        same input the model actually saw."""
        from ..features.scaling import apply_scaler
        return apply_scaler(np.asarray(x_raw, dtype=np.float64), self.scaler)


def forecast_probabilities(model, x: np.ndarray, stages: list[str]) -> dict:
    """Deprecated: assumes x is ALREADY scaled. Prefer `Forecaster.predict`."""
    if torch is None or model is None:
        raise RuntimeError("model unavailable — use cached/simulated mode in the app")
    with torch.no_grad():
        prog_logits, stage_logits, _ = model(
            torch.from_numpy(x[None].astype(np.float32)))
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
