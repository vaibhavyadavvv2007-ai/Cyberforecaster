"""TCP SYN port scan - the RULE-ENGINE attack (fires within one 30s window).

Half-open SYN scan across many ports. One window of this produces
unique_dst_ports >= 15 and syn_ratio >= 0.4, which trips the independent
rule engine's Reconnaissance rule immediately - the demo's instant detection
moment, before the LSTM's sustained pattern has had time to build.

  python syn_scan.py --target 192.168.1.20 --minutes 1

Equivalent ready-made tools (pick whichever device is easier):
  nmap -sS -p 1-2048 <target>          (Linux/Mac/Windows nmap)
  hping3 -S --scan 1-2048 <target>     (Linux)
"""
from __future__ import annotations

import argparse
import random
import time

from scapy.all import IP, TCP, sr1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True)
    ap.add_argument("--minutes", type=float, default=1.0)
    ap.add_argument("--rate", type=float, default=30.0, help="SYNs per second")
    a = ap.parse_args()

    ports = list(range(1, 2049)) + [3306, 3389, 5432, 6379, 8080, 8443, 9000]
    print(f"SYN scan -> {a.target}: {len(ports)} ports, {a.rate:.0f}/s")
    deadline = time.time() + a.minutes * 60
    interval = 1.0 / a.rate
    n = 0
    while time.time() < deadline:
        dport = ports[n % len(ports)]
        sport = random.randint(40000, 65000)
        pkt = IP(dst=a.target) / TCP(sport=sport, dport=dport, flags="S")
        try:
            sr1(pkt, timeout=0.05, verbose=0)
        except Exception:  # noqa: BLE001 — RST/refused is the expected reply
            pass
        n += 1
        time.sleep(interval)
    print(f"sent {n} SYNs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
