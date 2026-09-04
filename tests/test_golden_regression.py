"""Phase 14 — golden regression fixtures.

Pins the frozen V1 stack so accidental artifact drift is caught by pytest,
not during the demo:

  - sha256 of every frozen artifact (live model, scaler, Phase 9 baselines,
    and the frozen baseline copy under models/baseline_cic2018_v1/)
  - exact Forecaster.predict outputs (probs to 4 decimals, stage, threshold)
    on four fixed inputs: two synthetic sequences and two real slices of the
    frozen training windows (deterministically selected)
  - the seeded MC-dropout band on a fixed input (seed=0, T=16)
  - API contracts via TestClient: /api/health shape, /api/forecast
    determinism, /api/datasets registry statuses

If a golden value legitimately changes (e.g. a deliberate retrain), update it
HERE on purpose and record why in the plan — never delete a pin to "fix" the
test. The demo (Sep 5, 2026) runs on these exact bytes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from src.config import SEQ_LEN
from src.features.window_builder import WINDOW_FEATURES

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- goldens

# First 16 hex chars of sha256 — enough to catch any byte-level change.
ARTIFACT_SHA256_16 = {
    "models/trained_models/lstm_forecaster.pt": "2b41bec7be520540",
    "data/processed/scaler.npz": "5e6be0e74fc7ecde",
    "models/benign_baseline.json": "b0e395f1c65989f9",
    "models/calibration_v1.json": "dbfd1acc76e2af3d",
    # the frozen baseline copy must stay byte-identical to the live model
    "models/baseline_cic2018_v1/trained_models/lstm_forecaster.pt":
        "2b41bec7be520540",
    "models/baseline_cic2018_v1/data/processed/scaler.npz":
        "5e6be0e74fc7ecde",
}

THRESHOLD = 0.5612232685089111

GOLDEN_PREDICT = {
    # built by _synthetic(benign): quiet uniform 2-flow windows
    "synthetic_benign": {
        "probs": [0.3026, 0.3282, 0.3664, 0.3654, 0.3994], "stage": "DoS"},
    # built by _synthetic(..., ramp=True): syn_ratio 0.8 ramp in the last 5
    "synthetic_synflood_ramp": {
        "probs": [0.13, 0.1315, 0.1652, 0.1589, 0.2076], "stage": "DoS"},
    # first SEQ_LEN rows of data/processed/windows.parquet (all benign)
    "real_benign_head": {
        "probs": [0.009, 0.0112, 0.0137, 0.0111, 0.0173],
        "stage": "Initial Access"},
    # the SEQ_LEN windows ending at the first attack_frac > 0.5 row
    # (rows 105-114; labels ramp 0 -> 0.08 -> 0.62 — a true attack onset)
    "real_attack_onset": {
        "probs": [0.4835, 0.4814, 0.4843, 0.4921, 0.4793],
        "stage": "Initial Access"},
}

# mc_dropout_forecast(model, scaled(synthetic_benign), T=16, seed=0)
GOLDEN_MC = {
    "probs_mean": [0.3386, 0.3505, 0.4158, 0.39, 0.4304],
    "probs_std": [0.1233, 0.1185, 0.1404, 0.1365, 0.1393],
    "max_std": 0.1404,
    "confidence": "MEDIUM",
    "T": 16,
    "stage_votes": {"5": 16},
}


# ------------------------------------------------------------- fixtures

def _synthetic(ramp: bool = False) -> np.ndarray:
    """(SEQ_LEN, F) benign windows; ramp=True switches the last 5 windows to a
    syn-flood-ish burst. Pure function of WINDOW_FEATURES order — no file
    access, so it pins the model+scaler bytes alone."""
    def feats(**over):
        f = {c: 0.0 for c in WINDOW_FEATURES}
        f.update({"flow_count": 20.0, "pkts_total": 400.0,
                  "bytes_total": 48_000.0, "unique_dst_ports": 6.0,
                  "iat_mean": 2.0, "avg_pkt_size": 120.0})
        f.update(over)
        return f

    rows = []
    for b in range(SEQ_LEN):
        over = {}
        if ramp and b >= SEQ_LEN - 5:
            over = {"syn_ratio": 0.8, "flow_count": 2000.0,
                    "pkts_total": 90_000.0, "bytes_total": 5_400_000.0,
                    "unique_dst_ports": 1.0, "iat_mean": 0.01}
        rows.append([feats(**over)[c] for c in WINDOW_FEATURES])
    return np.asarray(rows, dtype=np.float64)


def _real_slices() -> dict[str, np.ndarray]:
    """Deterministically-selected slices of the frozen training windows."""
    import pandas as pd
    wt = pd.read_parquet(ROOT / "data" / "processed" / "windows.parquet")
    arr = wt[WINDOW_FEATURES].to_numpy(dtype=np.float64)
    lab = wt["attack_frac"].to_numpy()
    idx = int(np.argmax(lab > 0.5))            # first mostly-attack window
    start = max(0, idx - SEQ_LEN + 1)
    return {"real_benign_head": arr[:SEQ_LEN],
            "real_attack_onset": arr[start:start + SEQ_LEN]}


@pytest.fixture(scope="module")
def forecaster():
    from src.forecasting.rollout import Forecaster
    fc, err = Forecaster.load()
    if fc is None:
        pytest.skip(f"frozen V1 model unavailable: {err}")
    return fc


# ---------------------------------------------------------------- tests

def test_frozen_artifacts_unchanged():
    """Every pinned artifact hashes exactly as recorded on 2026-09-04."""
    for rel, want in ARTIFACT_SHA256_16.items():
        p = ROOT / rel
        assert p.exists(), f"frozen artifact missing: {rel}"
        got = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        assert got == want, (
            f"{rel} changed (sha {got} != {want}). If this was a deliberate "
            "retrain, update the pin in tests/test_golden_regression.py and "
            "record why — never delete the pin.")


def test_baseline_freeze_is_live_model():
    """The frozen baseline copy must be byte-identical to the running model."""
    live = hashlib.sha256(
        (ROOT / "models/trained_models/lstm_forecaster.pt").read_bytes()
    ).hexdigest()
    frozen = hashlib.sha256(
        (ROOT / "models/baseline_cic2018_v1/trained_models"
         / "lstm_forecaster.pt").read_bytes()
    ).hexdigest()
    assert live == frozen


@pytest.mark.parametrize("case", ["synthetic_benign",
                                  "synthetic_synflood_ramp",
                                  "real_benign_head", "real_attack_onset"])
def test_predict_golden(case, forecaster):
    if case.startswith("synthetic"):
        seq = _synthetic(ramp=case.endswith("ramp"))
    else:
        seq = _real_slices()[case]
    res = forecaster.predict(seq)
    gold = GOLDEN_PREDICT[case]
    assert res["probs"] == gold["probs"], f"{case} probs drifted"
    assert res["stage"] == gold["stage"], f"{case} stage drifted"
    assert res["threshold"] == THRESHOLD


def test_predict_is_deterministic(forecaster):
    seq = _synthetic()
    assert forecaster.predict(seq) == forecaster.predict(seq)


def test_mc_dropout_golden(forecaster):
    from src.explainability.uncertainty import mc_dropout_forecast
    mc = mc_dropout_forecast(forecaster.model,
                             forecaster.scaled(_synthetic()), T=16, seed=0)
    assert mc["probs_mean"] == GOLDEN_MC["probs_mean"]
    assert mc["probs_std"] == GOLDEN_MC["probs_std"]
    assert mc["max_std"] == GOLDEN_MC["max_std"]
    assert mc["confidence"] == GOLDEN_MC["confidence"]
    assert mc["T"] == GOLDEN_MC["T"]
    assert mc["stage_votes"] == GOLDEN_MC["stage_votes"]


def test_real_attack_onset_slice_is_an_attack():
    """Guard the golden slice itself: it must contain the attack onset, or the
    parquet changed under us and the golden values above are meaningless."""
    slices = _real_slices()
    assert slices["real_attack_onset"].shape == (SEQ_LEN, len(WINDOW_FEATURES))
    import pandas as pd
    wt = pd.read_parquet(ROOT / "data" / "processed" / "windows.parquet")
    lab = wt["attack_frac"].to_numpy()
    idx = int(np.argmax(lab > 0.5))
    assert lab[idx - 1] <= 0.1 < lab[idx], "onset structure changed"


# ------------------------------------------------------------- API layer

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    # context manager triggers the app's lifespan (state boot)
    with TestClient(app) as c:
        yield c


def test_api_health_contract(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    h = r.json()
    for key in ("mode", "boot_error", "model_error", "n_windows",
                "n_scenarios", "threshold", "mean_attack_frac"):
        assert key in h
    assert h["boot_error"] is None
    assert h["model_error"] is None
    assert h["n_scenarios"] > 0
    assert h["threshold"] == pytest.approx(THRESHOLD, abs=1e-6)


def test_api_forecast_deterministic(client):
    scen = client.get("/api/scenarios").json()
    assert scen, "no scenarios registered"
    sid = scen[0]["id"]
    a = client.post("/api/forecast", json={"scenario_id": sid}).json()
    b = client.post("/api/forecast", json={"scenario_id": sid}).json()
    assert a == b, "same scenario forecast differs between calls"
    assert a["scenario_id"] == sid
    assert len(a["probs"]) == 5
    assert 0.0 <= a["peak"] <= 1.0


def test_api_datasets_registry(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    rows = r.json()["datasets"]
    ids = {row["id"] for row in rows}
    assert {"cic2018", "cic2017", "unsw_nb15", "ctu13"} <= ids
    by_id = {row["id"]: row for row in rows}
    assert by_id["cic2018"]["status"] == "READY"
    # pending adapters report honestly — never silently READY
    for did in ("cic2017", "unsw_nb15", "ctu13"):
        assert by_id[did]["status"] in ("READY", "PENDING_WIRING",
                                        "NOT_DOWNLOADED")
