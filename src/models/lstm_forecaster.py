"""Temporal forecaster: 2-layer LSTM → direct multi-horizon heads.

Outputs per input sequence:
  prog_logits (K,) — attack-progression probability for each of the next K windows
  stage_logits (n_stages,) — dominant stage over the horizon (multi-task head)

Direct multi-horizon (teacher-forced labels), not recursive prediction-on-
predictions: stable to train and defensible as "risk trajectory". Recursive
latent rollout is the Tier-3 stretch (see forecasting/rollout.py).

Usage:
  python -m src.models.lstm_forecaster --dir data/processed [--epochs 40]
"""
from __future__ import annotations

import argparse
import json
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

from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score
from ..models.baseline_logreg import evaluate

N_STAGES = 6


class TemporalForecaster(nn.Module):
    def __init__(self, n_feat: int, seq_len: int = 10, horizon: int = 5,
                 hidden: int = 64, layers: int = 2, dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(n_feat, hidden, num_layers=layers, batch_first=True,
                            dropout=dropout if layers > 1 else 0.0)
        self.head = nn.Sequential(nn.Linear(hidden, hidden // 2), nn.ReLU(),
                                  nn.Dropout(dropout))
        self.prog_head = nn.Linear(hidden // 2, horizon)
        self.stage_head = nn.Linear(hidden // 2, N_STAGES)

    def forward(self, x):  # x: (B, L, F)
        out, _ = self.lstm(x)
        h = self.head(out[:, -1])
        return self.prog_head(h), self.stage_head(h)


def _loader(npz_dir: Path, name: str, batch: int, shuffle: bool):
    d = np.load(npz_dir / f"sequences_{name}.npz", allow_pickle=False)
    X = torch.from_numpy(d["X"]).float()
    y = torch.from_numpy(d["y_prog"]).float()
    s = torch.from_numpy(d["y_stage"]).long().clamp(min=-1)
    return DataLoader(TensorDataset(X, y, s), batch_size=batch, shuffle=shuffle)


def train(npz_dir: Path, epochs: int = 40, batch: int = 256,
          lr: float = 1e-3, out_dir: Path | None = None) -> dict:
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"training on {dev}")
    tr_dl = _loader(npz_dir, "train", batch, shuffle=True)
    va_dl = _loader(npz_dir, "val", batch, shuffle=False)
    n_feat = next(iter(tr_dl))[0].shape[-1]

    # class imbalance: pos_weight from the training split only
    n_pos = sum(int((yb > 0).sum()) for _, yb, _ in tr_dl)
    n_all = sum(len(yb) for _, yb, _ in tr_dl)
    pos_weight = torch.tensor([(n_all - n_pos) / max(n_pos, 1)], device=dev)
    print(f"train split: {n_pos}/{n_all} positive windows → pos_weight={pos_weight.item():.2f}")

    model = TemporalForecaster(n_feat).to(dev)
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    ce = nn.CrossEntropyLoss(ignore_index=-1)
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    best_ap, best_state, bad = -1.0, None, 0
    for epoch in range(1, epochs + 1):
        model.train()
        for xb, yb, sb in tr_dl:
            xb, yb, sb = xb.to(dev), yb.to(dev), sb.to(dev)
            opt.zero_grad()
            prog, stg = model(xb)
            loss = bce(prog, yb.unsqueeze(1).expand_as(prog)) + ce(stg, sb)
            loss.backward()
            opt.step()

        model.eval()
        aps, preds, golds = [], [], []
        with torch.no_grad():
            for xb, yb, sb in va_dl:
                prob = torch.sigmoid(model(xb.to(dev))[0]).cpu()
                aps.append(average_precision_score(yb.numpy(), prob.mean(dim=1).numpy())
                           if yb.sum() > 0 else 0.0)
                preds.append((prob.mean(dim=1) >= 0.5).int().numpy())
                golds.append(yb.numpy().astype(int))
        ap = float(np.mean([a for a in aps if not np.isnan(a)]))
        f1 = f1_score(np.concatenate(golds), np.concatenate(preds), zero_division=0)
        print(f"epoch {epoch:02d}  val AP={ap:.4f}  val F1={f1:.4f}")

        if ap > best_ap:
            best_ap, best_state, bad = ap, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 6:
                print(f"early stop at epoch {epoch} (best val AP={best_ap:.4f})")
                break

    out_dir = out_dir or Path("models") / "trained_models"
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, out_dir / "lstm_forecaster.pt")
    cfg = {"n_feat": int(n_feat), "hidden": 64, "layers": 2, "val_AP": best_ap}
    (out_dir / "lstm_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # honest test-split numbers for the benchmark table
    model.load_state_dict(best_state)
    model.eval()
    d = np.load(npz_dir / "sequences_test.npz", allow_pickle=False)
    with torch.no_grad():
        prob = torch.sigmoid(model(torch.from_numpy(d["X"]).float().to(dev))[0]).cpu()
    m = evaluate(d["y_prog"], prob.mean(dim=1).numpy())
    print("\nTEST (chronological):")
    for k, v in m.items():
        print(f"  {k:<10} {v:.4f}" if isinstance(v, float) else f"  {k:<10} {v}")
    metrics_path = Path("models") / "metrics_lstm.json"
    metrics_path.write_text(json.dumps({"lstm": m}, indent=2), encoding="utf-8")
    print(f"wrote {out_dir/'lstm_forecaster.pt'}, {metrics_path}")
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--epochs", type=int, default=40)
    a = ap.parse_args()
    train(a.dir, epochs=a.epochs)
