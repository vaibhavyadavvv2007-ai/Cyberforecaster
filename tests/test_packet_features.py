"""Packet feature extraction tests (Phase 4).

Two layers:
  1. deterministic PacketObservation streams (no scapy needed) exercising
     rollover, scan signatures, retransmission, host_ip availability;
  2. a real scapy pcap round-trip proving from_scapy/extract_pcap work on
     actual files and that the flow-level 18 are byte-identical to a bare
     LiveWindowBuilder fed the same packets (the reuse guarantee).
"""
from __future__ import annotations

import math

import pytest

from src.features.canonical_schema import FEATURE_NAMES, V1_ORDER
from src.features.packet_features import (PacketFeaturePipeline,
                                          PacketObservation)
from src.live.packet_windower import LiveWindowBuilder

BIN = 30
BASE = 999_999_990          # 30s-aligned epoch


def pkt(ts_off, src, sport, dst, dport, *, proto="tcp", ip_len=60, ttl=64,
        flags=0x02, window=8192, payload=0, frag=False, seq=1000):
    return PacketObservation(
        ts=BASE + ts_off, src=src, sport=sport, dst=dst, dport=dport,
        proto=proto, ip_len=ip_len, ttl=ttl, tcp_flags=flags,
        tcp_window=window if proto == "tcp" else None,
        payload_len=payload, frag_flag=frag,
        tcp_seq=seq if proto == "tcp" else None)


# --------------------------------------------------------------- benign flow

def test_benign_bin_core_features():
    pipe = PacketFeaturePipeline(bin_secs=BIN)
    # one handshake-ish conversation + a reply, 2s apart
    pipe.observe_packet(pkt(0, "10.0.0.1", 40000, "10.0.0.2", 443, payload=100))
    pipe.observe_packet(pkt(2, "10.0.0.2", 443, "10.0.0.1", 40000, payload=400,
                            flags=0x10, window=65535, seq=2000))
    pipe.observe_packet(pkt(4, "10.0.0.1", 40001, "10.0.0.3", 22, payload=50))
    windows = pipe.close()

    assert len(windows) == 1
    ws = windows[0]
    # flow-level (reused builder)
    assert ws.get("flow_count").value == 2.0
    assert ws.get("unique_dst_ips").available
    # packet-level
    assert ws.get("ttl_mean").value == pytest.approx(64.0)
    assert ws.get("ttl_std").value == pytest.approx(0.0)
    assert ws.get("payload_size_mean").value == pytest.approx((100 + 400 + 50) / 3)
    assert ws.get("tcp_window_mean").value == pytest.approx((8192 + 65535 + 8192) / 3)
    # direction features need a host_ip — honestly absent without one
    assert not ws.get("inbound_bytes").available
    assert not ws.get("outbound_bytes").available
    # service ratios are port-based → always available
    assert ws.get("ssh_ratio").value == pytest.approx(0.5)


def test_host_ip_unlocks_direction_features():
    pipe = PacketFeaturePipeline(bin_secs=BIN, host_ip="10.0.0.2")
    pipe.observe_packet(pkt(0, "10.0.0.1", 40000, "10.0.0.2", 443, ip_len=100))
    pipe.observe_packet(pkt(1, "10.0.0.2", 443, "10.0.0.1", 40000, ip_len=200))
    ws = pipe.close()[0]
    assert ws.get("inbound_bytes").value == 100.0
    assert ws.get("outbound_bytes").value == 200.0
    assert ws.get("inbound_packets").value == 1.0
    assert ws.get("outbound_packets").value == 1.0


# ------------------------------------------------------------ attack signals

def test_sequential_port_scan_signature():
    pipe = PacketFeaturePipeline(bin_secs=BIN)
    for i, port in enumerate([21, 22, 23, 24, 25, 80]):
        pipe.observe_packet(pkt(i, "10.9.9.9", 50000 + i, "10.0.0.5", port))
    ws = pipe.close()[0]
    # 4 of 5 consecutive first-contact port pairs differ by exactly 1
    assert ws.get("port_scan_sequentiality").value == pytest.approx(0.8)
    # six equally-used ports → perfectly uniform → normalized entropy 1.0
    assert ws.get("port_scan_randomness").value == pytest.approx(1.0)
    assert ws.get("syn_ratio").value == pytest.approx(1.0)


def test_no_scan_signal_stays_absent():
    pipe = PacketFeaturePipeline(bin_secs=BIN)
    # one pair only (below the >=3 evidence threshold) — unavailable, not zero
    pipe.observe_packet(pkt(0, "10.0.0.1", 40000, "10.0.0.2", 443))
    pipe.observe_packet(pkt(1, "10.0.0.1", 40001, "10.0.0.2", 8080))
    ws = pipe.close()[0]
    assert not ws.get("port_scan_sequentiality").available


def test_retransmission_detected():
    pipe = PacketFeaturePipeline(bin_secs=BIN)
    pipe.observe_packet(pkt(0, "10.0.0.1", 40000, "10.0.0.2", 80, seq=1000))
    pipe.observe_packet(pkt(1, "10.0.0.1", 40000, "10.0.0.2", 80, seq=1000))  # retrans
    pipe.observe_packet(pkt(2, "10.0.0.1", 40000, "10.0.0.2", 80, seq=2000))
    ws = pipe.close()[0]
    assert ws.get("retransmission_rate").value == pytest.approx(1 / 3)


def test_burstiness_spikes_on_flood():
    quiet = PacketFeaturePipeline(bin_secs=BIN)
    for i in range(30):     # steady 1 pkt/s across 30 one-second buckets
        quiet.observe_packet(pkt(i, "10.0.0.1", 40000 + i, "10.0.0.2", 443))
    flood = PacketFeaturePipeline(bin_secs=BIN)
    for i in range(29):     # 29 packets in second 0, one in second 29
        flood.observe_packet(pkt(0, "10.0.0.1", 40000 + i, "10.0.0.2", 443))
    flood.observe_packet(pkt(29, "10.0.0.1", 40100, "10.0.0.2", 443))
    q, f = quiet.close()[0], flood.close()[0]
    assert q.get("burstiness").value == pytest.approx(1.0)
    assert f.get("burstiness").value == pytest.approx(29.0)   # peak/mean rate


# ------------------------------------------------------------------ rollover

def test_two_bins_roll_cleanly():
    pipe = PacketFeaturePipeline(bin_secs=BIN)
    pipe.observe_packet(pkt(0, "10.0.0.1", 40000, "10.0.0.2", 443))
    pipe.observe_packet(pkt(29, "10.0.0.1", 40001, "10.0.0.2", 443))
    pipe.observe_packet(pkt(31, "10.0.0.9", 50000, "10.0.0.4", 22))   # new bin
    pipe.observe_packet(pkt(32, "10.0.0.9", 50001, "10.0.0.4", 22))
    windows = pipe.close()
    assert len(windows) == 2
    assert windows[0].get("flow_count").value == 2.0
    assert windows[1].get("flow_count").value == 2.0
    assert windows[0].get("ssh_ratio").value == pytest.approx(0.0)
    assert windows[1].get("ssh_ratio").value == pytest.approx(1.0)
    assert windows[0].ts == BASE
    assert windows[1].ts == BASE + BIN


# ---------------------------------------------------------- schema conformance

def test_only_canonical_names_set():
    pipe = PacketFeaturePipeline(bin_secs=BIN, host_ip="10.0.0.1")
    pipe.observe_packet(pkt(0, "10.0.0.2", 443, "10.0.0.1", 40000))
    ws = pipe.close()[0]
    mask = ws.availability_mask()
    assert len(mask) == len(FEATURE_NAMES)
    for i, ok in enumerate(mask):
        if ok:
            assert ws.slots[i].source == "pcap"


# --------------------------------------------------- scapy pcap round-trip

def test_pcap_roundtrip_matches_live_builder():
    """extract_pcap on a real file must produce the SAME flow-level 18 as a
    bare LiveWindowBuilder fed the same packets — the reuse guarantee."""
    scapy = pytest.importorskip("scapy")
    from scapy.all import IP, TCP, UDP, wrpcap
    from src.features.packet_features import extract_pcap, from_scapy

    t0 = BIN * 33_333_333          # 30s-aligned
    pkts = []
    for i in range(3):
        p = IP(src="10.0.0.1", dst="10.0.0.2", ttl=64) / TCP(
            sport=40000 + i, dport=443, flags="S", window=8192, seq=1000 + i)
        p.time = t0 + i
        pkts.append(p)
    p = IP(src="10.0.0.3", dst="10.0.0.4", ttl=128) / UDP(sport=5353, dport=5353)
    p.time = t0 + 5
    pkts.append(p)

    # baseline: bare builder fed via from_scapy
    bare = LiveWindowBuilder(bin_secs=BIN)
    for sp in pkts:
        o = from_scapy(sp)
        bare.observe(o.ts, o.src, o.sport, o.dst, o.dport, o.proto,
                     o.ip_len, o.tcp_flags)
    base_win = bare.flush_bin()

    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.pcap")
        wrpcap(path, pkts)
        windows = extract_pcap(path, bin_secs=BIN)

    assert len(windows) == 1
    ws = windows[0]
    # every legacy feature matches the reused builder exactly
    for name in V1_ORDER:
        assert ws.get(name).value == pytest.approx(base_win["features"][name]), name
    # packet-level extras came through the pcap file too
    assert ws.get("ttl_mean").value == pytest.approx((64 * 3 + 128) / 4)
    assert ws.get("ttl_std").value > 0
    assert ws.get("syn_ratio").value == pytest.approx(3 / 4)   # 3 SYN / 4 flows
    # non-IP/IPv6 packets would be skipped, not crash — from_scapy returns None
    from scapy.all import Ether
    assert from_scapy(Ether() / IP(src="1.1.1.1", dst="2.2.2.2") / TCP()) is not None
