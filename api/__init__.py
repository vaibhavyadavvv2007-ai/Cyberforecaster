"""FastAPI backend for the CyberForecaster demo — offline, one machine.

Wraps the existing src/ ML code (rollout, scenarios, attribution, rules) as
JSON endpoints for the Next.js frontend. The Streamlit app stays untouched as
the fallback demo; this service must never diverge from what it shows, so every
computation is ported from app/streamlit_app.py, not reinvented.

  uvicorn api.main:app --port 8000     (from the repo root)
"""
