"""CTU-13 adapter — bidirectional NetFlow from the Stratosphere IPS lab.

Files verified on disk 2026-09-04 (extracted from CTU-13-Dataset.tar.bz2 into
data/raw/ctu13/CTU-13-Dataset/<scenario>/capture*.binetflow, read-only):
13 scenarios, each a different botnet infection captured on the CTU
university network (Aug 2011), shipped as Argus bidirectional NetFlow with
REAL IP addresses — a third capture modality next to CIC2018's per-host
flow CSVs and UNSW's research flows.

Schema verified from the real files (every scenario's header is identical):
  StartTime,Dur,Proto,SrcAddr,Sport,Dir,DstAddr,Dport,State,sTos,dTos,
  TotPkts,TotBytes,SrcBytes,Label
  - StartTime "2011/08/10 09:46:59.607825" (local capture time)
  - Dir ∈ {"<->", "->", "<-", "?>", "<?", "<?>", "who"} — bidirectional rows
    dominate; direction is explicit, unlike CIC2018/UNSW
  - Sport/Dport are decimal OR hex ("0x0303") for the ICMP-era rows
  - State is a per-flow Argus TCP-state string (CON, FSPA_FSPA, S_RA, …) —
    it encodes handshake state, NOT packet counts
  - Label: "flow=From-Botnet-V<N>-..." (attack), "flow=From-Normal-V42-*",
    "flow=Background*" / "flow=To-Background-*" (benign) — read from every
    scenario's real label distribution before writing any mapping

What this source provides (all verified from the real files):
  ✓ 11 of the legacy 18 V1 features — INCLUDING unique_src_ips /
    unique_dst_ips and the full address/port group (real IPs, real ports)
  ✓ duration_std, src_port_entropy, flow_rate, packet_rate (extras)
  ✓ all Group-G service ratios (port-based, canonical definitions)
  ✓ fwd/bwd byte split: SrcBytes vs TotBytes-SrcBytes → down_up_ratio
  ✗ NO TCP flag counts: Argus State strings describe per-flow handshake
    state, not packets — syn/ack/fin/rst/push ratios are honestly UNAVAILABLE
    (same refusal as UNSW's synack/ackdat trap; mixing flow-state shares with
    CIC2018's packet-count ratios would pretend two semantics are one)
  ✗ NO inter-arrival statistics: no IAT columns — iat_mean/iat_std/max
    unavailable
  ✗ NO packet internals (TTL, window, payload, fragments) — Group E empty

Memory note: the 13 scenarios total >15M flows. load() is safe per file; the
multi-dataset build processes one scenario at a time (see
scripts/build_dataset_windows.py) rather than concatenating all scenarios.

Label honesty: CTU-13 provides no per-flow stage labels — every botnet flow
maps to COMMAND_AND_CONTROL (a botnet IS a C2 architecture) with the
documented scenario family (Neris/Rbot/Virut/Menti/Sogou/Murlo); see
src/labels/attack_taxonomy.py for the verified label semantics.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..features.canonical_schema import WindowSlots
from ..labels.attack_taxonomy import (LabelRecord,
                                      canonicalize_ctu13)
from .base import AttackMetadata, DatasetAdapter, ValidationReport

# The 15 columns, in file order — verified identical in every scenario file.
BINETFLOW_COLUMNS = [
    "StartTime", "Dur", "Proto", "SrcAddr", "Sport", "Dir", "DstAddr",
    "Dport", "State", "sTos", "dTos", "TotPkts", "TotBytes", "SrcBytes",
    "Label",
]
USECOLS = ["StartTime", "Dur", "Proto", "SrcAddr", "Sport", "Dir", "DstAddr",
           "Dport", "TotPkts", "TotBytes", "SrcBytes", "Label"]

SOURCE = "ctu13_binetflow"
_SERVICE_PORTS = {
    "http_ratio": {80, 8080}, "dns_ratio": {53}, "ssh_ratio": {22},
    "rdp_ratio": {3389}, "smb_ratio": {445}, "ftp_ratio": {20, 21},
}
_AUTH_PORTS = {21, 22, 23, 3389}
_BENIGN = {"BENIGN"}


def _port_to_num(s: pd.Series) -> pd.Series:
    """Binetflow ports are decimal or hex ('0x0303'); anything else → NaN."""
    s = s.astype(str).str.strip()
    hexmask = s.str.startswith("0x", na=False)
    out = pd.to_numeric(s, errors="coerce")
    if hexmask.any():
        hexvals = s[hexmask].str.slice(2).apply(
            lambda t: int(t, 16) if t else None)
        out = out.mask(hexmask, pd.to_numeric(hexvals, errors="coerce"))
    return out


def _entropy(counts: pd.Series) -> float:
    """Shannon entropy over category counts (nats→bits via log2)."""
    c = counts.astype(float).to_numpy()
    c = c[c > 0]
    if len(c) <= 1:
        return 0.0
    p = c / c.sum()
    return float(-(p * np.log2(p)).sum())


def scenario_of(path: Path) -> int | None:
    """Scenario number 1–13 from the capture's parent directory name."""
    try:
        return int(Path(path).parent.name)
    except ValueError:
        return None


class CTU13Adapter(DatasetAdapter):
    dataset_id = "ctu13"
    name = "CTU-13"
    version = ("13 botnet scenarios (Stratosphere IPS, Aug 2011, "
               "bidirectional Argus NetFlow with real IPs)")
    source_url = "https://www.stratosphereips.org/datasets-ctu13"
    modality = "flow_csv"

    # -------------------------------------------------------------- discover
    def discover(self, root: Path) -> list[Path]:
        """Every scenario's .binetflow file, sorted by scenario number.
        Bro logs / pcaps in the archive are NOT training inputs and must not
        make a partial download look complete."""
        root = Path(root)
        sub = root / self.dataset_id
        if not sub.is_dir():
            return []
        found = [p for p in sub.rglob("*.binetflow") if scenario_of(p) is not None]
        return sorted(found, key=lambda p: (scenario_of(p) or 0, p.name))

    # -------------------------------------------------------------- validate
    def validate(self, files: list[Path]) -> ValidationReport:
        if not files:
            return ValidationReport(False, 0.0, "none",
                                    errors=["no .binetflow files found"])
        checks: dict[str, str] = {}
        errors: list[str] = []
        try:
            head = pd.read_csv(files[0], nrows=100, usecols=USECOLS,
                               dtype={"Proto": str, "SrcAddr": str,
                                      "DstAddr": str, "Dir": str,
                                      "Label": str})
        except Exception as exc:  # noqa: BLE001 — report, never crash
            return ValidationReport(False, 0.0, "unreadable binetflow",
                                    errors=[f"{type(exc).__name__}: {exc}"])

        checks["header_15_columns"] = "OK" if len(head.columns) == len(
            USECOLS) else "column mismatch"
        ts = pd.to_datetime(head["StartTime"], format="mixed", errors="coerce")
        n_bad_ts = int(ts.isna().sum())
        checks["starttime_parseable"] = "OK" if n_bad_ts == 0 \
            else f"{n_bad_ts} unparseable"
        n_bad_num = int(pd.to_numeric(head["TotPkts"], errors="coerce")
                        .isna().sum())
        checks["totpkts_numeric"] = "OK" if n_bad_num == 0 \
            else f"{n_bad_num} unparseable"
        # Botnet flows are RARE and arrive late: in scenario 1 the first
        # From-Botnet line is ~675k rows in, so a 100-row head sample can
        # never see it. Scan the Label column in chunks (stop at first hit,
        # cap at 2M rows) instead of trusting the head.
        has_botnet = False
        try:
            scanned = 0
            for chunk in pd.read_csv(files[0], usecols=["Label"],
                                     dtype={"Label": str},
                                     chunksize=250_000):
                if chunk["Label"].str.contains("Botnet", na=False).any():
                    has_botnet = True
                    break
                scanned += len(chunk)
                if scanned >= 2_000_000:
                    break
        except Exception:  # noqa: BLE001 — fall back to the head sample
            has_botnet = head["Label"].str.contains("Botnet", na=False).any()
        checks["attack_marker_present"] = "OK" if has_botnet \
            else "no From-Botnet labels in first 2M rows"
        n_files = len(files)
        checks["scenarios"] = f"OK (13/13)" if n_files == 13 \
            else f"partial {n_files}/13"
        scenarios = {scenario_of(p) for p in files}
        checks["scenario_dirs"] = "OK" if None not in scenarios \
            else "file outside a numbered scenario directory"

        n_ok = sum(1 for v in checks.values() if v.startswith("OK"))
        ok = (n_bad_ts == 0 and n_bad_num == 0 and has_botnet
              and n_files == 13 and None not in scenarios)
        if not ok:
            errors = [f"{k}: {v}" for k, v in checks.items()
                      if not v.startswith("OK")]
        return ValidationReport(
            ok=ok, confidence=round(n_ok / len(checks), 3),
            detected_format="CTU-13 binetflow (Argus, 15 columns)",
            checks=checks, errors=errors)

    # ------------------------------------------------------------------ load
    def load(self, files: list[Path]) -> pd.DataFrame:
        """binetflow files → canonical flow records + raw extras.

        Timestamps are naive capture-local (CTU-13 documents no zone); they
        are localized as UTC-annotated naive → tz-aware so the sequence
        engine's datetime math is uniform across datasets. Scenario ordering,
        not absolute wall-clock, is what the per-scenario splits use.
        """
        frames = []
        for p in files:
            df = pd.read_csv(p, usecols=USECOLS,
                             dtype={"Proto": str, "SrcAddr": str,
                                    "DstAddr": str, "Dir": str, "Label": str},
                             low_memory=False)
            df["scenario"] = scenario_of(p)
            frames.append(df)
        raw = pd.concat(frames, ignore_index=True)
        raw = raw.sort_values("StartTime", kind="mergesort").reset_index(drop=True)

        tot_b = pd.to_numeric(raw["TotBytes"], errors="coerce")
        src_b = pd.to_numeric(raw["SrcBytes"], errors="coerce")
        fwd = src_b.clip(lower=0)
        # bwd = total − src, floored at 0 (unidirectional rows: TotBytes==SrcBytes)
        bwd = (tot_b - fwd).clip(lower=0)

        out = pd.DataFrame({
            "ts": pd.to_datetime(raw["StartTime"], format="mixed",
                                 errors="coerce", utc=True),
            "src_ip": raw["SrcAddr"], "src_port": _port_to_num(raw["Sport"]),
            "dst_ip": raw["DstAddr"], "dst_port": _port_to_num(raw["Dport"]),
            "protocol": raw["Proto"],
            "duration_s": pd.to_numeric(raw["Dur"], errors="coerce"),
            "pkts": pd.to_numeric(raw["TotPkts"], errors="coerce"),
            "bytes": tot_b,
            "fwd_pkts": np.nan, "bwd_pkts": np.nan,      # not in binetflow
            "fwd_bytes": fwd, "bwd_bytes": bwd,
            "iat_mean_s": np.nan, "iat_std_s": np.nan,   # no IAT columns
            "syn_cnt": np.nan, "ack_cnt": np.nan, "fin_cnt": np.nan,
            "rst_cnt": np.nan, "psh_cnt": np.nan,        # state ≠ flag counts
            "dataset_label": raw["Label"].fillna("").str.strip(),
        })
        # raw extras for to_window_slots
        for col in ("Dir", "scenario"):
            out[col] = raw[col]
        return out

    # --------------------------------------------------------------- windows
    def to_window_slots(self, flows: pd.DataFrame, bin_secs: int = 30
                        ) -> tuple[list[WindowSlots], list[LabelRecord]]:
        """Per-scenario time bins — scenarios sharing a calendar date
        (e.g. S4 and S5 both Aug 15) must NEVER merge into one bin."""
        df = flows.copy()
        df = df[df["ts"].notna()]
        df = df.assign(bin=df["ts"].dt.floor(f"{bin_secs}s"))
        df = df.sort_values(["scenario", "ts"], kind="mergesort")

        slots: list[WindowSlots] = []
        labels: list[LabelRecord] = []
        for (scen, bin_ts), g in df.groupby(["scenario", "bin"], sort=True):
            ws = WindowSlots(source=SOURCE, ts=bin_ts.timestamp())

            pkts = g["pkts"].to_numpy(dtype=float)
            byts = (g["fwd_bytes"].to_numpy(dtype=float)
                    + g["bwd_bytes"].to_numpy(dtype=float))
            dur = g["duration_s"].to_numpy(dtype=float)

            ws.set("flow_count", float(len(g)), SOURCE)
            ws.set("bytes_total", float(np.nansum(byts)), SOURCE)
            ws.set("pkts_total", float(np.nansum(pkts)), SOURCE)
            d = dur[~np.isnan(dur)]
            if len(d):
                ws.set("duration_mean", float(d.mean()), SOURCE)
                if len(d) > 1:
                    ws.set("duration_std", float(d.std()), SOURCE)
            nz = pkts > 0
            if nz.any():
                ws.set("avg_pkt_size",
                       float(np.mean(byts[nz] / pkts[nz])), SOURCE)
            pos = g["fwd_bytes"].to_numpy(dtype=float) > 0
            if pos.any():
                ws.set("down_up_ratio",
                       float(np.mean(g["bwd_bytes"].to_numpy(dtype=float)[pos]
                                     / g["fwd_bytes"].to_numpy(dtype=float)[pos])),
                       SOURCE)

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
            # syn/ack/fin/rst/push ratios (State ≠ counts), IAT stats,
            # inbound/outbound (needs a vantage-point definition CTU-13 does
            # not give), every Group-E packet internal: UNAVAILABLE — see the
            # module docstring. Never zero-filled.

            slots.append(ws)

            # dominant ORIGINAL label per bin; scenario → documented family
            lab = str(g["dataset_label"].value_counts().index[0])
            labels.append(canonicalize_ctu13(lab, scen))
        return slots, labels

    # -------------------------------------------------------------- metadata
    def attack_metadata(self, flows: pd.DataFrame) -> AttackMetadata:
        from ..labels.attack_taxonomy import CTU13_SCENARIO_FAMILY
        scen_fams: dict[str, str] = {}
        for scen in sorted(set(flows["scenario"].dropna().astype(int))):
            fam = CTU13_SCENARIO_FAMILY.get(scen, "Unknown-Botnet")
            scen_fams[f"S{scen} ({fam})"] = "COMMAND_AND_CONTROL"
        is_atk = flows["dataset_label"].str.contains("Botnet", na=False)
        counts = {"Botnet": int(is_atk.sum()),
                  "Benign (Normal/Background)": int((~is_atk).sum())}
        tr = (str(flows["ts"].min()), str(flows["ts"].max())) \
            if len(flows) else None
        return AttackMetadata(families=scen_fams, n_flows=int(len(flows)),
                              label_counts=counts, time_range=tr,
                              scenarios=sorted(
                                  f"S{s}" for s in
                                  set(flows["scenario"].dropna().astype(int))))
