"""Upload analysis pipeline (plan §29–32): PCAP / CSV → forecast + decisions.

One file in, one decision-support record out — through the SAME feature and
model path as training and live (never a third implementation):

    PCAP ──→ extract_pcap (Phase 4, reuses the live packet pipeline)
    CSV  ──→ ColumnMapper → build_windows (the audited training windowing)
                      ↓
         model_matrix conditioning (IP-zeroing + p99 clamps, as live)
                      ↓
         Forecaster.predict per anchor  → forecast trajectory
                      ↓
         MC uncertainty + evidence + decision support (Phases 9–10)

Security (parse, never execute):
  - format detection is by MAGIC BYTES, never by trusting the extension
  - PCAPs are parsed by scapy's PcapReader only; nothing in an uploaded
    file is ever executed or eval'd
  - CSVs are read with pandas only; formulas (e.g. `=cmd|...` spreadsheet
    injection) stay inert strings and are never sent to Excel/eval
  - the caller enforces a size cap before this module runs

Honesty (plan rule 4): features the source cannot provide are reported in
`unavailable_features`, never silently passed off as real zeros.
"""
from __future__ import annotations

import csv as _csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.config import BIN_SECS

# --- pcap magic bytes (libpcap + pcapng, incl. nanosecond variants) --------
PCAP_MAGIC = {
    b"\xd4\xc3\xb2\xa1": "pcap",      # little endian, microseconds
    b"\xa1\xb2\xc3\xd4": "pcap",      # big endian, microseconds
    b"\x4d\x3c\xb2\xa1": "pcap",      # little endian, nanoseconds
    b"\xa1\xb2\x3c\x4d": "pcap",      # big endian, nanoseconds
    b"\x0a\x0d\x0d\x0a": "pcapng",
}

MAX_CSV_SNIFF_ROWS = 50          # enough to survive a comment header, not more
GENERIC_MIN_FIELDS = {"ts", "dst_port"}   # below this we cannot window at all


class UnknownSchemaError(ValueError):
    """The file is neither a known flow-CSV schema nor a pcap. The caller
    must ask the user to map columns — never guess (plan §30)."""


class AnalysisError(RuntimeError):
    """The format was detected but the analysis itself failed."""


# ============================================================== detection

def detect_format(path: str | Path) -> dict:
    """Magic-byte + header detection with confidence. Never silent-guesses:
    an unrecognized file returns format 'unknown' with the mapper report so
    the UI can ask for a column mapping."""
    path = Path(path)
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head in PCAP_MAGIC:
        return {"format": PCAP_MAGIC[head], "style": None, "confidence": 1.0,
                "matched": ["magic bytes"], "missing": []}

    # ---- CSV: score the header against the two known flow schemas --------
    try:
        cols = _read_csv_header(path)
    except (UnicodeDecodeError, _csv.Error) as exc:
        raise UnknownSchemaError(
            f"not a pcap (magic bytes) and not a readable CSV: {exc}") from exc

    from src.ingestion.csv_loader import CORE_COLS
    cic_req = ("Timestamp", "Label", "Dst Port", "Flow Duration")
    present = {c.strip() for c in cols}
    if all(c in present for c in cic_req):
        core = sum(1 for c in CORE_COLS if c in present)
        return {"format": "csv", "style": "cic-flow-csv",
                "confidence": round(core / len(CORE_COLS), 3),
                "matched": [c for c in CORE_COLS if c in present],
                "missing": [c for c in CORE_COLS if c not in present]}

    report = ColumnMapper().map_columns(cols)
    if GENERIC_MIN_FIELDS <= set(report.mapping):
        conf = round(len(report.mapping) / len(ColumnMapper.FIELDS), 3)
        return {"format": "csv", "style": "generic-flow-csv",
                "confidence": conf,
                "matched": sorted(report.mapping),
                "missing": sorted(set(ColumnMapper.FIELDS) - set(report.mapping))}

    raise UnknownSchemaError(
        "unknown schema - please map columns",
        {"header": cols[:40], "mapper_report": report.to_dict()})


def _read_csv_header(path: Path) -> list[str]:
    """First header row of a CSV, tolerating leading junk (comment lines,
    BOM). Raises UnicodeDecodeError/csv.Error for non-CSV content."""
    import io
    with open(path, "r", encoding="utf-8-sig", errors="strict",
              newline="") as fh:
        for _ in range(MAX_CSV_SNIFF_ROWS):
            line = fh.readline()
            if not line:
                break
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("//"):
                continue
            return next(_csv.reader(io.StringIO(line)))
    raise _csv.Error("no non-comment header line found")


# ============================================================ ColumnMapper

@dataclass
class MappingReport:
    mapping: dict[str, str] = field(default_factory=dict)   # canonical → actual
    unmapped: list[str] = field(default_factory=list)       # input cols we ignored

    def to_dict(self) -> dict:
        return {"mapping": self.mapping, "unmapped": self.unmapped}


class ColumnMapper:
    """Plan §31: alias table → canonical flow fields. Maps a source header to
    the canonical names, then `to_flows()` turns it into the CIC-style
    flow DataFrame `build_windows` already understands — so a generic CSV
    flows through the SAME audited windowing as the training data."""

    # canonical field → column aliases seen across CIC/UNSW/CTU/Zeek exports
    FIELDS: dict[str, list[str]] = {
        "ts": ["Timestamp", "timestamp", "Time", "time", "StartTime",
               "start_time", "flow_start", "Date", "date", "stime"],
        "label": ["Label", "label", "Attack", "attack", "attack_cat",
                  "Attack Type", "attack_type", "class", "Category"],
        "src_ip": ["Src IP", "src_ip", "Source IP", "srcaddr", "SrcAddr",
                   "IP_SRC", "srcip", "src"],
        "dst_ip": ["Dst IP", "dst_ip", "Destination IP", "dstaddr",
                   "DstAddr", "IP_DST", "dstip", "dst"],
        "src_port": ["Src Port", "src_port", "Source Port", "Sport",
                     "sport", "srcport"],
        "dst_port": ["Dst Port", "dst_port", "Destination Port", "Dport",
                     "dport", "dstport"],
        "proto": ["Protocol", "proto", "Protocol Number", "pr"],
        "bytes": ["bytes", "Bytes", "tot_bytes", "TotBytes", "total_bytes",
                  "BytesTotal", "flow_bytes"],
        "pkts": ["pkts", "Pkts", "packets", "Packets", "tot_pkts",
                 "TotPkts", "total_packets", "flow_pkts"],
        "duration": ["duration", "Duration", "dur", "Dur", "flow_duration",
                     "flow_dur"],
    }

    def __init__(self, mapping: dict[str, str] | None = None):
        """`mapping` lets the UI override aliases with a user-confirmed map
        (canonical → actual column). Explicit mapping beats every alias."""
        self.explicit = dict(mapping or {})

    def map_columns(self, columns: list[str]) -> MappingReport:
        norm = {}                       # lowered/stripped alias → canonical
        for canon, aliases in self.FIELDS.items():
            for a in aliases:
                norm[a.strip().lower()] = canon
        mapping, used = {}, set()
        for col in columns:
            key = col.strip().lower()
            if key in self.explicit.values():      # explicit overrides later
                continue
            canon = norm.get(key)
            if canon and canon not in mapping:
                mapping[canon] = col
                used.add(col)
        # explicit mapping wins over aliases
        for canon, col in self.explicit.items():
            if canon in self.FIELDS and col in columns:
                mapping[canon] = col
                used.add(col)
        return MappingReport(mapping, [c for c in columns if c not in used])

    def to_flows(self, df) -> "tuple":
        """(flows DataFrame in CIC-style columns, report). Fields the source
        lacks are simply absent — build_windows zero-fills and reports them,
        which is the honest V1_COMPAT behavior."""
        import pandas as pd
        report = self.map_columns(list(df.columns))
        m = report.mapping
        out = pd.DataFrame(index=df.index)

        if "ts" not in m:
            raise UnknownSchemaError("no timestamp column found - map 'ts'")
        out["Timestamp"] = pd.to_datetime(df[m["ts"]], errors="coerce")
        bad = int(out["Timestamp"].isna().sum())
        if bad:
            raise AnalysisError(f"{bad}/{len(out)} timestamps unparseable")
        out["Label"] = (df[m["label"]].astype(str) if "label" in m
                        else "Benign")           # labels absent → benign-supervision
        for canon, cic in (("src_ip", "Src IP"), ("dst_ip", "Dst IP"),
                           ("src_port", "Src Port"), ("dst_port", "Dst Port"),
                           ("proto", "Protocol")):
            if canon in m:
                out[cic] = df[m[canon]]
        if "bytes" in m:
            out["TotLen Fwd Pkts"] = pd.to_numeric(df[m["bytes"]],
                                                   errors="coerce").fillna(0.0)
        if "pkts" in m:
            out["Tot Fwd Pkts"] = pd.to_numeric(df[m["pkts"]],
                                                errors="coerce").fillna(0.0)
        if "duration" in m:                     # assume seconds → CIC µs
            out["Flow Duration"] = (pd.to_numeric(df[m["duration"]],
                                                  errors="coerce")
                                    .fillna(0.0) * 1e6)
        return out, report


# ================================================================ analysis

def analyze_file(path: str | Path, forecaster,
                 evidence_engine=None, ds_engine=None,
                 bin_secs: int = BIN_SECS) -> dict:
    """The whole §29 pipeline for one uploaded file. Raises UnknownSchemaError
    (ask the user to map columns) or AnalysisError (parse/analysis failure);
    everything else is a normal honest record."""
    from src.features.window_builder import SEQ_LEN, WINDOW_FEATURES

    det = detect_format(path)

    if det["format"] in ("pcap", "pcapng"):
        windows, unavailable = _pcap_windows(path, bin_secs)
        n_rows = len(windows)
    else:
        windows, unavailable, n_rows = _csv_windows(path, det)

    if len(windows) < SEQ_LEN:
        raise AnalysisError(
            f"only {len(windows)} windows after binning - need >= {SEQ_LEN} "
            f"({SEQ_LEN * bin_secs}s of traffic) for a forecast")

    # ---- same conditioning as the live path: IP features zeroed, ratios
    # clamped to the training p99 (the model's validated input domain) ----
    seq_rows = [{"features": {n: w.get(n, 0.0) for n in WINDOW_FEATURES}}
                for w in windows]
    from src.live.history import model_matrix
    X = np.stack([model_matrix(seq_rows[i - SEQ_LEN + 1:i + 1])
                  for i in range(SEQ_LEN - 1, len(seq_rows))])

    trajectory, latest, latest_seq = [], None, None
    for i in range(SEQ_LEN - 1, len(seq_rows)):
        res = forecaster.predict(X[i - (SEQ_LEN - 1)])
        w = windows[i]
        rec = {"ts": w.get("ts"), "probs": res["probs"],
               "peak": max(res["probs"]), "stage": res["stage"]}
        trajectory.append(rec)
        latest = rec | {"threshold": res["threshold"],
                        "crossing_step": next((k + 1 for k, p
                                               in enumerate(res["probs"])
                                               if p >= res["threshold"]), None)}
        latest_seq = X[i - (SEQ_LEN - 1)]

    out = {
        "file": Path(path).name,
        "detection": det,
        "bin_secs": bin_secs,
        "n_flows_or_packets": n_rows,
        "n_windows": len(windows),
        "n_forecasts": len(trajectory),
        "unavailable_features": unavailable,       # honest, never silent zeros
        "trajectory": trajectory,
        "latest": latest,
    }

    # ---- optional enrichments, each degrading to None on absence --------
    if latest_seq is not None:
        try:
            from src.explainability.uncertainty import mc_dropout_forecast
            out["uncertainty"] = mc_dropout_forecast(
                forecaster.model, latest_seq, T=16, seed=0)
        except Exception:                             # noqa: BLE001
            out["uncertainty"] = None                 # optional, never fatal

        if evidence_engine is not None:
            try:
                from src.explainability.attribution import \
                    integrated_gradients_attribution
                attrs = integrated_gradients_attribution(
                    forecaster.model, forecaster.scaled(latest_seq))
                # model_matrix conditioned IP features to 0 — show the real
                # observed values in evidence, not the conditioning zeros
                raw_rows = seq_rows[-SEQ_LEN:]
                raw = np.asarray([[r["features"][n] for n in WINDOW_FEATURES]
                                  for r in raw_rows], dtype=np.float64)
                out["evidence"] = evidence_engine.explain(raw, attrs)
            except Exception:                         # noqa: BLE001
                out["evidence"] = None

    if ds_engine is not None and latest is not None:
        out["decision_support"] = ds_engine.assess(
            latest, uncertainty=out.get("uncertainty"),
            evidence=out.get("evidence"))
    return out


def _pcap_windows(path: Path, bin_secs: int) -> tuple[list[dict], list[str]]:
    """PCAP → per-bin window dicts with the 18 V1 features (extract_pcap
    already reuses the live packet pipeline — Phase 4)."""
    from src.features.canonical_schema import V1_ORDER
    from src.features.packet_features import extract_pcap
    slots_list = extract_pcap(path, bin_secs=bin_secs)
    windows = []
    for s in slots_list:
        w = {n: (s.get(n).value if s.get(n).available else 0.0)
             for n in V1_ORDER}
        w["ts"] = s.ts
        windows.append(w)
    # unavailable = a feature NO window in this file provided — slot-level
    # honesty, not a value-based guess (a true 0.0 is still "available")
    unavailable = sorted({n for n in V1_ORDER
                          if not any(s.get(n).available for s in slots_list)})
    return windows, unavailable


def _csv_windows(path: Path, det: dict) -> tuple[list[dict], list[str], int]:
    """CSV → window dicts via the audited build_windows (zero-fill + report)."""
    import pandas as pd
    from src.features.window_builder import (WINDOW_FEATURES, build_windows)

    if det["style"] == "cic-flow-csv":
        from src.ingestion.csv_loader import load_day_csv
        flows = load_day_csv(path, verbose=False)
        n_rows = len(flows)
    else:
        df = pd.read_csv(path, low_memory=False)
        n_rows = len(df)
        flows, _report = ColumnMapper().to_flows(df)
    wdf = build_windows(flows, bin_secs=BIN_SECS)
    windows = [{**{n: float(row[n]) for n in WINDOW_FEATURES},
                "ts": row.name.value / 1e9 if hasattr(row.name, "value")
                else None}
               for _, row in wdf.iterrows()]
    unavailable = [c for c in WINDOW_FEATURES if (wdf[c] == 0).all()]
    return windows, unavailable, n_rows
