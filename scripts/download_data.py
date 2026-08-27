"""Prioritized downloader for CSE-CIC-IDS2018.

Usage:
  python scripts/download_data.py --list        # inspect bucket contents + sizes (pull nothing)
  python scripts/download_data.py --yes         # download curated list from configs/data_sources.yaml

Never pulls anything without --yes, so nobody burns bandwidth on a 7GB surprise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CONFIG = ROOT / "configs" / "data_sources.yaml"

BUCKET = "cse-cic-ids2018"
# verified 2026-08-26: bucket root has two folders; ML CSVs live under this one
PREFIX = "Processed Traffic Data for ML Algorithms"


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def list_bucket() -> list[tuple[str, int]] | None:
    """Return [(key, size_bytes)] for the CSV prefix, or None if boto3 unavailable."""
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.client import Config
    except ImportError:
        return None
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    out: list[tuple[str, int]] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].lower().endswith(".csv"):
                out.append((obj["Key"], obj["Size"]))
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="show bucket contents and exit")
    ap.add_argument("--yes", action="store_true", help="actually download")
    args = ap.parse_args()

    entries = list_bucket()
    if entries is None:
        print("`boto3` missing — pip install boto3 — or run manually:")
        print(f'  aws s3 ls s3://{BUCKET}/{PREFIX}/ --human-readable --summarize')
        print(f"Console: https://console.aws.amazon.com/s3/buckets/{BUCKET}")
        sys.exit(1)

    print(f"{len(entries)} CSVs under s3://{BUCKET}/{PREFIX}/:\n")
    total = 0
    for key, size in entries:
        total += size
        print(f"  {_human(size):>10}  {key}")
    print(f"\nTotal: {_human(total)} across {len(entries)} files")

    if args.list or not args.yes:
        print("\n(list mode — nothing downloaded). Edit configs/data_sources.yaml, then rerun with --yes.")
        return

    import yaml
    plan = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    wanted = [f["key"] for f in plan.get("files", [])]
    sizes = dict(entries)
    missing = [k for k in wanted if k not in sizes]
    if missing:
        print("WARNING — not found in bucket (fix paths in data_sources.yaml):")
        for k in missing:
            print("  ", k)
    wanted = [k for k in wanted if k in sizes]
    planned_total = sum(sizes[k] for k in wanted)
    print(f"\nPulling {len(wanted)} files, {_human(planned_total)} total into {RAW}")

    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.client import Config
        s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    except ImportError:
        sys.exit("boto3 required for download: pip install boto3")

    RAW.mkdir(parents=True, exist_ok=True)
    for key in wanted:
        dest = RAW / Path(key).name
        if dest.exists():
            print(f"  skip (exists): {dest.name}")
            continue
        print(f"  downloading {dest.name} ({_human(sizes[key])}) ...", flush=True)
        s3.download_file(BUCKET, key, str(dest))

    print("\nDone. Next: python -m src.preprocessing.pipeline --raw data/raw --out data/processed")


if __name__ == "__main__":
    main()
