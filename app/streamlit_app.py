"""CyberForecaster demo app — fully offline.

Three modes, always badged honestly:
  REAL      trained model + fitted transform loaded → live inference
  CACHED    precomputed predictions from demo_cache.json → deterministic, crash-proof
  SIMULATED no model and no cache → extrapolated placeholders, clearly marked

  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.attack_mapping.mitre_mapper import rule_based_stage                  # noqa: E402
from src.features.window_builder import HORIZON, SEQ_LEN, WINDOW_FEATURES     # noqa: E402
from src.forecasting.scenarios import (CHAIN, CONTEXT_AFTER, CONTEXT_BEFORE,  # noqa: E402
                                       build_scenarios, sequence_at)

PROCESSED = ROOT / "data" / "processed"
WINDOWS_PATH = PROCESSED / "windows.parquet"
CACHE_PATH = PROCESSED / "demo_cache.json"
MODELS = ROOT / "models"

st.set_page_config(page_title="CyberForecaster", page_icon="🛡️", layout="wide")
st.title("🛡️ CyberForecaster — temporal attack-progression forecasting")


# ---------------------------------------------------------------- loading
@st.cache_data(show_spinner=False)
def load_windows(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


@st.cache_resource(show_spinner=False)
def get_forecaster():
    """(Forecaster, None) or (None, reason). Never raises."""
    try:
        from src.forecasting.rollout import Forecaster
        return Forecaster.load(MODELS / "trained_models" / "lstm_forecaster.pt",
                               PROCESSED / "scaler.npz")
    except Exception as exc:  # noqa: BLE001 — demo must never crash on optional deps
        return None, f"{type(exc).__name__}: {exc}"


@st.cache_data(show_spinner=False)
def load_cache(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def simulated_forecast(hist: np.ndarray, k: int = HORIZON) -> list[float]:
    """Damped-momentum extrapolation of recent attack activity — placeholder only."""
    recent = hist[-3:] if len(hist) >= 3 else hist
    momentum = float(np.mean(np.diff(recent))) if len(recent) > 1 else 0.0
    out, val = [], float(hist[-1]) if len(hist) else 0.0
    for i in range(k):
        val = float(np.clip(val + momentum * (0.7 ** i), 0.0, 1.0))
        out.append(round(val, 4))
    return out


# ---------------------------------------------------------------- boot
if not WINDOWS_PATH.exists():
    st.warning(
        f"No `{WINDOWS_PATH.relative_to(ROOT)}` found.\n\n"
        "1. `python scripts/download_data.py --list` → `--yes`\n"
        "2. `python -m src.preprocessing.pipeline`\n"
        "3. reload this page"
    )
    st.stop()

try:
    windows = load_windows(str(WINDOWS_PATH), WINDOWS_PATH.stat().st_mtime)
except ImportError:
    st.error("Cannot read parquet — no engine installed. Run: `pip install pyarrow`")
    st.stop()

missing = [c for c in WINDOW_FEATURES if c not in windows.columns]
if missing:
    st.error(f"windows.parquet is missing feature columns {missing} — re-run the pipeline.")
    st.stop()

forecaster, load_err = get_forecaster()
cache = load_cache(str(CACHE_PATH), CACHE_PATH.stat().st_mtime) if CACHE_PATH.exists() else None
mode = "REAL" if forecaster is not None else ("CACHED" if cache else "SIMULATED")
scenarios = build_scenarios(windows)

with st.sidebar:
    st.header("Input")
    st.caption(f"{len(windows):,} windows · {windows['attack_frac'].mean():.1%} mean attack fraction")
    if mode == "REAL":
        st.success(f"**REAL MODEL** — {forecaster.n_feat} features, K={forecaster.horizon}, "
                   f"threshold {forecaster.threshold:.2f}")
    elif mode == "CACHED":
        st.info("**CACHED MODE** — replaying precomputed real predictions (deterministic).")
        st.caption(f"model unavailable: {load_err}")
        st.caption(f"cache: threshold {cache.get('threshold', 0.5):.2f}, "
                   f"{len(cache.get('scenarios') or {})} scenarios")
    else:
        st.error("**SIMULATED MODE** — no trained model and no cache. Panels below are "
                 "extrapolations, not inference.")
        st.caption(f"reason: {load_err}")

    names = [s["name"] for s in scenarios] or ["(no scenario found)"]
    picked = st.selectbox("Scenario", names, help="Anchored on the last window before "
                                                 "an attack begins.")
    scenario = scenarios[names.index(picked)] if scenarios else None
    default_thr = forecaster.threshold if mode == "REAL" else 0.6
    threshold = st.slider("Alert threshold", 0.0, 1.0, float(default_thr), 0.05)
    if mode == "REAL":
        st.caption(f"Model's own operating point: {forecaster.threshold:.2f} "
                   "(picked on validation under an FPR budget).")

if mode == "SIMULATED":
    st.warning("⚠️ **SIMULATED** — extrapolated placeholders shown to validate the UI. "
               "Train the model (`python -m src.models.lstm_forecaster`) or build the "
               "cache (`python scripts/build_demo_cache.py`) for real numbers.")

if scenario is None:
    st.error("No usable scenario in this dataset (need an attack onset with "
             f"{SEQ_LEN} windows of history). Check the pipeline output.")
    st.stop()

anchor = scenario["anchor"]

# ---------------------------------------------------------------- analyze
if st.button("▶️ ANALYZE + FORECAST", type="primary"):
    seq = sequence_at(windows, anchor)
    why, why_err, pred_stage = None, None, ""

    if mode == "REAL":
        result = forecaster.predict(seq)
        probs, pred_stage = result["probs"], result["stage"]
        try:
            from src.explainability.attribution import integrated_gradients_attribution
            attr = integrated_gradients_attribution(forecaster.model, forecaster.scaled(seq))
            order = np.argsort(-np.abs(attr))[:6]
            why = [(WINDOW_FEATURES[i], float(abs(attr[i]))) for i in order]
        except Exception as exc:  # noqa: BLE001 — but SHOW the reason, never swallow it
            why_err = f"{type(exc).__name__}: {exc}"
    elif mode == "CACHED":
        entry = (cache.get("scenarios") or {}).get(scenario["id"])
        if entry:
            probs, pred_stage = entry["probs"], entry.get("stage", "")
            why = [tuple(w) for w in entry.get("why", [])] or None
        else:
            probs = simulated_forecast(windows["attack_frac"].to_numpy()[:anchor + 1])
            why_err = f"no cache entry for {scenario['id']}"
    else:
        probs = simulated_forecast(windows["attack_frac"].to_numpy()[:anchor + 1])

    peak = max(probs) if probs else 0.0
    level = "🔴 HIGH" if peak >= 0.8 else "🟠 ELEVATED" if peak >= threshold else "🟢 LOW"
    crossing = next((k + 1 for k, p in enumerate(probs) if p >= threshold), None)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Peak progression probability", f"{peak:.0%}")
    c2.metric("Risk level", level)
    c3.metric("Predicted stage (horizon)", pred_stage or "—")
    c4.metric("Warning lead time",
              f"{crossing} window{'s' if crossing != 1 else ''}" if crossing else "no warning",
              help="How many windows ahead of the forecast horizon the probability "
                   "first crosses the threshold. 1 window = 60s.")

    # ---- timeline: a readable slice, not the whole capture -----------------
    lo = max(0, anchor - CONTEXT_BEFORE)
    hi = min(len(windows), anchor + HORIZON + CONTEXT_AFTER)
    idx = windows.index[lo:hi]
    observed = windows["attack_frac"].to_numpy()[lo:hi]

    fc = np.full(len(idx), np.nan)
    a_rel = anchor - lo
    fc[a_rel] = observed[a_rel]                       # join the curves visually
    for k, p in enumerate(probs):
        if a_rel + 1 + k < len(fc):
            fc[a_rel + 1 + k] = p

    tl = pd.DataFrame({"observed attack activity": observed,
                       "forecast": fc,
                       "threshold": threshold}, index=idx)
    st.line_chart(tl, height=300)
    st.caption(
        f"Anchor **{windows.index[anchor]:%d %b %H:%M}** — the last window the model sees. "
        f"Everything right of it is forecast ({HORIZON} windows = {HORIZON} min). "
        "Observed activity is ground truth, shown only to check the forecast; the model "
        "never receives it."
    )

    left, right = st.columns([1, 2])
    with left:
        st.subheader("MITRE ATT&CK strip")
        p99b = float(windows["bytes_total"].quantile(0.99))
        p99p = float(windows["pkts_total"].quantile(0.99))
        rule_stage = rule_based_stage(windows.iloc[anchor].to_dict(), p99b, p99p)
        hit = pred_stage if pred_stage in CHAIN else None

        cols = st.columns(len(CHAIN))
        for box, name in zip(cols, CHAIN):
            hot = name == hit
            box.markdown(
                f"<div style='padding:10px 6px;border-radius:8px;text-align:center;"
                f"font-size:12px;background:{'#b91c1c' if hot else '#27272a'};"
                f"color:{'#fff' if hot else '#a1a1aa'}'>{name}</div>",
                unsafe_allow_html=True,
            )
        if pred_stage == "DoS":
            st.info("Model stage: **DoS** — shown outside the chain on purpose "
                    "(ATT&CK places flooding under Impact).")
        elif hit is None:
            st.caption("No stage highlighted — the model did not predict a chain stage "
                       "for this horizon.")
        st.caption(f"Rule engine (independent cross-check): **{rule_stage or 'no rule matched'}**")
        if peak >= threshold:
            st.error(f"🚨 Attack progression forecast within {HORIZON} windows "
                     f"(p={peak:.0%}). Investigate flagged flows — decision support, "
                     "not auto-blocking.")

    with right:
        st.subheader("WHY? — feature attribution")
        if why:
            wdf = pd.DataFrame(why, columns=["feature", "|attribution|"]).set_index("feature")
            st.bar_chart(wdf, height=260)
            st.caption("IntegratedGradients on the sequence input, |attribution| summed "
                       "over the time axis.")
        else:
            if why_err:
                st.warning(f"Attribution unavailable — {why_err}")
            corr = windows[list(WINDOW_FEATURES)].corrwith(windows["attack_frac"]).abs().nlargest(6)
            st.bar_chart(corr.rename("SIMULATED |correlation|"), height=260)
            st.caption("⚠️ SIMULATED: global feature/label correlation, not per-prediction "
                       "attribution.")
else:
    st.info("Pick a scenario and hit **ANALYZE + FORECAST**.")


# ---------------------------------------------------------------- tabs
t1, t2, t3 = st.tabs(["Flagged windows", "Benchmark", "Lead time"])

with t1:
    flagged = windows[windows["attack_frac"] > 0].sort_values("attack_frac", ascending=False)
    show = flagged.head(15).drop(
        columns=[c for c in windows.columns if c.startswith("frac_")], errors="ignore"
    ).reset_index(names="window")
    st.dataframe(show, use_container_width=True, height=320)
    st.caption(f"{len(flagged):,} of {len(windows):,} windows contain attack activity.")

with t2:
    rows, per_step = [], {}
    for mf in sorted(MODELS.glob("metrics_*.json")):
        if mf.name == "metrics_lead_time.json":
            continue
        for name, m in json.loads(mf.read_text(encoding="utf-8")).items():
            rows.append({"model": name.replace("_", " "),
                         **{k: v for k, v in m.items() if not k.startswith("_")}})
            if m.get("_per_step"):
                per_step[name] = m["_per_step"]
    if rows:
        st.dataframe(pd.DataFrame(rows).set_index("model"), use_container_width=True)
        st.caption("Chronological test split. Identical features, identical transform, "
                   "identical split for every model — that is what makes the comparison "
                   "meaningful. Threshold picked on validation under an FPR budget, never "
                   "on test. Numbers come from the training scripts; never hand-edited.")
        if per_step:
            st.markdown("**Per horizon step** — does accuracy decay as we forecast further?")
            for name, steps in per_step.items():
                df = pd.DataFrame(steps)
                df.index = [f"t+{i + 1}" for i in range(len(df))]
                st.markdown(f"`{name}`")
                st.dataframe(df[["precision", "recall", "f1", "fpr", "pr_auc"]],
                             use_container_width=True)
    else:
        st.info("No metrics yet. Run `python -m src.models.baseline_logreg` and "
                "`python -m src.models.lstm_forecaster`. The PS requires the logistic "
                "baseline comparison.")

with t3:
    lt_path = MODELS / "metrics_lead_time.json"
    if lt_path.exists():
        lt = json.loads(lt_path.read_text(encoding="utf-8"))
        df = pd.DataFrame({k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                           for k, v in lt.items()}).T
        st.dataframe(df, use_container_width=True)
        if "lstm_forecaster" in lt and "logistic_baseline" in lt:
            a = lt["lstm_forecaster"]["median_lead_min"]
            b = lt["logistic_baseline"]["median_lead_min"]
            st.metric("Median early-warning advantage (LSTM − logistic)",
                      f"{a - b:+.1f} min")
        st.caption("Lead time = how far ahead of an attack's onset the forecast first "
                   "crosses the alert threshold, over every onset in the held-out split. "
                   "This is the metric a SOC actually buys: detection accuracy alone does "
                   "not tell you whether a warning arrived in time to act.")
    else:
        st.info("No lead-time numbers yet. Run `python -m src.evaluation.lead_time`.")
