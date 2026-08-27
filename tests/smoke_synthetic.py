"""End-to-end smoke test on SYNTHETIC flows — no dataset download needed.

Verifies the whole Tier-1 spine at runtime:
  load-style cleaning → build_windows → make_sequences → chrono_split →
  rule validation → logistic metrics helper → attribution fallback.

Run from repo root:
  python tests/smoke_synthetic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.attack_mapping.mitre_mapper import STAGES, validate_rules
from src.features.window_builder import (HORIZON, SEQ_LEN, WINDOW_FEATURES,
                                         build_windows, chrono_split, make_sequences)
from src.ingestion.csv_loader import load_day_csv
from src.models.baseline_logreg import evaluate

rng = np.random.default_rng(42)


def synthetic_flows(n_benign=6000, n_attack_bins=40, flows_per_attack_bin=60):
    """Two days of benign traffic + injected scan/brute-force bursts."""
    rows = []
    day0 = pd.Timestamp("2026-01-05 08:00:00")

    def add(ts, label, dport, syn, n=1, srcs=("10.0.0.5",), dsts=("10.0.1.10",)):
        for _ in range(n):
            rows.append({
                "Timestamp": ts + pd.Timedelta(seconds=float(rng.integers(0, 55))),
                "Label": label, "Dst Port": int(dport),
                "Protocol": 6, "Flow Duration": float(rng.integers(1_000, 90_000_000)),
                "Tot Fwd Pkts": float(rng.integers(2, 200)),
                "Tot Bwd Pkts": float(rng.integers(2, 400)),
                "TotLen Fwd Pkts": float(rng.integers(100, 500_000)),
                "TotLen Bwd Pkts": float(rng.integers(100, 900_000)),
                "Flow IAT Mean": float(rng.uniform(100, 50_000_000)),
                "Flow IAT Std": float("inf") if rng.random() < 0.001 else float(rng.uniform(0, 9e6)),
                "Avg Pkt Size": float(rng.uniform(40, 1500)),
                "Down/Up Ratio": float(rng.uniform(0, 2)),
                "SYN Flag Cnt": float(syn), "ACK Flag Cnt": float(1 - syn * 0.7),
                "FIN Flag Cnt": float(rng.random() < 0.5), "RST Flag Cnt": 0.0,
                "PSH Flag Cnt": float(rng.random() < 0.3),
                "Src IP": str(rng.choice(srcs)), "Src Port": int(rng.integers(1024, 65535)),
                "Dst IP": str(rng.choice(dsts)),
            })

    for i in range(n_benign):  # background web/dns chatter across the full span
        ts = day0 + pd.Timedelta(seconds=float(rng.integers(0, 165_000)))
        add(ts, "Benign", rng.choice([443, 80, 53]), syn=rng.random() < 0.3)

    base = day0
    good_bins = set()
    while len(good_bins) < n_attack_bins:
        # two clusters so positives appear in BOTH halves of the chronological
        # timeline — otherwise the test tail is all-benign (a real pitfall)
        half = rng.random() < 0.7
        lo, hi = (7_200, 80_000) if half else (90_000, 162_000)
        good_bins.add((int(rng.integers(lo, hi)), half))
    for j, b in enumerate(sorted(good_bins)):
        ts = base + pd.Timedelta(seconds=b[0])
        if j % 2 == 0:  # port-scan burst → Reconnaissance signature
            ports = rng.choice(range(1, 1024), size=flows_per_attack_bin)
            for p in ports:
                add(ts, "SSH-Brute-Force", p, syn=1.0, dsts=("10.0.1.10",))
        else:           # credential burst at auth port → Initial Access signature
            add(ts, "FTP-Brute Force", 21, syn=1.0, n=flows_per_attack_bin,
                srcs=("203.0.113.66",))
    return pd.DataFrame(rows)


def main() -> None:
    raw = synthetic_flows()
    tmp = Path("data/tmp_smoke")
    tmp.mkdir(parents=True, exist_ok=True)
    raw_path = tmp / "synthetic.csv"
    raw.to_csv(raw_path, index=False)

    flows = load_day_csv(raw_path)
    assert len(flows) > 0 and {"Timestamp", "Label"} <= set(flows.columns)

    windows = build_windows(flows)
    assert list(WINDOW_FEATURES)[0] in windows.columns
    assert windows["attack_frac"].between(0, 1).all()
    assert windows["dominant_stage_idx"].between(-1, len(STAGES) - 1).all()
    assert (windows["flow_count"] > 0).all()

    validate_rules(windows)

    X, y_prog, y_stage, ends = make_sequences(windows)
    assert X.shape[0] == len(y_prog) == len(y_stage) == len(ends)
    assert X.shape[1:] == (SEQ_LEN, len(WINDOW_FEATURES))
    assert set(np.unique(y_prog)) <= {0.0, 1.0}
    tr, va, te = chrono_split(windows, ends)
    assert tr and te, f"splits empty: {len(tr)}/{len(va)}/{len(te)}"
    # chronological invariant: every train sequence ends before any test sequence begins
    assert max(ends[i] for i in tr) < min(ends[i] for i in te)
    print(f"windows={len(windows)} seqs={len(X)} splits tr/va/te="
          f"{len(tr)}/{len(va)}/{len(te)} pos_rate(train)={y_prog[tr].mean():.2f}")

    m = evaluate(y_prog[te].astype(int),
                 np.clip(y_prog[te] + rng.normal(0, 0.2, len(te)), 0, 1))
    assert 0.0 <= m["fpr"] <= 1.0 and 0.0 <= m["f1"] <= 1.0
    print("metrics helper:", {k: round(v, 3) for k, v in m.items()})

    try:
        import warnings
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from src.explainability.attribution import permutation_fallback
        Xtr = StandardScaler().fit_transform(X[tr].reshape(len(tr), -1))
        clf = LogisticRegression(max_iter=300).fit(Xtr, y_prog[tr].astype(int))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # degenerate-subset AP warnings are expected here
            imp = permutation_fallback(lambda Z: clf.predict_proba(Z)[:, 1],
                                       X[te].reshape(len(te), -1), y_prog[te])
        assert len(imp) == SEQ_LEN * len(WINDOW_FEATURES)
        print("attribution fallback OK (importances computed)")
    except ImportError as exc:
        print(f"[sklearn missing — attribution fallback skipped: {exc}]")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("\nSMOKE TEST PASSED ✔")


if __name__ == "__main__":
    main()
