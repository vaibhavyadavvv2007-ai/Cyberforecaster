"""CyberForecaster demo app — fully offline.

Runs in SIMULATED mode (clearly badged) until a trained model exists at
models/trained_models/lstm_forecaster.pt; then every panel is real inference.

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

PROCESSED = ROOT / "data" / "processed"
MODEL_PATH = ROOT / "models" / "trained_models" / "lstm_forecaster.pt"
SEQ_LEN, HORIZON = 10, 5
RISK_THRESHOLD = 0.6

st.set_page_config(page_title="CyberForecaster", page_icon="🛡️", layout="wide")
st.title("🛡️ CyberForecaster — temporal attack-progression forecasting")

# ---------------------------------------------------------------- state
@st.cache_data
def load_windows(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def load_model():
    try:
        from src.forecasting.rollout import load_model as _lm
        return _lm(MODEL_PATH)
    except Exception as exc:  # noqa: BLE001 — demo must never crash on optional deps
        return None, f"model unavailable: {exc}"


def simulated_forecast(hist: np.ndarray, k: int = HORIZON) -> list[float]:
    """Damped-momentum extrapolation of recent attack activity — placeholder only."""
    recent = hist[-3:] if len(hist) >= 3 else hist
    momentum = float(np.mean(np.diff(recent))) if len(recent) > 1 else 0.0
    out, val = [], float(hist[-1])
    for i in range(k):
        val = float(np.clip(val + momentum * (0.7 ** i), 0.0, 1.0))
        out.append(round(val, 4))
    return out


samples = sorted(PROCESSED.glob("windows.parquet"))
if not samples:
    st.warning(
        "No `data/processed/windows.parquet` found.\n\n"
        "1. `python scripts/download_data.py --list` → `--yes`\n"
        "2. `python -m src.preprocessing.pipeline`\n"
        "3. reload this page"
    )
    st.stop()

with st.sidebar:
    st.header("Input")
    sample_file = st.selectbox("Processed traffic", [str(s.relative_to(ROOT)) for s in samples])
    windows = load_windows(ROOT / sample_file)
    st.caption(f"{len(windows):,} windows · {windows['attack_frac'].mean():.1%} mean attack frac")
    model, cfg = load_model()
    simulated = model is None
    if simulated:
        st.error("**SIMULATED MODE** — no trained model found. "
                 "Forecast/attribution panels are extrapolations, not inference.")
    else:
        st.success("Real model loaded")
    threshold = st.slider("Alert threshold", 0.0, 1.0, RISK_THRESHOLD, 0.05)

if simulated:
    st.warning("⚠️ **SIMULATED** — numbers below are extrapolated placeholders, shown to "
               "validate the UI. Train the LSTM (`python -m src.models.lstm_forecaster`) "
               "and reload for real inference.")

feats_cols = [c for c in windows.columns if c not in
              ("attack_frac", "dominant_stage_idx") and not c.startswith("frac_")]
hist = windows["attack_frac"].to_numpy()
stages = ["Reconnaissance", "Initial Access", "Lateral Movement",
          "Command & Control", "Exfiltration", "DoS"]

# ---------------------------------------------------------------- analyze
if st.button("▶️ ANALYZE + FORECAST", type="primary"):
    if simulated:
        probs = simulated_forecast(hist)
        why = None
        pred_stage = ""
    else:
        from src.forecasting.rollout import forecast_probabilities
        seq = windows[feats_cols].tail(SEQ_LEN).to_numpy(dtype=np.float32)
        result = forecast_probabilities(model, seq, stages)
        probs = result["probs"]
        pred_stage = result["stage"]
        why = None
        try:
            from src.explainability.attribution import integrated_gradients_attribution
            why = integrated_gradients_attribution(model, seq)
            order = np.argsort(-np.abs(why))[:6]
            why = [(feats_cols[i], float(abs(why[i]))) for i in order]
        except Exception:
            why = None

    peak = max(probs) if probs else 0.0
    level = "🔴 HIGH" if peak >= 0.8 else "🟠 ELEVATED" if peak >= threshold else "🟢 LOW"

    c1, c2, c3 = st.columns(3)
    c1.metric("Peak progression probability", f"{peak:.0%}", delta=f"+{(peak - hist[-1]):.0%}")
    c2.metric("Risk level", level)
    c3.metric("Predicted stage (horizon)", pred_stage or "—")

    # timeline: history solid, forecast dashed/shaded
    tl = pd.DataFrame({
        "history": np.concatenate([hist, np.full(HORIZON, np.nan)]),
        "forecast": np.concatenate([np.full(len(hist) - 1, np.nan), [hist[-1]], probs]),
        "threshold": threshold,
    })
    st.line_chart(tl, height=260)
    st.caption(f"Solid = observed attack activity · dashed = {HORIZON}-window forecast · "
               "flat line = alert threshold")

    left, right = st.columns([1, 2])
    with left:
        st.subheader("MITRE ATT&CK strip")
        chain = ["Reconnaissance", "Initial Access", "Lateral Movement",
                 "Command & Control", "Exfiltration"]
        cols = st.columns(len(chain))
        hit = pred_stage if pred_stage in chain else None
        for box, stage_name in zip(cols, chain):
            hot = stage_name == hit or (hit is None and peak >= threshold
                                        and stage_name == "Lateral Movement")
            box.markdown(
                f"<div style='padding:10px 6px;border-radius:8px;text-align:center;"
                f"font-size:12px;background:{'#b91c1c' if hot else '#27272a'};"
                f"color:{'#fff' if hot else '#a1a1aa'}'>{stage_name}</div>",
                unsafe_allow_html=True,
            )
        if peak >= threshold:
            st.error(f"🚨 Forecast: attack progression likely within {HORIZON} windows "
                     f"(p={peak:.0%}). Investigate flagged flows — decision support, "
                     "not auto-blocking.")
    with right:
        st.subheader("WHY? — feature attribution")
        if why is not None:
            wdf = pd.DataFrame(why, columns=["feature", "|attribution|"]).set_index("feature")
            st.bar_chart(wdf, height=240)
        elif simulated:
            # pseudo-importances from correlation with recent attack activity (SIMULATED)
            corr = windows[feats_cols].corrwith(windows["attack_frac"]).abs().nlargest(6)
            st.bar_chart(corr.rename("simulated |correlation|"), height=240)
            st.caption("SIMULATED attributions — replace with IntegratedGradients output.")
        else:
            st.info("Attribution unavailable for this prediction (captum missing?).")
else:
    st.info("Load a processed capture and hit **ANALYZE + FORECAST**.")

# ---------------------------------------------------------------- tabs
t1, t2 = st.tabs(["Flagged windows", "Benchmark"])
with t1:
    flagged = windows[windows["attack_frac"] > 0].sort_values("attack_frac", ascending=False)
    show = flagged.head(15).drop(
        columns=[c for c in windows.columns if c.startswith("frac_")], errors="ignore"
    ).reset_index(names="window")
    st.dataframe(show, use_container_width=True, height=320)

with t2:
    metrics_files = sorted((ROOT / "models").glob("metrics_*.json"))
    rows = []
    for mf in metrics_files:
        data = json.loads(mf.read_text(encoding="utf-8"))
        for name, m in data.items():
            rows.append({"model": name.replace("_", " "), **m})
    if rows:
        st.dataframe(pd.DataFrame(rows).set_index("model"), use_container_width=True)
        st.caption("Produced by baseline_logreg / lstm_forecaster on the chronological test "
                   "split. Report exactly these numbers.")
    else:
        st.info("No metrics yet — run `python -m src.models.baseline_logreg` first. "
                "The PS requires the logistic baseline comparison.")
