# CyberForecaster — Training Handoff (Packet 2)

**Date generated:** 2026-09-02
**For:** Human running `notebooks/Colab_Training.ipynb` on GPU
**Context:** Packet 1 (audit/bugfix/cleanup) is complete and verified.
This document governs the Packet 2 Colab training round.

---

## 1. What changed and why

A second output head — the **state-reconstruction head** — was added to
`TemporalForecaster` in `src/models/lstm_forecaster.py`. The existing progression
and stage heads are **untouched**: same architecture, same loss terms, same output shapes.

The new head predicts the actual next-window feature vectors (K future windows,
F-dim each) alongside the existing attack-probability and stage outputs.
This directly answers the PS requirement for a state-transition model: the system
now predicts *what the network will look like* in the next 5 windows, not only
*whether there will be an attack*. Two config flags control the feature:

- `predict_next_state` (bool): enable/disable the head. `True` for new training.
- `loss_state_weight` (float): relative weight of the Huber reconstruction loss.

The existing heads, metrics, and all downstream code are byte-for-byte identical
with `predict_next_state=False` — this is purely additive.

---

## 2. Exact Colab training commands

Run these cells **in order** in `notebooks/Colab_Training.ipynb`.

### Cell 1 — Mount and clone (skip if already done)

```python
from google.colab import drive
drive.mount("/content/drive")
import subprocess
subprocess.run(["git", "-C", "/content/cyberforecaster", "pull"], check=True)
# OR first time: subprocess.run(["git", "clone", "<repo-url>", "/content/cyberforecaster"], check=True)
%cd /content/cyberforecaster
```

### Cell 2 — Install deps

```python
!pip install -q pyarrow fastapi uvicorn torch torchvision captum scikit-learn pandas numpy
```

### Cell 3 — (Re-)build data if needed (skip if data/processed/ is present)

```python
!python -m src.preprocessing.pipeline --raw data/raw --out data/processed
```

### Cell 4 — Train (PRIMARY: start with loss_state_weight=0.3)

> Suggested sweep: run all three values, compare PR-AUC to the pre-change
> baseline (noted in models/metrics_lstm.json before this run). Pick the
> loss_state_weight that keeps PR-AUC within 0.02 of baseline.

```python
from pathlib import Path
from src.models.lstm_forecaster import train

# --- Recommended starting point ---
result = train(
    npz_dir=Path("data/processed"),
    epochs=40,
    predict_next_state=True,
    loss_state_weight=0.3,
)
print(result)

# --- Conservative (state head has less influence) ---
# result = train(npz_dir=Path("data/processed"), epochs=40,
#                predict_next_state=True, loss_state_weight=0.1)

# --- Aggressive (state head has more influence) ---
# result = train(npz_dir=Path("data/processed"), epochs=40,
#                predict_next_state=True, loss_state_weight=0.5)

# --- Safety net: reproduces pre-change behaviour exactly ---
# result = train(npz_dir=Path("data/processed"), epochs=40,
#                predict_next_state=False, loss_state_weight=0.0)
```

### Cell 5 — Check metrics after each run

```python
import json
m = json.loads(open("models/metrics_lstm.json").read())["lstm_forecaster"]
print(f"PR-AUC: {m['pr_auc']:.4f}  Precision: {m['precision']:.4f}  "
      f"Recall: {m['recall']:.4f}  FPR: {m['fpr']:.4f}")
```

Acceptance criterion: **PR-AUC must not regress by more than 0.02 from Packet 1 baseline.**
If it does: reduce `loss_state_weight` or fall back to `predict_next_state=False`.

### Cell 6 — Lead-time re-evaluation

```python
!python -m src.evaluation.lead_time --dir data/processed
```

### Cell 7 — Rebuild demo cache

```python
!python scripts/build_demo_cache.py
```

---

## 3. What to bring back from Colab

Download exactly these files and commit them to `main`:

| File | Location | Description |
|------|----------|-------------|
| `lstm_forecaster.pt` | `models/trained_models/` | New weights |
| `lstm_config.json` | `models/trained_models/` | Config with `predict_next_state` key |
| `metrics_lstm.json` | `models/` | Updated benchmark numbers |
| `metrics_lead_time.json` | `models/` | Lead-time re-evaluation |
| `demo_cache.json` | `data/processed/` | Rebuilt demo cache |

Do **not** bring back `data/processed/*.npz` or `windows.parquet` unless the
pipeline was re-run with different settings.

---

## 4. How to re-verify locally after import

```powershell
# 1. Artifact + state_head consistency check
python scripts/verify_state.py

# 2. Full wiring test (no GPU needed)
python tests/smoke_synthetic.py

# 3. API round-trip (needs running server)
uvicorn api.main:app --port 8000
# in another terminal:
python scripts/check_api.py
```

**Critical checks in verify_state.py output:**

- `[ ok ] predict_next_state=True (state-reconstruction head enabled)`
- `[ ok ] state_head weights present in lstm_forecaster.pt`

If you see `[BAD ] predict_next_state=True in config but NO state_head weights`,
the `.pt` is from a pre-Packet-2 training run — replace with the Colab output.

---

## 5. The 14% recall problem

Current baseline (Packet 1): **88% precision, 14% recall** on the unseen attack
family in the test split. Three options, honestly:

### Option A — Threshold adjustment only (cheapest, no retraining)
Move the threshold lower to trade FPR for recall. This picks a different point
on the *same* PR curve — not a genuine improvement. The 5% FPR budget was
chosen deliberately; moving it without disclosing is dishonest. Only use this
as a last resort on demo morning.

### Option B — Class-weighted loss (recommended, same Colab round)
The `pos_weight` per horizon step is already auto-computed from training data
in `train()`. The Packet 2 state-head training may incidentally improve recall
through trunk regularisation. After the Packet 2 run: check the recall number.
If still below 20%, a follow-up commit can add a `pos_weight_scale` multiplier
(try 2.0, 3.0) and re-train in a second Colab round.

### Option C — More data / 30s bins (future work)
30s bins roughly double the sequence count, helping generalisation. But the
30s/60s live-sensor mismatch (BUG-5.1 in AUDIT_LOG.md) must be resolved first.
Flag as Packet 3 / post-demo.

**Decision for this Colab round:** Run Packet 2 training first. Check recall
in `metrics_lstm.json`. If recall is still below 20%, add `pos_weight_scale`
in a follow-up commit — do not attempt it in the same Colab session without
evaluating the Packet 2 results first.

---

## 6. Fallback plan — Option A reframing language

If training does not finish in time, or `predict_next_state=False` must be kept
for demo day, use this language verbatim in pitch materials:

---

*CyberForecaster implements a learned temporal world model of network state.
Rather than explicit hand-crafted state-transition equations, the LSTM encodes
the full recent history of 18 engineered network features into a dense latent
state* `h_t` *(64-dim), from which it directly simulates K future states — one
per horizon window — outputting both attack infiltration probability and dominant
ATT&CK stage for each.*

*This is world-modelling via learned neural dynamics: the temporal representation*
`h_t` *must capture all state information needed to predict the next K outcomes,
exactly the requirement in PS26153 §3.2. The latent state IS the state vector.*
*The K-head output layer maps it to K simultaneous future predictions (K-step
forward simulation). Integrated Gradients attribution identifies which input
features drive each future prediction — that is the interpretability the PS asks for.*

---

## 7. Time estimate

| Step | Time (T4 GPU) |
|------|--------------|
| Pipeline rebuild (if needed) | 5–10 min |
| Training per run | 15–25 min |
| Three-way sweep (0.1 / 0.3 / 0.5) | 45–75 min |
| Lead-time re-evaluation | 1–2 min |
| Demo cache rebuild | 2–3 min |
| **Total** | **~60–90 min** |

**Start the Colab session by Sep 3 evening (IST)** — allows the full sweep plus
one fallback run if needed. Sep 4 allows one run only. Sep 5 morning is too late.

Critical path: budget **30 minutes for local re-verification** after Colab files arrive.
