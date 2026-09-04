"""UNSW-NB15 adapter — first new dataset wired after the CIC2018 baseline.

Files verified on disk 2026-09-04 (data/raw/unsw_nb15/, byte sizes exact):
  UNSW-NB15_{1..4}.csv — 2,540,047 flows, HEADERLESS, 49 columns exactly
  matching NUSW-NB15_features.csv (srcip … ct_dst_src_ltm, attack_cat,
  Label). NUSW-NB15_GT.csv (per-packet ground truth) and the features/events
  listings are also present but NOT consumed: the main CSVs already carry
  per-flow attack_cat + Label.

What this source provides (verified from the real files):
  ✓ 12 of the legacy 18 V1 features — INCLUDING unique_src_ips /
    unique_dst_ips (UNSW ships real IP columns, unlike CIC2018's ML CSVs)
  ✗ NO TCP flag counts: there is no SYN/ACK/FIN/RST/PSH packet column
    (synack/ackdat are TCP-setup *times*; state FIN/RST are per-flow states,
    not packet counts). syn/ack/fin/rst/psh ratios are honestly UNAVAILABLE.
  ✗ NO per-flow IAT std: Sintpkt/Dintpkt are mean interpacket times per
    direction — enough for iat_mean (ms→s, directions averaged), not iat_std.
  ✓ extras CIC2018 cannot provide: ttl_mean/ttl_std (sttl/dttl),
    tcp_window_mean/std (swin/dwin, TCP flows only), duration_std,
    src_port_entropy, flow_rate/packet_rate, all Group-G service ratios
    (port-based, matching the canonical definitions).

Semantics notes (kept honest, per DATA_CONTRACT "never pretend datasets
provide the same information"):
  - sloss/dloss are "packets retransmitted OR DROPPED" — close to, but not
    the same as, canonical retransmission_rate → left UNAVAILABLE.
  - smeanz/dmeansz are mean packet sizes per direction, not L4 payload
    sizes → payload_* left UNAVAILABLE (avg_pkt_size covers packet size).
  - down_up_ratio = dbytes/sbytes per flow (same construction as CIC's
    Down/Up Ratio), averaged over flows with sbytes > 0.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..features.canonical_schema import WindowSlots
from ..labels.attack_taxonomy import (BENIGN, UNSW_FAMILY_CANONICAL,
                                      LabelRecord, canonicalize)
from .base import AttackMetadata, DatasetAdapter, ValidationReport

# The 49 columns, in file order — NUSW-NB15_features.csv is authoritative.
UNSW_COLUMNS = [
    "srcip", "sport", "dstip", "dsport", "proto", "state", "dur",
    "sbytes", "dbytes", "sttl", "dttl", "sloss", "dloss", "service",
    "Sload", "Dload", "Spkts", "Dpkts", "swin", "dwin", "stcpb", "dtcpb",
    "smeansz", "dmeansz", "trans_depth", "res_bdy_len", "Sjit", "Djit",
    "Stime", "Ltime", "Sintpkt", "Dintpkt", "tcprtt", "synack", "ackdat",
    "is_sm_ips_ports", "ct_state_ttl", "ct_flw_http_mthd", "is_ftp_login",
    "ct_ftp_cmd", "ct_srv_src", "ct_srv_dst", "ct_dst_ltm", "ct_src_ltm",
    "ct_src_dport_ltm", "ct_dst_sport_ltm", "ct_dst_src_ltm",
    "attack_cat", "Label",
]
N_COLS = len(UNSW_COLUMNS)            # 49
assert N_COLS == 49

# Columns load() keeps — everything downstream needs + the canonical flow
# record. Dropped eagerly to keep 2.5M-row loads lean.
USECOLS = ["srcip", "sport", "dstip", "dsport", "proto", "state", "dur",
           "sbytes", "dbytes", "sttl", "dttl", "Spkts", "Dpkts",
           "swin", "dwin", "Sintpkt", "Dintpkt", "Stime", "Ltime",
           "attack_cat", "Label"]

SOURCE = "unsw_csv"
BENIGN_SENTINELS = ("", "NORMAL", "Normal")
# canonical Group-G service ratios, port-based like everywhere else
_SERVICE_PORTS = {
    "http_ratio": {80, 8080}, "dns_ratio": {53}, "ssh_ratio": {22},
    "rdp_ratio": {3389}, "smb_ratio": {445}, "ftp_ratio": {20, 21},
}
_AUTH_PORTS = {21, 22, 23, 3389}


def _entropy(counts: pd.Series) -> float:
    """Shannon entropy over category counts (nats→bits via log2)."""
    c = counts.astype(float).to_numpy()
    c = c[c > 0]
    if len(c) <= 1:
        return 0.0
    p = c / c.sum()
    return float(-(p * np.log2(p)).sum())


class UNSWNB15Adapter(DatasetAdapter):
    dataset_id = "unsw_nb15"
    name = "UNSW-NB15"
    version = "NB15 (main CSVs, 9 attack categories, 2015-01-22 → 2015-02-18)"
    source_url = "https://research.unsw.edu.au/projects/unsw-nb15-dataset"
    modality = "flow_csv"

    # -------------------------------------------------------------- discover
    def discover(self, root: Path) -> list[Path]:
        """The four main CSVs only — GT/features/events listings are not
        training inputs and must not make a partial download look complete."""
        root = Path(root)
        sub = root / self.dataset_id
        if not sub.is_dir():
            return []
        return sorted(sub.glob("UNSW-NB15_[1-4].csv"))

    # -------------------------------------------------------------- validate
    def validate(self, files: list[Path]) -> ValidationReport:
        if not files:
            return ValidationReport(False, 0.0, "none",
                                    errors=["no UNSW-NB15_*.csv files found"])
        checks: dict[str, str] = {}
        errors: list[str] = []
        try:
            head = pd.read_csv(files[0], header=None, names=UNSW_COLUMNS,
                               nrows=50, usecols=USECOLS,
                               dtype={"srcip": str, "dstip": str, "proto": str,
                                      "state": str, "attack_cat": str})
        except Exception as exc:  # noqa: BLE001 — report, never crash
            return ValidationReport(False, 0.0, "unreadable CSV",
                                    errors=[f"{type(exc).__name__}: {exc}"])

        # headerless 49 columns: every expected column parsed with a usable dtype
        checks["headerless_49_columns"] = "OK" if len(head.columns) == len(
            {c for c in USECOLS}) else "column mismatch"
        n_bad_ts = int(pd.to_numeric(head["Stime"], errors="coerce")
                       .isna().sum())
        checks["stime_numeric_epoch"] = "OK" if n_bad_ts == 0 \
            else f"{n_bad_ts} unparseable"
        labels_ok = set(pd.to_numeric(head["Label"], errors="coerce")
                        .dropna().unique()) <= {0, 1}
        checks["label_binary"] = "OK" if labels_ok else "non-binary Label"
        cats = {str(c).strip() for c in head["attack_cat"].dropna().unique()}
        unknown = cats - set(UNSW_FAMILY_CANONICAL) - set(BENIGN_SENTINELS)
        checks["attack_cat_spelling"] = "OK" if not unknown \
            else f"unrecognized: {sorted(unknown)[:3]}"
        n_files = len(files)
        checks["main_files"] = "OK (4/4)" if n_files == 4 \
            else f"partial {n_files}/4"

        n_ok = sum(1 for v in checks.values() if v == "OK" or v.startswith("OK"))
        ok = (n_bad_ts == 0 and labels_ok and not unknown and n_files == 4)
        if not ok:
            errors = [f"{k}: {v}" for k, v in checks.items()
                      if not v.startswith("OK")]
        return ValidationReport(
            ok=ok, confidence=round(n_ok / len(checks), 3),
            detected_format="UNSW-NB15 flow CSV (headerless, 49 columns)",
            checks=checks, errors=errors)

    # ------------------------------------------------------------------ load
    def load(self, files: list[Path]) -> pd.DataFrame:
        """Main CSVs → canonical flow records + the raw extras windowing needs."""
        frames = []
        for p in files:
            df = pd.read_csv(p, header=None, names=UNSW_COLUMNS,
                             usecols=USECOLS,
                             dtype={"srcip": str, "dstip": str, "proto": str,
                                    "state": str, "attack_cat": str},
                             low_memory=False)
            frames.append(df)
        raw = pd.concat(frames, ignore_index=True)
        raw = raw.sort_values("Stime", kind="mergesort").reset_index(drop=True)

        out = pd.DataFrame({
            "ts": pd.to_datetime(raw["Stime"], unit="s", utc=True),
            "src_ip": raw["srcip"], "src_port": raw["sport"],
            "dst_ip": raw["dstip"], "dst_port": raw["dsport"],
            "protocol": raw["proto"],
            "duration_s": pd.to_numeric(raw["dur"], errors="coerce"),
            "pkts": (pd.to_numeric(raw["Spkts"], errors="coerce")
                     + pd.to_numeric(raw["Dpkts"], errors="coerce")),
            "bytes": (pd.to_numeric(raw["sbytes"], errors="coerce")
                      + pd.to_numeric(raw["dbytes"], errors="coerce")),
            "fwd_pkts": pd.to_numeric(raw["Spkts"], errors="coerce"),
            "bwd_pkts": pd.to_numeric(raw["Dpkts"], errors="coerce"),
            "fwd_bytes": pd.to_numeric(raw["sbytes"], errors="coerce"),
            "bwd_bytes": pd.to_numeric(raw["dbytes"], errors="coerce"),
            # mean of the two directional interpacket means, ms → s
            "iat_mean_s": ((pd.to_numeric(raw["Sintpkt"], errors="coerce")
                            + pd.to_numeric(raw["Dintpkt"], errors="coerce"))
                           / 2.0 / 1000.0),
            "iat_std_s": np.nan,          # NOT provided (means only)
            "syn_cnt": np.nan, "ack_cnt": np.nan, "fin_cnt": np.nan,
            "rst_cnt": np.nan, "psh_cnt": np.nan,   # NOT provided (no flag counts)
            "dataset_label": raw["attack_cat"].fillna("").str.strip()
                             .replace({"": "NORMAL"}),
        })
        # raw extras for to_window_slots (not part of the canonical record)
        for col in ("sttl", "dttl", "swin", "dwin", "state", "proto"):
            out[col] = raw[col]
        return out

    # --------------------------------------------------------------- windows
    def to_window_slots(self, flows: pd.DataFrame, bin_secs: int = 30
                        ) -> tuple[list[WindowSlots], list[LabelRecord]]:
        df = flows.sort_values("ts", kind="mergesort")
        df = df.assign(bin=df["ts"].dt.floor(f"{bin_secs}s"))

        slots: list[WindowSlots] = []
        labels: list[LabelRecord] = []
        for bin_ts, g in df.groupby("bin", sort=True):
            ws = WindowSlots(source=SOURCE, ts=bin_ts.timestamp())

            pkts = g["pkts"].to_numpy(dtype=float)
            fwd_b = g["fwd_bytes"].to_numpy(dtype=float)
            bwd_b = g["bwd_bytes"].to_numpy(dtype=float)
            dur = g["duration_s"].to_numpy(dtype=float)

            ws.set("flow_count", float(len(g)), SOURCE)
            ws.set("bytes_total", float(np.nansum(fwd_b + bwd_b)), SOURCE)
            ws.set("pkts_total", float(np.nansum(pkts)), SOURCE)
            d = dur[~np.isnan(dur)]
            if len(d):
                ws.set("duration_mean", float(d.mean()), SOURCE)
                if len(d) > 1:
                    ws.set("duration_std", float(d.std()), SOURCE)
            nz = pkts > 0
            if nz.any():
                ws.set("avg_pkt_size",
                       float(np.mean((fwd_b + bwd_b)[nz] / pkts[nz])), SOURCE)
            pos = fwd_b > 0
            if pos.any():
                ws.set("down_up_ratio",
                       float(np.mean(bwd_b[pos] / fwd_b[pos])), SOURCE)
            iat = g["iat_mean_s"].dropna().to_numpy(dtype=float)
            if len(iat):
                ws.set("iat_mean", float(iat.mean()), SOURCE)
            # iat_std stays absent — the source provides means only

            ws.set("unique_dst_ports", float(g["dst_port"].nunique()), SOURCE)
            ws.set("unique_dst_ips", float(g["dst_ip"].nunique()), SOURCE)
            ws.set("unique_src_ips", float(g["src_ip"].nunique()), SOURCE)
            ws.set("src_port_entropy", _entropy(g["src_port"].value_counts()),
                   SOURCE)
            ws.set("dst_port_entropy",
                   _entropy(g["dst_port"].value_counts()), SOURCE)

            ws.set("flow_rate", float(len(g)) / bin_secs, SOURCE)
            ws.set("packet_rate", float(np.nansum(pkts)) / bin_secs, SOURCE)

            ports = set(g["dst_port"].dropna().unique())
            for feat, want in _SERVICE_PORTS.items():
                ws.set(feat, float(len(g[g["dst_port"].isin(want)])) / len(g),
                       SOURCE)
            ws.set("auth_port_share",
                   float(len(g[g["dst_port"].isin(_AUTH_PORTS)])) / len(g),
                   SOURCE)

            ttl = (pd.to_numeric(g["sttl"], errors="coerce").to_numpy(float)
                   + pd.to_numeric(g["dttl"], errors="coerce").to_numpy(float)) / 2
            ttl = ttl[~np.isnan(ttl)]
            if len(ttl):
                ws.set("ttl_mean", float(ttl.mean()), SOURCE)
                if len(ttl) > 1:
                    ws.set("ttl_std", float(ttl.std()), SOURCE)
            # TCP window: swin/dwin are 0 for non-TCP flows — averaging those
            # in would fabricate a window size, so restrict to TCP flows.
            tcp = g[g["proto"].str.lower() == "tcp"]
            if len(tcp):
                w = (pd.to_numeric(tcp["swin"], errors="coerce")
                     + pd.to_numeric(tcp["dwin"], errors="coerce")) / 2
                w = w.dropna()
                if len(w):
                    ws.set("tcp_window_mean", float(w.mean()), SOURCE)
                    if len(w) > 1:
                        ws.set("tcp_window_std", float(w.std()), SOURCE)
            # syn/ack/fin/rst/psh ratios, payload sizes, retransmission
            # (sloss/dloss = "retransmitted or dropped" ≠ retransmitted),
            # burstiness, iat_max, scan-pattern shares: UNAVAILABLE — see
            # the module docstring. Never zero-filled.

            slots.append(ws)

            # dominant ORIGINAL label per bin (ties → first by count)
            fam = str(g["dataset_label"].value_counts().index[0])
            if fam in BENIGN_SENTINELS:
                labels.append(LabelRecord(self.dataset_id, "NORMAL", BENIGN,
                                          "benign", "verified"))
            else:
                labels.append(canonicalize(self.dataset_id, fam))
        return slots, labels

    # -------------------------------------------------------------- metadata
    def attack_metadata(self, flows: pd.DataFrame) -> AttackMetadata:
        counts = flows["dataset_label"].value_counts().to_dict()
        fams = {f: canonicalize(self.dataset_id, f).canonical_label
                for f in counts if f not in BENIGN_SENTINELS}
        tr = (str(flows["ts"].min()), str(flows["ts"].max())) \
            if len(flows) else None
        return AttackMetadata(families=fams, n_flows=int(len(flows)),
                              label_counts={k: int(v) for k, v in counts.items()},
                              time_range=tr,
                              scenarios=sorted(set(flows["ts"].dt.date.astype(str))))
