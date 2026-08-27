"""Per-day diagnostics: labels, time coverage, windows, rule validation.

Usage (from repo root):
  python scripts/day_report.py                          # all files in data/raw
  python scripts/day_report.py data/raw/Wednesday-14-02-2018_TrafficForML_CICFlowMeter.csv
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.attack_mapping.mitre_mapper import validate_rules
from src.features.window_builder import build_windows
from src.ingestion.csv_loader import load_many


def main() -> None:
    raw = Path("data/raw")
    files = [Path(a) for a in sys.argv[1:]] or sorted(raw.glob("*.csv"))
    if not files:
        raise SystemExit("no CSVs found — download first")

    t0 = time.time()
    flows = load_many(files)
    print(f"\n{len(flows):,} flows in {time.time()-t0:.0f}s")
    print("time range:", flows["Timestamp"].min(), "->", flows["Timestamp"].max())
    print("\nLABEL COUNTS:")
    print(flows["Label"].value_counts().to_string())

    windows = build_windows(flows)
    att = windows["attack_frac"]
    print(f"\nwindows={len(windows)}  attack_windows={(att > 0).sum()} "
          f"mean={att.mean():.4f} p99={att.quantile(0.99):.3f} max={att.max():.3f}")
    print("\nper-day window coverage:")
    per_day = windows.groupby(windows.index.date)["attack_frac"].agg(["count", lambda s: (s > 0).sum()])
    per_day.columns = ["windows", "attack_windows"]
    print(per_day.to_string())

    try:
        validate_rules(windows)
    except Exception as exc:  # noqa: BLE001
        print(f"rule validation skipped: {exc}")


if __name__ == "__main__":
    main()
