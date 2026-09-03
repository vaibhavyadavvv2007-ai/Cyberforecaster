import numpy as np
from collections import defaultdict
from scapy.all import PcapReader, IP, TCP, UDP
import pandas as pd
from typing import Dict, Any, List

def extract_packet_features(pcap_path: str, bin_secs: int = 60) -> pd.DataFrame:
    """
    Extracts packet-level features required by the Problem Statement from a PCAP file.
    
    Features extracted per time window:
    - ttl_mean: Average Time-To-Live
    - ttl_var: Variance of Time-To-Live
    - tcp_win_mean: Average TCP window size
    - tcp_win_var: Variance of TCP window size
    - frag_ratio: Ratio of fragmented IP packets
    - payload_size_mean: Average payload size (bytes)
    - payload_size_var: Variance of payload size
    """
    
    # Store raw metrics per time bin
    bins = defaultdict(lambda: {
        'ttls': [],
        'tcp_wins': [],
        'frag_count': 0,
        'total_packets': 0,
        'payload_sizes': []
    })
    
    with PcapReader(pcap_path) as pcap_reader:
        for pkt in pcap_reader:
            try:
                if not IP in pkt:
                    continue
                
                timestamp = float(pkt.time)
                bin_idx = int(timestamp // bin_secs) * bin_secs
                
                b = bins[bin_idx]
                b['total_packets'] += 1
                
                # TTL
                b['ttls'].append(pkt[IP].ttl)
                
                # Fragmentation (More Fragments flag or non-zero fragment offset)
                if pkt[IP].flags == 'MF' or pkt[IP].frag > 0:
                    b['frag_count'] += 1
                    
                # Payload size
                payload_len = len(pkt[IP].payload)
                b['payload_sizes'].append(payload_len)
                
                # TCP specific
                if TCP in pkt:
                    b['tcp_wins'].append(pkt[TCP].window)
            except Exception:
                continue
            
    # Aggregate into DataFrame
    records = []
    for bin_time, b in bins.items():
        total = max(b['total_packets'], 1)
        
        ttl_array = np.array(b['ttls']) if b['ttls'] else np.array([0])
        tcp_win_array = np.array(b['tcp_wins']) if b['tcp_wins'] else np.array([0])
        payload_array = np.array(b['payload_sizes']) if b['payload_sizes'] else np.array([0])
        
        records.append({
            'Timestamp': pd.to_datetime(bin_time, unit='s'),
            'ttl_mean': np.mean(ttl_array),
            'ttl_var': np.var(ttl_array),
            'tcp_win_mean': np.mean(tcp_win_array),
            'tcp_win_var': np.var(tcp_win_array),
            'frag_ratio': b['frag_count'] / total,
            'payload_size_mean': np.mean(payload_array),
            'payload_size_var': np.var(payload_array)
        })
        
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values('Timestamp').reset_index(drop=True)
    return df
