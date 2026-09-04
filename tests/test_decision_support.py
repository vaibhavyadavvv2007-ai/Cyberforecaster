"""Phase 10 tests — response levels, MITRE knowledge, recommendations, engine."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.decision_support.engine import DecisionSupportEngine
from src.decision_support.levels import level_for
from src.decision_support.mitre import (CURATED_FAMILY_TECHNIQUES,
                                        MitreKnowledge, build_index)
from src.decision_support.recommendations import (build as build_actions,
                                                  rank)

THR = 0.5612          # the frozen V1 threshold — tests use the real one


# ------------------------------------------------------------------ levels

def test_level_monitor_when_below_threshold():
    r = level_for([0.1, 0.2, 0.3, 0.4, 0.5], THR, "HIGH")
    assert r["level"] == "MONITOR"
    assert r["facts"]["crossing_step"] is None and r["facts"]["steps_above"] == 0


def test_level_investigate_on_distant_crossing():
    r = level_for([0.2, 0.3, 0.4, 0.7, 0.8], THR, "HIGH")
    assert r["level"] == "INVESTIGATE"
    assert r["facts"]["crossing_step"] == 4


def test_level_investigate_on_low_confidence_even_if_near():
    r = level_for([0.9, 0.9, 0.9, 0.9, 0.9], THR, "LOW")
    assert r["level"] == "INVESTIGATE"
    assert "MC-dropout" in r["why"]


def test_level_escalate_near_sustained_high():
    r = level_for([0.7, 0.8, 0.9, 0.9, 0.8], THR, "HIGH")
    assert r["level"] == "ESCALATE"
    assert r["facts"]["steps_above"] == 5


def test_level_containment_review_near_but_not_sustained():
    # crossing step 1 but only 2/5 above and MEDIUM band
    r = level_for([0.8, 0.7, 0.2, 0.1, 0.1], THR, "MEDIUM")
    assert r["level"] == "CONTAINMENT REVIEW"


def test_level_none_confidence_treated_as_medium_never_high():
    # without MC results the engine must not claim HIGH confidence:
    # sustained near crossing + unknown band -> CONTAINMENT REVIEW, not ESCALATE
    r = level_for([0.8, 0.8, 0.8, 0.8, 0.8], THR, None)
    assert r["level"] == "CONTAINMENT REVIEW"
    assert r["facts"]["confidence"] == "MEDIUM"


def test_level_empty_trajectory_raises():
    with pytest.raises(ValueError):
        level_for([], THR)


# ------------------------------------------------------------------- mitre

def test_knowledge_unavailable_when_index_missing(tmp_path):
    kb = MitreKnowledge.load(tmp_path / "nope.json")
    assert not kb.available
    assert kb.technique("T1110") is None
    assert kb.techniques_for_stage("DoS") is None       # None, never invented


@pytest.fixture(scope="module")
def kb() -> MitreKnowledge:
    k = MitreKnowledge.load()
    if not k.available:
        pytest.skip("MITRE index not built (run python -m src.decision_support.mitre)")
    return k


def test_every_curated_technique_exists_in_stix(kb):
    for fam, tids in CURATED_FAMILY_TECHNIQUES.items():
        for tid in tids:
            t = kb.technique(tid)
            assert t is not None, f"{fam} -> {tid} not in ATT&CK"
            assert t["name"], tid


def test_brute_force_family_maps_to_t1110_with_mitigations(kb):
    techs = kb.techniques_for_family("FTP-Brute Force")
    assert [t["id"] for t in techs] == ["T1110"]
    assert techs[0]["name"] == "Brute Force"
    assert len(techs[0]["mitigations"]) >= 1    # real STIX course-of-action


def test_stage_mapping_covers_all_six_stages(kb):
    from src.decision_support.mitre import STAGE_PHASE
    from src.attack_mapping.mitre_mapper import STAGES
    assert set(STAGE_PHASE) == set(STAGES)
    for stage in STAGES:
        techs = kb.techniques_for_stage(stage)
        assert techs, stage
        assert all(t["mitigations"] is not None for t in techs)
    # unknown stage -> empty list (a claim of nothing), not an error
    assert kb.techniques_for_stage("Nonsense Stage") == []


def test_dos_stage_maps_into_impact_tactic(kb):
    techs = kb.techniques_for_stage("DoS")
    tids = {t["id"] for t in techs}
    assert "T1498" in tids        # Network Denial of Service is reachable


def test_build_index_from_synthetic_bundle(tmp_path):
    """build_index must work from raw STIX alone — no dependence on the
    54 MB file having a particular download."""
    t1110 = {
        "type": "attack-pattern", "id": "attack-pattern--1",
        "name": "Brute Force", "x_mitre_detection": "Monitor auth logs.",
        "kill_chain_phases": [
            {"kill_chain_name": "mitre-attack", "phase_name": "credential-access"},
            {"kill_chain_name": "pre-attack", "phase_name": "ignore-me"},
        ],
        "external_references": [
            {"source_name": "mitre-attack", "external_id": "T1110"},
            {"source_name": "other", "external_id": "X9999"},   # not a TID
        ],
    }
    coa = {"type": "course-of-action", "id": "course-of-action--1",
           "name": "Strong Password Policy"}
    rev = {"type": "attack-pattern", "id": "attack-pattern--2",
           "name": "Revoked", "revoked": True,
           "external_references": [{"source_name": "mitre-attack",
                                    "external_id": "T0001"}]}
    rel = {"type": "relationship", "relationship_type": "mitigates",
           "source_ref": "course-of-action--1",
           "target_ref": "attack-pattern--1"}
    other = {"type": "relationship", "relationship_type": "uses",
             "source_ref": "x", "target_ref": "y"}
    bundle = tmp_path / "b.json"
    bundle.write_text(json.dumps(
        {"objects": [t1110, coa, rev, rel, other]}), encoding="utf-8")
    idx = build_index(bundle, tmp_path / "i.json")
    assert idx["n_techniques"] == 1                 # revoked + non-T skipped
    t = idx["techniques"]["T1110"]
    assert t["mitigations"] == ["Strong Password Policy"]
    assert t["detection"] == "Monitor auth logs."
    assert idx["by_phase"]["credential-access"] == ["T1110"]
    assert "ignore-me" not in idx["by_phase"]       # only mitre-attack phases


# ---------------------------------------------------------- recommendations

def test_evidence_actions_only_from_real_deviations():
    ev = [
        {"feature": "flow_count", "observed": 2000, "benign_mean": 687,
         "z": 8.1, "direction": "elevated", "attribution": 0.9,
         "benign_p99": 2269},
        {"feature": "syn_ratio", "observed": 0.5, "benign_mean": 0.4,
         "z": 1.0, "direction": "normal", "attribution": 0.5,
         "benign_p99": 0.9},                        # inside benign range
    ]
    acts = build_actions("INVESTIGATE", "MEDIUM", "Initial Access", ev, [])
    ev_acts = [a for a in acts if a["source"] == "evidence"]
    assert len(ev_acts) == 1                          # only the deviating row
    assert "flow_count" in ev_acts[0]["action"] and "z=8.1" in ev_acts[0]["action"]


def test_rank_is_stable_and_priority_ordered():
    acts = [
        {"priority": "P2", "source": "mitre", "action": "m"},
        {"priority": "P1", "source": "stage", "action": "s"},
        {"priority": "P1", "source": "evidence", "action": "e"},
        {"priority": "P3", "source": "verification", "action": "v"},
    ]
    assert [a["action"] for a in rank(acts)] == ["s", "e", "m", "v"]


def test_verification_only_when_not_escalating():
    v = [a for a in build_actions("ESCALATE", "HIGH", "DoS", None, [])
         if a["source"] == "verification"]
    assert v == []                                    # no wait-and-see at ESCALATE
    v2 = [a for a in build_actions("INVESTIGATE", "MEDIUM", "DoS", None, [])
          if a["source"] == "verification"]
    assert len(v2) == 1


# ------------------------------------------------------------------ engine

def test_engine_end_to_end_with_real_kb(kb):
    eng = DecisionSupportEngine(kb)
    fc = {"probs": [0.2, 0.3, 0.4, 0.7, 0.8], "threshold": THR,
          "stage": "Command & Control"}
    r = eng.assess(fc, uncertainty={"confidence": "HIGH"},
                   evidence=[{"feature": "iat_mean", "observed": 2.0,
                              "benign_mean": 0.5, "z": 5.0,
                              "direction": "elevated", "attribution": 0.7,
                              "benign_p99": 1.0}])
    assert r["level"] == "INVESTIGATE"
    assert r["mitre"]["knowledge_base"].startswith("mitre-attack")
    tids = [t["id"] for t in r["mitre"]["techniques"]]
    assert tids                                        # stage tactic techniques
    assert any(a["source"] == "stage" for a in r["recommendations"])
    assert "NOT blocked" in r["human_in_loop"]
    # evidence citation carries the real numbers through
    ev = [a for a in r["recommendations"] if a["source"] == "evidence"][0]
    assert "z=5.0" in ev["action"]


def test_engine_family_beats_stage_mapping(kb):
    eng = DecisionSupportEngine(kb)
    r = eng.assess({"probs": [0.8, 0.8, 0.8, 0.8, 0.8], "threshold": THR,
                    "stage": "Initial Access"},
                   uncertainty={"confidence": "HIGH"}, family="SSH-Brute-Force")
    assert [t["id"] for t in r["mitre"]["techniques"]] == ["T1110"]


def test_engine_escalate_full_packet(kb):
    eng = DecisionSupportEngine(kb)
    r = eng.assess({"probs": [0.7, 0.8, 0.9, 0.9, 0.8], "threshold": THR,
                    "stage": "DoS"}, uncertainty={"confidence": "HIGH"})
    assert r["level"] == "ESCALATE"
    assert r["level_facts"]["steps_above"] == 5


def test_engine_requires_forecast(kb):
    eng = DecisionSupportEngine(kb)
    with pytest.raises(ValueError):
        eng.assess({"probs": [], "threshold": THR})


def test_engine_without_kb_is_honest_not_inventive(tmp_path):
    eng = DecisionSupportEngine(MitreKnowledge.load(tmp_path / "nope.json"))
    r = eng.assess({"probs": [0.8, 0.8, 0.8, 0.8, 0.8], "threshold": THR,
                    "stage": "Exfiltration"},
                   uncertainty={"confidence": "HIGH"})
    assert r["mitre"]["knowledge_base"] == "unavailable"
    assert "techniques" not in r["mitre"]             # nothing invented
    assert r["recommendations"]                        # stage+evidence still work
    assert not any(a["source"] == "mitre" for a in r["recommendations"])
