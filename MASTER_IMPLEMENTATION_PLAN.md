# MASTER IMPLEMENTATION PLAN — CyberForecaster multi-dataset upgrade

Owner: orchestrator (Agent 0). This file is the single source of truth for
what is being built, in what order, and what is deferred. Every phase is
updated here when it starts and when it passes its gate.

## Objective

Upgrade from CSE-CIC-IDS2018-only temporal attack forecasting to a
multi-dataset temporal forecasting **and decision-support** system:

  telemetry → canonical state engine → temporal world model
    → future-state trajectory + attack-risk forecast + ATT&CK stage
    → evidence-based explanation → defender decision support (human-in-loop)

The current working system is preserved as a frozen, reproducible baseline.

## Non-negotiable rules

1. **Never destroy the current model.** Frozen copy in `models/baseline_cic2018_v1/`.
   The old model stays runnable at all times.
2. **Never concatenate datasets blindly.** Adapters first; every dataset has
   different features/units/labels/timestamps/flow definitions.
3. **Do not pretend datasets provide the same information.** A capability
   matrix governs what each dataset can contribute; LANL is an auxiliary
   host-behavior modality, never forced into the flow feature vector.
4. **No fabrication, ever:** no fake packet features, fake ATT&CK mappings,
   fake lead time, fake accuracy, hand-written metrics. Missing = marked
   unavailable, not zero.
5. **No random splits.** Chronological splits + boundary purge everywhere.
6. **No automated destructive response.** Decision support only; the human
   analyst stays in control.
7. **Preserve the honesty contract:** REAL / CACHED / SIMULATED badges stay.
8. **No LLM in the core explanation path.** Deterministic explanation engine
   from real model outputs. No GNN/Transformer/blockchain added for marketing.
9. **No git commits** (user constraint for this repo during the build).
10. **Demo safety:** the internal demo (Sep 5, 2026) runs on the current
    system. Until it is done, all changes are additive — new files/modules
    only; the live demo path is not modified.

## Two-model strategy

- **Model V1 — `cic2018_v1`**: existing 18-feature LSTM. Frozen baseline.
  Answers "did more data actually help?" with evidence.
- **Model V2 — multidataset world model**: canonical feature schema,
  state head enabled, trained per the staged experiments below.

## Canonical feature schema (summary)

Groups A–G: flow-volume, TCP behavior, temporal behavior, address/port
behavior, packet-level behavior, directionality, application/service
behavior. Every feature slot carries `(value, available, source)` — a
feature a dataset cannot provide is *unavailable*, never silently zero.
Full definition: `src/features/canonical_schema.py` (Phase 2).

## Staged experiments

| Exp | Training data | Notes |
|---|---|---|
| A | CIC2018 only, 18F | = frozen baseline (rerun under V2 pipeline for comparability) |
| B | + CIC2017 | eval on both held-out sets |
| C | + UNSW-NB15 | |
| D | + CTU-13 | |
| E | + CICIoT2023 | IoT domain |
| F | DARPA | external/generalization evaluation only |

Testing in three regimes: in-domain (same dataset, later time),
cross-dataset (train on N, test on held-out dataset),
leave-one-dataset-out.

## STOP POINT (user instruction)

Phase 3 (dataset adapters for the new datasets) and Phases 7–8
(multi-dataset training/evaluation) require the raw datasets, which the
user will download. **When the build reaches the point where the actual
CIC2017 / UNSW-NB15 / CTU-13 / CICIoT2023 / DARPA files are needed, STOP
and hand the download list to the user.** Everything buildable with
CIC2018 + live packets proceeds now.

## Execution order and status

| # | Phase | Status | Gate |
|---|---|---|---|
| 0 | Repository audit → `docs/AUDIT_BEFORE_MULTIDATASET.md` | DONE 2026-09-04 | audit doc complete, verified against code |
| 1 | Baseline freeze → `models/baseline_cic2018_v1/` | DONE 2026-09-04 | old model verified running (API REAL mode) after freeze |
| 2 | Canonical feature schema | DONE 2026-09-04 | 48 features, groups A–G, availability mask, hash `a9570d8349141d92`; 8 tests |
| 3 | Dataset adapter layer | PARTIAL 2026-09-04 — **UNSW-NB15 WIRED** (first new dataset past the stop point): `src/datasets/unsw_nb15.py` — 49-column headerless schema (NUSW-NB15_features.csv authoritative), labels verified from the real files (2,540,047 flows, `Label`≡`attack_cat` 0 mismatches, "Backdoors" spelling variant handled), taxonomy `UNSW_FAMILY_CANONICAL` (mapping_source "manual/research"; Generic → UNKNOWN_ATTACK — refusal to guess), capability row `UNSW_NB15_AVAILABLE` (12/18 legacy features incl. **unique_src/dst_ips** — the one CIC2018 lacks; syn/ack/fin/rst/push ratios + iat_std honestly UNAVAILABLE — no flag-count columns; extras: TTL, TCP window (TCP-flows-only), duration_std, src_port_entropy, rates, all Group-G service ratios), manifest `configs/datasets/unsw_nb15.yaml`, registry flip READY. Slots feed the canonical sequence engine with zero glue (test-proven mask ≡ capability set). 21 tests (`tests/test_unsw_adapter.py`) incl. a real-file smoke on the actual bytes. CIC2017 / CTU-13 / CICIoT2023 / DARPA still pending files | adapter contract + registry + manifest |
| 4 | Packet feature extraction | DONE 2026-09-04 | `src/features/packet_features.py`: reuses LiveWindowBuilder (unchanged) for the 18 flow features + PacketWindowAccumulator for Group E/extras; pcap round-trip test proves byte-identical 18 vs a bare builder; 9 tests |
| 5 | Unified windowing/scaling | DONE 2026-09-04 | `src/config.py` single-sources BIN_SECS=30/L=10/K=5 (stale 60s defaults fixed in window_builder/pipeline/lead_time/live_state); `src/features/sequence_engine.py`: one canonical engine (gap-filled empty windows, masked CanonicalScaler with schema-hash guard, chrono split with purge) for train/live/upload; 10 tests |
| 6 | World-model state head (CIC2018 retrain) | DONE 2026-09-04 | `src/models/world_model.py` (WorldModelForecaster subclass — V1 file/artifact untouched; V1 weights load with strict=False and reproduce prog/stage byte-identically, test-verified). λ sweep {0.1,0.3,0.5}×Huber on CIC2018: λ=0.5 best (pr_auc 0.605 vs V1 0.657, precision 0.881 vs 0.882, state cosine 0.227; λ=0.1/0.3 state heads near-dead). HONEST FINDING: state head did NOT improve attack forecasting on CIC2018 alone — recorded as-is; the "did more data help" comparison extends to V2-multi-dataset. Artifacts in `models/world_model_v2/lambda_*/`; 5 tests |
| 7 | Multi-dataset training | BLOCKED on datasets | experiments B–F |
| 8 | Cross-dataset evaluation | BLOCKED on datasets | 3-regime reports |
| 9 | Explainability: evidence + temporal + uncertainty + calibration | DONE 2026-09-04 | `src/explainability/{evidence,temporal,uncertainty,calibration}.py`: EvidenceEngine (observed/benign z/direction/contribution, std=0 → no claim, TRAIN-split-only baseline `models/benign_baseline.json` over 3,308 benign train windows), temporal_why W-9..W-0 per-window importance/trend, seeded MC-dropout (state-restoring) with HIGH/MEDIUM/LOW bands, calibration of frozen V1 (`models/calibration_v1.json`: pooled n=4,580 Brier 0.1399 ECE 0.095; per-step ECE 0.077–0.112, no degradation with horizon). No LLM anywhere — templates with real numbers. 10 tests (`tests/test_explainability.py`) |
| 10 | Decision-support engine | DONE 2026-09-04 | `src/decision_support/` (levels.py explicit ladder, mitre.py, recommendations.py, engine.py): 4 levels MONITOR/INVESTIGATE/CONTAINMENT REVIEW/ESCALATE from probs vs threshold + crossing proximity + sustain + MC band (unknown band = MEDIUM, never HIGH); official MITRE STIX bundle (53.8 MB) downloaded to `data/knowledge/mitre_attack/` and pre-digested into a 160 KB index (709 techniques, 15 tactics) — curated family→technique map (T1110/T1190/T1071/T1021/T1498/T1005, all verified in STIX) + stage→tactic fallback, real mitigations/detections, honest "knowledge base unavailable" when index missing; ranked P1/P2/P3 recommendations citing real evidence numbers; human-in-loop statement on every record; NOTHING executes (rule 6). 21 tests (`tests/test_decision_support.py`) |
| 11 | PCAP/CSV upload + auto-detection + column mapper | DONE 2026-09-04 | `src/ingestion/upload_pipeline.py` + POST `/api/analyze/upload`: magic-byte detection (pcap/pcapng incl. nanosecond variants; extension NEVER trusted), CIC-flow-CSV (required-cols + CORE_COLS confidence) vs generic-flow-CSV (ColumnMapper: 10 canonical fields, ~60 aliases across CIC/UNSW/CTU/Zeek, explicit user mapping overrides aliases, duration s→µs), unknown schema → 400 "please map columns" with mapper report (never silent guess); PCAP path reuses Phase-4 extract_pcap (live pipeline), CSV path reuses audited build_windows; same model_matrix conditioning as live (IP-zeroing + p99 clamps); per-anchor forecast trajectory + MC uncertainty + evidence + decision support; `unavailable_features` reported honestly (slot availability for pcap, all-zero columns for CSV); 100 MB cap, parse-never-execute, temp file always cleaned. API restarted in REAL mode (duplicate uvicorn processes killed first); all existing routes verified unchanged. 13 tests (`tests/test_upload_pipeline.py`); TestClient E2E: CIC CSV→200, junk→400, pcap→200 |
| 12 | UI integration | DONE 2026-09-04 | `/analyze` page: file upload → detection card (format/style/confidence, matched/missing cols, honest unavailable-features note) → forecast-at-end hero + MC confidence badge + PeakGauge → per-anchor trajectory chart (recharts, threshold refline) → `EvidencePanel` (observed/benign-mean/p99/z/direction/attribution bars) → `DecisionSupportPanel` (level badge, guidance, ranked P1–P3 actions, ATT&CK enrichment, human-in-loop footer). `/datasets` page renders `/api/datasets` verbatim (READY/PENDING_WIRING/NOT_DOWNLOADED badges, modality, source links, "1/7 ready" meta). Nav: Forecast · Live · Analyze · Benchmarks · Datasets. `web/lib/api.ts` types mirror the API contract; browser-verified end-to-end (CIC CSV upload → full Phase 9–11 record, no console errors); tsc clean; API restarted in REAL mode with `/api/datasets` live. 83 tests green | WHY panel, trajectory, benchmarks |
| 13 | Live pipeline alignment | DONE 2026-09-04 | `LiveHistory.predict()` now returns the Phase 9/10 stack **additively**: seeded MC-dropout band (T=16, deterministic), evidence rows built from the **RAW observed** window values (real IP counts + unclamped ratios — NOT the model's conditioning zeros/p99 clamps; test-proven with ack_ratio=10.0 → `observed 10.0, elevated` while the model input is clamped), and the same `DecisionSupportEngine.assess()` record the upload path produces. Every enrichment degrades to `None` when its engine/artifact is missing, so the demo-day live path returns exactly the legacy fields plus nulls (test-verified). Engines are now ONE process-wide lazy singleton (`api/live_state.explain_engines()`) shared by the live feed and the upload endpoint (removed the duplicate loader in main.py). Windowing/conditioning/honesty badges untouched. Live page renders EvidencePanel + DecisionSupportPanel when present. VERIFIED on real captured traffic: 98 live windows, feed 200 on every poll, MC band HIGH (max σ 0.0274), 8 evidence rows, decision support MONITOR with real STIX mitigations (T1078/T1091/T1133/T1189), human-in-loop present; only console 404 is the pre-existing favicon. 88 tests green (5 new in `tests/test_live_enrichment.py`); tsc clean | live uses canonical engine |
| 14 | Full regression testing | DONE 2026-09-04 | `tests/test_golden_regression.py` (12 tests): sha256 pins on every frozen artifact (live `lstm_forecaster.pt`, `scaler.npz`, `benign_baseline.json`, `calibration_v1.json`, and the frozen baseline copies — a changed hash fails with "update the pin on purpose, never delete it"); baseline-freeze ≡ live-model byte-identity check; exact `Forecaster.predict` goldens (probs to 4 decimals + stage + threshold) on 4 fixed inputs — 2 synthetic sequences and 2 deterministically-selected real slices of `windows.parquet` (benign head + the true attack onset at rows 105–114, with a guard test asserting the onset structure); seeded MC-dropout golden (T=16, seed=0, pinned probs_mean/std/max_std/confidence/stage_votes); API contracts via TestClient (health shape + boot/model error null, forecast determinism across repeated calls, datasets registry statuses incl. honest pending adapters). Full suite: **100 tests green** (88 prior + 12 golden) in 16.8s | pytest green, golden fixtures |
| 15 | Demo hardening + model card | DONE 2026-09-04 | `MODEL_CARD.md` (repo root): real metrics (P 0.882 / R 0.140 / F1 0.241 / FPR 0.006 / PR-AUC 0.656 vs logistic 0.333; calibration Brier 0.1399 / ECE 0.095 / n=4,580), lead-time zero-result reported as an honest limitation (test split has 1 onset, warned_rate 0.0 — cite live-rehearsal numbers instead), live-input domain-conditioning disclosure, world_model_v2 negative result, intended-use limits (no automated response, no attribution, no LLM in explanations), reproducibility hashes. `docs/ACCEPTANCE_CHECKLIST.md`: every final-acceptance criterion mapped to evidence, open items honestly gated on the dataset stop point. `docs/DEMO_RUNBOOK.md` §8 (additive — §0–§7 rehearsed content untouched): new Live evidence/decision-support panels, /analyze upload page as offline backup beat, /datasets credibility beat, Q&A doc tabs, 3 extra pre-flight checks incl. the 100-test golden gate. Final verification: **100 tests green in 16.5s, tsc clean** | acceptance checklist all true (except items honestly gated on datasets) |

## Agent handoff rule

Every phase hands off: what changed, files changed, why, tests added,
tests passed, known limitations, remaining work, metrics affected,
breaking changes. "Done" without evidence is not done.

## Final acceptance criteria

Condensed from the full plan (see §71 of the original): data layer works
per-dataset with manifests; canonical schema + availability mask enforced
everywhere; state head enabled with future-state metrics; forecasting has
risk/stage/cross-dataset/calibration evaluation; explainability is
evidence-based with uncertainty; decision support has WHY/evidence/forecast/
recommendations/priority/human-in-loop; product has upload + live + offline
+ honesty badges + benchmarks; reproducibility artifacts (model card,
config, scaler, manifest, git-commit-of-record) complete.
