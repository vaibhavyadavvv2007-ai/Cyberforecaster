"""Canonical sequence engine — ONE windowing/supervision path for every source.

DATA_CONTRACT §3–§5: training CSVs, the live sensor and uploaded pcaps must
all travel the same road

    source → WindowSlots (canonical schema, honest availability)
           → make_canonical_sequences()  (gap-filled, L×K supervision)
           → CanonicalScaler            (masked log1p + standardise)

The legacy V1 path (window_builder.make_sequences + scaling.fit_scaler) stays
untouched — it is the frozen baseline's road. This engine is the V2 road; the
two share the schema (V1_ORDER ⊂ canonical features) but not the code path.

Empty windows (DATA_CONTRACT §3): a bin with no packets is an explicit
zero-observation window, never a timeline gap. Following the live pipeline's
`flush_empty_bin` convention and extending it honestly:
  - counts, rates, ratios, means/entropies over *flows* → 0.0, available
  - quantities that are properties of PACKETS (ttl, tcp window, payload
    sizes, retransmission, scan patterns, burstiness) → unavailable: a
    mean over zero packets has no value, and 0.0 would be a lie.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import BIN_SECS, HORIZON, SEQ_LEN
from ..labels.attack_taxonomy import BENIGN, CANONICAL_INDEX, LabelRecord
from .canonical_schema import (CANONICAL_FEATURES, FEATURE_INDEX, N_FEATURES,
                               SCHEMA_VERSION, WindowSlots, schema_hash)

# features that are honestly 0.0 in an empty (zero-observation) bin
_EMPTY_ZERO = {
    # counts / volumes
    "flow_count", "bytes_total", "pkts_total", "fragment_count",
    # flow-property ratios and means (0 flows → 0 by convention)
    "duration_mean", "duration_std", "syn_ratio", "ack_ratio", "fin_ratio",
    "rst_ratio", "psh_ratio", "urg_ratio", "fragment_flag_rate",
    "iat_mean", "iat_std", "iat_max", "avg_pkt_size", "down_up_ratio",
    "flow_rate", "packet_rate",
    # address/port observations over zero flows
    "unique_dst_ports", "unique_dst_ips", "unique_src_ips",
    "src_port_entropy", "dst_port_entropy",
    # service shares over zero flows
    "auth_port_share", "http_ratio", "dns_ratio", "ssh_ratio", "rdp_ratio",
    "smb_ratio", "ftp_ratio",
}
_LOG_FLAGS = np.array([f.log_transform for f in CANONICAL_FEATURES])


def empty_bin_slots(ts: float, bin_secs: int = BIN_SECS,
                    host_ip: str | None = None,
                    source: str = "empty_bin") -> WindowSlots:
    """A quiet bin: an explicit observation of *nothing happening*."""
    ws = WindowSlots(source=source, ts=float(ts))
    for name in _EMPTY_ZERO:
        ws.set(name, 0.0, source)
    if host_ip is not None:      # direction of zero traffic is still zero
        for name in ("inbound_bytes", "outbound_bytes",
                     "inbound_packets", "outbound_packets"):
            ws.set(name, 0.0, source)
    # everything packet-derived (ttl_*, payload_*, tcp_window_*, scan
    # patterns, retransmission, burstiness) stays absent — see module docstring
    return ws


@dataclass
class CanonicalSequences:
    """Sequences over canonical slots. X may contain NaN (MASKED policy)."""
    X: np.ndarray            # (n, L, F) float32, NaN = unavailable
    mask: np.ndarray         # (n, L, F) bool, availability
    y_prog: np.ndarray | None   # (n, K) per-step attack labels, or None (live)
    y_stage: np.ndarray | None  # (n,) canonical stage index, -1 = none
    ends: np.ndarray         # (n,) absolute window index of each horizon end
    ts: np.ndarray           # (windows,) bin start times, epoch seconds
    labels: list[LabelRecord] | None

    @property
    def n_sequences(self) -> int:
        return int(self.X.shape[0])


def make_canonical_sequences(
        slots: list[WindowSlots],
        labels: list[LabelRecord] | None = None,
        seq_len: int = SEQ_LEN, horizon: int = HORIZON,
        bin_secs: int = BIN_SECS, emit_empty: bool = True,
        host_ip: str | None = None) -> CanonicalSequences:
    """WindowSlots (any source) → training/inference sequences.

    Gap handling: consecutive bins further apart than `bin_secs` are filled
    with explicit empty windows so the timeline has no holes (the model's
    history is real elapsed time, not compressed). Gap labels are BENIGN —
    an empty bin by definition contains no attack.
    """
    if labels is not None and len(labels) != len(slots):
        raise ValueError(f"{len(slots)} slots but {len(labels)} labels")
    items = sorted(zip(slots, labels or [None] * len(slots)),
                   key=lambda p: (p[0].ts if p[0].ts is not None else 0.0))

    out_slots: list[WindowSlots] = []
    out_labels: list[LabelRecord] = []
    prev_bin: int | None = None
    for ws, lab in items:
        if ws.ts is None:
            raise ValueError("WindowSlots without ts — cannot place on the timeline")
        b = int(ws.ts) // bin_secs
        if emit_empty and prev_bin is not None and b > prev_bin + 1:
            for g in range(prev_bin + 1, b):
                out_slots.append(empty_bin_slots(g * bin_secs, bin_secs, host_ip))
                out_labels.append(LabelRecord("engine", "Benign", BENIGN,
                                              "benign", "empty_bin"))
        # duplicate bins (two sources) — last one wins, loudly
        if prev_bin is not None and b == prev_bin:
            out_slots[-1], out_labels[-1] = ws, lab
        else:
            out_slots.append(ws)
            out_labels.append(lab)   # type: ignore[arg-type]
        prev_bin = b

    n_w = len(out_slots)
    X = np.full((n_w, N_FEATURES), np.nan, dtype=np.float32)
    M = np.zeros((n_w, N_FEATURES), dtype=bool)
    for i, ws in enumerate(out_slots):
        for j, slot in enumerate(ws.slots):
            if slot.available:
                X[i, j] = slot.value
                M[i, j] = True

    ts = np.array([s.ts for s in out_slots], dtype=np.float64)

    if labels is not None:
        is_attack = np.array(
            [l is not None and l.is_attack for l in out_labels], dtype=np.float32)
        stage_of = lambda l: (CANONICAL_INDEX.get(l.canonical_label, -1)
                              if l is not None and l.is_attack else -1)
        stages = np.array([stage_of(l) for l in out_labels], dtype=np.int64)
    else:
        is_attack = None      # live / upload: no ground truth
        stages = None

    xs, ys_prog, ys_stage, ends = [], [], [], []
    for i in range(n_w - seq_len - horizon + 1):
        xs.append(X[i:i + seq_len])
        ends.append(i + seq_len + horizon)
        if is_attack is not None:
            hz = is_attack[i + seq_len:i + seq_len + horizon]
            ys_prog.append(hz.astype(np.float32))
            hz_stage = stages[i + seq_len:i + seq_len + horizon]
            valid = hz_stage[hz_stage >= 0]
            ys_stage.append(int(np.bincount(valid,
                                            minlength=len(CANONICAL_INDEX)).argmax())
                            if len(valid) else -1)

    if not xs:
        return CanonicalSequences(
            X=np.empty((0, seq_len, N_FEATURES), dtype=np.float32),
            mask=np.empty((0, seq_len, N_FEATURES), dtype=bool),
            y_prog=(np.empty((0, horizon), dtype=np.float32)
                    if is_attack is not None else None),
            y_stage=(np.empty(0, dtype=np.int64) if stages is not None else None),
            ends=np.empty(0, dtype=np.int64), ts=ts,
            labels=out_labels if labels is not None else None)

    seq_mask = np.stack([M[i:i + seq_len] for i in range(len(ends))])
    return CanonicalSequences(
        X=np.stack(xs), mask=seq_mask,
        y_prog=(np.stack(ys_prog) if is_attack is not None else None),
        y_stage=(np.array(ys_stage, dtype=np.int64)
                 if is_attack is not None else None),
        ends=np.array(ends, dtype=np.int64), ts=ts,
        labels=out_labels if labels is not None else None)


def chrono_split_canonical(ts: np.ndarray, ends: np.ndarray,
                           seq_len: int = SEQ_LEN, horizon: int = HORIZON,
                           train: float = 0.70, val: float = 0.15
                           ) -> tuple[list[int], list[int], list[int]]:
    """Chronological split with boundary purge, on canonical sequences.

    Mirrors window_builder.chrono_split: day boundaries are forbidden zones;
    any sequence whose span touches one is dropped so overlapping windows
    cannot leak across splits. `ts` = per-window bin start times.
    """
    days = (ts.astype("datetime64[s]").astype("datetime64[D]"))
    change_points = {i for i in range(1, len(days)) if days[i] != days[i - 1]}
    margin = max(seq_len, horizon)

    def split_at(frac_lo: float, frac_hi: float) -> list[int]:
        lo, hi = int(len(ts) * frac_lo), int(len(ts) * frac_hi)
        out = []
        for j, e in enumerate(ends):
            start = e - horizon - seq_len + 1
            if start < lo or e > hi:
                continue
            if any(abs(e - cp) <= margin or abs(start - cp) <= margin
                   for cp in change_points):
                continue
            out.append(j)
        return out

    return (split_at(0.0, train), split_at(train, train + val),
            split_at(train + val, 1.0))


# ------------------------------------------------------------------ scaling

class CanonicalScaler:
    """log1p + standardise for canonical vectors, fitted on AVAILABLE values
    only (masked statistics). NaN propagates — never zero-filled.

    Mirrors the V1 scaler's design decisions (scaling.py: log1p on
    heavy-tailed non-negative features first, standardise after, fit on train
    only) so V1→V2 comparisons stay apples-to-apples.
    """

    def __init__(self):
        self.means: np.ndarray | None = None
        self.stds: np.ndarray | None = None
        self.schema_hash: str | None = None

    def fit(self, X: np.ndarray) -> "CanonicalScaler":
        """X: (n, L, F) or (n, F) with NaN where unavailable."""
        flat = X.reshape(-1, X.shape[-1]).astype(np.float64)
        with np.errstate(invalid="ignore"):
            z = np.where(_LOG_FLAGS, np.log1p(np.clip(flat, 0, None)), flat)
            self.means = np.nanmean(z, axis=0)
            self.stds = np.nanstd(z, axis=0)
        # a feature available nowhere (all NaN) has no statistics: mean 0,
        # std 1 keeps transform a no-op instead of NaN-poisoning everything
        self.means = np.where(np.isnan(self.means), 0.0, self.means)
        self.stds = np.where(np.isnan(self.stds) | (self.stds < 1e-12),
                             1.0, self.stds)
        self.schema_hash = schema_hash()
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.means is None:
            raise RuntimeError("CanonicalScaler not fitted")
        shape = X.shape
        flat = X.reshape(-1, shape[-1]).astype(np.float64)
        with np.errstate(invalid="ignore"):
            z = np.where(_LOG_FLAGS, np.log1p(np.clip(flat, 0, None)), flat)
            z = (z - self.means) / self.stds
        return z.reshape(shape).astype(np.float32)

    def save(self, path: str | Path) -> None:
        np.savez_compressed(
            path, means=self.means, stds=self.stds,
            feature_names=np.array([f.name for f in CANONICAL_FEATURES]),
            schema_version=np.array(SCHEMA_VERSION),
            schema_hash=np.array(self.schema_hash))

    @classmethod
    def load(cls, path: str | Path) -> "CanonicalScaler":
        d = np.load(path, allow_pickle=False)
        want = schema_hash()
        got = str(d["schema_hash"])
        if got != want:
            raise ValueError(
                f"scaler at {path} was fitted against canonical schema {got} "
                f"but this code defines {want} — retrain or pin the schema")
        s = cls()
        s.means, s.stds = d["means"], d["stds"]
        s.schema_hash = got
        return s
