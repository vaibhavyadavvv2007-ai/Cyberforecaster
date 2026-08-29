# CyberForecaster API — FastAPI service

Wraps the trained models and demo logic as JSON endpoints for the Next.js
frontend (`web/`). Everything loads once at startup (~2s); inference is CPU
torch, sub-millisecond per request.

## Run

```bash
pip install -r requirements.txt          # fastapi/uvicorn included
python -m uvicorn api.main:app --port 8000
# or, to start API + frontend together:
scripts\start_demo.bat                    # (scripts/start_demo.sh on bash)
```

Verify: `python scripts/check_api.py` — compares live forecasts against the
precomputed demo cache (same model, deterministic) and checks every endpoint.

## Modes (honesty survives the migration)

`GET /api/health` → `mode`:
- `REAL` — trained model + fitted transform loaded, live inference
- `CACHED` — model unavailable; replays precomputed real predictions from `demo_cache.json`
- `SIMULATED` — no model, no cache; extrapolated placeholders

The frontend MUST display this badge. Never hardcode numbers; every metric on
screen comes from `/api/metrics` (the training scripts' JSONs, verbatim).

## Endpoints

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/health` | — | mode, n_windows, n_scenarios, n_features, horizon, threshold, errors |
| GET | `/api/scenarios` | — | `[{id, name, kind: "onset"\|"during"\|"quiet", anchor}]` |
| POST | `/api/forecast` | `{scenario_id, threshold?}` | probs (K steps), peak, level (HIGH/ELEVATED/LOW), stage, rule_stage, threshold, crossing_step, why[] |
| GET | `/api/timeline?scenario_id=` | — | points: ts, observed, forecast (null before anchor); anchor_index = where the forecast starts |
| GET | `/api/metrics` | — | merged `models/metrics_*.json` |
| GET | `/api/flagged?limit=15` | — | top attack windows (the "Flagged windows" tab) |

Error shape: FastAPI default (`{"detail": "..."}`), 404 unknown scenario,
503 when `windows.parquet` is missing.

## Frontend integration notes

- **Timeline chart** (the centerpiece): plot `observed` as a solid line and
  `forecast` as a dashed line over `ts`; draw `threshold` as a horizontal rule.
  `points[anchor_index].forecast` equals the observed value there on purpose —
  it joins the two curves visually.
- **Threshold slider**: pass the chosen value as `threshold` in the forecast
  request; omit it to use the model's own operating point (picked on
  validation under an FPR budget).
- `crossing_step` is 1-based; `null` means the forecast never crosses the
  threshold ("no warning").
- `why` may be `null` with `why_note` set — surface the note, don't hide it.

## Architecture

`api/state.py` loads everything once (windows, `Forecaster`, cache, scenarios,
rule-engine p99s, metrics). `api/main.py` only orchestrates. All ML logic
lives in `src/` — imported, never copied, so the API and the Streamlit
fallback (`app/streamlit_app.py`) cannot disagree.
