"""Flows → time-window aggregates → sliding sequences.

This is the heart of the project: the point where per-flow classification
(the thing the PS rejects) becomes temporal state evolution (the thing the PS
asks for).

Design locked in the battle plan (§5.3):
- 60-second bins, ~24 aggregate features per window
- input sequence L=10 windows, forecast horizon K=5 windows
- chronological split ONLY, with boundary purge so overlapping sequences
  cannot leak future information into training
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..attack_mapping.mitre_mapper import AUTH_PORTS, FAMILY_STAGE, STAGES

SEQ_LEN = 10   # L: windows of history fed to the model
HORIZON = 5    # K: windows forecast ahead

WINDOW_FEATURES = [
    "flow_count", "bytes_total", "pkts_total", "duration_mean",
    "syn_ratio", "ack_ratio", "fin_ratio", "rst_ratio", "psh_ratio",
    "unique_dst_ports", "auth_port_share", "unique_dst_ips", "unique_src_ips",
    "dst_port_entropy", "iat_mean", "iat_std", "avg_pkt_size", "down_up_ratio",
    # Packet-level features
    "ttl_mean", "ttl_var", "tcp_win_mean", "tcp_win_var", "frag_ratio", "payload_size_var"
]


def _entropy(counts: np.ndarray) -> float:
    if counts.size == 0 or counts.sum() <= 0:
        return 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        p = counts / counts.sum()
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def build_windows(flows: pd.DataFrame, bin_secs: int = 60) -> pd.DataFrame:
    """Aggregate cleaned flows into per-bin feature vectors + supervision labels."""
    df = flows.copy()
    df["bin"] = df["Timestamp"].dt.floor(f"{bin_secs}s")
    df["is_attack"] = (df["Label"] != "Benign").astype(float)
    if "stage" not in df.columns:
        df["stage"] = df["Label"].map(lambda s: FAMILY_STAGE.get(s, ""))

    g = df.groupby("bin")
    w = pd.DataFrame(index=g.size().index)
    w.index.name = "bin"

    w["flow_count"] = g.size().astype(float)

    # Track columns we had to zero-fill. A feature that silently reads 0.0 for
    # every window is worse than a crash: it looks like a real input, trains a
    # useless weight, and shows up in the WHY panel as "unimportant". That is
    # exactly how `avg_pkt_size` stayed dead (the column is "Pkt Size Avg").
    zero_filled: list[str] = []

    def _sum(col: str) -> pd.Series:
        if col in df.columns:
            return g[col].sum()
        zero_filled.append(col)
        return pd.Series(0.0, index=w.index)

    def _mean(col: str) -> pd.Series:
        if col in df.columns:
            return g[col].mean()
        zero_filled.append(col)
        return pd.Series(0.0, index=w.index)

    w["bytes_total"] = _sum("TotLen Fwd Pkts") + _sum("TotLen Bwd Pkts")
    w["pkts_total"] = _sum("Tot Fwd Pkts") + _sum("Tot Bwd Pkts")
    # Flow Duration is microseconds → seconds for readability
    w["duration_mean"] = _mean("Flow Duration") / 1e6

    n = w["flow_count"].clip(lower=1)
    for flag in ("SYN", "ACK", "FIN", "RST", "PSH"):
        col = f"{flag} Flag Cnt"
        w[f"{flag.lower()}_ratio"] = (_sum(col) / n).fillna(0.0)

    if "Dst Port" in df.columns:
        ports = df["Dst Port"].to_numpy()
        w["unique_dst_ports"] = g["Dst Port"].nunique().astype(float)
        w["auth_port_share"] = (
            df[df["Dst Port"].isin(AUTH_PORTS)].groupby("bin").size()
            .reindex(w.index).fillna(0) / n
        )
        w["dst_port_entropy"] = [
            _entropy(ports[g.indices[k]]) if k in g.indices else 0.0 for k in w.index
        ]
    else:
        w["unique_dst_ports"] = 0.0
        w["auth_port_share"] = 0.0
        w["dst_port_entropy"] = 0.0

    if "Dst IP" in df.columns:
        w["unique_dst_ips"] = g["Dst IP"].nunique().astype(float)
    else:
        w["unique_dst_ips"] = 0.0
    if "Src IP" in df.columns:
        w["unique_src_ips"] = g["Src IP"].nunique().astype(float)
    else:
        w["unique_src_ips"] = 0.0

    w["iat_mean"] = _mean("Flow IAT Mean") / 1e6  # µs → s
    w["iat_std"] = _mean("Flow IAT Std") / 1e6
    w["avg_pkt_size"] = _mean("Pkt Size Avg")
    w["down_up_ratio"] = _mean("Down/Up Ratio")

    # Packet-level features
    w["ttl_mean"] = _mean("ttl_mean")
    w["ttl_var"] = _mean("ttl_var")
    w["tcp_win_mean"] = _mean("tcp_win_mean")
    w["tcp_win_var"] = _mean("tcp_win_var")
    w["frag_ratio"] = _mean("frag_ratio")
    w["payload_size_var"] = _mean("payload_size_var")

    if zero_filled:
        print(f"  WARNING: columns absent from input, features zero-filled: "
              f"{sorted(set(zero_filled))}")

    # ---- supervision columns (never model inputs) ----
    w["attack_frac"] = g["is_attack"].mean()

    stage_frac = (
        df[df["is_attack"] > 0]
        .pivot_table(index="bin", columns="stage", values="is_attack", aggfunc="count")
        .reindex(w.index)
        .fillna(0.0)
    )
    stage_frac = stage_frac.div(stage_frac.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    for st in STAGES:
        w[f"frac_{st}"] = stage_frac[st] if st in stage_frac.columns else 0.0

    frac_cols = [f"frac_{st}" for st in STAGES]
    fracs = w[frac_cols].to_numpy()
    dominant = fracs.argmax(axis=1)
    dominant[(fracs.sum(axis=1) <= 0)] = -1  # no attack → no stage label
    w["dominant_stage_idx"] = dominant

    return w[list(WINDOW_FEATURES) + ["attack_frac", "dominant_stage_idx"]
             + frac_cols].sort_index()


def make_sequences(windows: pd.DataFrame,
                   seq_len: int = SEQ_LEN, horizon: int = HORIZON):
    """Sliding sequences over window features.

    Returns X (n, L, F) float32, y_prog (n, K) binary, y_stage (n,) int
    (-1 = none), and end-index of each sequence's horizon for chronological
    splitting.

    y_prog is PER HORIZON STEP: y_prog[i, k] = 1 iff window t+k+1 contains
    attack activity. This is what makes the K outputs a forecast trajectory
    rather than one number copied K times — collapsing the horizon to a single
    `(hz > 0).any()` bool (as this did originally) trains all K heads on an
    identical target, so the predicted curve is mathematically flat and the
    "risk trajectory" claim is unsupportable. Use `horizon_any()` when you
    genuinely need the old "attack anywhere in horizon" label.
    """
    feats = windows[WINDOW_FEATURES].to_numpy(dtype=np.float32)
    attack_frac = windows["attack_frac"].to_numpy(dtype=np.float32)
    stage = windows["dominant_stage_idx"].to_numpy(dtype=np.int64)

    xs, ys_prog, ys_stage, ends = [], [], [], []
    for i in range(len(windows) - seq_len - horizon + 1):
        xs.append(feats[i:i + seq_len])
        hz = attack_frac[i + seq_len:i + seq_len + horizon]
        ys_prog.append((hz > 0).astype(np.float32))       # (K,) per-step labels
        hz_stage = stage[i + seq_len:i + seq_len + horizon]
        valid = [s for s in hz_stage if s >= 0]
        # dominant stage over horizon = most frequent among horizon windows
        ys_stage.append(int(np.bincount(valid, minlength=len(STAGES)).argmax()) if valid else -1)
        ends.append(i + seq_len + horizon)
    return (np.stack(xs), np.stack(ys_prog),
            np.array(ys_stage, dtype=np.int64), np.array(ends))


def horizon_any(y_prog: np.ndarray) -> np.ndarray:
    """(n, K) per-step labels → (n,) 'attack anywhere in horizon'.

    The single-number summary used for the headline benchmark row. Kept as one
    function so every model reports the same aggregate.
    """
    y = np.asarray(y_prog)
    return (y.max(axis=1) > 0).astype(np.float32) if y.ndim > 1 else (y > 0).astype(np.float32)


def chrono_split(windows: pd.DataFrame, ends: np.ndarray,
                 train: float = 0.70, val: float = 0.15):
    """Chronological split with boundary purge.

    Day boundaries are forbidden zones: any sequence whose span touches one is
    dropped entirely — overlapping windows would otherwise leak future labels.
    """
    days = windows.index.normalize()
    change_points = {i for i in range(1, len(days)) if days[i] != days[i - 1]}
    margin = max(SEQ_LEN, HORIZON)

    def split_at(frac_lo: float, frac_hi: float) -> list[int]:
        lo, hi = int(len(windows) * frac_lo), int(len(windows) * frac_hi)
        out = []
        for j, e in enumerate(ends):
            start = e - HORIZON - SEQ_LEN
            if start < lo or e > hi:
                continue
            if any(abs(e - cp) <= margin or abs(start - cp) <= margin
                   for cp in change_points):
                continue
            out.append(j)
        return out

    tr = split_at(0.0, train)
    va = split_at(train, train + val)
    te = split_at(train + val, 1.0)
    return tr, va, te


if __name__ == "__main__":
    print("features:", WINDOW_FEATURES, "| L =", SEQ_LEN, "| K =", HORIZON)
