"""Record ~N minutes of benign network traffic → seed windows for the live demo.

Run this ONCE (or before each rehearsal/demo) on the demo laptop while normal
traffic is flowing (browsing, video, git pulls — the room's real background):

  python scripts/record_seed.py --minutes 12 --iface "Wi-Fi"

Writes data/live/seed_windows.json — one feature dict per 30s bin, exactly the
shape src/live/packet_windower.flush_bin() produces. On demo day,
POST /api/live/start pre-loads these windows so the model has its 10-window
history the moment capture begins (no 5-minute dead air on stage).

The seed is REAL captured traffic, not synthetic. It is labeled `seed` in the
API and drawn differently in the UI — the jury can always tell replayed
background from live windows.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass

OUT = ROOT / "data" / "live" / "seed_windows.json"
BIN_SECS = 30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=12.0)
    ap.add_argument("--iface", default=None, help="capture interface (scapy name)")
    a = ap.parse_args()

    from src.live.sensor import LiveSensor

    print(f"recording {a.minutes:.0f} min of benign traffic "
          f"(iface={a.iface or 'default'}, {BIN_SECS}s bins)")
    sensor = LiveSensor(iface=a.iface, bin_secs=BIN_SECS)
    err = sensor.start()
    if err:
        print(f"ERROR: {err}")
        return 1

    windows: list[dict] = []
    deadline = time.time() + a.minutes * 60
    last_status = 0.0
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            w = sensor.poll()
            if w is not None:
                windows.append(w)
                f = w["features"]
                print(f"  bin {w['bin_id']}: flows={f['flow_count']:.0f} "
                      f"pkts={f['pkts_total']:.0f} syn={f['syn_ratio']:.2f} "
                      f"ports={f['unique_dst_ports']:.0f}"
                      + ("  [EMPTY]" if w.get("empty") else ""))
            if time.time() - last_status > 10:
                last_status = time.time()
                st = sensor.status()
                print(f"  ... {st['packets_seen']} pkts, "
                      f"{st['flows_in_bin']} flows in open bin, "
                      f"{st['bin_remaining_s']:.0f}s left in bin")
    except KeyboardInterrupt:
        print("\ninterrupted - keeping what we have")
    finally:
        sensor.stop()

    if len(windows) < 10:
        print(f"ERROR: only {len(windows)} windows recorded - need >= 10 "
              "(SEQ_LEN). Record longer, or check the interface.")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(windows, indent=1), encoding="utf-8")
    print(f"\nwrote {len(windows)} windows -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
