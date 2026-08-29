# CyberForecaster Web - Next.js frontend

Dark security-analytics frontend for the FastAPI backend (`../api/`).
Fully offline: both servers run on the demo laptop.

## Run

```bash
npm install
npm run dev          # http://localhost:3000
```

Backend must be running on `http://localhost:8000` (or set
`NEXT_PUBLIC_API_URL` in `.env.local`). One-command launcher for both:
`scripts\start_demo.bat` from the repo root.

## Structure

- `lib/api.ts` - typed API client; types mirror `../api/schemas.py` exactly
- `app/page.tsx` - the console: control bar (scenario + threshold + run) ->
  prediction card (probability, risk, stage, lead time) -> threshold-crossed
  banner -> forecast chart -> ATT&CK progression + attribution
- `app/benchmarks/page.tsx` - conclusions first: summary metrics, model
  comparison bars, per-horizon chart, then exact tables
- `components/ui.tsx` - shared primitives (Card, Badge, Metric, NavLinks)
- `components/ForecastChart.tsx` - observed vs forecast over time (Recharts):
  gray observed, amber forecast over a tinted forecast region, red dashed
  threshold, "now" divider
- `components/AttackProgression.tsx` - ATT&CK chain with the predicted stage
  highlighted
- `components/WhyPrediction.tsx` - feature attribution with a
  plain-language summary derived from the actual top features
- `components/ModelStatus.tsx` - the model status pill in the header

## Design system

The visual world is "The Analyst's Console" — a professional security
analytics register (Datadog / Grafana / Linear). Tokens, component classes
and the world's laws live in `../DESIGN.md` at the repo root. Read it before
restyling anything; the named rules there (semantic color, mono-is-technical,
prediction-first) are load-bearing.

Typography: Inter for the interface, JetBrains Mono for measured values
(timestamps, IDs, feature names, metrics) — both self-hosted via @fontsource,
no CDN.

## Non-negotiables (the demo's honesty contract)

1. The model status pill (live / cached / simulated) stays visible on every
   screen.
2. Metrics on screen come from `/api/metrics` - never typed in by hand.
3. The observed line is ground truth the model never sees; every chart keeps
   observed vs forecast visually distinct. Keep it.
4. Warnings say "forecast", never "confirmed incident".

## Notes for the frontend owner

This scaffold is hand-written to be complete but minimal. If you prefer your
own `create-next-app` setup, keep `lib/api.ts` and the components - the typed
client is the contract with the backend and the forecast chart is the demo's
centerpiece.
