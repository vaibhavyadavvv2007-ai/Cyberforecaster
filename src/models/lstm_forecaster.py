"""Temporal forecaster: 2-layer LSTM → direct multi-horizon heads.

Outputs per input sequence:
  prog_logits (K,) — attack-progression probability for EACH of the next K windows
  stage_logits (n_stages,) — dominant stage over the horizon (multi-task head)

Direct multi-horizon (teacher-forced per-step labels), not recursive
prediction-on-predictions: stable to train and defensible as "risk trajectory".
Recursive latent rollout is the Tier-3 stretch (see forecasting/rollout.py).

Inputs go through the SHARED transform in features/scaling.py — the same one the
logistic baseline uses. Feeding this model raw features (as it originally did)
while the baseline got StandardScaler made the PS-required benchmark unfair
against our own hero model.

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
          loss_state_weight: float = 0.3) -> dict:
    """Train the TemporalForecaster.

    predict_next_state: enable the additive state-reconstruction head
        (Option B world-model gap fix). Set False to reproduce old behaviour
        exactly — useful as a safety net if the head hurts existing metrics.
    loss_state_weight: relative weight of the state-reconstruction Huber loss
        vs. the BCE+CE sum.  Suggested sweep: {0.1, 0.3, 0.5}.
        Too high → state head dominates and progression recall drops.
        Too low → head exists but learns nothing useful.
    """
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    sc = load_scaler(npz_dir / "scaler.npz")
    Xtr, ytr, str_ = _split(npz_dir, "train", sc)
    Xva, yva, sva = _split(npz_dir, "val", sc)
    Xte, yte, ste = _split(npz_dir, "test", sc)
    n_feat, K = Xtr.shape[-1], ytr.shape[1]
    print(f"training on {dev} | train={len(Xtr)} val={len(Xva)} test={len(Xte)} "
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

    model = TemporalForecaster(n_feat, horizon=K,
                               predict_next_state=predict_next_state).to(dev)
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    ce = nn.CrossEntropyLoss(ignore_index=-1)
    # Huber is less sensitive than MSE to log1p-scaled outliers in volume
    # features (bytes_total, pkts_total can be 1e8+ before scaling).
    huber = nn.HuberLoss() if predict_next_state else None
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    have_val = len(Xva) > 0 and float(horizon_any(yva.numpy()).sum()) > 0
    if not have_val:
        print("WARNING: val split unusable for model selection - falling back to last epoch")

    best_ap, best_state, bad = -1.0, None, 0
    for epoch in range(1, epochs + 1):
        model.train()
        if predict_next_state:
            for xb, yb, sb, ysb in tr_dl:
                xb, yb, sb, ysb = xb.to(dev), yb.to(dev), sb.to(dev), ysb.to(dev)
                opt.zero_grad()
                prog, stg, state = model(xb)
                loss = (bce(prog, yb) + ce(stg, sb)
                        + loss_state_weight * huber(state, ysb))
                loss.backward()
                opt.step()
        else:
            for xb, yb, sb in tr_dl:
                xb, yb, sb = xb.to(dev), yb.to(dev), sb.to(dev)
                opt.zero_grad()
                prog, stg, _ = model(xb)
                loss = bce(prog, yb) + ce(stg, sb)
                loss.backward()
                opt.step()

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
        print(f"epoch {epoch:02d}  val AP(pooled)={ap:.4f}  train AP={ap_tr:.4f}")
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
    p_va = _predict(model, Xva, dev) if have_val else None
    thr = pick_threshold(horizon_any(yva.numpy()), p_va.max(axis=1)) if have_val else 0.5
    p_te = _predict(model, Xte, dev)
    agg = evaluate(horizon_any(yte.numpy()), p_te.max(axis=1), thr)
    per_step = [evaluate(yte.numpy()[:, k], p_te[:, k], thr) for k in range(K)]
    report("LSTM forecaster", agg, per_step)

    cost = _measure_cost(model, Xte if len(Xte) else Xtr, weights)
    print(f"cost: {cost['_params']:,} params · {cost['_size_mb']} MB · "
          f"{cost['_latency_ms_cpu']} ms/sequence on CPU")

    cfg = {"n_feat": int(n_feat), "horizon": int(K), "hidden": 64, "layers": 2,
           "val_AP": best_ap, "threshold": thr, "max_fpr": MAX_FPR,
           "predict_next_state": predict_next_state,
           "loss_state_weight": loss_state_weight}
    (out_dir / "lstm_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    payload = {**agg, "_per_step": per_step, "_n_train": int(len(Xtr)),
               "_n_test": int(len(Xte)), "_max_fpr": MAX_FPR, "_val_ap": best_ap, **cost}
    metrics_path = Path("models") / "metrics_lstm.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps({"lstm_forecaster": payload}, indent=2),
                            encoding="utf-8")
    print(f"wrote {weights}, {out_dir/'lstm_config.json'}, {metrics_path}")
    return agg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--epochs", type=int, default=40)
    a = ap.parse_args()
    train(a.dir, epochs=a.epochs)
