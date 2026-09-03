import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

def load_binetflow(csv_path: str | Path) -> pd.DataFrame:
    """
    Loads a CTU-13 Binetflow CSV file and maps it to the internal schema
    expected by window_builder.py.
    """
    df = pd.read_csv(csv_path)
    
    # Standardize column names to match CIC-IDS2018 style mapping where possible
    # CTU-13 has: StartTime, Dur, Proto, SrcAddr, Sport, Dir, DstAddr, Dport, State, sTos, dTos, TotPkts, TotBytes, SrcBytes, Label
    
    df['Timestamp'] = pd.to_datetime(df['StartTime'], errors='coerce')
    
    # Basic numeric flow features
    df['Flow Duration'] = df['Dur'] * 1e6  # convert seconds to microseconds to match CIC
    df['Total Fwd Packets'] = df['TotPkts'] / 2  # Approximate split since CTU-13 doesn't split Fwd/Bwd packets natively
    df['Total Backward Packets'] = df['TotPkts'] / 2
    df['Total Length of Fwd Packets'] = df['SrcBytes']
    df['Total Length of Bwd Packets'] = df['TotBytes'] - df['SrcBytes']
    
    # CTU-13 Labels: typically "Background", "Normal", "Botnet"
    # Stringent Cleaning: Drop all "Background" traffic entirely.
    df = df[~df['Label'].astype(str).str.contains('Background', case=False, na=False)]
    
    # Map remaining to Benign / Botnet
    df['is_attack'] = df['Label'].astype(str).str.contains('Botnet', case=False, na=False)
    df['Label'] = df['is_attack'].apply(lambda x: 'Botnet' if x else 'BENIGN')
    
    # Map Botnet to STAGES (Initial Access, Execution, Persistence, Evasion, C&C, Lateral Movement)
    # Most CTU-13 botnet traffic is C&C or Lateral Movement (port scanning / spam)
    def map_stage(row):
        if not row['is_attack']:
            return ""
        # Very rough approximation based on typical CTU-13 characteristics:
        # High connection rate (scan) -> Lateral Movement
        if row['TotPkts'] < 5 and row['Dur'] < 1.0:
            return "Lateral Movement" 
        # Long duration, steady traffic -> C&C
        return "Command and Control"
        
    df['stage'] = df.apply(map_stage, axis=1)
    
    # TCP Flags: CTU-13 State column encodes this, but it's complex (e.g. CON, INT, FIN, REQ).
    # For now, we will approximate these to zero or extract from State if possible.
    # A true packet parser is meant to supplement this.
    df['Fwd PSH Flags'] = 0
    df['FIN Flag Count'] = df['State'].apply(lambda x: 1 if 'FIN' in str(x) else 0)
    df['SYN Flag Count'] = df['State'].apply(lambda x: 1 if 'REQ' in str(x) or 'CON' in str(x) else 0)
    df['RST Flag Count'] = df['State'].apply(lambda x: 1 if 'RST' in str(x) else 0)
    df['PSH Flag Count'] = 0
    df['ACK Flag Count'] = df['State'].apply(lambda x: 1 if 'CON' in str(x) else 0)
    
    # Ports and IPs
    df['Dst Port'] = pd.to_numeric(df['Dport'], errors='coerce').fillna(0)
    df['Src IP'] = df['SrcAddr']
    df['Dst IP'] = df['DstAddr']
    
    # IAT approximation
    df['Flow IAT Mean'] = df['Flow Duration'] / max(df['TotPkts'].mean(), 1)
    df['Flow IAT Std'] = 0
    df['Flow IAT Max'] = df['Flow IAT Mean']
    df['Flow IAT Min'] = df['Flow IAT Mean']
    
    # Down/Up
    df['Down/Up Ratio'] = df['Total Length of Bwd Packets'] / (df['Total Length of Fwd Packets'] + 1)
    
    # Filter invalid
    df = df.dropna(subset=['Timestamp'])
    df = df.dropna()  # Stringent cleaning: drop any row with NaN values
    df = df.sort_values('Timestamp').reset_index(drop=True)
    
    return df
