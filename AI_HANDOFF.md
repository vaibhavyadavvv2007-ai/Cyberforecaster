# CyberForecaster — AI-to-AI Handoff Document

**To the Next AI Agent:**
You are picking up an advanced cybersecurity forecasting project. Read this document carefully to understand the context, constraints, and your immediate next tasks. Update the trackers `[ ]` -> `[x]` as you complete them.

## 1. Project Context & Current State
- **Goal:** We are building a temporal forecaster that predicts cyber attack progression (MITRE ATT&CK stages) over a sliding time window.
- **Recent Upgrades (Packet 2 / Phase 4):**
  - **World Model Architecture:** We replaced the baseline LSTM with a **Temporal Transformer Forecaster** (`src/models/transformer_forecaster.py`). It retains the multi-head structure (progression, stage, and state-reconstruction).
  - **Dataset Augmentation:** We expanded the input feature vector from 18 to **24 features** by adding strict packet-level telemetry (`ttl_mean`, `tcp_win_mean`, `frag_ratio`, etc.) via `scapy` parsing.
  - **CTU-13 Integration:** We updated `pipeline.py` and `ctu13_loader.py` to stringently parse CTU-13 `.binetflow` files, completely dropping noisy `Background` traffic and all `NaN` values to minimize FPR.
- **Current Branch:** `v2_cyberforecast`. **NEVER push to or edit the `main` branch.**

## 2. Immediate Situation
The human user is currently training the new Temporal Transformer model on Google Colab using the newly pushed codebase. Once training is complete, they will upload a file named `transformer_trained.zip` to you.

## 3. Your Task Tracker
*Mark these with an `[x]` as you complete them to track your progress.*

- `[ ]` **Receive the Weights:** Wait for the user to provide `transformer_trained.zip`.
- `[ ]` **Import Weights:** Extract the zip. Move `lstm_forecaster.pt` and `lstm_config.json` into `models/trained_models/`. Move `metrics_lstm.json` and `metrics_lead_time.json` into `models/`.
- `[ ]` **Verify Architecture:** Run `python scripts/verify_state.py`. Ensure it successfully loads the model and recognizes `architecture: transformer` and `F=24`.
- `[ ]` **Live Sensor Test:** Run `python scripts/live_rehearsal.py`. Ensure the `scapy` packet capture correctly extracts the 24 features and doesn't crash on inference.
- `[ ]` **Analyze Metrics:** Review `models/metrics_lstm.json`. Verify that the stringent cleaning and Transformer architecture successfully lowered the FPR while maintaining or improving Recall/PR-AUC.
- `[ ]` **Commit & Push:** Commit the new verified weights and metrics to `v2_cyberforecast` and push to GitHub.

## 4. Critical Constraints & Knowledge
- **No `torch` on the Live Sensor:** The live app runs in environments where PyTorch may not be installed. Model inference is strictly guarded by `try/except ImportError` blocks.
- **Zero-Variance Features:** If `scaler.npz` warns about zero-variance features, that is expected for some IPs in CTU-13. Do not attempt to force-fill fake IP data.
- **Philosophy:** Never make a change without first understanding what depends on it. If a test fails, do not rewrite the testing script to pass; fix the underlying architecture bug.
