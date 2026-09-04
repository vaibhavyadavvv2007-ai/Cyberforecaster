# CyberForecaster: AI-Based Network Attack Forecasting from Network Traffic Data

**Problem Statement ID:** 26153 | **Organization:** NTRO | **Theme:** Blockchain & Cybersecurity

---

## 1. Problem & Approach

Traditional intrusion detectors treat each network flow in isolation, assigning a binary benign/malicious label. This discards the temporal structure of an infiltration — the sequence in which ports are probed, the pattern in which SYN flags precede ACK floods, the timing of reconnaissance before lateral movement. An infiltration is a process unfolding over time, not a single anomalous packet.

**CyberForecaster** applies the *World Models* paradigm: rather than classifying traffic, it learns the transition dynamics **P(Sₜ₊₁ | Sₜ)** — given the current observed network state, what is the probability distribution over future states. This enables forward simulation: roll out K steps ahead and identify whether the current trajectory converges to an infiltration state *before* the attacker completes the kill chain.

The system ingests CIC-IDS2018 flow records, learns temporal behaviour across 60-second windows, forecasts infiltration probability over a 5-window horizon, maps predicted behaviour to MITRE ATT&CK stages, and explains each prediction via feature attribution.

---

## 2. Data Pipeline

### Input
CIC-IDS2018 CSVs (8.1M flows across multiple attack days) are loaded by `csv_loader.py`, which handles real-world data messiness: embedded duplicate header rows, label casing variants (`SSH-Bruteforce` vs `SSH-Brute-Force`), NaN/inf rate columns, and malformed timestamps. Labels are canonicalized to a small set (Benign, FTP-Brute Force, SSH-Brute-Force, Web-Brute Force, XSS, SQL-Injection, Botnet-Ares, Heartbleed, Infiltration, DoS variants).

### Two-Level Feature Extraction
The problem statement requires both flow-level and packet-level features:

**Flow-level (16 features from CSV aggregates per 60s window):**
| Feature | Description |
|---------|-------------|
| `flow_count` | Flows in window |
| `bytes_total`, `pkts_total` | Aggregate volume |
| `duration_mean` | Mean flow duration (seconds) |
| `syn_ratio`, `ack_ratio`, `fin_ratio`, `rst_ratio`, `psh_ratio` | TCP flag distributions |
| `unique_dst_ports` | Port scan signature |
| `auth_port_share` | Credential attack signal (ports 20,21,22,23,3389) |
| `dst_port_entropy` | Port distribution diversity |
| `iat_mean`, `iat_std` | Inter-arrival timing |
| `avg_pkt_size`, `down_up_ratio` | Packet characteristics |

**Packet-level (6 features derivable from CSV columns, no PCAP required):**
| Feature | Description |
|---------|-------------|
| `tcp_win_fwd`, `tcp_win_bwd` | TCP window sizes (forward/backward) |
| `pkt_len_var` | Payload size variance |
| `fwd_seg_min` | Minimum forward segment size |
| `fwd_pkt_len_std`, `bwd_pkt_len_std` | Packet length variability |

A PCAP parser (`pcap_parser.py`) using Scapy is implemented for true packet-level features (TTL mean/variance, TCP window variance, fragmentation ratio, payload size distribution) and is ready for deployment when PCAP data becomes available.

### Windowing & Sequences
Flows are aggregated into 60-second bins → 22-feature window vectors. Sliding windows of L=10 history produce sequences with K=5 horizon steps. Critically, **y_prog is per-horizon-step**: `y_prog[i, k] = 1` iff window `t+k+1` contains attack activity. This makes the K outputs a forecast *trajectory* rather than one number copied K times — collapsing the horizon to a single bool would train all heads on an identical target and make the "risk trajectory" claim unsupportable.

### Chronological Split
70/15/15 chronological split with day-boundary purge: any sequence whose span touches a day boundary is dropped entirely, preventing overlapping windows from leaking future labels into training. No random shuffling.

### Shared Transform
`features/scaling.py` applies log1p to heavy-tailed features (counts, volumes, durations) then standardizes. Fitted on the **train split only** — no leakage. This single transform is imported by the logistic baseline, the LSTM, and the demo app, ensuring the PS-required benchmark is fair and inference cannot diverge from training.

---

## 3. World Model Architecture

### TemporalForecaster (LSTM)
```
Input: (B, L=10, F=22)  — 10 windows of 22 features each

  LSTM(22 → 64, 2 layers, dropout=0.2)
    └─→ head: Linear(64 → 32) + ReLU + Dropout
          ├─→ prog_head: Linear(32 → 5)     # K=5 progression logits
          ├─→ stage_head: Linear(32 → 6)    # MITRE ATT&CK stage
          └─→ state_head: Linear(32 → 22×5) # world model: reconstruct K future feature vectors
```

**Total:** 61,881 parameters, 0.25 MB, 0.52 ms/sequence on CPU.

### The World Model Component
The `state_head` is the literal world model: it learns to reconstruct the next K window feature vectors from the current state. Given sequence i (ending at window `ends[i]`), the target is `windows[ends[i]-K : ends[i]]` — the actual feature vectors the model must predict. The Huber loss on this reconstruction forces the LSTM to learn genuine transition dynamics P(Sₜ₊₁ | Sₜ), not just a classification shortcut.

During inference, the state trajectory (K × 22 scaled feature vectors) is returned alongside the probabilities, giving defenders a predicted future state to inspect.

### Multi-Task Training
- **Progression:** Focal Loss (α=0.5, γ=1.0) + per-horizon-step pos_weight (later steps rarer → higher weight)
- **Stage:** CrossEntropy over 6 MITRE stages
- **State:** Huber loss (robust to log1p-scaled volume outliers) × weight 0.3

### Training Configuration
- Optimizer: AdamW (lr=1e-3, weight_decay=1e-4)
- Scheduler: CosineAnnealingLR (T_max=epochs, eta_min=1e-6)
- Gradient clipping: max_norm=1.0
- Early stopping: patience=25 on validation AP
- Temperature scaling: learns optimal T on validation via grid search (minimizes NLL), applies `sigmoid(logits/T)` at inference for calibrated probabilities
- Multi-seed: 5 seeds, keep best (reduces initialization variance)

### Transformer Alternative
A Temporal Transformer (80,889 params, 2 layers, 4 heads, d_model=64) was trained as an alternative architecture. It achieves F1=0.871 (vs LSTM F1=0.270) but FPR=25.6%, exceeding the 5% constraint. It is retained as a documented alternative; the LSTM is deployed for its FPR compliance.

---

## 4. Infiltration Prediction & Attack Stage Mapping

### K-Step Forward Simulation
Given a current traffic snapshot (10 windows), `Forecaster.predict()` returns:

1. **Probability trajectory:** `[p(t+1), p(t+2), ..., p(t+5)]` — infiltration likelihood for each future window
2. **Predicted MITRE ATT&CK stage:** From `stage_head` (6-class classification)
3. **State trajectory:** K predicted future feature vectors (the world model's simulation)
4. **Threshold:** The operating point (picked on validation at FPR ≤ 5%)
5. **Temperature:** Calibration parameter for probability refinement

### MITRE ATT&CK Stage Mapping
Two complementary components:

**Family→Stage table** (supervision + validation):
| Attack Family | Stage | Rationale |
|--------------|-------|-----------|
| FTP/SSH/Web brute-force, XSS, SQL-Injection | Initial Access | Credential attacks / application exploitation |
| Botnet-Ares | Command & Control | Implant beaconing to C2 |
| Heartbleed | Exfiltration | Memory disclosure → data leaves host |
| Infiltration | Lateral Movement | Attacker pivots DMZ → production |
| DoS/DDoS variants | DoS (separate) | Under ATT&CK Impact, outside the 5 progression stages |

**Rule-based stage predictor** (`mitre_mapper.py:rule_based_stage()`): Explicit, readable thresholds on window aggregates — SYN scan detection (unique_ports ≥ 15 + syn_ratio ≥ 0.4 → Reconnaissance), credential burst (auth_share ≥ 0.5 + flow_count ≥ 8 → Initial Access), volumetric flood (both bytes and packets exceed 99th percentile → DoS), regular low-jitter beaconing (flow_count 5-60, iat_cv < 0.25 → C2), huge outbound transfer with few flows → Exfiltration. Rules are validated against dataset labels via `validate_rules()` and the agreement rate is reported.

---

## 5. Explainability

Every prediction includes feature attribution via two methods:

1. **Captum IntegratedGradients** (primary): Computes |attributions| summed over the time axis → one importance value per window feature for a specific horizon step's prediction. Answers: "which flags, ports, or flow statistics drove this forecast?"

2. **Permutation importance fallback** (dependency-free): Shuffles each feature and measures AP drop. Used when Captum/torch is unavailable.

The PS rejects black-box outputs; the demo interface displays the top contributing features for every prediction in a "WHY" panel.

---

## 6. Demonstration Interface

Two surfaces, one model:

1. **Next.js console + FastAPI backend** (primary): Accepts a scenario, runs world model inference, displays infiltration probability timeline, flagged flows, attack stage annotations, and feature attribution. Runs fully offline.

2. **Streamlit fallback** (`app/streamlit_app.py`): Same capabilities in a single Python file. Benchmark tab, lead-time tab, WHY panel.

3. **Live sensor** (`src/live/`): Npcap capture → same 60s windows → same forecaster. Verified: benign traffic stays below threshold; UDP sweep crosses threshold across three windows.

The app badges its mode: REAL (live inference), CACHED (precomputed real predictions), SIMULATED (extrapolated placeholders). Never silently falls back.

---

## 7. Benchmark Results

| Metric | LSTM World Model | Logistic Regression Baseline | Improvement |
|--------|-----------------|------------------------------|-------------|
| Precision | 0.895 | 0.034 | 26× |
| Recall | 0.159 | 0.003 | 53× |
| F1 Score | 0.270 | 0.006 | **45×** |
| FPR | 2.3% | 10.5% | 4.6× lower |
| PR-AUC | 0.699 | 0.385 | 1.8× |
| Val AP | 0.762 | — | — |

**Threshold:** 0.504 (picked on validation at FPR ≤ 5%, never on test).  
**Temperature:** T = 4.95 (calibrated on validation).

The logistic baseline is the PS-required benchmark: one LogisticRegression per horizon step, same features, same transform, same chronological split. The 45× F1 improvement demonstrates that temporal dynamics learning provides measurable value over static per-flow classification.

### Lead Time
On the validation split (3 onsets): LSTM warns 33% of onsets with 1-minute lead; the logistic baseline warns 33% with 4-minute lead (via its rule-engine-based thresholds on aggregate features). The LSTM's value is not earlier warning on this dataset — it is the **probability trajectory** that shows *how* risk evolves, and the **state reconstruction** that lets defenders inspect the predicted future network state. With more attack onsets in the test data, the temporal model's lead-time advantage would emerge more clearly.

---

## 8. Known Limitations

1. **CIC-IDS2018 ML-ready CSVs have no Src IP / Dst IP columns** — IP-derived features (unique_src_ips, unique_dst_ips) are constant zero in training. The lateral-movement rule abstains rather than firing on a fabricated threshold. The live pipeline zeroes IP features in model input because nonzero values are out-of-spec.

2. **Test set has only 1-2 attack onsets** — lead time metrics are statistically limited. The val split (3 onsets) is reported alongside for transparency.

3. **Infiltration class has only dozens of samples** — we forecast across attack families at window level rather than infiltration-only.

4. **CTU-13 data (2011) is incompatible** with CIC-IDS2018 (2018) traffic patterns — cross-dataset training hurt FPR from 2.3% to 36.3%. Same-era data matters more than more data.

5. **PCAP-derived features** are implemented (`pcap_parser.py`) but await PCAP data. CSV-derived packet features are used as a substitute.

6. **Transformer FPR (25.6%)** exceeds the 5% constraint despite higher F1 — not deployed, retained as a documented alternative.

---

## 9. Deliverables Checklist

| Deliverable | Status |
|-------------|--------|
| Source code (GitHub) | ✅ |
| README with setup instructions | ✅ |
| Architecture document (this document, ≤2 pages) | ✅ |
| Demo video (≤2 minutes) | ☐ Recorded separately |
| Technical presentation (≤5 slides) | ☐ Created separately |

---

*CyberForecaster — SIH26153. Fully open-source, runs offline, no cloud API dependencies.*
