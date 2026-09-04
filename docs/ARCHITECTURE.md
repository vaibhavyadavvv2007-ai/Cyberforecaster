# ARCHITECTURE — what is actually implemented

This is the authoritative architecture document. The code is the final
authority; this file describes what exists, and clearly separates it from
what is future work. Status date: 2026-09-04.

## Implemented architecture

```
┌────────────────────────── SOURCES ──────────────────────────┐
│  Live packets (Npcap)   Uploaded PCAP/CSV   Offline datasets │
└──────┬──────────────────────┬──────────────────────┬────────┘
       ▼                      ▼                      ▼
  ┌───────────────────────────────────────────────────────┐
  │           ADAPTER LAYER (per-dataset, honest)          │
  │  CIC2018 READY · UNSW-NB15 READY · CTU-13/CIC2017 …    │
  │  → canonical flow records → 48-feature WindowSlots      │
  │    (value, available, source) — unavailable ≠ zero      │
  └──────────────────────────┬────────────────────────────┘
                             ▼
  ┌───────────────────────────────────────────────────────┐
  │        SEQUENCE ENGINE (ONE road for everything)       │
  │  30s bins · gap-filled empty windows · L=10 → K=5      │
  │  masked CanonicalScaler · chronological split + purge   │
  └──────────┬───────────────────────────┬────────────────┘
             ▼                           ▼
  ┌─────────────────────┐      ┌─────────────────────────┐
  │  TEMPORAL MODELS    │      │  RULE ENGINE (no ML)    │
  │  V1 LSTM (demo)     │      │  volumetric / recon /   │
  │  V2 state head      │      │  lateral / C2 rules     │
  │  V3 ROLLOUT WORLD   │      │  on RAW values          │
  │  MODEL (risk from   │      └───────────┬─────────────┘
  │  forecast states)   │                  │
  └──────────┬──────────┘                  │
             └──────────────┬──────────────┘
                            ▼
  ┌───────────────────────────────────────────────────────┐
  │        EXPLAINABILITY STACK (deterministic, no LLM)    │
  │  MC-dropout bands · evidence rows · temporal WHY ·     │
  │  calibration                                          │
  └──────────────────────────┬────────────────────────────┘
                             ▼
  ┌───────────────────────────────────────────────────────┐
  │        DECISION SUPPORT (human-in-the-loop)            │
  │  MONITOR→INVESTIGATE→CONTAINMENT REVIEW→ESCALATE       │
  │  P1–P3 actions · MITRE ATT&CK STIX · nothing executes  │
  └──────────────────────────┬────────────────────────────┘
                             ▼
              FastAPI (8000)  ←→  Next.js UI (3000)
```

## The three-model lineage (all additive, V1 never destroyed)

| | V1 (demo) | V2 | **V3 (2026-09-04)** |
|---|---|---|---|
| File | `src/models/lstm_forecaster.py` | `src/models/world_model.py` | `src/models/rollout_world_model.py` |
| Architecture | LSTM → direct K-step risk + stage heads | V1 + parallel state head (one linear map → all K states) | LSTM → **autoregressive state rollout** |
| Risk path | encoder h → risk | encoder h → risk (states are a side task) | **risk DECODED from each forecast state Ŝ(t+k)** |
| State path | none | h → Ŝ(t+1..K) direct | h → Ŝ(t+1) → Ŝ(t+2) → … (residual transition g) |
| Stage path | single stage over horizon | single stage | **per-step stage decoder from Ŝ(t+k)** |
| Artifacts | `models/trained_models/` (frozen copy in `models/baseline_cic2018_v1/`) | `models/world_model_v2/` | `models/world_model_v3/lambda_0.5_huber/` |
| Test PR-AUC | 0.6565 | 0.6050 | 0.6331 |

Why V3 exists: V1/V2 answer "P(attack | history)". V3 answers the PS's actual
formulation — learn P(S_(t+1) | S_t), roll the state forward, and read the
attack risk and ATT&CK stage OFF the forecast states. In V3, if the state
rollout is wrong, the risk forecast is wrong; they cannot diverge. The
per-step stage display ("T+3: Initial Access, 72%") comes from V3.

V3 is an ADDITIVE companion: `/api/forecast` keeps its V1 numbers and adds
`future_steps` (per-step stage, risk-from-state, top moving state features)
when the V3 artifact loads; it degrades to `null` otherwise. The live demo
path never depends on V3.

## Component map

| Concern | Implementation |
|---|---|
| Canonical state S_t (48 features, groups A–G) | `src/features/canonical_schema.py` |
| Windowing / supervision / scaling (train = live = upload) | `src/features/sequence_engine.py`, `src/features/window_builder.py` |
| Packet-level features (TTL, TCP window, frag, payload, retransmission) | `src/features/packet_features.py` |
| Dataset adapters (discover→validate→load→slots, honest status) | `src/datasets/` |
| Stage taxonomy (canonical ATT&CK stages, per-dataset maps) | `src/labels/attack_taxonomy.py`, `src/attack_mapping/mitre_mapper.py` |
| Inference bundle (model+scaler+threshold, cannot diverge) | `src/forecasting/rollout.py` |
| Upload (magic-byte detection, column mapper, parse-never-execute) | `src/ingestion/upload_pipeline.py` |
| Evidence / temporal WHY / uncertainty / calibration | `src/explainability/` |
| Decision support (ladder, P1–P3, MITRE STIX) | `src/decision_support/` |
| Live capture → windows → forecast + rules | `src/live/`, `api/live_state.py` |
| Evaluation (onset lead, stage-transition lead) | `src/evaluation/lead_time.py`, `src/evaluation/stage_lead.py` |

## Deployment view (FUTURE — architecture-ready, not implemented)

Where the prototype would sit in a CII/enterprise:

```
Firewall / Router / IDS / Servers / Endpoints
        ↓ (telemetry: flow exports, packet taps, PCAP)
 Telemetry Collector (already: Npcap tap / file upload — implemented)
        ↓
 Feature Extraction + Canonical State  (implemented)
        ↓
 CyberForecaster  (implemented, single-node prototype)
        ↓
 Forecast + ATT&CK + Evidence + Decision Support  (implemented)
        ↓
 SOC Analyst (human-in-the-loop — the ONLY actor who acts)
```

Not claimed: multi-tenant deployment, streaming scale-out, SIEM integrations,
high availability. Those are production work beyond this prototype.

## Security posture

- Untrusted input is parsed, never executed; 100 MB upload cap; temp files
  always cleaned; `torch.load(weights_only=True)` everywhere.
- No automated response exists anywhere in the codebase — recommendations
  only, human decides (test-enforced).
- Fully offline at inference: no cloud APIs, no CDN-required assets, no LLM,
  MITRE knowledge is a local STIX digest.
