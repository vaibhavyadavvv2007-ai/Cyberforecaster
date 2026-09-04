"""Phase 5 tests — the ONE sequence engine across all three sources.

Proves the DATA_CONTRACT §3–§5 claims on golden data:
  1. training path: CIC CSV → adapter slots → canonical sequences
  2. packet path:   PacketFeaturePipeline slots → the SAME engine
  3. gaps become explicit empty windows (zero-observation, packet features
     honestly absent), never timeline holes
  4. CanonicalScaler: masked statistics, NaN propagation, schema-hash guard
  5. chrono_split_canonical purges at day boundaries like the V1 split
  6. the bin size is single-sourced (src.config) — no stale 60s default left
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from src.config import BIN_SECS
from src.datasets.registry import get_adapter
from src.features.canonical_schema import FEATURE_INDEX, N_FEATURES, V1_INDICES
from src.features.packet_features import PacketFeaturePipeline
from src.features.sequence_engine import (CanonicalScaler, CanonicalSequences,
                                          chrono_split_canonical,
                                          empty_bin_slots,
                                          make_canonical_sequences)
from src.features.window_builder import build_windows
from src.labels.attack_taxonomy import BENIGN

# reuse the golden CIC fixture shape from the adapter tests
from tests.test_dataset_adapters import CIC_COLS, _row


@pytest.fixture()
def cic_csv(tmp_path):
    rows = (
        [_row(f"14/02/2018 09:00:{s:02d}", "Benign") for s in range(0, 30, 5)]
        + [_row(f"14/02/2018 09:01:{s:02d}", "Benign") for s in range(0, 20, 5)]
        + [_row(f"14/02/2018 09:01:{s:02d}", "SSH-Brute-Force", port=22,
                syn=1) for s in range(20, 30, 2)]
    )
    p = tmp_path / "Wednesday-14-02-2018_TrafficForML_CICFlowMeter.csv"
    pd.DataFrame(rows, columns=CIC_COLS).to_csv(p, index=False)
    return p


# ------------------------------------------------------- training path (CSV)

def test_training_csv_through_canonical_engine(cic_csv):
    a = get_adapter("cic2018")
    flows = a.load([cic_csv])
    slots, labels = a.to_window_slots(flows, bin_secs=30)
    seq = make_canonical_sequences(slots, labels, seq_len=1, horizon=1)

    # 3 windows: 09:00, the skipped 09:00:30 bin (explicit empty), 09:01
    assert len(seq.ts) == 3
    assert seq.X.shape == (2, 1, N_FEATURES)
    # availability mask mirrors the CIC2018 capability set: IPs are NaN
    ip = FEATURE_INDEX["unique_src_ips"]
    ttl = FEATURE_INDEX["ttl_mean"]
    assert np.isnan(seq.X[0, 0, ip])
    assert not seq.mask[0, 0, ip]
    assert np.isnan(seq.X[0, 0, ttl])
    assert seq.mask[0, 0, FEATURE_INDEX["flow_count"]]
    # seq 0's horizon window is the EMPTY gap bin (benign); seq 1's is the
    # brute-force bin — per-step labels, not any-in-horizon
    assert seq.y_prog is not None
    assert seq.y_prog[0, 0] == 0.0
    assert seq.y_prog[1, 0] == 1.0
    # the gap window itself: flow features zero-observation, packet absent
    assert seq.X[1, 0, FEATURE_INDEX["flow_count"]] == 0.0


def test_y_prog_per_step_and_stage(cic_csv):
    a = get_adapter("cic2018")
    flows = a.load([cic_csv])
    slots, labels = a.to_window_slots(flows, bin_secs=30)
    seq = make_canonical_sequences(slots, labels, seq_len=1, horizon=1)
    # seq 0 horizon = benign gap bin → no stage; seq 1 = SSH → INITIAL_ACCESS
    assert seq.y_stage is not None
    assert seq.y_stage[0] == -1
    assert seq.y_stage[1] >= 0


# --------------------------------------------------------- packet path (pcap)

def test_packet_windows_through_same_engine():
    from src.features.packet_features import PacketObservation
    pipe = PacketFeaturePipeline(bin_secs=BIN_SECS)
    t0 = 999_999_990
    pipe.observe_packet(PacketObservation(
        ts=t0, src="10.0.0.1", sport=40000, dst="10.0.0.2",
        dport=443, proto="tcp", ip_len=60, ttl=64, tcp_flags=0x02, tcp_seq=1))
    pipe.observe_packet(PacketObservation(
        ts=t0 + BIN_SECS, src="10.0.0.1", sport=40000, dst="10.0.0.2",
        dport=443, proto="tcp", ip_len=60, ttl=64, tcp_flags=0x02, tcp_seq=2))
    slots = pipe.close()
    seq = make_canonical_sequences(slots, None, seq_len=1, horizon=1)
    # live/upload has no ground truth: y stays None, X still flows through
    assert seq.y_prog is None and seq.y_stage is None
    assert seq.X.shape[0] == 1                          # 2 windows → 1 sequence
    assert seq.mask[0, 0, FEATURE_INDEX["ttl_mean"]]      # packets provide TTL


# ------------------------------------------------------------- gap handling

def test_gaps_become_explicit_empty_windows():
    ts0 = 999_999_990                    # 30s-aligned
    slots = [
        PacketFeaturePipelineSlots(ts0),
        PacketFeaturePipelineSlots(ts0 + 3 * BIN_SECS),   # 2 missing bins
    ]
    seq = make_canonical_sequences(slots, None, seq_len=1, horizon=1)
    assert len(seq.ts) == 4                             # 2 real + 2 empty
    # empty bin (window 1): flow features zero-observation, packet features absent
    e, m = seq.X[1, 0], seq.mask[1, 0]
    assert e[FEATURE_INDEX["flow_count"]] == 0.0 and m[FEATURE_INDEX["flow_count"]]
    assert np.isnan(e[FEATURE_INDEX["ttl_mean"]]) and not m[FEATURE_INDEX["ttl_mean"]]
    assert np.isnan(e[FEATURE_INDEX["burstiness"]]) and not m[FEATURE_INDEX["burstiness"]]
    assert e[FEATURE_INDEX["ssh_ratio"]] == 0.0 and m[FEATURE_INDEX["ssh_ratio"]]


def PacketFeaturePipelineSlots(ts: float):
    from src.features.canonical_schema import WindowSlots
    ws = WindowSlots(source="pcap", ts=ts)
    ws.set("flow_count", 1.0, "pcap")
    ws.set("ttl_mean", 64.0, "pcap")
    return ws


# ----------------------------------------------------------------- splitting

def test_chrono_split_purges_at_day_boundary():
    # 200 bins with a 2-day jump inside: window i>=100 is shifted +2 days
    n = 200
    jump = 2 * 86400 // BIN_SECS                 # 2 days, in bins
    ts = np.array([(i + (jump if i >= 100 else 0)) * BIN_SECS
                   for i in range(n)], dtype=np.float64)
    ends = np.arange(12, n + 1)          # seq_len=10, horizon=2
    tr, va, te = chrono_split_canonical(ts, ends, seq_len=10, horizon=2)
    # no overlap, chronological order preserved, all non-empty
    assert tr and va and te
    assert max(tr) < min(va) and max(va) < min(te)
    # boundary purge: sequences whose span touches the day change are dropped
    days = ts.astype("datetime64[s]").astype("datetime64[D]")
    change = next(i for i in range(1, n) if days[i] != days[i - 1])
    for j in tr + va + te:
        start = ends[j] - 2 - 10 + 1
        assert abs(ends[j] - change) > 2 and abs(start - change) > 2


# ------------------------------------------------------------------- scaling

def test_scaler_masked_statistics_and_roundtrip(tmp_path):
    rng = np.random.default_rng(7)
    n, L = 200, 10
    X = rng.normal(5, 2, size=(n, L, N_FEATURES)).astype(np.float32)
    # make ttl_* and payload_* unavailable everywhere
    for name in ("ttl_mean", "payload_size_p50"):
        X[:, :, FEATURE_INDEX[name]] = np.nan
    sc = CanonicalScaler().fit(X)
    Z = sc.transform(X)
    assert np.isnan(Z[0, 0, FEATURE_INDEX["ttl_mean"]])   # NaN propagates
    assert np.isfinite(Z[0, 0, FEATURE_INDEX["flow_count"]])
    # available features standardised
    assert abs(Z[:, :, FEATURE_INDEX["flow_count"]].mean()) < 0.05
    assert 0.9 < Z[:, :, FEATURE_INDEX["flow_count"]].std() < 1.1
    # save/load round-trip with schema guard
    p = tmp_path / "canonical_scaler.npz"
    sc.save(p)
    sc2 = CanonicalScaler.load(p)
    assert np.allclose(sc.transform(X), sc2.transform(X), equal_nan=True)


def test_scaler_log_transform_order():
    # log1p applied BEFORE standardisation on log_transform features (same
    # order as the V1 scaler, so V1↔V2 feature comparisons stay meaningful)
    X = np.full((1, 1, N_FEATURES), 1000.0, dtype=np.float32)
    sc = CanonicalScaler().fit(X)
    idx = FEATURE_INDEX["flow_count"]          # log_transform=True
    # constant feature → std forced to 1.0, so z = log1p(1000) - mean(=same)
    assert sc.transform(X)[0, 0, idx] == pytest.approx(np.log1p(1000.0) - sc.means[idx], abs=1e-4)


def test_scaler_all_nan_feature_is_noop_not_poison():
    X = np.full((5, 2, N_FEATURES), np.nan, dtype=np.float32)
    X[:, :, FEATURE_INDEX["flow_count"]] = 3.0
    sc = CanonicalScaler().fit(X)
    Z = sc.transform(X)
    assert np.isfinite(Z[:, :, FEATURE_INDEX["flow_count"]]).all()
    assert np.isnan(Z[:, :, FEATURE_INDEX["ttl_mean"]]).all()


# --------------------------------------------------- single-sourcing checks

def test_bin_secs_single_sourced_everywhere():
    from src.features import packet_features, sequence_engine, window_builder
    from src.preprocessing import pipeline
    from src.evaluation import lead_time
    from api import live_state

    assert BIN_SECS == 30
    # no stale 60-second defaults survive in any signature
    for mod, fn in [
        (window_builder, window_builder.build_windows),
        (pipeline, pipeline.run),
        (lead_time, lead_time.to_minutes),
        (lead_time, lead_time.main),
        (packet_features, packet_features.extract_pcap),
    ]:
        default = inspect.signature(fn).parameters["bin_secs"].default
        assert default == BIN_SECS, f"{fn.__name__} default {default} != {BIN_SECS}"
    assert live_state.BIN_SECS == BIN_SECS
