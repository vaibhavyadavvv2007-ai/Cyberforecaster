"""Decision-support engine — one `assess()` from forecast to human action.

Consumes ONLY what the existing pipeline already produces (Phase 9 outputs):
  forecast    {probs, threshold, stage, crossing_step?, rule_stage?}
  uncertainty {confidence, max_std}            (MC-dropout; optional)
  evidence    [records from EvidenceEngine]     (optional)
  family      dataset label, when one is known  (upload/offline; optional)

Produces the decision-support record the UI renders:
  level + guidance + why, ranked recommendations, the ATT&CK mapping with
  real STIX mitigations/detections, and the human-in-the-loop statement.

Nothing here touches the network, the firewall, or the host. The engine's
entire output is advisory text with citations — rule 6 of the master plan.
"""
from __future__ import annotations

import time

from .levels import level_for
from .mitre import MitreKnowledge
from .recommendations import build as build_actions

HUMAN_IN_LOOP = ("Decision support only: the system has NOT blocked, isolated "
                 "or modified anything. Every action above is executed by a "
                 "human analyst who approves it.")


class DecisionSupportEngine:
    def __init__(self, knowledge: MitreKnowledge | None = None):
        self.knowledge = knowledge if knowledge is not None else MitreKnowledge.load()

    # ------------------------------------------------------------- assess
    def assess(self, forecast: dict, uncertainty: dict | None = None,
               evidence: list[dict] | None = None,
               family: str | None = None) -> dict:
        probs = forecast.get("probs") or []
        threshold = forecast.get("threshold")
        if not len(probs) or threshold is None:
            raise ValueError("forecast needs probs and threshold")
        stage = forecast.get("stage") or forecast.get("rule_stage")
        band = (uncertainty or {}).get("confidence")

        lvl = level_for(probs, threshold, band)

        # --- MITRE mapping: family-specific when a label is known, otherwise
        # the tactic-phase techniques for the predicted stage. When the STIX
        # index is missing we say so — no invented techniques (plan rule 4).
        mapping = {"knowledge_base": "unavailable"}
        if self.knowledge.available:
            techs = None
            if family:
                techs = self.knowledge.techniques_for_family(family)
            if not techs:
                techs = self.knowledge.techniques_for_stage(stage)
            mapping = {
                "knowledge_base": "mitre-attack enterprise (STIX)",
                "stage": stage,
                "family": family,
                "techniques": techs or [],
            }

        actions = build_actions(lvl["level"], band, stage, evidence,
                                mapping.get("techniques"))

        return {
            "ts": time.time(),
            "level": lvl["level"],
            "level_why": lvl["why"],
            "level_facts": lvl["facts"],
            "guidance": lvl["guidance"],
            "recommendations": actions,
            "mitre": mapping,
            "human_in_loop": HUMAN_IN_LOOP,
        }
