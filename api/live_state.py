"""Live-demo service — one process-wide instance behind the /api/live/* routes.

Owns the sensor (capture thread) and the history (seed + live windows +
forecaster). Endpoints in main.py only start/stop/poll this object, so the
capture thread's lifecycle cannot drift from what the UI sees.
"""
from __future__ import annotations

import threading

from src.live.history import LiveHistory
from src.live.sensor import LiveSensor, list_interfaces

BIN_SECS = 30   # intentionally 30s (≠ training's 60s in meta.txt): lower
                # latency on demo day. The mismatch is the A/B experiment;
                # features that depend on bin size (iat_mean, duration_mean,
                # bytes_total, pkts_total, flow_count) will differ in scale
                # from the training distribution. Disclose this if asked.


class LiveService:
    def __init__(self):
        self.sensor: LiveSensor | None = None
        self.history = LiveHistory()          # replaced on start()
        self.last_error: str | None = None    # why the last start() failed
        self._lock = threading.Lock()

    # -------------------------------------------------------------- start
    def start(self, iface: str | None = None, use_seed: bool = True) -> dict:
        with self._lock:
            if self.sensor is not None and self.sensor.running:
                return {"ok": True, "already_running": True,
                        "status": self.sensor.status()}
            from api.state import state       # late import: state loads torch
            fc = state.forecaster
            hist = LiveHistory(forecaster=fc,
                               rule_p99=(state.p99_bytes, state.p99_pkts))
            n_seed = hist.load_seed() if use_seed else 0
            sensor = LiveSensor(iface=iface, bin_secs=BIN_SECS)
            err = sensor.start()
            if err:
                self.last_error = err
                return {"ok": False, "error": err, "interfaces": list_interfaces()}
            self.last_error = None
            self.sensor, self.history = sensor, hist
            return {"ok": True, "seeded_windows": n_seed,
                    "model_ready": fc is not None,
                    "status": sensor.status()}

    def stop(self) -> dict:
        with self._lock:
            if self.sensor is None:
                return {"ok": True, "was_running": False}
            self.sensor.stop()
            return {"ok": True, "was_running": True,
                    "windows_captured": len(self.history.live)}

    # --------------------------------------------------------------- feed
    def poll(self) -> dict | None:
        """Drain one finalized bin (if any) into the history."""
        if self.sensor is None:
            return None
        w = self.sensor.poll()
        if w is None:
            return None
        w["source"] = "live"
        self.history.append_live(w)
        return w

    def feed(self) -> dict:
        self.poll()
        with self._lock:
            sensor = self.sensor
            hist = self.history
        sensor_status = sensor.status() if sensor else {
            "running": False, "iface": None, "error": self.last_error, "bin_secs": BIN_SECS,
            "packets_seen": 0, "packets_skipped": 0, "flows_in_bin": 0,
            "bin_elapsed_s": 0.0, "bin_remaining_s": float(BIN_SECS),
            "started_at": None, "last_packet_age_s": None,
        }
        latest = hist.predict() if sensor is not None else None
        self.annotate()
        windows = self._windows_payload(hist)
        from src.features.window_builder import SEQ_LEN
        return {
            "sensor": sensor_status,
            "bin_secs": BIN_SECS,
            "seq_len": SEQ_LEN,
            "n_seed": len(hist.seed),
            "n_live": len(hist.live),
            "ready": hist.ready(),
            "windows": windows,
            "latest": latest,
            "events": hist.events[-20:],
        }

    def _windows_payload(self, hist: LiveHistory) -> list[dict]:
        """Compact per-window rows for the live chart. forecast_peak is the
        model's peak next-horizon probability as of that window — computed by
        replaying the same 10-window sequence the model would have seen."""
        out = []
        for w in hist.all_windows()[-90:]:
            f = w["features"]
            row = {
                "ts": w["ts"], "bin_id": w.get("bin_id", 0),
                "source": w.get("source", "seed"),
                "flow_count": f["flow_count"],
                "pkts_total": f["pkts_total"],
                "syn_ratio": round(f["syn_ratio"], 4),
                "unique_dst_ports": f["unique_dst_ports"],
                "rule_stage": hist._rule_stage(w),
                "empty": bool(w.get("empty", False)),
            }
            if "forecast_peak" in w:
                row["forecast_peak"] = w["forecast_peak"]
            out.append(row)
        return out

    # ------------------------------------------------------- annotation
    def annotate(self) -> None:
        """Backfill forecast_peak on any window that lacks it (seed replay,
        or live windows that arrived while the model was briefly busy). Runs
        opportunistically on /api/live/feed — each missing window is one
        forward pass; the seed's ~18 windows annotate in well under a second."""
        hist = self.history
        if not hist.ready():
            return
        import numpy as np
        from src.features.window_builder import SEQ_LEN
        from src.live.history import model_matrix
        allw = hist.all_windows()
        for i in range(len(allw) - 1, SEQ_LEN - 2, -1):
            w = allw[i]
            if "forecast_peak" in w:
                break                        # everything older is annotated
            seq = model_matrix(allw[i - SEQ_LEN + 1:i + 1])
            try:
                res = hist.forecaster.predict(seq)          # type: ignore[union-attr]
                w["forecast_peak"] = round(max(res["probs"]), 4)
            except Exception:  # noqa: BLE001 — chart gap beats a crashed feed
                w["forecast_peak"] = None


live_service = LiveService()
