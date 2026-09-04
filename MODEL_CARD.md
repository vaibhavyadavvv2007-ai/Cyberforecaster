# MODEL CARD — CyberForecaster SIH26153

**Model:** `cic2018_v1` (frozen production baseline) · **Date:** 2026-09-04
**Task:** temporal network-attack forecasting — predict the attack fraction of
the next five 30-second windows and the dominant ATT&CK stage, from the last
ten observed windows.

## 1. Model architecture

- `TemporalForecaster`: LSTM(18 → 64, 2 layers) → linear head producing 5
  horizon steps (attack fraction per step).
- Input: 10 consecutive 30-second windows × 18 flow features (volume, TCP flag
  ratios, port/address behavior, inter-arrival statistics, directionality).
- Independent rule engine (threshold-based, no ML) runs alongside for
  instantaneous reconnaissance detection; the LSTM provides the forecast.
- Threshold **0.5612** chosen on the validation PR curve (not test).
- Weights: `models/trained_models/lstm_forecaster.pt` (234,073 bytes,
  sha256-16 `2b41bec7be520540`); scaler `data/processed/scaler.npz`
  (`5e6be0e74fc7ecde`). Both pinned by `tests/test_golden_regression.py`,
  together with byte-identical copies in `models/baseline_cic2018_v1/`.

## 2. Training data

- **CSE-CIC-IDS2018**, 7 daily flow-CSV captures (Wed 14 Feb – Thu 1 Mar
  2018), aggregated into **6,192 30-second windows** (764 windows with attack
  fraction > 0.5; mean attack fraction 0.121).
- Chronological train/val/test split with boundary purge — **no random
  splits, no leakage** (test windows never precede training windows).
- Labels: per-window attack fraction derived from the dataset's flow labels;
  stage labels from the ATT&CK stage mapping of CIC attack categories.

## 3. Evaluation (held-out test split, chronological)

| Metric | LSTM forecaster | Logistic baseline |
|---|---|---|
| Precision @ threshold | **0.882** | 0.500 |
| Recall @ threshold | 0.140 | 0.009 |
| F1 | 0.241 | 0.018 |
| False-positive rate | **0.006** | 0.003 |
| PR-AUC | **0.656** | 0.333 |

Source artifacts: `models/metrics_lstm.json`, `models/metrics_baseline.json`
(namespaced in `/api/metrics`; the Benchmarks page renders them verbatim).

**Calibration** (`models/calibration_v1.json`): pooled n=4,580,
Brier **0.1399**, ECE **0.095**; per-step ECE 0.077–0.112 with no degradation
across the horizon. The model is over-confident in low bins — reported as-is,
and MC-dropout bands (below) communicate this uncertainty rather than hiding it.

**Uncertainty:** seeded MC-dropout (T=16, state-restoring, deterministic per
seed) with HIGH (<0.05 max σ) / MEDIUM (<0.15) / LOW bands.

**Lead time (honest limitation):** on the test split there is only **1 attack
onset**, and the model did not cross threshold before it (warned_rate 0.0,
`models/metrics_lead_time.json`). The test split is too onset-poor to
estimate offline lead time. Demonstrated instead in **live rehearsal** on real
captured traffic (Aug 30, 2026): UDP sweep forecast climbed 0.03 → 0.17 →
0.905 → 0.968 → 0.988 over consecutive windows, crossing on the 4th sustained
window; benign traffic stayed ≤ 0.014. Cite the rehearsal numbers for lead
time, not an offline metric we cannot support.

## 4. Live-input conditioning (disclosed, not hidden)

Training CSVs carry no IP columns (constant 0) and long-lived aggregate flows.
Live capture sees both. Every live/upload window is conditioned to the
model's validated input domain before inference: IP-count features zeroed and
flag-ratio/down_up features clamped to the training p99. The rule engine and
the evidence panel always see the **raw observed** values. Without this
conditioning a quiet network's benign traffic reads 0.69 (false alarm);
with it, 0.014, and attacks still cross 0.95+.

## 5. Experimental variants (not deployed)

**V2 — `world_model_v2`** (state head, `src/models/world_model.py`): adding an
explicit ATT&CK state head did **not** improve attack forecasting on
CIC2018 alone — best λ=0.5: PR-AUC 0.605 vs baseline 0.657, precision 0.881
vs 0.882, state cosine 0.227. Recorded as a negative result; the multi-dataset
experiments (Phases 7–8) will re-test the state head with more diverse data.

**V3 — rollout world model** (`src/models/rollout_world_model.py`, added
2026-09-04; artifacts `models/world_model_v3/lambda_0.5_huber/`): the genuine
state-transition architecture — the encoder initializes Ŝ(t+1), a residual
transition rolls the state forward autoregressively to Ŝ(t+K), and the attack
risk and per-step ATT&CK stage are **decoded from each forecast state**
(risk/stage cannot diverge from the state trajectory). Results on the same
test split: PR-AUC 0.633 (V1: 0.657) at its own val-picked threshold 0.894
(precision 1.000, recall 0.065, FPR 0.000); state cosine 0.257 (V2: 0.227);
stage-transition lead time identical to V1 on the available onsets (1 test
onset, warned 5 windows = 2.5 min early — sample too small for a claim, see
`docs/EVALUATION.md`). **Honest verdict: V3 does not beat V1's direct head on
CIC2018 alone either.** Its value is architectural (a true P(S_{t+1}|S_t)
chain with per-step stage, exposed as the additive `future_steps` field in
`/api/forecast`); whether diverse multi-dataset data changes the verdict is
exactly what Phases 7–8 will measure. V1 remains the deployed demo model.

**Multidataset-V1 — `models/multidataset_v1/`** (Phase 7, added 2026-09-04,
time-boxed for the internal demo): the V1 architecture at n_feat=**9** — the
honest three-way intersection of the legacy 18 (CIC2018's ML-ready CSVs ship
no IP columns, so `unique_src/dst_ips` cannot enter a shared feature set) —
trained pooled on **CIC2018 + UNSW-NB15** (CTU-13's 34 GB archive was still
extracting at training time), 8 epochs, threshold 0.5694 validation-picked.
Pooled test PR-AUC **0.8961** (P 0.966 / R 0.681 / FPR 0.021, n=1,334).
Per-dataset: UNSW-NB15 1.000 on a **degenerate all-attack test split**
(418/418 attack windows — separable, not proof of a great forecaster);
CIC2018 **0.3195, below V1's 0.657** — the honest capability/precision
trade-off of a 9-feature pooled model. Leave-one-dataset-out and
single-dataset baselines were skipped for the demo deadline and are recorded
in `models/metrics_multidataset.json` (`"skipped"` key). **Not deployed; V1
remains the demo model.**

**Multidataset-V2 — `models/multidataset_v2/`** (Phase 7, same day): adds
**CTU-13 (7/13 scenarios, partial build flagged in the artifact — 4,413
windows from 8.78M NetFlow records, scenarios 2/3/6/9/11/13 still
extracting)** to the v1 pool. Same protocol (8 epochs, 9-feature
intersection, threshold 0.6426 validation-picked). Results: pooled test
PR-AUC **0.9348** (P 0.992 / R 0.322 / FPR 0.004); CTU-13 in-domain
**0.9918** (P 0.992 / R 0.693 / FPR 0.097) — the forecaster learns botnet
C2 dynamics well from the intersection features alone. CIC2018 in-domain
slips further to **0.2147**, and the pooled threshold fires zero alarms on
CIC2018/UNSW test splits despite usable ranking — **score scales differ per
dataset; per-dataset thresholds are the recorded fix** (future work). **Not
deployed; V1 remains the demo model.**

## 6. Intended use & decision support

- **Intended:** early-warning indicator and triage aid for network defenders
  in SOC-like settings, with human-in-the-loop decision support: evidence rows
  (observed value vs benign baseline, z-score, attribution), ranked P1–P3
  recommendations, ATT&CK technique enrichment from the official MITRE STIX
  bundle, and a MONITOR → INVESTIGATE → CONTAINMENT REVIEW → ESCALATE ladder.
- **NOT intended / hard limits:**
  - **No automated response.** The system never blocks, drops, or reconfigures
    anything — recommendations only; the analyst decides.
  - **No autonomous attribution** and no identification of specific attackers.
  - The deployed model is single-dataset trained (CIC-IDS2018). The
    multi-dataset experiments (v1/v2, §5) measured that pooling 2–3 datasets
    through the 9-feature intersection does NOT transfer to CIC2018
    in-domain (0.32 / 0.21 vs 0.657) — cross-network generalization remains
    an open limitation, now with numbers attached.
  - Low recall at the operating threshold: it misses most attack *moments* by
    design — the point is high-precision warning ahead of sustained attacks,
    not per-window detection.
  - No LLM anywhere in the explanation path; all explanations are
    deterministic templates over real model outputs.

## 7. Fairness, privacy, ethics

- The system profiles **traffic**, not people; no user identifiers are
  modeled. Live capture runs on the operator's own network with consent.
- Uploaded captures are parsed, never executed (magic-byte detection,
  100 MB cap, temp files always cleaned; `torch.load` restricted to
  `weights_only=True`).
- Honesty contract enforced end-to-end: REAL / CACHED / SIMULATED badges;
  missing features are reported as unavailable, never zero-filled; every
  displayed number traces to an artifact on disk.

## 8. Reproducibility

- Golden regression suite (`tests/test_golden_regression.py`, 12 tests) pins
  artifact hashes and exact model outputs; **163 tests green** overall.
- Frozen baseline copy: `models/baseline_cic2018_v1/` (byte-identical, test-
  enforced). The old model stays runnable at all times.
- Config single-sourced in `src/config.py` (BIN_SECS=30, L=10, K=5).
- Dataset manifest: `configs/dataset_manifest.yaml`; adapter registry:
  `src/datasets/registry.py` (statuses reported honestly per dataset).
- Git: commits disabled during the build per team decision; last commit of
  record at freeze time: `7d5c827` ("ppt"). All phase evidence lives in
  `MASTER_IMPLEMENTATION_PLAN.md`.
