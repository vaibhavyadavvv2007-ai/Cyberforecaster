# Baseline freeze — CSE-CIC-IDS2018, Model V1 (18 features)

Frozen on 2026-09-04, before the multi-dataset / world-model refactor
(MASTER_IMPLEMENTATION_PLAN.md). Nothing in this directory may be modified
or deleted — it is the reproducible "before" state that answers the judge
question "did the extra data actually help?".

## Provenance record

| Item | Value |
|---|---|
| Dataset | CSE-CIC-IDS2018 (AWS attack-infrastructure scenarios, 10 days) |
| Windows | 6,192 total · 1,486 attack (~24%) · 30-second bins |
| Features | 18 (current schema; see `data/processed/meta.txt`) |
| SEQ_LEN (L) | 10 |
| HORIZON (K) | 5 |
| Model | 2-layer LSTM, hidden 64, multi-task heads (5 progression logits + 6-stage head) |
| State head | disabled in this baseline (not trained) |
| Threshold | 0.5612 (validation-selected, max_fpr = 0.05) |
| Scaler | log1p + standardize, fitted on train split only (`data/processed/scaler.npz`) |
| Splits | chronological 70/15/15: 4,145 / 881 / 916 sequences, boundary purge |
| bin_secs | 30 (official training value; the 60s variant is preserved in `ab_60s_backup/`) |
| Zero-variance features | unique_dst_ips, unique_src_ips (IP-derived, zeroed at live inference) |
| Test PR-AUC | LSTM 0.656 vs logistic 0.333 (same features & split) |
| Operating point | precision 0.88 · recall 0.14 · FPR 0.006 (high-precision budget) |

## Contents

```
models/baseline_cic2018_v1/
├── README.md              ← this provenance record
├── trained_models/        ← lstm_forecaster.pt + lstm_config.json (production V1)
├── ab_30s/                ← 30s-bin A/B artifacts (the winning config)
├── ab_60s_backup/         ← 60s-bin A/B artifacts (superseded)
├── metrics/               ← metrics_lstm.json, metrics_baseline.json, metrics_lead_time.json
├── configs/               ← data_sources.yaml
└── data/
    ├── processed/         ← windows.parquet, sequences_{train,val,test}.npz, scaler.npz, demo_cache.json
    └── processed_30s/     ← same split without demo cache
```

## Rerunning V1

The original files remain untouched at their live locations
(`models/trained_models/`, `data/processed/`, `configs/`). This copy exists
so that any future change to those paths cannot destroy the baseline. To
reproduce V1 numbers, point training/inference at this directory's
artifacts.
