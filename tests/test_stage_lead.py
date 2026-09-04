"""Tests for stage-transition lead time (src/evaluation/stage_lead.py)."""
from __future__ import annotations

import numpy as np

from src.attack_mapping.mitre_mapper import STAGES
from src.evaluation.stage_lead import (find_stage_onsets, stage_lead_times,
                                       to_minutes, window_stages)


class TestFindStageOnsets:
    def test_basic_transitions(self):
        # stages over 8 windows: benign, benign, RECON(0), RECON, IA(1), IA, benign, C2(3)
        stages = np.array([-1, -1, 0, 0, 1, 1, -1, 3])
        onsets = find_stage_onsets(stages)
        assert onsets == {0: [2], 1: [4], 3: [7]}

    def test_no_onset_without_observed_predecessor(self):
        # stage active from window 0: not a transition we could have anticipated
        stages = np.array([0, 0, 0])
        assert find_stage_onsets(stages) == {}

    def test_same_stage_restart_counts(self):
        # 0 -> -1 -> 0: a NEW run of stage 0 is a fresh onset
        stages = np.array([0, -1, 0])
        assert find_stage_onsets(stages) == {0: [2]}

    def test_all_benign(self):
        assert find_stage_onsets(np.array([-1, -1, -1])) == {}


class TestStageLeadTimes:
    def _ends(self, n: int, horizon: int = 5) -> np.ndarray:
        # sequence i covers windows i+1 .. i+K (anchor = i)
        return np.arange(horizon + 1, horizon + 1 + n, dtype=int)

    def test_perfect_warning_two_windows_early(self):
        horizon, n = 5, 20
        stages = np.full(n + horizon + 1, -1, dtype=int)
        stages[10:] = 1                       # stage 1 (Initial Access) from w=10
        ends = self._ends(n, horizon)
        # onset w=10 is forecast by the sequence anchored at 10-j at step j:
        # only anchor 8 / step 2 (j=2) names stage 1 for it
        pred = np.full((n, horizon), -1, dtype=int)
        pred[8, 1] = 1                        # anchor 8, step 2 -> covers w=10
        pred[9, 2] = 1                        # anchor 9, step 3 -> covers w=12 (not the onset)
        s = stage_lead_times(stages, ends, pred, horizon)
        assert s["n_stage_onsets"] == 1
        assert s["warned_rate"] == 1.0
        assert s["median_lead_windows"] == 2.0

    def test_no_warning_gives_zero(self):
        horizon, n = 5, 20
        stages = np.full(n + horizon + 1, -1, dtype=int)
        stages[10:] = 2
        pred = np.zeros((n, horizon), dtype=int)   # always predicts stage 0
        s = stage_lead_times(stages, self._ends(n, horizon), pred, horizon)
        per = next(v for k, v in s["per_stage"].items() if k == STAGES[2])
        assert per["n_warned"] == 0
        assert s["warned_rate"] == 0.0

    def test_wrong_stage_never_counts(self):
        horizon, n = 5, 20
        stages = np.full(n + horizon + 1, -1, dtype=int)
        stages[10:] = 4                        # Exfiltration
        pred = np.full((n, horizon), 1, dtype=int)   # always Initial Access
        s = stage_lead_times(stages, self._ends(n, horizon), pred, horizon)
        assert s["warned_rate"] == 0.0

    def test_per_stage_breakdown_present(self):
        horizon, n = 5, 20
        stages = np.full(n + horizon + 1, -1, dtype=int)
        stages[10:] = 1
        pred = np.full((n, horizon), -1, dtype=int)
        pred[8, 1] = 1
        s = stage_lead_times(stages, self._ends(n, horizon), pred, horizon)
        assert STAGES[1] in s["per_stage"]


class TestToMinutes:
    def test_conversion(self):
        s = {"median_lead_windows": 2.0, "mean_lead_windows": 2.0,
             "max_lead_windows": 4.0}
        m = to_minutes(s, bin_secs=30)
        assert m["median_lead_min"] == 1.0
        assert m["max_lead_min"] == 2.0
