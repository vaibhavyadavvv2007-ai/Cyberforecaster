# 🛡️ CyberForecaster Battle Plan
### SIH26153 — Network Attack Forecasting · Internal Round: **Saturday, Sep 5, 2026**

> Mission: walk into the internal round with a working, offline, live-demo'd attack-forecasting system, a 7-minute story that lands, and answers to every jury question. This document is the single source of truth. Merge of our strategy + the ChatGPT blueprint, corrected against the real calendar and real dataset behavior.

---

## 0. The one-sentence thesis (everyone memorizes this)

> **"We don't classify traffic — we model how network state evolves over time and forecast an attack's progression before it completes, with every prediction explained."**

Everything below exists to make that sentence true and demonstrable.

---

## 1. Win conditions for a live-demo internal round

Judges in demo rounds reward, in order: (1) a demo that *runs*, (2) a story they can retell, (3) evidence of rigor, (4) confident Q&A. So:

| # | Win condition | Definition of done |
|---|---|---|
| W1 | Demo never crashes | Runs fully offline from one laptop; cached-predictions mode as fallback; rehearsed ≥2× on the actual machine |
| W2 | The forecast moment is visual | Probability timeline visibly climbs past threshold during the pitch |
| W3 | Rigor is visible | Benchmark table: Logistic vs LSTM vs Transformer(if ready) — F1/precision/recall/FPR, honest numbers, chronological split stated |
| W4 | Explainability is interactive | "WHY?" button reveals per-feature attribution on the live prediction |
| W5 | Q&A is pre-banked | All 15 questions in §8 answered by heart by ≥3 members |

**Anti-goal (REVISED Aug 29):** the original plan said "Streamlit wins Sep 5; React is for the national round." The team has since decided to move the frontend to **Next.js/TypeScript + a FastAPI backend** (`api/` wraps `src/` verbatim; `web/` is the frontend) — our frontend developer works fastest there and we have a backend person to wire it. Conditions attached: Streamlit stays untouched and demo-ready as the **fallback**, the timeline chart is the frontend's day-1 task, and Gate 2 (Sep 2) is a hard freeze. The fallback chain on demo day: Next.js → Streamlit → backup video → screenshot pack. `scripts/check_api.py` verifies the API reproduces the rehearsed numbers.

---

## 2. Calendar reality & the two hard gates

Your actual availability: **full days only Aug 30–31**, ~3h evenings otherwise. Event Sat Sep 5.

| Slot | Date | Type | Focus |
|---|---|---|---|
| S1 | Mon Aug 25 (eve) | 3h | Kickoff: repo setup, roles, download starts, study sprint U1–U2 begins |
| S2 | Tue Aug 26 (eve) | 3h | Data cleaning recipe + study sprint U3–U5 finish |
| S3 | Wed Aug 27 (eve) | 3h | Windowing pipeline works on ONE day-file |
| S4 | Thu Aug 28 (eve) | 3h | Logistic baseline trained + metrics table v0 |
| S5 | Fri Aug 29 (eve) | 3h | LSTM v1 training kicked off on Kaggle overnight |
| **S6** | **Sat Aug 30 (FULL)** | 8h+ | Integration day #1 → **GATE 1 (EOD): walking skeleton end-to-end** (CSV → windows → model → probability timeline in app). If missing: cut Transformer track permanently, switch to cached-mode strategy |
| **S7** | Sun Aug 31 (FULL) | 8h+ | K-step forecast head + attribution wired into app; MITRE mapping table drafted; benchmark experiments |
| S8 | Mon Sep 1 (eve) | 3h | CTU-13 secondary eval attempt (Tier 2); flagged-flows view |
| S9 | Tue Sep 2 (eve) | 3h | Polish pass → **GATE 2 (EOD): FEATURE/MODEL FREEZE.** Nothing new enters after this |
| S10 | Wed Sep 3 (eve) | 3h | Dress rehearsal #1 timed on demo laptop → record backup video same night |
| S11 | Thu Sep 4 (eve) | 3h | Dress rehearsal #2 → deck final → offline package test on second laptop → print screenshot pack |
| 🏁 | **Sat Sep 5** | event | Run-of-show §7 |

**Rule:** nothing critical is scheduled only in an evening slot. Evening slips are expected; weekend days absorb them.

---

## 3. Roles (6 members) — pair everything critical

| Role | Owns | Backed up by |
|---|---|---|
| **ML-A** (PyTorch #1) | Model ladder: logistic → LSTM → rollout head; Kaggle training runs | ML-B |
| **ML-B** (PyTorch #2) | Evaluation harness + explainability: metrics table, chronological-split guard, attribution | ML-A |
| **DE** — Data Eng | Download/cleaning/windowing pipeline; dataset documentation | Domain/Pitch |
| **BE** — Backend/Integration | App wiring, cached-predictions mode, offline packaging, model loading | FE/Product |
| **FE/Product** (designer) | Streamlit UX, charts, demo flow, deck visuals | BE |
| **Domain/Pitch** | Study-sprint lead → docs, MITRE mapping co-owner, demo script, Q&A bank | DE |

---

## 4. Study sprint — ALL the cybersecurity you need (~2 evenings, parallel to build)

You need **traffic literacy + attack taxonomy vocabulary**, not hacking skills. The model learns patterns from labels; you need enough understanding to design features, sanity-check outputs, and answer questions.

### Unit 1 — TCP/IP primitives (90 min)
Packets vs flows · 3-way handshake · flags SYN/ACK/FIN/RST/PSH/URG · ports (well-known ranges) · TTL · what NetFlow/IPFIX records are.
*Self-check: What does a SYN without ACK suggest? Why do scanners touch many ports on one host? What's a "flow record"?*

### Unit 2 — Attack families in CSE-CIC-IDS2018 (60 min)
One paragraph each, focus on *what it looks like in traffic*: FTP/SSH Brute-Force · Heartbleed · Botnet (Ares) · DoS (GoldenEye/Hulk/SlowHTTPTest) · DDoS (LOIC) · Web Attacks (XSS/SQLi/Brute-Force) · Infiltration (Metasploit via compromised DMZ host).
*Self-check: which families produce port-scans first? Which produce east-west internal connections? Which flood bandwidth?*

### Unit 3 — MITRE ATT&CK (45 min)
Tactics vs techniques · the five stages the PS names: Reconnaissance → Initial Access → Lateral Movement → Command & Control → Exfiltration · Lockheed-Martin kill chain (for Q&A flavor).
*Self-check: where do Botnet beacons sit? Where does SSH brute-force sit?*

### Unit 4 — Dataset semantics (45 min)
How CSE-CIC-IDS2018 was collected (testbed topology: attacker VLAN → firewall → servers; benign profile scripts), what the `Label` column means, why per-day files exist, CTU-13 scenario structure.
*Self-check: why must we split chronologically? What does class imbalance look like here?*

### Unit 5 — SOC vocabulary (30 min)
IDS vs IPS vs SIEM · precision/recall/false-positive-rate as SOC operators feel them · "decision support" framing.

**Explicitly SKIP (rabbit holes that waste your sprint):** penetration testing rooms, exploit development, malware reversing, firewall admin, certifications, deep Wireshark analysis. None of it is in the deliverable.

---

## 5. Locked technical decisions

### 5.1 Task framing (decided for a reason)
- Forecast **window-level malicious-progression probability** P(attack activity within next K=5 windows | last L=10 windows) **+ dominant attack stage** over the horizon.
- Why not "infiltration-only forecasting": the Infiltration class in CIC-IDS2018 has only dozens of samples — data-starved. Across-family progression keeps the story AND gives the model signal. Say this openly if asked; it reads as maturity, not evasion.
- Per-flow static classification is exactly what the PS rejects; window-level sequences are the differentiator.

### 5.2 Data
- **Primary:** CSE-CIC-IDS2018 (public AWS S3 `cse-cic-ids2018`, MachineGeneratedCSV per-day files). ~80 CICFlowMeter columns; use subset (§5.3).
- **Known mess (handled in starter-kit code):** inconsistent label spellings/casing, occasional duplicated header rows mid-file, NaN/inf in rate columns, malformed timestamps incl. epoch artifacts parsing as year 1970 (filtered by plausibility check), extreme imbalance.
- **Verified 26 Aug on real files:** this bucket's ML-ready CSVs contain **NO IP columns** (`Src IP`/`Dst IP` absent) — IP-based features degrade to 0 and the lateral-movement rule must rely on ports/timing/volume instead; Feb-14 file is truncated at 13:00 (brute-force only, no Heartbleed); benign background runs ~900+ flows/min so *shares* (e.g., auth-port share) get diluted — rule thresholds will need tuning against `validate_rules()` output (scheduled task, not a bug).
- **Priority pull order:** small attack-bearing day-files first (Botnet, DoS/Heartbleed, DDoS/BruteForce, Web-attack days + Infiltration day + one benign-heavy file). Run `python scripts/download_data.py --list` FIRST to see real sizes before pulling anything; curated list lives in `configs/data_sources.yaml`. Cap initial pull ≈ 2–3 GB.
- **Verify the attack↔day mapping yourself** against the bucket README/paper when listing — don't trust any summary blindly (including this doc).
- **Secondary:** CTU-13 (Stratosphere group, direct downloads) — used ONLY for the held-out generalization claim (train on CIC, evaluate one CTU scenario). Tier 2.

### 5.3 Windowing (the heart of the project)
- Sort flows by timestamp → bin into **60-second windows**.
- Per-window aggregate vector (~24 features): flow_count, bytes/packets sums+means, duration_mean, **flag ratios (SYN/ACK/FIN/RST/PSH)**, unique_dst_ports, unique_dst_ips, unique_src_ips, dst-port entropy, IAT mean/std, fwd/bwd byte ratio, mean packet size, small-packet ratio (+ label fractions for supervision only).
- Sequences: L=10 windows in → predict K=5 ahead. Label y_prog = attack fraction > 0 in any horizon window; y_stage = dominant stage across horizon (from flow labels).
- **Chronological split ONLY:** 70/15/15 by time, split at day boundaries, **purge sequences straddling splits** (overlapping windows leak otherwise — ChatGPT blueprint's most important correctness point).

### 5.4 Models
| Stage | Model | Notes |
|---|---|---|
| 0 | Logistic regression on flattened L×F features | PS-required benchmark; also your sanity floor |
| 1 | 2-layer LSTM (hidden 64) → multi-task heads | Trains on Kaggle T4/P100 easily; even 4–6GB local GPU fine |
| 2 | Temporal Transformer (2 layers, d=64) | **Only if Gate 1 passed early** |
- **Forecast head = direct multi-horizon:** outputs p̂(t+1…t+K) as a vector (teacher-forced labels), NOT recursive prediction-on-predictions. Simpler, stable, defensible ("risk trajectory"). Recursive-on-latent rollout = Tier 3 stretch.
- Imbalance: pos_weight in BCE; report PR curves alongside F1.
- **Explainability (one method, locked):** Captum IntegratedGradients on sequence input, aggregated over the time axis → per-feature importance for each prediction. Fallback: permutation importance on flattened features (precomputed for sample files). SHAP DeepExplainer optional garnish only.
- **MITRE mapping = documented rule table** (in `src/attack_mapping/mitre_mapper.py` + docs slide): e.g., high unique-dst-ports + high SYN ratio + low volume → Reconnaissance · auth-port bursts (21/22/3389) → Initial Access · growing internal-east-west connections → Lateral Movement · periodic low-volume beaconing to external → C2 · large outbound spikes → Exfiltration · volumetric floods → **DoS (displayed as its own category** — the kill-chain's Impact tactic isn't among the PS's five named stages; being explicit about this is a credibility win).
- Validate the table against the dataset's own labels per attack family; ship it as a slide.

### 5.5 App & packaging (offline-first)
- **Streamlit** single app: Upload/sample-select → Analyze → panels: Risk card, **probability timeline (history solid + forecast dashed/shaded)**, WHY bars, ATT&CK strip, flagged-flows table, Benchmark tab.
- **Cached-predictions mode:** precomputed results JSON per sample file → instant, deterministic demo even if the laptop hiccups. Mock-vs-real badge in UI until the real model is plugged in — honesty built into the product.
- Packaging: pinned requirements (torch CPU wheel locally, CUDA build on Kaggle), committed `.pt` weights, bundled few-MB parquet samples, tested cold-start on a clean machine Sep 4.

### 5.6 Cut lines (tiered, pre-agreed — no day-of debates)
- **Tier 1 MUST:** CSV → clean → windows → logistic baseline + LSTM → K-step timeline → attribution → MITRE strip → Streamlit → benchmark table → offline.
- **Tier 2 SHOULD:** PCAP ingest (thin Scapy path), packet-level features (TTL variance, window size, retransmissions), CTU-13 cross-dataset eval, Transformer.
- **Tier 3 WOW (cut first, no guilt):** GNN/graph views, recursive latent rollout, streaming ingestion, SOC simulator.
- **Never cut:** leakage-safe split, explainability, baseline comparison, backup video.

---

## 6. Risk register — triggers → actions

| Trigger | Action |
|---|---|
| Aug 27 EOD: windows still broken on real data | Drop to 5-min bins, single day-file; simplify feature set |
| Aug 30 EOD (Gate 1): no walking skeleton | Kill Transformer track permanently; wire app to cached outputs; all hands on integration |
| Sep 2 (Gate 2): LSTM ≤ logistic F1 | Pivot metric, honestly: report **early-warning lead time** (probability crosses threshold N windows before attack peak — temporal models usually win THIS); keep benchmark table truthful either way |
| Attribution slow at runtime | Precompute attributions for the three demo samples |
| Kaggle quota exhausted mid-week | Local GPU trains the small LSTM (it fits in 4–6GB); Kaggle reserved for Transformer attempts |
| Demo laptop dies / venue surprises | Second mirrored laptop + recorded video + printed screenshot pack |
| Anyone loses >1 day (exams etc.) | Role backups activate; ML pair absorbs; scope shrinks along Tier 3→2 order |

---

## 6.1 State of the rebuild — verified Thu Aug 28 night (READ BEFORE S5/S6)

Everything below is **measured, not estimated**, from the full 7-file rebuild after the correctness fixes (per-horizon-step labels, shared train-fitted transform, `Pkt Size Avg` column fix, `Infilteration` label fix).

**Data reality (7 files, 6.19M flows, 3172 windows, 3158 sequences / tr 2031 · va 428 · te 463):**
- Attack families present: DDoS-HOIC, DoS-Hulk, FTP/SSH brute, **Infilteration** (dataset's own misspelling — was silently unmapped, 161k flows), DoS-Slow*, DDoS-LOIC, Web attacks. **No Botnet, no port-scan family in these 7 files.**
- Test split (last 15% chronologically) = Feb 28 + Mar 1 → **almost entirely Infiltration**, an attack family ABSENT from train. This is an honest, brutal evaluation: it measures transfer to an unseen attack, and both models struggle. Say this out loud in the pitch — it's a feature of the evaluation, not an embarrassment.

**Benchmark (chronological test split, threshold picked on val under FPR≤5%), retrained Aug 28 late:**
| model | PR-AUC | precision | recall | FPR | note |
|---|---|---|---|---|---|
| Logistic (K per-step models) | 0.346 | 0.667 | 0.034 | 0.6% | its val threshold stayed conservative on test |
| LSTM (57k params, 0.23 MB, 0.25 ms/seq CPU) | **0.591** | **0.815** | 0.190 | **1.4%** | FPR budget transfers; high-precision SOC story |

The LSTM clearly beats the baseline on PR-AUC (+70%) at a defensible operating point. First training run this night was undertrained (early stop kept epoch-4 weights because per-epoch val AP on 428 sequences is noisy) — fixed by PATIENCE=25 + train AP printed per epoch (train AP 0.95, val 0.667, test 0.591). Q&A #13 cost numbers are above.

**What the model genuinely does (measured, for the pitch):**
- **Persistence forecasting works**: mid-attack anchors output 0.90-0.97 for high-volume attacks (DoS/HOIC/brute), and 0.87 for the Infiltration attack — a family ABSENT from training. Cross-family transfer of "attack continues" is real.
- **Diluted attacks are honest misses**: low-volume attacks (Slowhttptest-class, <30% of window flows) score low — the model reports low risk when attack traffic is a small share. Say this; it invites the 30s-bin improvement as roadmap.
- **Attack resumption is forecast**: when attack activity happened recently but is currently paused, the model outputs ~0.92 for the resumption — the honest version of "early warning" that exists in this data.
- **Pre-onset warning is impossible here** (flat ~0.52 base-rate from clean inputs) — see lead-time note below.

**Lead time (§6 pivot): currently 0 for BOTH models.** Test split holds **1** onset (one continuous attack), val holds 2; no pre-onset warning fired. **CONFIRMED by `scripts/diagnose_leadtime.py` (Aug 28):** pre-onset probabilities are flat ~0.52 (the base rate) at every horizon distance — the model has NO precursor signal to warn from, because CIC attacks are scripted and the 10 windows before an onset are ordinary benign traffic. Pre-onset warning is information-theoretically impossible on this data. Therefore:
- Do NOT fake a lead-time slide. The honest differentiators that DO exist: per-step forecast decay curves (t+1 vs t+5 accuracy), persistence/recovery forecasting during an ongoing attack, stage trajectory prediction, and the rule engine + attribution explainability.
- If we want a real lead-time number we need data where attacks have precursors (more day-files so onsets exist in val/test, or CTU-13 scenarios with scan→exploit sequences).

**Open decisions for S6 (Aug 30):**
1. More day-files (Tue Feb 13 brute-force, Thu Feb 22)? Adds sequences and onsets but does not change test composition (test stays last-15%).
2. 30-second bins: ~~doubles sequences (≈6.3k), still matches beaconing tempo. Cheap, one flag.~~ **A/B MEASURED Aug 29 — see §6.2. 30s wins on every threshold-independent metric.**
3. Rule-engine thresholds (13.6% agreement, dilution issue documented in mitre_mapper TUNING NOTES) — tune Sunday S7 against validate_rules(), then FREEZE.

**Known-forever limitations (say them before the jury asks):** no IP columns → lateral-movement rule abstains, C2 rule weaker; DoS shown outside the 5-stage chain on purpose.

## 6.2 30-second bins A/B — measured Fri Aug 29 (Gate 1 input)

Ran the full pipeline at `--bin-secs 30` (6192 windows, 6178 sequences / tr 4145 · va 881 · te 916 — 2× the 60s data), retrained BOTH models identically, then **restored the 60s artifacts** so the verified demo stayed untouched. Both result sets are preserved: `models/ab_60s_backup/` (= live demo) and `models/ab_30s/`.

| metric (chronological test split) | 60s bins | 30s bins | verdict |
|---|---|---|---|
| LSTM PR-AUC | 0.591 | **0.657** | +11%, threshold-independent — the fair comparison |
| LSTM val AP (best epoch) | 0.667 | **0.681** | better model selection too |
| LSTM precision / FPR @ operating point | 0.815 / 1.44% | **0.882 / 0.57%** | cleaner alerting story |
| LSTM recall @ operating point | 0.190 | 0.140 | low in both — a property of the FPR-budget threshold on the unseen-family test split, not the bin size |
| Logistic PR-AUC | 0.346 | 0.334 | baseline unaffected |
| train sequences | 2031 | **4145** | 2× supervision |

**Recommendation: switch to 30s.** To adopt (≈30 min): re-run the rebuild chain pointed at `data/processed_30s` (lead_time, demo cache, verify_state), update the 60s→"1 window = 30s" caption language everywhere (app captions say "1 window = 60s"), and re-verify with `scripts/check_api.py`. Decision belongs to Gate 1 (Aug 30 EOD) — after that, frozen either way.

---

## 7. Demo choreography — the 7-minute arc

**REVISED Aug 30:** the live attack segment landed and is now the centerpiece — two engines, real packets, real crossing (0.022 → 0.384 → 0.947 over three windows, verified). The timed run-of-show with exact commands, pre-flight checklist, and fallbacks lives in **`docs/DEMO_RUNBOOK.md`** (single source of truth for demo day). Summary: offline rigor first (~2 min: scenario forecast, WHY?, benchmarks), then `/live`: seeded-history narration → attacker's SYN scan (rule engine flags Recon in one window) → sustained UDP sweep (LSTM crosses at window 3, holds ~0.98) → attribution on the live prediction → honesty close. Original arc preserved below for the pitch backbone:


1. **0:00 Hook:** critical infrastructure gets probed continuously; static detectors raise alerts *after* the kill chain completes. NTRO is asking for forecasting.
2. **0:45 Thesis slide:** classification vs evolution diagram (from ChatGPT blueprint §1 — keep those two ASCII-ish graphics as slides).
3. **1:15 Architecture:** 3 blocks only — telemetry→temporal states→forecast(+why).
4. **2:00 LIVE:** dropdown → "Infiltration scenario (Feb 14 morning)" → ANALYZE → history timeline draws → hit **FORECAST** → animated curve climbs past threshold → risk card flips 🔴.
5. **3:30 WHY?** → attribution bars: "SYN activity, port diversity, IAT irregularity" — the model shows its work.
6. **4:00 ATT&CK strip:** Recon → Initial Access → **Lateral Movement** highlighted → C2.
7. **4:30 Rigor slide:** benchmark table + "chronological split, no leakage" line + CTU-13 held-out note (if Tier 2 landed).
8. **5:30 Roadmap:** React console, streaming ingestion, SIEM/SAHYOG-style integration — national-round vision.
9. **6:30 Close:** *"Detection tells you what happened. We forecast what happens next — and show you why."*
- Backup chain: cached mode → second laptop → recorded video → printed screenshots. Rehearse the handoff between them once.

---

## 8. Jury Q&A bank (own these — ≥3 members each)

1. **"Isn't this just a classifier?"** → Classification judges one observation in isolation. We consume a temporal sequence of network states and roll forward — the probability comes from the trajectory, not a snapshot. Our own benchmark table shows the delta.
2. **"Why call it a world model?"** → We learn state-transition dynamics P(S_{t+1}|S_t) over windowed network states and perform forward rollout over K steps — the PS's definition, implemented pragmatically.
3. **"Can it catch attacks it has never seen?"** → Honest: we evaluate held-out windows and (if Tier 2 landed) a cross-dataset CTU-13 family. We claim learned temporal progression, not zero-shot magic.
4. **"False positives?"** → Output is a probabilistic warning with explanations for analysts — decision support, not auto-blocking. We report FPR in the table because SOC operators care most about it.
5. **"Why LSTM and not Transformer/GNN?"** → Strong temporal baseline, lighter to validate under our constraint; same features as the logistic baseline so the comparison isolates temporal modelling. Transformer = roadmap.
6. **"Why should we trust the prediction?"** → Every prediction ships with per-feature attribution + the rule-based ATT&CK mapping table validated against labelled attacks.
7. **"What if it's wrong?"** → Analyst investigates flagged flows first; the cost asymmetry in cyber defence favours early probabilistic warnings over late certainty.
8. **"Data is synthetic/testbed — realistic?"** → It's the standard public benchmark (Canadian testbed with real tooling: LOIC, Metasploit, Ares); we're explicit about that limitation and name production telemetry (NetFlow/IPFIX) as the deployment input.
9. **"Privacy/legal?"** → We process flow metadata (counts, flags, ports, timings), never payload content — same data NetFlow exporters already produce.
10. **"Why offline?"** → PS requirement + sovereignty argument (NTRO context) + our demo reliability.
11. **"Why 60s windows?"** → Matches reconnaissance/beaconing tempo; configurable; sensitivity noted in docs.
12. **"DoS isn't in your five stages?"** → Correct — ATT&CK places flooding under Impact, outside the listed progression stages; we display it as its own category rather than forcing it into the chain.
13. **"Model size/latency?"** → [fill real numbers by Sep 3] MBs, sub-second inference on CPU — edge-deployable.
14. **"Split method?"** → Chronological with boundary purge; random shuffling would leak future into training — we refuse it even though it inflates numbers.
15. **"With 6 more months?"** → Packet-level features, graph-state representation, online learning drift handling, analyst feedback loop.

---

## 9. Post-win runway (Sep 5 → 20, SIH official submission)

- Portal needs: final idea title/abstract, **YouTube demo link field**, dataset link field, team details — assign ONE owner on Sep 5 night.
- Upgrade Streamlit → FastAPI + React console (your home stack — now worth the time).
- Add Tier-2 items: thin packet-level features, CTU-13 cross-dataset table.
- Produce the exact PS deliverables: GitHub repo cleaned, README, **≤2-page architecture doc**, **≤2-min demo video**, **≤5-slide technical presentation**.
- Rehearse the national pitch around the same arc — deeper rigor section.

---

## 10. Next 48 hours (start tonight)

1. **Tonight S1:** repo clone, environments, `python scripts/download_data.py --list`, start curated pull; study Units 1–2 begin (Domain/Pitch leads, everyone participates).
2. **Tomorrow S2:** DE finishes cleaning recipe on first file; ML pair reads starter notebook end-to-end; study Units 3–5 done.
3. **Exit criterion by Aug 26 EOD:** raw CSV → clean parquet on disk, everyone can define "window", "flow", "SYN ratio", "kill chain".
4. From there the calendar (§2) takes over. Gates decide cuts — not moods.
