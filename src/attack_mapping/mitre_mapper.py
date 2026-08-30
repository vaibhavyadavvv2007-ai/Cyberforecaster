"""MITRE ATT&CK stage mapping — the honesty layer of this project.

Two components:

1. FAMILY_STAGE — maps each dataset attack family to a stage. Used to build
   supervision labels and to VALIDATE the rule engine below.

   | Family            | Stage              | Rationale                                   |
   |-------------------|--------------------|---------------------------------------------|
   | FTP/SSH/Web brute | Initial Access     | credential attacks against exposed services |
   | XSS / SQLi        | Initial Access     | exploiting a public-facing application      |
   | Botnet-Ares       | Command & Control  | implant beaconing to C2                     |
   | Heartbleed        | Exfiltration       | memory-disclosure → data leaves the host    |
   | Infiltration      | Lateral Movement   | attacker pivots DMZ → production subnet     |
   | DoS*/DDoS*        | DoS (own category) | flooding sits under ATT&CK Impact, outside  |
   |                   |                    | the PS's five progression stages; forcing   |
   |                   |                    | it into the chain would be dishonest        |

2. rule_based_stage() — predicts a stage from window aggregate features alone.
   Thresholds are deliberately explicit so the jury can read them, and
   validate_rules() scores the rules against dataset labels.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STAGES = [
    "Reconnaissance",
    "Initial Access",
    "Lateral Movement",
    "Command & Control",
    "Exfiltration",
    "DoS",  # displayed separately — see table above
]

FAMILY_STAGE = {
    "FTP-Brute Force": "Initial Access",
    "SSH-Brute-Force": "Initial Access",
    "Web-Brute Force": "Initial Access",
    "XSS": "Initial Access",
    "SQL-Injection": "Initial Access",
    "Botnet-Ares": "Command & Control",
    "Heartbleed": "Exfiltration",
    "Infiltration": "Lateral Movement",
    "DoS-GoldenEye": "DoS",
    "DoS-Hulk": "DoS",
    "DoS-Slowhttptest": "DoS",
    "DoS-Slowloris": "DoS",
    "DDoS-LOIC": "DoS",
    "DDoS-HOIC": "DoS",
}

AUTH_PORTS = {20, 21, 22, 23, 3389}  # ftp, ssh, telnet, rdp

# TUNING NOTES (from first real run, Feb-14, 2026-08-26):
# Benign background on CIC days runs ~900+ flows/min. Attack bursts therefore
# DILUTE ratio-based features: a brute-force bin mixing ~500 attack flows with
# ~900 benign ones has auth_port_share ≈ 0.36 — under the 0.5 threshold — even
# though it is obviously an auth burst. When you tune on Sunday:
#   1. Prefer ABSOLUTE counts (auth flow count per window) over shares, or
#      normalize shares against a rolling benign baseline instead of the raw bin.
#   2. Re-check scan/C2 rules the same way — any share feature suffers dilution.
#   3. Tune ONLY against validate_rules() output across ALL downloaded days,
#      then freeze thresholds and copy them into a slide. Never tune on demo day.


def stage_for_label(label: str) -> str:
    return FAMILY_STAGE.get(label, "Reconnaissance" if label not in (None, "Benign") else "")


def rule_based_stage(f: dict, p99_bytes: float = 0.0, p99_pkts: float = 0.0,
                     has_ip: bool | None = None) -> str:
    """Predict a stage from one window's aggregate features.

    `f` keys mirror the columns produced by features.window_builder.
    Ordered checks: first match wins. Thresholds are tunable knobs — tune them
    against validate_rules(), never by feel on demo day.

    `has_ip`: whether the IP-derived features carry signal. CIC-IDS2018's
    ML-ready CSVs ship NO Src IP / Dst IP columns (battle plan §5.2), so those
    features are constant 0. Auto-detected when None. This matters a lot:
      - the lateral-movement rule keyed on `east_west >= 3` could NEVER fire
      - the C2 rule's `unique_dst_ips <= 3` clause was ALWAYS true, so C2
        over-fired on anything with regular timing
    Rather than invent a threshold that looks authoritative, we make the gap
    explicit: with no IPs, lateral movement is UNDECIDABLE from these features
    and the rule abstains. Say that out loud — an abstention you can explain
    beats a rule the jury can break.
    """
    flow_count = f.get("flow_count", 0)
    syn_ratio = f.get("syn_ratio", 0.0)
    unique_ports = f.get("unique_dst_ports", 0)
    bytes_total = f.get("bytes_total", 0.0)
    pkts_total = f.get("pkts_total", 0.0)
    iat_mean = f.get("iat_mean", 0.0)
    iat_std = f.get("iat_std", 0.0)
    auth_share = f.get("auth_port_share", 0.0)
    n_src, n_dst = f.get("unique_src_ips", 0), f.get("unique_dst_ips", 0)
    if has_ip is None:
        has_ip = (n_src > 0) or (n_dst > 0)

    # Order matters: distinctive signatures first, generic volume last —
    # otherwise every busy window collapses into "flood".
    # 1) many distinct ports + SYN-heavy → scanning
    if unique_ports >= 15 and syn_ratio >= 0.4:
        return "Reconnaissance"
    # 2) bursts at remote-access services → credential access attempts
    if auth_share >= 0.5 and flow_count >= 8:
        return "Initial Access"
    # 3) volumetric flood (extreme on BOTH volume metrics) → DoS
    if p99_pkts > 0 and pkts_total > p99_pkts and p99_bytes > 0 and bytes_total > p99_bytes:
        return "DoS"
    # 4) regular low-jitter beaconing, low volume → C2. The destination-count
    #    clause only applies when IPs exist; without them, regularity + low
    #    volume is all we legitimately have. pkts_total floor: a near-dead
    #    window (5 flows / 14 pkts) is silence, not beaconing — without the
    #    floor the rule fires on quiet-network noise (observed live Aug 30).
    if 5 <= flow_count <= 60 and pkts_total >= 30 and iat_mean > 0 \
            and (iat_std / max(iat_mean, 1e-9)) < 0.25 \
            and (not has_ip or n_dst <= 3):
        return "Command & Control"
    # 5) internal endpoints moving between Windows admin ports → lateral
    #    movement. Endpoint count alone is not evidence: benign Wi-Fi gives
    #    min(n_src, n_dst) >= 3 in every 30s window (SSDP/mDNS/LAN chatter),
    #    so the count clause over-fired as a constant false positive. The
    #    live-only lateral_port_share (SMB/RPC/RDP/WinRM share of flows,
    #    LATERAL_PORTS in packet_windower) is the actual signal; it is absent
    #    (0) in training windows, where this rule already abstains.
    if has_ip and min(n_src, n_dst) >= 3 and flow_count >= 6 \
            and f.get("lateral_port_share", 0.0) >= 0.2:
        return "Lateral Movement"
    # 6) huge outbound transfer with few flows → bulk exfiltration
    if p99_bytes > 0 and bytes_total > p99_bytes:
        return "Exfiltration"
    return ""


def validate_rules(windows: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """Cross-tab predicted vs label-derived stages over all attack windows."""
    attack = windows[windows["attack_frac"] > 0].copy()
    if attack.empty:
        raise ValueError("no attack windows found — is the input only benign traffic?")
    p99b = float(windows["bytes_total"].quantile(0.99)) if "bytes_total" in windows else 0.0
    p99p = float(windows["pkts_total"].quantile(0.99)) if "pkts_total" in windows else 0.0
    feats = ["flow_count", "syn_ratio", "unique_dst_ports", "auth_port_share",
             "unique_src_ips", "unique_dst_ips", "bytes_total", "pkts_total",
             "iat_mean", "iat_std"]

    # Detect ONCE on the whole frame: a per-row check would misread a quiet
    # window as "no IP data" even when the dataset does have IP columns.
    has_ip = bool(
        (windows.get("unique_src_ips", pd.Series(dtype=float)).max() or 0) > 0
        or (windows.get("unique_dst_ips", pd.Series(dtype=float)).max() or 0) > 0
    )
    pred = [rule_based_stage(row.to_dict(), p99b, p99p, has_ip=has_ip)
            for _, row in attack[feats].iterrows()]
    idx = attack["dominant_stage_idx"].astype(int)
    label_stage = pd.Series(
        [STAGES[i] if 0 <= i < len(STAGES) else "unknown" for i in idx],
        index=attack.index,
    )
    ct = pd.crosstab(label_stage, pd.Series(pred, index=attack.index, name="predicted"))
    if verbose:
        # full-width print — truncated crosstabs hide whole predicted classes
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print("\nRule-engine validation (rows=label stage, cols=predicted):\n", ct)
            if not has_ip:
                print("\nNOTE: no IP-derived signal in this data (Src IP/Dst IP absent from")
                print("      CIC's ML-ready CSVs). The Lateral Movement rule ABSTAINS and the")
                print("      C2 rule drops its destination-count clause. This is a documented")
                print("      limitation, not a tuning failure — see battle plan §5.2.")
            empty_col = ct.get("", pd.Series(dtype=int))
            if len(empty_col):
                print(f"\n({int(empty_col.sum())} attack windows matched NO rule — "
                      f"thresholds too strict, see tuning notes in this file)")
        acc = float(np.trace(ct.values)) / max(np.sum(ct.values), 1)
        print(f"rule-vs-label agreement: {acc:.2%}")
    return ct


if __name__ == "__main__":
    print("Stages:", STAGES)
    print("Family map rows:", len(FAMILY_STAGE))
