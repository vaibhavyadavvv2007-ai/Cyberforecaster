"""Phase 13 tests — live-feed enrichment with Phase 9/10 outputs.

Proves the additive contract on LiveHistory.predict():
  - with engines attached, the live forecast carries uncertainty (seeded MC),
    evidence (from RAW observed values, not the conditioning zeros/clamps),
    and a decision-support record — same engines the upload path uses
  - with engines absent, predict() returns exactly the legacy fields plus
    None enrichments: the demo-day live path degrades, never breaks
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config import SEQ_LEN
from src.features.window_builder import WINDOW_FEATURES
from src.live.history import LiveHistory, model_matrix


def _window(bin_id: int, **over) -> dict:
    """One benign-looking live window; `over` overrides feature values."""
    feats = {c: 0.0 for c in WINDOW_FEATURES}
    feats.update({"flow_count": 20.0, "pkts_total": 400.0,
                  "bytes_total": 48_000.0, "unique_dst_ports": 6.0,
                  "iat_mean": 2.0, "avg_pkt_size": 120.0})
    feats.update(over)
    return {"ts": 1_700_000_000 + bin_id * 30, "bin_id": bin_id,
            "source": "seed", "features": feats, "empty": False}


@pytest.fixture()
def real_forecaster():
    from src.forecasting.rollout import Forecaster
    fc, err = Forecaster.load()
    if fc is None:
        pytest.skip(f"frozen V1 model unavailable: {err}")
    return fc


@pytest.fixture()
def engines():
    from src.decision_support.engine import DecisionSupportEngine
    from src.explainability.evidence import EvidenceEngine
    baseline = Path("models/benign_baseline.json")
    ev = EvidenceEngine.load(baseline) if baseline.exists() else None
    return ev, DecisionSupportEngine()


def _history(forecaster, evidence_engine=None, ds_engine=None) -> LiveHistory:
    h = LiveHistory(forecaster=forecaster, rule_p99=(1e12, 1e9),
                    evidence_engine=evidence_engine, ds_engine=ds_engine)
    for b in range(SEQ_LEN):
        h.append_live(_window(b))
    return h


def test_predict_with_engines_full_record(real_forecaster, engines):
    from src.decision_support.levels import LEVELS
    h = _history(real_forecaster, engines[0], engines[1])
    out = h.predict()
    assert out is not None

    # uncertainty: seeded MC, deterministic band
    unc = out["uncertainty"]
    assert unc and unc["T"] == 16
    assert unc["confidence"] in ("HIGH", "MEDIUM", "LOW")
    assert len(unc["probs_mean"]) == 5

    # evidence: real numbers, ranked by attribution
    if out["evidence"]:
        e = out["evidence"][0]
        assert {"feature", "observed", "benign_mean", "z", "direction",
                "attribution"} <= set(e)

    # decision support: the same record shape the upload path produces
    ds = out["decision_support"]
    assert ds["level"] in LEVELS
    assert "NOT blocked" in ds["human_in_loop"]
    assert ds["recommendations"]

    # legacy fields unchanged — the live demo path is not disturbed
    for k in ("probs", "peak", "level", "stage", "threshold",
              "crossing_step", "why", "rule_stage", "n_history"):
        assert k in out


def test_predict_deterministic_uncertainty(real_forecaster):
    h1 = _history(real_forecaster)
    h2 = _history(real_forecaster)
    assert h1.predict()["uncertainty"] == h2.predict()["uncertainty"]


def test_engines_absent_degrade_to_none(real_forecaster):
    """Demo safety: no artifacts → None enrichments, forecast still returns."""
    h = _history(real_forecaster)                    # no engines attached
    out = h.predict()
    assert out is not None
    assert out["evidence"] is None
    assert out["decision_support"] is None
    assert out["uncertainty"] is not None            # MC needs no artifact


def test_evidence_shows_raw_values_not_conditioned(real_forecaster, engines):
    """ack_ratio is clamped to the training p99 for the model input, but the
    evidence row must cite what was actually OBSERVED (10.0), not the clamp."""
    h = LiveHistory(forecaster=real_forecaster, rule_p99=(1e12, 1e9),
                    evidence_engine=engines[0])
    for b in range(SEQ_LEN):
        h.append_live(_window(b, ack_ratio=10.0))
    out = h.predict()

    # sanity: the model input really was clamped
    seq = model_matrix(h.all_windows()[-SEQ_LEN:])
    i = WINDOW_FEATURES.index("ack_ratio")
    assert seq[-1, i] < 10.0

    row = next(e for e in out["evidence"] if e["feature"] == "ack_ratio")
    assert row["observed"] == 10.0
    assert row["direction"] == "elevated"


def test_not_ready_returns_none(real_forecaster):
    h = LiveHistory(forecaster=real_forecaster, rule_p99=(1e12, 1e9))
    for b in range(SEQ_LEN - 1):
        h.append_live(_window(b))
    assert h.predict() is None
