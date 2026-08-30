"""Capture thread: Npcap/scapy sniff → LiveWindowBuilder.

Why scapy and not tshark: one dependency (Npcap), one language, no text
parsing between processes, and the packet rates in this demo (tens of pps
benign, a few thousand pps under SYN flood) are well inside pure-Python
capture territory. If packets drop under flood, the drop only under-samples a
flood that is 100x the benign baseline — the feature signature survives, and
the packet counter shown in the UI makes the drop visible, not hidden.

The sniffer sees every packet that reaches the demo laptop's interface:
traffic to/from the laptop itself, plus broadcast/multicast. On the switched
Wi-Fi used for the demo, the ATTACK TARGETS THE DEMO LAPTOP, so every attack
packet is visible by construction — that is the honest architecture, and it
is also how a real sensor on a gateway would see a subnet's traffic.
"""
from __future__ import annotations

import threading
import time

from .packet_windower import LiveWindowBuilder

# BPF filter: IPv4 TCP/UDP only — the feature set is port/flag based. ARP and
# IPv6 neighbor chatter would inflate flow counts in ways training never saw.
BPF = "ip and (tcp or udp)"


class LiveSensor:
    """Owns the sniffer thread + the window builder. Thread-safe enough for
    one sniffer thread writing and one API thread polling/flushing."""

    def __init__(self, iface: str | None = None, bin_secs: int = 30):
        self.iface = iface
        self.builder = LiveWindowBuilder(bin_secs=bin_secs)
        self._sniffer = None
        self._err: str | None = None
        self.started_at: float | None = None
        self._last_pkt_ts: float | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ control
    @property
    def running(self) -> bool:
        return self._sniffer is not None and self._sniffer.thread and self._sniffer.thread.is_alive()

    @property
    def error(self) -> str | None:
        return self._err

    def start(self) -> str | None:
        """Start sniffing. Returns an error string, or None on success."""
        if self.running:
            return None
        try:
            from scapy.all import AsyncSniffer
        except ImportError as exc:
            self._err = f"scapy not installed: {exc}"
            return self._err
        if self.iface is None:
            # conf.iface can name a dead adapter (e.g. unplugged Ethernet);
            # the default route always names the one carrying traffic.
            try:
                from scapy.all import conf
                self.iface = conf.route.route("0.0.0.0")[0]
            except Exception:  # noqa: BLE001 — fall back to scapy's default
                pass
        self._sniffer = AsyncSniffer(
            iface=self.iface, filter=BPF, prn=self._on_packet, store=False)
        try:
            self._sniffer.start()
        except Exception as exc:  # noqa: BLE001 — surface every capture failure
            self._err = f"cannot start capture on {self.iface or 'default iface'}: {exc}"
            return self._err
        # The thread can die instantly (e.g. Npcap absent: "winpcap is not
        # installed") without start() raising — verify it actually came up.
        import time as _time
        _time.sleep(0.5)
        if not self.running:
            self._err = ("capture thread died at startup - Npcap is probably "
                         "not installed (https://npcap.com/, default options)")
            self.stop()
            return self._err
        self.started_at = time.time()
        return None

    def stop(self) -> None:
        if self._sniffer is not None:
            try:
                self._sniffer.stop(join=True)
            except Exception:  # noqa: BLE001 — stopping must never raise
                pass
            self._sniffer = None

    # ------------------------------------------------------------ packets
    def _on_packet(self, pkt) -> None:
        try:
            ip = pkt.getlayer("IP")
            if ip is None:
                return
            ts = float(pkt.time) if pkt.time else time.time()
            tcp = pkt.getlayer("TCP")
            udp = pkt.getlayer("UDP")
            if tcp is not None:
                self.builder.observe(ts, ip.src, int(tcp.sport), ip.dst,
                                     int(tcp.dport), "tcp", int(ip.len),
                                     int(tcp.flags))
            elif udp is not None:
                self.builder.observe(ts, ip.src, int(udp.sport), ip.dst,
                                     int(udp.dport), "udp", int(ip.len), 0)
            self._last_pkt_ts = ts
        except Exception:  # noqa: BLE001
            # A malformed packet must never kill the capture thread. The
            # skipped counter below keeps the loss visible in the UI.
            self.builder.packets_skipped += 1

    # ------------------------------------------------------------- status
    def status(self) -> dict:
        return {
            "running": self.running,
            "iface": self.iface,
            "error": self._err,
            "bin_secs": self.builder.bin_secs,
            "packets_seen": self.builder.packets_seen,
            "packets_skipped": self.builder.packets_skipped,
            "flows_in_bin": self.builder.live_flow_count(),
            "bin_elapsed_s": round(self.builder.bin_elapsed(), 1),
            "bin_remaining_s": round(self.builder.current_bin_remaining(), 1),
            "started_at": self.started_at,
            "last_packet_age_s": (time.time() - self._last_pkt_ts)
                                 if self._last_pkt_ts else None,
        }

    # -------------------------------------------------------------- flush
    def poll(self) -> dict | None:
        """Called by the API on every feed request. Drains bins finalized by
        packet rollover first, then closes the wall-clock bin when it is
        overdue — so the timeline advances even when the page was backgrounded
        (many pending bins drain one per poll) or the network went quiet
        (explicit empty window, never a stall)."""
        if not self.running:
            return None
        if self.builder.pending:
            return self.builder.pending.pop(0)
        rem = self.builder.current_bin_remaining()
        if rem > 0:
            return None
        if self.builder.live_flow_count() > 0:
            return self.builder.flush_bin()
        return self.builder.flush_empty_bin()


def list_interfaces() -> list[str]:
    """Interface names for the UI picker (Npcap syntax, e.g. 'Wi-Fi 2')."""
    try:
        from scapy.all import get_if_list
        return list(get_if_list())
    except Exception as exc:  # noqa: BLE001 — no Npcap → empty list + reason
        return [f"(capture unavailable: {exc})"]
