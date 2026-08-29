"""Precompute every demo scenario's real prediction into a JSON cache.

This is win-condition W1's fallback: with `data/processed/demo_cache.json` in
place the app renders genuine model output with no torch, no GPU and no
inference at demo time — deterministic and instant. It is NOT simulated data;
it is this model's real predictions, frozen.

Run it AFTER training, and re-run it after any retrain:
  python scripts/build_demo_cache.py

The app badges itself CACHED (not REAL) when it falls back to this, so the
distinction stays visible to the jury.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.features.window_builder import WINDOW_FEATURES          # noqa: E402
from src.forecasting.rollout import Forecaster                   # noqa: E402
from src.forecasting.scenarios import build_scenarios, sequence_at  # noqa: E402

PROC = ROOT / "data" / "processed"


def main(top_k: int = 6) -> None:
    import pandas as pd

    wpath = PROC / "windows.parquet"
    if not wpath.exists():
        raise SystemExit(f"no {wpath} — run the pipeline first")
    windows = pd.read_parquet(wpath)

    fc, err = Forecaster.load()
    if fc is None:
        raise SystemExit(
            f"cannot load model/transform: {err}\n"
            "The cache must contain REAL predictions — refusing to write simulated "
            "values that would be indistinguishable from inference at demo time."
        )

    try:
        from src.explainability.attribution import integrated_gradients_attribution
        have_ig = True
    except Exception as exc:  # noqa: BLE001
        print(f"[attribution unavailable, caching forecasts only: {exc}]")
        have_ig = False

    scenarios = build_scenarios(windows)
    print(f"caching {len(scenarios)} scenarios (threshold={fc.threshold:.3f})")
    out: dict[str, dict] = {}
    for s in scenarios:
        seq = sequence_at(windows, s["anchor"])
        res = fc.predict(seq)
        entry = {"probs": res["probs"], "stage": res["stage"],
                 "threshold": res["threshold"], "anchor": int(s["anchor"]),
                 "name": s["name"], "kind": s["kind"]}
        if have_ig:
            try:
                attr = integrated_gradients_attribution(fc.model, fc.scaled(seq))
                order = np.argsort(-np.abs(attr))[:top_k]
                entry["why"] = [[WINDOW_FEATURES[i], round(float(abs(attr[i])), 6)]
                                for i in order]
            except Exception as exc:  # noqa: BLE001 — a forecast alone still beats nothing
                print(f"  [{s['id']}] attribution failed: {exc}")
        peak = max(entry["probs"])
        flag = "CROSSES" if peak >= entry["threshold"] else "below   "
        print(f"  {flag}  {s['id']:<14} peak={peak:.3f}  stage={entry['stage'] or '—':<18} "
              f"{s['name']}")
        out[s["id"]] = entry

    payload = {"threshold": fc.threshold, "horizon": fc.horizon,
               "n_feat": fc.n_feat, "scenarios": out}
    dest = PROC / "demo_cache.json"
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    crossing = sum(1 for e in out.values() if max(e["probs"]) >= e["threshold"])
    print(f"\nwrote {dest}  ({crossing}/{len(out)} scenarios cross the threshold)")
    if crossing == 0:
        print("WARNING: NO scenario crosses the alert threshold. Your demo has no forecast")
        print("    moment (W2). Check: did the model train? is the threshold too high?")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=6, help="features kept per WHY panel")
    a = ap.parse_args()
    main(a.top_k)
