"""Startup state — everything loaded ONCE, at import time.

Mirrors app/streamlit_app.py's boot: windows, Forecaster (or the reason it
failed), demo cache, scenarios, rule-engine p99s, metrics JSONs. Keeping this
in one module means every endpoint sees the same state and a broken artifact
degrades the mode badge instead of crashing a request mid-demo.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.attack_mapping.mitre_mapper import rule_based_stage               # noqa: E402
from src.features.window_builder import WINDOW_FEATURES                    # noqa: E402
from src.forecasting.rollout import Forecaster                             # noqa: E402
from src.forecasting.scenarios import build_scenarios                      # noqa: E402

PROCESSED = ROOT / "data" / "processed"
WINDOWS_PATH = PROCESSED / "windows.parquet"
CACHE_PATH = PROCESSED / "demo_cache.json"
MODELS = ROOT / "models"


def simulated_forecast(hist: np.ndarray, k: int = 5) -> list[float]:
    """Damped-momentum extrapolation — placeholder only, same math as the app."""
    recent = hist[-3:] if len(hist) >= 3 else hist
    momentum = float(np.mean(np.diff(recent))) if len(recent) > 1 else 0.0
    out, val = [], float(hist[-1]) if len(hist) else 0.0
    for i in range(k):
        val = float(np.clip(val + momentum * (0.7 ** i), 0.0, 1.0))
        out.append(round(val, 4))
    return out


@dataclass
class AppState:
    windows: pd.DataFrame | None = None
    scenarios: list[dict] = field(default_factory=list)
    cache: dict | None = None
    forecaster: Forecaster | None = None
    load_err: str | None = None
    boot_error: str | None = None      # missing windows.parquet etc.
    p99_bytes: float = 0.0             # rule-engine thresholds, computed once
    p99_pkts: float = 0.0
    metrics: dict = field(default_factory=dict)

    @property
    def mode(self) -> str:
        if self.forecaster is not None:
            return "REAL"
        return "CACHED" if self.cache else "SIMULATED"

    @property
    def default_threshold(self) -> float:
        if self.forecaster is not None:
            return self.forecaster.threshold
        if self.cache is not None:
            return float(self.cache.get("threshold", 0.6))
        return 0.6

    def scenario_by_id(self, scenario_id: str) -> dict | None:
        return next((s for s in self.scenarios if s["id"] == scenario_id), None)

    def rule_stage_at(self, anchor: int) -> str:
        return rule_based_stage(self.windows.iloc[anchor].to_dict(),
                                self.p99_bytes, self.p99_pkts)


def _load_metrics() -> dict:
    """Serve every metrics_*.json, namespaced by file stem.

    Not a flat merge: metrics_lead_time.json ALSO has an "lstm_forecaster" key
    (lead-time stats) which would silently overwrite the benchmark numbers from
    metrics_lstm.json. Namespacing by file keeps both.
    """
    merged: dict = {}
    if not MODELS.exists():
        return merged
    for mf in sorted(MODELS.glob("metrics_*.json")):
        try:
            merged[mf.stem.removeprefix("metrics_")] = json.loads(
                mf.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            merged[f"_unreadable:{mf.name}"] = {"error": str(exc)}
    return merged


def load_state() -> AppState:
    st = AppState()
    if not WINDOWS_PATH.exists():
        st.boot_error = (
            f"no {WINDOWS_PATH.relative_to(ROOT)} - run the pipeline first "
            "(python -m src.preprocessing.pipeline)"
        )
        st.metrics = _load_metrics()
        return st

    try:
        st.windows = pd.read_parquet(WINDOWS_PATH)
    except Exception as exc:  # noqa: BLE001 — degrade, never crash the service
        st.boot_error = f"cannot read windows.parquet: {type(exc).__name__}: {exc}"
        st.metrics = _load_metrics()
        return st

    missing = [c for c in WINDOW_FEATURES if c not in st.windows.columns]
    if missing:
        st.boot_error = f"windows.parquet missing feature columns {missing} - re-run the pipeline"
        st.metrics = _load_metrics()
        return st

    # Forecaster.load returns (None, reason) instead of raising — keep that.
    try:
        st.forecaster, st.load_err = Forecaster.load(
            MODELS / "trained_models" / "lstm_forecaster.pt",
            PROCESSED / "scaler.npz",
        )
    except Exception as exc:  # noqa: BLE001
        st.forecaster, st.load_err = None, f"{type(exc).__name__}: {exc}"

    if CACHE_PATH.exists():
        try:
            st.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st.cache = None

    st.scenarios = build_scenarios(st.windows)
    st.p99_bytes = float(st.windows["bytes_total"].quantile(0.99))
    st.p99_pkts = float(st.windows["pkts_total"].quantile(0.99))
    st.metrics = _load_metrics()
    return st


state = load_state()
