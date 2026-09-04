# EVALUATION — the one authoritative numbers document

Every number below is produced by a script in this repo and stored in an
artifact under `models/`. If a number is not in this file, it is not a result.
Nothing here is hand-edited — rerun the named command to reproduce.

Status date: 2026-09-04. Labels: **measured** (produced by a run), **limited**
(measured but statistically weak — sample too small), **negative** (an
experiment that did not help, kept on purpose).

## Authoritative configuration (single source)

| Parameter | Value | Source |
|---|---|---|
| Window size | 30 s | `src/config.py` BIN_SECS |
| Lookback L | 10 windows (5 min) | `src/config.py` SEQ_LEN |
| Horizon K | 5 windows (2.5 min) | `src/config.py` HORIZON |
| Features (V1/V2/V3) | 18 flow-level | `src/features/window_builder.py` WINDOW_FEATURES |
| Canonical schema | 48 features, hash `a9570d8349141d92` | `src/features/canonical_schema.py` |
| Training data | CSE-CIC-IDS2018, 7 days, 6,192 windows | `data/processed/windows.parquet` |
| Split | chronological 70/15/10 + day-boundary purge | `chrono_split` |
| V1 threshold | 0.5612 (picked on VAL at FPR≤5%) | `models/trained_models/lstm_config.json` |
| V3 threshold | 0.8942 (same rule, own val run) | `models/world_model_v3/lambda_0.5_huber/rollout_config.json` |

## Forecasting quality (held-out chronological TEST split, measured)

| Model | PR-AUC | Precision | Recall | F1 | FPR | Artifact |
|---|---|---|---|---|---|---|
| Logistic baseline (same features/split) | 0.3335 | 0.500 | 0.009 | 0.018 | 0.003 | `models/metrics_logistic.json` |
| **V1 LSTM (demo model)** | **0.6565** | 0.8824 | 0.1395 | 0.2410 | 0.0057 | `models/metrics_lstm.json` |
| V2 state-head multi-task (λ=0.5) | 0.6050 | 0.8810 | 0.1721 | 0.2879 | 0.0071 | `models/world_model_v2/lambda_0.5_huber/metrics.json` |
| V3 rollout world model (λ=0.5) | 0.6331 | 1.0000 | 0.0651 | 0.1223 | 0.0000 | `models/world_model_v3/lambda_0.5_huber/metrics.json` |

Reading: V1 remains the best forecaster on CIC2018. V3 improves on V2's
ranking (0.605 → 0.633) and its val-picked threshold is extremely
conservative (precision 1.0, recall 0.065). The V3 value is architectural
(risk/stage decoded from forecast future STATES), not headline metrics — and
it is reported exactly that way.

Reproduce: `python -m src.models.lstm_forecaster`, `python -m src.models.world_model`,
`python -m src.models.rollout_world_model`.

## State-prediction quality (measured, scaled space)

| Model | Cosine/step (mean) | MAE/RMSE per step |
|---|---|---|
| V2 (direct state head) | 0.227 | in `metrics.json` `_state` |
| **V3 (autoregressive rollout)** | **0.257** (0.219→0.289 across K) | in `metrics.json` `_state` |

Reproduce: state metrics are inside each variant's `metrics.json` `_state`
key; zero-variance (degenerate) features excluded, exclusion recorded.

## Calibration (measured)

Pooled n=4,580 test windows: **Brier 0.1399, ECE 0.095**; per-step ECE
0.077–0.112 — no degradation across the horizon. Artifact:
`models/calibration_v1.json`. The model is over-confident in low-probability
bins; reported as-is on the Benchmarks page.

## Lead time — attack onset (limited)

`models/metrics_lead_time.json` (rerun: `python -m src.evaluation.lead_time`):
the test split contains **1 attack onset** and the model did not warn before
it (warned_rate 0.0). CIC-2018 attacks start abruptly from clean baselines;
pre-onset warning on this data is close to impossible (verified with
`scripts/diagnose_leadtime.py` — flat ~0.52 base-rate output from clean
inputs). The citable lead-time evidence is the LIVE rehearsal: sustained UDP
sweep crosses threshold at the 4th window (0.03 → 0.03 → 0.17 → 0.905).

## Lead time — stage transition (limited, NEW 2026-09-04)

`models/metrics_stage_lead.json` (rerun: `python -m src.evaluation.stage_lead`):

| Split | Warnable stage onsets | Warned | Median lead |
|---|---|---|---|
| test | 1 (Lateral Movement) | 1 | 5 windows = **2.5 min** |
| val | 2 (Lateral Movement) | 2 | 5 windows = 2.5 min |

Both V1 (single stage head) and V3 (per-step stage decoders) warn on all
available onsets. **The sample is 1–3 onsets — too small to be a headline**;
it is recorded as a limited result, not a claim.

## Per-step stage accuracy (V3, measured with caveat)

V3's stage decoders score 1.0 / 1.0 / 1.0 / 1.0 / 0.958 across steps on the
test split (n=215 staged sequences). **Caveat: the test split is dominated by
one stage (Infiltration → Lateral Movement), so this is majority-class
inflation, not discrimination.** Stage supervision is the sequence-level
dominant stage (V1 label granularity). Recorded in `_stage` of the V3 metrics.

## Live rehearsal (measured, real packets, 2026-08-30)

| Scenario | Verified numbers |
|---|---|
| Benign Wi-Fi (two-device) | worst peak 0.014, all LOW |
| SYN scan | Recon rule within ONE window; model LOW 0.02–0.07 (by design) |
| UDP sweep (two-device) | 0.03 → 0.03 → 0.17 → **0.905** → 0.968 → 0.988 |
| UDP sweep (loopback) | 0.022 → 0.384 → 0.947, holds 0.977–0.989 |

Full verified-numbers section: `docs/DEMO_RUNBOOK.md`.

## Negative results (kept on purpose)

1. **V2 state head** — did not improve CIC2018 forecasting (PR-AUC 0.605 vs
   V1 0.657). Stated in `MODEL_CARD.md`.
2. **V3 does not beat V1 either** (0.633 vs 0.657) — the honest conclusion is
   that on CIC2018 alone, decoding risk from rolled-out states costs some
   ranking quality vs the direct head. The multi-dataset experiments
   (Phases 7–8) will retest with diverse data.
3. **Offline onset lead time** — 0.0 warned rate (see above).
4. **Multi-dataset pooling did not improve CIC2018 in-domain** (Phase 7,
   2026-09-04, time-boxed) — measured twice: the 9-feature pooled v1
   (CIC2018 + UNSW-NB15, `models/multidataset_v1/`) scores 0.3195 PR-AUC on
   CIC2018's test split vs V1's 0.6565 with all 18 features; the 3-dataset
   v2 (+ CTU-13 7/13 scenarios, `models/multidataset_v2/`) slips to 0.2147.
   Pooled test improved 0.8961 → **0.9348** and CTU-13 in-domain is
   **0.9918** — more diverse data helps the pooled forecaster while costing
   CIC2018 in-domain precision. UNSW-NB15's chronological test split is
   degenerate (418/418 attack windows → 1.000 means "separable", disclosed).
   Also recorded: a single pooled threshold does not transfer across
   datasets (v2's 0.643 fires zero alarms on CIC2018/UNSW despite usable
   ranking — per-dataset thresholds are the recorded fix). Full detail:
   `models/metrics_multidataset.json` (keys v1/v2) +
   `models/metrics_cross_dataset.json`, §8.4 of `docs/PROTOTYPE_MASTER.md`.
   Leave-one-dataset-out and single-dataset baselines were skipped for the
   demo deadline — recorded in the artifact.

## Rules that govern every number above

- Chronological split with day-boundary purge; no random splits.
- Threshold picked on VALIDATION only; test numbers are honest.
- Missing = unavailable, never zero.
- Every artifact hash-pinned by `tests/test_golden_regression.py`.
- Live inputs are domain-conditioned (disclosed: IP features zeroed, ratios
  clamped to training p99); rule engine and evidence always see RAW values.
