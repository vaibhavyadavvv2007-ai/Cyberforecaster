# Attack launchers - run from the ATTACKER device (2nd laptop / phone)

All three scripts target the **demo laptop's IP** on the same Wi-Fi. The demo
laptop's sensor sees every attack packet by construction (it is the target),
so no switch-spanning or monitor mode is needed.

## Setup on the attacker device (once)

**Windows laptop:**
```
winget install Python.Python.3.12        # or any Python 3.10+
pip install scapy
# install Npcap from https://npcap.com/ (default options are fine)
```

**Linux / Termux (Android):**
```
pip install scapy        # Termux: pkg install python && pip install scapy
# root required for raw sockets: su / sudo termux-chroot
```

Copy this folder (`scripts/attacks/`) to the attacker device. Get the demo
laptop's IP (shown in the Live page header) and run over the room Wi-Fi.

## The demo script (rehearsed order)

| Act | Command (on attacker) | What the jury sees on the demo laptop |
|---|---|---|
| 1. Port scan | `python syn_scan.py --target <ip> --minutes 1` | Rule engine flags **Reconnaissance** within one 30s window (unique ports + SYN ratio) |
| 2. UDP sweep (the forecast moment) | `python udp_sweep.py --target <ip> --minutes 4` | LSTM forecast climbs each window, **crosses the alert threshold after ~5 windows (~2.5 min)** and keeps rising toward ~0.98, stage DoS |
| 3. (optional) SYN flood | `python syn_flood.py --target <ip> --port 8080 --minutes 1` | Volumetric spike; pkts/bytes blow past training p99 |

Act 2 is the one that requires SUSTAINED traffic - the model forecasts
attack *progression*, so the pattern must persist several windows. Do not stop
it early; narrate the climb instead (that is the product's whole thesis).

## Honesty notes (say these out loud)

- The SYN scan and UDP sweep are chosen because they map onto the dataset's
  attack classes (recon + UDP flooding). The model was trained on CSE-CIC-IDS2018;
  live traffic is by definition a distribution shift, which is exactly why
  detection was verified in rehearsal (`scripts/live_rehearsal.py`) and not
  assumed.
- The LSTM does not cross on every attack shape (single-port SYN flood does
  not move it - CIC's TCP flag columns are mostly zero, a known dataset
  artifact, while live SYNs are real). The rule engine catches what the model
  does not; that layering is the design, not a bug.
- Attacks are launched against our own laptop on our own network, with
  permission, at demo-safe rates.
