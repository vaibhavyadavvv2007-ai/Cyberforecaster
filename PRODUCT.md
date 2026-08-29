# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary audience: the jury at the Smart India Hackathon internal round (SIH26153, Saturday Sep 5, 2026) watching a 7-minute live demo from a projector, plus the six team members rehearsing and presenting. Secondary audience: the persona the demo role-plays — a SOC analyst who needs to see an attack's trajectory before it completes. One design serves both: a working analyst console that reads beautifully from the back of the room.

## Product Purpose

CyberForecaster is a temporal attack-progression forecasting console. It does not classify traffic — it models how network state evolves over time and forecasts the next 5 minutes of an attack's progression, with every prediction explained (IntegratedGradients attribution, MITRE ATT&CK stage mapping, an independent rule-engine cross-check). Success: the jury sees a probability timeline visibly climb past an alert threshold during the pitch, understands WHY, and believes the rigor.

## Positioning

Forecasting, not detection: trajectory (will the attack continue/escalate over the next K windows) rather than point-in-time classification — with a benchmark that proves it on a chronological split where the test set is an attack family absent from training.

## Operating Context

- Fully offline demo on one laptop: FastAPI backend (localhost:8000) + this Next.js frontend (localhost:3000), launched by `scripts/start_demo.bat`. No internet at any point.
- 7-minute demo arc with a rehearsed money-moment: scenario "28 Feb 10:55 — Lateral Movement underway" → 87% peak, HIGH, Lateral Movement, rst_ratio/iat_mean attribution.
- Streamlit app (`app/streamlit_app.py`) is the verified fallback demo; this frontend replaces it if it survives rehearsal.

## Capabilities and Constraints

- Console page: scenario picker (9 named moments: onset/during/quiet), alert-threshold slider, risk metric cards, forecast timeline (observed solid + forecast dashed + threshold rule), MITRE ATT&CK strip, WHY attribution bars.
- Benchmarks page: aggregate + per-horizon-step tables, lead-time table, rigor captions.
- Hard honesty constraints: the REAL/CACHED/SIMULATED mode badge must stay visible on every screen; all metrics come verbatim from `/api/metrics` (never hand-typed); the observed line is ground truth the model never sees (caption says so); lead time is honestly 0 on this dataset.
- API contract lives in `web/lib/api.ts` mirroring `api/schemas.py`; endpoints `/api/health|scenarios|forecast|timeline|metrics|flagged`.

## Brand Commitments

Binding: the product name "CyberForecaster". The shield emoji is NOT binding and may be replaced by a proper mark. Everything else (palette, typography, mark, composition) is free.

## Evidence on Hand

- Real trained model: LSTM PR-AUC 0.591 vs logistic 0.346 (60s bins), 0.657 (30s bins, Gate-1 decision pending) — `models/metrics_*.json`.
- Verified demo run + screenshot: `models/demo_screenshot_nextjs_lateral.png` (87% peak moment).
- 9 real scenarios from CSE-CIC-IDS2018 (6.19M flows, 7 day-files).
- Do NOT fabricate: customer names, testimonials, lead-time claims, real-time/live-feed claims (demo replays recorded windows).

## Product Principles

1. The forecast moment is the hero — every layout decision serves the probability timeline climbing past the threshold.
2. Honesty is a feature: mode badges, verbatim metrics, ground-truth captions are design elements, not fine print.
3. Readable from the back of a lecture hall: large numerals, one accent color for risk, high contrast on dark.
4. Calm authority, not alarm theater: a SOC console that feels professional earns more trust than one that feels like a movie.
5. Rehearsal-proof: every state (loading, error, quiet scenario) must look intentional.
