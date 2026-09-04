"""Canonical feature schema — the ONE model-input definition for every source.

Why this module exists
----------------------
Before the multi-dataset refactor, the model input was the 18-feature list in
`window_builder.WINDOW_FEATURES`, computed by two parallel implementations
(CIC CSVs offline, packets live). Adding datasets on top of that would have
produced N incompatible feature lists and an availability crisis: datasets
provide different information (CSE-CIC-IDS2018's ML CSVs have no IP columns,
no TTL, no TCP-window stats; CTU-13 has IPs but different flow semantics).

The contract after this module
------------------------------
1. Every feature a model may consume is declared HERE, exactly once, with a
   stable order and a group.
2. No dataset defines its own model input. Adapters produce `FeatureSlot`s —
   `(value, available, source)` triples. A feature the source cannot provide
   is `available=False`, NEVER a silent zero.
3. Model V1 (18 features) is exactly the canonical subset flagged `v1=True`;
   the legacy path keeps working unchanged.
4. The schema has a version and a content hash, saved into every training
   artifact, so a model can refuse input produced by a different schema.

Missing-value policy
--------------------
Internally, unavailable slots hold `None`. Two explicit, caller-chosen
policies convert to a numeric vector:
  - `Policy.V1_COMPAT`: unavailable → 0.0 (byte-identical to the legacy
    zero-fill behavior, so V1 numbers reproduce exactly).
  - `Policy.MASKED`: unavailable → NaN + the availability mask travels
    alongside the matrix (used by V2 training, where the loss/normalization
    respects the mask).
There is no third policy. "Guess a plausible value" is not a policy.

Capability matrix
-----------------
`DATASET_CAPABILITIES` records what each source VERIFIABLY provides. Rows are
only marked available when confirmed from the actual source data (audit of
2026-09-04 for CIC-IDS2018; others get populated when the data is downloaded —
see MASTER_IMPLEMENTATION_PLAN stop point). Unverified rows are absent until
proven, per the "do not mark ✓ until verified" rule.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum

SCHEMA_VERSION = "2.0.0-canonical"


class Group(str, Enum):
    A_FLOW_VOLUME = "A_flow_volume"
    B_TCP = "B_tcp"
    C_TEMPORAL = "C_temporal"
    D_ADDR_PORT = "D_addr_port"
    E_PACKET = "E_packet"
    F_DIRECTION = "F_direction"
    G_SERVICE = "G_service"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: Group
    description: str
    v1: bool = False        # member of the legacy 18-feature model input
    log_transform: bool = False   # heavy-tailed/non-negative → log1p (matches scaling.LOG_FEATURES)


CANONICAL_FEATURES: list[FeatureSpec] = [
    # ---- Group A: flow-volume ------------------------------------------------
    FeatureSpec("flow_count", Group.A_FLOW_VOLUME,
                "flows (bidirectional conversations) per window", v1=True, log_transform=True),
    FeatureSpec("bytes_total", Group.A_FLOW_VOLUME,
                "sum of packet bytes per window", v1=True, log_transform=True),
    FeatureSpec("pkts_total", Group.A_FLOW_VOLUME,
                "sum of packets per window", v1=True, log_transform=True),
    FeatureSpec("duration_mean", Group.A_FLOW_VOLUME,
                "mean per-flow duration, seconds", v1=True, log_transform=True),
    FeatureSpec("duration_std", Group.A_FLOW_VOLUME,
                "std of per-flow durations, seconds"),
    FeatureSpec("avg_pkt_size", Group.A_FLOW_VOLUME,
                "mean packet size in bytes (flow bytes / flow packets, averaged)",
                v1=True, log_transform=True),
    # ---- Group B: TCP behavior ----------------------------------------------
    FeatureSpec("syn_ratio", Group.B_TCP,
                "SYN packets / flows", v1=True),
    FeatureSpec("ack_ratio", Group.B_TCP,
                "ACK packets / flows", v1=True),
    FeatureSpec("fin_ratio", Group.B_TCP,
                "FIN packets / flows", v1=True),
    FeatureSpec("rst_ratio", Group.B_TCP,
                "RST packets / flows", v1=True),
    FeatureSpec("psh_ratio", Group.B_TCP,
                "PSH packets / flows", v1=True),
    FeatureSpec("urg_ratio", Group.B_TCP,
                "URG packets / flows"),
    FeatureSpec("tcp_window_mean", Group.B_TCP,
                "mean advertised TCP window size"),
    FeatureSpec("tcp_window_std", Group.B_TCP,
                "std of advertised TCP window sizes"),
    FeatureSpec("retransmission_rate", Group.B_TCP,
                "retransmitted packets / packets (TCP)"),
    # ---- Group C: temporal behavior -----------------------------------------
    FeatureSpec("iat_mean", Group.C_TEMPORAL,
                "mean inter-arrival time within flows, seconds", v1=True, log_transform=True),
    FeatureSpec("iat_std", Group.C_TEMPORAL,
                "mean per-flow IAT std, seconds", v1=True, log_transform=True),
    FeatureSpec("iat_max", Group.C_TEMPORAL,
                "max inter-arrival time within flows, seconds", log_transform=True),
    FeatureSpec("burstiness", Group.C_TEMPORAL,
                "peak-to-mean packet-rate ratio within the window"),
    FeatureSpec("flow_rate", Group.C_TEMPORAL,
                "flows per second", log_transform=True),
    FeatureSpec("packet_rate", Group.C_TEMPORAL,
                "packets per second", log_transform=True),
    # ---- Group D: address/port behavior -------------------------------------
    FeatureSpec("unique_dst_ports", Group.D_ADDR_PORT,
                "distinct destination ports", v1=True, log_transform=True),
    FeatureSpec("unique_dst_ips", Group.D_ADDR_PORT,
                "distinct destination IPs", v1=True, log_transform=True),
    FeatureSpec("unique_src_ips", Group.D_ADDR_PORT,
                "distinct source IPs", v1=True, log_transform=True),
    FeatureSpec("src_port_entropy", Group.D_ADDR_PORT,
                "Shannon entropy of source-port counts"),
    FeatureSpec("dst_port_entropy", Group.D_ADDR_PORT,
                "Shannon entropy of destination-port counts", v1=True),
    FeatureSpec("port_scan_sequentiality", Group.D_ADDR_PORT,
                "share of consecutive-port access patterns (scan signature)"),
    FeatureSpec("port_scan_randomness", Group.D_ADDR_PORT,
                "share of random-port access patterns (scan signature)"),
    # ---- Group E: packet-level behavior -------------------------------------
    FeatureSpec("ttl_mean", Group.E_PACKET, "mean IP TTL"),
    FeatureSpec("ttl_std", Group.E_PACKET, "std of IP TTL"),
    FeatureSpec("payload_size_mean", Group.E_PACKET,
                "mean L4 payload size, bytes", log_transform=True),
    FeatureSpec("payload_size_std", Group.E_PACKET,
                "std of L4 payload size, bytes", log_transform=True),
    FeatureSpec("payload_size_p50", Group.E_PACKET,
                "median L4 payload size, bytes", log_transform=True),
    FeatureSpec("payload_size_p95", Group.E_PACKET,
                "95th-percentile L4 payload size, bytes", log_transform=True),
    FeatureSpec("fragment_flag_rate", Group.E_PACKET,
                "IP-fragment-flagged packets / packets"),
    FeatureSpec("fragment_count", Group.E_PACKET,
                "IP fragments per window", log_transform=True),
    # ---- Group F: directionality --------------------------------------------
    FeatureSpec("down_up_ratio", Group.F_DIRECTION,
                "bwd bytes / fwd bytes, mean over flows", v1=True),
    FeatureSpec("inbound_bytes", Group.F_DIRECTION,
                "bytes toward the monitored host(s)", log_transform=True),
    FeatureSpec("outbound_bytes", Group.F_DIRECTION,
                "bytes from the monitored host(s)", log_transform=True),
    FeatureSpec("inbound_packets", Group.F_DIRECTION,
                "packets toward the monitored host(s)", log_transform=True),
    FeatureSpec("outbound_packets", Group.F_DIRECTION,
                "packets from the monitored host(s)", log_transform=True),
    # ---- Group G: application/service behavior ------------------------------
    FeatureSpec("auth_port_share", Group.G_SERVICE,
                "flows to auth ports (ftp/ssh/telnet/rdp) / flows", v1=True),
    FeatureSpec("http_ratio", Group.G_SERVICE, "HTTP(80/8080) flows / flows"),
    FeatureSpec("dns_ratio", Group.G_SERVICE, "DNS(53) flows / flows"),
    FeatureSpec("ssh_ratio", Group.G_SERVICE, "SSH(22) flows / flows"),
    FeatureSpec("rdp_ratio", Group.G_SERVICE, "RDP(3389) flows / flows"),
    FeatureSpec("smb_ratio", Group.G_SERVICE, "SMB(445) flows / flows"),
    FeatureSpec("ftp_ratio", Group.G_SERVICE, "FTP(20/21) flows / flows"),
]

# Indices / name lookup --------------------------------------------------------

FEATURE_NAMES: list[str] = [f.name for f in CANONICAL_FEATURES]
FEATURE_INDEX: dict[str, int] = {n: i for i, n in enumerate(FEATURE_NAMES)}
N_FEATURES = len(CANONICAL_FEATURES)

# The legacy 18, in the legacy order (window_builder.WINDOW_FEATURES order),
# expressed as canonical indices. Guarantees V1 reproducibility: projecting a
# canonical vector through this gives the byte-identical legacy input.
# NOTE: import-free by design — the legacy order is spelled out here and
# cross-checked by tests against window_builder.WINDOW_FEATURES.
V1_ORDER: list[str] = [
    "flow_count", "bytes_total", "pkts_total", "duration_mean",
    "syn_ratio", "ack_ratio", "fin_ratio", "rst_ratio", "psh_ratio",
    "unique_dst_ports", "auth_port_share", "unique_dst_ips", "unique_src_ips",
    "dst_port_entropy", "iat_mean", "iat_std", "avg_pkt_size", "down_up_ratio",
]
V1_INDICES: list[int] = [FEATURE_INDEX[n] for n in V1_ORDER]
assert len(V1_INDICES) == 18 and len(set(V1_INDICES)) == 18

V1_NAMES_SET = set(V1_ORDER)


# Feature slots ----------------------------------------------------------------

@dataclass
class FeatureSlot:
    """One feature from one source: value + honest availability + provenance."""
    value: float | None = None
    available: bool = False
    source: str | None = None      # e.g. "csc_csv", "pcap", "live_sensor"

    @staticmethod
    def present(value: float, source: str) -> "FeatureSlot":
        return FeatureSlot(value=float(value), available=True, source=source)

    @staticmethod
    def absent() -> "FeatureSlot":
        return FeatureSlot(value=None, available=False, source=None)


class Policy(str, Enum):
    V1_COMPAT = "v1_compat"     # unavailable → 0.0 (legacy zero-fill behavior)
    MASKED = "masked"           # unavailable → NaN, mask travels with matrix


@dataclass
class WindowSlots:
    """All canonical slots for ONE time window, in canonical order."""
    slots: list[FeatureSlot] = field(default_factory=lambda: [FeatureSlot.absent()
                                                              for _ in FEATURE_NAMES])
    source: str | None = None
    ts: float | None = None

    def set(self, name: str, value: float, source: str) -> None:
        self.slots[FEATURE_INDEX[name]] = FeatureSlot.present(value, source)

    def mark_absent(self, name: str) -> None:
        self.slots[FEATURE_INDEX[name]] = FeatureSlot.absent()

    def get(self, name: str) -> FeatureSlot:
        return self.slots[FEATURE_INDEX[name]]

    def availability_mask(self) -> list[bool]:
        return [s.available for s in self.slots]

    def vector(self, policy: Policy = Policy.MASKED) -> list[float]:
        if policy is Policy.V1_COMPAT:
            return [0.0 if not s.available else float(s.value) for s in self.slots]
        # MASKED: NaN is the only honest numeric encoding of "not provided"
        return [float("nan") if not s.available else float(s.value)
                for s in self.slots]

    def v1_vector(self) -> list[float]:
        """Legacy 18-feature input, in the legacy order (V1_COMPAT semantics)."""
        vals = self.vector(Policy.V1_COMPAT)
        return [vals[i] for i in V1_INDICES]


# Dataset capability matrix ----------------------------------------------------
# Available = VERIFIED against actual source files. Rows appear here only once
# proven. CIC-IDS2018 row is from the 2026-09-04 audit (csv_loader CORE_COLS):
# the ML-ready CSVs ship no Src IP / Dst IP columns, so IP-derived features are
# UNAVAILABLE (this is the honest version of the legacy zero-fill), and nothing
# packet-level (TTL/window/payload/retrans) exists in flow aggregates.

CIC2018_AVAILABLE: set[str] = set(V1_ORDER) - {"unique_dst_ips", "unique_src_ips"}

# Live sensor today (packet_windower): same 18 (IPs ARE available live), plus
# the rule-engine-only lateral_port_share which is NOT a model feature.
LIVE_AVAILABLE: set[str] = set(V1_ORDER)

# UNSW-NB15 (verified from the real main CSVs, 2026-09-04 — see
# src/datasets/unsw_nb15.py docstring for the semantics notes):
#   • 12 of the legacy 18, INCLUDING unique_src_ips/unique_dst_ips (UNSW
#     ships real IP columns — the one legacy feature CIC2018 lacks)
#   • NO TCP flag counts (syn/ack/fin/rst/push ratios unavailable) and no
#     per-flow IAT std — the source provides directional interpacket MEANS
#   • extras CIC2018 cannot provide: TTL, TCP window (TCP flows only),
#     duration_std, src_port_entropy, rates, all Group-G service ratios
UNSW_NB15_AVAILABLE: set[str] = (
    {  # legacy 18 that UNSW verifiably provides
        "flow_count", "bytes_total", "pkts_total", "duration_mean",
        "avg_pkt_size", "unique_dst_ports", "unique_dst_ips",
        "unique_src_ips", "dst_port_entropy", "iat_mean", "down_up_ratio",
        "auth_port_share",
    } | {  # verified extras
        "duration_std", "ttl_mean", "ttl_std", "tcp_window_mean",
        "tcp_window_std", "src_port_entropy", "flow_rate", "packet_rate",
        "http_ratio", "dns_ratio", "ssh_ratio", "rdp_ratio", "smb_ratio",
        "ftp_ratio",
    }
)

# CTU-13 (bidirectional Argus NetFlow, real IPs) — verified from the actual
# .binetflow files on disk 2026-09-04 (13 scenarios, label column read from
# every file): provides flow volume (TotPkts/TotBytes/Dur), the full
# address/port group (real Src/DstAddr + ports, incl. hex-encoded ICMP-era
# port spellings), directionality (SrcBytes vs TotBytes → fwd/bwd bytes), and
# all port-based service ratios. Honestly UNAVAILABLE: TCP flag counts (Argus
# `State` strings describe per-flow handshake state, not packet counts — same
# refusal as UNSW's synack/ackdat trap), inter-arrival statistics (no IAT
# columns), and every Group-E packet internal.
CTU13_AVAILABLE: set[str] = (
    {  # legacy 18 that CTU-13 verifiably provides (11 of 18)
        "flow_count", "bytes_total", "pkts_total", "duration_mean",
        "avg_pkt_size", "unique_dst_ports", "unique_dst_ips",
        "unique_src_ips", "dst_port_entropy", "down_up_ratio",
        "auth_port_share",
    } | {  # verified extras
        "duration_std", "src_port_entropy", "flow_rate", "packet_rate",
        "http_ratio", "dns_ratio", "ssh_ratio", "rdp_ratio", "smb_ratio",
        "ftp_ratio",
    }
)

DATASET_CAPABILITIES: dict[str, set[str]] = {
    "cic2018": CIC2018_AVAILABLE,
    "live": LIVE_AVAILABLE,
    "unsw_nb15": UNSW_NB15_AVAILABLE,
    "ctu13": CTU13_AVAILABLE,
    # "cic2017", "ciciot2023", "darpa", "lanl":
    # deliberately absent until the data is downloaded and verified
    # (plan rule: do not mark ✓ until verified from source data).
}


def availability_for(dataset_id: str) -> list[bool]:
    """Canonical-length availability mask for a dataset (unknown → all False)."""
    have = DATASET_CAPABILITIES.get(dataset_id, set())
    return [n in have for n in FEATURE_NAMES]


def v1_mask_for(dataset_id: str) -> list[bool]:
    """Availability restricted to the legacy 18, in legacy order."""
    have = DATASET_CAPABILITIES.get(dataset_id, set())
    return [n in have for n in V1_ORDER]


# Reproducibility ---------------------------------------------------------------

def schema_hash() -> str:
    """Stable content hash — store in every artifact; refuse mismatches."""
    payload = ";".join(f"{f.name}|{f.group.value}|{int(f.v1)}|{int(f.log_transform)}"
                       for f in CANONICAL_FEATURES)
    return hashlib.sha256(f"v{SCHEMA_VERSION}:{payload}".encode()).hexdigest()[:16]


def describe() -> str:
    counts: dict[Group, int] = {}
    for f in CANONICAL_FEATURES:
        counts[f.group] = counts.get(f.group, 0) + 1
    lines = [f"canonical schema v{SCHEMA_VERSION} — {N_FEATURES} features "
             f"(of which {len(V1_ORDER)} legacy V1)"]
    for g in Group:
        names = [f.name for f in CANONICAL_FEATURES if f.group is g]
        lines.append(f"  {g.value:14s} {len(names):2d}: {', '.join(names)}")
    lines.append(f"  hash: {schema_hash()}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
    print("\ncic2018 availability (of legacy 18):")
    for n, ok in zip(V1_ORDER, v1_mask_for("cic2018")):
        print(f"  {'OK ' if ok else '-- '} {n}")
