"""End-to-end: raw day-file CSVs → cleaned flows → windows → sequences on disk.

Usage:
  python -m src.preprocessing.pipeline --raw data/raw --out data/processed

Outputs:
  <out>/windows.parquet    window aggregates + supervision columns
  <out>/sequences.npz      X, y_prog, y_stage, ends + chronological split indices
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from ..features.window_builder import (HORIZON, SEQ_LEN, WINDOW_FEATURES,
                                       build_windows, chrono_split, make_sequences)
from ..ingestion.csv_loader import load_many
from ..attack_mapping.mitre_mapper import STAGES, validate_rules


def run(raw_dir: Path, out_dir: Path) -> None:
    files = sorted(raw_dir.glob("*.csv"))
    if not files:
        raise SystemExit(f"no CSVs under {raw_dir} — run scripts/download_data.py first")

    flows = load_many(files)
    print(f"\nloaded {len(flows):,} flows from {len(files)} files "
          f"({flows['Timestamp'].min()} → {flows['Timestamp'].max()})")
    print("\nlabel distribution:\n", flows["Label"].value_counts().to_string())

    windows = build_windows(flows)
    print(f"\n{len(windows)} windows × {len(WINDOW_FEATURES)} features "
          f"| attack_frac mean={windows['attack_frac'].mean():.3f}")

    # sanity-check the rule engine against dataset labels while we're here
    try:
        validate_rules(windows)
    except Exception as exc:  # noqa: BLE001 — validation must never block the pipeline
        print(f"[rule validation skipped: {exc}]")

    X, y_prog, y_stage, ends = make_sequences(windows)
    tr, va, te = chrono_split(windows, ends)
    print(f"sequences: total={len(X)} train={len(tr)} val={len(va)} test={len(te)} "
          f"(purged at day boundaries)")
    if len(tr) == 0 or len(te) == 0:
        raise SystemExit("empty split — need more data or fewer boundary collisions")

    out_dir.mkdir(parents=True, exist_ok=True)
    windows.to_parquet(out_dir / "windows.parquet")

    # one npz per split keeps loaders trivial and leak-proof
    for name, idx in (("train", tr), ("val", va), ("test", te)):
        np.savez_compressed(
            out_dir / f"sequences_{name}.npz",
            X=X[idx],
            y_prog=y_prog[idx],
            y_stage=y_stage[idx],
            feature_names=np.array(WINDOW_FEATURES),
            stages=np.array(STAGES),
        )
    meta = f"L={SEQ_LEN} K={HORIZON} features={len(WINDOW_FEATURES)} stages={STAGES}\n"
    (out_dir / "meta.txt").write_text(meta, encoding="utf-8")
    print(f"\nwrote {out_dir}/windows.parquet + sequences_{{train,val,test}}.npz")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    a = ap.parse_args()
    run(a.raw, a.out)
