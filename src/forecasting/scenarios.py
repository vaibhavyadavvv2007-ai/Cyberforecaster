"""Demo scenarios — shared by the app and the cache builder.

Lives here, not in the app, so the precomputed cache and the live app can never
disagree about what "scenario onset-1234" means. A cache keyed to scenarios the
app builds differently is a silent wrong-answer machine, and the cache exists
precisely for the moment we cannot debug anything.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..attack_mapping.mitre_mapper import STAGES
from ..features.window_builder import HORIZON, SEQ_LEN, WINDOW_FEATURES

# The five progression stages the PS names. DoS is deliberately NOT here — ATT&CK
# places flooding under Impact, outside this chain (battle plan §5.4).
CHAIN = ["Reconnaissance", "Initial Access", "Lateral Movement",
         "Command & Control", "Exfiltration"]

CONTEXT_BEFORE = 30      # windows of history to plot around a scenario
CONTEXT_AFTER = 5
DURING_OFFSET = 5        # windows past an onset to anchor the "attack underway" view


def build_scenarios(windows: pd.DataFrame, max_n: int = 8) -> list[dict]:
    """Named demo moments, in two honest families.

    PRE-ONSET (anchor = last clean window before an onset): the input carries
    NO precursor signal in this dataset (measured — see
    scripts/diagnose_leadtime.py; CIC attacks are scripted and start abruptly),
    so a good model shows honest uncertainty here, not a magic warning.

    DURING-ATTACK (anchor = onset+5, attack underway in the input): this is
    where a temporal forecaster EARNS its name — the trajectory should stay
    high (persistence) while the attack runs and decay as it ends.

    The demo moment is measured, not staged — and if the curve stays flat, that
    is real information about the model, not a UI bug.
    """
    attack = windows["attack_frac"].to_numpy() > 0
    stage_idx = windows["dominant_stage_idx"].to_numpy()
    onsets = [i for i in range(1, len(attack)) if attack[i] and not attack[i - 1]]

    pre, during = [], []
    for i in onsets:
        st_i = int(stage_idx[i])
        label = STAGES[st_i] if 0 <= st_i < len(STAGES) else "attack"
        if i - 1 >= SEQ_LEN - 1 and i - 1 + HORIZON < len(windows):
            pre.append({
                "id": f"onset-{i}",
                "name": f"{windows.index[i]:%d %b %H:%M} - {label} onset (forecast from before)",
                "anchor": int(i - 1),
                "kind": "onset",
            })
        if i + DURING_OFFSET >= SEQ_LEN - 1 and i + DURING_OFFSET + HORIZON < len(windows):
            a = i + DURING_OFFSET
            # "underway" must mean the attack DOMINATES the anchored window —
            # a burst diluted to a 2% share by ~900 benign flows/min is not
            # "underway", it is "started but invisible", which the model
            # honestly reports as low risk.
            if float(windows["attack_frac"].iloc[a]) >= 0.3:
                during.append({
                    "id": f"during-{i}",
                    "name": f"{windows.index[a]:%d %b %H:%M} - {label} underway (expect persistence)",
                    "anchor": int(a),
                    "kind": "during",
                })

    # spread picks across the whole timeline rather than taking the first N
    def spread(items: list[dict], n: int) -> list[dict]:
        if len(items) <= n:
            return items
        step = len(items) / n
        return [items[int(j * step)] for j in range(n)]

    half = max(max_n // 2, 1)
    out = spread(pre, half) + spread(during, max_n - half)

    # a quiet stretch too — an honest demo shows the low-risk case as well,
    # and it is the only on-stage evidence about false positives.
    quiet = [i for i in range(SEQ_LEN, len(windows) - HORIZON)
             if not attack[max(0, i - SEQ_LEN):i + HORIZON].any()]
    if quiet:
        mid = int(quiet[len(quiet) // 2])
        out.append({"id": f"quiet-{mid}", "kind": "quiet", "anchor": mid,
                    "name": f"{windows.index[mid]:%d %b %H:%M} - quiet baseline (expect LOW)"})
    return out


def sequence_at(windows: pd.DataFrame, anchor: int) -> np.ndarray:
    """(L, F) RAW feature window ending at `anchor`, in canonical feature order.

    Indexed by WINDOW_FEATURES explicitly — deriving the column list by exclusion
    lets column order drift silently reorder the model's inputs.
    """
    lo = anchor - SEQ_LEN + 1
    if lo < 0:
        raise ValueError(f"anchor {anchor} has fewer than {SEQ_LEN} windows of history")
    return windows[list(WINDOW_FEATURES)].iloc[lo:anchor + 1].to_numpy(dtype=np.float64)
