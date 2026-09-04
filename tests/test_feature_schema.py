"""Canonical schema invariants — the contract every adapter depends on."""
from __future__ import annotations

import math

from src.features.canonical_schema import (
    CANONICAL_FEATURES, FEATURE_INDEX, FEATURE_NAMES, N_FEATURES,
    Policy, V1_INDICES, V1_ORDER, WindowSlots, availability_for,
    schema_hash, v1_mask_for,
)


def test_v1_order_matches_window_builder():
    """The canonical schema must contain the legacy 18 in the legacy order."""
    from src.features.window_builder import WINDOW_FEATURES
    assert V1_ORDER == list(WINDOW_FEATURES)
    assert [FEATURE_NAMES[i] for i in V1_INDICES] == list(WINDOW_FEATURES)


def test_names_unique_and_indexed():
    assert len(set(FEATURE_NAMES)) == N_FEATURES
    assert FEATURE_INDEX[FEATURE_NAMES[0]] == 0
    assert FEATURE_INDEX[FEATURE_NAMES[-1]] == N_FEATURES - 1


def test_slots_missing_never_silent_zero():
    ws = WindowSlots(source="test")
    ws.set("flow_count", 42.0, "test")
    vec = ws.vector(Policy.MASKED)
    assert vec[FEATURE_INDEX["flow_count"]] == 42.0
    assert math.isnan(vec[FEATURE_INDEX["ttl_mean"]])       # absent → NaN
    assert ws.availability_mask()[FEATURE_INDEX["ttl_mean"]] is False
    # V1_COMPAT reproduces the legacy zero-fill exactly
    assert ws.vector(Policy.V1_COMPAT)[FEATURE_INDEX["ttl_mean"]] == 0.0


def test_v1_vector_projection():
    ws = WindowSlots(source="test")
    for i, n in enumerate(FEATURE_NAMES):
        ws.set(n, float(i), "test")
    assert ws.v1_vector() == [float(i) for i in V1_INDICES]


def test_cic2018_capability_is_honest():
    """IP features were zero-filled in V1 because the CSVs lack the columns —
    the canonical matrix must call them unavailable, not present-with-zero."""
    mask = v1_mask_for("cic2018")
    names = dict(zip(V1_ORDER, mask))
    assert names["unique_dst_ips"] is False
    assert names["unique_src_ips"] is False
    assert names["flow_count"] is True
    # live sensor DOES see IPs
    live = dict(zip(V1_ORDER, v1_mask_for("live")))
    assert live["unique_dst_ips"] is True


def test_unknown_dataset_is_fully_unavailable():
    assert not any(availability_for("not_a_dataset"))
    assert not any(v1_mask_for("not_a_dataset"))


def test_schema_hash_stable_and_sensitive():
    h1 = schema_hash()
    h2 = schema_hash()
    assert h1 == h2 and len(h1) == 16
    # hash covers name, group, v1 flag and log flag: any change must move it
    assert h1 != "0000000000000000"


def test_every_feature_has_group_and_description():
    for f in CANONICAL_FEATURES:
        assert f.description and f.group
