"""Stage-transition lead time — how early is the NEXT attack stage forecast?

Companion to src/evaluation/lead_time.py (which measures attack-ONSET lead
time). This module measures the temporal model's other forecasting claim:
that it anticipates PROGRESSION — the movement of the attack through ATT&CK
stages — before the first labelled occurrence of the new stage.

Definition
----------
A *stage-transition onset* is a window `w` whose true dominant stage (from
windows.parquet `dominant_stage_idx`) is stage `B != none`, while window
`w-1`'s stage is not `B` — the first labelled window of a run of stage B.

    stage_lead(onset w) = max { j in 1..K :
        the sequence anchored at w-j forecast stage B at horizon step j }

For V1 (single stage head over the horizon) the forecast stage is the one
argmax the model produces; for V3 (per-step stage decoders decoded from the
rolled-out future states) step j's own prediction is used. 0 = the model
never named stage B before its first labelled window.

Usage:
  python -m src.evaluation.stage_lead --dir data/processed
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import BIN_SECS
from ..features.scaling import apply_scaler, load_scaler
from ..features.window_builder import make_world_sequences
from ..attack_mapping.mitre_mapper import STAGES


def window_stages(windows: pd.DataFrame) -> np.ndarray:
    """Per-window true stage index; -1 = benign / no stage."""
    return windows["dominant_stage_idx"].to_numpy(dtype=np.int64)


def find_stage_onsets(stages: np.ndarray) -> dict[int, list[int]]:
    """stage index -> sorted list of first-window indices of each run of it.

    Requires an OBSERVED predecessor (`w-1` inside the array) so a stage that
    is active from the very first window is not counted as a fresh transition
    — the model had nothing to anticipate it from.
    """
    onsets: dict[int, list[int]] = {}
    for w in range(1, len(stages)):
        b = stages[w]
        if b < 0 or b == stages[w - 1]:
            continue
        onsets.setdefault(int(b), []).append(w)
    return onsets


def _anchors(ends: np.ndarray, horizon: int) -> dict[int, int]:
    """anchor window index -> sequence row (sequence covers anchor+1..anchor+K)."""
    return {int(a): i for i, a in enumerate(ends - horizon - 1)}


def stage_lead_times(stages: np.ndarray, ends: np.ndarray,
                     pred_stages: np.ndarray, horizon: int) -> dict:
    """Lead-time distribution over all stage-transition onsets.

    pred_stages: (n, K) predicted stage index at each horizon step (for V1,
    the single argmax repeated across steps — see main()).
    """
    idx_of_anchor = _anchors(ends, horizon)
    onsets = find_stage_onsets(stages)

    # Honesty: only count onsets THIS split's anchors could warn about — an
    # onset whose warning anchors all live in another split must not deflate
    # this split's warned_rate (and must not make val/test look identical).
    def _warnable(w: int) -> bool:
        return any((w - j) in idx_of_anchor for j in range(1, horizon + 1))

    flat = [(int(b), w) for b, ws in onsets.items() for w in ws if _warnable(w)]

    leads: list[int] = []
    per_stage: dict[str, list[int]] = {}
    for b, w in flat:
        lead = 0
        for j in range(1, horizon + 1):
            i = idx_of_anchor.get(w - j)
            if i is not None and pred_stages[i, j - 1] == b:
                lead = j                # keep the largest j that named B
        leads.append(lead)
        per_stage.setdefault(STAGES[b] if 0 <= b < len(STAGES) else str(b),
                             []).append(lead)

    arr = np.array(leads, dtype=float)
    warned = arr > 0
    per_stage_out = {}
    for stage, ls in per_stage.items():
        a = np.array(ls, dtype=float)
        w_mask = a > 0
        per_stage_out[stage] = {
            "n_onsets": int(len(a)),
            "n_warned": int(w_mask.sum()),
            "warned_rate": float(w_mask.mean()) if len(a) else 0.0,
            "median_lead_windows": float(np.median(a[w_mask])) if w_mask.any() else 0.0,
        }
    return {
        "n_stage_onsets": int(len(arr)),
        "n_warned": int(warned.sum()),
        "warned_rate": float(warned.mean()) if len(arr) else 0.0,
        "median_lead_windows": float(np.median(arr[warned])) if warned.any() else 0.0,
        "mean_lead_windows": float(arr[warned].mean()) if warned.any() else 0.0,
        "max_lead_windows": float(arr.max()) if len(arr) else 0.0,
        "per_stage": per_stage_out,
    }


def to_minutes(stats: dict, bin_secs: int = BIN_SECS) -> dict:
    m = bin_secs / 60.0
    return {**stats,
            "median_lead_min": round(stats["median_lead_windows"] * m, 2),
            "mean_lead_min": round(stats["mean_lead_windows"] * m, 2),
            "max_lead_min": round(stats["max_lead_windows"] * m, 2)}


def _report(name: str, s: dict) -> None:
    print(f"\n{name}")
    print(f"  stage-transition onsets : {s['n_stage_onsets']}")
    print(f"  warned before onset     : {s['n_warned']} ({s['warned_rate']:.1%})")
    print(f"  median lead (when warned): {s['median_lead_windows']:.1f} windows "
          f"= {s['median_lead_min']:.1f} min")
    for stage, d in s.get("per_stage", {}).items():
        print(f"    {stage:<20} onsets={d['n_onsets']} warned={d['n_warned']} "
              f"median={d['median_lead_windows']:.1f}w")


def main(npz_dir: Path, bin_secs: int = BIN_SECS,
         out_json: Path | None = None) -> dict:
    from ..features.window_builder import chrono_split

    sc = load_scaler(npz_dir / "scaler.npz")
    windows = pd.read_parquet(npz_dir / "windows.parquet")
    X, _Xf, y_prog, y_stage, ends = make_world_sequences(windows)
    Xs = apply_scaler(X, sc)
    stages = window_stages(windows)
    horizon = y_prog.shape[1]
    tr, va, te = chrono_split(windows, ends)
    results: dict[str, dict] = {"bin_secs": int(bin_secs),
                                "stages": list(STAGES)}

    # ---- V1: single stage head, repeated across steps ----
    try:
        import torch
        from ..forecasting.rollout import load_model
        model, cfg = load_model()
        if model is None:
            raise RuntimeError(cfg)
        with torch.no_grad():
            Xt = torch.from_numpy(Xs).float()
            _prog, stage_logits = model(Xt)
            v1_stages = stage_logits.argmax(dim=-1).numpy()  # (n,)
        v1_pred = np.repeat(v1_stages[:, None], horizon, axis=1)  # same at every step
        for split_name, idx in (("test", te), ("val", va)):
            # stage onsets must fall inside the split's window span; the
            # anchors that can warn about them are exactly the split's rows
            s = stage_lead_times(stages, ends[idx], v1_pred[idx], horizon)
            s = to_minutes(s, bin_secs)
            results[f"v1_single_stage_{split_name}"] = s
            _report(f"V1 single-stage head ({split_name} split)", s)
    except Exception as exc:  # noqa: BLE001 — V3 result is still useful alone
        print(f"\n[V1 stage-lead skipped: {exc}]")

    # ---- V3: per-step stage decoded from rolled-out states ----
    try:
        from ..models.rollout_world_model import (load_rollout_model,
                                                  predict_rollout)
        v3, v3cfg = load_rollout_model()
        if v3 is None:
            raise RuntimeError(v3cfg)
        import torch
        _p, stg, _s = predict_rollout(v3, torch.from_numpy(Xs).float(), "cpu")
        for split_name, idx in (("test", te), ("val", va)):
            s = stage_lead_times(stages, ends[idx], stg[idx], horizon)
            s = to_minutes(s, bin_secs)
            results[f"v3_per_step_stage_{split_name}"] = s
            _report(f"V3 per-step stage from state rollout ({split_name} split)", s)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[V3 stage-lead skipped: {exc}]")

    out_json = out_json or (Path("models") / "metrics_stage_lead.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {out_json}")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--bin-secs", type=int, default=BIN_SECS)
    a = ap.parse_args()
    main(a.dir, a.bin_secs)
