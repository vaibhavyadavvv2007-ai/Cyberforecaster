"""World-model forecaster — V1 + a state head that predicts S(t+1..t+K).

Why this file is separate (Phase 6, plan §20–§23):
The audit proved the original plan's claim wrong — TemporalForecaster has NO
state head (prog + stage only). The world model is therefore an ADDITION:
this subclass leaves `src/models/lstm_forecaster.py` and the frozen V1
artifact (`models/trained_models/`, in use by the live demo) completely
untouched. V2 artifacts land in `models/world_model_v2/`.

What the state head adds
------------------------
From the same LSTM trunk and shared representation `h`, a third head predicts
the next K WINDOW FEATURE VECTORS (in scaled space, same transform as the
inputs): Ŝ(t+1), ..., Ŝ(t+K). Loss:

    L = BCE(prog) + CE(stage) + λ_state · L_state(Ŝ, S)

with L_state ∈ {Huber (default), MAE, MSE} and λ_state swept over
{0.1, 0.3, 0.5}. Checkpoint selection stays V1's rule (pooled val AP of the
prog head) so V1↔V2 forecasting numbers stay comparable; state quality is
then MEASURED on the test split, never selected on.

State metrics (per horizon step and per feature): MAE, RMSE, cosine
similarity between predicted and true (scaled) state vectors. Zero-variance
features (the IP columns the CIC ML CSVs can't provide) are excluded from
metrics — a constant-0 prediction is trivially perfect and would inflate
the numbers. That exclusion is recorded in the metrics JSON.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import average_precision_score

from ..features.scaling import apply_scaler, load_scaler
from ..features.window_builder import (WINDOW_FEATURES, chrono_split,
                                       horizon_any, make_world_sequences)
from .baseline_logreg import MAX_FPR, evaluate, pick_threshold, report
from .lstm_forecaster import PATIENCE, TemporalForecaster, _predict

STATE_LOSSES = {"huber": nn.SmoothL1Loss, "mae": nn.L1Loss, "mse": nn.MSELoss}


class WorldModelForecaster(TemporalForecaster):
    """prog + stage heads (inherited, unchanged shapes) + state head."""

    def __init__(self, n_feat: int, seq_len: int = 10, horizon: int = 5,
                 hidden: int = 64, layers: int = 2, dropout: float = 0.2):
        super().__init__(n_feat, seq_len, horizon, hidden, layers, dropout)
        # shared trunk → (K, F) future state, from the SAME pooled repr as prog
        self.state_head = nn.Linear(hidden // 2, horizon * n_feat)
        self.n_feat = n_feat

    def forward(self, x):  # x: (B, L, F)
        out, _ = self.lstm(x)
        h = self.head(out[:, -1])
        # inherit V1's outputs exactly; add (B, K, F) state prediction
        state = self.state_head(h).reshape(-1, self.horizon, self.n_feat)
        return self.prog_head(h), self.stage_head(h), state


# ------------------------------------------------------------------- metrics

def state_metrics(pred: np.ndarray, true: np.ndarray,
                  feature_names: list[str],
                  degenerate: np.ndarray | None = None) -> dict:
    """Per-horizon and per-feature state quality on SCALED vectors.

    `degenerate` (from the scaler) marks zero-variance features; they are
    excluded from aggregate metrics and the exclusion is reported, not hidden.
    """
    pred, true = np.asarray(pred, dtype=np.float64), np.asarray(true, dtype=np.float64)
    n, K, F = true.shape
    keep = np.ones(F, dtype=bool) if degenerate is None else ~np.asarray(degenerate, dtype=bool)

    mae_h, rmse_h, cos_h = [], [], []
    for k in range(K):
        p, t = pred[:, k, keep], true[:, k, keep]
        mae_h.append(float(np.abs(p - t).mean()))
        rmse_h.append(float(np.sqrt(((p - t) ** 2).mean())))
        # cosine over each predicted/true state vector, averaged
        num = (p * t).sum(axis=1)
        den = np.linalg.norm(p, axis=1) * np.linalg.norm(t, axis=1)
        cos_h.append(float((num / np.clip(den, 1e-12, None)).mean()))

    mae_f = np.abs(pred - true).mean(axis=(0, 1))
    return {
        "n_test": int(n), "horizon": int(K),
        "excluded_degenerate_features": [f for f, k in zip(feature_names, keep) if not k],
        "mae_per_horizon": [round(v, 4) for v in mae_h],
        "rmse_per_horizon": [round(v, 4) for v in rmse_h],
        "cosine_per_horizon": [round(v, 4) for v in cos_h],
        "mae_per_feature": {f: round(float(m), 4) for f, m in zip(feature_names, mae_f)},
        "cosine_mean": round(float(np.mean(cos_h)), 4),
    }


# ------------------------------------------------------------------ training

def _predict3(model, X, dev, batch=1024):
    model.eval()
    progs, states = [], []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            prog, _stg, state = model(X[i:i + batch].to(dev))
            progs.append(torch.sigmoid(prog).cpu().numpy())
            states.append(state.cpu().numpy())
    return (np.concatenate(progs) if progs else np.zeros((0, model.horizon)),
            np.concatenate(states) if states else np.zeros((0, model.horizon, model.n_feat)))


def train_world_model(npz_dir: Path, lambda_state: float = 0.3,
                      state_loss: str = "huber", epochs: int = 40,
                      batch: int = 256, lr: float = 1e-3,
                      out_dir: Path | None = None,
                      train_frac_limit: float | None = None) -> dict:
    """Train V2 on CIC2018 windows (same data, same split, same scaler as V1).

    Reads windows.parquet (not the frozen npz) to also get the future-window
    targets; splits come from the SAME chrono_split as V1, so the test set is
    identical and V1↔V2 numbers are directly comparable.
    """
    assert state_loss in STATE_LOSSES, f"state_loss must be one of {list(STATE_LOSSES)}"
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    sc = load_scaler(npz_dir / "scaler.npz")
    windows = pd.read_parquet(npz_dir / "windows.parquet")

    X, Xf, y_prog, y_stage, ends = make_world_sequences(windows)
    Xs, Xfs = apply_scaler(X, sc), apply_scaler(Xf, sc)
    tr, va, te = chrono_split(windows, ends)
    if train_frac_limit is not None:              # smoke runs only — never production
        tr = tr[: max(8, int(len(tr) * train_frac_limit))]
    to = lambda idx, *arrs: [torch.from_numpy(a[idx]).float() for a in arrs]
    Xtr, Xftr, ytr, ystr = to(tr, Xs, Xfs, y_prog, y_stage)
    str_ = ystr.long()
    Xva, Xfva, yva, ysva = to(va, Xs, Xfs, y_prog, y_stage)
    sva = ysva.long()
    Xte, Xfte, yte, yste = to(te, Xs, Xfs, y_prog, y_stage)
    ste = yste.long()
    n_feat, K = Xtr.shape[-1], ytr.shape[1]
    print(f"[V2 lambda={lambda_state} {state_loss}] dev={dev} train={len(Xtr)} "
          f"val={len(Xva)} test={len(Xte)} | F={n_feat} K={K}")

    tr_dl = DataLoader(TensorDataset(Xtr, Xftr, ytr, str_),
                       batch_size=batch, shuffle=True)
    n_pos = ytr.sum(dim=0)
    pos_weight = ((len(ytr) - n_pos) / n_pos.clamp(min=1)).to(dev)

    model = WorldModelForecaster(n_feat, horizon=K).to(dev)
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    ce = nn.CrossEntropyLoss(ignore_index=-1)
    s_loss = STATE_LOSSES[state_loss]()
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    have_val = len(Xva) > 0 and float(horizon_any(yva.numpy()).sum()) > 0
    best_ap, best_state, bad = -1.0, None, 0
    for epoch in range(1, epochs + 1):
        model.train()
        for xb, xfb, yb, sb in tr_dl:
            xb, xfb, yb, sb = (t.to(dev) for t in (xb, xfb, yb, sb))
            opt.zero_grad()
            prog, stg, state = model(xb)
            loss = (bce(prog, yb) + ce(stg, sb)
                    + lambda_state * s_loss(state, xfb))
            loss.backward()
            opt.step()

        if not have_val:
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            continue
        p_va, _ = _predict3(model, Xva, dev)
        ap = float(average_precision_score(horizon_any(yva.numpy()), p_va.max(axis=1)))
        print(f"  epoch {epoch:02d}  val AP(pooled)={ap:.4f}")
        if ap > best_ap:
            best_ap, bad = ap, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= PATIENCE:
                print(f"  early stop at epoch {epoch} (best val AP={best_ap:.4f})")
                break

    model.load_state_dict(best_state)
    model = model.to(dev)
    out_dir = out_dir or Path("models") / "world_model_v2" / f"lambda_{lambda_state}_{state_loss}"
    out_dir.mkdir(parents=True, exist_ok=True)
    weights = out_dir / "world_model.pt"
    torch.save(best_state, weights)

    # forecasting quality: threshold on val, honest test numbers (V1 protocol)
    p_va, _ = _predict3(model, Xva, dev) if have_val else (None, None)
    thr = pick_threshold(horizon_any(yva.numpy()), p_va.max(axis=1)) if have_val else 0.5
    p_te, s_te = _predict3(model, Xte, dev)
    agg = evaluate(horizon_any(yte.numpy()), p_te.max(axis=1), thr)
    per_step = [evaluate(yte.numpy()[:, k], p_te[:, k], thr) for k in range(K)]
    report(f"World model lambda={lambda_state} ({state_loss})", agg, per_step)

    # state quality on the SAME test split
    sm = state_metrics(s_te, Xfte.numpy(), list(WINDOW_FEATURES),
                       degenerate=sc["degenerate"])
    print(f"  state: cosine/step {sm['cosine_per_horizon']} "
          f"(mean {sm['cosine_mean']}); excluded {sm['excluded_degenerate_features']}")

    cfg = {"n_feat": int(n_feat), "horizon": int(K), "hidden": 64, "layers": 2,
           "lambda_state": lambda_state, "state_loss": state_loss,
           "val_AP": best_ap, "threshold": thr, "max_fpr": MAX_FPR,
           "schema": "v1_18_features (CIC2018)"}
    (out_dir / "world_model_config.json").write_text(json.dumps(cfg, indent=2),
                                                     encoding="utf-8")
    payload = {**agg, "_per_step": per_step, "_state": sm,
               "_n_train": int(len(Xtr)), "_n_test": int(len(Xte)),
               "_val_ap": best_ap, "_lambda_state": lambda_state,
               "_state_loss": state_loss}
    (out_dir / "metrics.json").write_text(json.dumps(payload, indent=2),
                                          encoding="utf-8")
    print(f"wrote {weights} + config + metrics")
    return payload


def sweep(npz_dir: Path, epochs: int = 40, state_loss: str = "huber") -> list[dict]:
    """λ_state ∈ {0.1, 0.3, 0.5} — the plan's staged sweep, one artifact each."""
    return [train_world_model(npz_dir, lambda_state=lb, state_loss=state_loss,
                              epochs=epochs)
            for lb in (0.1, 0.3, 0.5)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lambda-state", type=float, default=None,
                    help="train ONE λ (default: sweep 0.1/0.3/0.5)")
    ap.add_argument("--state-loss", choices=list(STATE_LOSSES), default="huber")
    ap.add_argument("--smoke", action="store_true",
                    help="tiny run to verify wiring (never for reported numbers)")
    a = ap.parse_args()
    if a.smoke:
        train_world_model(a.dir, lambda_state=0.3, state_loss=a.state_loss,
                          epochs=2, train_frac_limit=0.05,
                          out_dir=Path("models") / "world_model_v2" / "_smoke")
    elif a.lambda_state is not None:
        train_world_model(a.dir, lambda_state=a.lambda_state,
                          state_loss=a.state_loss, epochs=a.epochs)
    else:
        sweep(a.dir, epochs=a.epochs, state_loss=a.state_loss)
