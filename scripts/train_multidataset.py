"""Multi-dataset + cross-dataset experiments (MASTER_IMPLEMENTATION_PLAN
phases 7–8).

  python scripts/train_multidataset.py --experiment D   # pooled 3-dataset model
  python scripts/train_multidataset.py --experiment LODO
  python scripts/train_multidataset.py --experiment single

Feature space: the HONEST 3-way intersection of the legacy 18 window
features across CIC2018 / UNSW-NB15 / CTU-13 = 9 features (the plan's
draft said 11, but CIC2018's ML-ready CSVs ship no IP columns, so
unique_src_ips / unique_dst_ips cannot enter a shared model — see
src/features/canonical_schema.py DATASET_CAPABILITIES).

Protocols (identical to frozen V1 wherever possible):
  - TemporalForecaster architecture (LSTM n_feat->64, 2 layers, prog head K=5,
    stage head 6 stages) — src/models/lstm_forecaster.py
  - pos-weighted BCE per horizon step + stage CE (ignore_index=-1)
  - early stopping on pooled val PR-AUC (patience from --patience)
  - threshold picked on VAL only (features.scaling + baseline_logreg tools)
  - scaler (log1p + standardise) fitted on the COMBINED train split only

Splits are leak-proof by construction: sequences form only within contiguous
same-(dataset, scenario, split) runs of windows, so no sequence can span a
split or scenario boundary (stronger than the V1 day-boundary purge).

Artifacts:
  models/multidataset_v1/          weights.pt, config.json, metrics.json
  models/cross/lodo_<held_out>/    leave-one-dataset-out runs
  models/cross/single_<dataset>/   in-domain 9-feature baselines
  models/metrics_cross_dataset.json  everything, one machine-readable file
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyTorch missing — see src/models/lstm_forecaster.py") from exc

from sklearn.metrics import average_precision_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import HORIZON, SEQ_LEN
from src.features.scaling import apply_scaler, fit_scaler, save_scaler
from src.features.window_builder import (WINDOW_FEATURES, horizon_any,
                                         make_sequences)
from src.models.baseline_logreg import evaluate, pick_threshold
from src.models.lstm_forecaster import TemporalForecaster

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data/processed"
STAGES = ["Reconnaissance", "Initial Access", "Lateral Movement",
          "Command & Control", "Exfiltration", "DoS"]

# The honest 3-way intersection — verified via DATASET_CAPABILITIES
INTERSECTION = [
    "flow_count", "bytes_total", "pkts_total", "duration_mean",
    "avg_pkt_size", "unique_dst_ports", "dst_port_entropy",
    "down_up_ratio", "auth_port_share",
]
assert set(INTERSECTION) <= set(WINDOW_FEATURES)


# --------------------------------------------------------------- sequences

def _sequences_from_parquet(windows: pd.DataFrame,
                            features: list[str]) -> dict[str, tuple]:
    """Split-labelled windows -> per-split sequences, formed ONLY within
    contiguous same-(scenario, split) runs (leak-proof by construction:
    no sequence can span a split or scenario boundary)."""
    feats = windows[features].to_numpy(dtype=np.float32)
    atk = windows["attack_frac"].to_numpy(dtype=np.float32)
    stage = windows["dominant_stage_idx"].to_numpy(dtype=np.int64)
    spl = windows["split"].to_numpy()
    scen = (windows["scenario"].to_numpy()
            if "scenario" in windows.columns
            else np.zeros(len(windows)))

    # run id: increments wherever (scenario, split) changes between
    # CONSECUTIVE rows — a re-appearing key later in time is a new run
    run_id = np.zeros(len(windows), dtype=int)
    for i in range(1, len(windows)):
        run_id[i] = run_id[i - 1] + (
            (scen[i], spl[i]) != (scen[i - 1], spl[i - 1]))

    out: dict[str, tuple] = {}
    for split in ("train", "val", "test"):
        xs, ys, st = [], [], []
        for rid in np.unique(run_id):
            idx = np.flatnonzero(run_id == rid)
            if spl[idx[0]] != split:
                continue
            for i in range(len(idx) - SEQ_LEN - HORIZON + 1):
                p = idx[i:i + SEQ_LEN + HORIZON]
                xs.append(feats[p[:SEQ_LEN]])
                hz = atk[p[SEQ_LEN:]]
                ys.append((hz > 0).astype(np.float32))
                hz_st = stage[p[SEQ_LEN:]]
                valid = [s for s in hz_st if s >= 0]
                st.append(int(np.bincount(valid, minlength=6).argmax())
                          if valid else -1)
        if xs:
            out[split] = (np.stack(xs), np.stack(ys),
                          np.array(st, dtype=np.int64))
        else:
            out[split] = (np.zeros((0, SEQ_LEN, len(features)), np.float32),
                          np.zeros((0, HORIZON), np.float32),
                          np.zeros((0,), np.int64))
    return out


def load_dataset(dataset_id: str,
                 features: list[str] = INTERSECTION) -> dict[str, tuple]:
    """dataset_id -> {split: (X, y_prog, y_stage)} on the shared features."""
    if dataset_id == "cic2018":
        out = {}
        for split in ("train", "val", "test"):
            d = np.load(PROC / f"sequences_{split}.npz", allow_pickle=False)
            names = [str(n) for n in d["feature_names"]]
            cols = [names.index(f) for f in features]
            out[split] = (d["X"][:, :, cols].astype(np.float32),
                          d["y_prog"].astype(np.float32),
                          d["y_stage"].astype(np.int64))
        return out
    p = PROC / f"windows_{dataset_id}.parquet"
    if not p.exists():
        raise SystemExit(
            f"{p} missing — run scripts/build_dataset_windows.py "
            f"--dataset {dataset_id} first")
    return _sequences_from_parquet(pd.read_parquet(p), features)


# ----------------------------------------------------------------- training

def _to_tensors(seq: dict[str, tuple], sc: dict) -> dict[str, tuple]:
    out = {}
    for k, (X, y, s) in seq.items():
        Xt = torch.from_numpy(apply_scaler(X, sc)).float()
        out[k] = (Xt, torch.from_numpy(y).float(), torch.from_numpy(s).long())
    return out


def _predict(model, X: torch.Tensor, dev: str, batch: int = 1024) -> np.ndarray:
    model.eval()
    chunks = []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            chunks.append(torch.sigmoid(
                model(X[i:i + batch].to(dev))[0]).cpu().numpy())
    return np.concatenate(chunks) if chunks else np.zeros((0, model.horizon))


def train_model(train_sets: list[dict[str, tuple]], val_sets: list[dict],
                features: list[str], epochs: int, patience: int,
                batch: int = 256, lr: float = 1e-3, dev: str = "cpu",
                tag: str = "", max_train: int | None = None
                ) -> tuple:
    """V1 protocol, pooled across datasets. Returns (model, scaler, thr, best_ap).

    max_train: optional cap on pooled TRAIN sequences (random subsample,
    seed fixed) — a time-budget knob for the demo deadline; val/test are
    NEVER subsampled."""
    Xtr = np.concatenate([s["train"][0] for s in train_sets])
    ytr = np.concatenate([s["train"][1] for s in train_sets])
    str_ = np.concatenate([s["train"][2] for s in train_sets])
    if max_train is not None and len(Xtr) > max_train:
        n_full = len(Xtr)
        rng = np.random.default_rng(0)
        pick = rng.choice(len(Xtr), size=max_train, replace=False)
        Xtr, ytr, str_ = Xtr[pick], ytr[pick], str_[pick]
        print(f"[{tag}] train subsampled {len(pick)}/{n_full}", flush=True)
    Xva = np.concatenate([s["val"][0] for s in val_sets])
    yva = np.concatenate([s["val"][1] for s in val_sets])
    sva = np.concatenate([s["val"][2] for s in val_sets])
    n_feat, K = Xtr.shape[-1], ytr.shape[1]
    print(f"[{tag}] train={len(Xtr)} val={len(Xva)} | F={n_feat} K={K}",
          flush=True)

    sc = fit_scaler(Xtr, features)                       # combined train only
    T = _to_tensors({"train": (Xtr, ytr, str_), "val": (Xva, yva, sva)}, sc)
    Xtr_t, ytr_t, str_t = T["train"]
    Xva_t, yva_t, sva_t = T["val"]
    tr_dl = DataLoader(TensorDataset(Xtr_t, ytr_t, str_t), batch_size=batch,
                       shuffle=True)

    n_pos = ytr_t.sum(dim=0)
    pos_weight = ((len(ytr_t) - n_pos) / n_pos.clamp(min=1)).to(dev)
    model = TemporalForecaster(n_feat, horizon=K).to(dev)
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    ce = nn.CrossEntropyLoss(ignore_index=-1)
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    best_ap, best_state, bad = -1.0, None, 0
    for epoch in range(1, epochs + 1):
        model.train()
        for xb, yb, sb in tr_dl:
            xb, yb, sb = xb.to(dev), yb.to(dev), sb.to(dev)
            opt.zero_grad()
            prog, stg = model(xb)
            (bce(prog, yb) + ce(stg, sb)).backward()
            opt.step()
        p_va = _predict(model, Xva_t, dev)
        ap = float(average_precision_score(horizon_any(yva_t.numpy()),
                                           p_va.max(axis=1)))
        print(f"[{tag}] epoch {epoch:02d}  val AP(pooled)={ap:.4f}",
              flush=True)
        if ap > best_ap:
            best_ap, bad = ap, 0
            best_state = {k: v.detach().cpu().clone()
                          for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                print(f"[{tag}] early stop at epoch {epoch}", flush=True)
                break
    model.load_state_dict(best_state)
    thr = pick_threshold(horizon_any(yva_t.numpy()),
                         _predict(model, Xva_t, dev).max(axis=1))
    return model, sc, thr, best_ap


def eval_on(model, seq: dict[str, tuple], sc: dict, thr: float, dev: str
            ) -> dict | None:
    """Metrics for one dataset's TEST split. None if the split is unusable."""
    X, y, _ = seq["test"]
    if len(X) == 0 or horizon_any(y).sum() == 0:
        return None
    Xt = torch.from_numpy(apply_scaler(X, sc)).float()
    p = _predict(model, Xt, dev)
    agg = evaluate(horizon_any(y), p.max(axis=1), thr)
    agg["_n_test_windows"] = int(len(X))
    agg["_n_attack_windows"] = int(horizon_any(y).sum())
    agg["threshold"] = float(thr)
    return agg


# ------------------------------------------------------------------- main

def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", required=True,
                    choices=["D", "LODO", "single"])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--patience", type=int, default=25)
    ap.add_argument("--quick", action="store_true",
                    help="time-boxed run: 12 epochs, patience 6")
    ap.add_argument("--datasets", type=str,
                    default="cic2018,unsw_nb15,ctu13",
                    help="comma-separated subset (e.g. cic2018,unsw_nb15) — "
                         "partial-CTU-13 fallback / smoke runs")
    ap.add_argument("--max-train", type=int, default=None,
                    help="cap on pooled train sequences (time budget); "
                         "val/test are never subsampled")
    ap.add_argument("--out-dir", type=Path,
                    default=Path("models/multidataset_v1"),
                    help="output dir for weights/scaler/config/metrics")
    ap.add_argument("--model-name", type=str, default="multidataset_v1",
                    help="label for this run in metrics_multidataset.json / "
                         "metrics_cross_dataset.json (history is kept, "
                         "never overwritten)")
    a = ap.parse_args()
    epochs = 12 if a.quick else a.epochs
    patience = 6 if a.quick else a.patience
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={dev} epochs={epochs} patience={patience}")

    datasets = [d.strip() for d in a.datasets.split(",") if d.strip()]
    seqs: dict[str, dict] = {}
    for did in datasets:
        t0 = time.perf_counter()
        seqs[did] = load_dataset(did)
        n = {k: len(v[0]) for k, v in seqs[did].items()}
        pos = {k: round(float(horizon_any(v[1]).mean()), 3)
               for k, v in seqs[did].items() if len(v[0])}
        print(f"{did}: seqs={n} any-in-horizon rate={pos} "
              f"({time.perf_counter() - t0:.0f}s)", flush=True)

    results: list[dict] = []

    if a.experiment == "D":
        model, sc, thr, ap_val = train_model(
            list(seqs.values()), list(seqs.values()), INTERSECTION,
            epochs, patience, dev=dev, tag="D", max_train=a.max_train)
        out_dir = ROOT / a.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), out_dir / "weights.pt")
        save_scaler(sc, out_dir / "scaler.npz")
        # per-dataset test + pooled
        pooled_X = np.concatenate([seqs[d]["test"][0] for d in datasets])
        pooled_y = np.concatenate([seqs[d]["test"][1] for d in datasets])
        pooled = {"test": (pooled_X, pooled_y, np.zeros(len(pooled_X), np.int64))}
        m_pool = eval_on(model, pooled, sc, thr, dev)
        per = {}
        for d in datasets:
            m = eval_on(model, seqs[d], sc, thr, dev)
            if m is None:
                print(f"  [D] {d}: test split has no positives — recorded "
                      "as unavailable")
                per[d] = {"error": "no positive test windows"}
            else:
                per[d] = m
                print(f"  [D] {d}: PR-AUC={m.get('pr_auc')} P={m.get('precision')} "
                      f"R={m.get('recall')} FPR={m.get('fpr')}")
        (out_dir / "config.json").write_text(json.dumps({
            "features": INTERSECTION, "n_feat": len(INTERSECTION),
            "horizon": HORIZON, "seq_len": SEQ_LEN, "hidden": 64, "layers": 2,
            "val_ap_pooled": ap_val, "threshold": thr,
            "epochs_run": epochs, "patience": patience,
            "trained_on": datasets}, indent=2), encoding="utf-8")
        payload = {
            "experiment": "D_pooled",
            "model": a.model_name,
            "trained_on": datasets,
            "features": INTERSECTION,
            "feature_note": ("honest 3-way intersection of the legacy 18; "
                             "the plan's draft 11 included unique_src/dst_ips "
                             "which CIC2018's ML-ready CSVs do not provide"),
            "epochs_run": epochs, "patience": patience,
            "train_subsampled": a.max_train is not None,
            "train_cap": a.max_train,
            "per_dataset_test": per,
            "pooled_test": m_pool,
            "val_ap_pooled": ap_val,
            "skipped": ["leave_one_dataset_out", "single_dataset_baselines"],
            "skip_reason": "time budget — internal demo 2026-09-05",
        }
        # partial-CTU-13 build provenance from the windows summary — the
        # ONE source of truth (never re-derived here)
        ctu_summary = PROC / "windows_ctu13.summary.json"
        if "ctu13" in datasets and ctu_summary.exists():
            s = json.loads(ctu_summary.read_text(encoding="utf-8"))
            used = s.get("scenarios_included") or []
            payload["ctu13_partial"] = bool(s.get("partial_build"))
            payload["ctu13_scenarios_used"] = used
            payload["ctu13_pending"] = [i for i in range(1, 14)
                                        if i not in used]
            payload["ctu13_windows"] = s.get("n_windows")
        (out_dir / "metrics.json").write_text(json.dumps(
            payload, indent=2), encoding="utf-8")
        # APPEND under this run's name — earlier runs are history, never lost
        mm_path = ROOT / "models/metrics_multidataset.json"
        mm = json.loads(mm_path.read_text(encoding="utf-8")) \
            if mm_path.exists() else {}
        mm[a.model_name] = payload
        mm_path.write_text(json.dumps(mm, indent=2), encoding="utf-8")
        for d in datasets:
            results.append({
                "experiment": "D_zero_shot", "model": a.model_name,
                "trained_on": "+".join(datasets),
                "tested_on": d,
                **({k: v for k, v in per[d].items() if not k.startswith("_")}
                   if "error" not in per[d] else {"error": per[d]["error"]}),
                "n_test_windows": per[d].get("_n_test_windows"),
                "n_attack_windows": per[d].get("_n_attack_windows"),
                "threshold": thr})
        results.append({
            "experiment": "D_pooled", "model": a.model_name,
            "trained_on": "+".join(datasets),
            "tested_on": "pooled",
            **{k: v for k, v in m_pool.items() if not k.startswith("_")},
            "n_test_windows": m_pool["_n_test_windows"],
            "n_attack_windows": m_pool["_n_attack_windows"],
            "threshold": thr})

    elif a.experiment == "LODO":
        for held in datasets:
            others = [d for d in datasets if d != held]
            model, sc, thr, ap_val = train_model(
                [seqs[d] for d in others], [seqs[d] for d in others],
                INTERSECTION, epochs, patience, dev=dev, tag=f"LODO-{held}")
            out_dir = ROOT / "models/cross" / f"lodo_{held}"
            out_dir.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), out_dir / "weights.pt")
            save_scaler(sc, out_dir / "scaler.npz")
            m = eval_on(model, seqs[held], sc, thr, dev)
            if m is None:
                print(f"  [LODO] {held}: no positive test windows")
                results.append({"experiment": "LODO",
                                "trained_on": "+".join(others),
                                "tested_on": held,
                                "error": "no positive test windows"})
                continue
            print(f"  [LODO] hold out {held}: PR-AUC={m.get('pr_auc')} "
                  f"P={m.get('precision')} R={m.get('recall')} "
                  f"FPR={m.get('fpr')}")
            (out_dir / "metrics.json").write_text(json.dumps(
                {"experiment": "LODO", "trained_on": "+".join(others),
                 "tested_on": held, **m}, indent=2), encoding="utf-8")
            results.append({
                "experiment": "LODO", "trained_on": "+".join(others),
                "tested_on": held,
                **{k: v for k, v in m.items() if not k.startswith("_")},
                "n_test_windows": m["_n_test_windows"],
                "n_attack_windows": m["_n_attack_windows"],
                "threshold": thr})

    elif a.experiment == "single":
        for d in datasets:
            model, sc, thr, ap_val = train_model(
                [seqs[d]], [seqs[d]], INTERSECTION, epochs, patience,
                dev=dev, tag=f"single-{d}")
            out_dir = ROOT / "models/cross" / f"single_{d}"
            out_dir.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), out_dir / "weights.pt")
            save_scaler(sc, out_dir / "scaler.npz")
            m = eval_on(model, seqs[d], sc, thr, dev)
            if m is None:
                results.append({"experiment": "single", "trained_on": d,
                                "tested_on": d,
                                "error": "no positive test windows"})
                continue
            print(f"  [single] {d}: PR-AUC={m.get('pr_auc')} "
                  f"P={m.get('precision')} R={m.get('recall')} "
                  f"FPR={m.get('fpr')}")
            (out_dir / "metrics.json").write_text(json.dumps(
                {"experiment": "single", "trained_on": d, "tested_on": d,
                 **m}, indent=2), encoding="utf-8")
            results.append({
                "experiment": "single", "trained_on": d, "tested_on": d,
                **{k: v for k, v in m.items() if not k.startswith("_")},
                "n_test_windows": m["_n_test_windows"],
                "n_attack_windows": m["_n_attack_windows"],
                "threshold": thr})

    # append to the machine-readable cross-dataset registry
    reg_path = ROOT / "models/metrics_cross_dataset.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8")) \
        if reg_path.exists() else {"runs": []}
    reg["runs"].extend(results)
    reg["features"] = INTERSECTION
    reg["feature_note"] = ("honest 3-way intersection of the legacy 18; the "
                           "plan's draft 11 included unique_src/dst_ips which "
                           "CIC2018's ML-ready CSVs do not provide")
    reg_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    print(f"\nwrote {len(results)} result rows -> {reg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
