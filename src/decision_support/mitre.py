"""MITRE ATT&CK knowledge base — real STIX data, pre-digested.

Source of truth: the official MITRE STIX bundle (enterprise-attack.json,
~54 MB, downloaded to data/knowledge/mitre_attack/). This module turns it
ONCE into a compact index (mitre_index.json) holding only what the
decision-support engine needs:

  techniques      {TID: {name, tactic_phases, detection, mitigations[]}}
  by_phase        {att&ck phase_name: [TID, ...]}   (top-level techniques)

Two-layer mapping, both verifiable:
  1. CURATED_FAMILY_TECHNIQUES — the CIC2018 attack families this prototype
     was trained on, each mapped to the specific ATT&CK technique that
     describes it. Small, hand-checked, cited in the plan.
  2. STAGE_PHASE — our 6 canonical stages mapped to ATT&CK tactic phases;
     used when no family is known (live traffic has no labels): we return
     the ATT&CK techniques under that tactic.

Honesty rules (plan rule 4): if the STIX bundle or index is missing, every
query returns None and callers must show "knowledge base unavailable" —
never an invented technique or mitigation.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_BUNDLE = Path("data/knowledge/mitre_attack/enterprise-attack.json")
DEFAULT_INDEX = Path("data/knowledge/mitre_attack/mitre_index.json")

# Our 6 canonical stages (src.attack_mapping.mitre_mapper.STAGES) → ATT&CK
# tactic phase names used in kill_chain_phases. DoS sits under ATT&CK Impact.
STAGE_PHASE = {
    "Reconnaissance": "reconnaissance",
    "Initial Access": "initial-access",
    "Lateral Movement": "lateral-movement",
    "Command & Control": "command-and-control",
    "Exfiltration": "exfiltration",
    "DoS": "impact",
}

# Family → specific technique (the dataset ground truth we actually train on).
# Verified against the STIX bundle by tests/test_decision_support.py.
CURATED_FAMILY_TECHNIQUES = {
    "FTP-Brute Force": ["T1110"],          # Brute Force
    "SSH-Brute-Force": ["T1110"],
    "Web-Brute Force": ["T1110"],
    "XSS": ["T1190"],                      # Exploit Public-Facing Application
    "SQL-Injection": ["T1190"],
    "Heartbleed": ["T1190", "T1005"],      # public-app exploit + memory read
    "Botnet-Ares": ["T1071"],              # Application Layer Protocol (C2)
    "Infiltration": ["T1021"],             # Remote Services (DMZ pivot)
    "DoS-GoldenEye": ["T1498"],            # Network Denial of Service
    "DoS-Hulk": ["T1498"],
    "DoS-Slowhttptest": ["T1498"],
    "DoS-Slowloris": ["T1498"],
    "DDoS-LOIC": ["T1498"],
    "DDoS-HOIC": ["T1498"],
}


# ------------------------------------------------------------------ builder

def build_index(bundle_path: Path = DEFAULT_BUNDLE,
                index_path: Path = DEFAULT_INDEX) -> dict:
    """STIX bundle → compact index. Run once (`python -m src.decision_support.mitre`);
    the runtime never loads the 54 MB bundle."""
    objs = json.loads(Path(bundle_path).read_text(encoding="utf-8"))["objects"]

    techniques, phases = {}, {}
    for o in objs:
        if o.get("type") != "attack-pattern" or o.get("revoked", False):
            continue
        tid = next((r["external_id"] for r in o.get("external_references", [])
                    if r.get("source_name") == "mitre-attack"
                    and r.get("external_id", "").startswith("T")), None)
        if tid is None:
            continue
        technique_phases = sorted(
            p["phase_name"] for p in o.get("kill_chain_phases", [])
            if p.get("kill_chain_name") == "mitre-attack")
        for ph in technique_phases:
            phases.setdefault(ph, []).append(tid)
        techniques[tid] = {
            "name": o.get("name", ""),
            "tactic_phases": technique_phases,
            "x_mitre_is_subtechnique": bool(o.get("x_mitre_is_subtechnique", False)),
            "detection": (o.get("x_mitre_detection") or "").strip() or None,
            "mitigations": [],           # filled from relationships below
        }

    # relationship course-of-action —mitigates→ attack-pattern: match by
    # exact STIX id (source_ref of the COA, target_ref of the technique)
    stid_to_tid = {}
    for o in objs:
        if o.get("type") == "attack-pattern":
            tid = next((r["external_id"] for r in o.get("external_references", [])
                        if r.get("source_name") == "mitre-attack"
                        and r.get("external_id", "").startswith("T")), None)
            if tid and tid in techniques:
                stid_to_tid[o["id"]] = tid
    coa_names = {o["id"]: o.get("name", "") for o in objs
                 if o.get("type") == "course-of-action"}
    for o in objs:
        if o.get("type") != "relationship" or o.get("relationship_type") != "mitigates":
            continue
        tid = stid_to_tid.get(o.get("target_ref", ""))
        coa = coa_names.get(o.get("source_ref", ""))
        if tid and coa:
            techniques[tid]["mitigations"].append(coa)
    for t in techniques.values():
        t["mitigations"] = sorted(set(t["mitigations"]))

    index = {
        "source": "mitre-attack/attack-stix-data enterprise-attack (official)",
        "n_techniques": len(techniques),
        "n_phases": len(phases),
        "techniques": techniques,
        "by_phase": phases,
    }
    Path(index_path).write_text(json.dumps(index), encoding="utf-8")
    return index


# ------------------------------------------------------------------ runtime

class MitreKnowledge:
    """Read-only queries over the compact index. `available=False` when the
    index is missing — callers must surface that, not guess."""

    def __init__(self, index: dict | None = None):
        self.index = index
        self.available = index is not None

    @classmethod
    def load(cls, index_path: str | Path = DEFAULT_INDEX) -> "MitreKnowledge":
        p = Path(index_path)
        if not p.exists():
            return cls(None)
        return cls(json.loads(p.read_text(encoding="utf-8")))

    # ------------------------------------------------------------ queries
    def technique(self, tid: str) -> dict | None:
        if not self.available:
            return None
        t = self.index["techniques"].get(tid)
        if t is None:
            return None
        return {"id": tid, "name": t["name"],
                "detection": t.get("detection"),
                "mitigations": t.get("mitigations", [])[:5]}

    def techniques_for_stage(self, stage: str, limit: int = 8) -> list[dict] | None:
        """Stage → ATT&CK techniques under its tactic phase."""
        if not self.available:
            return None
        phase = STAGE_PHASE.get(stage)
        if phase is None:
            return []
        tids = [t for t in self.index["by_phase"].get(phase, [])
                if not self.index["techniques"][t]["x_mitre_is_subtechnique"]]
        out = []
        for tid in sorted(tids)[:limit]:
            t = self.index["techniques"][tid]
            out.append({"id": tid, "name": t["name"],
                        "detection": t.get("detection"),
                        "mitigations": t.get("mitigations", [])[:3]})
        return out

    def techniques_for_family(self, family: str) -> list[dict] | None:
        """Dataset family → curated specific techniques."""
        if not self.available:
            return None
        return [self.technique(tid)          # type: ignore[misc]
                for tid in CURATED_FAMILY_TECHNIQUES.get(family, [])]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="build the compact MITRE index")
    ap.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    ap.add_argument("--out", type=Path, default=DEFAULT_INDEX)
    a = ap.parse_args()
    idx = build_index(a.bundle, a.out)
    print(f"index: {idx['n_techniques']} techniques, {idx['n_phases']} phases -> {a.out}")
