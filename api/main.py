"""FastAPI routes. All computation lives in src/ or api/state.py — this file
only orchestrates and serializes, so the API cannot drift from the app.

Run from the repo root:
  uvicorn api.main:app --port 8000
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.schemas import (AttributionItem, ForecastRequest, ForecastResponse,   # noqa: E402
                         HealthResponse, ScenarioOut, TimelinePoint,
                         TimelineResponse)
from api.state import simulated_forecast, state
from src.features.window_builder import HORIZON, WINDOW_FEATURES               # noqa: E402
from src.forecasting.scenarios import CONTEXT_AFTER, CONTEXT_BEFORE           # noqa: E402

app = FastAPI(title="CyberForecaster API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_boot() -> None:
    if state.boot_error or state.windows is None:
        raise HTTPException(status_code=503, detail=state.boot_error or "not booted")


def _get_scenario(scenario_id: str) -> dict:
    _require_boot()
    sc = state.scenario_by_id(scenario_id)
    if sc is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario_id: {scenario_id}")
    return sc


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    f = state.forecaster
    return HealthResponse(
        mode=state.mode,
        boot_error=state.boot_error,
        model_error=None if f is not None else state.load_err,
        n_windows=0 if state.windows is None else len(state.windows),
        n_scenarios=len(state.scenarios),
        n_features=f.n_feat if f else None,
        horizon=f.horizon if f else None,
        threshold=state.default_threshold,
        mean_attack_frac=0.0 if state.windows is None
        else float(state.windows["attack_frac"].mean()),
    )


@app.get("/api/scenarios", response_model=list[ScenarioOut])
def scenarios() -> list[ScenarioOut]:
    _require_boot()
    return [ScenarioOut(**s) for s in state.scenarios]


@app.post("/api/forecast", response_model=ForecastResponse)
def forecast(req: ForecastRequest) -> ForecastResponse:
    sc = _get_scenario(req.scenario_id)
    anchor = sc["anchor"]
    thr = req.threshold if req.threshold is not None else state.default_threshold

    why: list[AttributionItem] | None = None
    why_note: str | None = None
    mode = state.mode

    if mode == "REAL" and state.forecaster is not None and state.windows is not None:
        seq = _sequence_at(anchor)
        result = state.forecaster.predict(seq)
        probs, stage = result["probs"], result["stage"]
        try:
            from src.explainability.attribution import integrated_gradients_attribution
            attr = integrated_gradients_attribution(
                state.forecaster.model, state.forecaster.scaled(seq))
            order = np.argsort(-np.abs(attr))[:6]
            why = [AttributionItem(feature=WINDOW_FEATURES[i],
                                   importance=round(float(abs(attr[i])), 6))
                   for i in order]
        except Exception as exc:  # noqa: BLE001 — show the reason, never swallow it
            why_note = f"{type(exc).__name__}: {exc}"
    elif mode == "CACHED" and state.cache is not None:
        entry = (state.cache.get("scenarios") or {}).get(sc["id"])
        if entry:
            probs, stage = entry["probs"], entry.get("stage", "")
            raw_why = [tuple(w) for w in entry.get("why", [])]
            why = [AttributionItem(feature=f_, importance=round(v, 6))
                   for f_, v in raw_why] or None
        else:
            probs = _simulated(anchor)
            stage = ""
            why_note = f"no cache entry for {sc['id']}"
    else:
        probs = _simulated(anchor)
        stage = ""
        why_note = (f"model unavailable: {state.load_err}" if state.load_err
                    else "no trained model and no cache")

    peak = max(probs) if probs else 0.0
    level = "HIGH" if peak >= 0.8 else ("ELEVATED" if peak >= thr else "LOW")
    crossing = next((k + 1 for k, p in enumerate(probs) if p >= thr), None)

    return ForecastResponse(
        scenario_id=sc["id"], mode=mode, probs=probs, peak=round(peak, 4),
        level=level, stage=stage or "", rule_stage=state.rule_stage_at(anchor),
        threshold=round(thr, 4), crossing_step=crossing, why=why, why_note=why_note,
    )


@app.get("/api/timeline", response_model=TimelineResponse)
def timeline(scenario_id: str, threshold: float | None = None) -> TimelineResponse:
    sc = _get_scenario(scenario_id)
    w = state.windows
    assert w is not None  # _require_boot guarantees it
    anchor = sc["anchor"]

    lo = max(0, anchor - CONTEXT_BEFORE)
    hi = min(len(w), anchor + HORIZON + CONTEXT_AFTER)
    idx = w.index[lo:hi]
    observed = w["attack_frac"].to_numpy()[lo:hi]

    # Same forecast the /api/forecast endpoint returns — a timeline that disagreed
    # with the risk panel would be two demos telling two stories.
    fc = _forecast_probs_for(sc)
    a_rel = anchor - lo
    points: list[TimelinePoint] = []
    for i, ts in enumerate(idx):
        p = None
        if i == a_rel:
            p = float(observed[i])                 # join the curves visually
        elif fc is not None and a_rel < i <= a_rel + len(fc):
            p = fc[i - a_rel - 1]
        points.append(TimelinePoint(ts=ts.isoformat(), observed=round(float(observed[i]), 6),
                                    forecast=p))

    return TimelineResponse(
        scenario_id=sc["id"], anchor_ts=w.index[anchor].isoformat(),
        anchor_index=a_rel,
        threshold=round(threshold if threshold is not None else state.default_threshold, 4),
        points=points,
    )


@app.get("/api/metrics")
def metrics() -> dict:
    """Every metrics_*.json merged verbatim. The frontend renders; it never edits.

    No boot requirement — the JSONs exist even before windows.parquet does, and
    the frontend team builds against this endpoint first.
    """
    return state.metrics


@app.get("/api/flagged")
def flagged(limit: int = 15) -> dict:
    """Top attack windows by activity — the 'Flagged windows' tab."""
    _require_boot()
    w = state.windows
    assert w is not None
    fw = w[w["attack_frac"] > 0].sort_values("attack_frac", ascending=False)
    cols = [c for c in w.columns if not c.startswith("frac_")]
    rows = fw.head(limit)[cols].reset_index(names="ts")
    rows["ts"] = rows["ts"].astype(str)
    # to_json (not to_dict): it coerces every numpy scalar json can't encode
    # and turns NaN into null in one step.
    return {"total_flagged": int(len(fw)), "total_windows": int(len(w)),
            "rows": json.loads(rows.to_json(orient="records"))}


# ---------------------------------------------------------------- helpers
def _sequence_at(anchor: int) -> np.ndarray:
    from src.forecasting.scenarios import sequence_at
    return sequence_at(state.windows, anchor)  # type: ignore[arg-type]


def _simulated(anchor: int) -> list[float]:
    w = state.windows
    assert w is not None
    return simulated_forecast(w["attack_frac"].to_numpy()[:anchor + 1])


def _forecast_probs_for(sc: dict) -> list[float] | None:
    """Probs for a scenario without re-running attribution — mirrors /api/forecast."""
    if state.mode == "REAL" and state.forecaster is not None:
        return state.forecaster.predict(_sequence_at(sc["anchor"]))["probs"]
    if state.cache is not None:
        entry = (state.cache.get("scenarios") or {}).get(sc["id"])
        if entry:
            return entry["probs"]
    return None
