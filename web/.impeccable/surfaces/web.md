---
version: 1
slug: "web"
primary_target: "web"
related_targets: []
---

# Surface brief — web console (Next.js, Operate)

## Surface
web/ — the CyberForecaster console: `/` (scenario analysis) and `/benchmarks` (metrics tables). Runs offline next to a local FastAPI (port 8000). The visitor is a hackathon jury member watching an operator-driven demo; success = they trust and understand the forecast in seconds.

## Mode
Operate. Scanability, consistency and the real usage scene (projected in a demo room, driven by keyboard/mouse) outrank expression. Brand lives in precise details.

## Direction
Mimic Panel (seed 59675c0d, assigned index 6) — industrial SCADA control-panel world. Anthracite panel ground, bone engraved legends (Barlow Condensed), IBM Plex Mono readouts, signal amber for lit cells, red reserved for the trip line. Registration ticks, chart-paper grid, instant segment-swap numbers, one panel-sweep signature moment on results.

## Non-negotiables
- Honesty contract: mode lamp (REAL/CACHED/SIMULATED) always visible in the header; metrics served verbatim from the API; observed (ground truth) vs forecast lines always distinguishable.
- Offline: self-hosted @fontsource fonts only, no CDN.
- Numbers always come from the API, never typed into the frontend.
