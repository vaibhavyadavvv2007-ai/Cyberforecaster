# ACCEPTANCE CHECKLIST — SIH26153 CyberForecaster

Maps every acceptance criterion from `MASTER_IMPLEMENTATION_PLAN.md` §"Final
acceptance criteria" to concrete, verifiable evidence in this repo. Status
date: 2026-09-04. Anything marked ⏳ is honestly incomplete — with the reason
and what unblocks it.

## Legend

✅ done + test/evidence · 🔍 done, verify by inspection · ⏳ blocked (reason)

## 1. Data layer works per-dataset with manifests

| Criterion | Status | Evidence |
|---|---|---|
| Adapter contract (one interface, per-dataset) | ✅ | `src/datasets/adapters.py` (base class); `tests/test_dataset_adapters.py` (16 tests) |
| Registry with honest per-dataset status | ✅ | `src/datasets/registry.py`; statuses surface at `/api/datasets`, pinned by `tests/test_golden_regression.py::test_api_datasets_registry` |
| Dataset manifest | ✅ | `configs/dataset_manifest.yaml` (+ `configs/datasets/` per-dataset) |
| CIC2018 adapter live | ✅ | powers the frozen baseline end-to-end |
| **UNSW-NB15 adapter wired** | ✅ | `src/datasets/unsw_nb15.py` (2026-09-04, files verified byte-exact); 21 tests incl. real-file smoke; status READY |
| CIC2017 / CTU-13 / CICIoT2023 adapters wired | ⏳ | **User stop point**: CIC2017 needs registration download; CTU-13 tar.bz2 ~75% downloaded in background; pending adapters raise loudly instead of guessing — never silently READY |
| No blind concatenation; capability matrix | ✅ | `docs/AUDIT_BEFORE_MULTIDATASET.md` + canonical schema availability masks (missing = unavailable, never zero — enforced and tested) |

## 2. Canonical schema + availability mask enforced everywhere

| Criterion | Status | Evidence |
|---|---|---|
| 48-feature schema, groups A–G | ✅ | `src/features/canonical_schema.py`, schema hash `a9570d8349141d92` |
| Every feature slot carries (value, available, source) | ✅ | `tests/test_feature_schema.py` |
| Single windowing/scaling engine for train/live/upload | ✅ | `src/features/sequence_engine.py` (gap-fill, masked CanonicalScaler with hash guard, chrono split + purge); `tests/test_sequence_engine.py`; live/upload verified to use it |
| Config single-sourced | ✅ | `src/config.py` (BIN_SECS=30, L=10, K=5) |
| Packet-level extraction (Group E) | ✅ | `src/features/packet_features.py`; pcap round-trip byte-identical vs bare builder; `tests/test_packet_features.py` |

## 3. State head + future-state metrics

| Criterion | Status | Evidence |
|---|---|---|
| WorldModelForecaster (V1 untouched) | ✅ | `src/models/world_model.py`; V1 weights reproduce prog/stage byte-identically (test-verified) |
| State head trained + swept on CIC2018 | ✅ | `models/world_model_v2/lambda_*/`; λ sweep log preserved |
| Honest result recorded | ✅ | λ=0.5 best: PR-AUC 0.605 vs V1 0.657 — **did not improve on CIC2018 alone**; stated in `MODEL_CARD.md` §5, not spun |
| Multi-dataset re-test of state head | ⏳ | Phases 7–8 (datasets landing) |

## 4. Forecasting: risk / stage / cross-dataset / calibration

| Criterion | Status | Evidence |
|---|---|---|
| Risk + stage forecast, threshold from val | ✅ | V1 LSTM, threshold 0.5612; goldens pin exact outputs |
| Chronological eval, no leakage | ✅ | metrics in `models/metrics_lstm.json`; splits in sequence engine |
| Calibration reported | ✅ | `models/calibration_v1.json`: n=4,580, Brier 0.1399, ECE 0.095; rendered on Benchmarks page |
| Uncertainty (MC-dropout, seeded) | ✅ | `src/explainability/uncertainty.py`; golden-pinned (T=16, seed=0) |
| Lead time | ✅/⚠️ | `models/metrics_lead_time.json`: offline test split has 1 onset, warned_rate 0.0 — **reported as a limitation** (`MODEL_CARD.md` §3); live-rehearsal lead time (0.17→0.905 crossing on 4th sustained window) is the citable number |
| Cross-dataset / LODO evaluation | ⏳ | Phases 7–8 (datasets landing) |

## 5. Explainability evidence-based with uncertainty

| Criterion | Status | Evidence |
|---|---|---|
| Evidence engine (observed vs benign baseline, z, direction) | ✅ | `src/explainability/evidence.py`; TRAIN-split-only baseline `models/benign_baseline.json`; std=0 → no claim |
| Temporal WHY (W-9..W-0) | ✅ | `src/explainability/temporal.py` |
| No LLM in the explanation path | ✅ | all templates over real model outputs; grep-clean |
| Evidence from RAW observed values (not conditioned inputs) | ✅ | `tests/test_live_enrichment.py` (ack_ratio=10.0 → observed 10.0, elevated, while model input is clamped) |
| UI renders it | ✅ | `web/components/EvidencePanel.tsx` on `/live` + `/analyze`; browser-verified |

## 6. Decision support: WHY/evidence/forecast/recs/priority/human-in-loop

| Criterion | Status | Evidence |
|---|---|---|
| Explicit escalation ladder | ✅ | `src/decision_support/levels.py` (MONITOR/INVESTIGATE/CONTAINMENT REVIEW/ESCALATE) |
| Ranked P1–P3 recommendations citing real evidence | ✅ | `src/decision_support/recommendations.py`; `tests/test_decision_support.py` (21 tests) |
| ATT&CK enrichment from official MITRE STIX | ✅ | `data/knowledge/mitre_attack/` (53.8 MB bundle, 160 KB index, 709 techniques); honest "knowledge base unavailable" when missing |
| Human-in-loop statement on every record | ✅ | test-enforced |
| **No automated response — nothing executes** | ✅ | rule 6; no write/block/drop call exists anywhere |
| UI renders it | ✅ | `web/components/DecisionSupportPanel.tsx`; verified on real captured traffic (MONITOR + real STIX mitigations) |

## 7. Product: upload + live + offline + honesty badges + benchmarks

| Criterion | Status | Evidence |
|---|---|---|
| PCAP/CSV upload with auto-detection + column mapper | ✅ | `src/ingestion/upload_pipeline.py`; POST `/api/analyze/upload`; magic bytes, never extension; unknown schema → 400 with mapper report; `tests/test_upload_pipeline.py` (13 tests) |
| Untrusted input parsed, never executed | ✅ | 100 MB cap, temp always cleaned, `torch.load(weights_only=True)` |
| Live pipeline with REAL/CACHED/SIMULATED badges | ✅ | preserved through Phase 13 (verified: enrichment degrades to legacy+nulls) |
| Offline scenarios | ✅ | `/` scenario page (unchanged, golden API tests) |
| Benchmarks page from real artifacts | ✅ | `/api/metrics` serves `models/metrics_*.json` verbatim |
| Datasets page (honest registry) | ✅ | `/datasets` renders `/api/datasets` |
| Nav updated | ✅ | Forecast · Live · Analyze · Benchmarks · Datasets; tsc clean |

## 8. Reproducibility artifacts

| Criterion | Status | Evidence |
|---|---|---|
| Model card | ✅ | `MODEL_CARD.md` (real metrics, honest limitations, hashes) |
| Config | ✅ | `src/config.py` |
| Scaler + model pinned | ✅ | sha256-16 pins in `tests/test_golden_regression.py` (change = failure with "update on purpose, never delete") |
| Frozen baseline never destroyed | ✅ | `models/baseline_cic2018_v1/` byte-identical (test-enforced) |
| Manifest | ✅ | `configs/dataset_manifest.yaml` |
| Full suite green | ✅ | **100 tests** (pytest, ~17 s) — rerun: `python -m pytest tests/ -q` |
| Git commit of record | ✅* | commits disabled per user constraint; last commit of record `7d5c827`; all phase evidence in `MASTER_IMPLEMENTATION_PLAN.md` |
| Frontend typecheck | ✅ | `cd web && npx tsc --noEmit` |

## Open items (all gated on datasets, per the user's stop point)

1. Phase 3 wiring for cic2017 / unsw_nb15 / ctu13 / ciciot2023 / darpa —
   files landing in `data/raw/`.
2. Phases 7–8: staged experiments B–F, three-regime (in-domain /
   cross-dataset / leave-one-out) evaluation reports.
3. Re-test of the world-model state head with diverse data (was a negative
   result on CIC2018 alone).

Everything else on this checklist is done and evidence-backed.
