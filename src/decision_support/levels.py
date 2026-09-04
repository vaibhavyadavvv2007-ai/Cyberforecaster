"""Response levels — the explicit, readable ladder.

Four levels, MONITOR → ESCALATE. The thresholds below are deliberately
simple and printed in the plan: a judge must be able to re-derive the level
from the forecast alone. Nothing here executes anything — rule 6 of the
master plan: decision support only, the analyst stays in control.

Inputs (all from real model outputs, never invented):
  probs          (K,) forecast trajectory, one probability per horizon step
  threshold      the model's alerting threshold (max_fpr-0.05 on val)
  confidence     HIGH / MEDIUM / LOW from MC-dropout spread (uncertainty.py);
                 None when MC was not run — treated as MEDIUM, never as HIGH
  crossing_step  first horizon step (1-based) at/above threshold, None if none

Ladder (first match wins):
  MONITOR              no step reaches the threshold
  INVESTIGATE          threshold crossed, but the forecast is far out
                       (crossing >= 3 steps ahead) OR the MC band is LOW —
                       verify before committing analyst time
  ESCALATE             threshold crossed within 2 steps AND sustained (>= 3
                       of 5 steps above) AND MC band HIGH — the model is
                       both confident and consistent
  CONTAINMENT REVIEW   everything else that crosses the threshold within 2
                       steps — bring containment options to a human, do not
                       act
"""
from __future__ import annotations

import numpy as np

LEVELS = ["MONITOR", "INVESTIGATE", "CONTAINMENT REVIEW", "ESCALATE"]

LEVEL_GUIDANCE = {
    "MONITOR": "No forecast step crosses the alerting threshold. Keep the "
               "normal watch; the next bin updates this assessment.",
    "INVESTIGATE": "Threshold crossed, but distant or uncertain. Assign an "
                   "analyst to verify the evidence before any further action.",
    "CONTAINMENT REVIEW": "Threshold crossed near-term. A human reviews "
                          "containment options (isolation, credential reset) "
                          "against the evidence below — the system executes "
                          "nothing by itself.",
    "ESCALATE": "Near-term, sustained and high-confidence forecast. Escalate "
                "to the on-call owner immediately with the evidence packet.",
}

SUSTAIN_STEPS = 3        # of K=5 steps above threshold = "sustained"
NEAR_CROSSING = 2        # crossing within this many steps = "near-term"


def level_for(probs, threshold: float, confidence: str | None = None) -> dict:
    """The whole ladder, evaluated. Returns level + the facts that chose it
    so the UI can show WHY this level (same honesty as the forecast itself)."""
    probs = np.asarray(probs, dtype=np.float64)
    if probs.size == 0:
        raise ValueError("empty forecast trajectory")
    band = confidence if confidence in ("HIGH", "MEDIUM", "LOW") else "MEDIUM"
    peak = float(probs.max())
    above = probs >= threshold
    n_above = int(above.sum())
    crossing = int(np.argmax(above)) + 1 if n_above else None   # 1-based

    if n_above == 0:
        level, why = "MONITOR", "no step reaches the threshold"
    elif band == "LOW":
        level = "INVESTIGATE"
        why = "crosses the threshold but MC-dropout spread is LOW (max_std >= 0.15) — verify first"
    elif crossing is not None and crossing > NEAR_CROSSING:
        level = "INVESTIGATE"
        why = f"crossing is {crossing} steps out (> {NEAR_CROSSING}) — time to verify before acting"
    elif n_above >= SUSTAIN_STEPS and band == "HIGH":
        level = "ESCALATE"
        why = (f"crosses at step {crossing} (<= {NEAR_CROSSING}), {n_above}/"
               f"{len(probs)} steps above threshold, MC band HIGH")
    else:
        level = "CONTAINMENT REVIEW"
        why = (f"crosses at step {crossing} (<= {NEAR_CROSSING}) with "
               f"{n_above}/{len(probs)} steps above and MC band {band}")

    return {
        "level": level,
        "guidance": LEVEL_GUIDANCE[level],
        "why": why,
        "facts": {
            "peak": round(peak, 4),
            "threshold": round(float(threshold), 4),
            "crossing_step": crossing,
            "steps_above": n_above,
            "confidence": band,
        },
    }
