"""Shared input transform — ONE definition used by every model and the app.

Why this module exists: the logistic baseline used to scale its inputs while the
LSTM was fed raw features. That made the PS-required benchmark unfair *against*
our own hero model (window volume features run to 1e8 while flag ratios sit in
[0,1], so the LSTM's gates saturated and the ratio features contributed almost
nothing). Any fix applied in only one place will silently drift again, so the
transform lives here and training + inference both import it.

Transform, in order:
  1. log1p on non-negative heavy-tailed features (counts / volumes / durations)
  2. per-feature standardisation

Fitted on the TRAIN split only, persisted next to the processed data, and
re-applied identically at inference time.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# Heavy-tailed, non-negative window features → log1p before standardising.
# Ratios (syn_ratio, auth_port_share, ...) are already bounded and stay linear.
LOG_FEATURES = {
    "flow_count",
    "bytes_total",
    "pkts_total",
    "duration_mean",
    "unique_dst_ports",
    "iat_mean",
    "iat_std",
    "avg_pkt_size",
    "down_up_ratio",
    "tcp_win_fwd",
    "tcp_win_bwd",
    "pkt_len_var",
    "fwd_seg_min",
    "fwd_pkt_len_std",
    "bwd_pkt_len_std",
    # Session 4b: rate and timing features (heavy-tailed)
    "idle_mean",
    "idle_std",
    "active_mean",
    "active_std",
    "flow_byts_per_sec",
    "flow_pkts_per_sec",
    "fwd_iat_mean",
    "bwd_iat_mean",
    "fwd_header_len_mean",
    "bwd_header_len_mean",
}


def _log_mask(feature_names: list[str]) -> np.ndarray:
    return np.array([n in LOG_FEATURES for n in feature_names], dtype=bool)


def _pre(X: np.ndarray, log_mask: np.ndarray) -> np.ndarray:
    """log1p the masked columns. X: (..., F)."""
    out = X.astype(np.float64, copy=True)
    if log_mask.any():
        # clip at 0: log1p needs x > -1, and these are all count/volume features
        out[..., log_mask] = np.log1p(np.maximum(out[..., log_mask], 0.0))
    return out


def fit_scaler(X: np.ndarray, feature_names: list[str]) -> dict:
    """Fit on TRAIN sequences only. X: (n, L, F) → scaler dict."""
    names = [str(n) for n in feature_names]
    log_mask = _log_mask(names)
    flat = _pre(X, log_mask).reshape(-1, X.shape[-1])
    mean = flat.mean(axis=0)
    scale = flat.std(axis=0)
    # zero-variance features (e.g. the IP columns absent from CIC's ML-ready
    # CSVs) would divide by 0 → keep them at 0 instead of producing NaNs.
    degenerate = scale < 1e-8
    scale = np.where(degenerate, 1.0, scale)
    return {
        "mean": mean,
        "scale": scale,
        "log_mask": log_mask,
        "degenerate": degenerate,
        "feature_names": np.array(names),
    }


def apply_scaler(X: np.ndarray, sc: dict) -> np.ndarray:
    """Apply the fitted transform. X: (..., F) → float32, same shape."""
    out = (_pre(X, sc["log_mask"]) - sc["mean"]) / sc["scale"]
    return np.ascontiguousarray(out, dtype=np.float32)


def save_scaler(sc: dict, path: str | Path) -> None:
    np.savez(Path(path), **sc)


def load_scaler(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"no scaler at {path} — re-run `python -m src.preprocessing.pipeline`. "
            "Training and inference MUST share one transform."
        )
    d = np.load(path, allow_pickle=False)
    return {k: d[k] for k in d.files}


def degenerate_features(sc: dict) -> list[str]:
    """Feature names with zero variance on train — dead inputs, worth reporting."""
    return [str(n) for n, bad in zip(sc["feature_names"], sc["degenerate"]) if bad]
