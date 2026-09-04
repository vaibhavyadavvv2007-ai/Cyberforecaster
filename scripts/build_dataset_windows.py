"""Build dataset windows parquet files in the SAME schema as the frozen
data/processed/windows.parquet (18 WINDOW_FEATURES + attack_frac +
dominant_stage_idx + frac_<stage>), plus a `split` column for leak-proof
multi-dataset training.

  python scripts/build_dataset_windows.py --dataset unsw_nb15
  python scripts/build_dataset_windows.py --dataset ctu13

Outputs:
  data/processed/windows_unsw_nb15.parquet
  data/processed/windows_ctu13.parquet

Why a `split` column (the frozen CIC2018 parquet has none): multi-dataset
training needs per-dataset chronological 70/15/10 splits — CTU-13's are
PER-SCENARIO (scenarios share calendar dates, so wall-clock ordering would
merge captures taken on different days). Sequences are formed at training
time only WITHIN contiguous (scenario, split) runs, so no sequence can span
a boundary — a stronger guarantee than the V1 boundary purge.

Honesty rules (DATA_CONTRACT):
  - features unavailable from a source are NaN, never zero
  - attack_frac is the flow-level attack fraction (mean of the per-flow
    indicator), NOT the dominant-label binarisation
  - dominant_stage_idx = dominant canonical stage among ATTACK flows;
    -1 when the bin has no attack flows
  - failed/partial builds raise; nothing half-written is kept
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.attack_mapping.mitre_mapper import STAGES
from src.config import BIN_SECS
from src.datasets.ctu13 import CTU13Adapter
from src.datasets.registry import get_adapter
from src.datasets.unsw_nb15 import BENIGN_SENTINELS
from src.features.canonical_schema import DATASET_CAPABILITIES
from src.features.window_builder import WINDOW_FEATURES
from src.labels.attack_taxonomy import (CANONICAL_TO_LEGACY, canonicalize,
                                        canonicalize_ctu13)

ROOT = Path(__file__).resolve().parents[1]
FRAC_COLS = [f"frac_{st}" for st in STAGES]


def _flow_is_attack(dataset_id: str, labels: pd.Series) -> np.ndarray:
    """Per-flow attack indicator, dataset-specific and verified from source."""
    lab = labels.fillna("").astype(str).str.strip()
    if dataset_id == "ctu13":
        return lab.str.contains("Botnet", na=False).to_numpy(dtype=float)
    if dataset_id == "unsw_nb15":
        return (~lab.isin(BENIGN_SENTINELS)).to_numpy(dtype=float)
    raise ValueError(f"no attack rule for {dataset_id}")


def _stage_of_flow(dataset_id: str, labels: pd.Series,
                   scenario: int | None = None) -> np.ndarray:
    """Legacy 6-stage index per flow (STAGES index; -1 = benign or no legacy
    stage), via the ONE taxonomy — canonicalize, then canonical → legacy
    display name. EXECUTION / UNKNOWN_ATTACK have no legacy slot → -1."""
    lab = labels.fillna("").astype(str).str.strip()
    uniq = {v: i for i, v in enumerate(lab.unique())}
    idx = np.array([uniq[v] for v in lab], dtype=int)
    canon = np.full(len(uniq), -1, dtype=int)
    for u, i in uniq.items():
        if dataset_id == "ctu13":
            rec = canonicalize_ctu13(u, scenario)
        elif dataset_id == "unsw_nb15":
            if u in BENIGN_SENTINELS:
                continue                     # benign — stays -1
            rec = canonicalize(dataset_id, u)
        else:
            raise ValueError(dataset_id)
        legacy = CANONICAL_TO_LEGACY.get(rec.canonical_label, "")
        if legacy in STAGES:
            canon[i] = STAGES.index(legacy)
    return canon[idx]


def _build_windows(dataset_id: str, flows: pd.DataFrame,
                   bin_secs: int) -> pd.DataFrame:
    """Canonical flows → windows in the frozen windows.parquet schema.

    Aggregation delegates to the adapter's to_window_slots (the ONE audited
    implementation); attack_frac / stage fractions are computed here from the
    SAME grouped rows, positionally aligned (both use pandas groupby sort
    order on identical keys — asserted below).
    """
    adapter = get_adapter(dataset_id)
    available = DATASET_CAPABILITIES.get(dataset_id, set())

    slots, _slot_labels = adapter.to_window_slots(flows, bin_secs=bin_secs)

    df = flows.copy()
    df = df[df["ts"].notna()]
    df["bin"] = df["ts"].dt.floor(f"{bin_secs}s")
    if dataset_id == "ctu13":
        df = df.sort_values(["scenario", "ts"], kind="mergesort")
        keys = ["scenario", "bin"]
    else:
        df = df.sort_values("ts", kind="mergesort")
        keys = ["bin"]
    groups = list(df.groupby(keys, sort=True))
    assert len(groups) == len(slots), \
        f"group/slot misalignment: {len(groups)} vs {len(slots)}"

    rows = []
    for (key, g), ws in zip(groups, slots):
        scen = int(key[0]) if dataset_id == "ctu13" else -1
        is_atk = _flow_is_attack(dataset_id, g["dataset_label"])
        stage = _stage_of_flow(dataset_id, g["dataset_label"],
                               scenario=scen if scen > 0 else None)

        row = {"bin": key[-1]}
        if dataset_id == "ctu13":
            row["scenario"] = scen
        for feat in WINDOW_FEATURES:
            slot = ws.get(feat)
            if slot is not None and slot.available and feat in available:
                row[feat] = float(slot.value)
            else:
                row[feat] = np.nan     # honestly unavailable — never zero

        n_atk = float(is_atk.sum())
        row["attack_frac"] = float(is_atk.mean()) if len(g) else 0.0
        # stage fractions among MAPPED attack flows (V1 build_windows
        # semantics: unmapped attack families contribute no stage, benign
        # bins get -1)
        atk_stages = stage[(is_atk > 0) & (stage >= 0)]
        if len(atk_stages):
            counts = np.bincount(atk_stages,
                                 minlength=len(STAGES)).astype(float)
            fracs = counts / counts.sum()
            dom = int(fracs.argmax())
        else:
            fracs = np.zeros(len(STAGES))
            dom = -1
        row["dominant_stage_idx"] = dom
        for st, f in zip(STAGES, fracs):
            row[f"frac_{st}"] = float(f)
        rows.append(row)

    return pd.DataFrame(rows).set_index("bin").sort_index()


def _assign_splits(windows: pd.DataFrame, per_scenario: bool
                   ) -> pd.DataFrame:
    """Chronological 70/15/10 with a `split` column. Sequences formed later
    only within contiguous same-split runs, so boundaries are automatically
    purged (no sequence can span two splits)."""
    out = windows.copy()
    if per_scenario:
        parts = []
        for scen, g in out.groupby("scenario", sort=True):
            g = g.sort_index()
            n = len(g)
            n_tr, n_va = int(n * 0.70), int(n * 0.15)
            g = g.assign(split=[
                "train"] * n_tr + ["val"] * n_va
                + ["test"] * (n - n_tr - n_va))
            parts.append(g)
        out = pd.concat(parts)
    else:
        out = out.sort_index()
        n = len(out)
        n_tr, n_va = int(n * 0.70), int(n * 0.15)
        out = out.assign(split=[
            "train"] * n_tr + ["val"] * n_va + ["test"] * (n - n_tr - n_va))
    return out


def build(dataset_id: str, raw_root: Path = ROOT / "data/raw",
          out_dir: Path = ROOT / "data/processed",
          bin_secs: int = BIN_SECS, max_scenarios: int | None = None
          ) -> Path:
    t0 = time.perf_counter()
    adapter = get_adapter(dataset_id)
    files = adapter.discover(raw_root)
    if not files:
        raise SystemExit(f"no files for {dataset_id} under {raw_root}")
    rep = adapter.validate(files)
    partial_requested = max_scenarios is not None and dataset_id == "ctu13"
    if not rep.ok:
        # an explicitly requested partial build may proceed ONLY when the
        # sole validation failure is the scenario count (structure is sound,
        # the download is just incomplete) — recorded as partial_build: true
        structural = [e for e in rep.errors
                      if not e.startswith("scenarios:")]
        if partial_requested and not structural:
            print(f"WARNING: PARTIAL BUILD — {rep.errors} "
                  f"(proceeding: structure valid, download incomplete)",
                  flush=True)
        else:
            raise SystemExit(f"{dataset_id} validation failed: {rep.errors}")

    if dataset_id == "ctu13":
        # >15M flows total — one scenario at a time, per the adapter contract.
        # max_scenarios caps the build (time budget) — honestly recorded in
        # the summary; never silently dropped.
        if max_scenarios is not None:
            files = files[:max_scenarios]
        parts = []
        for f in files:
            t1 = time.perf_counter()
            flows = adapter.load([f])
            w = _build_windows(dataset_id, flows, bin_secs)
            print(f"  S{f.parent.name}: {len(flows):,} flows -> {len(w)} "
                  f"windows ({time.perf_counter() - t1:.0f}s)", flush=True)
            parts.append(w)
            del flows
        windows = pd.concat(parts)
        per_scenario = True
    else:
        flows = adapter.load(files)
        print(f"  loaded {len(flows):,} flows", flush=True)
        windows = _build_windows(dataset_id, flows, bin_secs)
        per_scenario = False

    windows = _assign_splits(windows, per_scenario)

    # summary — printed AND written next to the parquet
    atk = windows["attack_frac"]
    n_attack_windows = int((atk > 0).sum())
    n_scenarios = (int(windows["scenario"].nunique())
                   if "scenario" in windows.columns else None)
    summary = {
        "dataset_id": dataset_id,
        "n_windows": int(len(windows)),
        "n_attack_windows": n_attack_windows,
        "attack_window_rate": round(float((atk > 0).mean()), 4),
        "mean_attack_frac": round(float(atk.mean()), 4),
        "n_scenarios": n_scenarios,
        "scenarios_included": (sorted(windows["scenario"].unique().tolist())
                               if "scenario" in windows.columns else None),
        "partial_build": bool(max_scenarios is not None
                              and dataset_id == "ctu13"
                              and n_scenarios is not None and n_scenarios < 13),
        "splits": windows["split"].value_counts().to_dict(),
        "available_features": sorted(
            f for f in WINDOW_FEATURES
            if f in DATASET_CAPABILITIES[dataset_id]),
        "unavailable_features": sorted(
            f for f in WINDOW_FEATURES
            if f not in DATASET_CAPABILITIES[dataset_id]),
        "stage_counts": {STAGES[i]: int(
            (windows["dominant_stage_idx"] == i).sum())
            for i in range(len(STAGES))},
        "bin_secs": bin_secs,
        "built_s": round(time.perf_counter() - t0, 1),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"windows_{dataset_id}.parquet"
    windows.to_parquet(out_path)
    (out_dir / f"windows_{dataset_id}.summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out_path}")
    return out_path


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True,
                    choices=["unsw_nb15", "ctu13"])
    ap.add_argument("--max-scenarios", type=int, default=None,
                    help="ctu13 only: cap scenarios built (partial download / "
                         "time budget). Proceeds only if the sole validation "
                         "failure is scenario count; recorded partial_build")
    a = ap.parse_args()
    build(a.dataset, max_scenarios=a.max_scenarios)
