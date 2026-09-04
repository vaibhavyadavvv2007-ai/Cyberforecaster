# AUDIT — system state before the multi-dataset / world-model refactor

Date: 2026-09-04. Written from direct code reading (file:line references
below). This is the authoritative "before" record; the frozen artifacts it
describes live in `models/baseline_cic2018_v1/`.

---

## 1. Model architecture

`src/models/lstm_forecaster.py` — class `TemporalForecaster` (line 53):

```
input (B, L=10, F=18)
  → nn.LSTM(18, hidden=64, layers=2, dropout=0.2, batch_first)
  → head: Linear(64→32) + ReLU + Dropout(0.2)            (line 60)
  → prog_head:   Linear(32→K=5)   per-horizon attack probability
  → stage_head:  Linear(32→6)     dominant ATT&CK stage over horizon
```

- Direct multi-horizon heads (teacher-forced per-step labels), NOT recursive
  rollout. `recursive_latent_rollout()` in `src/forecasting/rollout.py:133`
  is a deliberate `NotImplementedError` (Tier-3 stretch).
- Loss: `BCEWithLogitsLoss(pos_weight per horizon step) + CrossEntropyLoss(ignore_index=-1)`
  (`lstm_forecaster.py:141`). Per-step pos_weight computed from train only (line 121).
- Early stop: patience 25 on pooled validation AP (line 50 — the comment
  documents the original patience-8 under-fitting bug).
- Checkpoint selection: pooled val AP computed ONCE over the whole val split
  (line 154), not per-batch averaged (that was the second historical bug).
- Footprint: 57,227 params · 0.23 MB · ~2.6 ms/sequence CPU (`_measure_cost`, line 89).

### ⚠️ STATE HEAD: DOES NOT EXIST

The refactor plan assumed "the current code already contains the
state-reconstruction head, but it has not yet been retrained." **That is
false.** `TemporalForecaster.forward` returns exactly `(prog_logits,
stage_logits)` (line 65-68). There is no state/future-feature head anywhere:
no head producing `S(t+1..K)`, no state loss term, no state metrics. Phase 6
of the refactor is therefore an **addition** (new head + loss + metrics), not
a retraining of an existing head. This changes effort estimates: the model
class, training loop, config and metrics all need a new (backward-compatible)
code path.

## 2. Features (the current 18)

`src/features/window_builder.py:23-28` — `WINDOW_FEATURES`, exact order:

| # | Feature | Definition (CICFlowMeter source) | Notes |
|---|---|---|---|
| 1 | flow_count | flows per bin | |
| 2 | bytes_total | Σ TotLen Fwd+Bwd Pkts | |
| 3 | pkts_total | Σ Tot Fwd+Bwd Pkts | |
| 4 | duration_mean | mean Flow Duration (µs→s) | |
| 5 | syn_ratio | Σ SYN Flag Cnt / flows | |
| 6 | ack_ratio | Σ ACK Flag Cnt / flows | |
| 7 | fin_ratio | Σ FIN Flag Cnt / flows | |
| 8 | rst_ratio | Σ RST Flag Cnt / flows | |
| 9 | psh_ratio | Σ PSH Flag Cnt / flows | |
| 10 | unique_dst_ports | nunique Dst Port | |
| 11 | auth_port_share | flows to {20,21,22,23,3389} / flows | |
| 12 | unique_dst_ips | nunique Dst IP | **zero-variance in training** (no IP cols in CSVs) |
| 13 | unique_src_ips | nunique Src IP | **zero-variance in training** |
| 14 | dst_port_entropy | H(dst port counts) | |
| 15 | iat_mean | mean Flow IAT Mean (µs→s) | |
| 16 | iat_std | mean Flow IAT Std (µs→s) | |
| 17 | avg_pkt_size | mean Pkt Size Avg | column name verified "Pkt Size Avg" (csv_loader.py:25) |
| 18 | down_up_ratio | mean Down/Up Ratio | |

Supervision columns (never model inputs): `attack_frac`, `dominant_stage_idx`,
`frac_<stage>` × 6.

Missing-feature handling today: `_sum/_mean` zero-fill with a printed warning
(`window_builder.py:60-70`) — the exact "silently becomes zero" failure the
new availability-mask design must eliminate.

## 3. Scaling

`src/features/scaling.py` — ONE shared transform (the module docstring
records the original bug: baseline scaled, LSTM raw):
- log1p on 11 heavy-tailed features (`LOG_FEATURES`, line 25), then
  per-feature standardize.
- Fitted on TRAIN sequences only; zero-variance features get scale=1 (line 62).
- Saved `data/processed/scaler.npz`; loaded by training, Forecaster, live.

## 4. Bin size — current state (the "30 vs 60" question)

- **Production: 30 s.** `data/processed/meta.txt` and
  `data/processed_30s/meta.txt` both record `bin_secs=30`.
- `api/live_state.py:14` hard-codes `BIN_SECS = 30` ("must match meta.txt").
- `LiveWindowBuilder(bin_secs=30)` default (`packet_windower.py:139`).
- **Stale defaults remain**: `build_windows(flows, bin_secs=60)` default
  (`window_builder.py:40`), `pipeline.run(..., bin_secs=60)` default and
  argparse default (`pipeline.py:26,106`), and the window_builder docstring
  still says "60-second bins, ~24 aggregate features" (line 7) — wrong on
  both counts. The 60s artifacts are preserved in `models/ab_60s_backup/`
  and `data/processed_60s_backup/`.
- **Conclusion: training = live = 30 s is ALREADY aligned.** The refactor
  must make the value single-sourced (config), not hard-coded in three
  places, and fix the stale docstrings/defaults.

## 5. Training flow

`python -m src.preprocessing.pipeline --raw data/raw --out data/processed --bin-secs 30`
→ `python -m src.models.lstm_forecaster --dir data/processed`

- Ingestion: `src/ingestion/csv_loader.py` — handles padded headers, embedded
  duplicate header rows, label-spelling canonicalization (`_canonical_label`
  line 39; dataset's "Infilteration" typo handled line 47), bad timestamps
  (year-plausibility filter line 108), inf/NaN cleanup.
- Windows: `build_windows` → `make_sequences` (X (n,10,18), y_prog (n,5)
  PER-STEP labels — the fix that made the trajectory non-flat;
  y_stage (n,) dominant-stage-or-−1, `ends` absolute positions for lead-time).
- Split: `chrono_split` (window_builder.py:182) — 70/15/15 chronological with
  day-boundary purge (margin = max(L,K)); **no random split anywhere**.
- Threshold: picked on VAL at max_fpr 0.05 (`baseline_logreg.pick_threshold`),
  applied to test. 6,192 windows / 4,145-881-916 sequences.
- Artifacts: `windows.parquet`, `sequences_{train,val,test}.npz` (X stays RAW;
  transform applied at load), `scaler.npz`, `meta.txt`; model side:
  `lstm_forecaster.pt` (state_dict, `weights_only=True` at load —
  rollout.py:48), `lstm_config.json`, `models/metrics_lstm.json` etc.

## 6. Inference flow

`src/forecasting/rollout.py` — `Forecaster` bundles model+scaler+threshold
(cannot diverge). `predict(x_raw)` → scaled → probs (K), stage, threshold.
`api/state.py` loads everything once at import; mode property:
REAL (forecaster loaded) / CACHED (demo_cache.json) / SIMULATED
(damped-momentum placeholder, `simulated_forecast` state.py:33).

## 7. Explainability

`src/explainability/attribution.py` — Captum IntegratedGradients on the
sequence input, |IG| summed over time → (F,) per-feature importance for one
prediction; explains the furthest horizon step by default. Fallback: sklearn
permutation importance (global, not per-prediction). Used in both
`/api/forecast` and live `predict()` (top-6 features).

## 8. ATT&CK mapping + rule engine

`src/attack_mapping/mitre_mapper.py`:
- `STAGES` (6): Reconnaissance, Initial Access, Lateral Movement,
  Command & Control, Exfiltration, DoS.
- `FAMILY_STAGE` (13 families → stages), incl. the honest DoS-as-separate-
  category decision.
- `rule_based_stage()` — 6 ordered rules (line 72): scan (ports≥15 ∧
  syn≥0.4), auth burst, DoS (p99 volume), C2 beaconing (regular timing, low
  jitter, pkts≥30 floor — added after the live FP), lateral movement
  (requires `lateral_port_share` live-only signal), exfiltration (p99 bytes).
  `has_ip` auto-detection handles the training-CSVs-have-no-IPs gap.
- `validate_rules()` crosstab vs labels, run inside the pipeline.
- **No ATT&CK technique IDs, no mitigations/detection data, no CAPEC** —
  the knowledge-base layer (plan §17-18) is entirely new.

## 9. Live pipeline

`src/live/sensor.py` (AsyncSniffer, BPF `ip and (tcp or udp)`, packet →
`observe`) → `src/live/packet_windower.py` (`LiveWindowBuilder`: bidirectional
flow key, Welford IAT — the `iat_m2` bug fix is documented line 96-99,
flush per 30 s wall-clock bin, empty bins are explicit zero windows) →
`src/live/history.py` (`LiveHistory`: seed 18 windows + live ≤240, predict →
probs/peak/level/stage/crossing/why/rule_stage, events fire when peak ≥ thr).
- Input conditioning (`history.py:33-70`): IP features zeroed (constant 0 in
  training), 6 ratio features clamped to training p99 (loaded from
  windows.parquet). Rule engine always sees raw values. `has_ip=True` live.
- `api/live_state.py` — `LiveService` singleton; feed() drains one bin per
  poll, annotates `forecast_peak` retroactively.
- Seed: `data/live/seed_windows.json` (recorded benign, `scripts/record_seed.py`).

## 10. API surface (`api/main.py`)

| Endpoint | Purpose |
|---|---|
| GET /api/health | mode, boot/model errors, window count, threshold |
| GET /api/scenarios | offline demo scenarios (from `forecasting/scenarios.py`) |
| POST /api/forecast | probs (K), peak, level, stage, rule_stage, threshold, crossing_step, why (top-6 IG), why_note; honors REAL/CACHED/SIMULATED |
| GET /api/timeline | observed attack_frac + forecast overlay for a scenario |
| GET /api/metrics | all metrics_*.json namespaced (dup-key hazard documented state.py:80) |
| GET /api/flagged | top attack windows table |
| GET /api/live/status | sensor status, seed/live counts, ready, events |
| POST /api/live/start | start capture (iface optional, seed optional) |
| POST /api/live/stop | stop |
| GET /api/live/feed | everything the Live page polls (windows, latest forecast, events) |
| GET /api/live/interfaces | Npcap interface list |

Missing for the refactor: upload endpoint, dataset registry endpoint,
decision-support endpoint, state-trajectory / uncertainty / evidence fields.

## 11. Web UI

Next.js 15 (App Router) pages: `/` (offline console: forecast hero, timeline,
flagged windows, scenarios), `/live` (capture controls, live windows chart,
events), `/benchmarks` (metrics tables). Components: `ForecastChart`,
`AttackProgression`, `WhyPrediction`, `ModelStatus`, `ui.tsx` primitives.
API client in `web/lib/api.ts`. No upload page, no decision-support panel,
no datasets page.

## 12. Datasets & metrics

- Only CSE-CIC-IDS2018 (7 curated day-files, ~2.1 GB raw, list in
  `configs/data_sources.yaml` with verified per-day labels). CTU-13 URL
  noted as Tier-2 future work — never downloaded.
- Metrics: `models/metrics_lstm.json` (test PR-AUC 0.656, precision 0.88,
  recall 0.14, FPR 0.006, per-step), `metrics_baseline.json` (logistic
  PR-AUC 0.333), `metrics_lead_time.json` (honest: onset lead time 0).
- No calibration metrics (Brier/ECE), no per-horizon state metrics, no
  cross-dataset evaluation.

## 13. Tests

`tests/smoke_synthetic.py` only — a synthetic smoke script, NOT a pytest
suite. No unit tests, no API contract tests, no fixtures. The refactor's
test suite (plan §53) starts from zero.

## 14. Verified inconsistencies & known limitations

1. **Stale 60s references** (see §4): window_builder docstring, function
   defaults in `build_windows`/`pipeline.run`/argparse. Production is 30s.
2. **Stale "~24 features"** in window_builder docstring (actual 18).
3. **Stale "~430 val sequences"** in lstm_forecaster.py:46 comment (actual 881).
4. **Patience-8 bug + per-batch-AP bug** — both fixed; comments preserve the
   history (good, keep).
5. **IP features are dead in training** (zero variance) but meaningful live —
   bridged by conditioning, not by better data. Multi-dataset work must make
   IP-derived features actually trainable (CTU-13/CICIoT2023 have IPs).
6. **C2 rule benign false-positive on very quiet networks** — observed live
   Sep 4 on the 10.71.x network (benign window tagged C2; produced no event
   because peak < threshold). Needs an activity floor review when the rule
   engine is touched.
7. **`data/processed` vs `data/processed_30s`** duplication (demo_cache.json
   only in the former) — confusing; the refactor's manifest should own this.
8. **Lead time for onset is honestly 0** — dataset has no pre-onset signal;
   stage-transition lead time (plan §37) is the defensible replacement.
9. **No state head** (see §1) — plan correction, biggest single gap to build.
10. **avg_pkt_size column-name trap** ("Pkt Size Avg") — verified & handled
    (csv_loader.py:24-28); adapters must re-verify per dataset.
11. `metrics_lead_time.json` contains its own `lstm_forecaster` key —
    namespaced at load (state.py:78-94); merging code must not flatten.

## 15. What must NOT change (demo-critical contract)

Until the Sep 5 internal demo is over: `api/main.py` route behavior,
`api/state.py` load paths, `src/live/*`, `models/trained_models/`,
`data/processed/*` — all frozen in behavior. The frozen copy in
`models/baseline_cic2018_v1/` guarantees recoverability afterwards.
