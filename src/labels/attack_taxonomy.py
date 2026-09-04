"""Canonical attack taxonomy — one label space across all datasets.

Rule (plan §15): normalize every dataset-specific label into the canonical
taxonomy, but NEVER throw the original away. A window's label record is:

    {dataset_label, canonical_label, attack_family, dataset_id}

The canonical taxonomy aligns with MITRE ATT&CK tactics rather than any one
dataset's naming. `EXECUTION` is optional and currently unused — no dataset
we ingest labels execution behavior distinctly; it exists so a future dataset
can use it without a breaking change.

Mapping sources are explicit: every entry in CIC2018_FAMILY→CANONICAL is
verified against the dataset's own documentation + our verified per-day label
counts (configs/data_sources.yaml). Other datasets' tables are added ONLY
when their data is downloaded and their label values are read from real files.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- canonical taxonomy (stable order; indices are persisted in artifacts) ---

BENIGN = "BENIGN"
RECONNAISSANCE = "RECONNAISSANCE"
INITIAL_ACCESS = "INITIAL_ACCESS"
EXECUTION = "EXECUTION"                      # optional, currently unused
LATERAL_MOVEMENT = "LATERAL_MOVEMENT"
COMMAND_AND_CONTROL = "COMMAND_AND_CONTROL"
EXFILTRATION = "EXFILTRATION"
IMPACT = "IMPACT"                            # DoS/DDoS sit here
UNKNOWN_ATTACK = "UNKNOWN_ATTACK"

CANONICAL_STAGES = [
    BENIGN, RECONNAISSANCE, INITIAL_ACCESS, EXECUTION,
    LATERAL_MOVEMENT, COMMAND_AND_CONTROL, EXFILTRATION, IMPACT,
    UNKNOWN_ATTACK,
]
CANONICAL_INDEX = {s: i for i, s in enumerate(CANONICAL_STAGES)}

# Legacy V1 display names (src/attack_mapping/mitre_mapper.STAGES) → canonical.
# Kept so old artifacts and the current UI keep working during the transition.
LEGACY_TO_CANONICAL = {
    "Reconnaissance": RECONNAISSANCE,
    "Initial Access": INITIAL_ACCESS,
    "Lateral Movement": LATERAL_MOVEMENT,
    "Command & Control": COMMAND_AND_CONTROL,
    "Exfiltration": EXFILTRATION,
    "DoS": IMPACT,
    "": BENIGN,
}
CANONICAL_TO_LEGACY = {
    RECONNAISSANCE: "Reconnaissance",
    INITIAL_ACCESS: "Initial Access",
    LATERAL_MOVEMENT: "Lateral Movement",
    COMMAND_AND_CONTROL: "Command & Control",
    EXFILTRATION: "Exfiltration",
    IMPACT: "DoS",
    BENIGN: "",
    UNKNOWN_ATTACK: "",
}


@dataclass(frozen=True)
class LabelRecord:
    """What every window carries once adapters are done with it."""
    dataset_id: str
    dataset_label: str          # original, verbatim — never discarded
    canonical_label: str
    attack_family: str          # e.g. "FTP-Brute Force"; "benign" if none
    mapping_source: str         # "verified" | "manual/research" | "inferred"

    @property
    def is_attack(self) -> bool:
        return self.canonical_label not in (BENIGN,)


# --- CIC-IDS2018: verified family → canonical stage ---------------------------
# Derived from mitre_mapper.FAMILY_STAGE (whose rationale table is documented
# in that file) + the canonical renames. "DoS" legacy category → IMPACT.

CIC2018_FAMILY_CANONICAL: dict[str, str] = {
    "FTP-Brute Force": INITIAL_ACCESS,
    "SSH-Brute-Force": INITIAL_ACCESS,
    "Web-Brute Force": INITIAL_ACCESS,
    "XSS": INITIAL_ACCESS,
    "SQL-Injection": INITIAL_ACCESS,
    "Botnet-Ares": COMMAND_AND_CONTROL,
    "Heartbleed": EXFILTRATION,
    "Infiltration": LATERAL_MOVEMENT,
    "DoS-GoldenEye": IMPACT,
    "DoS-Hulk": IMPACT,
    "DoS-Slowhttptest": IMPACT,
    "DoS-Slowloris": IMPACT,
    "DDoS-LOIC": IMPACT,
    "DDoS-HOIC": IMPACT,
}


# --- UNSW-NB15: family → canonical stage --------------------------------------
# Label values verified from the actual main CSVs on disk (2026-09-04,
# 2,540,047 flows): NORMAL, Generic, Exploits, Fuzzers, DoS, Reconnaissance,
# Analysis, Backdoor, Shellcode, Backdoors (a spelling variant of Backdoor —
# 534 rows), Worms; Label ∈ {0,1} is perfectly consistent with attack_cat.
# The stage mapping itself follows the dataset's own category documentation
# (Moustafa & Slay 2015) — hence "manual/research", not "verified":
#   Reconnaissance → RECONNAISSANCE (the name says it)
#   Analysis       → RECONNAISSANCE (port scans / spam / html-file probes)
#   Fuzzers        → RECONNAISSANCE (vulnerability discovery via random input)
#   Backdoor(s)    → INITIAL_ACCESS (entry through a planted backdoor)
#   Exploits       → INITIAL_ACCESS (software exploit to gain access)
#   Shellcode      → EXECUTION (first real use of the EXECUTION stage)
#   Worms          → LATERAL_MOVEMENT (self-propagating spread)
#   DoS            → IMPACT (matches CIC2018's DoS → IMPACT)
#   Generic        → UNKNOWN_ATTACK (doc describes a block-cipher attack with
#                    no stage-attributable behavior — we refuse to guess)

UNSW_FAMILY_CANONICAL: dict[str, str] = {
    "Reconnaissance": RECONNAISSANCE,
    "Analysis": RECONNAISSANCE,
    "Fuzzers": RECONNAISSANCE,
    "Backdoor": INITIAL_ACCESS,
    "Backdoors": INITIAL_ACCESS,
    "Exploits": INITIAL_ACCESS,
    "Shellcode": EXECUTION,
    "Worms": LATERAL_MOVEMENT,
    "DoS": IMPACT,
    "Generic": UNKNOWN_ATTACK,
}


# --- CTU-13: label semantics verified from the real .binetflow files -------
# Every scenario's Label column was read on disk (2026-09-04). The universal
# attack marker is `From-Botnet-V<N>-...` (V42 in S1, V45 in S4, V46 in S5,
# V48 in S7, V49 in S8, V51 in S10/S12 — the V-number is the botnet "version",
# consistent within a family); everything else is `From-Normal-*`,
# `To-Background-*` or `Background*` — benign by the dataset's definition.
#
# Stage honesty: CTU-13 provides NO per-flow stage labels — only botnet vs
# normal vs background. All botnet flows therefore map to COMMAND_AND_CONTROL
# (a botnet is, by definition, a C2 architecture); we refuse to invent
# finer stage labels from behavior suffixes (SPAM/DNS/ICMP/CC-HTTP) because
# the dataset does not assert them. The scenario→family table is from the
# CTU-13 documentation (Garcia et al., Stratosphere IPS) — mapping_source
# "manual/research".

CTU13_SCENARIO_FAMILY: dict[int, str] = {
    1: "Neris", 2: "Neris", 9: "Neris",
    3: "Rbot", 4: "Rbot", 10: "Rbot", 11: "Rbot", 12: "Rbot",
    5: "Virut", 13: "Virut",
    6: "Menti", 7: "Sogou", 8: "Murlo",
}
CTU13_FAMILY_CANONICAL: dict[str, str] = {
    fam: COMMAND_AND_CONTROL for fam in set(CTU13_SCENARIO_FAMILY.values())
}


def canonicalize_ctu13(dataset_label: str, scenario: int | None) -> LabelRecord:
    """Map one CTU-13 binetflow Label onto the canonical taxonomy.

    `scenario` (1–13, from the capture directory) selects the documented
    botnet family; without it the family stays the verbatim "Botnet".
    """
    label = str(dataset_label).strip()
    if "Botnet" in label:
        fam = (CTU13_SCENARIO_FAMILY.get(int(scenario), "Botnet")
               if scenario is not None else "Botnet")
        return LabelRecord("ctu13", label,
                           CTU13_FAMILY_CANONICAL.get(fam, COMMAND_AND_CONTROL),
                           fam, "manual/research")
    # From-Normal-* / Background* / To-Background-* — benign, verified on disk
    return LabelRecord("ctu13", label, BENIGN, "benign", "verified")


def canonicalize(dataset_id: str, dataset_label: str) -> LabelRecord:
    """Map one dataset label onto the canonical taxonomy.

    Unknown attack labels are honestly UNKNOWN_ATTACK (never guessed into a
    stage they might not belong to); unknown benign spellings likewise stay
    BENIGN only for the exact benign sentinel of that dataset.
    """
    label = str(dataset_label).strip()
    if dataset_id == "cic2018":
        if label == "Benign":
            return LabelRecord(dataset_id, label, BENIGN, "benign", "verified")
        stage = CIC2018_FAMILY_CANONICAL.get(label)
        if stage is not None:
            return LabelRecord(dataset_id, label, stage, label, "verified")
        return LabelRecord(dataset_id, label, UNKNOWN_ATTACK, label, "inferred")
    if dataset_id == "unsw_nb15":
        # benign sentinel: the main CSVs leave attack_cat empty for normal
        # traffic (read as NaN) — "NORMAL" is the GT-file spelling.
        if label in ("", "NORMAL", "Normal"):
            return LabelRecord(dataset_id, "NORMAL", BENIGN, "benign", "verified")
        stage = UNSW_FAMILY_CANONICAL.get(label)
        if stage is not None:
            return LabelRecord(dataset_id, label, stage, label, "manual/research")
        return LabelRecord(dataset_id, label, UNKNOWN_ATTACK, label, "inferred")
    if dataset_id == "ctu13":
        # scenario-less fallback (the adapter passes the scenario for the
        # documented family; this path serves upload auto-detection)
        return canonicalize_ctu13(label, None)
    # Datasets not yet downloaded: refuse to guess. Their tables are added
    # when real files are in hand (see MASTER_IMPLEMENTATION_PLAN stop point).
    raise ValueError(
        f"no verified label mapping for dataset '{dataset_id}' — the dataset "
        "must be downloaded and its labels read from real files before "
        "mapping is defined (never guess a taxonomy mapping)"
    )


def map_legacy_stage(legacy: str) -> str:
    """V1 stage display name → canonical (for old artifacts)."""
    return LEGACY_TO_CANONICAL.get(legacy, UNKNOWN_ATTACK if legacy else BENIGN)
