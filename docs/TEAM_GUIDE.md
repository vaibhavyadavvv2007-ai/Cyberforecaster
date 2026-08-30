# CyberForecaster — the complete team guide

**SIH26153 · Network Attack Forecasting · Internal round: Saturday Sep 5, 2026**

This document is the single place where a teammate who has never opened this
repo can learn: what we built, why each decision was made, how every piece
works, how to run all of it, and what their own role owns. Read it top to
bottom once (~45 min); after that use it as a reference.

Companion documents (each is the authority on its own topic):

| Document | Authority on |
|---|---|
| `README.md` | repo quickstart, honesty rails |
| `SIH26153_battle_plan.md` | strategy, calendar, jury Q&A bank |
| `docs/DEMO_RUNBOOK.md` | demo-day choreography, fallbacks, verified numbers |
| `DESIGN.md` | the UI design system |

---

## 0. The 60-second version

We built a system that **forecasts network attacks before they finish**.
Instead of asking "is this traffic bad right now?" (a classifier — what every
IDS does), we ask: **"given the last 5 minutes of network behavior, what is
the probability that attack activity appears in the next 2.5 minutes, which
stage of the kill chain is coming, and which measurements drove that
prediction?"**

One trained LSTM does this. It is served two ways, both fully offline on one
laptop:

1. **Offline scenario console** — pick a real historical attack window from
   the CSE-CIC-IDS2018 dataset, run the forecast, see the probability curve,
   the ATT&CK stage, and per-feature attribution.
2. **Live sensor** — capture real packets on this laptop's Wi-Fi (Npcap),
   convert them into the exact same 18-feature windows the model was trained
   on, and forecast live. On demo day we attack our own laptop from a second
   laptop and the forecast visibly crosses the alert threshold in front of
   the jury.

The one sentence everyone memorizes:

> **"We don't classify traffic — we model how network state evolves over time
> and forecast an attack's progression before it completes, with every
> prediction explained."**

Team: 2 × ML (model, features, evaluation), Data Engineering (pipeline,
dataset), Backend (FastAPI + integration), Frontend (Next.js console),
Domain/Pitch (story, ATT&CK mapping, Q&A). Everyone demos.

---

# PART I — Concepts from zero

*If you already know what a TCP flow and a SYN flag are, skim to §I.3.*

## I.1 Packets, flows, flags

- A **packet** is one unit of data on the network. It has source/destination
  IP + port, a size, and (for TCP) a set of flag bits.
- A **flow** is one conversation: same 5-tuple (src ip, src port, dst ip,
  dst port, protocol) in a time window. Browsers open many flows; a port
  scan opens thousands per minute.
- TCP flags mark the handshake/teardown: **SYN** = start a connection,
  **ACK** = acknowledge, **FIN** = close politely, **RST** = abort, **PSH** =
  "deliver now". A scanner sends SYN to many ports and never completes
  handshakes — that's what makes scans *visible in flag statistics*.
- Ports identify services (22 SSH, 445 SMB, 3389 RDP...). Touching 1000
  different ports in 30 seconds is scanning behavior by definition.

## I.2 The measurement: a "window"

Raw packets are too fine-grained for a small model; we aggregate. A
**window** is 30 seconds of traffic summarized into **18 numbers** — the
feature vector (full list in §II.4). Windows are the model's language: in
goes a sequence of 10 consecutive windows (5 minutes of history), out comes
a forecast for the next 5 windows (2.5 minutes ahead). This is the
`L=10, K=5` notation you'll see everywhere (`SEQ_LEN=10`, `HORIZON=5`).

## I.3 Forecasting vs classification (the whole point)

A classifier looks at one window in isolation and says bad/not-bad. It
cannot say anything about the future, and it fires on any single weird
window. Our model consumes a **trajectory** — 10 windows — and rolls the
state forward. Two consequences that show up throughout this project:

1. **Persistence matters.** The model learned that attack activity in the
   recent past is the strongest predictor of attack activity ahead (this is
   true in the data — attacks persist). A single attack-shaped window on
   top of quiet history scores LOW; three sustained attack windows cross
   HIGH. This is *honest behavior* and it is exactly what the demo shows.
2. **A quiet period after attacks decays slowly**, which matches how real
   incidents unwind.

## I.4 ATT&CK stages

MITRE ATT&CK is the industry taxonomy of attack behavior. The problem
statement names five progression stages; we predict which is coming:

```
Reconnaissance → Initial Access → Lateral Movement → Command & Control → Exfiltration
```

DoS/flooding is technically outside this progression (ATT&CK places it under
Impact), so it's handled as its own sixth category in the label head and the
rule engine. If a juror asks "why is DoS separate" — that's the answer, and
it's the honest one.

## I.5 The dataset in one paragraph

**CSE-CIC-IDS2018** is a public benchmark built by the Canadian Institute
for Cybersecurity: a realistic test network (servers, DMZ, benign user
profile scripts generating background traffic) attacked on schedule with
real tools — LOIC (DDoS), Hulk/GoldenEye (DoS), Metasploit (Infiltration),
Ares (botnet), brute-forcers, web attacks. Each day-file is a set of
**flow records** (one row per flow, ~80 columns produced by the CICFlowMeter
tool) plus a `Label` column saying benign or which attack. It is the
standard "looks like real telemetry" dataset for this kind of work — we did
not synthesize anything.

---

# PART II — The data pipeline (Data Engineering + ML own this)

## II.1 From raw CSV to windows

```
data/raw/*.csv                  one CSV per day, flow records, ~80 columns
   │  src/ingestion/csv_loader.py
   ▼  label canonicalization, dup-header rows dropped, NaN/inf rates fixed,
      epoch-artifact timestamps (year 1970) filtered by plausibility check
clean flow table
   │  src/preprocessing/pipeline.py
   ▼  sort by timestamp → bin into 30s windows → 18 features per window
data/processed/windows.parquet   ~6,192 windows, indexed by time
   ▼  sliding sequences: 10 in → 5 out, labels attached per step
data/processed/sequences_{train,val,test}.npz
   ▼  scaler fitted on TRAIN ONLY (log1p + standardize)
data/processed/scaler.npz        THE one input transform, shared by every model
```

Rebuild everything in order: `python scripts/rebuild_all.py` (fails fast at
the first broken step). Audit before any demo: `python scripts/verify_state.py`.

## II.2 Verified dataset facts (each one cost us time — memorize them)

| Fact | Consequence |
|---|---|
| The label is misspelled **"Infilteration"** | a naive substring match on "infiltration" silently drops 161k flows and all Lateral Movement supervision |
| The column is **"Pkt Size Avg"**, not "Avg Pkt Size" | silent KeyError otherwise |
| The ML-ready CSVs ship **no `Src IP`/`Dst IP` columns** | `unique_src_ips`/`unique_dst_ips` are constant 0 in ALL of training (see §VIII.5 for what we do live) |
| Flag-count columns are near-dead (median 0 even for TCP) | CICFlowMeter aggregates long-lived flows; live short flows have real flag counts — the reason for input conditioning (§VIII.5) |
| Feb-14 file truncated at 13:00 (no Heartbleed) | day-file coverage must be checked, not assumed |
| The **Infiltration** family has only ~dozens of windows | we forecast across families, not infiltration-only (§III.1) |
| 1,486 of 6,192 windows (~24%) contain attack | classic imbalance; why precision/recall/FPR matter more than accuracy |

## II.3 The split (do not touch, do not shuffle)

**Chronological 70/15/15 with a boundary purge.** Sequences that straddle a
split boundary are dropped — otherwise a training sequence overlaps a test
sequence in time and the model "remembers the future". Random shuffling
would inflate every metric and is refused outright. Bonus property we got
for free: the test split (Feb 28 + Mar 1) is dominated by **Infiltration, a
family absent from training** — so test measures *transfer to an unseen
attack family*, the hardest honest setting.

## II.4 The 18 window features

| # | Feature | Meaning |
|---|---|---|
| 1 | `flow_count` | distinct conversations in the window |
| 2 | `bytes_total` | total bytes |
| 3 | `pkts_total` | total packets |
| 4 | `duration_mean` | mean flow duration (s) |
| 5–9 | `syn/ack/fin/rst/psh_ratio` | flag packets per flow (TCP) |
| 10 | `unique_dst_ports` | distinct destination ports touched |
| 11 | `auth_port_share` | share of flows to {20,21,22,23,3389} |
| 12–13 | `unique_dst/src_ips` | distinct endpoints (constant 0 in training) |
| 14 | `dst_port_entropy` | Shannon entropy over the port histogram — high = spread over many ports (scanning), low = hammering few |
| 15–16 | `iat_mean`, `iat_std` | inter-arrival time statistics within flows — jittery (flood) vs metronomic (beaconing) |
| 17 | `avg_pkt_size` | mean packet size |
| 18 | `down_up_ratio` | response/request byte ratio |

Windows are 30 seconds. (We A/B-tested 60s vs 30s on Aug 30: 30s doubled
training sequences 2,031 → 4,145 and slightly improved val AP; Gate 1
decided 30s. The old 60s artifacts are backed up in `data/processed_60s_backup/`.)

---

# PART III — The models (ML pair own this)

## III.1 Task definition (say it exactly like this)

> Given the last `L=10` windows, predict for each of the next `K=5` windows
> whether it contains attack activity (`y_prog`, one label per horizon step
> — not one broadcast label), and predict the dominant ATT&CK stage across
> the horizon (`y_stage`, 6 classes: the 5 stages + DoS).

We forecast **across attack families** at window level rather than
"infiltration only" — Infiltration has dozens of samples and would starve
the model. If asked, present this as the mature trade-off it is.

## III.2 The input transform — one function, one place

`src/features/scaling.py`: **log1p then standardize**, scaler fitted on the
train split only, saved once (`scaler.npz`), imported by the logistic
baseline, the LSTM, the attribution code, the API and the live pipeline.
History: the baseline once scaled its inputs while the LSTM got raw
features, making our own benchmark unfairly *worse*. Any transform change
made in one place only will drift again — hence the rule.

## III.3 The model ladder

| Rung | Model | Purpose |
|---|---|---|
| 0 | **Logistic regression** on flattened 10×18 inputs, one per horizon step | the problem-statement-required benchmark; also our sanity floor |
| 1 | **2-layer LSTM (hidden 64)** → multi-task heads (5 progression logits + stage head) | the temporal forecaster we demo |

Same features, same scaling, same split for both — the comparison isolates
*temporal modeling* as the only difference. That's why the benchmark table
is a fair claim.

## III.4 Training facts you should be able to recite

- Trained with early stopping on **validation AP computed once over the
  pooled split** (averaging per-batch AP is not AP — with ~24% positives
  many batches still have none, and checkpoint selection was being driven
  by noise).
- **PATIENCE=25 matters**: validation is 881 sequences; per-epoch AP
  is noisy. With patience 8 the best checkpoint landed at epoch 4 and
  couldn't even fit training data (train AP 0.545). After the fix: val AP
  0.68.
- Kaggle/Colab path exists (`notebooks/Colab_Training.ipynb`) — bring back
  `metrics_lstm.json`, not just weights.

## III.5 Current metrics (from `models/*.json` — never hand-typed)

| Metric (test split) | LSTM | Logistic |
|---|---|---|
| PR-AUC | **0.656** | 0.333 |
| Precision @ operating point | **0.88** | 0.50 |
| Recall @ operating point | 0.14 | 0.009 |
| False-positive rate | **0.006** | 0.003 |

How to read this honestly: at the alert threshold, when the LSTM says
"attack coming", it is right 88% of the time, and it falsely alerts on
0.6% of quiet windows — but it catches a minority (14%) of onsets in the
unseen-family test split. It is a **high-precision early-warning system,
not a catch-everything detector** — exactly the profile a SOC analyst wants
from decision support, and exactly how we pitch it.

**Threshold 0.5612** is not 0.5-by-default: it is the score that produces a
5% false-positive budget (`max_fpr=0.05`) **on the validation split** —
never on test, never tuned by hand on demo day.

## III.6 Two honest limitations (own them before a juror finds them)

1. **No pre-onset magic.** CIC attacks are scripted and start abruptly; the
   model cannot warn before the first attack packets exist. Verified with
   `scripts/diagnose_leadtime.py` — the lead-time table shows warned_rate 0.
   Our differentiators are *persistence forecasting* (0.90-0.97 mid-attack),
   per-step decay curves, and cross-family transfer — not clairvoyance.
2. **It is a persistence detector.** An attack window on top of benign
   history scores 0.006; on top of attack-shaped history, 0.987. That is
   what the data teaches, it is why the live demo attack must *sustain*,
   and it is the product thesis stated plainly.

---

# PART IV — Explainability (why every prediction shows its work)

`src/explainability/attribution.py` implements **Integrated Gradients**
(Captum) over the input sequence: per-feature contribution to THIS
prediction, with a permutation fallback if Captum is unavailable. The UI
renders the top features as attribution bars plus a plain-language sentence
derived from the actual top two features (never invented text). On the live
page, attribution runs on every forecast. This is W4 (explainability is
interactive) and the answer to "why should we trust it".

---

# PART V — The rule engine and MITRE mapping (Domain + ML-B own it)

`src/attack_mapping/mitre_mapper.py` has three jobs:

1. **FAMILY_STAGE table** — maps each CIC attack family to its stage
   (brute-force → Initial Access, botnet → C2, infiltration → Lateral
   Movement, ...) for training labels.
2. **`rule_based_stage(f, p99_bytes, p99_pkts)`** — a transparent,
   no-ML cross-check that labels one window from its features. Rules are
   checked in order (first match wins; distinctive signatures before generic
   volume):
   1. many ports + SYN-heavy → **Reconnaissance** (≥15 unique ports AND
      syn_ratio ≥ 0.4)
   2. bursts at remote-access ports → **Initial Access**
   3. volumetric flood, extreme on BOTH p99 metrics → **DoS**
   4. regular low-jitter beaconing, low volume, ≥30 packets → **C2**
      (the packet floor stops near-dead windows being called beaconing)
   5. internal endpoints + **SMB/RPC/RDP/WinRM port share ≥ 0.2** →
      **Lateral Movement** (live-only signal, see below)
   6. huge outbound transfer with few flows → **Exfiltration**
3. **`validate_rules()`** — scores the rules against labeled training
   windows so thresholds are tuned against data, never by feel.

Two subtleties we fixed during live testing (both verified, both are good
jury stories):

- **Lateral movement offline vs online.** Training data has no IPs, so
  endpoint-count rules can never fire offline — the rule *abstains* (an
  explained abstention beats a fabricated threshold). Live, we DO see IPs,
  but "≥3 endpoints" is true of every benign Wi-Fi window (SSDP/mDNS
  chatter) — so live we additionally require traffic to actual Windows
  admin ports (`lateral_port_share ≥ 0.2`, computed only by the live
  windower).
- The C2 rule needed a minimum-activity floor (≥30 packets) because a
  5-flow/14-packet near-silent window otherwise matched "beaconing".

The two-engine story for the demo: **the rule engine catches what the model
does not** (a SYN scan trips rules in one window but never moves the LSTM —
CIC's flag columns are near-dead, a dataset artifact), and the model
forecasts what rules cannot (progression). Layering is the design.

---

# PART VI — Backend architecture (Backend owns this)

```
                 ┌────────────────────── FastAPI :8000 (api/) ─────────────────────┐
                 │  api/state.py     loads model+scaler+windows ONCE at boot      │
                 │  api/main.py      routes                                        │
                 │  api/schemas.py   pydantic contracts                            │
                 │  api/live_state.py  the live service (sensor + history)         │
                 └────────────────────────────────────────────────────────────────┘
  /api/health /api/scenarios /api/forecast          /api/live/status|start|stop|feed|interfaces
        │ offline demo (cached real predictions)                │ live demo (real packets)
        ▼                                                      ▼
  web/ (Next.js :3000)  ◄───────────── JSON over HTTP ──────────┘
```

Contracts: the frontend consumes the JSON shapes produced here verbatim —
every number on screen comes from the API, nothing is computed in the
browser. `web/lib/api.ts` is the typed client mirroring `api/schemas.py`.

**Honesty modes** (never hidden, always in the header): `REAL` (live
inference now) · `CACHED` (precomputed *real* predictions, frozen by
`scripts/build_demo_cache.py` — deterministic and crash-proof) ·
`SIMULATED` (explicitly-marked placeholder, last resort). The health
endpoint reports the mode and any boot error; a rehearsal must never
accidentally run in a fallback.

Fallback chain on demo day: Next.js console → Streamlit (kept working) →
recorded video → printed screenshots. `scripts/check_api.py` verifies the
API reproduces the rehearsed numbers.

---

# PART VII — Frontend (Frontend owns this)

Next.js 15 + TypeScript + Tailwind 4 + Recharts, fully offline (self-hosted
Inter + JetBrains Mono via fontsource — no CDN, the venue may have no
internet). Pages:

- **`/` (Console)** — scenario picker → ANALYZE (history timeline) →
  FORECAST (5-step curve vs threshold) → hero probability + risk badge,
  ATT&CK progression strip, attribution, benchmark summary.
- **`/benchmarks`** — LSTM vs logistic tables, horizon chart, the
  chronological-split statement.
- **`/live`** — capture control, live hero forecast, seed-vs-live chart,
  events, per-window table, attribution.

Design system lives in `DESIGN.md` + `.impeccable/design.json`; colors are
semantic only (amber=forecast/attention, red=danger, green=healthy,
blue=info) on a dark analyst-console ground; `web/lib/chartTheme.ts` holds
hex constants because Recharts cannot read CSS variables. Numbers use
JetBrains Mono with tabular numerals; sentence case everywhere except
10px mono section labels. The honesty contract (REAL/CACHED/SIMULATED
pill) is always visible in the header.

---

# PART VIII — The live pipeline (everyone must understand this one)

This is the demo centerpiece: **real packets → the exact training feature
vector → the same trained model → live forecast.** Four modules in
`src/live/`:

## VIII.1 Sensor (`sensor.py`)

Scapy `AsyncSniffer` on Npcap (Windows), BPF filter `ip and (tcp or udp)`,
feeding the windower. Hard-won Npcap facts:

- Without Npcap's DLL the capture thread **dies silently** (interfaces still
  list) → `start()` sleeps 0.5s and verifies the thread is alive; the UI
  then says "capture thread died at startup — Npcap probably not installed".
- `conf.iface` (scapy's default) can name a **dead adapter** (unplugged
  Ethernet) → we resolve the interface from the default route:
  `conf.route.route("0.0.0.0")[0]`.
- This laptop's Wi-Fi device is
  `\Device\NPF_{07E61EE8-...}`; loopback is `\Device\NPF_Loopback`. Always
  list live ones: `curl :8000/api/live/interfaces`.

## VIII.2 Window builder (`packet_windower.py`)

Turns packets into the same 18 features. Key behaviors:

- **Bidirectional flows.** Both directions of a conversation are ONE flow
  (CICFlowMeter's convention), keyed canonically so direction of first
  packet defines forward/backward. Otherwise every handshake counts as two
  flows and counts inflate 2× against training.
- **Welford online variance** for per-flow inter-arrival times — O(1)
  memory per flow. (This is where our worst bug lived; see §VIII.6.)
- Windows close on wall-clock boundaries; a silent 30s becomes an explicit
  all-zero window (an honest observation, not a gap).
- It also computes one **live-only extra**: `lateral_port_share` (share of
  flows to SMB/RPC/RDP/WinRM ports) — used by rule 5, never by the model.

## VIII.3 Seeded history (`history.py`, `scripts/record_seed.py`)

The model needs 10 windows of context before it can forecast — waiting 5
minutes on stage is dead air. So the history is **pre-seeded with ~18
benign windows recorded on the demo network beforehand** (12-minute
recording). Seeded windows are labeled `source: "seed"` and drawn gray in
the chart; live windows are amber. The jury sees exactly what is replayed
background and what is live. **The seed must be recorded on the network you
demo from** — verified both directions on Aug 30 (matched seed: benign peak
0.014; seed from a different network: 0.65+ false ELEVATED, because network
quietness/shape differs).

## VIII.4 Attacks (run from the attacker laptop, `scripts/attacks/`)

All against our own laptop, at demo-safe rates, on the same Wi-Fi:

| Act | Script | What happens |
|---|---|---|
| 1 | `syn_scan.py --target <ip> --minutes 1` | SYN scan of ~2,050 ports → rule engine flags **Reconnaissance** within one 30s window (model stays LOW — by design) |
| 2 | `udp_sweep.py --target <ip> --minutes 3` | UDP sweep, ~1,032 ports, ~17k flows/window → LSTM forecast climbs window by window and **crosses HIGH at the 4th sustained window (~0.905) → 0.98**. This is the money moment. |
| 3 (optional) | `syn_flood.py --target <ip> --port 8080 --minutes 1` | volumetric spike past training p99 → DoS rule |

The sweep must run the full 3 minutes — the model forecasts *progression*,
so the pattern must persist. Narrate the climb; that IS the thesis.
**Android/Termux cannot be the attacker** — scapy raw I/O is unsupported on
Android and sends nothing. The attacker must be a laptop with Python +
scapy + Npcap. Target the demo laptop's **private Wi-Fi IP** (from
`ipconfig` — e.g. `10.x.x.x`), never the carrier's public IP.

## VIII.5 Input conditioning — the honesty-critical part

Live traffic differs from CIC training flows in two structural ways. Both
are handled by conditioning **model input** to the model's validated domain
(`model_matrix()` in `src/live/history.py`) while the **rule engine always
sees raw values**:

1. **IP features are zeroed.** Training has no IP columns, so
   `unique_src/dst_ips` are constant 0 — live real counts are out-of-spec
   input that pushed benign toward "attack" (measured: 0.613 → 0.554).
2. **Ratios are clamped to the training p99** (`syn/ack/fin/rst/psh_ratio`,
   `down_up_ratio`). CIC flows are long-lived aggregates (flags-per-flow
   ≈ 0); live short TCP transactions run ack 9.9 / psh 4.1 / fin 0.38 vs
   training p99 0.57 / 1.0 / 0.03. On a quiet network that alone read
   **0.69 ELEVATED on pure benign**; clamped, benign reads **0.014** and the
   attack still crosses (0.951 at window 4).

This is input conditioning to the trained domain — the same class of
decision as feeding the model the feature spec it was trained on — **not**
result manipulation. The measurements above are exactly what you say if a
juror probes.

## VIII.6 The bug story (know it — it is our rigor story)

First live rehearsal read **0.98 HIGH DoS on pure benign Wi-Fi**. Chain of
diagnosis: greedy feature substitution showed `iat_std` alone drove it →
live iat_std was 8,000–15,000 vs training max 26 → root cause: the Welford
update used the **absolute epoch timestamp** where it needed the
**inter-arrival gap** (`iat_m2 += d * (ts - mean)` instead of
`dt - mean`) — three orders of magnitude of inflation from one wrong
variable. One-line fix, unit-verified against `statistics.pstdev`, seed
re-recorded, everything re-rehearsed. Lesson embodied in the repo: **never
trust a pipeline that hasn't seen a negative case** — the benign-quiet
check in the runbook's pre-flight exists because of this day.

## VIII.7 Verified end-to-end numbers (Aug 30, real packets)

| Scenario | Result |
|---|---|
| Benign, matched seed | worst peak **0.014** — all LOW |
| Benign, mismatched seed / unclamped | 0.65–0.69 ELEVATED (why pre-flight checks exist) |
| SYN scan (laptop attacker, real Wi-Fi) | **Recon rule on 3 consecutive windows**; model LOW |
| UDP sweep (laptop attacker, real Wi-Fi) | 0.03 → 0.03 → 0.17 → **0.905 HIGH** → 0.968 → 0.988; events on every HIGH window |
| UDP sweep (loopback self-attack fallback) | 0.022 → 0.384 → 0.947 at window 3, holds 0.98 |

---

# PART IX — Setup and running everything

## IX.1 One-time environment (demo laptop, Windows)

```bash
cd cyberforecaster
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# CPU-only torch (smaller): pip install torch --index-url https://download.pytorch.org/whl/cpu
# Npcap from https://npcap.com/ (default options) — required for live capture
```

Frontend: `cd web && npm install`.

Attacker laptop: Python 3.10+, `pip install scapy`, Npcap installed, and a
copy of `scripts/attacks/`.

## IX.2 Day-to-day running (artifacts are already built and committed)

```bash
# terminal 1 — API first (it loads the model)
python -m uvicorn api.main:app --port 8000 --log-level warning
# terminal 2 — web
cd web && npm run dev
# open http://localhost:3000  → header pill must show: live · thr 0.56
```

Offline console: pick a scenario → ANALYZE → FORECAST → WHY?.
Live demo: Live page → Start capture (Wi-Fi interface) → attacker runs the
acts (§VIII.4). Full choreography: `docs/DEMO_RUNBOOK.md`.

## IX.3 Full rebuild (only if data/model must change — ~needs the dataset)

```bash
python scripts/download_data.py --list      # see sizes BEFORE pulling
python scripts/download_data.py --yes       # curated pull, 2–3 GB
python scripts/rebuild_all.py               # windows → splits → models → cache
python scripts/verify_state.py              # MUST pass before demoing
python scripts/build_demo_cache.py          # refresh the cached fallback
```

## IX.4 Live rehearsal (any time, single laptop, no second device)

```bash
python scripts/record_seed.py --minutes 12 --iface "<wi-fi NPF name>"   # per network
python scripts/live_rehearsal.py --minutes 6 --attack udp-sweep --attack-at 0.3 \
    --iface "\\Device\\NPF_Loopback"
# exit code 0 = attack was flagged. If this script doesn't flag, demo day won't either.
```

## IX.5 Troubleshooting quick table

| Symptom | Fix |
|---|---|
| "capture thread died at startup" | Npcap missing → reinstall (default options), reboot |
| 0 packets captured | wrong interface — list `/api/live/interfaces`, use the Wi-Fi one |
| Benign forecast climbs above threshold | seed not recorded on this network → re-record (§IX.4); verify pre-flight in runbook §1 |
| `/api/health` mode ≠ REAL | read `model_error`; reboot API; CACHED is the honest fallback |
| Port 3000/8000 already in use | orphaned process: `netstat -ano \| findstr :3000` → `taskkill /PID <pid> /F` |
| Attacker "no route" / nothing arrives | targeting the public IP instead of the laptop's private `10.x`/`192.168.x` address, or devices on different networks |

---

# PART X — Role handbooks (who owns what, starting today)

### ML pair (model + features + evaluation)
- Own: `src/models/`, `src/features/scaling.py`, `src/evaluation/`,
  `src/explainability/`, `notebooks/`.
- Know cold: §II, §III, §VIII.5, §VIII.6. You are the ones who explain the
  threshold (validation, 5% FPR budget), the chronological split, and why
  recall is 14% on an unseen family and that's the honest number.
- Next: Gate 2 (Sep 2) freezes model/features — nothing new after that.

### Data Engineering
- Own: `src/ingestion/`, `src/preprocessing/`, `scripts/download_data.py`,
  dataset documentation.
- Know cold: §II (all of it). You are the one who explains the dataset
  quirks table and why we refuse random splits.

### Backend
- Own: `api/`, `scripts/check_api.py`, offline packaging, model loading,
  the honesty-mode plumbing.
- Know cold: §VI, §VIII.1, §VIII.3. Demo-day duty: API up first, health
  check REAL mode, live capture control.

### Frontend
- Own: `web/` (pages, components, chart theme), `DESIGN.md` fidelity.
- Know cold: §VII + the Live page data flow (§VIII.3): seed gray / live
  amber / threshold red, honesty pill always visible.

### Domain/Pitch
- Own: the 7-minute arc, ATT&CK mapping table (§V with ML-B), jury Q&A
  bank (battle plan §8 — all 15 answers, ≥3 members each).
- Know cold: §0, §I, §V, §VIII.7 numbers, and the runbook timing.

Everyone: read `docs/DEMO_RUNBOOK.md` before Sep 5; everyone can run §IX.2.

---

# PART XI — Where everything lives (file map)

```
SIH26153_battle_plan.md          strategy, calendar, gates, jury Q&A  ← start here
docs/DEMO_RUNBOOK.md             demo-day choreography + verified numbers
README.md                        quickstart + honesty rails
DESIGN.md                        UI design system
src/
  ingestion/csv_loader.py        messy CSV → clean flow table
  preprocessing/pipeline.py      flows → 30s windows → sequences → splits + scaler
  features/window_builder.py     THE 18 features; L=10/K=5; chronological split
  features/scaling.py            THE shared input transform
  models/baseline_logreg.py      logistic benchmark (per-horizon-step)
  models/lstm_forecaster.py      2-layer LSTM → 5 progression logits + stage head
  forecasting/rollout.py         Forecaster bundle: model + transform + threshold
  forecasting/scenarios.py       offline demo scenarios from real windows
  evaluation/lead_time.py        early-warning lead time (LSTM vs baseline)
  explainability/attribution.py  Integrated Gradients (+ permutation fallback)
  attack_mapping/mitre_mapper.py family→stage table + rule engine + validation
  live/sensor.py                 Npcap/scapy capture thread
  live/packet_windower.py        packets → the exact training feature vector
  live/history.py                seed+live history; model_matrix (input conditioning)
api/                             FastAPI (offline + /api/live/*)
web/                             Next.js console (/, /benchmarks, /live)
scripts/
  rebuild_all.py verify_state.py build_demo_cache.py check_api.py
  record_seed.py live_rehearsal.py
  attacks/  (syn_scan.py udp_sweep.py syn_flood.py + README)  → attacker laptop
data/processed/                  windows.parquet, sequences_*.npz, scaler.npz
data/live/seed_windows.json      benign seed for the live demo (network-specific!)
models/                          metrics_*.json + trained_models/lstm_forecaster.pt
```

---

# PART XII — Glossary

- **Window** — 30s of traffic summarized into 18 numbers.
- **Sequence (L=10 / K=5)** — 10 windows in, 5 windows forecast ahead.
- **y_prog** — per-horizon-step label (attack activity in that future window).
- **PR-AUC** — area under precision-recall; the right headline metric under
  ~24% class imbalance.
- **Operating point / threshold (0.5612)** — score cut chosen on validation
  for a 5% FPR budget.
- **Seed** — pre-recorded benign windows that warm up live history (gray in
  the chart, honestly labeled).
- **Honesty modes** — REAL / CACHED / SIMULATED; the app badges its own mode.
- **Input conditioning** — zeroing/clamping live features to the model's
  training domain before inference (rules still see raw values).
- **Persistence detector** — the model's true nature: recent attack activity
  is the strongest signal of imminent attack activity.
- **ATT&CK** — MITRE's taxonomy of adversary behavior; our five stages plus
  DoS.

*Document written Aug 30, 2026, after the full pipeline — offline and live —
was verified end-to-end. Numbers quoted here come from the artifacts in
`models/` and the rehearsal logs; if you change anything, re-run and update.*
