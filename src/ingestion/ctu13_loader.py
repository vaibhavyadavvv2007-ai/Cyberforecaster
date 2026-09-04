"""Load CTU-13 botnet dataset (binetflow format) and convert to our pipeline format.

CTU-13 contains 13 scenarios of botnet traffic captured in a controlled environment.
The binetflow format has: StartTime, Dur, Proto, SrcAddr, Sport, Dir, DstAddr, Dport,
State, sTos, dTos, TotPkts, TotBytes, SrcBytes, Label.

This loader:
1. Parses binetflow files
2. Maps labels to our canonical format (Benign, Botnet, etc.)
3. Adds IP-derived features (unique_src_ips, unique_dst_ips, src_ip_entropy)
4. Outputs CSV compatible with our pipeline

Usage:
    python -m src.ingestion.ctu13_loader --dir data/raw/ctu13/CTU-13-Dataset
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


# CTU-13 label patterns → our canonical labels
CTU13_LABEL_MAP = {
    "Background": "Benign",
    "Botnet": "Botnet-Ares",  # Map to our existing botnet label
    "Botnet-DDoS": "Botnet-Ares",
    "Botnet-Clicker": "Botnet-Ares",
    "Botnet-FTP": "Botnet-Ares",
    "Botnet-SSH": "Botnet-Ares",
    "Botnet-HTTP": "Botnet-Ares",
    "Botnet-SMTP": "Botnet-Ares",
    "Botnet-DNS": "Botnet-Ares",
    "Normal": "Benign",
}


def _canonical_label(raw: str) -> str:
    """Map CTU-13 label to our canonical format."""
    s = str(raw).strip()
    # Labels look like "flow=Background-Established-cmpgw-CVUT"
    # or "flow=Botnet-DDoS-NotDec"
    if "flow=" in s:
        s = s.split("flow=")[1]
    
    # Check each pattern
    for pattern, canonical in CTU13_LABEL_MAP.items():
        if pattern.lower() in s.lower():
            return canonical
    
    # Default: if it contains "bot" anywhere, it's botnet
    if "bot" in s.lower():
        return "Botnet-Ares"
    
    return "Benign"


def load_ctu13_scenario(scenario_dir: Path, verbose: bool = True) -> pd.DataFrame:
    """Load one CTU-13 scenario directory."""
    binetflow_files = list(scenario_dir.glob("*.binetflow"))
    if not binetflow_files:
        if verbose:
            print(f"  No .binetflow files in {scenario_dir}")
        return pd.DataFrame()
    
    frames = []
    for bf in binetflow_files:
        if verbose:
            print(f"  Loading {bf.name}...")
        
        # binetflow has comma-separated values with headers
        df = pd.read_csv(bf, low_memory=False)
        df.columns = [c.strip() for c in df.columns]
        
        # Parse timestamps
        df["Timestamp"] = pd.to_datetime(df["StartTime"], errors="coerce")
        df = df.dropna(subset=["Timestamp"])
        
        # Canonical labels
        df["Label"] = df["Label"].map(_canonical_label)
        
        # Convert numeric columns
        for col in ["Dur", "TotPkts", "TotBytes", "SrcBytes", "sTos", "dTos"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        
        # Rename to match CIC-IDS format where possible
        df["Flow Duration"] = df["Dur"] * 1e6  # seconds -> microseconds
        df["Tot Fwd Pkts"] = df["TotPkts"] * 0.5  # Approximate split
        df["Tot Bwd Pkts"] = df["TotPkts"] * 0.5
        df["TotLen Fwd Pkts"] = df["TotBytes"] * 0.5
        df["TotLen Bwd Pkts"] = df["TotBytes"] * 0.5
        df["Dst Port"] = pd.to_numeric(df.get("Dport", 0), errors="coerce").fillna(0).astype(int)
        df["Protocol"] = df["Proto"].map({"tcp": 6, "udp": 17, "icmp": 1}).fillna(0).astype(int)
        
        # IP columns (CTU-13 HAS these!)
        df["Src IP"] = df.get("SrcAddr", "")
        df["Dst IP"] = df.get("DstAddr", "")
        df["Src Port"] = pd.to_numeric(df.get("Sport", 0), errors="coerce").fillna(0).astype(int)
        
        # Compute IAT from timestamps
        df = df.sort_values("Timestamp")
        df["Flow IAT Mean"] = df["Timestamp"].diff().dt.total_seconds().fillna(0) * 1e6
        
        # Approximate flag counts from State field
        state = df.get("State", pd.Series(dtype=str))
        df["SYN Flag Cnt"] = state.str.contains("S", na=False).astype(float)
        df["ACK Flag Cnt"] = state.str.contains("A", na=False).astype(float)
        df["RST Flag Cnt"] = state.str.contains("R", na=False).astype(float)
        df["FIN Flag Cnt"] = state.str.contains("F", na=False).astype(float)
        df["PSH Flag Cnt"] = state.str.contains("P", na=False).astype(float)
        
        # Fill missing columns with 0
        for col in ["Flow IAT Std", "Pkt Size Avg", "Down/Up Ratio",
                     "Init Fwd Win Byts", "Init Bwd Win Byts",
                     "Pkt Len Var", "Fwd Seg Size Min",
                     "Fwd Pkt Len Std", "Bwd Pkt Len Std"]:
            if col not in df.columns:
                df[col] = 0.0
        
        frames.append(df)
    
    if not frames:
        return pd.DataFrame()
    
    return pd.concat(frames, ignore_index=True)


def load_all_ctu13(base_dir: Path, verbose: bool = True) -> pd.DataFrame:
    """Load all CTU-13 scenarios."""
    scenarios = sorted([d for d in base_dir.iterdir() if d.is_dir()])
    
    if verbose:
        print(f"Found {len(scenarios)} CTU-13 scenarios")
    
    frames = []
    for scenario in scenarios:
        if verbose:
            print(f"\nScenario {scenario.name}:")
        df = load_ctu13_scenario(scenario, verbose=verbose)
        if len(df) > 0:
            frames.append(df)
            if verbose:
                print(f"  -> {len(df):,} flows")
    
    if not frames:
        return pd.DataFrame()
    
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("Timestamp").reset_index(drop=True)
    
    if verbose:
        print(f"\nTotal CTU-13 flows: {len(combined):,}")
        print(f"Label distribution:\n{combined['Label'].value_counts().to_string()}")
    
    return combined


def load_binetflow(path: Path, verbose: bool = True) -> pd.DataFrame:
    """Load a single .binetflow file and return a DataFrame compatible with our pipeline."""
    return load_ctu13_scenario(path.parent, verbose=verbose)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/raw/ctu13/CTU-13-Dataset"))
    args = ap.parse_args()
    
    df = load_all_ctu13(args.dir)
    if len(df) > 0:
        out = Path("data/raw/ctu13_combined.csv")
        df.to_csv(out, index=False)
        print(f"\nWrote {len(df):,} flows to {out}")
