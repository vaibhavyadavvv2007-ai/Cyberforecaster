"""Pre-demo state check — answers "is this project actually ready?" in one run.

Prints, and never raises on missing optional pieces:
  1. environment: which packages are importable (torch/captum/pyarrow/streamlit)
  2. raw CSVs: which columns exist — specifically whether Src IP / Dst IP are
     present (battle plan §5.2 says they are NOT; several features and one MITRE
     rule silently depend on them)
  3. processed data: window/sequence counts, per-horizon-step positive rates
  4. raw feature ranges + zero-variance (dead) features
  5. artifact consistency: scaler ↔ model config ↔ npz feature count
  6. a demo-readiness checklist

Usage (from repo root):
  python scripts/verify_state.py
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252 when output is piped, and cp1252 cannot
# encode arrows or emoji — an UnicodeEncodeError would kill a diagnostic script
# at exactly the moment you need it. Keep the console's encoding, but degrade
# unencodable characters to '?' instead of raising.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass

PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
MODELS = ROOT / "models"

OK, WARN, BAD = "[ ok ]", "[warn]", "[BAD ]"


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def check_env() -> dict:
    section("1. ENVIRONMENT")
    print(f"python: {sys.executable}")
    found = {}
    for mod in ("numpy", "pandas", "sklearn", "pyarrow", "fastparquet", "torch",
               "captum", "streamlit", "yaml", "boto3", "matplotlib"):
        try:
            m = importlib.import_module(mod)
            found[mod] = getattr(m, "__version__", "?")
            print(f"  {OK} {mod:<12} {found[mod]}")
        except ImportError:
            found[mod] = None
            print(f"  {WARN} {mod:<12} MISSING")
    if not found.get("pyarrow") and not found.get("fastparquet"):
        print(f"  {BAD} no parquet engine -> windows.parquet unreadable -> the app cannot start.")
        print("        fix: pip install pyarrow")
    if not found.get("torch"):
        print(f"  {WARN} torch missing -> cannot train or run real inference here.")
    return found


def check_raw_columns() -> None:
    section("2. RAW CSV COLUMNS (does the dataset have IP columns?)")
    files = sorted(RAW.glob("*.csv"))
    if not files:
        print(f"  {WARN} no CSVs in {RAW} — skipping")
        return
    print(f"  {len(files)} file(s) present")
    f = files[0]
    with f.open("r", encoding="utf-8", errors="replace") as fh:
        header = [c.strip() for c in fh.readline().split(",")]
    print(f"  header of {f.name}: {len(header)} columns")
    for col in ("Src IP", "Dst IP", "Src Port", "Timestamp", "Label"):
        mark = OK if col in header else BAD
        print(f"    {mark} {col}")
    if "Src IP" not in header or "Dst IP" not in header:
        print(f"\n  {BAD} CONFIRMED: no IP columns. Consequences in current code:")
        print("        - unique_src_ips / unique_dst_ips are constant 0 (dead inputs)")
        print("        - mitre_mapper lateral-movement rule (east_west>=3) can NEVER fire")
        print("        - the C2 rule's `unique_dst_ips <= 3` clause is ALWAYS true")


def check_processed() -> dict:
    section("3. PROCESSED SEQUENCES")
    info = {}
    if not PROC.exists():
        print(f"  {BAD} {PROC} missing — run: python -m src.preprocessing.pipeline")
        return info
    for name in ("train", "val", "test"):
        p = PROC / f"sequences_{name}.npz"
        if not p.exists():
            print(f"  {BAD} {p.name} missing")
            continue
        d = np.load(p, allow_pickle=False)
        X, y = d["X"], d["y_prog"]
        info[name] = {"n": len(X), "shape": X.shape, "y_shape": y.shape,
                      "has_ends": "ends" in d.files}
        print(f"  {name:<6} X={str(X.shape):20s} y_prog={str(y.shape):12s} "
              f"ends={'yes' if 'ends' in d.files else 'NO'}")
        if y.ndim != 2:
            print(f"    {BAD} y_prog is {y.ndim}-D — expected (n, K) per-step labels. "
                  "Re-run the pipeline.")
        else:
            rates = " ".join(f"t+{k+1}={y[:, k].mean():.3f}" for k in range(y.shape[1]))
            print(f"         per-step positive rate: {rates}")
            print(f"         any-in-horizon: {(y.max(axis=1) > 0).mean():.3f}")
        if "ends" not in d.files:
            print(f"    {BAD} no `ends` in {name} split -> lead-time eval cannot run. Re-run pipeline.")
    total = sum(v["n"] for v in info.values())
    if total and total < 3000:
        print(f"\n  {WARN} only {total} sequences total. A 2-layer LSTM(64) is ~35k params;")
        print("        this is small enough that metrics will be noisy. Consider 30s bins")
        print("        (doubles sequences, still matches beaconing tempo) or one more day-file.")
    return info


def check_meta() -> None:
    """Cross-check meta.txt against the actual sequences (can drift if pipeline
    was re-run with a different --bin-secs without updating the downstream note)."""
    meta_p = PROC / "meta.txt"
    if not meta_p.exists():
        print(f"  {WARN} meta.txt missing — run the pipeline to regenerate it")
        return
    meta = meta_p.read_text(encoding="utf-8")
    # Extract bin_secs=XX from the first line
    import re
    m = re.search(r"bin_secs=(\d+)", meta)
    if m:
        bin_secs = int(m.group(1))
        print(f"  {OK} meta.txt bin_secs={bin_secs}")
    else:
        print(f"  {WARN} meta.txt has no bin_secs field — regenerate with the pipeline")


def check_features() -> None:
    section("4. FEATURE RANGES + DEAD FEATURES")
    p = PROC / "sequences_train.npz"
    if not p.exists():
        print(f"  {WARN} no train npz — skipping")
        return
    d = np.load(p, allow_pickle=False)
    X, names = d["X"], [str(n) for n in d["feature_names"]]
    print(f"  {'feature':<20}{'min':>14}{'max':>16}{'mean':>14}{'std':>14}")
    dead = []
    for i, n in enumerate(names):
        c = X[:, :, i]
        if c.std() < 1e-8:
            dead.append(n)
        print(f"  {n:<20}{c.min():>14.3f}{c.max():>16.1f}{c.mean():>14.2f}{c.std():>14.2f}")
    spread = X.reshape(-1, X.shape[-1]).std(axis=0)
    live = spread > 1e-8
    if live.any():
        ratio = spread[live].max() / spread[live].min()
        print(f"\n  dynamic range across features: {ratio:,.0f}x")
        if ratio > 100:
            print(f"  {WARN} that spread is why an unscaled LSTM saturates. The shared")
            print("        transform (features/scaling.py) exists to fix exactly this.")
    if dead:
        print(f"\n  {BAD} ZERO-VARIANCE (dead) features: {dead}")
    else:
        print(f"\n  {OK} no dead features")


def check_artifacts() -> None:
    section("5. ARTIFACT CONSISTENCY")
    check_meta()
    sc_p, cfg_p = PROC / "scaler.npz", MODELS / "trained_models" / "lstm_config.json"
    n_sc = n_cfg = n_npz = None
    if sc_p.exists():
        n_sc = len(np.load(sc_p, allow_pickle=False)["feature_names"])
        print(f"  {OK} scaler.npz            features={n_sc}")
    else:
        print(f"  {BAD} scaler.npz MISSING — run the pipeline. Training and inference")
        print("        must share one transform or the app silently mispredicts.")
    if (PROC / "sequences_train.npz").exists():
        n_npz = int(np.load(PROC / "sequences_train.npz", allow_pickle=False)["X"].shape[-1])
        print(f"  {OK} sequences_train.npz   features={n_npz}")
    if cfg_p.exists():
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        n_cfg = cfg.get("n_feat")
        print(f"  {OK} lstm_config.json      n_feat={n_cfg} horizon={cfg.get('horizon')} "
              f"threshold={cfg.get('threshold')}")
        if cfg.get("threshold") is None:
            print(f"    {WARN} no threshold in config -> app falls back to 0.5 (arbitrary). Retrain.")
        # --- state-reconstruction head consistency check ---
        if cfg.get("predict_next_state"):
            pt = MODELS / "trained_models" / "lstm_forecaster.pt"
            if pt.exists():
                try:
                    import torch
                    sd = torch.load(pt, map_location="cpu", weights_only=True)
                    has_head = any(k.startswith("state_head") for k in sd)
                    if has_head:
                        print(f"  {OK} state_head weights present in lstm_forecaster.pt")
                    else:
                        print(f"  {BAD} predict_next_state=True in config but NO state_head"
                              " weights in .pt — model needs retraining on Colab")
                except Exception as exc:
                    print(f"  {WARN} could not inspect .pt for state_head: {exc}")
            else:
                print(f"  {WARN} predict_next_state=True but lstm_forecaster.pt missing")
        else:
            print(f"  {OK} predict_next_state={cfg.get('predict_next_state', False)} "
                  f"(state-reconstruction head {'enabled' if cfg.get('predict_next_state') else 'disabled'})")
    else:
        print(f"  {WARN} lstm_config.json missing — LSTM not trained yet")
    counts = {k: v for k, v in {"scaler": n_sc, "npz": n_npz, "config": n_cfg}.items()
              if v is not None}
    if len(set(counts.values())) > 1:
        print(f"  {BAD} FEATURE-COUNT MISMATCH {counts} — the saved model does not match")
        print("        the current data. Re-run pipeline, then retrain. Do not demo this.")
    elif counts:
        print(f"  {OK} feature counts agree ({list(counts.values())[0]})")

    for f, why in ((MODELS / "metrics_baseline.json", "logistic benchmark"),
                   (MODELS / "metrics_lstm.json", "LSTM benchmark (W3)"),
                   (MODELS / "metrics_lead_time.json", "lead-time differentiator"),
                   (MODELS / "trained_models" / "lstm_forecaster.pt", "trained weights")):
        print(f"  {OK if f.exists() else BAD} {f.name:<26} {why}")


def checklist() -> None:
    section("6. DEMO READINESS")
    items = [
        (PROC / "windows.parquet").exists(), "processed windows exist",
        (PROC / "scaler.npz").exists(), "shared transform saved",
        (MODELS / "metrics_baseline.json").exists(), "logistic benchmark numbers",
        (MODELS / "metrics_lstm.json").exists(), "LSTM benchmark numbers (W3)",
        (MODELS / "metrics_lead_time.json").exists(), "lead-time numbers (the slide)",
        (MODELS / "trained_models" / "lstm_forecaster.pt").exists(), "trained weights",
        (PROC / "demo_cache.json").exists(), "cached-predictions fallback (W1)",
    ]
    for i in range(0, len(items), 2):
        print(f"  {OK if items[i] else BAD} {items[i + 1]}")
    print("\nRebuild order after any pipeline change:")
    print("  1. python -m src.preprocessing.pipeline --raw data/raw --out data/processed")
    print("  2. python -m src.models.baseline_logreg --dir data/processed")
    print("  3. python -m src.models.lstm_forecaster --dir data/processed --epochs 40")
    print("  4. python -m src.evaluation.lead_time --dir data/processed")
    print("  5. python scripts/build_demo_cache.py")
    print("  6. streamlit run app/streamlit_app.py")


def main() -> None:
    check_env()
    check_raw_columns()
    check_processed()
    check_features()
    check_artifacts()
    checklist()
    print()


if __name__ == "__main__":
    main()
