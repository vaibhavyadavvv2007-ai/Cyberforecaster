# CyberForecaster — Technical Presentation (5 Slides)

**Problem Statement 26153 — AI Based Network Attack Forecasting from Network Traffic Data**
**NTRO | Blockchain & Cybersecurity**

---

## Slide 1: The Problem — Why Static Classification Fails

### The Limitation of Traditional IDS

- Traditional ML classifiers treat **each network flow in isolation** → binary benign/malicious label
- This discards the **temporal and causal structure** of an infiltration:
  - The sequence in which ports are probed
  - The pattern in which SYN flags precede ACK floods
  - The inter-arrival timing of reconnaissance before lateral movement
- **An infiltration is a process unfolding over time, not a single anomalous packet**

### The World Models Paradigm

| Traditional Approach | World Model Approach |
|---------------------|---------------------|
| Classify each flow: benign or malicious? | Learn: given current state, what is P(future state)? |
| One prediction per flow | K-step forward simulation |
| Cannot anticipate progression | Can forecast attack stages before compromise completes |
| Black-box score | Interpretable: which features drive the prediction? |

**Core idea:** Learn transition dynamics **P(Sₜ₊₁ | Sₜ)** — given observed network state (active flows, flag distributions, port activity, packet timing), predict the probability distribution over future states. Roll out K steps ahead and identify whether the current trajectory converges to an infiltration state **before the attacker completes the kill chain**.

---

## Slide 2: System Architecture

### Data Pipeline (CIC-IDS2018 → Sequences)

```
CIC-IDS2018 CSVs (8.1M flows)
  → csv_loader.py        # clean, canonicalize labels, handle messiness
  → window_builder.py    # 60s bins → 22 features/window
  → make_sequences()     # L=10 history, K=5 horizon, per-step labels
  → chrono_split()       # 70/15/15 chronological, day-boundary purge
  → scaler.npz           # log1p + standardize, train only
```

### Feature Set (22 features — meets PS requirement for 2-level features)

| Flow-level (16) | Packet-level (6, CSV-derived) |
|----------------|------------------------------|
| flow_count, bytes_total, pkts_total | tcp_win_fwd, tcp_win_bwd |
| duration_mean | pkt_len_var, fwd_seg_min |
| syn/ack/fin/rst/psh_ratio | fwd_pkt_len_std, bwd_pkt_len_std |
| unique_dst_ports, auth_port_share | *(PCAP parser ready for TTL, frag, payload)* |
| dst_port_entropy, iat_mean, iat_std | |
| avg_pkt_size, down_up_ratio | |

### Model Architecture

```
Input: (B, L=10, F=22) — 10 windows of 22 features

  2-layer LSTM (hidden=64, dropout=0.2) — 61,881 params
    └─→ head: Linear(64→32) + ReLU + Dropout
          ├─ prog_head:   Linear(32→5)    # K=5 infiltration probabilities
          ├─ stage_head:  Linear(32→6)    # MITRE ATT&CK stage
          └─ state_head:  Linear(32→22×5) # WORLD MODEL: predict K future feature vectors
```

**The state_head IS the world model** — it learns to reconstruct the next K window feature vectors, forcing the LSTM to learn genuine transition dynamics, not a classification shortcut.

### Training

- Focal Loss (α=0.5, γ=1.0) + CrossEntropy (stage) + Huber (state) × 0.3
- Per-horizon-step pos_weight (later steps rarer → higher weight)
- AdamW + CosineAnnealingLR + gradient clipping
- Temperature scaling: learns T=4.95 on validation for calibrated probabilities
- Multi-seed: 5 seeds, keep best

---

## Slide 3: Infiltration Prediction & MITRE ATT&CK Mapping

### K-Step Forward Simulation

Given a 10-window traffic snapshot, the model outputs:

1. **Probability trajectory:** `[p(t+1), p(t+2), p(t+3), p(t+4), p(t+5)]`
   - Infiltration likelihood for each future 60s window
   - Shows HOW risk evolves, not just a single score

2. **Predicted MITRE ATT&CK stage** (6 classes):
   - Reconnaissance → Initial Access → Lateral Movement → C2 → Exfiltration
   - DoS shown separately (under ATT&CK Impact, outside the 5 progression stages)

3. **State trajectory:** K predicted future feature vectors
   - Defenders can inspect the predicted future network state

### MITRE ATT&CK Stage Mapping

| Attack Family | Stage | Signal |
|--------------|-------|--------|
| FTP/SSH/Web brute-force, XSS, SQLi | **Initial Access** | Auth port bursts, credential attempts |
| Botnet-Ares | **Command & Control** | Regular low-jitter beaconing |
| Heartbleed | **Exfiltration** | Memory disclosure → data leaves host |
| Infiltration | **Lateral Movement** | Pivoting DMZ → production |
| DoS/DDoS | **DoS** (separate) | Volumetric flood |

### Explainability (PS Requirement)

- **Captum IntegratedGradients:** |attributions| summed over time → per-feature importance for each prediction
- **Permutation fallback:** Feature shuffling → AP drop measurement
- Every prediction shows **which flags, ports, and flow statistics drove the forecast** — no black-box outputs

---

## Slide 4: Results — Benchmark vs Logistic Regression

### Headline Metrics (Chronological Test Split)

| Metric | **LSTM World Model** | **Logistic Regression** | **Improvement** |
|--------|---------------------|------------------------|-----------------|
| **Precision** | 0.895 | 0.034 | **26×** |
| Recall | 0.159 | 0.003 | 53× |
| **F1 Score** | **0.270** | 0.006 | **45×** |
| **FPR** | **2.3%** | 10.5% | 4.6× lower |
| **PR-AUC** | **0.699** | 0.385 | 1.8× |
| Validation AP | 0.762 | — | — |

**Threshold:** 0.504 (picked on validation at FPR ≤ 5%, never on test)  
**Temperature:** T = 4.95 (calibrated on validation)

### Why Temporal Dynamics Matter

- The logistic baseline uses **the same features, same transform, same split** — one LogisticRegression per horizon step
- The 45× F1 improvement proves that **learning P(Sₜ₊₁|Sₜ) provides measurable value** over static per-flow classification
- LSTM FPR (2.3%) is well under the 5% constraint; baseline FPR (10.5%) exceeds it
- Precision (0.895) means when the model warns, it is almost always right — critical for SOC triage

### Lead Time (Early Warning)

| Model | Onsets | Warned | Rate | Median Lead |
|-------|--------|--------|------|-------------|
| LSTM (val) | 3 | 1 | 33% | 1 min |
| Logistic (val) | 3 | 1 | 33% | 4 min |

*Test set has only 1 onset — statistically limited. Validation split reported for transparency.*

The LSTM's value is the **probability trajectory** and **state reconstruction**, not necessarily earlier warning on this dataset. With more attack onsets, the temporal model's advantage would emerge more clearly.

---

## Slide 5: Demonstration & Deliverables

### Demo Interface (Runs Fully Offline, No Cloud APIs)

**Two surfaces, one model:**

1. **Next.js console + FastAPI backend** (primary)
   - Accepts PCAP or CSV input → runs world model inference
   - Displays: infiltration probability timeline, flagged flows, attack stage annotations, feature attribution (WHY panel)

2. **Streamlit fallback** (`app/streamlit_app.py`)
   - Same capabilities: timeline, risk, WHY, ATT&CK mapping, benchmark, lead time

3. **Live sensor** (`src/live/`)
   - Npcap capture → same 60s windows → same forecaster
   - Verified: benign stays below threshold; UDP sweep crosses threshold across 3 windows

### Mode Badging (Honesty Rail)

| Mode | Description |
|------|-------------|
| **REAL** | Live inference from packet capture |
| **CACHED** | Precomputed real predictions (crash-proof fallback) |
| **SIMULATED** | Extrapolated placeholders (when model unavailable) |

### Deliverables for Evaluation

| Deliverable | Status |
|-------------|--------|
| Source Code (GitHub) | ✅ |
| README with Setup Instructions | ✅ |
| Architecture Document (≤2 pages) | ✅ |
| Demo Video (≤2 minutes) | ⏳ |
| Technical Presentation (this deck, ≤5 slides) | ✅ |

### Reproducibility

- Training scripts: `src/models/lstm_forecaster.py`
- Model weights: `models/trained_models/lstm_forecaster.pt` (61,881 params, 0.25 MB)
- Config: `models/trained_models/lstm_config.json`
- Metrics: `models/metrics_lstm.json`, `models/metrics_baseline.json`
- Colab training notebook: `notebooks/Colab_Training.ipynb`
- Verify state: `python scripts/verify_state.py`

---

*CyberForecaster — SIH26153. Fully open-source. Runs offline. No cloud API dependencies.*
