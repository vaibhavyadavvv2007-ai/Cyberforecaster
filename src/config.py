"""Single source of truth for the windowing contract (DATA_CONTRACT §3).

Before this module, the bin size lived in five places: meta.txt (30, the
production value after the Gate 1 decision), api/live_state.py (30), and
stale 60-second defaults in window_builder / pipeline / lead_time — a caller
that forgot to pass bin_secs silently built a *different timeline* than the
model was trained on. Now every default imports from here.

Changing any of these values invalidates every trained model and demo
artifact; the meta.txt written by the preprocessing pipeline records them
per-run so artifacts can refuse mismatches.
"""
from __future__ import annotations

BIN_SECS = 30    # window size, seconds (Gate 1 decision, 2026-09)
SEQ_LEN = 10     # L: history windows fed to the model
HORIZON = 5      # K: windows forecast ahead
