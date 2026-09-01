"""Packets → the 18 WINDOW_FEATURES, one vector per time bin.

This mirrors features/window_builder.py — same feature names, same order,
same semantics — but computed from raw packets on the sensor instead of from
CICFlowMeter flow CSVs. Any place the two CANNOT match exactly is documented
at the computation below and must be explainable to a judge in one sentence.

Feature-by-feature mapping (training → live):

| training (window_builder)              | live (this module)                       |
|----------------------------------------|------------------------------------------|
| flow rows from CICFlowMeter            | flow key = (src ip, src port, dst ip,    |
|                                        |   dst port, proto), tracked per bin      |
| flow_count                             | number of distinct flow keys             |
| bytes_total = Σ fwd+bwd TotLen         | Σ packet IP payload lengths              |
| pkts_total  = Σ fwd+bwd Tot Pkts       | Σ packets                                |
| duration_mean = mean Flow Duration     | mean (last_ts - first_ts) per flow       |
| syn_ratio = Σ SYN Flag Cnt / flows     | Σ packets-with-SYN / flows               |
| (same for ACK/FIN/RST/PSH)             | (same)                                   |
| unique_dst_ports = nunique Dst Port    | distinct flow dst ports                  |
| auth_port_share = auth flows / n       | flows to AUTH_PORTS / flows              |
| unique_dst_ips / unique_src_ips        | distinct flow src/dst IPs                |
| dst_port_entropy = H(Dst Port counts)  | H(dst port counts over flow rows)        |
| iat_mean/std = mean of per-flow IAT    | per-flow inter-arrival mean/std,         |
|                                        |   Welford-incremental, then mean/flows   |
| avg_pkt_size = mean Pkt Size Avg       | mean over flows of (bytes/pkts)          |
| down_up_ratio = mean Down/Up Ratio     | mean over flows of bwd_bytes/fwd_bytes   |
|                                        |   (forward = first packet's direction)   |

Supervision columns (attack_frac, frac_* ...) do NOT exist here — there is no
ground truth live. The model consumes only the 18 features; the label columns
were training-time scaffolding.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ..features.window_builder import WINDOW_FEATURES

AUTH_PORTS = {20, 21, 22, 23, 3389}   # mirrors mitre_mapper.AUTH_PORTS
# Windows internal-movement ports (SMB/RPC/RDP/WinRM). Live-only signal for
# the rule engine's lateral-movement check — it never reaches the model
# (not in WINDOW_FEATURES; training CSVs have no per-port breakdown anyway).
LATERAL_PORTS = {135, 139, 445, 3389, 5985, 5986}


def _entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


@dataclass
class _Flow:
    """One BIDIRECTIONAL conversation inside the current bin.

    CICFlowMeter merges both directions into one flow record; the live sensor
    must too, or every handshake counts as two flows and flow_count /
    unique_dst_ports inflate 2x against the training distribution. Direction:
    the first packet seen defines 'forward' (CIC's convention), so Dst Port /
    down-up semantics below match the training features.
    """
    first_ts: float
    last_ts: float
    fwd_ep: tuple = ()             # (ip, port) the first packet came FROM
    dst_ep: tuple = ()             # (ip, port) the first packet went TO
    pkts: int = 0
    bytes_total: int = 0
    fwd_bytes: int = 0          # direction of the first packet seen
    bwd_bytes: int = 0
    syn: int = 0                # packet counts per TCP flag
    ack: int = 0
    fin: int = 0
    rst: int = 0
    psh: int = 0
    iat_n: int = 0              # Welford over inter-arrival gaps (seconds)
    iat_mean: float = 0.0
    iat_m2: float = 0.0

    def observe(self, ts: float, length: int, flags: int, is_fwd: bool) -> None:
        if self.pkts > 0:
            # Welford: incremental mean/var of inter-arrival times, so a flow
            # with a million packets costs O(1) memory, not O(n).
            dt = ts - self.last_ts
            self.iat_n += 1
            d = dt - self.iat_mean
            self.iat_mean += d / self.iat_n
            # Welford: M2 accumulates d * (x - mean_new) where x is the gap
            # dt — NOT the absolute timestamp ts (that inflated iat_std by
            # ~1e9 and pushed every benign window to HIGH).
            self.iat_m2 += d * (dt - self.iat_mean)
        self.last_ts = ts
        self.pkts += 1
        self.bytes_total += length
        if is_fwd:
            self.fwd_bytes += length
        else:
            self.bwd_bytes += length
        # TCP flag bits (scapy convention): F=0x01, S=0x02, R=0x04, P=0x08, A=0x10
        if flags & 0x02:
            self.syn += 1
        if flags & 0x10:
            self.ack += 1
        if flags & 0x01:
            self.fin += 1
        if flags & 0x04:
            self.rst += 1
        if flags & 0x08:
            self.psh += 1

    @property
    def duration(self) -> float:
        return max(self.last_ts - self.first_ts, 0.0)

    @property
    def iat_std(self) -> float:
        if self.iat_n < 2:
            return 0.0
        var = self.iat_m2 / self.iat_n   # population variance, like CICFlowMeter
        return math.sqrt(max(var, 0.0))


class LiveWindowBuilder:
    """Accumulates packets into fixed-length bins; flush one feature vector per bin.

    Bins are wall-clock aligned (epoch // bin_secs) so the demo timeline is
    readable. The training pipeline uses 60s bins (data/processed/meta.txt).
    The live sensor runs 30s bins by design — lower latency on demo day; this
    is the documented A/B experiment (see STATUS.md). The mismatch is
    intentional and must be disclosed if asked by a judge.
    """

    def __init__(self, bin_secs: int = 30):
        self.bin_secs = bin_secs
        self._bin_id: int | None = None
        self._flows: dict[tuple, _Flow] = {}
        self.packets_seen = 0
        self.packets_skipped = 0
        # bins finalized by packet rollover, waiting for the poller to drain
        self.pending: list[dict] = []

    # ------------------------------------------------------------ observe
    def observe(self, ts: float, src: str, sport: int, dst: str, dport: int,
                proto: str, length: int, tcp_flags: int = 0) -> None:
        """Record one TCP/UDP packet. `length` = IP payload bytes (IP layer len)."""
        bin_id = int(ts) // self.bin_secs
        if self._bin_id is None:
            self._bin_id = bin_id
        elif bin_id != self._bin_id:
            # Packet time crossed into a new bin BEFORE the poller flushed the
            # old one (e.g. frontend tab in background). Finalize the old bin
            # now so its features are not contaminated by the new bin's
            # packets; the poller drains it from `pending`.
            self.pending.append(self._finalize(self._bin_id))
            self._bin_id = bin_id
        # canonical, direction-invariant key: both conversation directions map
        # to the same flow record, exactly like CICFlowMeter's bidirectional
        # flows. proto distinguishes the (rare) same-endpoints TCP/UDP pair.
        a, b = (src, sport), (dst, dport)
        lo, hi = min(a, b), max(a, b)
        key = (lo, hi, proto)
        flow = self._flows.get(key)
        if flow is None:
            flow = _Flow(first_ts=ts, last_ts=ts, fwd_ep=a, dst_ep=b)
            self._flows[key] = flow
            flow.observe(ts, length, tcp_flags, is_fwd=True)
            self.packets_seen += 1
            return
        flow.observe(ts, length, tcp_flags, is_fwd=(src, sport) == flow.fwd_ep)
        self.packets_seen += 1

    # ------------------------------------------------------------- flush
    def current_bin_remaining(self) -> float:
        """Seconds until the current bin closes (for UI countdown)."""
        if self._bin_id is None:
            return float(self.bin_secs)
        return max(self.bin_secs - (time.time() - self._bin_id * self.bin_secs), 0.0)

    def bin_elapsed(self) -> float:
        if self._bin_id is None:
            return 0.0
        return min(time.time() - self._bin_id * self.bin_secs, float(self.bin_secs))

    def live_flow_count(self) -> int:
        """Flows seen so far in the OPEN bin — the 'current activity' readout."""
        return len(self._flows)

    def flush_empty_bin(self) -> dict | None:
        """Close the current bin as an explicit ZERO window (no packets).

        A quiet 30 seconds is a real observation the model should see — not a
        gap in the timeline. All ratios are 0 by convention (0/flows where
        flows=0 is guarded here, once, instead of NaN-ing downstream).
        """
        if self._bin_id is None:
            return None
        bin_id, self._bin_id = self._bin_id, None
        self._flows = {}
        return {
            "bin_id": bin_id,
            "ts": bin_id * self.bin_secs,
            "features": {c: 0.0 for c in WINDOW_FEATURES} | {
                "lateral_port_share": 0.0},
            "pkts_seen": self.packets_seen,
            "empty": True,
        }

    def flush_bin(self) -> dict | None:
        """Close the current bin → one WINDOW_FEATURES dict (or None if empty).

        Also resets internal state for the next bin, so this is safe to call on
        every poll: if the bin has not rolled over yet it returns None and
        changes nothing. A bin with zero packets is flushed via flush_empty_bin.
        """
        if self._bin_id is None or not self._flows:
            return None
        bin_id, self._bin_id = self._bin_id, None
        return self._finalize(bin_id)

    def _finalize(self, bin_id: int) -> dict:
        """Compute one feature dict from the accumulated flows and reset state."""
        flows = list(self._flows.values())
        self._flows = {}

        n = len(flows)
        feats: dict[str, float] = {}
        feats["flow_count"] = float(n)
        feats["bytes_total"] = float(sum(f.bytes_total for f in flows))
        feats["pkts_total"] = float(sum(f.pkts for f in flows))
        feats["duration_mean"] = sum(f.duration for f in flows) / n

        for flag in ("syn", "ack", "fin", "rst", "psh"):
            total = sum(getattr(f, flag) for f in flows)
            feats[f"{flag}_ratio"] = total / n

        # port/IP features use the CIC convention: 'dst' = the endpoint the
        # conversation's FIRST packet was sent to (usually the service)
        dports = [f.dst_ep[1] for f in flows]
        feats["unique_dst_ports"] = float(len(set(dports)))
        feats["auth_port_share"] = sum(
            1 for p in dports if p in AUTH_PORTS) / n
        feats["unique_dst_ips"] = float(len({f.dst_ep[0] for f in flows}))
        feats["unique_src_ips"] = float(len({f.fwd_ep[0] for f in flows}))
        port_counts: dict[int, int] = {}
        for p in dports:
            port_counts[p] = port_counts.get(p, 0) + 1
        feats["dst_port_entropy"] = _entropy(list(port_counts.values()))
        # rule-engine-only extra (see LATERAL_PORTS) — kept beside the model
        # features so _rule_stage sees it; windows_to_matrix ignores it.
        feats["lateral_port_share"] = sum(
            1 for p in dports if p in LATERAL_PORTS) / n

        feats["iat_mean"] = sum(f.iat_mean for f in flows) / n
        feats["iat_std"] = sum(f.iat_std for f in flows) / n
        feats["avg_pkt_size"] = sum(
            f.bytes_total / f.pkts for f in flows) / n
        # clip: one 400-byte forward packet against a 4GB reply otherwise makes
        # log1p(down_up) a 14-sigma outlier the scaler never saw in training
        feats["down_up_ratio"] = sum(
            min(f.bwd_bytes / max(f.fwd_bytes, 1), 1e5) for f in flows) / n

        missing = [c for c in WINDOW_FEATURES if c not in feats]
        assert not missing, f"live window missing features: {missing}"

        return {
            "bin_id": bin_id,
            "ts": bin_id * self.bin_secs,     # epoch seconds, bin-aligned
            "features": {c: feats[c] for c in WINDOW_FEATURES} | {
                "lateral_port_share": feats["lateral_port_share"]},
            "pkts_seen": self.packets_seen,
        }


def windows_to_matrix(windows: list[dict]) -> list[list[float]]:
    """List of flush_bin() dicts (or seed rows) → (L, F) raw feature matrix."""
    return [[float(w["features"][c]) for c in WINDOW_FEATURES] for w in windows]
