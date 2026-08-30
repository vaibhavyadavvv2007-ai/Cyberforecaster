"""Full live-pipeline rehearsal — verify detection BEFORE demo day.

Runs the exact demo chain end-to-end on this laptop:

  seed windows (or fresh benign capture)
    -> live capture for N minutes
    -> optionally a self-launched attack (SYN scan / SYN flood against this
       machine's own IP, so no second device is needed for rehearsal)
    -> model forecast per window + rule-engine cross-check
    -> prints the verdict table

Exit code 0 = attack windows were flagged (model OR rule engine). Rehearse,
do not improvise: if this script does not flag, demo day will not either.

  python scripts/live_rehearsal.py --minutes 2                    # benign only
  python scripts/live_rehearsal.py --minutes 4 --attack syn-scan
  python scripts/live_rehearsal.py --minutes 4 --attack syn-flood
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import threading
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

BIN_SECS = 30


def self_udp_sweep(target_ip: str, duration: float) -> None:
    """UDP sweep of our own ports — the rehearsed LSTM-crossing attack
    (mirrors scripts/attacks/udp_sweep.py so rehearsal tests the real thing)."""
    from scapy.all import IP, UDP, conf, send
    conf.verb = 0
    import random
    ports = list(range(1, 1025)) + [3306, 3389, 5432, 6379, 8080, 8443, 9000]
    deadline = time.time() + duration
    n = 0
    while time.time() < deadline:
        sport = random.randint(30000, 60000)
        dport = ports[n % len(ports)]
        send(IP(dst=target_ip) / UDP(sport=sport, dport=dport) / ("X" * 42),
             verbose=0)
        n += 1
    print(f"    (self-attack sent {n} UDP probes)")


def self_syn_scan(target_ip: str, duration: float) -> None:
    """SYN scan our own ports with scapy — the same packet signature the
    attacker laptop will produce against us on demo day."""
    from scapy.all import IP, TCP, sr1, conf
    conf.verb = 0
    ports = list(range(1, 1025)) + [3306, 3389, 5432, 6379, 8080, 8443, 9000]
    deadline = time.time() + duration
    i = 0
    while time.time() < deadline:
        for dport in ports:
            if time.time() >= deadline:
                return
            pkt = IP(dst=target_ip) / TCP(dport=dport, flags="S", sport=33333 + (i % 200))
            try:
                sr1(pkt, timeout=0.05, verbose=0)
            except Exception:  # noqa: BLE001 — closed ports RST, that's the point
                pass
            i += 1


def self_syn_flood(target_ip: str, duration: float) -> None:
    from scapy.all import IP, TCP, send, conf
    conf.verb = 0
    deadline = time.time() + duration
    i = 0
    while time.time() < deadline:
        send(IP(dst=target_ip) / TCP(dport=8080, flags="S",
                                     sport=40000 + (i % 4096)) / ("X" * 16),
             verbose=0, count=200)     # raw L3 send: no kernel handshake state
        i += 200


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--iface", default=None)
    ap.add_argument("--attack", choices=["udp-sweep", "syn-scan", "syn-flood"],
                    default=None,
                    help="self-launch this attack halfway through the capture "
                         "(udp-sweep is the rehearsed LSTM-crossing attack)")
    ap.add_argument("--attack-at", type=float, default=0.5,
                    help="fraction of the run after which to attack (0-1)")
    a = ap.parse_args()

    from src.features.window_builder import SEQ_LEN
    from src.forecasting.rollout import Forecaster
    from src.live.history import LiveHistory
    from src.live.sensor import LiveSensor, list_interfaces

    print("interfaces:", list_interfaces())
    if a.attack:
        print("NOTE: a self-attack to this machine's own IP routes over the "
              "LOOPBACK adapter, not Wi-Fi. Capture it with --iface "
              "\"Npcap Loopback Adapter\" (install Npcap with loopback "
              "support). The two-device demo needs no such workaround - the "
              "attack crosses the real interface.")

    import pandas as pd
    windows_train = pd.read_parquet(ROOT / "data" / "processed" / "windows.parquet")
    p99 = (float(windows_train["bytes_total"].quantile(0.99)),
           float(windows_train["pkts_total"].quantile(0.99)))

    fc, err = Forecaster.load()
    if fc is None:
        print(f"ERROR: no model ({err}) - run rebuild_all first")
        return 1
    print(f"model: threshold={fc.threshold:.3f} horizon={fc.horizon}")

    hist = LiveHistory(forecaster=fc, rule_p99=p99)
    n_seed = hist.load_seed()
    print(f"seed windows: {n_seed} (record with scripts/record_seed.py if 0)")

    sensor = LiveSensor(iface=a.iface, bin_secs=BIN_SECS)
    err = sensor.start()
    if err:
        print(f"ERROR: {err}")
        return 1

    total = a.minutes * 60
    attack_t = total * a.attack_at
    attack_thread: threading.Thread | None = None
    launched = False
    target_ip = socket.gethostbyname(socket.gethostname())
    print(f"capturing {a.minutes:.1f} min on {sensor.iface or 'default iface'}; "
          f"local ip {target_ip}"
          + (f"; attack={a.attack} at t+{attack_t:.0f}s" if a.attack else ""))

    rows: list[dict] = []
    t0 = time.time()
    try:
        while time.time() - t0 < total:
            time.sleep(1.0)
            if a.attack and not launched and time.time() - t0 >= attack_t:
                fn = {"udp-sweep": self_udp_sweep,
                      "syn-scan": self_syn_scan,
                      "syn-flood": self_syn_flood}[a.attack]
                attack_thread = threading.Thread(target=fn,
                                                 args=(target_ip, total - attack_t - 5),
                                                 daemon=True)
                attack_thread.start()
                launched = True
                print(">>> ATTACK LAUNCHED <<<")
            w = sensor.poll()
            if w is None:
                continue
            w["source"] = "live"
            hist.append_live(w)
            if not hist.ready():
                continue
            pred = hist.predict()
            f = w["features"]
            row = {
                "bin": w["bin_id"], "flows": f["flow_count"],
                "pkts": f["pkts_total"], "syn": round(f["syn_ratio"], 2),
                "ports": f["unique_dst_ports"],
                "peak": pred["peak"], "level": pred["level"],
                "stage": pred["stage"], "rule": pred["rule_stage"] or "-",
            }
            rows.append(row)
            print(f"  bin {row['bin']}: flows={row['flows']:.0f} pkts={row['pkts']:.0f} "
                  f"syn={row['syn']:.2f} ports={row['ports']:.0f} -> "
                  f"peak={row['peak']:.3f} [{row['level']}] "
                  f"stage={row['stage'] or '-'} rule={row['rule']}")
    except KeyboardInterrupt:
        print("\ninterrupted early")
    finally:
        sensor.stop()

    if not rows:
        print("no live windows closed - capture too short or interface silent")
        return 1

    # verdict: did any window during the attack phase get flagged?
    thr = fc.threshold
    flagged_model = [r for r in rows if r["peak"] >= thr]
    flagged_rule = [r for r in rows if r["rule"] != "-"]
    print("\n" + "=" * 72)
    print(f"windows analyzed: {len(rows)}  threshold: {thr:.3f}")
    print(f"model crossings: {len(flagged_model)}   rule-engine hits: {len(flagged_rule)}")
    if flagged_model:
        print(f"  first model crossing: peak={flagged_model[0]['peak']:.3f} "
              f"stage={flagged_model[0]['stage']}")
    if a.attack and not (flagged_model or flagged_rule):
        print("\n[FAIL] attack ran but NEITHER model NOR rules flagged it.")
        print("       Do not demo this attack until this script flags it.")
        return 1
    print("\n[OK] rehearsal verdict above - record it for the runbook.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
