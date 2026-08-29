"""Load + clean CSE-CIC-IDS2018 day-file CSVs.

Known mess this module handles (verified against real files):
- header/column names padded with spaces
- duplicate header rows embedded mid-file
- label spelling/casing variants ('SSH-Bruteforce', 'FTP-Brute Force', ...)
- NaN / inf in rate columns
- malformed timestamps
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

BENIGN = "Benign"

# Columns the window builder actually consumes. Files may contain more; we keep
# only these so memory stays sane. Missing columns degrade gracefully — and
# build_windows() now reports which features got zero-filled as a result.
#
# VERIFIED against the real bucket header 2026-08-28:
#   - the average-packet-size column is "Pkt Size Avg", NOT "Avg Pkt Size".
#     The old name silently zero-filled avg_pkt_size for every window.
#   - "Src IP" / "Dst IP" / "Src Port" are genuinely ABSENT from these
#     ML-ready CSVs (battle plan §5.2). They stay listed so the degradation is
#     explicit rather than forgotten.
CORE_COLS = [
    "Timestamp", "Label",
    "Dst Port", "Protocol", "Flow Duration",
    "Tot Fwd Pkts", "Tot Bwd Pkts", "TotLen Fwd Pkts", "TotLen Bwd Pkts",
    "Flow IAT Mean", "Flow IAT Std", "Pkt Size Avg", "Down/Up Ratio",
    "FIN Flag Cnt", "SYN Flag Cnt", "RST Flag Cnt", "PSH Flag Cnt", "ACK Flag Cnt",
    "Src IP", "Src Port", "Dst IP",
]


def _canonical_label(raw: str) -> str:
    """Map the dataset's messy label spellings onto a small canonical set."""
    s = " ".join(str(raw).split()).lower()
    if s.startswith("benign"):
        return BENIGN
    # NOTE: the dataset misspells this "Infilteration" (verified in the real
    # Feb-28/Mar-01 files) — match on the stem so both spellings canonicalize.
    # Unmapped, these 161k flows would lose their Lateral Movement stage label.
    if "infil" in s:
        return "Infiltration"
    if "heartbleed" in s:
        return "Heartbleed"
    if "sql" in s:
        return "SQL-Injection"
    if "xss" in s:
        return "XSS"
    if "brute" in s and ("web" in s or "-web" in s):
        return "Web-Brute Force"
    if s.startswith("ftp") or ("ftp" in s and "brute" in s):
        return "FTP-Brute Force"
    if s.startswith("ssh") or ("ssh" in s and "brute" in s):
        return "SSH-Brute-Force"
    if "bot" in s:
        return "Botnet-Ares"
    if "goldeneye" in s:
        return "DoS-GoldenEye"
    if "hulk" in s:
        return "DoS-Hulk"
    if "slowhttptest" in s:
        return "DoS-Slowhttptest"
    if "slowloris" in s:
        return "DoS-Slowloris"
    if "loic" in s:
        return "DDoS-LOIC"
    if "hoic" in s:
        return "DDoS-HOIC"
    return f"Other:{str(raw)[:40]}"


def load_day_csv(path: str | Path, verbose: bool = True) -> pd.DataFrame:
    """Load one day-file into a clean frame with parsed Timestamp + canonical Label."""
    path = Path(path)
    df = pd.read_csv(path, low_memory=False)

    # strip padding from headers and object values
    df.columns = [c.strip() for c in df.columns]

    # embedded duplicate header rows (e.g. a row whose Dst Port literally says 'Dst Port')
    if "Dst Port" in df.columns:
        dup_header = df["Dst Port"].astype(str).str.strip().eq("Dst Port")
        n_dup = int(dup_header.sum())
        df = df[~dup_header]
    else:
        n_dup = 0

    keep = [c for c in CORE_COLS if c in df.columns]
    missing = [c for c in CORE_COLS if c not in df.columns]
    df = df[keep].copy()

    # canonical labels
    if "Label" not in df.columns:
        raise ValueError(f"{path.name}: no 'Label' column found")
    df["Label"] = df["Label"].map(_canonical_label)
    unknown = int(df["Label"].str.startswith("Other:").sum())

    # timestamps: dd/mm/yyyy hh:mm:ss style — coerce failures to NaT then drop.
    # Epoch artifacts (raw unix seconds) parse "successfully" to 1970 — filter
    # implausible years too, else they poison the earliest windows.
    ts_raw = pd.to_datetime(df["Timestamp"], dayfirst=True, errors="coerce")
    plausible = ts_raw.notna() & (ts_raw.dt.year >= 2010) & (ts_raw.dt.year <= 2035)
    n_bad_ts = int((~plausible).sum())
    df["Timestamp"] = ts_raw.where(plausible)
    df = df.dropna(subset=["Timestamp"])

    # numeric coercion + inf cleanup — NEVER touch identifier strings
    STRING_COLS = {"Timestamp", "Label", "Src IP", "Dst IP"}
    n_bad_num = 0
    for c in keep:
        if c in STRING_COLS:
            continue
        col = pd.to_numeric(df[c].replace([np.inf, -np.inf], np.nan), errors="coerce")
        n_bad_num += int(col.isna().sum())
        df[c] = col
    before = len(df)
    essential = [c for c in ("Dst Port", "Protocol", "Flow Duration") if c in df.columns]
    df = df.dropna(subset=essential)

    if verbose:
        print(f"[{path.name}] rows={len(df):,} (dropped {before - len(df)} unusable, "
              f"{n_dup} embedded headers, {n_bad_ts} bad timestamps, "
              f"{n_bad_num} non-numeric/inf cells, {unknown} unmapped labels)")
        if missing:
            print(f"          missing optional columns: {missing}")
    return df.reset_index(drop=True)


def load_many(paths: list[str | Path]) -> pd.DataFrame:
    """Concatenate several day-files chronologically."""
    frames = [load_day_csv(p) for p in paths]
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values("Timestamp").reset_index(drop=True)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        load_day_csv(p)
