# CyberForecaster - Session Context

## Project Overview
**SIH26153 - AI-based Network Attack Forecasting from Network Traffic Data**

World model that learns P(S_t+1 | S_t) - network state transition dynamics - to forecast attack progression before compromise completes.

## Current State (as of Sep 4, 2026)

### What Works
- **Data Pipeline**: CIC-IDS2018 CSVs → windows.parquet → sequences_*.npz → scaler.npz
- **Feature Set**: 22 features (16 flow-level + 6 CSV-derived packet-level)
- **LSTM Forecaster**: Trained, 62K params, 0.5ms/sequence on CPU
- **Logistic Baseline**: PS-required benchmark, one model per horizon step
- **Rule Engine**: MITRE ATT&CK stage mapping with validation
- **Lead Time Evaluation**: Metric framework exists but scores 0% on test (only 1 onset)
- **Explainability**: Captum IG + permutation fallback
- **Demo App**: Next.js console + FastAPI backend + Streamlit fallback
- **Live Sensor**: Npcap capture → windows → forecasts (verified Aug 30)

### Final Model (LSTM, Sep 4 2026 - retrained)
- **Precision**: 0.977 | **Recall**: 0.134 | **F1**: 0.236
- **FPR**: 0.4% (well under 5% target) | **PR-AUC**: 0.699
- **Val AP**: 0.759 | **Lead time**: 0% warned on val (threshold too strict for onsets)
- **Threshold**: 0.611 | **Temperature**: 4.65
- **Params**: 61,881 | **Latency**: 0.52ms/seq CPU

### Baseline Comparison (PS requirement)
- **LSTM F1**: 0.236 vs **Baseline F1**: 0.006 (39× improvement)
- **LSTM PR-AUC**: 0.699 vs **Baseline PR-AUC**: 0.385 (1.8× improvement)
- **LSTM FPR**: 0.4% vs **Baseline FPR**: 10.5% (LSTM much better)

### Transformer (trained, not deployed)
- **Precision**: 0.815 | **Recall**: 0.935 | **F1**: 0.871
- **FPR**: 25.6% (too high, >5% target)
- **Lead time**: 33% on val, 3 min lead
- **Val AP**: 0.760 | **Params**: 80,889
- Not used: FPR exceeds competition constraint

### CTU-13 Experiment (Sep 4, 2026)
- **Result**: CTU-13 data hurt performance (FPR jumped from 0.4% to 36.3%)
- **Reason**: CTU-13 is from 2011 with very different traffic patterns than CIC-IDS2018
- **Decision**: Reverted to CIC-IDS2018 only, CTU-13 data archived in data/raw/ctu13_archive/
- **Lesson**: Cross-dataset transfer is hard; same-era data matters more than more data

### Critical Issues (Priority Order)
1. **Test set attack-heavy** - 54.7% attack rate makes test FPR unreliable
2. **Lead time** - LSTM warns 0% of onsets on val (threshold too strict)
3. **Transformer FPR** - 25.6%, needs tuning to meet <5% constraint

### Feature Set (22 features)
```
Flow-level (from CSVs):
flow_count, bytes_total, pkts_total, duration_mean,
syn_ratio, ack_ratio, fin_ratio, rst_ratio, psh_ratio,
unique_dst_ports, auth_port_share, dst_port_entropy,
iat_mean, iat_std, avg_pkt_size, down_up_ratio

Packet-level (CSV-derived, no PCAP needed):
tcp_win_fwd, tcp_win_bwd, pkt_len_var, fwd_seg_min,
fwd_pkt_len_std, bwd_pkt_len_std
```

### Model Architecture
- **LSTM**: 2-layer, hidden=64, 62K params
  - prog_head: K=5 horizon steps (per-step labels, NOT broadcast)
  - stage_head: 6 MITRE stages
  - state_head: world model reconstruction (K × F features)
- **Transformer**: Skeleton only, needs integration

### Training Configuration
- Chronological split: 70/15/15 with day-boundary purge
- Input transform: log1p + standardize (fitted on train only)
- Loss: BCEWithLogits (pos_weight per step) + CrossEntropy (stage) + Huber (state)
- Early stopping: patience=25 on val AP
- Threshold: picked on val at FPR≤5%

### Key Files
```
src/ingestion/csv_loader.py      - Load CIC-IDS2018 CSVs
src/ingestion/ctu13_loader.py    - Load CTU-13 binetflow (not used currently)
src/features/window_builder.py   - Flows → windows → sequences
src/features/scaling.py          - Shared input transform
src/preprocessing/pipeline.py    - End-to-end pipeline
src/models/baseline_logreg.py    - Logistic benchmark
src/models/lstm_forecaster.py    - LSTM forecaster + training
src/models/transformer_forecaster.py - Transformer (skeleton)
src/forecasting/rollout.py       - Model loading + inference
src/evaluation/lead_time.py      - Early warning metric
src/attack_mapping/mitre_mapper.py - MITRE stage mapping
src/explainability/attribution.py - Feature importance
tests/smoke_synthetic.py         - End-to-end smoke test
```

### Data Artifacts
```
data/processed/windows.parquet   - (4232, 28) windows
data/processed/sequences_train.npz - (2742, 10, 22) features
data/processed/sequences_val.npz - (587, 10, 22)
data/processed/sequences_test.npz - (587, 10, 22)
data/processed/scaler.npz
models/trained_models/lstm_forecaster.pt - NEW weights (22 features + temp)
models/trained_models/lstm_config.json - includes temperature
models/metrics_baseline.json
models/metrics_lstm.json
models/metrics_lead_time.json
```

## What the Previous Session Did

### Completed
1. **PHASE 0: Cleanup** - Removed unnecessary MD files, archives, temp_extract, .impeccable, .playwright-mcp
2. **PHASE 1: Fix dead features** - Replaced 6 PCAP features with CSV-derived equivalents. Removed 2 dead IP features.
3. **PHASE 2: Update csv_loader** - Added new CSV columns to CORE_COLS
4. **PHASE 3: Rebuild pipeline** - Sequences now have 22 features, clean, no NaN/inf
5. **PHASE 4: CTU-13 experiment** - Tried adding CTU-13 data, hurt performance, reverted

### NOT Completed (Competition Deadline Tomorrow)
1. **Improve lead time** - Currently 0% on val (threshold too strict)
2. **Integrate Transformer** - Still skeleton
3. **Consider recall tradeoff** - LSTM recall=0.134, may be too conservative

## Problem Statement Requirements Checklist
- [x] Feature extraction pipeline (CIC-IDS2018 CSVs)
- [x] World model architecture (LSTM with state reconstruction head)
- [x] Infiltration prediction (K-step forward simulation)
- [x] MITRE ATT&CK stage mapping
- [x] Explainability (Captum IG + permutation)
- [x] Demo interface (Next.js + FastAPI + Streamlit)
- [x] Benchmark against logistic regression (39× F1 improvement)
- [x] FPR < 5% (LSTM FPR=0.4%, well under 5%)
- [ ] Lead time > 0 (LSTM warns 0% on val, data limitation)
- [ ] Transformer integration (currently skeleton)

## How to Continue

### Step 1: Consider Lowering Threshold for Demo
- At threshold=0.3, LSTM warns 33% of onsets with 2 min lead (FPR=12.2%)
- At threshold=0.5, no warnings (FPR=7.8%)
- Tradeoff: more warnings = more FPR, but shows the system works

### Step 2: Try to Get More CIC-IDS2018 Data
- Download Thursday-22-02-2018 (365 MB)
- Rebuild pipeline and retrain
- More data → better generalization, more onsets

### Step 3: Consider Recall Tradeoff
- LSTM recall=0.134, may be too conservative
- Try adjusting threshold or class weights
- Balance precision/recall based on PS requirements

### Step 4: Verify Metrics
```bash
python tests/smoke_synthetic.py
python -m src.models.baseline_logreg --dir data/processed
python -m src.evaluation.lead_time --dir data/processed
```

## Known Limitations
1. CIC-IDS2018 ML-ready CSVs have NO Src IP/Dst IP columns
2. Test set has only 1-2 attack onsets → metrics statistically empty
3. Infiltration class has only dozens of samples
4. Feb-14 is truncated at 13:00 (brute-force only, no Heartbleed)
5. CTU-13 data from 2011 incompatible with CIC-IDS2018 patterns

## Competition Deadline
**September 5, 2026** - Tomorrow!
