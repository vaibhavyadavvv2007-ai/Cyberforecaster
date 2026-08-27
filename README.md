# CyberForecaster — SIH26153 Starter Kit

Temporal attack-progression forecasting: `flows → time-window states → LSTM → K-step probability forecast + ATT&CK stage + attribution`.

**Read `../SIH26153_battle_plan.md` first.** This kit exists so Day 1 is setup-free and Day 2 starts on real data.

## Setup (once)

```bash
cd cyberforecaster
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Training extras (ML pair only, when needed):
```bash
# CPU wheel is enough for the small LSTM locally; use CUDA build on Kaggle (preinstalled there)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install captum
```

## Quickstart

```bash
# 1) See what's in the dataset bucket + real file sizes BEFORE pulling anything
python scripts/download_data.py --list

# 2) Pull the curated subset (edit configs/data_sources.yaml after verifying day↔attack mapping)
python scripts/download_data.py --yes

# 3) Clean → windows → sequences (writes processed/windows.parquet + sequences.npz)
python -m src.preprocessing.pipeline --raw data/raw --out data/processed

# 4) Required benchmark (logistic regression on identical features)
python -m src.models.baseline_logreg --npz data/processed/sequences.npz

# 5) The app (runs in SIMULATED mode until a trained model exists)
streamlit run app/streamlit_app.py

# 6) Train the LSTM (ML pair, Kaggle or local GPU)
python -m src.models.lstm_forecaster --npz data/processed/sequences.npz
```

Or open `notebooks/02_windows_baseline.ipynb` to walk steps 1–5 interactively.

Sanity-check the whole pipeline without downloading anything (runs on synthetic flows):
```bash
python tests/smoke_synthetic.py   # must print SMOKE TEST PASSED
```

## Repo map

```
configs/data_sources.yaml      # curated download list — EDIT AFTER VERIFYING day↔attack mapping
scripts/download_data.py       # S3 listing + prioritized pull (no blind 7GB downloads)
src/
  ingestion/csv_loader.py      # load + label canonicalization + duplicate-header/NaN/inf cleanup
  preprocessing/pipeline.py    # orchestrates clean → windows → sequences (chronological split w/ purge)
  features/window_builder.py   # flows → 60s window aggregates; sliding L=10/K=5 sequences
  models/baseline_logreg.py    # PS-required logistic baseline + F1/precision/recall/FPR table
  models/lstm_forecaster.py    # 2-layer LSTM, direct multi-horizon head (K probabilities + stage)
  forecasting/rollout.py       # forecast_probabilities(); recursive-latent = Tier 3 stub
  explainability/attribution.py# Captum IG aggregated over time; permutation-importance fallback
  attack_mapping/mitre_mapper.py # family→stage table + rule-based stage predictor + validation
app/streamlit_app.py           # demo UI: timeline / risk card / WHY / ATT&CK strip / flagged flows
notebooks/                     # interactive walkthrough of the full pipeline
data/{raw,processed}/          # created by scripts; never commit big files
```

## Honesty rails (do not remove)

- The app shows a **SIMULATED** badge until a real trained model is wired in.
- Benchmark numbers must come from `baseline_logreg` / training runs — never typed by hand.
- Splitting is chronological with boundary purge (`window_builder.chrono_split`) — no random shuffling anywhere.

## Data notes (why this kit looks cautious)

- CSE-CIC-IDS2018 labels are messy: casing variants, embedded duplicate header rows, NaN/inf rate columns, malformed timestamps — `csv_loader` handles all of these and prints what it fixed.
- The **Infiltration** class has only dozens of samples → we forecast across attack families at window level (see battle plan §5.1).
- Verify the attack-day mapping yourself from the bucket README/paper — including against comments in `data_sources.yaml`.
