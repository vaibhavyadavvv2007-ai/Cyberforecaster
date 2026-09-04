"""CTU-13 adapter tests.

The synthetic fixture writes real-schema .binetflow files (15 columns, the
exact header, hex-port rows, the 'From-Botnet-V<N>' label convention read
from the real captures) and drives the full adapter path:
validate → load → to_window_slots → labels → canonical sequences.

A separate smoke test runs against the REAL extracted captures when they
exist (data/raw/ctu13/CTU-13-Dataset/…) — skipped otherwise, so CI on a
machine without the 1.9 GB download still passes.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.datasets.base import FLOW_COLUMNS
from src.datasets.ctu13 import BINETFLOW_COLUMNS
from src.datasets.registry import get_adapter, status
from src.features.canonical_schema import CTU13_AVAILABLE, FEATURE_NAMES
from src.features.sequence_engine import make_canonical_sequences
from src.labels.attack_taxonomy import (BENIGN, COMMAND_AND_CONTROL,
                                        canonicalize,
                                        canonicalize_ctu13)

BOTNET_LABEL = "flow=From-Botnet-V42-UDP-DNS"


def _row(ts: str, src="94.44.127.113", sport=1577, dir_="   ->",
         dst="147.32.84.59", dport=6881, proto="tcp", dur=1.0, pkts=4,
         tot=276, srcb=156, state="S_RA", label="flow=Background-Established"
         ) -> list:
    """One 15-column binetflow row. Defaults mirror a real background flow
    from capture20110810.binetflow."""
    return [ts, dur, proto, src, sport, dir_, dst, dport, state, 0, 0,
            pkts, tot, srcb, label]


@pytest.fixture()
def ctu_dir(tmp_path: Path) -> Path:
    """13 scenario directories (the full layout validate expects). Scenario 1
    carries the data: one benign bin, one botnet bin, one hex-port row.
    Scenario 2 shares scenario 1's clock ON PURPOSE — same-date scenarios
    must never merge into one bin."""
    root = tmp_path / "ctu13" / "CTU-13-Dataset"
    for scen in range(1, 14):
        (root / str(scen)).mkdir(parents=True)
    rows = (
        [_row(f"2011/08/10 09:00:{s:02d}.100000") for s in range(0, 30, 5)]
        + [_row(f"2011/08/10 09:01:{s:02d}.100000",
                src="147.32.84.165", sport=19236, dir_="  <->",
                dst="192.168.0.1", dport="0x0303", proto="udp", pkts=40,
                tot=4000, srcb=200, label=BOTNET_LABEL)
           for s in range(0, 30, 5)]
    )
    pd.DataFrame(rows, columns=BINETFLOW_COLUMNS).to_csv(
        root / "1" / "capture20110810.binetflow", index=False)
    # scenario 2: same wall-clock, benign only
    pd.DataFrame(
        [_row(f"2011/08/10 09:00:{s:02d}.100000") for s in range(0, 30, 5)],
        columns=BINETFLOW_COLUMNS).to_csv(
        root / "2" / "capture20110811.binetflow", index=False)
    # scenarios 3–13: one benign row each — the full 13-file layout
    for scen in range(3, 14):
        pd.DataFrame([_row("2011/08/16 09:00:00.100000")],
                     columns=BINETFLOW_COLUMNS).to_csv(
            root / str(scen) / f"capture20110816-{scen}.binetflow",
            index=False)
    return tmp_path / "ctu13"


# ---------------------------------------------------------------- taxonomy

def test_botnet_maps_to_c2_with_documented_family():
    rec = canonicalize_ctu13(BOTNET_LABEL, scenario=1)
    assert rec.canonical_label == COMMAND_AND_CONTROL
    assert rec.attack_family == "Neris"            # scenario→family table
    assert rec.dataset_label == BOTNET_LABEL       # original never discarded
    assert rec.mapping_source == "manual/research"


def test_scenario_selects_family():
    assert canonicalize_ctu13(BOTNET_LABEL, 3).attack_family == "Rbot"
    assert canonicalize_ctu13(BOTNET_LABEL, 8).attack_family == "Murlo"
    assert canonicalize_ctu13(BOTNET_LABEL, 7).attack_family == "Sogou"


def test_scenario_less_fallback_keeps_botnet():
    rec = canonicalize("ctu13", BOTNET_LABEL)      # upload auto-detect path
    assert rec.canonical_label == COMMAND_AND_CONTROL
    assert rec.attack_family == "Botnet"


def test_benign_labels():
    for sent in ("flow=From-Normal-V42-Stribrek",
                 "flow=Background-UDP-Established",
                 "flow=To-Background-CVUT-Proxy"):
        rec = canonicalize_ctu13(sent, 1)
        assert rec.canonical_label == BENIGN
        assert rec.dataset_label == sent


# -------------------------------------------------------------- validate

def test_validate_accepts_full_layout(ctu_dir: Path):
    a = get_adapter("ctu13")
    files = a.discover(ctu_dir.parent)
    assert len(files) == 13
    rep = a.validate(files)
    assert rep.ok, rep.errors
    assert rep.detected_format.startswith("CTU-13 binetflow")
    assert rep.confidence == 1.0


def test_validate_rejects_partial_download(ctu_dir: Path):
    a = get_adapter("ctu13")
    for f in (ctu_dir / "CTU-13-Dataset").rglob("*.binetflow"):
        f.unlink()
    (ctu_dir / "CTU-13-Dataset" / "1" / "capture20110810.binetflow") \
        .write_text(",".join(map(str, BINETFLOW_COLUMNS)) + "\n"
                    + ",".join(map(str, _row("2011/08/10 09:00:00.000000",
                                             label=BOTNET_LABEL))) + "\n")
    rep = a.validate(a.discover(ctu_dir.parent))
    assert not rep.ok
    assert any("partial" in v for v in rep.checks.values())


def test_validate_rejects_foreign_csv(ctu_dir: Path):
    a = get_adapter("ctu13")
    for f in (ctu_dir / "CTU-13-Dataset").rglob("*.binetflow"):
        f.unlink()
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(
        ctu_dir / "CTU-13-Dataset" / "1" / "capture20110810.binetflow",
        index=False)
    rep = a.validate(a.discover(ctu_dir.parent))
    assert not rep.ok


def test_registry_flipped_to_ready(ctu_dir: Path):
    """ctu13 registers the REAL adapter now — a pending stub must never
    shadow it."""
    from src.datasets.ctu13 import CTU13Adapter
    a = get_adapter("ctu13")
    assert isinstance(a, CTU13Adapter)
    assert status("ctu13", root=ctu_dir.parent) == "READY"


# ------------------------------------------------------------------- load

def test_load_produces_canonical_flow_record(ctu_dir: Path):
    a = get_adapter("ctu13")
    flows = a.load(a.discover(ctu_dir.parent))
    for col in FLOW_COLUMNS:
        assert col in flows.columns, f"missing canonical column {col}"
    # unavailable quantities are NaN — never fabricated zeros
    for col in ("iat_mean_s", "iat_std_s", "syn_cnt", "ack_cnt", "fin_cnt",
                "rst_cnt", "psh_cnt", "fwd_pkts", "bwd_pkts"):
        assert flows[col].isna().all(), f"{col} must be unavailable (NaN)"
    # fwd/bwd byte split: SrcBytes fwd, TotBytes-SrcBytes bwd
    bot = flows[flows["dataset_label"] == BOTNET_LABEL]
    assert (bot["fwd_bytes"] == 200).all()
    assert (bot["bwd_bytes"] == 3800).all()
    # hex port parsed, not dropped
    assert 0x0303 in set(flows["dst_port"].dropna())
    # labels verbatim
    assert set(flows["dataset_label"].unique()) == {
        "flow=Background-Established", BOTNET_LABEL}
    # scenario column carried for per-scenario windowing (all 13 fixture dirs)
    assert set(flows["scenario"].dropna().astype(int).unique()) == set(range(1, 14))


# ---------------------------------------------------------------- windows

def test_to_window_slots_availability_and_labels(ctu_dir: Path):
    a = get_adapter("ctu13")
    flows = a.load(a.discover(ctu_dir.parent))
    slots, labels = a.to_window_slots(flows, bin_secs=30)
    # 2 bins in scenario 1 + 1 bin in scenario 2 (same clock — never merged)
    # + 1 benign bin for each of scenarios 3–13 = 14 windows
    assert len(slots) == len(labels) == 14
    assert all(ws.source == "ctu13_binetflow" for ws in slots)

    for ws in slots[:2]:        # scenario 1's bins (multi-flow: std defined)
        for name in CTU13_AVAILABLE:
            assert ws.get(name).available, f"{name} must be available"
            assert ws.get(name).source == "ctu13_binetflow"
        for name in ("syn_ratio", "ack_ratio", "fin_ratio", "rst_ratio",
                     "psh_ratio", "iat_mean", "iat_std", "retransmission_rate",
                     "ttl_mean", "tcp_window_mean", "burstiness"):
            assert not ws.get(name).available, f"{name} must be unavailable"

    benign, attack, benign2 = slots[:3]
    assert benign.get("flow_count").value == 6.0
    # botnet bin: 6 flows, one distinct hex dst port, one source IP
    assert attack.get("flow_count").value == 6.0
    assert attack.get("unique_dst_ports").value == 1.0
    assert attack.get("unique_src_ips").value == 1.0
    assert attack.get("down_up_ratio").value == pytest.approx(3800.0 / 200.0)

    # labels: dominant original preserved; botnet → C2 with the S1 family
    assert labels[0].canonical_label == BENIGN
    assert labels[1].canonical_label == COMMAND_AND_CONTROL
    assert labels[1].attack_family == "Neris"
    assert labels[1].dataset_label == BOTNET_LABEL
    # scenario 2's same-clock bin is its own window, benign
    assert labels[2].canonical_label == BENIGN


def test_slots_feed_the_canonical_sequence_engine(ctu_dir: Path):
    """The whole point of the adapter: its output must drive the ONE
    sequence engine (gap-filled, masked) without any glue code."""
    a = get_adapter("ctu13")
    flows = a.load(a.discover(ctu_dir.parent))
    slots, labels = a.to_window_slots(flows, bin_secs=30)
    seq = make_canonical_sequences(slots, labels, seq_len=1, horizon=1,
                                   bin_secs=30, emit_empty=False)
    assert seq.n_sequences >= 1
    assert seq.X.shape[2] == 48               # canonical width
    for j, name in enumerate(FEATURE_NAMES):
        assert bool(seq.mask[0, 0, j]) == (name in CTU13_AVAILABLE), name


# ------------------------------------------------------------- real files

def test_smoke_on_real_captures():
    """Runs only when the real CTU-13 captures are on disk. Uses the
    smallest scenario so the smoke stays fast."""
    a = get_adapter("ctu13")
    files = a.discover(Path("data/raw"))
    if len(files) < 13:
        pytest.skip(f"real CTU-13 captures not fully extracted yet "
                    f"({len(files)}/13)")
    rep = a.validate(files)
    assert rep.ok, rep.errors
    smallest = min(files, key=lambda p: p.stat().st_size)
    scen = int(smallest.parent.name)
    flows = a.load([smallest])
    assert len(flows) > 10_000                 # a real scenario, not a stub
    slots, labels = a.to_window_slots(flows, bin_secs=30)
    assert len(slots) > 50
    # the real capture must contain botnet windows AND benign windows
    canon = {lr.canonical_label for lr in labels}
    assert COMMAND_AND_CONTROL in canon
    assert BENIGN in canon
    # every window's label scenario matches the file it came from
    assert all(lr.dataset_id == "ctu13" for lr in labels)
