# CyberForecaster — SIH26153

Temporal attack-progression forecasting:
`flows → 30s window states → LSTM → K-step probability forecast + ATT&CK stage + attribution`.

Two demo surfaces, one model: an **offline scenario console** (cached real
predictions from CSE-CIC-IDS2018) and a **live sensor** (Npcap capture →
same windows → same forecaster, detection verified by rehearsal).

**Read `../SIH26153_battle_plan.md` first. Demo day: `docs/DEMO_RUNBOOK.md`.**

## Setup

```bash
cd cyberforecaster
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Smaller download on CPU-only machines:
`pip install torch --index-url https://download.pytorch.org/whl/cpu`

## Quickstart

```bash
# 0) Sanity-check the whole spine on synthetic flows — no download needed
python tests/smoke_synthetic.py      # must print SMOKE TEST PASSED

# 1) See what's in the dataset bucket + real sizes BEFORE pulling anything
python scripts/download_data.py --list
python scripts/download_data.py --yes

# 2) Rebuild every artifact in the right order (stops at the first failure)
python scripts/rebuild_all.py

# 3) The demo stack (FastAPI + Next.js — the primary demo surface)
python -m uvicorn api.main:app --port 8000 --log-level warning   # terminal 1
cd web && npm install && npm run dev                             # terminal 2 → http://localhost:3000

# 3b) Legacy Streamlit fallback (kept demo-ready)
streamlit run app/streamlit_app.py
```

`rebuild_all.py` is the safe path. The individual steps, in dependency order:

```bash
python -m src.preprocessing.pipeline --raw data/raw --out data/processed  # → windows + sequences + scaler
python -m src.models.baseline_logreg --dir data/processed                 # PS-required benchmark
python -m src.models.lstm_forecaster --dir data/processed --epochs 40     # temporal model
python -m src.evaluation.lead_time   --dir data/processed                 # the differentiator
python scripts/build_demo_cache.py                                       # crash-proof fallback
python scripts/verify_state.py                                           # audit before demoing
```

**Always run `python scripts/verify_state.py` before a rehearsal.** It checks that
`scaler.npz`, the `.npz` splits and `lstm_config.json` agree on the feature count.
A mismatch means the saved model does not match the current data, and the app will
mispredict *silently*.

Training on Colab: `notebooks/Colab_Training.ipynb` — upload `scaler.npz` too, and
bring back `metrics_lstm.json`, not just the weights.

## Live demo (real packets → real forecasts)

```bash
# 1) Record ~12 min of benign history on the demo network (once per network)
python scripts/record_seed.py --minutes 12 --iface "<wi-fi NPF name>"

# 2) Rehearse the attack chain end-to-end BEFORE demo day (exit 0 = flagged)
python scripts/live_rehearsal.py --minutes 6 --attack udp-sweep --attack-at 0.3 \
    --iface "\\Device\\NPF_Loopback"
```

Then on the web console: **Live** page → start capture → attacker device runs
`scripts/attacks/` (see its README). Verified Aug 30: benign all LOW (worst
0.554 < 0.561); UDP sweep crosses 0.022 → 0.384 → 0.947 over three windows.

Two-engine layering, by design: the rule engine catches a SYN scan within one
window; the LSTM forecasts progression only under sustained attack shapes.
`src/live/` maps packets to the exact training window features
(`packet_windower`), seeds history so the model has its 10-window context
(`history`), and the sensor resolves the live interface via the default route
(Npcap quirks — see comments in `sensor.py`).

## Repo map

```
configs/data_sources.yaml        curated download list — verify day↔attack mapping
scripts/
  download_data.py               S3 listing + prioritized pull (no blind 7GB downloads)
  rebuild_all.py                 every artifact, correct order, fails fast
  verify_state.py                pre-demo audit: env, data, artifact consistency
  build_demo_cache.py            freeze real predictions → offline, deterministic demo
  day_report.py                  per-day diagnostics: labels, coverage, rule validation
src/
  ingestion/csv_loader.py        load + label canonicalization + dup-header/NaN/inf cleanup
  preprocessing/pipeline.py      clean → windows → sequences → chronological split + scaler
  features/
    window_builder.py            flows → 30s aggregates; L=10/K=5 sliding sequences
    scaling.py                   THE shared input transform (log1p + standardise)
  models/
    baseline_logreg.py           logistic benchmark, one model per horizon step
    lstm_forecaster.py           2-layer LSTM → K progression logits + stage head
  forecasting/
    rollout.py                   Forecaster bundle: model + transform + threshold
    scenarios.py                 demo scenarios, shared by app and cache builder
  evaluation/lead_time.py        early-warning lead time — LSTM vs baseline
  explainability/attribution.py  Captum IG over time; permutation fallback
  attack_mapping/mitre_mapper.py family→stage table + rule predictor + validation
  live/                          Npcap/scapy capture → live windows → forecasts
    sensor.py                    sniffer thread; default-route iface resolution
    packet_windower.py           packets → the exact training feature vector
    history.py                   seed + live windows; model_matrix (IP-zeroing)
api/                             FastAPI: offline scenarios + /api/live/* routes
web/                             Next.js console: forecast, benchmarks, live
app/streamlit_app.py             fallback demo UI: timeline / risk / WHY / ATT&CK / benchmark / lead time
```

## Honesty rails (do not remove)

- **The app badges its own mode**: `REAL` (live inference) · `CACHED` (precomputed
  *real* predictions) · `SIMULATED` (extrapolated placeholders). Never let a
  rehearsal run in a fallback mode by accident — the sidebar prints why.
- **One transform, one place.** `features/scaling.py` is imported by the baseline,
  the LSTM and the app. The logistic baseline used to scale its inputs while the
  LSTM got raw features, which made the PS-required benchmark unfair *against* our
  own model. Any fix applied in only one place drifts again.
- **`y_prog` is per horizon step**, shape `(n, K)`. It was originally one bool
  broadcast to all K heads — that trains every head on an identical target, so the
  forecast curve is mathematically flat and "risk trajectory" is unsupportable.
  `tests/smoke_synthetic.py` now asserts against the regression.
- **Thresholds are picked on validation** under a stated FPR budget
  (`baseline_logreg.MAX_FPR`), never on test, never by feel on demo day. `0.5` is
  not a decision.
- **Metrics come from the scripts.** Never hand-typed.
- **Splitting is chronological with boundary purge** (`window_builder.chrono_split`)
  — no random shuffling anywhere.
- **Validation AP is computed once over the pooled split.** Averaging per-batch AP
  is not AP: with ~10% positives many batches contain no positives at all, so
  checkpoint selection was being driven by noise.

## Known data limitations (state these before a judge finds them)

- CSE-CIC-IDS2018's ML-ready CSVs contain **no `Src IP` / `Dst IP` columns**. So
  `unique_src_ips` / `unique_dst_ips` are constant 0 in training; the live
  pipeline **zeroes them in model input** (`src/live/history.py: model_matrix`)
  because nonzero values are out-of-spec and push benign toward "attack"
  (measured 0.613 → 0.554 vs threshold 0.561). The rule engine still uses the
  real IP counts live — where the MITRE **lateral-movement rule** is armed via
  a live-only `lateral_port_share` (SMB/RPC/RDP/WinRM); offline it abstains
  rather than firing on a fabricated threshold. `validate_rules()` prints this.
- Labels are messy — casing variants, embedded duplicate header rows, NaN/inf rate
  columns, epoch-artifact timestamps parsing as 1970. `csv_loader` handles all of
  these and reports what it fixed.
- The **Infiltration** class has only dozens of samples, so we forecast across
  attack families at window level rather than infiltration-only (battle plan §5.1).
- Feb-14 is truncated at 13:00 (brute-force only, no Heartbleed).
