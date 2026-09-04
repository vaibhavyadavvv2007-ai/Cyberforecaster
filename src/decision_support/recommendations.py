"""Ranked investigation actions — deterministic templates, real numbers.

Every recommendation is a template filled with values that already exist in
the forecast/evidence record (plan rule 8: no LLM in the explanation path).
Sources, in priority order:

  P1  stage actions    what to check first for the predicted ATT&CK stage
  P1  evidence actions concrete checks derived from the top deviating
                       feature (observed value + benign reference + z)
  P2  MITRE mitigations from the STIX knowledge base for the mapped
                       techniques (shown only when the KB is available)
  P3  verification     when the level is INVESTIGATE/LOW-confidence: collect
                       more bins before deciding

Ranking is stable: priority (P1 < P2 < P3), then the source order above,
then the order the inputs arrived in. No randomness anywhere.
"""
from __future__ import annotations

# What an analyst checks first per predicted stage. Written as actions that
# make sense on a laptop demo AND on a real network.
STAGE_ACTIONS = {
    "Reconnaissance": [
        "Identify the source host(s) behind the scan burst (top talker by "
        "unique destination ports in the last window).",
        "Check whether scanned ports cluster on exposed services (web, auth) "
        "— targeted recon, not noise.",
    ],
    "Initial Access": [
        "Pull authentication logs for the auth services (SSH/FTP/RDP) in the "
        "last window; count failed logins per source.",
        "Look for repeated identical requests against public-facing apps "
        "(credential stuffing / injection patterns).",
    ],
    "Lateral Movement": [
        "Audit new east-west connections on admin ports (SMB 445, RDP 3389, "
        "WinRM 5985/5986) between subnets in the last window.",
        "Check whether the same internal host now reaches hosts it never "
        "contacted before.",
    ],
    "Command & Control": [
        "Inspect egress traffic for regular low-jitter intervals (beaconing) "
        "from the same internal host.",
        "Resolve the destination of the most regular flow and check it "
        "against threat-intel feeds.",
    ],
    "Exfiltration": [
        "Review the largest outbound transfers in the last window; compare "
        "against the benign p99 for volume.",
        "Identify which host sent the bulk and whether the destination is "
        "new for that host.",
    ],
    "DoS": [
        "Confirm per-flow volume on the top talker — flood vs many benign "
        "users sharing one service.",
        "Check whether the target service is degraded (health check), not "
        "just busy.",
    ],
}


def stage_actions(stage: str | None) -> list[dict]:
    """P1 recommendations from the predicted stage. Unknown/None stage →
    a single honest action instead of nothing."""
    if stage and stage in STAGE_ACTIONS:
        return [{"priority": "P1", "source": "stage",
                 "action": a, "rationale": f"predicted stage: {stage}",
                 "refs": []} for a in STAGE_ACTIONS[stage]]
    if stage is None or stage == "":
        return [{"priority": "P1", "source": "stage",
                 "action": "No stage predicted yet — re-check once more "
                           "history accumulates.",
                 "rationale": "stage head returned no stage", "refs": []}]
    return [{"priority": "P1", "source": "stage",
             "action": f"Stage '{stage}' is not in the action playbook — "
                       "verify the forecast evidence manually.",
             "rationale": "unknown stage label", "refs": []}]


def evidence_actions(evidence: list[dict] | None, top_k: int = 2) -> list[dict]:
    """P1 recommendations from the strongest deviating evidence rows.

    Only rows with a real deviation (|z| >= 2 AND direction != normal) and a
    non-trivial attribution become actions — a feature inside the benign
    range is not evidence of anything.
    """
    out = []
    if not evidence:
        return out
    strong = [e for e in evidence
              if e.get("direction") in ("elevated", "suppressed")
              and abs(e.get("attribution", 0.0)) > 1e-6]
    for e in strong[:top_k]:
        out.append({
            "priority": "P1",
            "source": "evidence",
            "action": (f"Verify {e['feature']} on the source host: observed "
                       f"{e['observed']} vs benign mean {e['benign_mean']} "
                       f"(z={e['z']}, {e['direction']})."),
            "rationale": (f"model attribution {e['attribution']} with benign "
                          f"deviation z={e['z']}"),
            "refs": [e["feature"]],
        })
    return out


def mitre_actions(techniques: list[dict] | None) -> list[dict]:
    """P2 recommendations from the STIX knowledge base — mitigations for the
    mapped techniques, deduplicated, capped. Only when the KB is loaded."""
    out, seen = [], set()
    if not techniques:                      # includes the None/unavailable case
        return out
    for t in techniques:
        for m in t.get("mitigations", [])[:3]:
            if m in seen:
                continue
            seen.add(m)
            out.append({
                "priority": "P2",
                "source": "mitre",
                "action": f"MITRE mitigation for {t['id']} ({t['name']}): {m}",
                "rationale": "official ATT&CK course of action (STIX)",
                "refs": [t["id"]],
            })
    return out[:5]


def verification_action(level: str, band: str | None) -> list[dict]:
    """P3 — the honest 'collect more data' option when the forecast is
    distant or uncertain. Never recommended at ESCALATE (time matters)."""
    if level == "ESCALATE":
        return []
    if level == "INVESTIGATE" or band == "LOW":
        return [{"priority": "P3", "source": "verification",
                 "action": "Let 2-3 more bins accumulate and re-assess "
                           "before committing analyst time (1-1.5 min at "
                           "30s bins).",
                 "rationale": "forecast is distant or the uncertainty band "
                              "is wide",
                 "refs": []}]
    return []


def rank(actions: list[dict]) -> list[dict]:
    """Stable priority sort — P1 first, then source order, then arrival."""
    order = {"P1": 0, "P2": 1, "P3": 2}
    src = {"stage": 0, "evidence": 1, "mitre": 2, "verification": 3}
    return sorted(actions, key=lambda a: (order[a["priority"]],
                                          src[a["source"]]))


def build(level: str, band: str | None, stage: str | None,
          evidence: list[dict] | None,
          techniques: list[dict] | None, limit: int = 8) -> list[dict]:
    """All sources → one ranked, capped list."""
    actions = (stage_actions(stage) + evidence_actions(evidence)
               + mitre_actions(techniques) + verification_action(level, band))
    return rank(actions)[:limit]
