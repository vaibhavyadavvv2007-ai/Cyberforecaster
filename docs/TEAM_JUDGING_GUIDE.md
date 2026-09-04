# TEAM GUIDE — Judging Rubric & The 3 Opening Questions

**SIH26153 · AI-based Network Attack Forecasting System (NTRO) · CyberForecaster**

*This guide is written for our own team. It explains (1) the three questions every
judge opens with, and (2) all 10 judging criteria — what each one actually checks,
what WE have that scores on it, what to SHOW on screen, and what to SAY. Read this
before the internal demo even if you know nothing else about the project.*

**Rubric: 10 criteria × 10 marks = 100 total.** You win by making the judge's
scoring job easy — every criterion below should be visibly demonstrable, not
claimed.

---

## PART 1 — The 3 opening questions (Problem Understanding)

> **"Who is bleeding? What is the real pain? Why now?**
> If the problem is weak, the product is weak."

These are the first three questions any judge asks. If you fumble these, nothing
else you built matters. Here are our answers.

### Q1. "Who is bleeding?" — Target user clarity

**Who actually suffers from this problem, by name and role?**

Our answer: **SOC analysts and network-defence teams** — the people sitting in a
Security Operations Centre watching dashboards for a bank, a telecom, a government
network, or a critical-infrastructure NOC. Specifically the **Tier-1/Tier-2
analyst** who has to triage alerts at 3 a.m.:

- They see attacks **only after the attack has already started** — the alert fires
  when the scan, the brute-force, or the exfiltration is *already happening*.
- They are drowning: a mid-size SOC sees **thousands of alerts a day**, most of
  them noise. Fatigue means real attacks get missed.
- When an alert does fire, they get a **number** ("severity 87") — not *what stage
  the attack is in*, not *what's coming next*, not *what to do about it*.

Secondary users: the **CISO/security manager** who needs early warning to
prioritize, and (for the NTRO context) **national cyber-defence monitoring** of
critical networks.

**One-liner to say:** *"Our user is the SOC analyst who today learns about an
attack while it's happening — we give them warning before the damage stage, and
tell them what to do next."*

### Q2. "What is the real pain?" — Root cause, not surface issue

**The surface issue:** "attacks happen and tools alert too late."
**The root cause:** today's tools are **detectors, not forecasters**.

- Every mainstream tool (IDS/IPS, SIEM rules, ML anomaly detectors) answers
  **"is this traffic bad, right now?"** — a *classification of the present*.
- But attacks are **not events, they are campaigns**: reconnaissance → initial
  access → lateral movement → command & control → exfiltration, unfolding over
  minutes to weeks. The damage (exfiltration, encryption, disruption) is at the
  END of that chain.
- Detecting the present means you always see stage N when stage N is already
  done. The missing capability is **predicting stage N+1..N+5** — a forecast of
  the attack's *trajectory* — plus **what stage it's in** (ATT&CK mapping) and
  **what the analyst should do** (decision support).

The second half of the pain: even when a tool warns, it hands the analyst a bare
score. No evidence, no recommended action, no confidence — so the human cannot
make a fast, defensible decision.

**One-liner to say:** *"The root cause is that every existing tool classifies the
present — but attacks are campaigns that unfold in stages. We forecast the
trajectory, map it to ATT&CK stages, and tell the analyst what to do."*

### Q3. "Why now?" — Urgency & market timing

1. **Attack economics have shifted.** Modern intrusions move laterally in
   minutes (ransomware pre-encryption phases, botnet C2 check-ins). A 2–5 minute
   heads-up is now the difference between containing one host and containing an
   estate.
2. **India-specific urgency (this is an NTRO problem statement).** Critical
   networks are under continuous probing; the ask is explicitly for *forecasting*
   capability — a defensive capability India currently deploys mostly as
   detection.
3. **The enabling pieces just matured together:** public staged-attack datasets
   (CIC-IDS2018, UNSW-NB15, CTU-13) make temporal training data available;
   commodity ML (sequence models) makes short-horizon traffic forecasting
   tractable on a laptop; and MITRE ATT&CK gives a shared stage vocabulary to
   explain predictions. None of this stack existed conveniently five years ago.
4. **Analyst burnout is a documented crisis** — alert fatigue is one of the top
   reasons breaches are missed. A tool that warns *early*, *rarely* (low FPR) and
   *with a recommended action* attacks exactly that.

**One-liner to say:** *"Attacks now move in minutes, India's defensive posture is
detection-first, and only now do staged-attack datasets + sequence models + ATT&CK
make forecasting buildable — the timing is not a coincidence, it's a window."*

---

## PART 2 — The 10 judging criteria, one by one

### 1. Problem Understanding (10) — *Clarity on the actual pain point, target users, scope*

**What it checks:** Did you understand the problem statement deeply, or just
pattern-matched keywords? Do you know your user, the pain, and the boundary of
what you're building?

**What we have:** The three answers above, plus a **scope decision we can defend**:
we forecast the **attack fraction of the next five 30-second windows (2.5 minutes
ahead)** and the **dominant ATT&CK stage**, from the last ten observed windows.
We deliberately did NOT build automated blocking — the problem statement demands
human-in-the-loop, and we built the entire decision-support stack around that
constraint. We can also state our limits plainly (single-onset test split,
per-dataset threshold transfer) — judges score *understanding*, and knowing your
own weaknesses is understanding.

**SHOW:** the slide/answer for the 3 questions. **SAY:** the one-liners above.

### 2. Innovation & Originality (10) — *How novel/creative the approach is vs. existing solutions*

**What it checks:** Is this an IDS re-skin, or something genuinely different?

**What we have — five things that are not standard IDS/ML practice:**
1. **Forecasting instead of detection** — an LSTM that outputs a *trajectory*
   (5-step horizon), not a yes/no. The horizon output lets us show *escalation
   and decay* of risk over time.
2. **Stage forecasting with ATT&CK mapping** — we predict the *dominant attack
   stage*, mapped to MITRE ATT&CK techniques from the **official STIX bundle**
   (no hand-waving, real knowledge base).
3. **Deterministic rule engine + ML forecast side by side** — the rule engine
   (thresholds, no ML) catches instantaneous recon; the LSTM forecasts. Two
   complementary systems, honestly labelled.
4. **Calibrated uncertainty** — MC-dropout variance bands (HIGH/MEDIUM/LOW) on
   every forecast, plus measured Brier 0.140 / ECE 0.095. Most hackathon ML
   shows a point prediction; we show *how sure the model is*.
5. **The honesty system** — every number on screen carries a REAL / CACHED /
   SIMULATED badge; missing features display "unavailable", never zero. This is
   an original engineering commitment, and judges notice it.

**SHOW:** the Live or Forecast page with uncertainty bands + the honesty badge.
**SAY:** *"We didn't build a better alarm — we built a forecaster that admits what
it doesn't know."*

### 3. Relevance to Problem Statement (10) — *Does the solution directly solve what was asked?*

**What it checks:** Did you solve THE problem, or a nearby easier one?

**What we have:** Walk the problem statement verb-by-verb:
- "forecast attacks **before** the damage stage" → 5-step horizon forecast,
  demonstrated live: a UDP sweep forecast climbs 0.03 → 0.17 → 0.905 → 0.968
  while benign traffic stays ≤ 0.014 — warning *as it builds*, with the
  trajectory visible.
- "estimate **what stage** the attack is in" → dominant-stage head + ATT&CK
  technique enrichment (stage-lead measurement: 2.5 min median warning on
  available stage transitions).
- "tell the analyst **what to do**" → decision-support engine: evidence rows
  (observed vs benign baseline, z-score, attribution), ranked P1–P3
  recommendations, and a MONITOR → INVESTIGATE → CONTAINMENT REVIEW → ESCALATE
  ladder.
- "**human in the loop**" → the system never blocks/drops/reconfigures anything.
  Recommendations only; the analyst decides. This is enforced in code, not just
  claimed.

**SHOW:** Forecast page → then the decision-support panel on Live/Analyze.
**SAY:** *"Every clause of the problem statement maps to a panel you can click."*

### 4. Technical Approach & Architecture (10) — *Soundness of tech stack, system design*

**What it checks:** Is the design principled or a pile of notebooks?

**What we have:**
- **Clean two-tier architecture:** FastAPI backend (model serving, capture,
  upload, decision engine) + Next.js 15 frontend; REST contract in
  `web/lib/api.ts` mirrors `api/schemas.py` (single source of truth, typed on
  both ends).
- **Data engineering, not just ML:** a **48-feature canonical schema** with a
  content-hash (`a9570d8349141d92`) that every dataset adapter must produce —
  three adapters (CIC-IDS2018, UNSW-NB15, CTU-13) behind one registry
  (`configs/dataset_manifest.yaml`). This is how real data platforms scale; it
  also enabled our multi-dataset experiments in hours, not weeks.
- **Leakage-proof evaluation protocol:** chronological train/val/test splits
  with day-boundary purge, thresholds picked on validation only. We can *explain
  why random splits would have inflated our numbers* — that sentence alone is
  worth marks.
- **Three model generations with recorded negative results:** V1 (direct LSTM
  head, deployed), V2 (state head — did NOT help, kept as a documented negative
  result), V3 (autoregressive state-rollout world model — architectural win,
  doesn't beat V1 on CIC2018; honestly reported). Judges rarely see teams that
  publish their own negative results.
- **163 automated tests** including a **golden regression suite** pinning model
  weights and artifact hashes — the demo cannot silently break.

**SHOW:** `docs/ARCHITECTURE.md` diagram or the Datasets page (adapter registry
statuses). **SAY:** *"Adapter pattern + chronological evaluation + 163 tests —
the boring engineering is what makes the demo trustworthy."*

### 5. Feasibility (Time & Resources) (10) — *Realistic to build within hackathon/timeframe*

**What it checks:** Could this actually be built by a team in the time given —
and was it?

**What we have:** **It's built and running on a laptop, offline.** Training data
ingested (8.78M NetFlow records from CTU-13 alone; 2.54M flows from UNSW-NB15),
models trained, API + UI running locally with no cloud dependency. The whole
demo works with the Wi-Fi off — that's the strongest feasibility statement a
demo can make. Everything runs on commodity hardware (this laptop, CPU-only
inference).

**SHOW:** open the app locally, point at the browser URL bar (localhost, no
cloud). **SAY:** *"Everything you'll see runs on this laptop, offline, right
now."*

### 6. Prototype / Proof of Concept (10) — *Working demo, MVP quality, functionality shown*

**What it checks:** Does it WORK, live, in front of me?

**What we have (the demo path — this is our strongest criterion):**
1. **Forecast page** — real model output on real CIC-IDS2018 data: 5-step
   forecast, uncertainty bands, per-step stage, rule engine, evidence.
2. **Live page** — capture real traffic from this laptop's network, watch the
   forecast react window by window (verified rehearsal numbers: benign Wi-Fi
   worst peak 0.014; SYN scan caught by the rule engine within one window;
   UDP sweep forecast crosses 0.947 by the third window). REAL badge on screen.
3. **Analyze page** — upload a capture (pcap/CSV), get the full pipeline:
   parse → features → forecast → evidence → recommendations.
4. **Benchmarks page** — every metric served verbatim from training artifacts,
   including the multi-dataset table (pooled PR-AUC 0.935; CTU-13 in-domain
   0.992) and negative results.
5. **Datasets page** — live status of all three datasets and the adapter
   registry.

**SHOW:** the whole tour (see `docs/DEMO_WALKTHROUGH.md` for the scripted order).
**SAY:** *"Five pages, all live, all real data, all numbers traceable to files on
disk."*

### 7. Scalability (10) — *Can it grow beyond the demo to real deployment?*

**What it checks:** Is this a science-fair project or the seed of a deployable
system?

**What we have:**
- **Data scalability, proven with numbers:** adding a third dataset (CTU-13,
  8.78M records, a completely different capture format — NetFlow binetflow vs
  CSV) took one new adapter + one build command, not a rewrite. The canonical
  schema is the scaling contract; new telemetry = new adapter.
- **Model scalability evidence:** the pooled multi-dataset model improved from
  PR-AUC 0.896 (2 datasets) to **0.935** (3 datasets) — the direction you want
  when more networks are added.
- **Deployment shape:** stateless FastAPI + stateless Next.js — horizontally
  scalable behind any load balancer; model inference is CPU-friendly (LSTM,
  234 KB weights); windowing is a streaming design (fixed 30-s bins), so it
  extends to a tap/SPAN port or Zeek/suricata feed in production.
- **Honest scaling limits we can state:** pooled thresholds don't transfer
  across networks (per-dataset thresholds = recorded next step); IP-derived
  features aren't in the shared schema because ML-ready public CSVs lack IP
  columns — a deployment with full telemetry would ADD those features.

**SHOW:** Datasets page (adapter registry) + the multi-dataset rows on
Benchmarks. **SAY:** *"We already scaled from one dataset to three, and the
pooled number went UP — the architecture scales because the schema is the
contract."*

### 8. Impact & Usefulness (10) — *Real-world value, who benefits, how much*

**What it checks:** Does anyone's life actually get better, measurably?

**What we have:**
- **For the Tier-1 analyst:** early warning during the build-up phase (the live
  rehearsal shows attack forecasts climbing across consecutive windows while
  benign stays flat ≤ 0.014) — triage starts minutes earlier, which is
  containment-window time.
- **For the SOC lead / CISO:** a low-FPR, high-precision warning stream
  (precision 0.882, FPR 0.006 at the operating threshold on the held-out test
  split) instead of a flood — directly attacks alert fatigue.
- **For decision-makers:** the recommendation ladder + evidence rows mean every
  warning is *auditable* — you can defend the response action afterwards.
- **National/critical-infrastructure framing (NTRO):** the same pipeline
  monitors a national NOC's uplinks; forecasting is the capability gap.
- **Measurable proxy we can cite:** our own live rehearsal numbers — warning
  while the sweep is still building, and stage-transition lead of 2.5 minutes
  median on the (small) available sample, honestly labelled as limited.

**SHOW:** Live page with a rising forecast + the recommendation panel.
**SAY:** *"Two minutes of extra warning is the difference between isolating one
host and chasing an intruder across the estate."*

### 9. Business / Sustainability Model (10) — *Cost-viability, adoption path, maintenance*

**What it checks:** Is there a path from prototype to something that survives?

**What we have:**
- **Deployment economics:** CPU-only inference, no GPU bill; the model is 234 KB;
  the stack is open-source end to end (FastAPI, Next.js, PyTorch, scapy) —
  near-zero marginal infrastructure cost. It can run on a sensor box already
  deployed in the network.
- **Adoption path (realistic, staged):** (1) internal SOC deployment as a
  *read-only advisory dashboard* next to the existing SIEM — zero risk, no
  workflow change, immediate feedback loop; (2) per-network threshold
  calibration from a week of that SOC's own traffic (our recorded next step);
  (3) integration as a correlation source feeding the SIEM (the API is already
  a clean REST surface).
- **Maintenance story:** datasets are re-trainable with two documented commands;
  the golden regression suite catches drift/breakage automatically; negative
  results and limitations are documented so future maintainers don't re-tread.
- **Sustainability honesty:** public datasets carry no IP columns, so a real
  deployment's first task is feature re-validation on site telemetry — we say
  this because an honest maintenance plan scores better than a fake one.

**SHOW:** (nothing on screen — this is a talk track) **SAY:** *"It runs on
hardware SOCs already own, starts as a read-only advisory pane next to the SIEM,
and the retraining pipeline is two commands."

### 10. Presentation & Communication (10) — *Clarity of pitch, documentation, Q&A handling*

**What it checks:** Can you *explain* it — pitch, docs, and surviving questions.

**What we have:**
- **A scripted demo** with a fixed order (Forecast → Live → Analyze → Benchmarks
  → Datasets) and a runbook (`docs/DEMO_RUNBOOK.md`) with verified numbers and
  fallbacks for every step.
- **Documentation depth:** `docs/PROTOTYPE_MASTER.md` (the everything-document),
  `MODEL_CARD.md` (model limits, intended use — the industry-standard format),
  `docs/EVALUATION.md` (single source of numbers), `docs/ARCHITECTURE.md`,
  `DATA_CONTRACT.md`, plus this guide. If a judge asks "where does 0.935 come
  from?", the answer is a file, openable live.
- **Q&A armour — questions we are READY for** (practise these):
  - *"Why is CIC2018 in-domain worse in the pooled model (0.215 vs 0.657)?"* →
    the 9-feature intersection trades per-network precision for pooled
    capability; measured, disclosed, and per-dataset thresholds are the recorded
    fix. Owning this converts a weakness into a credibility win.
  - *"What's your lead time?"* → offline onset lead time is honestly 0 (test
    split has 1 onset, attacks start abruptly); the citable evidence is the
    LIVE rehearsal trajectory + stage-transition lead (2.5 min, small sample).
    Never claim a number we can't show.
  - *"Can it block attacks?"* → No, by design — human-in-the-loop is in the
    problem statement; recommendations only.
  - *"What about encrypted traffic?"* → we model flow-level behaviour (sizes,
    timing, ports, directionality), which survives encryption; payload
    inspection is out of scope.
  - *"Is any number here fake?"* → every number traces to an artifact on disk;
    the badges say REAL/CACHED/SIMULATED; the tests enforce it.
- **Team delivery rule:** one narrator for the demo, others drive the
  environment and take questions in their area. Numbers are only spoken by the
  person who owns that artifact.

**SHOW:** open `docs/PROTOTYPE_MASTER.md` if a judge doubts documentation depth.
**SAY:** nothing — let the docs answer for you.

---

## Quick marks-map (use this as the pitch skeleton)

| # | Criterion | Our single strongest proof |
|---|---|---|
| 1 | Problem Understanding | The 3 one-liners (Part 1) |
| 2 | Innovation | Forecast trajectory + uncertainty bands + honesty badges |
| 3 | Relevance | Every problem-statement clause → a clickable panel |
| 4 | Technical Approach | Canonical schema + 3 adapters + 163 tests |
| 5 | Feasibility | Runs offline on this laptop, right now |
| 6 | Prototype | The live 5-page tour with REAL badges |
| 7 | Scalability | 1 → 3 datasets, pooled 0.896 → 0.935 |
| 8 | Impact | Live rehearsal: attack 0.947+ vs benign ≤ 0.014 |
| 9 | Business | CPU-only, read-only-first adoption, 2-command retraining |
| 10 | Presentation | Scripted runbook + every number traceable to a file |

**The one sentence to remember for the whole pitch:**

> *"CyberForecaster is a working, offline, human-in-the-loop attack FORECASTER:
> it predicts the next 2.5 minutes of attack pressure with calibrated
> uncertainty, maps it to ATT&CK stages, and hands the analyst evidence and a
> recommended action — every number on screen traceable to an artifact."*
