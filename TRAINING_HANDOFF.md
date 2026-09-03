# CyberForecaster — Phase 3 Training Handoff (Temporal Transformer & CTU-13)

**For:** Human running `notebooks/Colab_Training.ipynb` on GPU
**Context:** Phase 1 (Data augmentation) and Phase 2 (World Model upgrade) are complete. This document governs the Phase 3 Colab training run.

---

## 1. What changed and why

1. **Dataset Augmentation (Gap #1 & #4)**: The pipeline now supports packet-level features extracted directly from PCAPs (`ttl_mean`, `tcp_win_mean`, `frag_ratio`, etc.). We will train using the merged CTU-13 dataset to provide these packet-level metrics alongside the flow metrics, extending our feature vector from 18 to 24.
2. **True World Model Architecture (Gap #2)**: We replaced the LSTM with a **Temporal Transformer Forecaster**. It retains the exact same multi-head structure (Progression, Stage, and State Reconstruction) but leverages self-attention for superior sequence modeling and built-in explainability.

---

## 2. Colab Execution Steps

Run these cells **in order** in your Colab notebook.

### Cell 1 — Mount and clone

```python
from google.colab import drive
drive.mount("/content/drive")
import os
if not os.path.exists('/content/cyberforecaster'):
    !git clone https://github.com/vaibhavyadavvv2007-ai/Cyberforecaster /content/cyberforecaster
else:
    %cd /content/cyberforecaster
    !git stash
    !git pull

%cd /content/cyberforecaster
!git checkout v2_cyberforecast
```

### Cell 2 — Install deps

```python
!pip install -q pyarrow fastapi uvicorn torch torchvision captum scikit-learn pandas numpy scapy
```

### Cell 3 — Build Data with PCAP features

```python
# Assuming you have downloaded CTU-13 to data/raw/ctu13
!python -m src.preprocessing.pipeline --raw data/raw --pcap-dir data/raw/ctu13 --out data/processed
```

### Cell 4 — Train the Transformer World Model

```python
import torch
from pathlib import Path
from src.models.transformer_forecaster import TemporalTransformerForecaster
from src.models.lstm_forecaster import train

print(f"\n=== Training Temporal Transformer (loss_state_weight=0.5) ===")
result = train(Path("data/processed"), epochs=40, predict_next_state=True, loss_state_weight=0.5, architecture="transformer")
print(result)
```

### Cell 5 — Verify and Save

```python
import json
m = json.loads(open("models/metrics_lstm.json").read())["lstm_forecaster"]
print(f"PR-AUC: {m['pr_auc']:.4f}  Recall: {m['recall']:.4f}  FPR: {m['fpr']:.4f}")

# Package for download
!zip -j transformer_trained.zip \
    models/trained_models/lstm_forecaster.pt \
    models/trained_models/lstm_config.json \
    models/metrics_lstm.json \
    models/metrics_lead_time.json \
    data/processed/demo_cache.json
from google.colab import files
files.download('transformer_trained.zip')
```

---

## 3. Human Handoff Instructions

When you have the `transformer_trained.zip` file:
1. Upload it back to the agent in the IDE.
2. Ask the agent to "Import the Transformer weights and verify the state".
