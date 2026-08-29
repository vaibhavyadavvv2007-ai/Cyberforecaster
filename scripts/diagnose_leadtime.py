"""Is pre-onset warning POSSIBLE on this dataset? — diagnostic, not a benchmark.

Lead time is 0 for every model. Two very different explanations:

  (a) the model is too weak, or
  (b) the dataset contains no precursors: CIC-IDS2018 attacks are scripted and
      begin abruptly, so the 10 input windows before an onset are ordinary
      benign traffic — no signal exists to warn from.

This script distinguishes them: for every onset in val/test it prints the
model's forecast probabilities made from PRE-onset anchors, plus the maximum
probability the model assigns to any pre-onset step. If pre-onset
probabilities never approach the threshold — and the inputs are by
construction attack-free — the honest conclusion is (b): the metric needs a
different anchor (escalation/peak) or more precursor-bearing data.

Usage (from repo root):
  python scripts/diagnose_leadtime.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass

from src.evaluation.lead_time import find_onsets, reconstruct_window_labels  # noqa: E402
from src.features.scaling import apply_scaler, load_scaler  # noqa: E402
from src.forecasting.rollout import load_model  # noqa: E402

PROC = ROOT / "data" / "processed"


def main() -> None:
    import torch

    sc = load_scaler(PROC / "scaler.npz")
    model, cfg = load_model()
    if model is None:
        raise SystemExit(f"no trained model: {cfg}")
    thr = float(cfg.get("threshold", 0.5))
    print(f"model loaded; alert threshold (picked on val) = {thr:.3f}\n")

    for split in ("val", "test"):
        d = np.load(PROC / f"sequences_{split}.npz", allow_pickle=False)
        K = int(d["horizon"])
        ends, y = d["ends"], d["y_prog"]
        with torch.no_grad():
            X = torch.from_numpy(apply_scaler(d["X"], sc)).float()
            p = torch.sigmoid(model(X)[0]).numpy()

        attack = reconstruct_window_labels(ends, y, K)
        onsets = find_onsets(attack)
        anchors = (ends - K - 1).astype(int)
        idx_of = {int(a): i for i, a in enumerate(anchors)}
        print(f"[{split}] {len(onsets)} onset(s)")
        for w in onsets:
            pre = [(j, float(p[idx_of[w - j], j - 1]))
                   for j in range(1, K + 1) if (w - j) in idx_of]
            if not pre:
                print(f"  onset {w}: no pre-onset anchor exists in this split")
                continue
            detail = ", ".join(f"j={j} p={v:.3f}" for j, v in pre)
            best = max(v for _, v in pre)
            verdict = "WARNED" if best >= thr else "no warning"
            print(f"  onset {w}: {detail}  -> max pre-onset p={best:.3f} ({verdict})")
        # Also: highest probability the model EVER assigns to a pre-onset step
        all_pre = [float(p[idx_of[w - j], j - 1])
                   for w in onsets for j in range(1, K + 1) if (w - j) in idx_of]
        if all_pre:
            print(f"  max pre-onset probability across all onsets: {max(all_pre):.3f}")
        print()

    print("Reading: if pre-onset probabilities sit far below the threshold, the input")
    print("windows carry no precursor signal (scripted attacks start abruptly).")
    print("Pre-onset warning then needs different data, not a bigger model. The")
    print("forecast value on THIS dataset is trajectory shape: persistence and")
    print("recovery of an ongoing attack, plus per-step decay — report that.")


if __name__ == "__main__":
    main()
