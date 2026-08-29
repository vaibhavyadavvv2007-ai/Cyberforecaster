# Surface brief: web (Next.js console + benchmarks)

- **Mode:** Operate — the visitor (a jury, an analyst) reads a forecast and
  its evidence, then judges it. Scanability, density and trust outrank
  expression.
- **Direction:** "The Analyst's Console" — professional security analytics
  register (Datadog / Grafana / Linear), subtle cybersecurity identity.
  Full system in `../../DESIGN.md`; sidecar in `../design.json`.
- **Non-negotiables:**
  - The model status (live / cached / simulated) stays visible on every
    screen — it is the honesty contract.
  - Metrics come from `/api/metrics` verbatim, never hand-edited.
  - The observed line is ground truth the model never sees; every chart
    keeps observed vs forecast visually distinct.
  - Warnings say "forecast", never "confirmed incident".
  - The prediction (probability, risk, stage, lead time) is the visually
    dominant element; everything else supports it.
- **Out of scope for this surface:** backend behavior, API contracts, model
  logic, routes.
