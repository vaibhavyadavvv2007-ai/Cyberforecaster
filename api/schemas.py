"""Request/response schemas — the contract the Next.js frontend codes against."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    scenario_id: str = Field(..., description='e.g. "during-2472" from GET /api/scenarios')
    threshold: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Override the alert threshold (UI slider). Null = the model's "
                    "own operating point picked on validation.")


class AttributionItem(BaseModel):
    feature: str
    importance: float


class ForecastResponse(BaseModel):
    scenario_id: str
    mode: str                        # REAL | CACHED | SIMULATED
    probs: list[float]               # K-step progression probabilities
    peak: float
    level: str                       # HIGH | ELEVATED | LOW
    stage: str                       # predicted dominant stage over the horizon
    rule_stage: str                  # independent rule-engine cross-check
    threshold: float
    crossing_step: int | None        # 1-based window where probs first cross threshold
    why: list[AttributionItem] | None = None
    why_note: str | None = None      # why attribution is missing (shown, never swallowed)


class TimelinePoint(BaseModel):
    ts: str                          # ISO timestamp of the window
    observed: float                  # ground-truth attack_frac (model never sees it)
    forecast: float | None           # null before/at the anchor, probs after


class TimelineResponse(BaseModel):
    scenario_id: str
    anchor_ts: str
    anchor_index: int                # index into this slice where forecast starts
    threshold: float
    points: list[TimelinePoint]


class ScenarioOut(BaseModel):
    id: str
    name: str
    kind: str                        # onset | during | quiet
    anchor: int


class HealthResponse(BaseModel):
    mode: str
    boot_error: str | None
    model_error: str | None
    n_windows: int
    n_scenarios: int
    n_features: int | None
    horizon: int | None
    threshold: float
    mean_attack_frac: float
