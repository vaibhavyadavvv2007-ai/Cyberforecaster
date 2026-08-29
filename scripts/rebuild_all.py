"""One command to rebuild every artifact in the correct order.

Order matters and the dependencies are invisible: the models need the scaler the
pipeline writes, lead-time needs the trained weights, and the demo cache needs
both. Running these by hand in the wrong order after a change is how you end up
demoing a model that disagrees with its own metrics.

  python scripts/rebuild_all.py              # full rebuild
  python scripts/rebuild_all.py --skip-train # reuse existing weights
  python scripts/rebuild_all.py --epochs 60

Stops at the first failure and tells you what to fix. Safe to re-run.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# cp1252 consoles (Windows, piped output) cannot encode arrows or emoji. Degrade
# instead of raising — a build script must not die on its own progress message.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def step(n: int, total: int, title: str, cmd: list[str]) -> bool:
    print(f"\n{'=' * 72}\n[{n}/{total}] {title}\n  $ {' '.join(cmd)}\n{'=' * 72}", flush=True)
    t0 = time.perf_counter()
    rc = subprocess.call(cmd, cwd=ROOT)
    dt = time.perf_counter() - t0
    if rc != 0:
        print(f"\n[FAILED] after {dt:.0f}s (exit {rc}): {title}")
        return False
    print(f"\n[  OK  ] {title} - {dt:.0f}s")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--skip-train", action="store_true",
                    help="reuse existing weights (still refreshes metrics that don't need training)")
    ap.add_argument("--skip-pipeline", action="store_true",
                    help="reuse processed data (skip if raw CSVs are unchanged)")
    a = ap.parse_args()

    py = sys.executable
    plan: list[tuple[str, list[str]]] = [
        ("Smoke test (synthetic — catches shape/label regressions early)",
         [py, "tests/smoke_synthetic.py"]),
    ]
    if not a.skip_pipeline:
        plan.append(("Pipeline: raw CSV -> windows -> sequences + scaler",
                     [py, "-m", "src.preprocessing.pipeline",
                      "--raw", "data/raw", "--out", "data/processed"]))
    plan.append(("Logistic baseline (PS-required benchmark)",
                 [py, "-m", "src.models.baseline_logreg", "--dir", "data/processed"]))
    if not a.skip_train:
        plan.append(("LSTM forecaster",
                     [py, "-m", "src.models.lstm_forecaster",
                      "--dir", "data/processed", "--epochs", str(a.epochs)]))
    plan += [
        ("Lead-time evaluation (the differentiator slide)",
         [py, "-m", "src.evaluation.lead_time", "--dir", "data/processed"]),
        ("Demo cache (crash-proof fallback — W1)",
         [py, "scripts/build_demo_cache.py"]),
        ("Final state verification",
         [py, "scripts/verify_state.py"]),
    ]

    total = len(plan)
    for i, (title, cmd) in enumerate(plan, start=1):
        if not step(i, total, title, cmd):
            print("\nFix the failure above, then re-run. Nothing downstream ran, so no "
                  "artifact is half-updated.")
            return 1

    print(f"\n{'=' * 72}\n*** ALL {total} STEPS PASSED ***\n{'=' * 72}")
    print("Now: streamlit run app/streamlit_app.py")
    print("The sidebar must badge **REAL MODEL**. If it says CACHED or SIMULATED, read")
    print("the reason it prints — do not rehearse against a fallback by accident.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
