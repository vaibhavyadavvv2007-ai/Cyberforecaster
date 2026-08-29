# Review raster provenance

All captures in this directory were taken with Chrome DevTools MCP from the
live application on 2026-08-30 — Next.js dev server at http://localhost:3000,
FastAPI at http://localhost:8000 serving in REAL model mode (live LSTM
inference), CSE-CIC-IDS2018 60s-bin artifacts (models/trained_models +
data/processed at commit-time working tree).

| File | Viewport | State |
|---|---|---|
| console-full.png | 1536px desktop, full page | Scenario "28 Feb 10:55 - Lateral Movement underway" analyzed: peak 87%, HIGH badge, predicted stage Lateral Movement, threshold-crossed banner, chart with forecast region, ATT&CK progression + attribution |
| console-mobile.png | ~390px mobile emulation, full page | Same analyzed state; header wrapped with model status visible, cards reflowed single-column |
| benchmarks-full.png | 1440px desktop, full page | Summary metric cards, model comparison bars, per-horizon chart, lead-time table and detailed tables populated from /api/metrics (served verbatim) |

These are internal review captures, not shipped demo assets. The shipped demo
screenshot of record for the Streamlit predecessor is
models/demo_screenshot_lateral.png; an equivalent Next.js capture can be taken
from the same live stack at rehearsal time.
