"""Dataset adapter contract — every dataset enters the system through one of these.

Non-negotiables (DATA_CONTRACT.md):
- an adapter NEVER defines its own model input; it emits canonical
  `WindowSlots` whose availability comes from `canonical_schema`
- an adapter NEVER discards original labels; it emits `LabelRecord`s
- an adapter refuses to run on files it has not validated
- raw dataset files are read-only; processing outputs go elsewhere

Lifecycle (all methods are cheap to call independently — scripts and tests
use them piecemeal):

    discover(root)      → raw file paths under a download directory
    validate(files)     → schema check + confidence, BEFORE any training
    load(files)         → canonical flow records (see FLOW_COLUMNS)
    to_window_slots()   → per-bin canonical WindowSlots + LabelRecords
    attack_metadata()   → families, stages, scenario/time structure
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..features.canonical_schema import WindowSlots
from ..labels.attack_taxonomy import LabelRecord

# Canonical flow-record columns produced by load(). Anything an adapter's
# source cannot provide is absent (None / NaN) — never fabricated.
FLOW_COLUMNS = [
    "ts",                # normalized UTC timestamp
    "src_ip", "src_port", "dst_ip", "dst_port", "protocol",
    "duration_s", "pkts", "bytes",
    "fwd_pkts", "bwd_pkts", "fwd_bytes", "bwd_bytes",
    "iat_mean_s", "iat_std_s",
    "syn_cnt", "ack_cnt", "fin_cnt", "rst_cnt", "psh_cnt",
    "dataset_label",     # verbatim original label
]


@dataclass
class ValidationReport:
    ok: bool
    confidence: float                      # 0..1, schema-match confidence
    detected_format: str
    checks: dict[str, str] = field(default_factory=dict)   # name → verdict
    errors: list[str] = field(default_factory=list)


@dataclass
class AttackMetadata:
    """What we know about the attacks in a dataset, for the UI and mappings."""
    families: dict[str, str] = field(default_factory=dict)  # family → canonical stage
    n_flows: int = 0
    label_counts: dict[str, int] = field(default_factory=dict)
    time_range: tuple[str, str] | None = None
    scenarios: list[str] = field(default_factory=list)      # day/scenario ids


class DatasetAdapter(ABC):
    """One dataset = one adapter. Subclasses implement source-specific logic."""

    dataset_id: str = ""                   # e.g. "cic2018" — registry key
    name: str = ""
    version: str = ""
    source_url: str = ""
    modality: str = ""                     # "flow_csv" | "pcap" | "auth_events"
    requires_download: bool = True         # False once the user provides files

    # ------------------------------------------------------------------ info
    @abstractmethod
    def discover(self, root: Path) -> list[Path]:
        """Locate this dataset's raw files under `root`. Missing → empty list
        (the caller decides whether that is fatal)."""

    @abstractmethod
    def validate(self, files: list[Path]) -> ValidationReport:
        """Schema validation BEFORE load: columns, label column, timestamps.
        Reports a confidence so upload auto-detection can compare formats."""

    @abstractmethod
    def load(self, files: list[Path]) -> pd.DataFrame:
        """Raw files → canonical flow records (FLOW_COLUMNS + raw extras)."""

    # ---------------------------------------------------------------- windows
    @abstractmethod
    def to_window_slots(self, flows: pd.DataFrame, bin_secs: int
                        ) -> tuple[list[WindowSlots], list[LabelRecord]]:
        """Flow records → time-binned canonical feature slots + labels.
        One WindowSlots/LabelRecord pair per bin, chronological order.
        Availability MUST reflect what the source actually provides."""

    @abstractmethod
    def attack_metadata(self, flows: pd.DataFrame) -> AttackMetadata:
        """Families present, label counts, time range — for the Datasets UI."""

    # ------------------------------------------------------------ capabilities
    @property
    def capabilities(self) -> set[str]:
        from ..features.canonical_schema import DATASET_CAPABILITIES
        return set(DATASET_CAPABILITIES.get(self.dataset_id, set()))


class DatasetNotAvailableError(RuntimeError):
    """Raised by stub adapters whose dataset the user has not yet downloaded."""

    def __init__(self, dataset_id: str, url: str):
        super().__init__(
            f"dataset '{dataset_id}' is not downloaded yet. Download it from "
            f"{url} and place the files under data/raw/{dataset_id}/, then "
            "implement/enable its adapter (see MASTER_IMPLEMENTATION_PLAN.md "
            "stop point). Never train on guessed schemas."
        )
        self.dataset_id = dataset_id
        self.url = url
