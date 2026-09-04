"""Dataset registry — dataset_id in, adapter out. One place to ask
"what can we train on today?".

Adapters for datasets that are not yet downloaded register as PENDING: they
carry metadata (URL, expected modality) but refuse to discover/load until the
user provides the files. This is deliberate — see MASTER_IMPLEMENTATION_PLAN
stop point. Never remove a pending stub to "unblock" training.
"""
from __future__ import annotations

from pathlib import Path

from .base import DatasetAdapter, DatasetNotAvailableError

# ---------------------------------------------------------------------------


class PendingAdapter(DatasetAdapter):
    """A dataset we have committed to supporting but do not have on disk.
    Every data-touching method raises; metadata methods answer."""

    def __init__(self) -> None:
        if not self.dataset_id:
            raise TypeError("PendingAdapter subclass must set dataset_id")

    def _unavailable(self) -> DatasetNotAvailableError:
        return DatasetNotAvailableError(self.dataset_id, self.source_url)

    def discover(self, root: Path) -> list[Path]:
        # honest probe: if the user HAS placed files, say so (non-empty list),
        # so the integration script can detect "downloaded but not wired up"
        root = Path(root)
        sub = root / self.dataset_id
        if sub.is_dir():
            return sorted(p for p in sub.rglob("*") if p.suffix.lower()
                          in {".csv", ".pcap", ".pcapng", ".parquet", ".zip"})
        return []

    def validate(self, files):
        raise self._unavailable()

    def load(self, files):
        raise self._unavailable()

    def to_window_slots(self, flows, bin_secs=30):
        raise self._unavailable()

    def attack_metadata(self, flows):
        raise self._unavailable()


class CIC2017Pending(PendingAdapter):
    dataset_id = "cic2017"
    name = "CIC-IDS2017"
    version = "2017 (GeneratedLabelledFlows / PCAPs)"
    source_url = "https://www.unb.ca/cic/datasets/ids-2017.html"
    modality = "flow_csv"


class CICIoT2023Pending(PendingAdapter):
    dataset_id = "ciciot2023"
    name = "CICIoT2023"
    version = "2023 IoT attacks (PCAP + CSV)"
    source_url = "https://www.unb.ca/cic/datasets/iotdataset.html"
    modality = "flow_csv"


class DARPAPending(PendingAdapter):
    dataset_id = "darpa"
    name = "DARPA/MIT-LL IDS"
    version = "1998/1999/2000 evaluation datasets"
    source_url = "https://www.ll.mit.edu/r-d/datasets"
    modality = "pcap"


class LANLPending(PendingAdapter):
    dataset_id = "lanl"
    name = "LANL cyber-authentication"
    version = "9 months of auth events — AUXILIARY modality, not flow data"
    source_url = "https://github.com/llnl/lanl-auth-dataset/"
    modality = "auth_events"


# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[DatasetAdapter]] = {}


def register(cls: type[DatasetAdapter]) -> type[DatasetAdapter]:
    _REGISTRY[cls.dataset_id] = cls
    return cls


def get_adapter(dataset_id: str) -> DatasetAdapter:
    if dataset_id not in _REGISTRY:
        raise KeyError(f"unknown dataset_id '{dataset_id}' "
                       f"(registered: {sorted(_REGISTRY)})")
    return _REGISTRY[dataset_id]()


def registered() -> list[str]:
    return sorted(_REGISTRY)


def status(dataset_id: str, root: Path = Path("data/raw")) -> str:
    """READY / PENDING (files present) / NOT_DOWNLOADED — for the Datasets UI."""
    a = get_adapter(dataset_id)
    files = a.discover(root)
    if isinstance(a, PendingAdapter):
        return "PENDING_WIRING" if files else "NOT_DOWNLOADED"
    return "READY" if files else "NOT_DOWNLOADED"


# Register: implemented first, pending stubs after (registry order = trust order)
from .cic2018 import CIC2018Adapter  # noqa: E402
from .ctu13 import CTU13Adapter  # noqa: E402
from .unsw_nb15 import UNSWNB15Adapter  # noqa: E402

register(CIC2018Adapter)
register(CTU13Adapter)
register(UNSWNB15Adapter)
register(CIC2017Pending)
register(CICIoT2023Pending)
register(DARPAPending)
register(LANLPending)
