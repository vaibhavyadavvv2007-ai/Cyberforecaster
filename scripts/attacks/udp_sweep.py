"""UDP service sweep - the LIVE LSTM-crossing attack (rehearsed, verified).

Sends UDP probes to many destination ports with varying source ports, so each
30s window sees ~1000+ distinct flows spread across dozens of ports with zero
TCP flags - the same feature signature as the dataset's UDP-flood attacks
(LOIC-UDP / HOIC), which is what the trained forecaster responds to most
strongly. Rehearsed verdict (see scripts/live_rehearsal.py --attack
udp-sweep): forecast crosses the 0.561 threshold after ~5 sustained windows.

Run ON THE ATTACKER DEVICE (2nd laptop / phone with Termux), aimed at the
demo laptop's IP:

  python udp_sweep.py --target 192.168.1.20 --minutes 4

Needs: Python 3 + scapy + Npcap (Windows attacker) or root (Linux/Termux).
"""
from __future__ import annotations

import argparse
import random
import time

from scapy.all import IP, UDP, send


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True, help="demo laptop IP")
    ap.add_argument("--minutes", type=float, default=4.0,
                    help="sustained duration (model crosses after ~5 x 30s windows)")
    ap.add_argument("--rate", type=float, default=45.0,
                    help="probes per second (45/s = ~1350 flows per 30s window)")
    ap.add_argument("--ports", default="1-1024,3306,3389,5432,6379,8080,8443,9000,17500",
                    help="destination port pool")
    a = ap.parse_args()

    pool: list[int] = []
    for part in a.ports.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            pool.extend(range(int(lo), int(hi) + 1))
        else:
            pool.append(int(part))
    print(f"UDP sweep -> {a.target}: {len(pool)} ports, {a.rate:.0f}/s "
          f"for {a.minutes:.1f} min")

    deadline = time.time() + a.minutes * 60
    interval = 1.0 / a.rate
    n = 0
    while time.time() < deadline:
        sport = random.randint(30000, 60000)
        dport = pool[n % len(pool)]
        pkt = IP(dst=a.target) / UDP(sport=sport, dport=dport) / ("X" * 42)
        send(pkt, verbose=0)
        n += 1
        # soft pacing: scapy send is slow enough that most rates need no sleep
        if a.rate < 40:
            time.sleep(interval)
    print(f"sent {n} probes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
