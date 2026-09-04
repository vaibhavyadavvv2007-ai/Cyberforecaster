"""Rollout world model (V3) — risk DECODED from autoregressive future states.

Why this file exists (2026-09-04, closes the "genuine world model" gap):
V1 (frozen, live demo) forecasts risk DIRECTLY from the encoder: h -> risk.
V2 (models/world_model_v2/) added a state head as a PARALLEL regression task,
but the risk forecast never flowed through the predicted states — and all K
states came from one linear map of h, with no S(t+1) -> S(t+2) chaining.

V3 is the genuine state-transition architecture the PS describes:

    LSTM encoder -> h
    S~(t+1) = state_init(h)                          (scaled feature space)
    S~(t+k+1) = S~(t+k) + transition(S~(t+k))        (autoregressive, residual)
    risk(t+k) = risk_decoder(S~(t+k))                <- risk flows THROUGH states
    stage(t+k) = stage_decoder(S~(t+k))              <- per-step ATT&CK stage (new)

The attack-risk and stage forecasts are now causally DOWNSTREAM of the
forecast future network states. If the state rollout is bad, the risk
forecast is bad — they cannot diverge, which is the whole point.

Honesty note: V2's negative result (state head did not improve CIC2018
forecasting) means V3 may also not beat V1 on PR-AUC. That is an acceptable
and reportable outcome: the architecture is evaluated on (a) forecasting
quality vs V1, (b) state quality (MAE/RMSE/cosine vs V2), (c) per-step stage
accuracy — and the verdict is recorded either way. V1 stays the demo model
regardless (additive rule: nothing here touches models/trained_models/).

Training protocol is IDENTICAL to V1/V2 (same windows.parquet, same
chrono_split, same frozen scaler, threshold from val only) so the numbers
are directly comparable.
"""
from __future__ import annotations

import argparse
import json
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
from ..attack_mapping.mitre_mapper import STAGES
from .baseline_logreg import MAX_FPR, evaluate, pick_threshold, report
from .lstm_forecaster import N_STAGES, PATIENCE, TemporalForecaster
from .world_model import STATE_LOSSES, state_metrics


class RolloutWorldModel(TemporalForecaster):
    """Autoregressive state rollout with risk/stage decoded from each state.

    Inherits the LSTM trunk and pooled head from TemporalForecaster so the
    encoder is architecturally comparable to V1/V2. The inherited
    prog_head/stage_head remain in the module (state_dict compatibility is
    irrelevant here — V3 is a new artifact) but forward() returns the
    rollout outputs instead.
    """

    def __init__(self, n_feat: int, seq_len: int = 10, horizon: int = 5,
                 hidden: int = 64, layers: int = 2, dropout: float = 0.2):
        super().__init__(n_feat, seq_len, horizon, hidden, layers, dropout)
        self.n_feat = n_feat
        # h -> S(t+1): initialize the rollout from the pooled representation
        self.state_init = nn.Linear(hidden // 2, n_feat)
        # S(k) -> S(k+1) residual transition — the learned state dynamics
        self.transition = nn.Sequential(nn.Linear(n_feat, hidden // 2), nn.ReLU(),
                                         nn.Linear(hidden // 2, n_feat))
        # decoders: risk and stage are functions OF THE FORECAST STATE
        self.risk_decoder = nn.Linear(n_feat, 1)
        self.stage_decoder = nn.Linear(n_feat, N_STAGES)

    def rollout(self, x: torch.Tensor):
        """x: (B, L, F) scaled -> risks (B,K), stage_logits (B,K,S), states (B,K,F)."""
        out, _ = self.lstm(x)
        h = self.head(out[:, -1])
        s = self.state_init(h)                       # S~(t+1)
        risks, stages, states = [], [], []
        for _ in range(self.horizon):
            states.append(s)
            risks.append(self.risk_decoder(s).squeeze(-1))
            stages.append(self.stage_decoder(s))
            s = s + self.transition(s)               # residual autoregressive step
        return (torch.stack(risks, dim=1),
                torch.stack(stages, dim=1),
                torch.stack(states, dim=1))

    def forward(self, x):  # V3's contract: the rollout IS the forward pass
        return self.rollout(x)


# ------------------------------------------------------------------ inference

def predict_rollout(model: RolloutWorldModel, X: torch.Tensor, dev: str,
                    batch: int = 1024):
    """(n,K) risk probs, (n,K) stage indices, (n,K,F) states — batched, pooled."""
    model.eval()
    probs, stages, states = [], [], []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            r, st, sp = model(X[i:i + batch].to(dev))
            probs.append(torch.sigmoid(r).cpu().numpy())
            stages.append(st.argmax(dim=-1).cpu().numpy())
            states.append(sp.cpu().numpy())
    return (np.concatenate(probs) if probs else np.zeros((0, model.horizon)),
            np.concatenate(stages) if stages else np.zeros((0, model.horizon), dtype=int),
            np.concatenate(states) if states else np.zeros((0, model.horizon, model.n_feat)))


def per_step_stage_accuracy(pred_stages: np.ndarray, y_stage: np.ndarray) -> dict:
    """Per-horizon-step stage accuracy vs the sequence-level dominant stage.

    Honest caveat, stated up front: supervision is the sequence's dominant
    horizon stage (the V1 pipeline's label granularity — per-window stage
    labels exist in windows.parquet but the training loss mirrors V1/V2 for
    comparability). Per-step differences therefore reflect the forecast state
    trajectory's evolution, which is exactly what we display.
    """
    valid = y_stage >= 0
    out = {"n_sequences_with_stage": int(valid.sum()), "accuracy_per_step": []}
    for k in range(pred_stages.shape[1]):
        ok = (pred_stages[valid, k] == y_stage[valid])
        out["accuracy_per_step"].append(round(float(ok.mean()), 4) if valid.any() else None)
    return out


# ------------------------------------------------------------------ training

def train_rollout_model(npz_dir: Path, lambda_state: float = 0.5,
                        state_loss: str = "huber", epochs: int = 40,
                        batch: int = 256, lr: float = 1e-3,
                        out_dir: Path | None = None,
                        train_frac_limit: float | None = None) -> dict:
    """Train V3 on CIC2018 windows — same data/split/scaler/protocol as V1/V2."""
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
    Xtr, Xftr, ytr = to(tr, Xs, Xfs, y_prog)
    str_ = y_stage[tr].astype(np.int64)
    Xva, Xfva, yva = to(va, Xs, Xfs, y_prog)
    sva = y_stage[va].astype(np.int64)
    Xte, Xfte, yte = to(te, Xs, Xfs, y_prog)
    ste = y_stage[te].astype(np.int64)
    n_feat, K = Xtr.shape[-1], ytr.shape[1]
    print(f"[V3 rollout lambda={lambda_state} {state_loss}] dev={dev} "
          f"train={len(Xtr)} val={len(Xva)} test={len(Xte)} | F={n_feat} K={K}")

    tr_dl = DataLoader(TensorDataset(Xtr, Xftr, ytr, torch.from_numpy(str_)),
                       batch_size=batch, shuffle=True)
    n_pos = ytr.sum(dim=0)
    pos_weight = ((len(ytr) - n_pos) / n_pos.clamp(min=1)).to(dev)

    model = RolloutWorldModel(n_feat, horizon=K).to(dev)
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
            risks, stages, states = model(xb)
            # stage: every step's decoder sees the sequence-level dominant
            # stage (V1 label granularity — see per_step_stage_accuracy note)
            loss = (bce(risks, yb)
                    + ce(stages.reshape(-1, N_STAGES),
                         sb.unsqueeze(1).expand(-1, K).reshape(-1))
                    + lambda_state * s_loss(states, xfb))
            loss.backward()
            opt.step()

        if not have_val:
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            continue
        p_va, _, _ = predict_rollout(model, Xva, dev)
        ap = float(average_precision_score(horizon_any(yva.numpy()), p_va.max(axis=1)))
        print(f"  epoch {epoch:02d}  val AP(pooled, risk-from-state)={ap:.4f}")
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
    out_dir = out_dir or Path("models") / "world_model_v3" / f"lambda_{lambda_state}_{state_loss}"
    out_dir.mkdir(parents=True, exist_ok=True)
    weights = out_dir / "rollout_world_model.pt"
    torch.save(best_state, weights)

    # forecasting quality: threshold on val, honest test numbers (V1 protocol)
    p_va, _, _ = predict_rollout(model, Xva, dev) if have_val else (None, None, None)
    thr = pick_threshold(horizon_any(yva.numpy()), p_va.max(axis=1)) if have_val else 0.5
    p_te, stg_te, s_te = predict_rollout(model, Xte, dev)
    agg = evaluate(horizon_any(yte.numpy()), p_te.max(axis=1), thr)
    per_step = [evaluate(yte.numpy()[:, k], p_te[:, k], thr) for k in range(K)]
    report(f"Rollout world model lambda={lambda_state} ({state_loss})", agg, per_step)

    # state quality + per-step stage accuracy on the SAME test split
    sm = state_metrics(s_te, Xfte.numpy(), list(WINDOW_FEATURES),
                       degenerate=sc["degenerate"])
    sa = per_step_stage_accuracy(stg_te, ste)
    print(f"  state: cosine/step {sm['cosine_per_horizon']} (mean {sm['cosine_mean']})")
    print(f"  stage: per-step accuracy {sa['accuracy_per_step']} "
          f"(n={sa['n_sequences_with_stage']})")

    cfg = {"n_feat": int(n_feat), "horizon": int(K), "hidden": 64, "layers": 2,
           "lambda_state": lambda_state, "state_loss": state_loss,
           "val_AP": best_ap, "threshold": thr, "max_fpr": MAX_FPR,
           "architecture": "autoregressive state rollout, risk/stage decoded from state",
           "schema": "v1_18_features (CIC2018)"}
    (out_dir / "rollout_config.json").write_text(json.dumps(cfg, indent=2),
                                                 encoding="utf-8")
    payload = {**agg, "_per_step": per_step, "_state": sm, "_stage": sa,
               "_n_train": int(len(Xtr)), "_n_test": int(len(Xte)),
               "_val_ap": best_ap, "_lambda_state": lambda_state,
               "_state_loss": state_loss}
    (out_dir / "metrics.json").write_text(json.dumps(payload, indent=2),
                                          encoding="utf-8")
    print(f"wrote {weights} + config + metrics")
    return payload


def load_rollout_model(model_dir: Path | None = None):
    """Load a trained V3 → (model, cfg) or (None, reason). weights_only=True."""
    if torch is None:  # pragma: no cover
        return None, "torch not installed"
    d = model_dir or Path("models") / "world_model_v3" / "lambda_0.5_huber"
    cfg_p = d / "rollout_config.json"
    w_p = d / "rollout_world_model.pt"
    if not cfg_p.exists() or not w_p.exists():
        return None, f"V3 artifacts missing at {d}"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    model = RolloutWorldModel(cfg["n_feat"], horizon=cfg["horizon"],
                              hidden=cfg.get("hidden", 64),
                              layers=cfg.get("layers", 2))
    model.load_state_dict(torch.load(w_p, map_location="cpu", weights_only=True))
    model.eval()
    return model, cfg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lambda-state", type=float, default=0.5,
                    help="state-loss weight (default 0.5 — V2's best)")
    ap.add_argument("--state-loss", choices=list(STATE_LOSSES), default="huber")
    ap.add_argument("--smoke", action="store_true",
                    help="tiny run to verify wiring (never for reported numbers)")
    a = ap.parse_args()
    if a.smoke:
        train_rollout_model(a.dir, lambda_state=a.lambda_state,
                            state_loss=a.state_loss, epochs=2,
                            train_frac_limit=0.05,
                            out_dir=Path("models") / "world_model_v3" / "_smoke")
    else:
        train_rollout_model(a.dir, lambda_state=a.lambda_state,
                            state_loss=a.state_loss, epochs=a.epochs)
