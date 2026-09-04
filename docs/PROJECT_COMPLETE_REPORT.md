# CyberForecaster — Complete Project Report (SIH26153)

**Problem:** SIH26153 — AI-based Network Attack Forecasting (NTRO, Smart India Hackathon 2026)
**Team deliverable:** a working temporal attack-forecasting + decision-support system
**Report date:** 2026-09-04 · **Internal demo:** Sat Sep 5, 2026
**Test suite at time of writing:** **143 tests, all passing** · TypeScript clean

> One-line pitch: **"Detection tells you what happened. We forecast what happens next — and we can prove why we said it."**

---

## Table of Contents

1. [The Problem and Why We Built This](#1-the-problem-and-why-we-built-this)
2. [Our Thesis](#2-our-thesis)
3. [What We Built — System at a Glance](#3-what-we-built--system-at-a-glance)
4. [Architecture](#4-architecture)
5. [The Data Story](#5-the-data-story)
6. [Model V1 — The Frozen Baseline](#6-model-v1--the-frozen-baseline)
7. [Uncertainty and Calibration](#7-uncertainty-and-calibration)
8. [The Two-Engine Design (Rules + LSTM)](#8-the-two-engine-design-rules--lstm)
9. [Explainability Without an LLM](#9-explainability-without-an-llm)
10. [Decision Support and Human-in-the-Loop](#10-decision-support-and-human-in-the-loop)
11. [The Live Pipeline](#11-the-live-pipeline)
12. [Upload / Analyze Pipeline](#12-upload--analyze-pipeline)
13. [The Multi-Dataset Architecture](#13-the-multi-dataset-architecture)
14. [Model V2 — World Model (Honest Negative Result)](#14-model-v2--world-model-honest-negative-result)
15. [All the Numbers (Honest)](#15-all-the-numbers-honest)
16. [Advantages](#16-advantages)
17. [Disadvantages and Limitations (Stated Openly)](#17-disadvantages-and-limitations-stated-openly)
18. [Security, Privacy and Ethics](#18-security-privacy-and-ethics)
19. [Testing and Reproducibility](#19-testing-and-reproducibility)
20. [Repository Map](#20-repository-map)
21. [The Verified Demo (Live, Real Packets)](#21-the-verified-demo-live-real-packets)
22. [The Build Journey — Phase by Phase](#22-the-build-journey--phase-by-phase)
23. [Roadmap](#23-roadmap)
24. [Suggested PPT Slide Outline](#24-suggested-ppt-slide-outline)
25. [Cheat Sheet — Numbers to Quote on Slides](#25-cheat-sheet--numbers-to-quote-on-slides)

---

## 1. The Problem and Why We Built This

Every SOC on the planet is drowning in **detection** tools. IDS/IPS products,
signature matchers, and anomaly detectors all answer the same backward-looking
question: *"did something bad just happen?"* By the time a traditional system
fires, the attack is already **inside**.

The actual pain in a Security Operations Center:

- **Reactive posture.** Analysts triage alerts about events that already
  completed. Mean time to detect is measured in hours or days; attackers need
  minutes.
- **Alert fatigue.** High-volume detection tools generate thousands of alerts a
  day; most are false positives; analysts start ignoring the noise.
- **No trajectory.** A detection says "SYN flood right now" — it does not say
  *"this pattern historically escalates; expect sustained DoS for the next
  several minutes; here is what to do before it peaks."*
- **Black-box ML.** Where ML is used, it is usually a classifier nobody can
  interrogate. When the CISO asks *"why did the model fire?"*, the honest answer
  is too often "we don't know."
- **No measured confidence.** A raw score of 0.87 means nothing if nobody knows
  whether the model's 0.87s are right 90% of the time or 40% of the time.

**What NTRO's problem statement asks for** is the missing half: use AI to
*forecast* attacks — look minutes ahead of the attack lifecycle, estimate risk
trajectories, and give the defender decision-ready context instead of
after-the-fact alerts.

That is exactly what we built: a system that watches the network as a **time
series**, forecasts the **attack fraction of the next five 30-second windows**,
assigns a **MITRE ATT&CK stage**, quantifies its **own uncertainty**, shows
**evidence-based reasons** for every prediction, and converts all of it into
**ranked, human-in-the-loop recommendations** — with zero fabricated numbers
anywhere in the chain.

### Why this is hard (say this on a slide)

1. Attacks are **rare** in real traffic — the class balance is brutal
   (our training data: mean attack fraction 0.12; 87% of windows benign).
2. Network data is **non-stationary** — Tuesday's benign looks nothing like
   Friday's attack, and a model trained with random splits silently memorizes
   the future.
3. Public datasets **lie about compatibility** — CIC, UNSW, CTU all call things
   "flows" and mean different things; blindly concatenating them produces a
   model trained on numbers that don't mean the same thing.
4. Forecasting needs **honest evaluation** — a "95% accurate" classifier on
   99%-benign data is a coin that always says "benign."

---

## 2. Our Thesis

We did not build a better detector. We built the thing that comes *after*
detection becomes useful — and before the attack completes:

```
telemetry  →  canonical state engine  →  temporal world model
   →  future-state trajectory + attack-risk forecast + ATT&CK stage
   →  evidence-based explanation  →  defender decision support (human-in-loop)
```

Three design commitments define the product:

1. **Forecast, don't just classify.** The output is a *trajectory* — five
   future 30-second windows — not a single alarm. The product value is the
   climb: LOW → 0.17 → 0.95, with the crossing visible before it happens.
2. **Every number is defensible.** No LLM in the explanation path, no invented
   metrics, no fake lead time. Missing data is displayed as *unavailable*,
   never as zero. Every displayed figure traces to an artifact on disk.
3. **The human decides.** The system recommends; it never blocks, drops, or
   reconfigures anything. There is no automated response anywhere in the
   codebase — by design, enforced by tests.

---

## 3. What We Built — System at a Glance

| Component | What it does | Where |
|---|---|---|
| **Temporal forecaster (V1)** | LSTM that forecasts attack fraction for the next 5×30s windows + dominant ATT&CK stage | `src/forecasting/rollout.py`, `models/trained_models/lstm_forecaster.pt` |
| **Rule engine** | Instant volumetric/recon/lateral/C2 detection on raw traffic (no ML) | `src/live/` |
| **Canonical schema** | 48-feature single model-input definition with per-feature availability | `src/features/canonical_schema.py` |
| **Sequence engine** | One windowing/supervision/scaling path for train, live and upload | `src/features/sequence_engine.py` |
| **Evidence engine** | Per-feature "why": observed vs benign baseline, z-score, direction, contribution | `src/explainability/evidence.py` |
| **Temporal WHY** | Window-by-window importance (W-9…W-0) showing *which history* drove the forecast | `src/explainability/temporal.py` |
| **Uncertainty** | Seeded MC-dropout (T=16) with HIGH/MEDIUM/LOW confidence bands | `src/explainability/uncertainty.py` |
| **Calibration** | Reliability curves, Brier, ECE per horizon step | `src/explainability/calibration.py` |
| **Decision support** | 4-level escalation ladder, P1–P3 ranked actions, ATT&CK enrichment from official MITRE STIX | `src/decision_support/` |
| **Live capture** | Npcap packet capture → 30s windows → forecast + rules + evidence + recommendations in real time | `src/live/`, `api/live_state.py` |
| **Upload/Analyze** | Drag-and-drop PCAP or flow CSV → auto-detection → full offline forecast story | `src/ingestion/upload_pipeline.py` |
| **Dataset registry** | Per-dataset adapters with honest READY/PENDING/NOT_DOWNLOADED status | `src/datasets/` |
| **MITRE knowledge base** | Official ATT&CK STIX bundle (53.8 MB) digested to a 160 KB index: 709 techniques, 15 tactics | `data/knowledge/mitre_attack/` |
| **FastAPI backend** | Port 8000, ~15 endpoints, REAL/CACHED/SIMULATED honesty modes | `api/` |
| **Next.js 15 frontend** | 5 pages: Forecast, Live, Analyze, Benchmarks, Datasets | `web/` |

---

## 4. Architecture

```
┌────────────────────────── SOURCES ──────────────────────────┐
│  Live packets (Npcap)   Uploaded PCAP/CSV   Offline datasets │
└──────┬──────────────────────┬──────────────────────┬────────┘
       │        ┌─────────────┴──────────────┐       │
       ▼        ▼                            ▼       ▼
  ┌───────────────────────────────────────────────────────┐
  │           ADAPTER LAYER (per-dataset, honest)          │
  │  CIC2018 ✔  UNSW-NB15 ✔  CTU-13 (landing)  CIC2017 …   │
  │  → canonical flow records → 48-feature WindowSlots      │
  │    (value, available, source) — unavailable ≠ zero      │
  └──────────────────────────┬────────────────────────────┘
                             ▼
  ┌───────────────────────────────────────────────────────┐
  │        SEQUENCE ENGINE (ONE road for everything)       │
  │  30s bins · gap-filled empty windows · L=10 → K=5      │
  │  masked CanonicalScaler · chronological split + purge   │
  └──────────┬───────────────────────────┬────────────────┘
             ▼                           ▼
  ┌─────────────────────┐      ┌─────────────────────────┐
  │  TEMPORAL MODEL     │      │  RULE ENGINE (no ML)    │
  │  LSTM 18→64×2       │      │  volumetric / recon /   │
  │  5-step forecast +  │      │  lateral / C2 rules     │
  │  ATT&CK stage       │      │  on RAW values          │
  └──────────┬──────────┘      └───────────┬─────────────┘
             └──────────────┬──────────────┘
                            ▼
  ┌───────────────────────────────────────────────────────┐
  │        EXPLAINABILITY STACK (deterministic)            │
  │  MC-dropout bands · evidence rows · temporal WHY ·     │
  │  calibration                                          │
  └──────────────────────────┬────────────────────────────┘
                             ▼
  ┌───────────────────────────────────────────────────────┐
  │        DECISION SUPPORT (human-in-the-loop)            │
  │  MONITOR→INVESTIGATE→CONTAINMENT REVIEW→ESCALATE       │
  │  P1–P3 actions · MITRE ATT&CK enrichment · evidence    │
  └──────────────────────────┬────────────────────────────┘
                             ▼
              FastAPI (8000)  ←→  Next.js UI (3000)
```

**Stack choices and why:**

- **FastAPI (Python)** — the ML ecosystem (pandas, NumPy, PyTorch, scapy)
  lives in Python; FastAPI gives async endpoints + automatic OpenAPI docs.
- **Next.js 15 + React + Recharts + Tailwind** — one codebase for 5 pages,
  fast dev loop, charts for trajectories.
- **PyTorch LSTM, not a Transformer** — the sequence is 10 steps of
  hand-engineered features; an LSTM is the right inductive bias and trains in
  minutes on a laptop. We deliberately did **not** add a GNN/Transformer/
  blockchain for marketing (plan rule 8).
- **SQLite-free, artifact-based state** — every number on screen traces to a
  JSON/parquet artifact on disk (`models/metrics_*.json`,
  `models/calibration_v1.json`, …). Reproducibility by construction.

---

## 5. The Data Story

### Training data (Model V1)

- **CSE-CIC-IDS2018** — the UNB/CIC "Processed Traffic Data for ML Algorithms"
  release: 7 daily flow-CSV captures (Wed 14 Feb – Thu 1 Mar 2018).
- Aggregated into **6,192 thirty-second windows** (L=10 lookback, K=5 horizon).
- **Mean attack fraction 0.121** — i.e. ~88% of windows are essentially benign;
  764 windows are mostly-attack (>0.5 attack fraction). This imbalance is the
  problem, not a bug in our pipeline.
- 18 hand-engineered flow features per window: volume (flow/byte/packet
  counts, durations, avg packet size), TCP behavior (SYN/ACK/FIN/RST/PSH
  ratios), address/port behavior (unique ports/IPs, port entropy),
  temporality (IAT mean/std), directionality (down/up ratio), service
  behavior (auth-port share).

### Methodology rules we enforced (and why they matter)

| Rule | Why |
|---|---|
| **Chronological split + boundary purge** | Random splits leak the future into training (overlapping windows!). Our test windows never precede training windows; day boundaries are forbidden zones. The test split (Feb 28 + Mar 1) is almost entirely *Infiltration* — a family absent from training — so the benchmark honestly measures **transfer to unseen attack families**, and we say so. |
| **No blind concatenation of datasets** | CIC "flow", UNSW "flow" and CTU "flow" are different measurements. A canonical schema with per-dataset capability masks governs what each can contribute. |
| **Unavailable ≠ zero** | CIC's ML CSVs have no IP columns; UNSW has no TCP flag counts. Those features are marked *unavailable* and masked, never silently zero-filled. |
| **Dataset quirks verified from real files** | e.g. CIC misspells "Infilteration" (a naive check silently drops 161k flows / all Lateral-Movement supervision); "Pkt Size Avg" not "Avg Pkt Size"; UNSW ships both "Backdoor" and "Backdoors" (534 rows). |

---

## 6. Model V1 — The Frozen Baseline

- **Architecture:** `TemporalForecaster` = LSTM(18 → 64, 2 layers) → linear
  head with 5 outputs (attack fraction forecast per horizon step) + stage head
  (ATT&CK stage distribution).
- **Operating threshold: 0.5612** — chosen on the *validation* PR curve, never
  on test.
- **Training:** masked log1p + standardization scaling; early stopping with
  **PATIENCE=25** (validation is only 428 sequences — per-epoch AP is noisy;
  with the typical patience of 8 the best checkpoint landed at epoch 4 and the
  model could not even fit training data. This was a real bug we found and
  fixed: train AP 0.545 → 0.95 after the fix).
- **Weights:** 234,073 bytes, sha256-16 `2b41bec7be520540` — pinned by golden
  regression tests together with the scaler, the benign baseline and the
  calibration artifact. A byte-level change anywhere fails the suite.
- **Frozen copy:** `models/baseline_cic2018_v1/` — byte-identical backup,
  test-enforced. The old model stays runnable forever; every future
  experiment answers "did more data actually help?" against this baseline.

### Headline metrics (held-out chronological test split)

| Metric | LSTM forecaster | Logistic baseline |
|---|---|---|
| Precision @ threshold | **0.882** | 0.500 |
| Recall @ threshold | 0.140 | 0.009 |
| F1 | 0.241 | 0.018 |
| False-positive rate | **0.006** | 0.003 |
| PR-AUC | **0.656** | 0.333 |

**How to read this honestly:** the model trades recall for precision on
purpose. At 0.561 it fires rarely, but when it crosses, it is right ~88% of
the time, with a false-positive rate of **0.6%**. The product is a
high-precision *early-warning* signal for sustained attacks, not a
per-window detector — the rule engine covers instant detection. The logistic
baseline (PR-AUC 0.333, near base rate) proves the temporal signal is real.

---

## 7. Uncertainty and Calibration

A single number is not enough; the system reports how much it trusts itself.

- **Seeded MC-dropout** (T=16, state-restoring, deterministic per seed):
  runs the forecast 16 times with dropout on and reports mean ± std.
  Confidence bands: **HIGH** (max σ < 0.05), **MEDIUM** (< 0.15), LOW.
  Deterministic seeding means the same input always produces the same band —
  demo-safe and test-pinned.
- **Calibration** (`models/calibration_v1.json`, computed on the frozen V1):
  pooled n = 4,580 windows, **Brier 0.1399**, **ECE 0.095**; per-step ECE
  0.077–0.112 — **no degradation across the 5-step horizon** (a forecasting
  model that gets *less* trustworthy further out would show rising ECE).
  The model is over-confident in low probability bins; we report that as-is
  on the Benchmarks page rather than hiding it.

---

## 8. The Two-Engine Design (Rules + LSTM)

We discovered — by experiment, not assumption — that one engine cannot cover
both instant detection and forecasting:

- **CIC's flow aggregates make flag features nearly dead offline** (median
  SYN/ACK counts ≈ 0 because CICFlowMeter aggregates long-lived flows), while
  live traffic has real flag ratios. A model trained on one distribution
  cannot instantly flag the other.
- **The LSTM is a persistence forecaster** (verified): a single attack window
  on benign history scores 0.006; the same window on attack-shaped history
  scores 0.987. That is *by design* — trajectory is the product.

So the production system runs two engines side by side:

| | Rule engine | LSTM forecaster |
|---|---|---|
| Latency | Instant (within one 30s window) | Crosses after ~3–4 sustained windows |
| Sees | RAW observed values | Domain-conditioned model input |
| Catches | SYN scans (Recon), volumetric floods, lateral movement, C2 beaconing | Escalation/progression of sustained attacks |
| Explainability | Rule name + thresholds | Evidence rows + temporal WHY + MC band |

**Verified live split (real Wi-Fi rehearsal):** a SYN port scan trips the
Recon rule on 3 consecutive windows while the model correctly stays LOW
(0.02–0.07); a sustained UDP sweep is ignored by instant rules but the
forecast climbs 0.03 → 0.03 → 0.17 → **0.905** → 0.968 → 0.988. The layering
is the design — say it out loud.

---

## 9. Explainability Without an LLM

No language model sits anywhere in the explanation path (plan rule 8). Every
sentence the UI shows is a deterministic template filled with real numbers:

- **Evidence rows** (per feature): observed value, benign baseline mean/p99
  (computed from the *training split only* — 3,308 benign windows,
  `models/benign_baseline.json`), z-score, direction (elevated/suppressed),
  contribution bar. If the baseline std is 0, the row explicitly makes **no
  claim** rather than inventing a z-score.
- **Raw vs conditioned honesty:** the evidence panel shows the **raw observed**
  window values (real IP counts, unclamped ratios) even though the model input
  is domain-conditioned (see §11) — a test proves an ack_ratio of 10.0 is
  displayed as "observed 10.0, elevated" while the model saw the clamped value.
- **Temporal WHY:** per-window importance W-9…W-0 — which parts of the history
  drove the forecast, plus trend arrows.
- **Calibration context:** the forecast number is always paired with its
  MC-dropout band.

Why not an LLM? Three reasons we can defend to judges: (1) determinism — the
same attack must produce the same explanation, every time; (2) auditability —
a SOC cannot act on "the AI said so"; (3) no hallucinated evidence — an LLM
can invent a plausible-sounding reason; a template filled with z-scores
cannot.

---

## 10. Decision Support and Human-in-the-Loop

The forecast becomes an *actionable record* (`src/decision_support/`):

- **Explicit escalation ladder:** MONITOR → INVESTIGATE → CONTAINMENT REVIEW →
  ESCALATE, decided from forecast vs threshold, crossing proximity,
  sustainment, and the MC confidence band (an unknown band is treated as
  MEDIUM — never optimistically HIGH).
- **Ranked recommendations P1/P2/P3**, each citing the actual evidence numbers
  ("dst_port_entropy z=8.2 above benign p99") — never generic advice.
- **ATT&CK enrichment** from the **official MITRE STIX bundle** (53.8 MB,
  downloaded and pre-digested into a 160 KB index — 709 techniques, 15
  tactics). A curated family→technique map (T1110 brute force, T1190 exploit
  public app, T1071 app-layer protocol, T1021 remote services, T1498 network
  DoS, T1005 local data collection — all verified present in the STIX) plus a
  stage→tactic fallback. Real mitigations and detection names from MITRE. If
  the knowledge base is missing, the panel says "knowledge base unavailable" —
  it does not guess.
- **Human-in-the-loop statement on every record** — and *nothing executes*.
  There is no code path that blocks, drops, drops a firewall rule, or
  reconfigures anything. The analyst decides; we advise. (This is also the
  correct ethical posture for a security tool, and a deliberate contrast to
  "autonomous response" marketing.)

---

## 11. The Live Pipeline

`/live` page → Npcap capture on the demo laptop's Wi-Fi interface →
`LiveWindowBuilder` accumulates real packets into 30-second windows →
each window flows through the SAME conditioning + model as training, plus the
rule engine on raw values → every poll returns forecast, MC band, events,
evidence rows, and a decision-support record.

**The domain-conditioning story (disclosed openly, never hidden):**
training CSVs carry no IP columns (constant zero) and long-lived aggregate
flows; live capture sees both. So every live window is conditioned to the
model's validated input domain before inference — IP-count features zeroed,
flag-ratio/down-up features clamped to the training p99. Without it, a quiet
network's benign traffic reads 0.69 (false alarm); with it, 0.014, and attacks
still cross 0.95+. **The rule engine and the evidence panel always see the
raw observed values.** This is input conditioning to the model's validated
domain, not result manipulation — and we present it as such.

Hard-won live engineering facts (all verified by experiment):

- A Welford-variance bug once inflated live iat_std to ~8,000–15,000 vs the
  training max 26.35 (absolute epoch timestamps instead of inter-arrival
  gaps), driving benign Wi-Fi to 0.98 HIGH. Found, fixed, and
  test-verified against `statistics.pstdev`.
- Seed history (18 benign windows of *this* network) is required — the model
  needs 10 windows of context and a matched network baseline (mismatched seed
  on a quiet network: benign 0.65+; matched: 0.014).
- Android/Termux cannot send scapy packets — the attacker laptop must have
  Npcap; the target must be the private Wi-Fi IP.

---

## 12. Upload / Analyze Pipeline

`/analyze` accepts a **PCAP/PCAPNG or a flow CSV** (100 MB cap):

- **Magic-byte detection** — never file extension (pcap/pcapng incl.
  nanosecond variants; CIC-style flow CSV vs generic flow CSV via a
  ~60-alias column mapper across CIC/UNSW/CTU/Zeek naming, with explicit user
  mapping overriding aliases; duration s→µs conversion).
- **Unknown schema → HTTP 400 "please map columns"** with a mapper report —
  the system never silently guesses a schema.
- PCAP path reuses the audited live extraction; CSV path reuses the audited
  windowing — the same model conditioning as live.
- Output: format card (style/confidence, matched/missing columns, honest
  unavailable-features note) → forecast-at-end hero + MC confidence →
  per-anchor trajectory chart with threshold refline → evidence panel →
  decision-support record.
- **Untrusted input is parsed, never executed**; temp files always cleaned;
  `torch.load` restricted to `weights_only=True`.

This gives the demo an offline fallback path: if live Wi-Fi fails on stage,
upload a capture and tell the same forecast story.

---

## 13. The Multi-Dataset Architecture

The long-term value proposition is **one canonical system, many datasets** —
and we built the hard part correctly instead of pretending:

- **Canonical schema** (`src/features/canonical_schema.py`): 48 features in
  7 groups (flow-volume, TCP behavior, temporal, address/port, packet-level,
  directionality, service). Every feature slot is a `(value, available,
  source)` triple. Schema version 2.0.0, content hash `a9570d8349141d92` —
  stored in every artifact; a model refuses input from a different schema.
  Model V1's 18 features are exactly the `v1=True` subset, in legacy order —
  byte-identical reproducibility guaranteed.
- **Capability matrix, verified per dataset:** a feature is marked available
  only when confirmed from the actual source files. No ✓ until proven.
- **Adapter contract** (`src/datasets/base.py`): discover → validate →
  load(canonical flow records) → to_window_slots(canonical WindowSlots +
  LabelRecords) → attack_metadata. Original labels are never discarded.
- **Registry with honest status:** READY / PENDING_WIRING / NOT_DOWNLOADED —
  pending adapters *raise loudly* instead of guessing.

**Dataset status today (2026-09-04):**

| Dataset | Status | Contribution |
|---|---|---|
| CSE-CIC-IDS2018 | ✅ READY (trained) | the frozen baseline |
| **UNSW-NB15** | ✅ READY (**wired today**) | 2.54M flows, 2015; real IPs; 9 attack families |
| CTU-13 | 🔄 1.9 GB downloading | 13 botnet scenarios, bidirectional NetFlow |
| CIC-IDS2017 | ⏳ awaits user registration download | 2017 attacks |
| CICIoT2023 / DARPA / LANL | optional later | IoT domain / external generalization / auxiliary auth modality |

**UNSW-NB15 adapter (wired 2026-09-04)** — the first new dataset through the
full contract:

- Verified from the real files before writing a line of mapping code:
  2,540,047 flows, headerless 49-column schema, `Label` ≡ `attack_cat` with
  **zero mismatches**, both "Backdoor"/"Backdoors" spellings present.
- **Capability (honest):** 12 of 18 legacy features **including
  unique_src/dst_ips** — the one legacy feature CIC2018 lacks — plus TTL,
  TCP window (TCP flows only), duration_std, src-port entropy, rates, and
  all service ratios. **Unavailable:** SYN/ACK/FIN/RST/PSH ratios (UNSW has
  no flag-count columns — synack/ackdat are setup *times*), iat_std (only
  directional interpacket means), retransmission (sloss/dloss is
  "retransmitted *or dropped*" ≠ retransmitted), payload sizes (smeanz/
  dmeansz are packet sizes, not payloads).
- **Taxonomy:** all 9 families mapped to canonical stages
  (`UNSW_FAMILY_CANONICAL`, source "manual/research" — label spellings
  verified, stage mapping from the dataset's own documentation).
  Notably: Shellcode → EXECUTION (the first real use of that stage), and
  **Generic → UNKNOWN_ATTACK** — an honest refusal to guess where the
  documentation doesn't support a stage claim.
- 21 tests including a smoke test on the real bytes; registry reports READY;
  the `/datasets` page shows it live.

---

## 14. Model V2 — World Model (Honest Negative Result) and Model V3 — Rollout World Model

We extended the forecaster with an explicit **ATT&CK state head**
(`src/models/world_model.py`, `WorldModelForecaster` — a subclass; V1's file
and artifacts untouched; V1 weights load and reproduce prog/stage
byte-identically, test-verified) and swept the multi-task loss weight
λ ∈ {0.1, 0.3, 0.5} with Huber loss on CIC2018:

| Variant | PR-AUC | Precision | State cosine |
|---|---|---|---|
| V1 baseline | **0.657** | 0.882 | — |
| V2 λ=0.5 (best) | 0.605 | 0.881 | 0.227 |
| V2 λ=0.1 / 0.3 | worse | — | state head near-dead |

**Result: the state head did NOT improve attack forecasting on CIC2018
alone.** We record this as a negative result, prominently, in the model card.

**V3 (added 2026-09-04) — the genuine state-transition architecture.** A fair
critique of V2: its states were a parallel regression task and the risk still
came straight from the encoder — not really "risk forecast from future
states." V3 (`src/models/rollout_world_model.py`) fixes the causality:

```
LSTM encoder → h → Ŝ(t+1) → Ŝ(t+2) → … → Ŝ(t+K)     (autoregressive rollout,
        residual transition g: Ŝ(k+1) = Ŝ(k) + g(Ŝ(k)))
each Ŝ(t+k) ──► risk_decoder ──► attack risk at t+k
            └─► stage_decoder ──► ATT&CK stage at t+k   (per-step, new)
```

Risk and stage are now decoded FROM the forecast network states — if the
state rollout is wrong, the risk forecast is wrong; they cannot diverge.
Results (same test split/protocol): **PR-AUC 0.633** (V1 0.657 — V3 improves
on V2 but does not beat the direct head on CIC2018 alone), state cosine
**0.257** (best of any variant), per-step stage decoders live in
`/api/forecast` as the additive `future_steps` field (T+1…T+5 stage + risk +
top moving state features, rendered as chips in the UI). The multi-dataset
experiments (Phases 7–8) will re-test both the state head and the rollout
with genuinely diverse data — that is the whole point of the strategy:
"did more data help?" answered with evidence, both when the answer is yes and
when it is no.

**Stage-transition lead time (new metric, 2026-09-04):** for every true
stage-transition onset (first labeled window of a new ATT&CK stage), we
measure how many horizon-steps earlier the model named that stage. Test
split: 1 warnable onset (Lateral Movement) — warned **5 windows (2.5 min)
early**; val split: 2/2 warned. Sample is too small for a headline claim;
recorded in `docs/EVALUATION.md` as a limited result.

---

## 15. All the Numbers (Honest)

**Offline, held-out chronological test split (frozen V1):**

| Metric | Value |
|---|---|
| Precision @ 0.5612 | 0.882 |
| Recall @ 0.5612 | 0.140 |
| F1 | 0.241 |
| False-positive rate | 0.006 |
| PR-AUC (LSTM) | 0.656 |
| PR-AUC (logistic baseline) | 0.333 |
| Calibration Brier / ECE (n=4,580) | 0.1399 / 0.095 |
| Per-step ECE range (5 horizons) | 0.077 – 0.112 (flat — no horizon decay) |

**Live, real captured traffic (Aug 30 rehearsals, post-fix):**

| Scenario | Verified numbers |
|---|---|
| Benign Wi-Fi (two-device setup) | worst peak **0.014** (all LOW) |
| Benign loopback | peak 0.008–0.010 LOW |
| SYN scan (attacker laptop) | **Recon rule hit within ONE 30s window** (3 consecutive: 97–219 flows, syn 0.96–1.03, 93–212 unique ports); model LOW 0.02–0.07 (by design) |
| UDP sweep (two-device, ~17k flows/1032 ports per window) | **0.03 → 0.03 → 0.17 → 0.905 HIGH → 0.968 → 0.988** — crossing at the 4th sustained window, events on every HIGH window |
| UDP sweep (loopback, ~50k probes/30s) | 0.022 → 0.384 → 0.947, sustains 0.977–0.989 |
| Live enrichment (98-window verification) | MC band HIGH (max σ 0.0274), 8 evidence rows, decision support MONITOR with real STIX mitigations (T1078/T1091/T1133/T1189) |

**The lead-time caveat (say it before a judge asks):** the offline test split
contains only **1 attack onset**, and the model did not cross threshold before
it (warned_rate 0.0). The test split is too onset-poor to estimate offline
lead time — we report that as a limitation in the model card and cite the
**live-rehearsal** numbers (crossing at the 4th sustained window) instead of
inventing an offline number. Why so poor? CIC-2018 attacks are scripted and
start abruptly from clean baselines; pre-onset warning on this data is close
to impossible (verified with `scripts/diagnose_leadtime.py` — the model
outputs flat ~0.52, the base rate, from clean inputs).

---

## 16. Advantages

1. **It forecasts, with a visible trajectory** — five future 30-second windows,
   not a binary alarm. The climb is the demo, and it is real.
2. **Extremely low false-positive rate on live benign traffic** (0.014 peak on
   real Wi-Fi after honest domain conditioning) — the alert-fatigue killer.
3. **Every prediction is defensible**: evidence rows with z-scores against a
   train-split-only benign baseline, temporal WHY, and a measured confidence
   band. No LLM, no hallucinated reasons, deterministic explanations.
4. **Calibrated and uncertainty-aware** — Brier/ECE reported per horizon step,
   MC-dropout bands; the system knows when it doesn't know.
5. **Human-in-the-loop decision support with real ATT&CK context** — ranked
   P1–P3 actions citing actual evidence numbers, enrichment from the official
   MITRE STIX bundle, an explicit escalation ladder, and zero automated
   response (ethically and operationally correct).
6. **Two-engine coverage** — instant rule-based detection (scans, floods,
   lateral movement, C2 beaconing) *and* ML forecasting of escalation; each
   covers the other's blind spot.
7. **Works on real networks, live** — packet capture → 30s windows → forecast
   in real time, with an offline scenario mode, an upload mode (PCAP/CSV
   auto-detection), and a cached fallback mode. Three honesty badges
   (REAL/CACHED/SIMULATED) mean the audience always knows what they are
   looking at.
8. **Genuinely multi-dataset architecture** — a canonical 48-feature schema
   with per-dataset capability masks, adapters that never fabricate
   unavailable features, honest per-dataset status. UNSW-NB15 wired end-to-end
   in one day once files landed; CTU-13/CIC-IDS2017 slot into the same
   contract.
9. **Reproducibility as a feature** — 143 passing tests, golden pins on every
   frozen artifact's sha256, byte-identical frozen baseline, config
   single-sourced, every displayed number traces to an on-disk artifact.
10. **Cheap to run** — trains in minutes on a laptop; no GPU, no cloud, no
    external API dependencies at inference (works fully offline).

---

## 17. Disadvantages and Limitations (Stated Openly)

We consider this section a feature. A team that can recite its own limits
credibly is more trustworthy than one that claims none.

1. **Low recall at the operating threshold (0.140).** The model deliberately
   misses most attack *moments* to keep precision at 0.88 and FPR at 0.006.
   It is an early-warning instrument for sustained attacks, not a per-window
   detector — the rule engine covers instant detection.
2. **Single-dataset training so far.** Until Phases 7–8 complete, V1 is
   trained only on CIC-IDS2018; performance on networks unlike that testbed
   is uncharacterized. The multi-dataset experiments are the answer, in
   progress.
3. **Offline lead time is not measurable on CIC-2018** (1 onset in the test
   split; scripted abrupt attacks). We cite live-rehearsal crossing behavior
   instead of inventing a number.
4. **Domain conditioning on live inputs.** Live windows are conditioned (IP
   features zeroed, ratios clamped to training p99) before inference —
   disclosed openly, with raw values still shown in evidence and rules. A
   purist would call this a train/serve skew; our answer is that it is an
   explicit, documented mapping of live inputs into the model's validated
   input domain — and the alternative is 0.69 false alarms on quiet networks.
5. **Feature availability is dataset-dependent.** CIC-2018 provides no IPs;
   UNSW provides no TCP flag ratios. The canonical schema masks these honestly,
   but it means no single model sees every feature — masked training and
   per-dataset capability sets are the price of honesty.
6. **30-second window granularity.** Sub-30s bursts are aggregated away;
   a very fast attack could complete inside one window. (Also our strength —
   it matches SOC triage rhythm.)
7. **The state head (V2) did not help on CIC2018 alone** — recorded as a
   negative result; verdict pending diverse data.
8. **Public-dataset realism gap.** CIC/UNSW/CTU are lab-generated or
   captured in controlled environments; no public dataset reproduces a real
   enterprise SOC's traffic mix. Cross-dataset evaluation (Phase 8) is our
   honest attempt to quantify this.
9. **No automated response** — by design. A buyer wanting "auto-block" will
   not find it here; we believe advisory + human authority is the correct
   design for a security tool, but it is a limitation of scope.
10. **LSTM persistence bias.** The model needs the attack to *persist* — a
    single-window spike does not cross. Fast-hit-and-run attacks are the rule
    engine's job, not the forecaster's.
11. **Binary per-window labels for V2 supervision** (dominant-label per bin)
    rather than a continuous attack fraction in the canonical path — a
    coarser signal than V1's regression target.

---

## 18. Security, Privacy and Ethics

- **No automated destructive response.** Nothing in the codebase blocks,
  drops, or reconfigures. Recommendations only; the analyst decides. A
  human-in-loop statement appears on every decision record (test-enforced).
- **Untrusted input is parsed, never executed:** magic-byte detection
  (extension never trusted), 100 MB upload cap, temp files always cleaned,
  `torch.load` restricted to `weights_only=True`.
- **Privacy:** the system profiles traffic, not people — no user identifiers
  are modeled. Live capture runs on the operator's own network with consent.
- **Honesty contract, end-to-end:** REAL/CACHED/SIMULATED badges;
  missing = unavailable, never zero; every displayed number traces to an
  artifact on disk; negative results are published (world-model V2, lead
  time).
- **Attacks only against our own laptop/network** — all rehearsal attacks
  (SYN scans, UDP sweeps) were run by us against our own machines on our own
  private Wi-Fi.
- **No LLM in the core explanation path** — deterministic templates over real
  model outputs; also means no data leaves the machine at inference time.

---

## 19. Testing and Reproducibility

- **143 pytest tests, all passing (~40 s)** across: dataset adapters (CIC2018,
  UNSW-NB15 incl. real-file smoke), canonical schema, sequence engine, packet
  features, world model, explainability, decision support, upload pipeline,
  live enrichment, and golden regression.
- **Golden regression suite** (`tests/test_golden_regression.py`):
  - sha256-16 pins on every frozen artifact (live model, scaler, benign
    baseline, calibration, and the frozen baseline copies). A changed hash
    fails with the instruction *"update the pin on purpose and record why —
    never delete it."*
  - Exact `Forecaster.predict` outputs (probs to 4 decimals) on 4 fixed
    inputs: 2 synthetic + 2 deterministically-selected real slices of the
    frozen windows (including the true attack onset at rows 105–114, with a
    guard test asserting the onset structure).
  - Seeded MC-dropout golden (T=16, seed=0, pinned mean/std/confidence).
  - API contracts via TestClient (health shape, forecast determinism,
    datasets-registry honesty).
- **Frozen baseline** `models/baseline_cic2018_v1/` — byte-identical,
  test-enforced; the answer to "did more data help?" is always computable.
- **Single-sourced config** (`src/config.py`): BIN_SECS=30, L=10, K=5.
- **Model card** (`MODEL_CARD.md`) + **acceptance checklist**
  (`docs/ACCEPTANCE_CHECKLIST.md`) mapping every criterion to evidence.

---

## 20. Repository Map

```
cyberforecaster/
├── api/                    FastAPI backend (main.py, live_state.py, port 8000)
├── web/                    Next.js 15 frontend (5 pages + panels, port 3000)
├── src/
│   ├── config.py           BIN_SECS / SEQ_LEN / HORIZON — single source
│   ├── features/           canonical_schema, window_builder (V1),
│   │                       sequence_engine (V2 road), packet_features
│   ├── datasets/           base contract, registry, cic2018, unsw_nb15
│   ├── labels/             attack_taxonomy (canonical stages, per-dataset maps)
│   ├── ingestion/          csv_loader (audited), upload_pipeline
│   ├── models/             world_model.py (V2 state head)
│   ├── forecasting/        rollout.py (Forecaster: load/predict/scaled)
│   ├── explainability/     evidence, temporal, uncertainty, calibration
│   ├── decision_support/   levels, mitre, recommendations, engine
│   ├── live/               packet capture, windowing, rules, history
│   ├── preprocessing/      pipeline (V1 audited path)
│   └── evaluation/         lead_time
├── models/                 trained_models/, frozen baseline, metrics JSONs,
│                           calibration_v1.json, benign_baseline.json, world_model_v2/
├── data/                   raw datasets (per-dataset dirs), processed windows,
│                           knowledge/mitre_attack/
├── configs/                dataset_manifest.yaml, datasets/*.yaml
├── scripts/                record_seed, live_rehearsal, attacks/, start_demo.bat …
├── tests/                  143 tests incl. test_golden_regression.py
├── MODEL_CARD.md           honest model documentation
├── DATA_CONTRACT.md        the data honesty contract
├── MASTER_IMPLEMENTATION_PLAN.md   phase board (single source of truth)
└── docs/                   DEMO_RUNBOOK, ACCEPTANCE_CHECKLIST, AUDIT, this report
```

---

## 21. The Verified Demo (Live, Real Packets)

The 7-minute arc (rehearsed end-to-end on the demo laptop, Aug 30; every
number below was measured, not estimated):

| Time | Beat | What happens |
|---|---|---|
| 0:00 | Hook | "Detection tells you what happened. We forecast what happens next." |
| 0:30 | Thesis | classification vs evolution; telemetry → states → forecast (+why) |
| 1:00 | Offline rigor | Scenario → forecast climb, WHY attribution, ATT&CK strip, benchmarks ("chronological split, no leakage") |
| 2:00 | LIVE | start capture on Wi-Fi; narrate the gray seed segment (real benign history of THIS network, nothing fabricated) |
| 2:45 | Act 1 — Recon | attacker laptop runs `syn_scan.py` → rule engine flags Reconnaissance within ONE window (model correctly LOW) |
| 3:45 | Act 2 — The forecast moment | `udp_sweep.py` → 0.03 → 0.17 → **0.95 HIGH, red hero, banner**; sustains ≈0.98 |
| 5:45 | Why it fired | Evidence panel + decision support; the two-engine story |
| 6:15 | Honesty close | "Trained on CSE-CIC-IDS2018, verified live in rehearsal, never faked a detection." |

Fallback chain (each rehearsed): two-device live → loopback self-attack →
offline scenarios (cached mode) → `/analyze` upload → recorded video.

---

## 22. The Build Journey — Phase by Phase

The full board lives in `MASTER_IMPLEMENTATION_PLAN.md`; the short version:

| Phase | What | Outcome |
|---|---|---|
| 0 | Repository audit before touching anything | `docs/AUDIT_BEFORE_MULTIDATASET.md` — every quirk documented (misspelled labels, dead flag columns, stale 60s defaults) |
| 1 | Baseline freeze | byte-identical copy in `models/baseline_cic2018_v1/`; old model verified still running |
| 2 | Canonical feature schema | 48 features, 7 groups, availability triples, hash-pinned; 8 tests |
| 3 | Dataset adapter layer | contract + registry + manifest; CIC2018 adapter; **UNSW-NB15 wired** (21 tests); CTU-13/CIC2017 landing |
| 4 | Packet feature extraction | live packet → 18 features + Group-E extras; pcap round-trip byte-identical vs bare builder |
| 5 | Unified windowing/scaling | ONE canonical engine (gap-filled empty windows, masked scaler, chrono split + purge) for train/live/upload |
| 6 | World-model state head | V2 built and swept — honest negative result on CIC2018 (see §14) |
| 7–8 | Multi-dataset training / cross-dataset eval | unblocked as datasets land (UNSW first) |
| 9 | Explainability | evidence + temporal WHY + MC-dropout + calibration; no LLM |
| 10 | Decision support | 4-level ladder, P1–P3 actions, MITRE STIX enrichment, human-in-loop; nothing executes |
| 11 | Upload pipeline | magic-byte auto-detection, column mapper, 400 on unknown schema; parse-never-execute |
| 12 | UI integration | /analyze + /datasets pages, Evidence + DecisionSupport panels, nav, tsc clean |
| 13 | Live pipeline alignment | live feed returns the full Phase 9/10 stack additively; degrades to legacy+nulls if engines missing |
| 14 | Golden regression | 12 tests pinning hashes and exact outputs; 100 green at the time |
| 15 | Demo hardening | MODEL_CARD, ACCEPTANCE_CHECKLIST, runbook §8; **143 green** today |

Notable engineering battles won along the way (good "how we built it" slide
material): the LSTM patience bug (epoch-4 checkpoint, train AP 0.545 → 0.95
after PATIENCE=25); the Welford iat_std variance bug that made benign Wi-Fi
read 0.98 HIGH; the CIC flag-column deadness that forced the two-engine
design; the live domain-conditioning discovery (0.69 → 0.014); the UNSW
SharePoint cookie wall (manual download, byte-exact verification).

---

## 23. Roadmap

**In flight (data landing):**
- CTU-13 (1.9 GB, ~75% downloaded) → adapter per the same contract.
- CIC-IDS2017 (user registration download) → adapter.
- Phase 7 experiments: A (CIC2018 rerun under V2 pipeline, comparability),
  B (+CIC2017), C (**+UNSW-NB15 — first real multi-dataset training**),
  D (+CTU-13), E (+CICIoT2023), F (DARPA external/generalization only).

**Then (Phase 8):** three-regime evaluation — in-domain (same dataset, later
time), cross-dataset (train on N, test on held-out dataset), leave-one-
dataset-out — with published per-regime reports. Re-test the V2 state head
with diverse data.

**Beyond:** LANL auth-events as an auxiliary host-behavior modality (never
forced into the flow vector); masked-training V2 as the production model if
it beats V1 with evidence; streaming deployment packaging.

---

## 24. Suggested PPT Slide Outline

A 12–15 slide deck maps naturally onto this report:

1. **Title + one-liner** — "Detection tells you what happened. We forecast
   what happens next." (§1–2)
2. **The problem** — reactive SOC, alert fatigue, black-box ML, no
   trajectory; why forecasting is hard (4 bullets, §1)
3. **Our thesis** — telemetry → states → forecast → why → decision support;
   3 design commitments (§2)
4. **System architecture** — the diagram in §4 (simplify to 4 layers)
5. **How the model works** — 30s windows, L=10→K=5, 18 features, LSTM,
   ATT&CK stage, threshold from validation (§6)
6. **Data rigor** — chronological split + boundary purge, no blind
   concatenation, unavailable ≠ zero; the misspelled-label story as a
   credibility anecdote (§5)
7. **Results — offline** — the metrics table (§6/§15); explain precision/
   recall trade honestly (high-precision early warning, not a detector)
8. **Results — live, real packets** — the 0.03 → 0.17 → 0.905 climb; benign
   0.014; SYN scan rule hit within one window (§15/§21) — this is the
   money slide
9. **Two-engine design** — rules catch the scan instantly, the LSTM forecasts
   the escalation (§8)
10. **Explainability** — evidence rows, temporal WHY, MC-dropout bands,
    calibration; "no LLM, no hallucinated reasons" (§7, §9)
11. **Decision support** — escalation ladder, P1–P3, ATT&CK from official
    STIX, human-in-the-loop, nothing executes (§10)
12. **Multi-dataset architecture** — canonical 48-feature schema, capability
    masks, adapters, UNSW wired + 4 more landing (§13)
13. **Honest limitations** — 4–5 bullets from §17 (judges reward this)
14. **Live demo** (then run the §21 arc)
15. **Roadmap + close** (§23)

---

## 25. Cheat Sheet — Numbers to Quote on Slides

| Claim | Number |
|---|---|
| Windows of training context → forecast | 10 × 30s → next 5 × 30s |
| Operating threshold (validation-chosen) | 0.5612 |
| Precision @ threshold | 88.2% |
| False-positive rate | 0.6% |
| PR-AUC vs logistic baseline | 0.656 vs 0.333 (≈2×) |
| Calibration | Brier 0.140, ECE 0.095, no horizon decay |
| Live benign (real Wi-Fi) | peak 0.014 — no false alarms |
| Live UDP sweep | 0.03 → 0.17 → 0.905 → 0.968 → 0.988 |
| SYN scan detection latency | within ONE 30s window (rule engine) |
| Training windows | 6,192 (CIC-2018, 7 days) |
| Datasets in the canonical system | 7 planned, 2 READY (CIC2018 + UNSW-NB15 2.54M flows), CTU-13/CIC2017 landing |
| MITRE ATT&CK coverage | 709 techniques, 15 tactics from the official STIX bundle |
| Genuine state-transition model (V3) | autoregressive S(t+1..K) rollout, risk+stage decoded from future states; PR-AUC 0.633 (V1 stays 0.657 — honest) |
| Stage-transition lead time | 2.5 min (5 windows) on available onsets — sample too small for a headline |
| Tests | 143 passing, golden-pinned artifacts |
| LLMs in the explanation path | 0 |

---

*Every number in this report traces to an artifact on disk (models/metrics_*.json,
models/calibration_v1.json, docs/DEMO_RUNBOOK.md verified-numbers section,
tests/test_golden_regression.py). Nothing here is estimated, rounded-up, or
aspirational — that is the product's defining constraint and its pitch.*
