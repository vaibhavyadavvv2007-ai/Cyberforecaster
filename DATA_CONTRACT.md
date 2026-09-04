# DATA CONTRACT — CyberForecaster v2

The rules every data source, feature extractor, model and endpoint must obey.
Enforced by `src/features/canonical_schema.py` and `tests/test_feature_schema.py`.

## 1. One feature vocabulary

- All model inputs are declared in `canonical_schema.CANONICAL_FEATURES`
  (48 features, groups A–G, schema version + content hash).
- No dataset, adapter, extractor or UI may define its own model input.
- The legacy 18-feature input (Model V1) is the canonical subset `V1_ORDER`;
  projection through `V1_INDICES` reproduces it byte-identically.

## 2. Honest availability

- Every feature value travels as `(value, available, source)`.
- A feature the source cannot provide is `available=False`. It is NEVER a
  silent zero.
- Numeric conversion happens only via an explicit policy:
  - `V1_COMPAT` — unavailable → 0.0 (legacy reproduction only)
  - `MASKED` — unavailable → NaN + availability mask (V2 training)
- `DATASET_CAPABILITIES` rows are added only after verification against
  actual source data. Unverified = absent.

## 3. One windowing contract

- Time is binned into fixed windows; the production bin size is 30 s,
  single-sourced from the pipeline config (production value recorded in
  `data/processed/meta.txt`). Training, live capture and uploads must use
  the same value.
- Sequence shape: X (n, L=10, F), forecast horizon K=5.
- Empty windows are explicit zero-observation windows, never timeline gaps.

## 4. One split discipline

- Chronological splits only, with boundary purge at day/scenario boundaries.
- Scalers are fitted on the train split only, persisted with every artifact,
  and re-applied identically at inference.
- No `random_split`, no shuffling across time, no test-derived thresholds.

## 5. One supervision schema

- Per-horizon-step progression labels `y_prog (n, K)`, not a collapsed bool.
- Stage labels carry the canonical taxonomy
  (BENIGN / RECONNAISSANCE / INITIAL_ACCESS / LATERAL_MOVEMENT /
  COMMAND_AND_CONTROL / EXFILTRATION / IMPACT(DoS) / UNKNOWN_ATTACK)
  **and** the original dataset label + dataset_id. Original labels are never
  discarded.

## 6. Artifact versioning

Every trained model ships with: weights, config, scaler, feature schema
(name + hash), dataset manifest, label mapping, metrics, training metadata,
git-commit-of-record. A model refuses input whose schema hash differs.

## 7. Honesty contract (unchanged from V1)

- REAL / CACHED / SIMULATED modes stay visible everywhere.
- No fabricated detections, metrics, lead times or mappings.
- Decision support recommends; the human analyst decides. No automated
  destructive response exists in this codebase.

## 8. Untrusted input

Uploaded PCAP/CSV is data to PARSE, never to execute. No payload execution,
no shell-outs on file content, offline processing only.
