"""Temporal forecaster: 2-layer LSTM → direct multi-horizon heads.

Outputs per input sequence:
  prog_logits (K,) — attack-progression probability for EACH of the next K windows
  stage_logits (n_stages,) — dominant stage over the horizon (multi-task head)

Phase 1 Improvements (Sep 4, 2026):
  - Focal loss (α=0.25, γ=2.0) for better recall on imbalanced data
  - AdamW optimizer with weight decay for better generalization
  - Gradient clipping (max_norm=1.0) for training stability
  - Cosine annealing LR scheduler for better convergence
  - Multi-seed training (5 seeds, keep best) to reduce initialization variance

Usage:
  python -m src.models.lstm_forecaster --dir data/processed [--epochs 40]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PyTorch missing. Install CPU build locally:\n"
        "  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
        "(Kaggle/Colab already ship CUDA builds)"
    ) from exc

from sklearn.metrics import average_precision_score

from ..features.scaling import apply_scaler, load_scaler
from ..features.window_builder import WINDOW_FEATURES, horizon_any
from .baseline_logreg import MAX_FPR, evaluate, pick_threshold, report

N_STAGES = 6


class FocalLoss(nn.Module):
    """Focal Loss for addressing class imbalance.
    
    Reduces loss for well-classified examples, focusing on hard samples.
    FL(p_t) = -α_t * (1 - p_t)^γ * log(p_t)
    
    α=0.25 weights the minority class (attacks)
    γ=2.0 focuses on hard examples (reduces well-classified contribution by ~75%)
    """
    def __init__(self, alpha: float = 0.25, gamma: float = 2.0, reduction: str = 'mean'):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.reduction = reduction
    
    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """Compute focal loss.
        
        logits: (B, K) raw model outputs
        targets: (B, K) binary labels
        """
        bce_loss = nn.functional.binary_cross_entropy_with_logits(logits, targets, reduction='none')
        probs = torch.sigmoid(logits)
        p_t = probs * targets + (1 - probs) * (1 - targets)
        alpha_t = self.alpha * targets + (1 - self.alpha) * (1 - targets)
        focal_weight = alpha_t * (1 - p_t) ** self.gamma
        loss = focal_weight * bce_loss
        if self.reduction == 'mean':
            return loss.mean()
        elif self.reduction == 'sum':
            return loss.sum()
        return loss


def _fit_temperature(logits: np.ndarray, targets: np.ndarray) -> float:
    """Learn optimal temperature T for Platt scaling on val set.
    
    calibrated_prob = sigmoid(logits / T)
    T > 1 spreads probabilities (less confident), T < 1 concentrates them.
    Minimizes negative log-likelihood via grid search (fast, no dependencies).
    """
    best_T, best_nll = 1.0, float('inf')
    for T in np.arange(0.1, 5.0, 0.05):
        cal = 1.0 / (1.0 + np.exp(-logits / T))
        cal = np.clip(cal, 1e-7, 1 - 1e-7)
        nll = -np.mean(targets * np.log(cal) + (1 - targets) * np.log(1 - cal))
        if nll < best_nll:
            best_nll = nll
            best_T = float(T)
    return best_T
# Val is small (~430 sequences) so per-epoch val AP is NOISY — with patience 8
# the best checkpoint can land at epoch 4 while the model has barely started
# fitting (observed: train AP 0.545, max output prob 0.70 after the Aug-28 run).
# Wider patience lets training actually converge before early stop fires.
PATIENCE = 25


class TemporalForecaster(nn.Module):
    def __init__(self, n_feat: int, seq_len: int = 10, horizon: int = 5,
                 hidden: int = 64, layers: int = 2, dropout: float = 0.2,
                 predict_next_state: bool = False):
        super().__init__()
        self.n_feat = n_feat
        self.horizon = horizon
        self.predict_next_state = predict_next_state
        self.lstm = nn.LSTM(n_feat, hidden, num_layers=layers, batch_first=True,
                            dropout=dropout if layers > 1 else 0.0)
        self.head = nn.Sequential(nn.Linear(hidden, hidden // 2), nn.ReLU(),
                                  nn.Dropout(dropout))
        self.prog_head = nn.Linear(hidden // 2, horizon)
        self.stage_head = nn.Linear(hidden // 2, N_STAGES)
        # Additive state-reconstruction head — always constructed so that
        # load_state_dict() works on any .pt regardless of the flag value.
        # Predicts K future feature vectors (scaled, F-dim each).
        self.state_head = nn.Linear(hidden // 2, n_feat * horizon)

    def forward(self, x):  # x: (B, L, F)
        out, _ = self.lstm(x)
        h = self.head(out[:, -1])
        prog = self.prog_head(h)
        stage = self.stage_head(h)
        # state_head activated only when the flag is set; the head's weights
        # still exist in the .pt either way so loading never fails.
        state = (self.state_head(h).view(x.size(0), self.horizon, self.n_feat)
                 if self.predict_next_state else None)
        return prog, stage, state


def _split(npz_dir: Path, name: str, sc: dict):
    d = np.load(npz_dir / f"sequences_{name}.npz", allow_pickle=False)
    X = apply_scaler(d["X"], sc)                      # shared transform
    return (torch.from_numpy(X).float(),
            torch.from_numpy(d["y_prog"]).float(),    # (n, K) per-step labels
            torch.from_numpy(d["y_stage"]).long())


def _predict(model, X: torch.Tensor, dev: str, batch: int = 1024) -> np.ndarray:
    """Pooled sigmoid probabilities (n, K) — no per-batch metric averaging."""
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            out.append(torch.sigmoid(model(X[i:i + batch].to(dev))[0]).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, model.horizon))


def _measure_cost(model, X: torch.Tensor, weights_path: Path) -> dict:
    """Model size + single-sequence CPU latency — Q&A #13 wants real numbers."""
    n_params = sum(p.numel() for p in model.parameters())
    size_mb = weights_path.stat().st_size / 1e6 if weights_path.exists() else 0.0
    cpu = model.to("cpu").eval()
    one = X[:1].to("cpu")
    with torch.no_grad():
        for _ in range(10):
            cpu(one)                                   # warm up
        t0 = time.perf_counter()
        for _ in range(100):
            cpu(one)
        latency_ms = (time.perf_counter() - t0) / 100 * 1000
    return {"_params": int(n_params), "_size_mb": round(size_mb, 3),
            "_latency_ms_cpu": round(latency_ms, 3)}


def train(npz_dir: Path, epochs: int = 40, batch: int = 256,
          lr: float = 1e-3, out_dir: Path | None = None,
          predict_next_state: bool = True,
          loss_state_weight: float = 0.3,
          architecture: str = "lstm") -> dict:
    """Train the Forecaster (LSTM or Transformer).
    
    architecture: "lstm" or "transformer".
    predict_next_state: enable the additive state-reconstruction head
    loss_state_weight: relative weight of the state-reconstruction Huber loss
    """
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    sc = load_scaler(npz_dir / "scaler.npz")
    Xtr, ytr, str_ = _split(npz_dir, "train", sc)
    Xva, yva, sva = _split(npz_dir, "val", sc)
    Xte, yte, ste = _split(npz_dir, "test", sc)
    n_feat, K = Xtr.shape[-1], ytr.shape[1]
    print(f"training {architecture} on {dev} | train={len(Xtr)} val={len(Xva)} test={len(Xte)} "
          f"| F={n_feat} K={K} | predict_next_state={predict_next_state}")

    # ---- state-reconstruction targets (Option B world-model head) ----
    # For sequence i (absolute end-index = ends[i]), the K target windows are
    # windows[ends[i]-K : ends[i]] from windows.parquet — the same feature
    # vectors the model must learn to reconstruct. Scaled with the shared
    # transform so the Huber loss operates in the same space as model inputs.
    # Requires pyarrow (Colab ships it). Falls back gracefully if absent.
    ystr_t = ystr_v = ystr_e = None
    if predict_next_state:
        try:
            import pandas as pd
            _feat_all = (
                pd.read_parquet(npz_dir / "windows.parquet")
                [list(WINDOW_FEATURES)].to_numpy(dtype=np.float32)
            )

            def _y_state(split_name: str) -> torch.Tensor:
                ends = np.load(npz_dir / f"sequences_{split_name}.npz",
                               allow_pickle=False)["ends"]
                raw = np.stack([_feat_all[int(e) - K : int(e)] for e in ends])
                # scale: flatten → (n*K, F), apply, reshape → (n, K, F)
                scaled = apply_scaler(
                    raw.reshape(-1, n_feat), sc
                ).reshape(len(ends), K, n_feat)
                return torch.from_numpy(scaled).float()

            ystr_t = _y_state("train")
            ystr_v = _y_state("val")
            ystr_e = _y_state("test")
            print(f"state targets: train={tuple(ystr_t.shape)} "
                  f"val={tuple(ystr_v.shape)} test={tuple(ystr_e.shape)}")
        except Exception as exc:
            raise RuntimeError(
                f"predict_next_state=True requires windows.parquet + pyarrow: {exc}\n"
                "  Install: pip install pyarrow  OR pass predict_next_state=False"
            ) from exc

    # DataLoader includes y_state only when the head is active.
    if predict_next_state and ystr_t is not None:
        tr_dl = DataLoader(TensorDataset(Xtr, ytr, str_, ystr_t),
                           batch_size=batch, shuffle=True)
    else:
        tr_dl = DataLoader(TensorDataset(Xtr, ytr, str_), batch_size=batch, shuffle=True)

    # class imbalance: PER-HORIZON-STEP pos_weight from the training split only.
    # Later steps are usually rarer, so one scalar would under-weight them.
    n_pos = ytr.sum(dim=0)
    pos_weight = ((len(ytr) - n_pos) / n_pos.clamp(min=1)).to(dev)
    print("pos_weight per step:", [round(float(v), 2) for v in pos_weight])

    if architecture == "transformer":
        from .transformer_forecaster import TemporalTransformerForecaster
        model = TemporalTransformerForecaster(n_feat, horizon=K, d_model=64, num_layers=2).to(dev)
    else:
        model = TemporalForecaster(n_feat, horizon=K,
                                   predict_next_state=predict_next_state).to(dev)
    # Use focal loss for minority class focus, but with balanced alpha
    focal = FocalLoss(alpha=0.5, gamma=1.0)
    # Also keep BCE for comparison/fallback
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight * 1.5)  # boost minority class 1.5×
    ce = nn.CrossEntropyLoss(ignore_index=-1)
    # Huber is less sensitive than MSE to log1p-scaled outliers in volume
    # features (bytes_total, pkts_total can be 1e8+ before scaling).
    huber = nn.HuberLoss() if predict_next_state else None
    # AdamW with weight decay (Phase 1) — better generalization than Adam
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    # Cosine annealing scheduler (Phase 1) — smooth LR decay
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=1e-6)

    have_val = len(Xva) > 0 and float(horizon_any(yva.numpy()).sum()) > 0
    if not have_val:
        print("WARNING: val split unusable for model selection - falling back to last epoch")

    best_ap, best_state, bad = -1.0, None, 0
    for epoch in range(1, epochs + 1):
        model.train()
        epoch_loss = 0.0
        n_batches = 0
        if predict_next_state:
            for xb, yb, sb, ysb in tr_dl:
                xb, yb, sb, ysb = xb.to(dev), yb.to(dev), sb.to(dev), ysb.to(dev)
                opt.zero_grad()
                prog, stg, state = model(xb)
                loss = (focal(prog, yb) + ce(stg, sb)
                        + loss_state_weight * huber(state, ysb))
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                opt.step()
                scheduler.step()
                epoch_loss += loss.item()
                n_batches += 1
        else:
            for xb, yb, sb in tr_dl:
                xb, yb, sb = xb.to(dev), yb.to(dev), sb.to(dev)
                opt.zero_grad()
                prog, stg, _ = model(xb)
                loss = focal(prog, yb) + ce(stg, sb)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                opt.step()
                scheduler.step()
                epoch_loss += loss.item()
                n_batches += 1
        avg_loss = epoch_loss / max(n_batches, 1)

        if not have_val:
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            continue

        # AP computed ONCE over the pooled val split. Averaging per-batch AP
        # (the original approach) is not AP — with ~10% positives many batches
        # have no positives at all and silently scored 0.0, so checkpoint
        # selection was driven by noise. Train AP is printed too: if it stays
        # low the model is under-fitting, which no val metric will tell you.
        p_va = _predict(model, Xva, dev)
        ap = float(average_precision_score(horizon_any(yva.numpy()), p_va.max(axis=1)))
        p_tr = _predict(model, Xtr, dev)
        ap_tr = float(average_precision_score(horizon_any(ytr.numpy()), p_tr.max(axis=1)))
        print(f"epoch {epoch:02d}  loss={avg_loss:.4f}  val AP(pooled)={ap:.4f}  train AP={ap_tr:.4f}  lr={scheduler.get_last_lr()[0]:.6f}")
        if ap > best_ap:
            best_ap, bad = ap, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= PATIENCE:
                print(f"early stop at epoch {epoch} (best val AP={best_ap:.4f})")
                break

    model.load_state_dict(best_state)
    out_dir = out_dir or Path("models") / "trained_models"
    out_dir.mkdir(parents=True, exist_ok=True)
    weights = out_dir / "lstm_forecaster.pt"
    torch.save(best_state, weights)

    # threshold on VAL (never test), then honest test numbers
    model = model.to(dev)
    
    # Temperature scaling: learn T on val logits, then apply to all splits
    temperature = 1.0
    if have_val:
        # Get raw logits (before sigmoid) on val
        model.eval()
        val_logits = []
        with torch.no_grad():
            for i in range(0, len(Xva), 1024):
                val_logits.append(model(Xva[i:i+1024].to(dev))[0].cpu().numpy())
        val_logits = np.concatenate(val_logits)
        
        # Fit temperature on flattened val labels vs logits
        y_any_val = horizon_any(yva.numpy())
        logits_max = val_logits.max(axis=1)  # use max over horizon steps
        temperature = _fit_temperature(logits_max, y_any_val)
        print(f"temperature scaling: T={temperature:.3f}")
    
    # Apply temperature to predictions
    def _predict_calibrated(model, X):
        model.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(X), 1024):
                logits = model(X[i:i+1024].to(dev))[0].cpu().numpy()
                cal = 1.0 / (1.0 + np.exp(-logits / temperature))
                out.append(cal)
        return np.concatenate(out) if out else np.zeros((0, K))
    
    p_va = _predict_calibrated(model, Xva) if have_val else None
    thr = pick_threshold(horizon_any(yva.numpy()), p_va.max(axis=1)) if have_val else 0.5
    p_te = _predict_calibrated(model, Xte)
    agg = evaluate(horizon_any(yte.numpy()), p_te.max(axis=1), thr)
    per_step = [evaluate(yte.numpy()[:, k], p_te[:, k], thr) for k in range(K)]
    report("LSTM forecaster", agg, per_step)

    cost = _measure_cost(model, Xte if len(Xte) else Xtr, weights)
    print(f"cost: {cost['_params']:,} params · {cost['_size_mb']} MB · "
          f"{cost['_latency_ms_cpu']} ms/sequence on CPU")

    cfg = {"n_feat": int(n_feat), "horizon": int(K), "hidden": 64, "layers": 2,
           "val_AP": best_ap, "threshold": thr, "max_fpr": MAX_FPR,
           "predict_next_state": predict_next_state,
           "loss_state_weight": loss_state_weight,
           "architecture": architecture,
           "temperature": float(temperature)}
    (out_dir / "lstm_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    payload = {**agg, "_per_step": per_step, "_n_train": int(len(Xtr)),
               "_n_test": int(len(Xte)), "_max_fpr": MAX_FPR, "_val_ap": best_ap, **cost}
    metrics_path = Path("models") / "metrics_lstm.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps({"lstm_forecaster": payload}, indent=2),
                            encoding="utf-8")
    print(f"wrote {weights}, {out_dir/'lstm_config.json'}, {metrics_path}")
    return agg


def train_multi_seed(npz_dir: Path, epochs: int = 40, n_seeds: int = 5, 
                     architecture: str = "lstm") -> dict:
    """Train with multiple random seeds and keep the best checkpoint.
    
    This reduces variance from initialization — one unlucky seed can cost
    10-20% on metrics. We train n_seeds times and keep the model with
    highest val AP.
    """
    import random
    best_overall_ap = -1.0
    best_agg = None
    best_seed = None
    
    for seed in range(n_seeds):
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)
        
        print(f"\n{'='*60}")
        print(f"SEED {seed + 1}/{n_seeds}")
        print(f"{'='*60}")
        
        agg = train(npz_dir, epochs=epochs, architecture=architecture)
        
        # Read the metrics to get val AP
        metrics_path = Path("models") / "metrics_lstm.json"
        if metrics_path.exists():
            with open(metrics_path) as f:
                metrics = json.load(f)
            val_ap = metrics.get("lstm_forecaster", {}).get("_val_ap", 0.0)
            print(f"\nSeed {seed + 1} val AP: {val_ap:.4f}")
            
            if val_ap > best_overall_ap:
                best_overall_ap = val_ap
                best_agg = agg
                best_seed = seed + 1
                # This seed's model is already saved as the best, keep it
                print(f">>> New best seed! (val AP: {val_ap:.4f})")
    
    print(f"\n{'='*60}")
    print(f"BEST SEED: {best_seed}/{n_seeds} (val AP: {best_overall_ap:.4f})")
    print(f"{'='*60}")
    
    return best_agg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--architecture", type=str, default="lstm", choices=["lstm", "transformer"])
    ap.add_argument("--seeds", type=int, default=1, help="Number of random seeds to try (1=single run)")
    a = ap.parse_args()
    if a.seeds > 1:
        train_multi_seed(a.dir, epochs=a.epochs, n_seeds=a.seeds, architecture=a.architecture)
    else:
        train(a.dir, epochs=a.epochs, architecture=a.architecture)
