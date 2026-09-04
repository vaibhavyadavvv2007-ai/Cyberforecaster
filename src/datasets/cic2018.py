"""CSE-CIC-IDS2018 adapter — the only fully-implemented adapter today.

Wraps the AUDITED, production-proven ingestion (src/ingestion/csv_loader.py)
and windowing (src/features/window_builder.py) rather than reimplementing
them — the multi-dataset layer must not fork the one implementation the
frozen baseline depends on.

What this source provides (verified 2026-09-04 audit, see
docs/AUDIT_BEFORE_MULTIDATASET.md §2):
  ✓ the 18 legacy features MINUS unique_src_ips/unique_dst_ips
    (the ML-ready CSVs ship no Src IP / Dst IP columns)
  ✗ nothing packet-level (flow aggregates only)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..features.canonical_schema import CIC2018_AVAILABLE, WindowSlots
from ..ingestion.csv_loader import CORE_COLS, load_many
from ..labels.attack_taxonomy import (BENIGN, LabelRecord,
                                      canonicalize, map_legacy_stage)
from ..features.window_builder import build_windows
from .base import AttackMetadata, DatasetAdapter, ValidationReport

REQUIRED_COLS = ("Timestamp", "Label", "Dst Port", "Flow Duration")
SOURCE = "cic_csv"


class CIC2018Adapter(DatasetAdapter):
    dataset_id = "cic2018"
    name = "CSE-CIC-IDS2018"
    version = "2018 (Processed Traffic Data for ML Algorithms)"
    source_url = "https://www.unb.ca/cic/datasets/ids-2018.html"
    modality = "flow_csv"

    # -------------------------------------------------------------- discover
    def discover(self, root: Path) -> list[Path]:
        """Accept either the flat historical layout (data/raw/*.csv) or a
        dedicated subdirectory (data/raw/cic2018/*.csv)."""
        root = Path(root)
        if (root / self.dataset_id).is_dir():
            return sorted((root / self.dataset_id).glob("*.csv"))
        return sorted(root.glob("*.csv"))

    # -------------------------------------------------------------- validate
    def validate(self, files: list[Path]) -> ValidationReport:
        if not files:
            return ValidationReport(False, 0.0, "none",
                                    errors=["no CSV files found"])
        try:
            head = pd.read_csv(files[0], nrows=2, low_memory=False)
        except Exception as exc:  # noqa: BLE001 — report, never crash
            return ValidationReport(False, 0.0, "unreadable CSV",
                                    errors=[f"{type(exc).__name__}: {exc}"])
        cols = {str(c).strip() for c in head.columns}
        missing_req = [c for c in REQUIRED_COLS if c not in cols]
        core_present = sum(1 for c in CORE_COLS if c in cols)
        confidence = round(core_present / len(CORE_COLS), 3)
        ok = not missing_req and confidence >= 0.7
        return ValidationReport(
            ok=ok, confidence=confidence,
            detected_format="CIC-style flow CSV (CICFlowMeter)",
            checks={
                "required_columns": "OK" if not missing_req
                else f"missing {missing_req}",
                "core_column_overlap": f"{core_present}/{len(CORE_COLS)}",
                "files": str(len(files)),
            },
            errors=[f"missing required columns: {missing_req}"] if missing_req else [],
        )

    # ------------------------------------------------------------------ load
    def load(self, files: list[Path]) -> pd.DataFrame:
        return load_many(list(files))

    # --------------------------------------------------------------- windows
    def to_window_slots(self, flows: pd.DataFrame, bin_secs: int = 30
                        ) -> tuple[list[WindowSlots], list[LabelRecord]]:
        windows = build_windows(flows, bin_secs=bin_secs)

        # Dominant ORIGINAL label per bin — the audit trail the taxonomy
        # demands (dataset_label is never discarded). Ties → first by count.
        flows = flows.copy()
        flows["bin"] = flows["Timestamp"].dt.floor(f"{bin_secs}s")
        dominant = (flows.groupby("bin")["Label"]
                    .agg(lambda s: s.value_counts().index[0]))

        slots: list[WindowSlots] = []
        labels: list[LabelRecord] = []
        for bin_ts, row in windows.iterrows():
            ws = WindowSlots(source=SOURCE, ts=bin_ts.timestamp())
            for name in CIC2018_AVAILABLE:
                if name in windows.columns:
                    ws.set(name, float(row[name]), SOURCE)
            # unique_src_ips/unique_dst_ips stay absent — the CSVs have no
            # IP columns. This is the honest version of V1's zero-fill.
            slots.append(ws)

            fam = str(dominant.get(bin_ts, "Benign"))
            if fam == "Benign":
                labels.append(LabelRecord("cic2018", "Benign", BENIGN,
                                          "benign", "verified"))
            else:
                labels.append(canonicalize("cic2018", fam))
        return slots, labels

    # -------------------------------------------------------------- metadata
    def attack_metadata(self, flows: pd.DataFrame) -> AttackMetadata:
        counts = flows["Label"].value_counts().to_dict()
        fams = {f: canonicalize("cic2018", f).canonical_label
                for f in counts if f != "Benign"}
        tr = (str(flows["Timestamp"].min()), str(flows["Timestamp"].max())) \
            if len(flows) else None
        days = sorted({str(d) for d in flows["Timestamp"].dt.date})
        return AttackMetadata(families=fams, n_flows=int(len(flows)),
                              label_counts={k: int(v) for k, v in counts.items()},
                              time_range=tr, scenarios=days)


def _legacy_stage_to_canonical(stage_idx: int) -> str:
    """V1 dominant_stage_idx → canonical label (bridge for old artifacts)."""
    from ..attack_mapping.mitre_mapper import STAGES
    if 0 <= stage_idx < len(STAGES):
        return map_legacy_stage(STAGES[stage_idx])
    return BENIGN
