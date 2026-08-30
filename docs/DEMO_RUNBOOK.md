# Demo-day runbook — SIH26153 internal round, Sat Sep 5, 2026

Everything below was verified on the demo laptop on Aug 30, 2026 (real
packets, real crossings — see "Verified numbers" at the bottom). Rehearse
this document top to bottom at least once before Sep 5; do not improvise
on stage.

---

## 0. The laptop (facts, not guesses)

- Demo laptop IP is shown in the Live page header once capture starts.
- Wi-Fi capture interface: `\Device\NPF_{07E61EE8-46AD-4FEC-8856-CBCBE2D131F1}`
  (verify on the day: `curl http://localhost:8000/api/live/interfaces`).
- Loopback (single-laptop fallback attacks): `\Device\NPF_Loopback`.
- Threshold: **0.561** · windows: 30 s · sequence 10 → horizon 5.
- Seed history: `data/live/seed_windows.json` (18 windows of this network's
  benign traffic, recorded Aug 30 with the fixed pipeline).

## 1. Pre-flight (do this 30 min before, on the demo Wi-Fi)

- [ ] Laptop on charger; Windows focus assist / notifications OFF; updates paused.
- [ ] `curl http://localhost:8000/api/health` → `"mode":"REAL"`, threshold `0.561`.
      If mode is CACHED/SIMULATED, the model failed to load — see §6.
- [ ] `curl http://localhost:8000/api/live/interfaces` → the Npcap names list.
- [ ] Quick benign check: start capture on Wi-Fi (Live page), let 2 windows
      close (~70 s). Forecast must read **LOW (≈0–25%)**. If it climbs on
      silence, the network changed → re-record the seed (§5).
- [ ] Attacker device on the SAME Wi-Fi, `scripts/attacks/` copied over,
      scapy installed, target IP noted (see `scripts/attacks/README.md`).

## 2. Boot order (if the laptop was rebooted)

```bash
# terminal 1 — API (must be first; it loads the model)
cd cyberforecaster && python -m uvicorn api.main:app --port 8000 --log-level warning

# terminal 2 — web
cd cyberforecaster/web && npm run dev          # http://localhost:3000
```

Open `http://localhost:3000` → header pill must show green **live · thr 0.56**.

## 3. The 7-minute arc (v2 — live attack included)

| Time | Beat | Action |
|---|---|---|
| 0:00 | Hook | "Detection tells you what happened. We forecast what happens next." |
| 0:30 | Thesis + architecture | classification vs evolution; telemetry → states → forecast(+why) |
| 1:00 | Offline rigor | Scenario → ANALYZE → FORECAST: the climb, the WHY? attribution, ATT&CK strip, benchmarks page ("chronological split, no leakage") |
| 2:00 | **Switch to LIVE** | `/live` → start capture on Wi-Fi. Narrate the gray seed segment: "recorded benign history of THIS network — the model needs 10 windows of context; nothing is fabricated." |
| 2:45 | **Act 1 — Recon** | Attacker: `python syn_scan.py --target <ip> --minutes 1`. Within ONE 30s window the **rule engine** flags Reconnaissance (unique ports + SYN ratio). Point at the events row. |
| 3:45 | **Act 2 — The forecast moment** | Attacker: `python udp_sweep.py --target <ip> --minutes 3`. Narrate the climb window by window: LOW → 0.38 → **0.95 HIGH, red hero, banner**. Hold ~2 min; it sustains ≈0.98. |
| 5:45 | Why it fired | Attribution panel on the live prediction; the two-engine story (rules catch the scan instantly, the LSTM forecasts progression — layering is the design). |
| 6:15 | Honesty + close | "Trained on CSE-CIC-IDS2018, verified live in rehearsal, never faked a detection." Close with the thesis line. |

Speaker notes for the live segment:

- The forecast is a **trajectory** reader: the first attack window still
  reads LOW (history is benign) — say that out loud, it IS the product
  thesis. It crosses on the 3rd sustained window (verified).
- UDP sweep must run **continuously** — do not stop it early.
- The SYN flood (Act 3) is optional; it trips the volumetric rule only.

## 4. Attacker device (2nd laptop) — exact commands

```bash
python syn_scan.py  --target <demo-ip> --minutes 1     # Act 1
python udp_sweep.py --target <demo-ip> --minutes 3     # Act 2 (do not cut short)
```

No second device on the day? Single-laptop fallback (verified working):

```bash
python scripts/live_rehearsal.py --minutes 5 --attack udp-sweep --attack-at 0.3 \
    --iface "\\Device\\NPF_Loopback"
```

…but drive the UI instead where possible: start capture on **Loopback** from
the Live page and run the rehearsal in a terminal for the attack only.

## 5. Seed maintenance

Re-record (~12 min) if the demo Wi-Fi is NOT the network the seed was
recorded on, or the benign check in §1 climbs unexpectedly:

```bash
python scripts/record_seed.py --minutes 12 \
    --iface "\\Device\\NPF_{07E61EE8-46AD-4FEC-8856-CBCBE2D131F1}"
```

Benign sanity after recording: all windows LOW, worst peak < 0.561, no rule
hits (verified Aug 30: worst 0.554).

## 6. Fallback chain (rehearse each handoff once)

1. Live two-device attack (primary).
2. Live self-attack over loopback (same laptop, still real packets).
3. Offline scenario demo (cached mode still shows the full forecast story).
4. Recorded video / printed screenshots.

Failure modes and fixes:

| Symptom | Cause | Fix |
|---|---|---|
| "capture thread died at startup" | Npcap missing/DLL | Reinstall Npcap (default options), reboot |
| 0 packets forever | Wrong interface (dead Ethernet) | Pick the Wi-Fi NPF name from `/api/live/interfaces` |
| Forecast climbs on silence | Stale seed / changed network | Re-record seed (§5) |
| Attack runs but peak stays LOW | Sweep too short / wrong target IP / attacker on wrong Wi-Fi | Let it run ≥3 full windows; re-check target IP in the Live header |
| `/api/health` mode ≠ REAL | Model load error (see `model_error`) | Reboot API; then cached mode is the honest fallback |

## 7. Verified numbers (Aug 30, 2026 — cite these, don't re-estimate)

**Two-device rehearsal over real Wi-Fi (the actual demo path — GO):**

- Benign on the demo hotspot network: worst peak **0.014** (after domain
  clamping, see below).
- SYN scan from attacker laptop: **Reconnaissance rule hit on 3 consecutive
  windows** (97-219 flows, syn 0.96-1.03, 93-212 unique ports); model stayed
  LOW 0.02-0.07 — the designed two-engine split.
- UDP sweep from attacker laptop (~17k flows, ~1032 ports per window):
  forecast **0.03 → 0.03 → 0.17 → 0.905 HIGH → 0.968 → 0.988** — crossing at
  the 4th sustained window, events fired on every HIGH window.

**Single-laptop loopback rehearsal (fallback path):**

- Benign loopback: peak 0.008-0.010 LOW.
- UDP sweep (~50k probes / 30s): 0.022 → 0.384 → 0.947 at window 3,
  sustains 0.977-0.989.
- SYN scan: rule Recon within one window.
- Exit code 0 from `scripts/live_rehearsal.py` = flagged as rehearsed.

**Live-input domain conditioning (Aug 30, `src/live/history.py`):** live
windows are conditioned to the model's training domain before inference —
IP features zeroed (constant 0 in training) and flag-ratio/down_up features
clamped to training p99 (CIC's long-flow aggregation makes live short-flow
ratios 10-20x out of domain; unclamped, a quiet network's benign traffic
read 0.69 — clamped, 0.014, attack still crosses). The rule engine always
sees raw values. Say this openly if asked — it is input conditioning, not
result manipulation.

**Attacker device lessons (learned the hard way):** Android/Termux cannot
send scapy packets ("Scapy does not support android — I/O will NOT work").
The attacker must be a laptop with Npcap. Target the laptop's PRIVATE Wi-Fi
IP (10.x/192.168.x from `ipconfig`), never the carrier public IP.

**Seed rule:** the seed must be recorded on the network you demo from
(12 min, §5). A seed from a different network skews the baseline — verified
both directions on Aug 30 (matched network: 0.014; mismatched: 0.65+).
