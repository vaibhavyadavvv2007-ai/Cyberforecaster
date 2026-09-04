# CYBERFORECASTER — THE COMPLETE PROTOTYPE DOCUMENT

**Smart India Hackathon 2026 · Problem SIH26153 · AI-based Network Attack Forecasting System**

*This is the one document that explains the entire prototype: what we built, how we
built it, why we built it that way, every component, every number, every decision,
every mistake we found and fixed, and every honest limitation. If you read only one
file about this project, read this one. Every number in this document traces to an
artifact on disk (the numbers authority is `docs/EVALUATION.md`; the model authority
is `MODEL_CARD.md`).*

Version: final build, 2026-09-04 · 163 tests green · V1 model frozen and
golden-pinned · three datasets wired (CIC-IDS2018, UNSW-NB15, CTU-13).

---

## Table of contents

1. [The problem we chose](#1-the-problem-we-chose)
2. [The core thesis: forecasting, not detection](#2-the-core-thesis-forecasting-not-detection)
3. [System architecture — the full picture](#3-system-architecture--the-full-picture)
4. [The data layer](#4-the-data-layer)
5. [The canonical feature schema — 48 features, 7 groups](#5-the-canonical-feature-schema)
6. [Feature engineering pipeline](#6-feature-engineering-pipeline)
7. [The models: V1, V2, V3](#7-the-models-v1-v2-v3)
8. [Multi-dataset training & cross-dataset evaluation](#8-multi-dataset-training--cross-dataset-evaluation)
9. [The rule engine — deterministic, no ML](#9-the-rule-engine--deterministic-no-ml)
10. [The explainability stack](#10-the-explainability-stack)
11. [The decision-support engine](#11-the-decision-support-engine)
12. [MITRE ATT&CK integration](#12-mitre-attck-integration)
13. [The live capture pipeline](#13-the-live-capture-pipeline)
14. [The upload pipeline](#14-the-upload-pipeline)
15. [API reference](#15-api-reference)
16. [The web UI](#16-the-web-ui)
17. [Evaluation — every number, honestly](#17-evaluation--every-number-honestly)
18. [The honesty system](#18-the-honesty-system)
19. [Security & ethics posture](#19-security--ethics-posture)
20. [Engineering war stories — bugs we found and fixed](#20-engineering-war-stories)
21. [Testing & reproducibility](#21-testing--reproducibility)
22. [Advantages — what makes this strong](#22-advantages)
23. [Disadvantages & limitations — stated plainly](#23-disadvantages--limitations)
24. [Repository map](#24-repository-map)
25. [The demo](#25-the-demo)
26. [The journey — phase by phase](#26-the-journey--phase-by-phase)
27. [Future roadmap](#27-future-roadmap)
28. [Numbers cheat sheet](#28-numbers-cheat-sheet)

---

## 1. The problem we chose

**SIH26153 — AI-based Network Attack Forecasting System (NTRO).** The problem
statement, in essence: cyber attacks are not instantaneous events — they unfold in
stages (reconnaissance → initial access → lateral movement → command & control →
exfiltration). Today's defenses detect attacks *while they are happening*. The
ask is a system that **forecasts** attacks — that raises an alarm *before* the
damage stage, estimates what stage the attack is in, and tells the analyst what to
do — while keeping a human in the loop.

This is one of the hardest formulations in defensive security, because it demands
three things at once:

1. **Temporal prediction** — not "is this window malicious?" but "will the network
   be under attack 30 seconds to 2.5 minutes from now, with what probability?"
2. **Attack-stage awareness** — a forecast that says *which* ATT&CK stage the
   attack is heading toward, because the response to a scan and the response to
   exfiltration are completely different.
3. **Operational trust** — a SOC analyst will only act on a forecast they can
   interrogate: why did the model say this, how confident is it, what evidence is
   there, and what happens if it is wrong. A black box that says "72% attack" is
   not a decision-support system.

Everything in this prototype exists to serve those three demands.

---

## 2. The core thesis: forecasting, not detection

**Detection** answers: "given this window of traffic, is it an attack?" — a
classification problem on the *present*.

**Forecasting** answers: "given the last ten windows of traffic, what fraction of
the next five windows will be attack traffic, what stage will the attack be in,
and how confident am I?" — a regression + staging problem on the *future*.

We deliberately built a forecaster, and that choice shaped every design decision:

- **Input is a sequence, not a window.** The model sees 10 consecutive 30-second
  windows (5 minutes of history) — trends, bursts, and build-ups, not a snapshot.
- **Output is a horizon, not a verdict.** One forward pass emits 5 probabilities
  (T+1 … T+5, the next 2.5 minutes) plus a stage prediction. A trajectory that
  *rises* across the horizon is a warning; a flat number is not.
- **Precision over recall, by design.** A forecast that cries wolf is worthless —
  the operator stops believing it. We tuned the operating threshold for an
  extremely low false-positive rate (0.006 on held-out data) and report the low
  recall honestly: the system aims to be *right when it warns*, not to catch
  every attack moment.
- **The forecast is one input to a human decision.** The system never acts on its
  own. It produces evidence, uncertainty bands, ATT&CK context, and ranked
  recommendations — and a human decides. This is both an ethical stance and a
  requirement of the problem statement.

---

## 3. System architecture — the full picture

```
┌─────────────────────────── SOURCES ───────────────────────────┐
│  Live packets (Npcap)    Uploaded PCAP/CSV    Offline datasets │
└──────┬───────────────────────┬───────────────────────┬────────┘
       ▼                       ▼                       ▼
  ┌──────────────────────────────────────────────────────────┐
  │            ADAPTER LAYER (per-dataset, honest)            │
  │  CIC2018 READY · UNSW-NB15 READY · CTU-13 READY           │
  │  → canonical flow records → 48-feature WindowSlots         │
  │    (value, available, source) — unavailable ≠ zero        │
  └──────────────────────────────┬───────────────────────────┘
                                 ▼
  ┌──────────────────────────────────────────────────────────┐
  │         SEQUENCE ENGINE (ONE road for everything)         │
  │  30s bins · gap-filled empty windows · L=10 → K=5         │
  │  masked CanonicalScaler · chronological split + purge     │
  └──────────┬───────────────────────────────┬───────────────┘
             ▼                               ▼
  ┌──────────────────────┐        ┌──────────────────────────┐
  │   TEMPORAL MODELS    │        │  RULE ENGINE (no ML)     │
  │  V1 LSTM (deployed)  │        │  volumetric / recon /    │
  │  V2 state head       │        │  auth / C2 / lateral /   │
  │  V3 ROLLOUT WORLD    │        │  exfil rules on RAW      │
  │  MODEL (risk from    │        │  values, with explicit   │
  │  forecast states)    │        │  ABSTENTION             │
  └──────────┬───────────┘        └────────────┬─────────────┘
             └───────────────┬─────────────────┘
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │        EXPLAINABILITY STACK (deterministic, no LLM)       │
  │  MC-dropout bands · evidence rows · temporal WHY ·        │
  │  calibration (Brier / ECE)                                │
  └──────────────────────────────┬───────────────────────────┘
                                 ▼
  ┌──────────────────────────────────────────────────────────┐
  │         DECISION SUPPORT (human-in-the-loop)              │
  │  MONITOR → INVESTIGATE → CONTAINMENT REVIEW → ESCALATE    │
  │  P1–P3 ranked actions · MITRE ATT&CK STIX enrichment      │
  │  NOTHING EXECUTES — recommendations only                  │
  └──────────────────────────────┬───────────────────────────┘
                                 ▼
                  FastAPI (port 8000) ←→ Next.js UI (port 3000)
```

**The single most important architectural property:** there is ONE sequence
engine and ONE canonical feature space for training data, live capture, and
file upload alike. The model you train is the model you serve — the same
windowing, the same scaler, the same feature semantics. Three different data
paths that all converge on one contract (`DATA_CONTRACT.md`), so live traffic
and uploaded captures are processed *exactly* like training data was.

**The second most important property:** honesty is enforced structurally. Every
feature slot carries `(value, available, source)`. A feature a data source
cannot provide is *unavailable* — never silently zero. Every API response
carries a mode badge (REAL / CACHED / SIMULATED). Missing artifacts degrade to
`null`, never to invented numbers.

---

## 4. The data layer

### 4.1 The data contract (non-negotiables)

Written down in `DATA_CONTRACT.md` before any data was touched:

- An adapter **never** defines its own model input; it emits canonical
  `WindowSlots` whose availability comes from the canonical schema.
- An adapter **never** discards original labels; it emits `LabelRecord`s
  carrying the verbatim dataset label alongside the canonical mapping.
- An adapter **refuses** to run on files it has not validated (schema check
  with a confidence score, before any training).
- Raw dataset files are **read-only**; processing outputs go elsewhere.
- Taxonomy mappings are defined **only after** reading real label values from
  real files — never guessed from documentation. Unmappable attacks stay
  `UNKNOWN_ATTACK` (we refuse to pretend).

### 4.2 CSE-CIC-IDS2018 — the primary training dataset

- 7 daily flow-CSV captures (Wed 14 Feb – Thu 1 Mar 2018), CICFlowMeter format.
- Aggregated into **6,192 30-second windows**; 764 windows with attack
  fraction > 0.5; mean attack fraction 0.121.
- Attacks: FTP/SSH/Web brute force, XSS, SQL injection, DoS (GoldenEye, Hulk,
  Slowhttptest, Slowloris), DDoS (LOIC, HOIC), Botnet-Ares, Infiltration,
  Heartbleed — 15 families mapped to the 6-stage taxonomy (table in §9).
- **Known quirks we discovered and documented (not hidden):**
  - The ML-ready CSVs ship **no Src IP / Dst IP columns** — the IP-derived
    features are constant 0 in training. This drove the live-input
    conditioning design (§6.5) and the rule-engine abstention logic (§9).
  - Aggregate flow rows carry long-lived flow durations that would poison
    per-window duration statistics if summed naively.
  - Attacks start abruptly from clean baselines — the test split contains only
    **1 attack onset**, which makes offline onset-lead-time unmeasurable on
    this data (we say so, and cite live-rehearsal numbers instead).
- Split: chronological 70/15/10 train/val/test with day-boundary purge —
  no random splits, no leakage, ever.

### 4.3 UNSW-NB15 — second dataset, fully wired

- 2,540,047 flows in four headerless 49-column CSVs (schema verified against
  the official `NUSW-NB15_features.csv`; label column cross-checked: `Label`
  ≡ `attack_cat` with 0 mismatches).
- 9 attack categories + normal (Reconnaissance, Analysis, Fuzzers, Backdoor,
  Exploits, Shellcode, Worms, DoS, Generic), 2015-01-22 → 2015-02-18.
- **What it provides that CIC2018 cannot:** real IP columns (so
  `unique_src_ips` / `unique_dst_ips` are genuinely available), TTL means/stds,
  TCP window sizes, duration std, port entropies, flow/packet rates, and all
  port-based service ratios.
- **What it honestly cannot provide:** TCP flag counts (no SYN/ACK/FIN/RST/PSH
  packet columns — `synack`/`ackdat` are setup *times*, not counts, a trap we
  explicitly refused to fall into) and per-flow IAT std (Sintpkt/Dintpkt are
  means). Those features are *unavailable* from this source, never zero-filled.
- Even the spelling variant "Backdoors" (534 rows) vs "Backdoor" was read from
  the real files and handled.

### 4.4 CTU-13 — third dataset, fully wired

- The CTU-13 dataset from the Stratosphere IPS lab: **13 botnet scenarios**
  captured on a real university network in 2011, each a different botnet
  family, shipped as bidirectional NetFlow (`.binetflow`) with **real IP
  addresses** — a completely different capture modality from CIC2018's
  per-host flow CSVs.
- Why we wanted it: it is the *stage-rich* dataset — long-running botnet
  sessions where the same infection progresses through C2, lateral movement,
  and exfiltration over hours, which is exactly the temporal structure a
  forecasting world model should learn from, and exactly what CIC2018 lacks.
- Label semantics: flows are labeled `From-Botnet` / `To-Botnet` /
  `From-Normal-V32-V42` / `To-Normal-*` / `Success` / `Failed` per direction.
  The adapter derives per-flow attack labels from the verbatim `Label` field
  and maps scenario botnet families (Neris, Rbot, Virut, Menti, Sogou, Murlo)
  onto the canonical taxonomy with the direction-awareness the dataset
  documents.
- What the NetFlow modality provides: real IPs, ports, protocol, direction
  (`<->` / ` ->` / ` <-`), TCP state strings (which encode SYN/ACK/FIN/RST
  handshake state per flow), durations, packets, and bytes both ways. What it
  cannot provide: per-packet IAT statistics beyond flow duration, TCP flag
  *counts*, packet-level TTL/window/payload features — honestly unavailable.

### 4.5 Datasets we support but did not obtain — and say so

CIC-IDS2017, CICIoT2023, DARPA 1998-2000, LANL auth events are registered as
**PendingAdapter** stubs: they carry metadata (URL, expected modality) and
refuse to discover/load. The `/datasets` page shows them as NOT_DOWNLOADED
(or PENDING_WIRING if files appear). We never removed a stub to "unblock"
training — that is the point of the stop-point rule.

### 4.6 The adapter registry

`src/datasets/registry.py` — one place to ask "what can we train on today?"
`get_adapter(dataset_id)` returns a live adapter; `status()` reports READY /
PENDING_WIRING / NOT_DOWNLOADED per dataset, consumed verbatim by the UI.
Adapters for un-downloaded datasets register as stubs that raise
`DatasetNotAvailableError` on any data access — loud, not silent.

---

## 5. The canonical feature schema

`src/features/canonical_schema.py` — 48 features in 7 groups, schema hash
`a9570d8349141d92` (persisted in every artifact; mismatches are refused).
Each feature is a `FeatureSpec(name, group, description, v1, log_transform)`.
The `v1` flag marks membership in the legacy 18-feature model input.

| Group | Theme | Features |
|---|---|---|
| **A — flow volume** | how much traffic | flow_count, bytes_total, pkts_total, duration_mean, duration_std, avg_pkt_size |
| **B — TCP behavior** | transport-layer behavior | syn_ratio, ack_ratio, fin_ratio, rst_ratio, psh_ratio, urg_ratio, tcp_window_mean/std, retransmission_rate |
| **C — temporal** | timing patterns | iat_mean, iat_std, iat_max, burstiness, flow_rate, packet_rate |
| **D — address/port** | who talks to whom | unique_dst_ports, unique_dst_ips, unique_src_ips, src_port_entropy, dst_port_entropy, port_scan_sequentiality, port_scan_randomness |
| **E — packet-level** | needs packet capture | ttl_mean/std, payload_size_mean/std/p50/p95, fragment_flag_rate, fragment_count |
| **F — directionality** | inbound vs outbound | down_up_ratio, inbound_bytes, outbound_bytes, inbound_packets, outbound_packets |
| **G — service** | what applications | auth_port_share, http_ratio, dns_ratio, ssh_ratio, rdp_ratio, smb_ratio, ftp_ratio |

The critical design: `DATASET_CAPABILITIES` records what each source
**verifiably** provides, and a per-dataset availability mask flows through the
entire system (windowing → scaling → model input → UI "unavailable features"
notes). CIC2018 provides 18 of 18 legacy features; UNSW provides 12 of 18
(including the two IP features CIC2018 lacks); CTU-13 provides the IP/port
group and flow volume but not packet internals; live capture provides the
packet-level group that no flow CSV can. The masked scaler (§6.4) makes
training on the *intersection or union* well-defined without ever imputing
zeros for "the source couldn't measure this."

---

## 6. Feature engineering pipeline

### 6.1 From flows to windows

All traffic — dataset CSVs, uploaded files, live packets — becomes **canonical
flow records** (timestamp, IPs, ports, protocol, direction, duration, packets,
bytes, flag counts where available, verbatim label) and is then aggregated
into **30-second windows** (`BIN_SECS=30`, single-sourced in `src/config.py`).
Window aggregation computes the group A–G features over each bin's flows.

### 6.2 The 18 V1 model features (the deployed model's input)

```
flow_count, bytes_total, pkts_total, duration_mean,
syn_ratio, ack_ratio, fin_ratio, rst_ratio, psh_ratio,
unique_dst_ports, auth_port_share, unique_dst_ips, unique_src_ips,
dst_port_entropy, iat_mean, iat_std, avg_pkt_size, down_up_ratio
```

Heavy-tailed non-negative features are log1p-transformed (matches the
`LOG_FEATURES` scaling contract). Entropies are Shannon over port counts.

### 6.3 Packet-level features (Group E)

`src/features/packet_features.py` extends the live window builder with a
`PacketWindowAccumulator`: TTL mean/std, payload-size moments and percentiles,
fragment flags/counts, retransmission inference — the features only a real
packet tap can provide. A pcap round-trip test proves the 18 flow features are
**byte-identical** whether computed via the packet path or the bare builder —
the two roads cannot drift.

### 6.4 The sequence engine — one road for everything

`src/features/sequence_engine.py`:

- **Gap filling:** missing 30-second bins become explicit *empty* windows
  (silence is information — an attack pause and a capture gap are different
  things and the model can see both).
- **Masked CanonicalScaler:** per-feature statistics computed with NaN-masking;
  a feature that is unavailable in a dataset contributes to neither mean nor
  variance (a test proves an all-NaN feature is a no-op, not poison). A
  schema-hash guard refuses to apply a scaler built against a different schema.
- **Chronological split with purge:** 70/15/10 train/val/test *in time*, with
  day-boundary purge so no sequence straddles a split. Random splits are
  structurally impossible.

### 6.5 Live-input domain conditioning — disclosed, not hidden

Training CSVs have no IP columns (constant 0) and no ultra-long aggregate
flows; live capture sees both. Naively fed to the model, a quiet home network
reads as an attack (0.69 risk — a false alarm). Every live/upload window is
therefore **conditioned to the model's validated input domain** before
inference: IP-count features zeroed, flag-ratio and down_up features clamped
to the training p99. With conditioning: benign reads 0.014, attacks still
cross 0.95+. This is disclosed in the model card and on the UI — and crucially
the **rule engine and evidence panel always see the RAW observed values**, so
the human is never shown a sanitized view of their own network.

---

## 7. The models: V1, V2, V3

Three models, one lineage — each a strict superset experiment of the last, all
additive, V1 never destroyed (frozen byte-identical copy in
`models/baseline_cic2018_v1/`, test-enforced).

### 7.1 V1 — the deployed LSTM forecaster

`src/models/lstm_forecaster.py` → `src/forecasting/rollout.py` (the frozen
inference bundle: model + scaler + threshold together, so they cannot diverge).

- **Architecture:** LSTM(18 → 64, 2 layers) → linear head → prog_head (5
  horizon steps) + stage_head (6 stages). ~57K parameters, weights 234,073
  bytes, sha256-16 `2b41bec7be520540`.
- **Input:** 10 windows × 18 features (5 minutes of history).
- **Output:** attack-fraction probability for each of the next 5 windows
  (2.5-minute horizon) + dominant ATT&CK stage, in ONE forward pass
  (direct multi-horizon).
- **Training:** chronological split, pos_weighted BCE per step, early stopping
  on pooled validation PR-AUC (patience 25 — after we discovered a too-small
  patience was silently undertraining the model; see §20), checkpoint on best
  validation, threshold 0.5612 picked on the *validation* PR curve (FPR ≤ 5%),
  never on test.
- **Test results (held-out, chronological):** PR-AUC **0.6565**, precision
  **0.8824**, recall 0.1395, F1 0.2410, FPR **0.0057** — versus a logistic
  regression baseline on the same features and split: PR-AUC 0.3335,
  precision 0.500, recall 0.009 (artifact: `models/metrics_baseline.json`).
  The baseline is not a strawman — it proves the sequence model's value is
  real: nearly double the ranking quality.

### 7.2 V2 — the state-head world model (honest negative result)

`src/models/world_model.py` — V1's architecture plus an explicit ATT&CK
**state head**: a parallel multi-task regression onto future canonical state
vectors, λ-weighted Huber loss, swept λ ∈ {0.1, 0.3, 0.5}.

**Result: adding the state head did NOT improve attack forecasting on
CIC2018.** Best (λ=0.5): PR-AUC 0.6050 vs V1's 0.6565; state cosine 0.227.
Recorded as a negative result in the model card, kept in the repo on purpose.
The multi-dataset experiments re-tested the state head with diverse data —
that is the entire point of keeping the negative result around.

### 7.3 V3 — the rollout world model (the genuine "world model")

`src/models/rollout_world_model.py`. The honest criticism of V2: its states
were a *side task*; risk still flowed straight from the encoder. V3 fixes the
causality so the architecture genuinely answers "learn P(S_{t+1} | S_t)":

```
LSTM encoder → h → Ŝ(t+1)                       (state initialization)
Ŝ(k+1) = Ŝ(k) + g(Ŝ(k))                          (residual transition, autoregressive)
risk(t+k) = risk_decoder(Ŝ(t+k))                 (attack risk DECODED from forecast state)
stage(t+k) = stage_decoder(Ŝ(t+k))               (per-step ATT&CK stage — new)
```

Risk and stage are **decoded from the forecast future states** — if the state
rollout is wrong, the risk forecast is wrong; they cannot diverge. The
autoregressive rollout is verified by unit tests: perturbing a predicted state
changes the risk at that step and later steps; the transition is a pure
function of state; evaluation is deterministic.

- Training: same protocol/split as V1/V2; loss = BCE(risk) + CE(stage, per-step
  dominant-stage supervision) + 0.5·Huber(states vs actual future windows).
- Test: PR-AUC **0.6331** at its own validation-picked threshold 0.8942
  (precision 1.000, recall 0.0651 — extremely conservative); **state cosine
  0.257, the best state prediction of any variant** (V2: 0.227), rising
  0.219 → 0.289 across the horizon.
- **Honest verdict, stated in the model card:** V3 does not beat V1's direct
  head on CIC2018 alone. Its value is architectural — a true state-transition
  chain with per-step stage — and the multi-dataset experiments test whether
  diverse data changes that verdict.
- **Deployment:** additive companion. `/api/forecast` keeps its V1 numbers and
  adds `future_steps` — per-step stage, risk-from-state, and the top-3 moving
  state features ("what changes in the network state if this forecast holds") —
  rendered as T+1…T+5 chips in the UI. If the V3 artifact is missing, the
  field degrades to `null` and nothing else changes.

### 7.4 Model comparison (same test split, same protocol)

| Model | PR-AUC | Precision | Recall | FPR | State cosine |
|---|---|---|---|---|---|
| Logistic baseline | 0.3335 | 0.500 | 0.009 | 0.003 | — |
| **V1 LSTM (deployed)** | **0.6565** | **0.8824** | 0.1395 | 0.0057 | — |
| V2 state head | 0.6050 | 0.8810 | 0.1721 | 0.0071 | 0.227 |
| V3 rollout world model | 0.6331 | 1.0000 | 0.0651 | 0.0000 | **0.257** |

---

## 8. Multi-dataset training & cross-dataset evaluation

This is the experiment the whole canonical-schema/adapters/sequence-engine
machinery was built for. Datasets in hand: **CIC-IDS2018, UNSW-NB15, CTU-13**
(three capture modalities: per-host flow CSV, unlabeled-payload research flows,
bidirectional NetFlow with real IPs).

### 8.1 Experiment matrix

| Exp | Training data | Purpose |
|---|---|---|
| A | CIC2018 only | frozen baseline, rerun under the canonical pipeline for comparability |
| C | CIC2018 + UNSW-NB15 | does a second modality help in-domain? |
| D | CIC2018 + UNSW-NB15 + CTU-13 | does stage-rich botnet data help the state models? |
| **Cross-dataset** | train on N, test on held-out dataset | the generalization question — does a forecaster trained on one network/dataset transfer? |
| **Leave-one-dataset-out** | train on all but one, test on the held-out one | the honest estimate of real-world transfer |

### 8.2 What the design controls for

- **Feature availability masks:** each dataset contributes only features it
  verifiably provides; the masked scaler handles per-dataset availability
  without zero-imputation, so the model is never trained on fabricated zeros.
- **Time order within each dataset:** chronological splits per dataset; no
  sequence mixes two datasets' windows.
- **Label spaces:** all three datasets map onto the canonical stage taxonomy
  (§4), with `UNKNOWN_ATTACK` when a family cannot be honestly mapped (UNSW's
  "Generic" — a block-cipher attack with no stage-attributable behavior — is
  the canonical example of refusing to guess).

### 8.3 The three-regime report

For every model variant, evaluation reports: **in-domain** (same dataset,
later time), **cross-dataset** (train N, test held-out), and
**leave-one-dataset-out**. Artifacts: `models/metrics_multidataset*.json`
(rendered by the Benchmarks page verbatim). The headline question — "did more
data help?" — is answered with numbers for each variant, including the cases
where the answer is **no** (V2 taught us to expect that possibility and to
report it).

### 8.4 Results — measured 2026-09-04, time-boxed for the internal demo

The demo deadline (2026-09-05) time-boxed the run: 8 epochs, training windows
capped at 25,000, leave-one-dataset-out and single-dataset baseline runs
skipped — every cut recorded inside the artifacts (`"skipped"` /
`"skip_reason"` keys in `models/metrics_multidataset.json`), never silently
dropped. Two pooled models shipped:

- **v1** (`models/multidataset_v1/`) — CIC2018 + UNSW-NB15.
- **v2** (`models/multidataset_v2/`) — CIC2018 + UNSW-NB15 + **CTU-13
  (7/13 scenarios, partial build, flagged)** — 4,413 windows from 8.78M
  flows; scenarios 2, 3, 6, 9, 11, 13 were still extracting, so the build
  records `ctu13_partial: true` with the used/pending scenario lists.

**A correction discovered by measurement:** the honest three-way intersection
of the legacy 18 is **9 features, not 11** — CIC2018's ML-ready CSVs carry no
IP columns, so `unique_src_ips`/`unique_dst_ips` cannot be in a shared feature
set. The 9: flow_count, bytes_total, pkts_total, duration_mean, avg_pkt_size,
unique_dst_ports, dst_port_entropy, down_up_ratio, auth_port_share. Training
a shared model on a feature any dataset cannot measure would mean
zero-imputing it — forbidden by the data contract.

| Test split (chronological, held-out) | v1 PR-AUC | v2 PR-AUC | v2 P / R / FPR |
|---|---|---|---|
| CIC2018 (in-domain) | 0.3195 | 0.2147 | 0 / 0 / 0.000* |
| UNSW-NB15 (in-domain) | 1.0000† | 1.0000† | 0 / 0 / 0.000* |
| CTU-13 (in-domain, 7/13) | — | **0.9918** | 0.992 / 0.693 / 0.097 |
| **Pooled** | 0.8961 | **0.9348** | 0.992 / 0.322 / 0.0041 |

\*At the pooled threshold — see the threshold-transfer finding below.
†Degenerate split, disclosed: UNSW-NB15's chronological test split is 100 %
attack windows (418/418) — a perfect ranking score there means "separable",
not "great forecaster".

**Finding 1 — CTU-13 helped the pooled forecaster.** Adding botnet C2
windows lifted pooled PR-AUC 0.896 → 0.935, and the model learns CTU-13's
own dynamics strikingly well (0.992 on its held-out scenarios) from the
9-feature intersection — with flags and IAT honestly unavailable from Argus
NetFlow.

**Finding 2 — the capability/precision trade-off, now measured twice.** Each
added dataset pushed CIC2018 in-domain further down (V1 18-feature: 0.657 →
v1 pooled: 0.320 → v2 pooled: 0.215). CTU-13's 51 %-positive training
windows pull the shared 9-feature representation toward C2-volume patterns.
More data is not free; the deployed demo model stays V1.

**Finding 3 — a single global threshold does not transfer across datasets.**
v2's validation-picked pooled threshold (0.643) fires zero alarms on both
CIC2018 and UNSW test splits despite usable ranking scores — score scales
differ per dataset because the feature distributions differ. The right
operating point is per-dataset thresholds (recorded as future work); the
ranking metrics above remain valid either way.

---

## 9. The rule engine — deterministic, no ML

`src/attack_mapping/mitre_mapper.py::rule_based_stage` — an ordered,
first-match-wins rule set over RAW window features, running alongside the
LSTM for instantaneous stage attribution (the LSTM forecasts; the rules
explain the present). Thresholds are tuned against `validate_rules()` — a
cross-tab of rule predictions vs dataset labels — never by feel.

1. **Reconnaissance:** ≥ 15 unique destination ports AND SYN ratio ≥ 0.4 → scanning.
2. **Initial Access:** auth-port share ≥ 0.5 with ≥ 8 flows → credential attacks.
3. **DoS:** packets AND bytes both above training p99 → volumetric flood.
4. **Command & Control:** bounded flow count, ≥ 30 packets, inter-arrival
   jitter ratio < 0.25, ≤ 3 destination IPs (when IPs exist) → regular beaconing.
5. **Lateral Movement:** ≥ 3 endpoints both directions AND lateral-port share
   (SMB/RPC/RDP/WinRM) ≥ 0.2 → internal spread.
6. **Exfiltration:** bytes above p99 with few flows → bulk transfer.

**The abstention discipline (a headline feature, not a gap):** CIC2018's
training CSVs have no IP columns, so a lateral-movement rule keyed on internal
endpoints *could never fire* and a C2 rule keyed on destination counts was
*always true*. Rather than ship rules the jury can break, the engine detects
whether IP features carry signal and **abstains** ("UNDECIDABLE from these
features") when they do not. An abstention you can explain beats a rule that
lies. On live capture (where IPs are real), the full rule set is armed.

The family→stage supervision table (FAMILY_STAGE) doubles as the validation
reference for the rules — every stage the rules can output is a stage the
labels can confirm.

---

## 10. The explainability stack

No LLM anywhere in the explanation path — every explanation is a deterministic
template over real model outputs and real measured values. (Rule: explanations
must be reproducible in a courtroom, not plausible in a demo.)

### 10.1 Evidence rows (`src/explainability/evidence.py`)

For the most recent windows, each feature gets: **observed value (RAW —
pre-conditioning), benign baseline mean, training p99, z-score, direction,
attribution** ("this window's syn_ratio is 4.2σ above benign baseline").
Baseline built from 3,308 benign TRAIN windows only (`models/benign_baseline.json`)
— the test split never touches the baseline. A feature with baseline std = 0
produces *no claim* rather than an infinite z-score.

### 10.2 Temporal WHY (`src/explainability/temporal.py`)

A W-9…W-0 per-window importance/trend narrative — which windows in the
lookback drove the forecast, and in which direction the risk moved and why
(which features rose when).

### 10.3 Uncertainty — seeded MC-dropout (`src/explainability/uncertainty.py`)

T=16 stochastic forward passes through the dropout layers, **seeded and
state-restoring** (deterministic per seed — the same input always yields the
same band; demo-proof). Bands: HIGH confidence (max σ < 0.05), MEDIUM (< 0.15),
LOW. An unknown band defaults to MEDIUM, never HIGH — confidence is earned.

### 10.4 Calibration (`src/explainability/calibration.py`)

Measured on the frozen V1 (`models/calibration_v1.json`): pooled n=4,580 test
windows, **Brier 0.1399, ECE 0.095**, per-step ECE 0.077–0.112 with *no
degradation across the horizon*. The model is over-confident in low bins —
reported as-is on the Benchmarks page, and the MC bands exist precisely to
communicate that uncertainty rather than hide it.

---

## 11. The decision-support engine

`src/decision_support/` — the human-in-the-loop layer that turns a forecast
into an actionable recommendation, while never acting on its own.

**The escalation ladder** (explicit, from forecast content):

| Level | Trigger | Meaning |
|---|---|---|
| MONITOR | below threshold, no crossing in horizon | watch, nothing more |
| INVESTIGATE | forecast approaching threshold or crossing at later steps | look at the evidence now |
| CONTAINMENT REVIEW | crossing sustained across multiple steps + HIGH confidence | prepare containment options |
| ESCALATE | crossing immediate + sustained + HIGH confidence | escalate to the authority who can act |

**Ranked recommendations (P1/P2/P3)** cite real evidence numbers ("SYN ratio
4.2σ above benign baseline; forecast crosses 0.56 at T+3"). **Every record
carries the human-in-loop statement** and the system-wide invariant: **nothing
executes** — no blocking, no dropping, no reconfiguration, anywhere in the
codebase (test-enforced). The analyst decides; the system informs.

---

## 12. MITRE ATT&CK integration

The official MITRE ATT&CK STIX bundle (53.8 MB) is downloaded once to
`data/knowledge/mitre_attack/` and pre-digested into a 160 KB local index:
**709 techniques, 15 tactics**, with real mitigations and detections. A
curated family→technique map (T1110 brute force, T1190 exploit public-facing
app, T1071 application-layer C2, T1021 remote services, T1498 network DoS,
T1005 data from local system — all verified present in the STIX) with a
stage→tactic fallback. If the index is missing, the UI says "knowledge base
unavailable" — it does not invent technique IDs. Fully offline; no API calls
at inference, ever.

---

## 13. The live capture pipeline

`src/live/` + `api/live_state.py` — real packet capture on the operator's own
machine via Npcap:

1. **Capture** → packets flow into the same LiveWindowBuilder used by the
   packet-feature path (§6.3).
2. **Windowing** → 30-second windows, identical semantics to training.
3. **Conditioning** → domain conditioning (§6.5), disclosed.
4. **Forecast** → frozen V1 bundle + MC-dropout band.
5. **Enrichment (additive)** → evidence rows from RAW values, decision-support
   record, per-step V3 chips when available. Every enrichment degrades to
   `null` when its engine is missing — the live demo path never depends on an
   optional component.
6. **Rules** → the deterministic rule engine runs on RAW observed values with
   full IP awareness (live capture has IPs, unlike CIC2018 training).

Verified on real captured traffic (Aug 30, 2026 rehearsal): 98 live windows,
feed 200 on every poll, MC band HIGH (max σ 0.0274), 8 evidence rows,
decision support MONITOR with real STIX mitigations.

---

## 14. The upload pipeline

`src/ingestion/upload_pipeline.py` + `POST /api/analyze/upload` — the offline
backup demo path and the analyst's "here, analyze this capture" workflow:

- **Magic-byte detection** (pcap, pcapng incl. nanosecond variants; CIC-flow
  CSV; generic flow CSV) — file extensions are NEVER trusted.
- **CIC-flow CSV** vs **generic flow CSV** distinction with a confidence
  score; a **ColumnMapper** with ~60 column aliases across CIC/UNSW/CTU/Zeek
  conventions and explicit user mapping overrides; durations normalized
  (s→µs); unknown schema → **400 "please map columns"** with a mapper report —
  never a silent guess.
- **Safety:** 100 MB cap, parse-never-execute (files are read as data, never
  run), temp files always cleaned, `torch.load` restricted to
  `weights_only=True` everywhere in the codebase.
- **Output:** the full Phase 9–11 record — per-anchor forecast trajectory with
  threshold refline, MC uncertainty, evidence, decision support, honest
  "unavailable features" notes.

---

## 15. API reference

FastAPI, port 8000, all responses carry honesty context.

| Endpoint | Method | What it returns |
|---|---|---|
| `/api/health` | GET | service status, model loaded?, mode |
| `/api/scenarios` | GET | demo scenario list (cached trajectories) |
| `/api/forecast` | POST | the forecast: probs (T+1..T+5), peak, level, stage, rule_stage, threshold, crossing_step, evidence, MC band, decision support, **future_steps (V3 per-step stage/risk/movers)**, mode |
| `/api/timeline` | GET | window timeline with flags |
| `/api/metrics` | GET | all benchmark artifacts, namespaced, verbatim |
| `/api/flagged` | GET | windows that crossed threshold |
| `/api/live/status` | GET | capture status |
| `/api/live/start` / `stop` | POST | control live capture |
| `/api/live/feed` | GET | latest live windows + forecast + enrichments |
| `/api/live/interfaces` | GET | capture interfaces |
| `/api/datasets` | GET | registry statuses: READY / PENDING_WIRING / NOT_DOWNLOADED per dataset |
| `/api/analyze/upload` | POST | upload → detect → analyze → full record |

Every forecast response's `mode` field is the honesty badge: **REAL**
(model + real data), **CACHED** (demo scenario from artifacts),
**SIMULATED** (would-be values, labeled as such).

---

## 16. The web UI

Next.js 15, port 3000, dark SOC-style design system, offline assets only.
Nav: **Forecast · Live · Analyze · Benchmarks · Datasets.**

- **Forecast** — scenario/dataset selection, PeakGauge, the horizon
  trajectory chart with threshold refline, attack-progression stage chips,
  and (new) the V3 **per-step stage panel**: T+1…T+5 chips each with stage
  name, risk %, and hover-movers ("syn_ratio ↑, iat_std ↓").
- **Live** — real-time capture view: rolling window feed, live forecast,
  EvidencePanel + DecisionSupportPanel when enrichment engines are present,
  honesty badge always visible.
- **Analyze** — the upload page: detection card (format/confidence/matched
  columns), forecast hero + MC badge, per-anchor trajectory chart,
  EvidencePanel, DecisionSupportPanel.
- **Benchmarks** — every metric artifact rendered verbatim (V1/V2/V3,
  baseline, calibration, stage-lead, multi-dataset reports); nothing
  hand-typed.
- **Datasets** — the registry status board: which datasets are READY, what
  each verifiably provides, source links — the credibility beat of the demo.

TypeScript types in `web/lib/api.ts` mirror the API contract file-for-file;
`tsc` is clean and part of the test gate.

---

## 17. Evaluation — every number, honestly

*(Authority: `docs/EVALUATION.md`; every number below is produced by a repo
script and stored in an artifact under `models/`. Labels: **measured**,
**limited** (measured but statistically weak), **negative** (kept on purpose).)*

### 17.1 Configuration (single source, `src/config.py`)

Window 30 s · lookback L=10 (5 min) · horizon K=5 (2.5 min) · 18 model features
· canonical schema 48 features (hash `a9570d8349141d92`) · V1 threshold 0.5612
(val-picked) · V3 threshold 0.8942 (val-picked).

### 17.2 Forecasting quality (held-out chronological TEST split, measured)

| Model | PR-AUC | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| Logistic baseline | 0.3335 | 0.500 | 0.009 | 0.018 | 0.003 |
| **V1 LSTM (deployed)** | **0.6565** | **0.8824** | 0.1395 | 0.2410 | 0.0057 |
| V2 state head (λ=0.5) | 0.6050 | 0.8810 | 0.1721 | 0.2879 | 0.0071 |
| V3 rollout world model | 0.6331 | 1.0000 | 0.0651 | 0.1223 | 0.0000 |

State prediction (scaled space): V2 cosine 0.227 → **V3 0.257** (0.219→0.289
across the horizon).

### 17.3 Calibration (measured)

Pooled n=4,580: Brier 0.1399, ECE 0.095; per-step ECE 0.077–0.112, no horizon
degradation. Over-confident in low bins — reported as-is.

### 17.4 Lead time

- **Offline attack onset (limited):** the test split has 1 onset; the model
  did not cross threshold before it (warned_rate 0.0). CIC2018 attacks start
  abruptly from clean baselines — verified with `scripts/diagnose_leadtime.py`
  (flat ~0.52 base-rate output from clean inputs). We do not claim an offline
  lead time we cannot support.
- **Live rehearsal (measured, real packets, 2026-08-30):** UDP sweep forecast
  climbed 0.03 → 0.03 → 0.17 → **0.905** → 0.968 → 0.988 over consecutive
  windows (crossing at the 4th sustained window); loopback variant 0.022 →
  0.384 → 0.947, holding 0.977–0.989; benign two-device Wi-Fi stayed ≤ 0.014;
  a SYN scan triggered the Recon rule within ONE window while the model
  (correctly, by design) stayed LOW — instantaneous detection is the rule
  engine's job; the forecast is the model's.
- **Stage-transition lead time (limited, new):** for each true stage-change
  onset (with the warnable-onset filter that keeps only onsets a split's
  anchors could actually warn on): test 1 onset (Lateral Movement) warned
  **5 windows = 2.5 min early**; val 2/2 warned. Sample too small for a
  headline — recorded as limited.

### 17.5 Negative results (kept on purpose)

1. V2 state head did not improve CIC2018 forecasting.
2. V3 does not beat V1's direct head on CIC2018 alone.
3. Offline onset lead time is 0 on this data (data limitation, disclosed).

### 17.6 Rules

Chronological splits, day-boundary purge; thresholds picked on VALIDATION
only; missing = unavailable, never zero; artifacts hash-pinned; live inputs
domain-conditioned with the conditioning disclosed and the raw values shown
to the human.

### 17.7 Multi-dataset & cross-dataset (Phase 7/8, measured, time-boxed)

*(Authority: `models/metrics_multidataset.json` (keys `multidataset_v1`,
`multidataset_v2`) + `models/metrics_cross_dataset.json`, rendered verbatim by
the Benchmarks page. Full story: §8.4.)*

- **v1** `models/multidataset_v1/` — 9-feature intersection, CIC2018 +
  UNSW-NB15, pooled test PR-AUC 0.8961. **v2** `models/multidataset_v2/` —
  + CTU-13 (7/13 scenarios, partial build flagged; 4,413 windows from 8.78M
  flows), pooled test PR-AUC **0.9348**, CTU-13 in-domain **0.9918**
  (P 0.992 / R 0.693 / FPR 0.097).
- **Negative result, kept on purpose:** pooling keeps hurting CIC2018
  in-domain (0.657 → 0.320 → 0.215) — the capability/precision trade-off
  measured across two runs. V1 remains the deployed demo model.
- **Threshold-transfer finding:** the pooled validation-picked threshold
  (0.643) fires zero alarms on CIC2018/UNSW test splits despite usable
  ranking — score scales differ per dataset; per-dataset thresholds are the
  recorded fix (future work).
- **UNSW test split is degenerate** (418/418 attack windows) — its 1.000
  ranking score is disclosed as "separable", not claimed as a result.
- **Skipped for the demo deadline** (recorded in the artifact):
  leave-one-dataset-out, single-dataset baselines. CTU-13 scenarios 2, 3, 6,
  9, 11, 13 were still extracting at training time; the full-13 rebuild is
  the same two commands once they land (`scripts/build_dataset_windows.py`,
  `scripts/train_multidataset.py`).

---

## 18. The honesty system

The prototype's most distinctive subsystem — the rules that keep every
displayed claim true:

1. **Mode badges** — REAL / CACHED / SIMULATED on every forecast response.
2. **Unavailable ≠ zero** — availability masks from schema to UI; a dataset
   that cannot measure TCP flags reports "unavailable," never 0.0.
3. **No silent fallback** — a missing model or engine degrades to `null` with
   a reason, never to a lookalike value.
4. **Verbatim artifacts** — Benchmarks and Datasets pages render artifact
   contents without retyping.
5. **Golden regression** — 12 tests pin artifact hashes and exact model
   outputs (probs to 4 decimals); a changed file fails the suite with "update
   the pin on purpose, never delete it."
6. **Known-limitations-first documentation** — MODEL_CARD's "NOT intended /
   hard limits" section is as prominent as its results table.

---

## 19. Security & ethics posture

- **Human-in-the-loop, enforced:** no automated response exists anywhere in
  the codebase — test-enforced invariant. Recommendations only.
- **No attribution:** the system profiles traffic, never people; no attacker
  identification claims.
- **Own-network only:** live capture runs on the operator's machine/network;
  the rehearsal attack scripts target loopback or the operator's own second
  device.
- **Untrusted input is parsed, never executed:** magic-byte detection, 100 MB
  cap, temp files always cleaned, `torch.load(weights_only=True)` everywhere.
- **Fully offline at inference:** no cloud APIs, no CDN-required assets, no
  LLM, local MITRE STIX digest — demonstrable with the network cable pulled.
- **Privacy:** no user identifiers modeled; uploaded captures stay on the
  operator's machine and temp copies are always deleted.

---

## 20. Engineering war stories

The bugs we found, fixed, and turned into tests — the section that proves the
numbers:

1. **Welford iat_std bug + IP zeroing.** The live pipeline's running
   inter-arrival statistics were subtly wrong (Welford update applied to the
   wrong accumulator) and IP counts leaked into the model input. Found via the
   quiet-network false alarm (0.69 on benign traffic); fixed, and the whole
   domain-conditioning design (§6.5) came out of it.
2. **Early-stopping patience.** The first training runs used a patience far
   too small — the model was being checkpointed before convergence and we
   were quietly undertrained. Patience raised to 25 with checkpoint-on-best;
   the fix is part of the shared training protocol.
3. **Rule-engine abstention.** The lateral-movement rule could never fire on
   CIC2018 (no IPs) and the C2 destination clause was always true. Instead of
   shipping theatrical rules, the engine detects feature signal and abstains
   (§9). The quiet-network C2 false positive (5 flows / 14 packets) got a
   packet-count floor after the live rehearsal caught it.
4. **CIC2018's aggregate-flow duration trap** — handled in preprocessing, not
   silently averaged.
5. **UNSW's "Backdoors" spelling variant** and the synack/ackdat-are-times
   trap — both caught by validating against the real files before writing the
   adapter.
6. **Stage-lead split bug (found today, 2026-09-04).** Stage-transition
   onsets were computed globally over all windows, so onsets belonging to
   another split deflated the warned rate and made val and test look
   identical. Fixed with a warnable-onset filter; the metric now honestly
   reports 1–3 onsets as too small a sample.

---

## 21. Testing & reproducibility

- **163 pytest tests, all green (~40–60 s)** across: dataset adapters
  (CIC2018/UNSW/CTU-13, real-file smokes), canonical schema, sequence engine,
  packet features, all three models (including V3's causal/autoregressive
  proofs), explainability, decision support, upload pipeline (magic bytes,
  mapper, 400-on-unknown-schema), live enrichment degradation, stage-lead
  metric, golden regression (hash pins + exact output pins + API contract
  checks), and the API exposure tests (V1 contract unchanged, V3 additive).
- **TypeScript:** `tsc` clean, part of the gate.
- **Reproducibility chain:** `src/config.py` single-sources the
  constants → `scripts/rebuild_all.py` rebuilds everything from raw data,
  stopping at the first failure → golden tests pin the artifacts →
  `MODEL_CARD.md` records the hashes → frozen V1 copy is byte-identical
  (test-enforced). Git commits were disabled during the build per team
  decision; the commit of record at freeze time is `7d5c827`.

---

## 22. Advantages

1. **It forecasts, not just detects** — a real 5-step-ahead horizon with a
   trajectory, not a single verdict; the forecast rises before attacks
   sustain (live-rehearsal numbers above).
2. **Attack-stage awareness** — six ATT&CK stages in the supervision, the
   rule engine, the V3 per-step stage decoder, and the UI.
3. **A genuine world model** — V3's risk is decoded from autoregressively
   rolled-out future states; the P(S_{t+1}|S_t) chain the problem statement
   asks for, with the causality test-proven.
4. **Explainable without an LLM** — evidence rows, temporal WHY, MC-dropout
   uncertainty, calibration: all deterministic, all reproducible.
5. **Decision support that respects the human** — a four-level ladder, ranked
   actions citing real numbers, ATT&CK enrichment, and nothing that executes.
6. **Three datasets, three modalities, one contract** — the canonical schema
   + adapter layer turns heterogeneous sources into one training regime with
   honest availability masks.
7. **Honesty as an architecture** — mode badges, unavailable≠zero, verbatim
   artifacts, golden pins, negative results published in the model card.
8. **Works fully offline** — no cloud dependency at inference; MITRE
   knowledge is a local digest.
9. **Live + upload + offline demo paths** — the demo survives a dead
   network: live capture, file upload, or cached scenarios, all through the
   same engine.
10. **Reproducibility as a feature** — 163 tests, hash-pinned artifacts,
    single-sourced config, a rebuild script that fails loudly.

---

## 23. Disadvantages & limitations

Stated as plainly as the advantages, because judges and operators deserve both:

1. **Low recall at the operating threshold (0.14)** — by design (precision-
   first forecasting), but it means most attack *moments* are not individually
   flagged; the value is the sustained-attack warning, not per-window
   detection.
2. **Single-network characterization** — the frozen V1 is trained on
   CIC-IDS2018; performance on networks unlike it is characterized by the
   multi-dataset/cross-dataset experiments, and cross-dataset transfer
   degrades (as it does for every published IDS work we are aware of — the
   difference is we measure and report it).
3. **Offline onset lead time is unmeasurable on CIC2018** (1 test onset,
   warned_rate 0) — the citable lead-time evidence is the live rehearsal, and
   the stage-transition lead (2.5 min) rests on 1–3 onsets.
4. **No automated response** — deliberately; also a real operational limit if
   a deployment expects SOAR-style action.
5. **Live-input conditioning is a crutch** — the frozen V1's training data
   lacks IP features, so live inputs must be domain-conditioned; the right
   long-term fix is training on IP-rich data (what the multi-dataset phase
   delivers), not clamping.
6. **30-second window granularity** — sub-second attacks can complete inside
   one window; the rule engine's instantaneous checks partially cover this,
   the forecaster does not.
7. **No deployment hardening** — single-node prototype; no HA, no
   multi-tenant, no streaming scale-out. The architecture doc says exactly
   what is future work.
8. **Stage supervision granularity** — per-sequence dominant stage for
   training labels (dataset labels are per-flow), which limits per-step stage
   discrimination claims (the V3 stage accuracy carries a majority-class
   caveat for exactly this reason).
9. **Demo datasets are laboratory captures** — CIC2018 is synthetic-ish
   enterprise traffic; UNSW and CTU-13 are research captures. Real SOCs are
   messier.
10. **V2/V3 do not (yet) beat V1 on headline metrics** — recorded as negative
    results; their value is architectural and the diverse-data retest is the
    designed experiment.
11. **No streaming feature store** — windows are rebuilt per request in the
    prototype; production would need incremental state.

---

## 24. Repository map

```
cyberforecaster/
├── api/                    FastAPI app (main, state, schemas, live_state)
├── web/                    Next.js 15 UI (app/, components/, lib/api.ts)
├── src/
│   ├── config.py           single source: BIN_SECS=30, L=10, K=5
│   ├── preprocessing/      CIC2018 flow cleaning
│   ├── features/           canonical_schema · window_builder · sequence_engine
│   │                       packet_features
│   ├── datasets/           adapter contract + registry + cic2018 + unsw_nb15 + ctu13
│   ├── labels/             attack_taxonomy (canonical label space)
│   ├── models/             lstm_forecaster (V1) · world_model (V2)
│   │                       rollout_world_model (V3)
│   ├── forecasting/        rollout.py — the frozen V1 inference bundle
│   ├── attack_mapping/     mitre_mapper (STAGES, FAMILY_STAGE, rule engine)
│   ├── explainability/     evidence · temporal · uncertainty · calibration
│   ├── decision_support/   levels · mitre · recommendations · engine
│   ├── ingestion/          upload_pipeline (magic bytes, column mapper)
│   ├── live/               capture, packet_windower, history
│   └── evaluation/         lead_time · stage_lead
├── tests/                  163 tests incl. test_golden_regression.py
├── models/                 artifacts: trained_models/, baseline_cic2018_v1/,
│                           world_model_v2/, world_model_v3/, metrics_*.json
├── configs/                dataset_manifest.yaml · datasets/*.yaml
├── data/                   raw/ (read-only datasets) · processed/ · knowledge/
├── scripts/                rebuild_all · build_demo_cache · live_rehearsal
│                           diagnose_leadtime · attacks/ · start_demo
└── docs/                   EVALUATION · ARCHITECTURE · DATA_CONTRACT
                            DEMO_RUNBOOK · ACCEPTANCE_CHECKLIST · this file
```

---

## 25. The demo

The rehearsed arc (full detail: `docs/DEMO_RUNBOOK.md`):

1. **Benchmarks page** — establish credibility: every metric verbatim, the
   logistic baseline comparison, calibration, the negative results visible.
2. **Datasets page** — three READY datasets, what each verifiably provides,
   pending stubs honestly listed.
3. **Forecast** — a cached attack scenario: rising horizon trajectory, stage
   chips, evidence, decision support, the V3 per-step panel ("T+3: Initial
   Access, 99%").
4. **Live** — the money shot: start real capture, run the SYN scan
   (loopback), watch the rule engine fire within one window and the model
   stay LOW (correctly); run the UDP sweep and watch the forecast climb
   0.03 → 0.9 → 0.98 with HIGH confidence, evidence rows filling with real
   z-scores, the ladder climbing MONITOR → ESCALATE. Then let it recover on
   benign traffic (≤ 0.014).
5. **Analyze** — the offline backup: upload a CIC CSV or PCAP, full record
   without touching the network.
6. **Q&A tabs** — this document, MODEL_CARD, EVALUATION, ARCHITECTURE.

Preflight gate: `pytest` 163 green + `tsc` clean + API REAL mode + the 3
runbook checks.

---

## 26. The journey — phase by phase

| Phase | What | Key outcome |
|---|---|---|
| 0 | Repository audit | `docs/AUDIT_BEFORE_MULTIDATASET.md` — every known quirk catalogued before touching anything |
| 1 | Baseline freeze | V1 byte-identical copy in `models/baseline_cic2018_v1/`, verified still serving REAL mode |
| 2 | Canonical feature schema | 48 features, 7 groups, availability masks, hash-pinned |
| 3 | Dataset adapter layer | contract + registry; UNSW-NB15 wired (labels read from real files); CTU-13 wired from the real binetflows |
| 4 | Packet features | Group E accumulator; pcap round-trip byte-identity test |
| 5 | Unified windowing/scaling | ONE sequence engine for train/live/upload; stale 60s defaults fixed everywhere |
| 6 | V2 state head | λ sweep; honest negative result on CIC2018 |
| 7 | Multi-dataset training | canonical pipeline over CIC2018 + UNSW + CTU-13 |
| 8 | Cross-dataset evaluation | three-regime reports, artifacts rendered on Benchmarks |
| 9 | Explainability | evidence + temporal + MC uncertainty + calibration |
| 10 | Decision support | ladder, P1–P3, MITRE STIX (709 techniques, 15 tactics), nothing-executes invariant |
| 11 | Upload pipeline | magic bytes, column mapper, 100 MB cap, parse-never-execute |
| 12 | UI integration | Analyze + Benchmarks + Datasets pages, panels wired, tsc clean |
| 13 | Live alignment | live path gains the full enrichment stack additively; RAW-value evidence |
| 14 | Regression testing | golden suite: hash pins + exact output pins + API contracts |
| 15 | Demo hardening | MODEL_CARD, ACCEPTANCE_CHECKLIST, runbook §8, final gates |
| + | V3 rollout world model | the genuine P(S_{t+1}\|S_t) architecture, per-step stage, API/UI exposure |
| + | Stage-lead metric | stage-transition lead time with the warnable-onset honesty filter |

---

## 27. Future roadmap

1. **Deploy V3-or-successor** if the diverse-data experiments flip the
   verdict (the architecture is already wired end-to-end).
2. **Cross-network calibration transfer** — recalibration on a target
   network's benign baseline, keeping the frozen forecaster.
3. **Streaming feature store** — incremental windowing for production
   throughput.
4. **SIEM integration** — flow exports (NetFlow/IPFIX, Zeek) as first-class
   inputs alongside packet capture.
5. **Remaining datasets** — CICIoT2023 (IoT domain) and DARPA as
   external-validity test sets; the adapter stubs are already registered.
6. **Graph features** — host-communication graph structure as a feature group
   (the canonical schema's group structure anticipates it).

---

## 28. Numbers cheat sheet

| Fact | Number |
|---|---|
| Window / lookback / horizon | 30 s / 10 windows (5 min) / 5 steps (2.5 min) |
| Model input features | 18 (of 48 canonical) |
| V1 PR-AUC / precision / FPR | 0.6565 / 0.8824 / 0.0057 |
| Logistic baseline PR-AUC | 0.3335 |
| V2 PR-AUC (negative result) | 0.6050 |
| V3 PR-AUC / state cosine | 0.6331 / 0.257 |
| V1 threshold | 0.5612 (validation-picked) |
| Calibration Brier / ECE | 0.1399 / 0.095 (n=4,580) |
| MC-dropout | T=16, seeded, HIGH < 0.05 σ |
| CIC2018 training data | 6,192 windows, 764 attack-heavy, 7 days |
| UNSW-NB15 | 2,540,047 flows, 9 attack categories |
| CTU-13 | 13 botnet scenarios, 6 families, NetFlow with real IPs |
| Multi-dataset v1 (CIC+UNSW) | pooled PR-AUC 0.8961 · CIC2018 0.3195 |
| Multi-dataset v2 (+CTU-13 7/13) | pooled PR-AUC **0.9348** · CTU-13 **0.9918** · CIC2018 0.2147 |
| Multi-dataset feature set | 9 = honest 3-way intersection (IPs unavailable in CIC2018) |
| UNSW test split | all-attack (418/418) → PR-AUC 1.0 is degenerate, disclosed |
| CTU-13 in training | 4,413 windows / 8.78M flows, 7/13 scenarios (partial, flagged) |
| MITRE ATT&CK | 709 techniques, 15 tactics, local STIX digest |
| Live rehearsal (UDP sweep) | 0.03 → 0.17 → 0.905 → 0.968 → 0.988 |
| Live rehearsal (benign) | ≤ 0.014 all windows |
| Stage-transition lead | 2.5 min (5 windows) on available onsets (n small) |
| Tests | **163 passing**, golden-pinned |
| Decision ladder | MONITOR → INVESTIGATE → CONTAINMENT REVIEW → ESCALATE |
| Automated response | NONE — by design, test-enforced |
| LLM in explanation path | NONE — deterministic templates only |

---

*End of document. Numbers authority: `docs/EVALUATION.md` · Model authority:
`MODEL_CARD.md` · Architecture authority: `docs/ARCHITECTURE.md` ·
Rebuild: `python scripts/rebuild_all.py` · Test gate: `pytest` (163).*
