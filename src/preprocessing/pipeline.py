"""End-to-end: raw day-file CSVs → cleaned flows → windows → sequences on disk.

Usage:
  python -m src.preprocessing.pipeline --raw data/raw --out data/processed

Outputs:
  <out>/windows.parquet    window aggregates + supervision columns
  <out>/sequences_*.npz    X, y_prog (n,K), y_stage, per split (chronological)
  <out>/scaler.npz         input transform fitted on TRAIN ONLY (see features.scaling)
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd
import numpy as np

from ..features.scaling import degenerate_features, fit_scaler, save_scaler
from ..features.window_builder import (HORIZON, SEQ_LEN, WINDOW_FEATURES,
                                       build_windows, chrono_split, horizon_any,
                                       make_sequences)
from ..ingestion.csv_loader import load_many
from ..attack_mapping.mitre_mapper import STAGES, validate_rules


def run(raw_dir: Path, out_dir: Path, pcap_dir: Path | None = None, bin_secs: int = 60) -> None:
    # If pcap_dir is provided and has .binetflow files, we route through ctu13_loader
    binetflow_files = sorted(pcap_dir.glob("*.binetflow")) if pcap_dir else []
    
    if binetflow_files:
        from ..ingestion.ctu13_loader import load_binetflow
        print(f"\nFound CTU-13 .binetflow files in {pcap_dir}. Using strict CTU-13 loader.")
        dfs = []
        for f in binetflow_files:
            dfs.append(load_binetflow(f))
        flows = pd.concat(dfs, ignore_index=True)
        files = binetflow_files
    else:
        files = sorted(raw_dir.glob("*.csv"))
        if not files:
            raise SystemExit(f"no CSVs under {raw_dir} or .binetflow under {pcap_dir} — run scripts/download_data.py first")
        from ..ingestion.csv_loader import load_many
        flows = load_many(files)
        
    print(f"\nloaded {len(flows):,} flows from {len(files)} files "
          f"({flows['Timestamp'].min()} -> {flows['Timestamp'].max()})")
    print("\nlabel distribution:\n", flows["Label"].value_counts().to_string())

    windows = build_windows(flows, bin_secs=bin_secs)
    print(f"\n{len(windows)} windows ({bin_secs}s bins) × {len(WINDOW_FEATURES)} features "
          f"| attack_frac mean={windows['attack_frac'].mean():.3f}")

    if pcap_dir and pcap_dir.exists():
        from ..features.pcap_parser import extract_packet_features
        pcap_files = sorted(pcap_dir.glob("*.pcap*"))
        if pcap_files:
            print(f"extracting packet features from {len(pcap_files)} pcaps...")
            pcap_dfs = []
            for pf in pcap_files:
                pcap_dfs.append(extract_packet_features(str(pf), bin_secs=bin_secs))
            if pcap_dfs:
                pcap_df = pd.concat(pcap_dfs).groupby('Timestamp').mean().reset_index()
                # Ensure 'Timestamp' aligns with windows.index ('bin')
                pcap_df = pcap_df.set_index('Timestamp')
                
                # Merge into windows, keeping all windows indices. Fill missing with 0
                windows = windows.join(pcap_df, how='left')
                windows.fillna(0, inplace=True)
                
                print(f"successfully merged packet features! Vector size now: {len(WINDOW_FEATURES)}")
    
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

    # Per-horizon-step positive rates. If step K is far rarer than step 1 the
    # forecast task is genuinely harder further out — that's the curve we want.
    print("\npositive rate per horizon step (train / val / test):")
    for k in range(y_prog.shape[1]):
        print(f"  t+{k+1}: {y_prog[tr][:, k].mean():.3f} / "
              f"{y_prog[va][:, k].mean() if len(va) else float('nan'):.3f} / "
              f"{y_prog[te][:, k].mean():.3f}")
    print(f"  any-in-horizon: {horizon_any(y_prog[tr]).mean():.3f} / "
          f"{horizon_any(y_prog[va]).mean() if len(va) else float('nan'):.3f} / "
          f"{horizon_any(y_prog[te]).mean():.3f}")

    out_dir.mkdir(parents=True, exist_ok=True)
    windows.to_parquet(out_dir / "windows.parquet")

    # Input transform fitted on TRAIN sequences ONLY (no leakage), shared by the
    # logistic baseline, the LSTM and the app — see features/scaling.py.
    scaler = fit_scaler(X[tr], list(WINDOW_FEATURES))
    save_scaler(scaler, out_dir / "scaler.npz")
    dead = degenerate_features(scaler)
    if dead:
        print(f"\nWARNING: ZERO-VARIANCE features on train (dead model inputs): {dead}")
        print("   CIC's ML-ready CSVs ship no Src IP/Dst IP columns, so the IP-derived")
        print("   features are constant. They contribute nothing and any rule keyed on")
        print("   them (mitre_mapper lateral-movement) can never fire. See battle plan §5.2.")

    # one npz per split keeps loaders trivial and leak-proof.
    # X stays RAW here (interpretable); the transform is applied at load time.
    # `ends` preserves each sequence's ABSOLUTE window position — without it the
    # lead-time evaluation cannot reconstruct when a warning was issued.
    for name, idx in (("train", tr), ("val", va), ("test", te)):
        np.savez_compressed(
            out_dir / f"sequences_{name}.npz",
            X=X[idx],
            y_prog=y_prog[idx],
            y_stage=y_stage[idx],
            ends=ends[idx],
            seq_len=np.array(SEQ_LEN),
            horizon=np.array(HORIZON),
            feature_names=np.array(WINDOW_FEATURES),
            stages=np.array(STAGES),
        )
    meta = (f"L={SEQ_LEN} K={HORIZON} bin_secs={bin_secs} features={len(WINDOW_FEATURES)} stages={STAGES}\n"
            f"y_prog shape=(n,{HORIZON}) per-horizon-step labels\n"
            f"scaler=scaler.npz (log1p+standardise, fitted on train split only)\n"
            f"zero_variance_features={dead}\n")
    (out_dir / "meta.txt").write_text(meta, encoding="utf-8")
    print(f"\nwrote {out_dir}/windows.parquet + sequences_{{train,val,test}}.npz + scaler.npz")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    ap.add_argument("--pcap-dir", type=Path, default=None, help="Directory containing raw PCAP files to extract packet-level features.")
    ap.add_argument("--bin-secs", type=int, default=60,
                    help="window bin size in seconds (60 = 1 window/minute). "
                         "30s doubles the sequence count; pick ONE and freeze it "
                         "before Gate 1 — models and demo artifacts must agree.")
    a = ap.parse_args()
    run(a.raw, a.out, pcap_dir=a.pcap_dir, bin_secs=a.bin_secs)
