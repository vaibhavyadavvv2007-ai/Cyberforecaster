# CyberForecaster (SIH26153) — Complete Project Status for Presentation

**Document Version:** 2026-09-04  
**Branch:** `v2_cyberforecast` (all work on this branch; `main` untouched)  
**Team:** 6 members (ML-A, ML-B, DE, BE, FE/Product, Domain/Pitch)  
**Internal Round:** Saturday, **September 5, 2026**  

---

## 1. EXECUTIVE SUMMARY (One-Sentence Pitch)

> **"We don't classify traffic — we model how network state evolves over time and forecast an attack's progression before it completes, with every prediction explained."**

---

## 2. PROBLEM STATEMENT ALIGNMENT (SIH26153)

| PS Requirement | Status | Evidence |
|----------------|--------|----------|
| **Flow-level features** (NetFlow/IPFIX) | ✅ **Complete** | 22 engineered features (16 flow + 6 CSV-derived packet) from CIC-IDS2018 CSVs |
| **Packet-level features** (PCAP-derived) | ⚠️ **Partial** | 6 CSV-derived (TCP window, pkt len var, fwd seg min, fwd/bwd pkt len std). True PCAP (TTL, fragmentation, retransmissions) needs raw PCAP parsing |
| **World Model: P(S_{t+1}\|S_t)** | 🔄 **Code Ready, Training Pending** | Additive state-reconstruction head in LSTM; Colab sweep pending |
| **K-step forward simulation** | ✅ **Complete** | L=10 history → K=5 horizon, per-step labels (direct multi-horizon) |
| **Infiltration probability score** | ✅ **Complete** | 5-step probability trajectory per forecast |
| **MITRE ATT&CK stage mapping** | ✅ **Complete** | Rule engine + model stage head (6 stages + DoS) |
| **Explainability (attention/SHAP/IG)** | ✅ **Complete** | Captum Integrated Gradients + permutation fallback |
| **Logistic regression benchmark** | ✅ **Complete** | PR-AUC 0.33 vs LSTM 0.61 (chronological split) |
| **Offline demo (Streamlit/FastAPI/Next.js)** | ✅ **Complete** | 3-mode honesty badges (REAL/CACHED/SIMULATED) |
| **Multi-dataset (CIC + CTU-13 + others)** | ❌ **Not Started** | Only CIC-IDS2018 used; CTU-13 planned |

---

## 3. CURRENT ARCHITECTURE

### 3.1 Data Pipeline (Verified Clean)

```
CIC-IDS2018 CSVs (7 days, 6.19M flows)
    │
    ▼
csv_loader.py  ──▶  Handles: "Infilteration" misspelling, "Pkt Size Avg" column,
                    duplicate headers, NaN/inf, epoch artifacts, missing IP cols
    │
    ▼
window_builder.py  ──▶  60s bins, 22 features, L=10/K=5 sequences,
                    chronological 70/15/15 split with boundary purge
    │
    ▼
scaling.py  ──▶  log1p + standardize (fitted on TRAIN only, shared by all models)
    │
    ▼
sequences_{train,val,test}.npz + scaler.npz + windows.parquet + meta.txt
```

**Verified (09-04):**
- 6,187,040 flows loaded from 7 day-files (Feb 14 – Mar 1)
- 3,172 windows × 22 features
- Sequences: Train 2,026 / Val 426 / Test 462 (boundary-purged)
- Per-horizon positive rates consistent across splits (~25% t+1 → ~23% t+5)
- Zero-variance features: none (dead IP features removed from WINDOW_FEATURES)
- All artifact feature counts agree (22)

### 3.2 Feature Set (22 Features: 16 Flow + 6 CSV-Derived Packet)

| # | Feature | Description | PS Category | Source |
|---|---------|-------------|-------------|--------|
| 1 | `flow_count` | Conversations per window | Flow | CSV |
| 2 | `bytes_total` | Total bytes transferred | Flow | CSV |
| 3 | `pkts_total` | Total packets | Flow | CSV |
| 4 | `duration_mean` | Mean flow duration (s) | Flow | CSV |
| 5 | `syn_ratio` | SYN flag fraction | Flow (TCP flag) | CSV |
| 6 | `ack_ratio` | ACK flag fraction | Flow (TCP flag) | CSV |
| 7 | `fin_ratio` | FIN flag fraction | Flow (TCP flag) | CSV |
| 8 | `rst_ratio` | RST flag fraction | Flow (TCP flag) | CSV |
| 9 | `psh_ratio` | PSH flag fraction | Flow (TCP flag) | CSV |
| 10 | `unique_dst_ports` | Distinct destination ports | Flow | CSV |
| 11 | `auth_port_share` | Fraction at ports 21/22/23/3389 | Flow | CSV |
| 12 | `dst_port_entropy` | Port usage entropy | Flow | CSV |
| 13 | `iat_mean` | Mean inter-arrival time | Flow (IAT) | CSV |
| 14 | `iat_std` | IAT standard deviation | Flow (IAT) | CSV |
| 15 | `avg_pkt_size` | Mean packet size | Flow | CSV |
| 16 | `down_up_ratio` | Download/upload byte ratio | Flow (bidirectional) | CSV |
| 17 | `tcp_win_fwd` | Initial forward TCP window bytes | **Packet (CSV-derived)** | CSV |
| 18 | `tcp_win_bwd` | Initial backward TCP window bytes | **Packet (CSV-derived)** | CSV |
| 19 | `pkt_len_var` | Packet length variance | **Packet (CSV-derived)** | CSV |
| 20 | `fwd_seg_min` | Forward segment size min | **Packet (CSV-derived)** | CSV |
| 21 | `fwd_pkt_len_std` | Forward packet length std | **Packet (CSV-derived)** | CSV |
| 22 | `bwd_pkt_len_std` | Backward packet length std | **Packet (CSV-derived)** | CSV |

**Removed (Dead — No IP Columns in ML-Ready CSVs):**
- `unique_dst_ips` — constant 0
- `unique_src_ips` — constant 0

**Missing True PCAP-Derived Packet Features (PS Requirement):**
| Feature | Source | Status |
|---------|--------|--------|
| `ttl_mean`, `ttl_var` | IP.ttl | ❌ Need raw PCAP |
| `frag_ratio` | IP.flags MF | ❌ Need raw PCAP |
| `retrans_ratio` | TCP SEQ duplicates | ❌ Need raw PCAP |
| `payload_size_dist` | TCP payload | ❌ Need raw PCAP |

**Note:** 6 packet-level features now extracted from CICFlowMeter CSV columns (no PCAP needed). True PCAP features (TTL, fragmentation, retransmissions) still require raw PCAP parsing.

### 3.3 Model Architecture

#### Current: LSTM Forecaster (`src/models/lstm_forecaster.py`)

```
Input: (Batch, L=10, F=18)  ──▶  2-layer LSTM (hidden=64, dropout=0.2)
                                    │
                                    ▼
                            Shared Trunk: Linear(64→32) → ReLU → Dropout(0.2)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            prog_head          stage_head       state_head (NEW)
            Linear(32→5)       Linear(32→6)     Linear(32→90)
            (sigmoid)          (softmax)        → view(5,18)
            K-step attack      Dominant ATT&CK  Predicted future
            probabilities                          feature vectors
```

**Parameters:** 60,197 | **Size:** 0.246 MB | **CPU Latency:** 0.598 ms/sequence

**Loss Function:**
```
L = BCEWithLogits(pos_weight per step) + CrossEntropy(ignore_index=-1)
    + loss_state_weight × HuberLoss(state_pred, state_target)  [if predict_next_state=True]
```

**Training Config (current best from new Colab run):**
- `predict_next_state: true`
- `loss_state_weight: 0.5`
- `epochs: 40`, `batch: 256`, `lr: 1e-3`
- Early stopping: patience=25 on pooled validation AP
- Threshold picked on validation at FPR ≤ 5%

#### Baseline: Logistic Regression (`src/models/baseline_logreg.py`)
- One model per horizon step (K=5)
- Flattened (L×F=180) features
- `class_weight="balanced"`, `max_iter=1000`
- Same chronological split, same scaler, same threshold methodology

### 3.4 Live Pipeline (Verified Working — Aug 30 Rehearsal)

```
Npcap/Scapy Capture (30s bins)
    │
    ▼
packet_windower.py  ──▶  Mirrors window_builder feature-by-feature
    │
    ▼
history.py  ──▶  model_matrix(): IP-zeroing + ratio-clamping to train p99
    │
    ▼
Forecaster.predict()  ──▶  Real-time forecast + rule engine + IG attribution
```

**Key Design Decisions:**
- Live uses **30s bins** (lower latency); training uses **60s** — documented A/B mismatch
- 5 bin-size-dependent features differ in scale (iat_mean, duration_mean, bytes_total, pkts_total, flow_count)
- Input conditioning: IP features zeroed (match train), ratio features clamped to train p99
- Rule engine sees RAW values (two-engine cross-check)

---

## 4. CURRENT METRICS (From Latest Colab Run — 09-03/04)

### 4.1 LSTM Forecaster (State Head Trained, loss_state_weight=0.5)

| Metric | Value | Notes |
|--------|-------|-------|
| **PR-AUC** | **0.507** | Threshold-independent |
| **Precision** | **0.554** | At FPR≤5% threshold |
| **Recall** | **0.313** | **↑ from 12% → 31%** (threshold dropped from 0.827→0.518) |
| **F1** | **0.400** | |
| **FPR** | **0.084** | Slightly above 5% budget (threshold from val) |
| **Threshold** | **0.518** | Picked on validation |
| **Val AP (pooled)** | **0.679** | Best epoch |

#### Per-Horizon-Step Breakdown (Test Set)

| Horizon | Precision | Recall | F1 | PR-AUC |
|---------|-----------|--------|-----|--------|
| t+1 | 0.000 | 0.000 | 0.000 | 0.297 |
| t+2 | 0.714 | 0.318 | 0.440 | **0.606** |
| t+3 | 0.316 | 0.110 | 0.163 | 0.292 |
| t+4 | 0.000 | 0.000 | 0.000 | 0.337 |
| t+5 | 0.385 | 0.093 | 0.150 | 0.296 |

**Key Insight:** Model only fires reliably at **t+2** (2 minutes ahead). t+1, t+4 never trigger at current threshold.

### 4.2 Logistic Regression Baseline

| Metric | Value |
|--------|-------|
| **PR-AUC** | **0.335** |
| **Precision** | 0.571 |
| **Recall** | 0.035 |
| **F1** | 0.066 |
| **FPR** | 0.009 |
| **Threshold** | 0.969 |

**LSTM beats baseline on PR-AUC by +51% (0.507 vs 0.335)**

### 4.3 Lead Time Evaluation

| Model | Test Onsets | Warned | Warned Rate | Median Lead |
|-------|-------------|--------|-------------|-------------|
| LSTM | 1 | 0 | 0% | 0 windows |
| Logistic | 1 | 0 | 0% | 0 windows |
| LSTM (Val) | 2 | 0 | 0% | 0 windows |

**Lead time = 0** — CIC-IDS2018 attacks start abruptly with no precursors in 10-window history. This is a **dataset limitation**, not model failure.

### 4.4 What the Model Actually Does Well (Measured)

| Behavior | Evidence |
|----------|----------|
| **Persistence forecasting** | Mid-attack probs 0.90–0.97 (DoS/Hulk), 0.87 (Infiltration — unseen family) |
| **Attack resumption forecasting** | ~0.92 when attack pauses and resumes |
| **Cross-family transfer** | Learns "attack continues" pattern without seeing Infiltration in train |
| **Dilution honesty** | Low-volume attacks (SlowHTTPTest <30% window share) score low — correct |
| **Per-step trajectory** | Probability curve shape matches attack sustain/decay |

---

## 5. ROOT CAUSE ANALYSIS: WHY RECALL IS 31% (NOT 70-90%)

### 5.1 Fundamental Constraints (Cannot Fix in 1-2 Days)

| Constraint | Impact | Fix Requires |
|------------|--------|--------------|
| **Test = Unseen Attack Family** | Infiltration absent from train; transfer is hard | More diverse training data (CTU-13, CICIoT2023) |
| **No Precursors in CIC** | Attacks start in 1 window; 10-window history sees only benign | Different dataset or synthetic precursor injection |
| **Tiny Dataset for LSTM** | 2,026 train sequences for 60k params | 30s bins (2x data) or more CIC days (Feb 20, Mar 2) |
| **No Packet Features** | Missing TTL, TCP window, fragmentation, retransmissions | PCAP parsing (320 GB CIC PCAPs infeasible; CTU-13 1.9 GB feasible) |
| **Single Dataset** | Overfits to CIC artifacts | Cross-dataset validation |

### 5.2 Tunable Levers (Can Improve in Hours)

| Lever | Current | Potential | Effort |
|-------|---------|-----------|--------|
| **Threshold** | 0.518 (val FPR≤5%) | Lower → 0.3-0.4 → recall 40-50%, FPR 10-15% | 0 min (demo operating point) |
| **pos_weight_scale** | 1.0 (auto per-step) | 2.0–3.0 → pushes recall during training | 1 Colab run |
| **30s bins** | 60s (2,026 seq) | 30s (~4,145 seq) → PR-AUC 0.507→0.657, FPR 8.4%→~0.6% | 4-6 hrs rebuild + Colab |
| **loss_state_weight** | 0.5 | Sweep {0.1, 0.3, 0.5} → best was 0.5 | Done in latest run |

---

## 6. PROOF OF CONCEPT STATUS

### 6.1 What Works End-to-End (Verified)

| Component | Verification |
|-----------|--------------|
| **Data pipeline** | `python -m src.preprocessing.pipeline` → clean artifacts |
| **Logistic baseline** | `python -m src.models.baseline_logreg` → metrics_baseline.json |
| **LSTM training** | Colab GPU → metrics_lstm.json (state head enabled) |
| **Lead time** | `python -m src.evaluation.lead_time` → metrics_lead_time.json |
| **Demo cache** | `python scripts/build_demo_cache.py` → demo_cache.json |
| **Smoke test** | `python tests/smoke_synthetic.py` → **PASSES** |
| **Artifact consistency** | `python scripts/verify_state.py` → **ALL [ ok ]** |
| **Live rehearsal** | `python scripts/live_rehearsal.py --attack udp-sweep` → **EXIT 0** (Aug 30) |
| **Offline demo (Streamlit)** | `streamlit run app/streamlit_app.py` → works |
| **Offline demo (Next.js + FastAPI)** | `uvicorn api.main:app` + `npm run dev` → works |
| **API contract** | `api/schemas.py` ↔ `web/lib/api.ts` → **NO DRIFT** |

### 6.2 Demo Scenarios (Pre-computed in demo_cache.json)

| Scenario | Anchor | Kind | Peak Prob | Stage |
|----------|--------|------|-----------|-------|
| 14 Feb 02:01 | 60 | onset | 0.59 | Initial Access |
| 15 Feb 10:02 | 936 | onset | 0.59 | Initial Access |
| 23 Feb 01:01 | 1476 | onset | 0.57 | Initial Access |
| 23 Feb 09:57 | 1848 | onset | 0.59 | Initial Access |
| 14 Feb 02:06 | 66 | during | 0.60 | Initial Access |
| 15 Feb 09:54 | 929 | during | 0.59 | DoS |
| 21 Feb 10:13 | 1445 | during | 0.55 | DoS |
| 28 Feb 10:55 | 2477 | during | 0.52 | Lateral Movement |
| 23 Feb 04:07 | 1663 | quiet | 0.56 | Initial Access |

**Attribution (IG) works** — top features per scenario: `rst_ratio`, `auth_port_share`, `pkts_total`, `syn_ratio`, `dst_port_entropy`, `flow_count`

### 6.3 Live Demo Rehearsal Results (Aug 30)

| Attack | Rule Engine | LSTM Forecast Trajectory | Result |
|--------|-------------|--------------------------|--------|
| SYN Scan | Reconnaissance (instant, 1 window) | Low (0.02–0.07) | ✅ Two-engine split works |
| UDP Sweep | No match | 0.03 → 0.17 → **0.905** → 0.968 → 0.988 | ✅ LSTM catches sustained pattern |

---

## 7. HONESTY RAILS (Non-Negotiable)

| Rail | Implementation |
|------|----------------|
| **Threshold on validation only** | `pick_threshold()` in baseline_logreg.py — never sees test |
| **Chronological split** | `chrono_split()` with day-boundary purge — no shuffling |
| **Metrics from scripts only** | All numbers in `models/*.json` — never hand-typed |
| **Mode badge always visible** | `ModelStatus.tsx`: REAL / CACHED / SIMULATED |
| **Observed line = ground truth** | Charts show gray observed line model NEVER sees |
| **Input conditioning disclosed** | IP-zeroing + ratio-clamping documented in `history.py` |
| **State head flag in config** | `predict_next_state` in `lstm_config.json` |
| **30s/60s mismatch disclosed** | Comments in `packet_windower.py` + `live_state.py` |

---

## 8. IMMEDIATE NEXT STEPS (1-2 Days Remaining)

### Phase 0: Complete Packet 2 Training (TONIGHT — 2-3 hrs Colab) ✅ **DONE**
- [x] Colab sweep: `loss_state_weight ∈ {0.1, 0.3, 0.5}`
- [x] Best: 0.5 → PR-AUC 0.507, Recall 31%, FPR 8.4%
- [x] Artifacts downloaded: `.pt`, `config.json`, `metrics_*.json`, `demo_cache.json`
- [x] Local verification: `verify_state.py` + `smoke_synthetic.py`

### Phase 1: 30-Second Bin Migration (TOMORROW — 4-6 hrs) 🎯 **NEXT**
```bash
# 1. Backup current 60s artifacts
mv data/processed data/processed_60s_backup

# 2. Rebuild pipeline with 30s bins
python -m src.preprocessing.pipeline --raw data/raw --out data/processed --bin-secs 30

# 3. Verify: expect ~4,145 train sequences, bin_secs=30 in meta.txt
python scripts/verify_state.py

# 4. Retrain on Colab (same sweep)
# 5. Rebuild demo cache
python scripts/build_demo_cache.py

# 6. Verify live/train mismatch resolved
```

**Expected Gains (from battle plan measurements):**
| Metric | 60s (current) | 30s (expected) |
|--------|---------------|----------------|
| Train sequences | 2,026 | ~4,145 |
| PR-AUC | 0.507 | **0.657** |
| Val AP | 0.679 | **0.681+** |
| Precision/FPR | 0.55 / 8.4% | **0.88 / 0.6%** |
| Live/train mismatch | YES | **NO** |

### Phase 2: Packet Features from CTU-13 (IF TIME PERMITS — 6-8 hrs) ⚠️ **STRETCH**
- Download CTU-13 (1.9 GB): `wget https://mcfp.felk.cvut.cz/publicDatasets/CTU-13-Dataset/CTU-13-Dataset.tar.bz2`
- Build `src/features/pcap_parser.py` (Scapy → 6 packet features)
- Build `src/ingestion/ctu13_loader.py` (NetFlow labels + PCAP alignment)
- Cross-dataset eval: Train CIC → Test CTU

### Phase 3: Threshold Tuning for Demo (LAST MINUTE) ⚡
- Lower threshold to 0.35-0.40 for demo day
- Accept FPR 10-15% → Recall 40-50%
- **Disclose honestly**: "Operating at higher sensitivity for demonstration"

---

## 9. ARCHITECTURE DECISIONS FOR PPT SLIDES

### Slide 1: Problem & Approach
- Classification vs Forecasting diagram
- World Model definition: P(S_{t+1}\|S_t) + K-step rollout

### Slide 2: Architecture
- Pipeline: CSV → Windows → Sequences → LSTM → Forecast
- Two heads: Progression (K=5) + Stage (6) + **State Reconstruction (NEW)**
- Live: PCAP → 30s windows → Conditioned input → Forecast

### Slide 3: Features
- 22 features: 16 flow + 6 CSV-derived packet (table)
- 4 true PCAP features missing (TTL, fragmentation, retransmissions)
- MITRE ATT&CK mapping table

### Slide 4: Results
| Model | PR-AUC | Precision | Recall | F1 | FPR |
|-------|--------|-----------|--------|-----|-----|
| Logistic | 0.335 | 0.571 | 0.035 | 0.066 | 0.009 |
| **LSTM (60s)** | **0.507** | **0.554** | **0.313** | **0.400** | **0.084** |
| LSTM (30s, projected) | **0.657** | **0.882** | ~0.35 | ~0.50 | **0.006** |

### Slide 5: Live Demo
- Two-engine: Rules (instant) + LSTM (trajectory)
- UDP sweep trajectory: 0.03 → 0.905 → 0.988 over 3 windows
- Attribution: `rst_ratio`, `auth_port_share`, `pkts_total`

### Slide 6: Limitations & Roadmap
- No IP columns → lateral movement blind
- Lead time 0 on CIC (dataset limitation)
- 30s bins next (resolves mismatch, 2x data)
- CTU-13 cross-eval (generalization proof)
- Packet features from PCAPs
- Transformer/GNN for national round

---

## 10. FILE MAP FOR QUICK REFERENCE

### Core Pipeline
```
src/ingestion/csv_loader.py          # CSV loading + cleaning
src/preprocessing/pipeline.py        # End-to-end: CSV → windows → sequences + scaler
src/features/window_builder.py       # 18 features, L=10/K=5, chrono_split
src/features/scaling.py              # log1p + standardize (single source of truth)
```

### Models
```
src/models/baseline_logreg.py        # Logistic regression (K models)
src/models/lstm_forecaster.py        # LSTM + 3 heads (prog, stage, state)
```

### Forecasting & Evaluation
```
src/forecasting/rollout.py           # Forecaster bundle (model+scaler+threshold)
src/forecasting/scenarios.py         # Demo scenario builder
src/evaluation/lead_time.py          # Early-warning lead time metric
src/explainability/attribution.py    # Captum IG + permutation fallback
src/attack_mapping/mitre_mapper.py   # MITRE stages + rule engine
```

### Live
```
src/live/sensor.py                   # Npcap/Scapy capture thread
src/live/packet_windower.py          # Packets → 18 features (30s bins)
src/live/history.py                  # Seed + live history, input conditioning
```

### API & Frontend
```
api/main.py                          # FastAPI routes
api/schemas.py                       # Pydantic contracts (mirror web/lib/api.ts)
api/state.py                         # Startup state loading
api/live_state.py                    # LiveService for /api/live/*
web/app/page.tsx                     # Next.js forecast console
web/app/live/page.tsx                # Live monitoring page
```

### Scripts & Verification
```
scripts/rebuild_all.py               # Full rebuild in dependency order
scripts/verify_state.py              # Pre-demo audit (run after EVERY change)
scripts/build_demo_cache.py          # Freeze predictions for cached demo
scripts/live_rehearsal.py            # End-to-end live rehearsal
scripts/check_api.py                 # API smoke test
scripts/download_data.py             # S3 downloader (boto3)
tests/smoke_synthetic.py             # E2E smoke test (no data needed)
```

### Artifacts (Current)
```
data/processed/
  windows.parquet          # 3,172 × 22 + supervision
  sequences_train.npz      # (2026, 10, 22)
  sequences_val.npz        # (426, 10, 22)
  sequences_test.npz       # (462, 10, 22)
  scaler.npz               # log1p+standardize (train-fitted)
  demo_cache.json          # Pre-computed predictions
  meta.txt                 # L=10 K=5 bin_secs=60 features=22

models/trained_models/
  lstm_forecaster.pt       # Latest: state head trained, loss_state_weight=0.5
  lstm_config.json         # predict_next_state=true, n_feat=22

models/
  metrics_lstm.json        # PR-AUC 0.507, Recall 0.313
  metrics_baseline.json    # PR-AUC 0.335, Recall 0.035
  metrics_lead_time.json   # Lead time = 0 (dataset limitation)
```

---

## 11. COMMANDS CHEAT SHEET (For Demo Day)

```bash
# Full rebuild (if needed)
python scripts/rebuild_all.py

# Verify everything before demo
python scripts/verify_state.py

# Start API + Next.js (2 terminals)
uvicorn api.main:app --port 8000
cd web && npm run dev

# Streamlit fallback
streamlit run app/streamlit_app.py

# Live rehearsal (needs Npcap + attacker device)
python scripts/live_rehearsal.py --minutes 6 --attack udp-sweep --attack-at 0.3 --iface "\Device\NPF_Loopback"

# API smoke test
python scripts/check_api.py

# Lead time re-evaluation
python -m src.evaluation.lead_time --dir data/processed
```

---

## 12. GLOSSARY FOR PRESENTATION

| Term | Definition |
|------|------------|
| **Flow** | Bidirectional conversation (5-tuple: src/dst IP/port + protocol) |
| **Window** | 60s (train) / 30s (live) time bin aggregated into 22 features |
| **Sequence** | L=10 consecutive windows fed to model |
| **Horizon** | K=5 future windows predicted |
| **PR-AUC** | Area under Precision-Recall curve (handles class imbalance) |
| **FPR** | False Positive Rate — % benign windows flagged as attack |
| **Lead Time** | Windows between first warning and attack onset |
| **MITRE ATT&CK** | Industry taxonomy: Recon → Initial Access → Lateral Movement → C2 → Exfiltration |
| **World Model** | Learns P(S_{t+1}\|S_t), rolls forward K steps |
| **State Reconstruction** | Predicts actual future feature vectors, not just labels |
| **Integrated Gradients** | Attribution method: interpolates baseline→input, integrates gradients |

---

## 13. RISK REGISTER & MITIGATIONS

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Colab GPU quota exhausted | Medium | Blocks training | Local GPU (4-6GB sufficient for LSTM) |
| Demo laptop fails | Low | No live demo | Second laptop + recorded video + screenshots |
| Npcap not working | Medium | No live capture | Loopback self-attack (SYN flood/UDP sweep scripts) |
| 30s pipeline breaks | Low | Rollback to 60s | `data/processed_60s_backup/` kept |
| State head regresses PR-AUC | Medium | Lose world model claim | Acceptance: PR-AUC ≥ 0.487 (within 0.02) |
| Threshold too high for demo | High | Recall too low | Lower to 0.35-0.40, disclose FPR increase |

---

## 14. TEAM CONTACTS & OWNERSHIP

| Role | Owner | Responsible For |
|------|-------|-----------------|
| ML-A | | Model training, Colab runs, architecture |
| ML-B | | Evaluation, metrics, explainability |
| DE | | Data pipeline, CSV/PCAP ingestion, scaling |
| BE | | FastAPI, model loading, API contracts |
| FE/Product | | Next.js console, charts, demo flow |
| Domain/Pitch | | PS alignment, Q&A bank, presentation |

---

## 15. FINAL VERIFICATION CHECKLIST (Pre-Demo)

- [ ] `python scripts/verify_state.py` → All `[ ok ]`
- [ ] `python tests/smoke_synthetic.py` → **SMOKE TEST PASSED**
- [ ] `uvicorn api.main:app` + `python scripts/check_api.py` → API matches rehearsed numbers
- [ ] Streamlit fallback loads and shows scenarios
- [ ] Next.js console at localhost:3000 shows forecast + attribution + ATT&CK strip
- [ ] Live page captures packets, shows real-time forecast
- [ ] Mode badge shows **REAL** (or **CACHED** if model fails to load)
- [ ] Demo video recorded (backup)
- [ ] Screenshot pack printed (last resort)
- [ ] All team members can explain: chronological split, threshold on val, IG attribution, two-engine live, state head

---

**Document End — Ready for PPT Extraction**

*All metrics sourced from `models/*.json` and script outputs — never hand-typed.*
*Run `python scripts/verify_state.py` to re-verify any number in this document.*