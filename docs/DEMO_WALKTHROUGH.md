# DEMO WALKTHROUGH — every page, every panel, explained

**SIH26153 · CyberForecaster · internal demo 2026-09-05**

*A judge-style tour of the prototype. Each section: the screenshot, WHAT you are
looking at, WHY it exists, and WHAT to SAY while showing it. Screenshots live in
`docs/demo_screenshots/` — open them side by side with this document.*

**Demo order:** Forecast → Live → Analyze → Benchmarks → Datasets.
Everything runs on this laptop, offline, at `http://localhost:3000` (API at
`:8000`). If a judge asks "is this real?", the answer is always a badge on
screen or a file on disk.

---

## Page 1 — FORECAST (`/`) — the model's answer on real training data

### 1.1 Setup state — `01-forecast-setup.png`

**What you see:** A scenario picker with 9 named moments from CSE-CIC-IDS2018
(real captured attack days, Feb–Mar 2018), an alert-threshold slider (default
0.56), and a "Run forecast" button.

**Why it exists:** This page is the model's core capability in isolation — pick
a moment in history, and the model forecasts from the 10 windows BEFORE it.
The scenarios are named by what actually happened ("14 Feb 02:01 — Initial
Access onset", "23 Feb 04:30 — quiet baseline") so the audience knows the
ground truth before the model answers. The threshold slider shows the
operating point is a choice, not a magic number — and its default is labelled
"tuned on validation data" (never on test).

**Say:** *"These are real moments from the 2018 CIC attack dataset. I pick one,
and the model will forecast the NEXT 2.5 minutes from only what came before."*

### 1.2 Attack onset result — `02-forecast-result.png`

**What you see (top to bottom):**
- **Attack progression forecast** — a peak probability (49%) over the next
  5 windows, with a LOW/MEDIUM/HIGH uncertainty band, predicted stage
  ("Initial Access"), lead time in windows, and the threshold marker.
- **Progression over time** — a chart with three series: *Observed (ground
  truth)*, *Forecast (model output)*, and the threshold line. The forecast
  origin is before the attack starts.
- **ATT&CK progression** — the five MITRE ATT&CK tactics
  (Reconnaissance → Initial Access → Lateral Movement → C2 → Exfiltration)
  with the predicted stage highlighted ("peak 49%").
- **Per-step stage (state rollout)** — T+1…T+5 chips from the V3 world model:
  stage AND risk decoded from the model's internal forecast state at each
  step.
- **Independent rule engine** — its own verdict ("no rule matched") — an ML-free
  second opinion.
- **Why this prediction?** — Integrated Gradients feature attribution: the top
  6 features with signed contribution magnitudes (e.g. fin_ratio 2.41,
  rst_ratio 2.09), plus a plain-language sentence.

**Why it exists:** This is the whole thesis on one screen — not "is it an
attack?" but "how will the attack progress, at what confidence, driven by
which evidence." The ground-truth overlay lets a judge verify honesty
instantly; the attribution answers "why should I trust a neural network?"

**Say:** *"The model forecasts attack progression at 49% — under threshold, and
the uncertainty band says LOW confidence in escalation. Look at the
attribution: connection teardown and reset behaviour drove this forecast. No
black boxes."*

### 1.3 Quiet baseline — `03-forecast-quiet-baseline.png`

**What you see:** Same panels, scenario "quiet baseline". Peak 32%, LOW risk.

**Why it exists:** The false-alarm half of the story. A forecaster that cries
wolf is useless; showing the model staying calm on benign traffic is what
makes the attack-case credible.

**Say:** *"Same model, benign traffic: it stays low and calm. This is the
FPR 0.006 number from the benchmarks page, happening live."*

### 1.4 Attack underway — `04-forecast-lateral-movement.png`

**What you see:** Scenario "Lateral Movement underway" — predicted stage
**Lateral Movement**, peak 56% (right at the alert line).

**Why it exists:** Shows the model doesn't just detect "attack" — it names the
STAGE of the campaign, which changes what the analyst does (lateral movement
→ segment the network, not just block one IP).

**Say:** *"Now it's mid-campaign. The model says Lateral Movement — that tells
the analyst to look at east-west traffic and segment, not just quarantine the
original host."*

---

## Page 2 — LIVE (`/live`) — real packets from this laptop, right now

### 2.1 Idle state — `05-live-idle.png`

**What you see:** "Capture stopped" prompt, a "Start live capture" button, and
panels already populated from **seeded history** (recorded benign traffic from
the rehearsal): current forecast, live trajectory chart, Integrated Gradients
panel, Events list, feature evidence, decision support, observed windows.

**Why it exists:** The seeded history solves the cold-start problem honestly —
the model needs 10 windows (5 minutes) of history before it can forecast, so
the page boots with recorded REAL benign windows (labelled "Seeded history
(recorded benign)" on the chart legend) instead of showing an empty screen or
faking data.

**Say:** *"Live mode captures this machine's actual network traffic. It boots
from recorded benign history — clearly labelled — because the model needs 5
minutes of context before it can forecast."*

### 2.2 Capture running — `06-live-capturing.png`

**What you see:** "Capturing live network traffic", the interface name, a live
packet counter climbing (this screenshot: 441 packets and counting), a
countdown to the next 30-second window close, "18 seeded windows · model
loaded" confirmation, and the current forecast at 1% LOW risk.

**Why it exists:** This is the proof-of-real screen. The packet counter and
per-window countdown show the system is ingesting raw packets in real time
(scapy sniffing on the Wi-Fi interface), binning them into 30-second windows,
and re-forecasting after every bin. The honesty chain: seeded windows are
labelled seeded, live windows labelled live.

**Say:** *"This is happening right now — real packets from this laptop, every
30 seconds a new window, every window a new forecast. Benign traffic reads
1%."*

### 2.3 Active capture with all panels — `07-live-active-with-panels.png`

**What you see:** After ~2 minutes: 22 windows of history (18 seeded + live),
9,975 packets captured, forecast still LOW, and the trajectory chart showing
the seeded→live transition; below, the full evidence and decision-support
stack populated with REAL observed values.

**Why it exists:** The judge sees the complete loop: packets → windows →
features → forecast → explanation → recommendation, all within one screen
refresh cycle.

**Say:** *"From raw packets to a recommendation in under 30 seconds, entirely
on-device."*

### 2.4 Defender decision support — `08-live-decision-support.png`

**What you see:** The recommendation panel: header "peak 1% vs threshold 56% ·
0 steps above · MC band HIGH", a verdict badge (**MONITOR** — the lowest rung
of the MONITOR → INVESTIGATE → CONTAINMENT REVIEW → ESCALATE ladder), a
plain-language situation line, then **ranked recommended investigation
actions** with priority tags:
- P1 STAGE actions (audit east-west admin-port connections, check new
  host-to-host contacts)
- P1 EVIDENCE actions — tied to a specific feature ("verify dst_port_entropy:
  observed 0.4831 vs benign mean 6.3649, z=−2.621, suppressed")
- P2 MITRE actions — real mitigations pulled from the official MITRE ATT&CK
  STIX bundle (T1021 Remote Services: Audit / Disable or Remove Feature /
  Limit Access; T1072 Software Deployment Tools)
- An ATT&CK ENRICHMENT block listing the mapped techniques and their official
  mitigations, sourced "mitre-attack enterprise (STIX)".

**Why it exists:** This is the "tell the analyst what to do" clause of the
problem statement. The panel never says "blocked" — it ends with the
disclosure line: *"Decision support only: the system has NOT blocked, isolated
or modified anything. Every action is executed by a human analyst."*
Human-in-the-loop is enforced in the UI, not just claimed.

**Say:** *"Every recommendation is traceable: the evidence ones cite the exact
feature and z-score; the MITRE ones come from the official STIX bundle. And
the system never acts — the analyst does."*

### 2.5 Observed windows — `09-live-observed-windows.png`

**What you see:** A raw window table: timestamp, flows, packets, SYN ratio,
port count, rule-engine verdict, and a SOURCE column — every row marked
**live** or **seed**, with the footer "Seeded rows are recorded benign".

**Why it exists:** The deepest layer of the honesty system — you can audit the
exact data every forecast was made from, and nothing's origin is hidden.

**Say:** *"If a judge wants to audit us down to the packet-window level, this
table is it — every window's provenance is on screen."*

---

## Page 3 — ANALYZE (`/analyze`) — offline forensics on any capture

### 3.1 Upload state — `10-analyze-upload.png`

**What you see:** "Analyze a capture or flow export — PCAP/PCAPNG or flow CSV
(CIC-style or generic) · max 100 MB · detected by content, never by filename."

**Why it exists:** Extends the system from live monitoring to forensic
triage: a SOC analyst can drop yesterday's capture from any tool and get the
same pipeline. "Detected by content, never by filename" is a security posture
— untrusted uploads are parsed by magic bytes, never executed (plus a 100 MB
cap and temp-file cleanup).

**Say:** *"Same pipeline as live, but for captures you already have — and
uploaded files are parsed, never executed."*

### 3.2 Results — `11-analyze-results.png` (54 MB, 150,000-row CIC CSV slice)

**What you see:**
- **Detected input**: "150,000 rows · 1143 × 30s windows · 1134 forecasts",
  detected as `cic-flow-csv` at 86% confidence, with matched columns listed
  and **missing columns honestly declared** ("missing: Src IP, Src Port, Dst
  IP" → "Features this source cannot provide (reported, never filled with
  fake zeros): unique_dst_ips, unique_src_ips").
- **Forecast at end of capture** with MC-dropout uncertainty (band MEDIUM,
  max σ across steps shown).
- **Forecast trajectory through the capture** — one dot per anchor window,
  with the caption "each point is a separate forecast made from the 10 windows
  ending at that timestamp — the model reacting as the capture progresses."
- **Feature evidence** (16 features): observed vs benign TRAIN baseline, p99,
  z-score, status (normal / elevated / suppressed), and attribution.
- **Defender decision support** — same engine as live.

**Why it exists:** Three judge-killers answered on one screen: (1) scale —
150k flows processed in seconds; (2) schema honesty — the CSV has no IP
columns and the system SAYS so instead of silently zero-filling; (3) the
trajectory chart is 1,134 independent forecasts, not one prediction stretched
across time.

**Say:** *"A 54-megabyte flow export, schema-detected by its bytes. Note what
it says it CANNOT know — this CSV has no IP columns, so those features are
reported unavailable, never faked. That's our honesty contract."*

---

## Page 4 — BENCHMARKS (`/benchmarks`) — every number, verbatim

### 4.1 Headline + comparison — `12-benchmarks-top.png`

**What you see:** "Model performance" card for the LSTM forecaster (F1 0.241,
Recall 0.140, Precision 0.882, FPR 0.006), a bar comparison vs the logistic
baseline (PR-AUC 0.333 vs 0.656), the per-horizon decay chart (PR-AUC by
t+1…t+5 for both models), and the honest lead-time table (0.0 min — with the
explanation that CIC-2018 attacks start abruptly, so offline onset lead time
is not claimable).

**Why it exists:** Establishes the deployed model's numbers WITH the baseline
in the same view, and the recall/FPR trade-off visible: high precision, low
FPR, low recall — by design (high-precision early warning, not per-window
detection). The decay chart answers "how far ahead can you actually see?"

**Say:** *"Precision 0.882 at a 0.6% false-positive rate — we deliberately
built for few, high-quality warnings. And we show where forecasting decays:
each step out loses a little accuracy, honestly charted."*

### 4.2 Detailed results + multi-dataset — `13-benchmarks-detailed-multidataset.png`

**What you see:** The full model table served verbatim from training
artifacts, including:
- lstm forecaster 0.657 / logistic baseline 0.333 (the V1 story)
- **multidataset v1 · pooled 0.896** (CIC2018+UNSW), and per-dataset rows
- **multidataset v2 · pooled 0.935** (CIC2018+UNSW+CTU-13), with
  **ctu13 0.992 in-domain**, cic2018 0.215, unsw 1.000
- cross-dataset zero-shot rows ("cic2018+unsw_nb15+ctu13 → ctu13", etc.)

**Why it exists:** The scalability evidence AND the honest-limitation
evidence in one table: pooling three networks IMPROVED the pooled forecaster
(0.896 → 0.935) and CTU-13 botnet forecasting is near-perfect (0.992), while
CIC2018 in-domain degrades (0.657 → 0.215) — the 9-feature
capability/precision trade-off, disclosed with numbers. UNSW's 1.000 is on a
degenerate all-attack test split — also disclosed. Below, per-step tables for
every model with `_per_step` data.

**Say:** *"More networks made the pooled model better — 0.896 to 0.935 — and
botnet C2 forecasting hits 0.992. We also show where it hurts: single-network
precision on CIC2018 drops. We could hide that; we don't."*

---

## Page 5 — DATASETS (`/datasets`) — the data platform

### 5.1 Registry — `14-datasets-registry.png`

**What you see:** "Dataset registry — every registered dataset with its live
on-disk status · a missing dataset is reported as missing, never as zero or
fake." Seven registered datasets: **cic2018 READY (7 files), ctu13 READY
(7 files — 13 scenarios, 7 extracted so far, partial build disclosed),
unsw_nb15 READY (4 files)** — and four honestly **NOT_DOWNLOADED**
(cic2017, ciciot2023, darpa, lanl), each with modality, version, file count,
and a download link.

**Why it exists:** This is the scalability architecture made visible — an
adapter registry behind one canonical 48-feature schema. A dataset is either
READY with files on disk or NOT_DOWNLOADED; nothing is faked. The footer
states the platform rule: "each is adapted separately — never blindly
concatenated."

**Say:** *"Three datasets are wired and live; four more are registered with
honest statuses. Adding a dataset = writing one adapter against the canonical
schema — that's how we went from one network to three in a day."*

---

## The demo in one breath

> Forecast: the model predicts progression + stage + evidence on real attack
> moments. Live: real packets from this laptop → forecast every 30 s with
> ranked, MITRE-backed recommendations and zero automated actions. Analyze:
> any capture, schema-detected by bytes, missing features declared not faked.
> Benchmarks: every number verbatim, including our negative results. Datasets:
> an adapter registry that scales to new networks honestly.

**If anything breaks mid-demo:** every page degrades gracefully with an
honest error card, and the numbers on Benchmarks come from files on disk —
the fallback story is always "the artifacts are real and inspectable."
