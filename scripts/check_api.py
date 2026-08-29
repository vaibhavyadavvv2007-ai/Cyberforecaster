"""API smoke test — verifies the FastAPI service matches the Streamlit numbers.

Catches the failure mode that matters most: the API quietly disagreeing with
the app the demo was rehearsed on. The demo cache was built from the SAME
trained model, so a live REAL-mode forecast must reproduce the cached probs
(deterministic CPU inference, same weights, same transform).

Usage (server must be running):
  python -m uvicorn api.main:app --port 8000
  python scripts/check_api.py [--base http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    a = ap.parse_args()
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    print("1) /api/health")
    h = get(a.base, "/api/health")
    print(f"    mode={h['mode']} windows={h['n_windows']} scenarios={h['n_scenarios']} "
          f"thr={h['threshold']}")
    check("mode is REAL (model + scaler loaded)", h["mode"] == "REAL",
          h.get("model_error") or "")
    check("windows loaded", h["n_windows"] > 0)
    check("scenarios built", h["n_scenarios"] > 0)

    print("2) /api/scenarios")
    scs = get(a.base, "/api/scenarios")
    kinds = {s["kind"] for s in scs}
    print(f"    {len(scs)} scenarios, kinds={sorted(kinds)}")
    check("has 'during' (mid-attack) scenarios", "during" in kinds)
    check("has 'quiet' baseline scenario", "quiet" in kinds)

    print("3) /api/forecast vs demo_cache.json (same model, deterministic)")
    cache = json.loads((ROOT / "data" / "processed" / "demo_cache.json")
                       .read_text(encoding="utf-8"))
    cached = cache.get("scenarios") or {}
    overlap = [s for s in scs if s["id"] in cached]
    print(f"    {len(overlap)} scenarios overlap with the cache")
    check("cache/API scenario overlap > 0", len(overlap) > 0)
    worst = 0.0
    for s in overlap:
        r = post(a.base, "/api/forecast", {"scenario_id": s["id"]})
        diffs = [abs(a - b) for a, b in zip(r["probs"], cached[s["id"]]["probs"])]
        worst = max(worst, max(diffs) if diffs else 0.0)
        if r["mode"] != "REAL":
            failures.append(f"{s['id']} mode={r['mode']}")
    print(f"    worst |live - cached| probability diff: {worst:.4f}")
    check("live forecasts reproduce the cache", worst < 1e-3)

    print("4) /api/timeline")
    tl = get(a.base, f"/api/timeline?scenario_id={overlap[0]['id']}" if overlap
             else f"/api/timeline?scenario_id={scs[0]['id']}")
    anchor_i = tl["anchor_index"]
    before = [p for p in tl["points"][:anchor_i] if p["forecast"] is not None]
    # forecast fills anchor+1 .. anchor+K; the trailing CONTEXT_AFTER windows are
    # observed-only on purpose (ground truth to check the forecast against).
    k = len([p for p in tl["points"][anchor_i + 1:] if p["forecast"] is not None])
    horizon_gaps = [p for p in tl["points"][anchor_i + 1:anchor_i + 1 + k]
                    if p["forecast"] is None]
    print(f"    {len(tl['points'])} points, forecast starts at index {anchor_i}, {k} steps")
    check("history carries no forecast", not before)
    check("forecast horizon has no gaps", not horizon_gaps)
    check("forecast covers the full K-step horizon", k >= 4)

    print("5) /api/metrics")
    m = get(a.base, "/api/metrics")
    check("baseline section present", "baseline" in m)
    check("lstm section present", "lstm" in m)
    check("lead_time section present", "lead_time" in m)
    if "baseline" in m and "lstm" in m:
        lb = m["baseline"].get("logistic_baseline", {})
        lt = m["lstm"].get("lstm_forecaster", {})
        check("benchmark keys survive the merge (not clobbered by lead_time)",
              "pr_auc" in lt, f"lstm pr_auc={lt.get('pr_auc')} "
              f"(logistic={lb.get('pr_auc')})")

    print("6) /api/flagged")
    f = get(a.base, "/api/flagged")
    print(f"    {f['total_flagged']} flagged of {f['total_windows']} windows, "
          f"{len(f['rows'])} rows returned")
    check("flagged rows serialize", len(f["rows"]) > 0)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("ALL CHECKS PASSED - API matches the rehearsed numbers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
