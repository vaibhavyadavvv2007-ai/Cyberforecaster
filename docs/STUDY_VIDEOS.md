# Study-sprint video list — SIH26153

One curated YouTube video per topic from the battle plan §4 study sprint,
plus optional deep dives. Core watch-time per unit is matched to the battle
plan's budget (U1 90 min · U2 60 · U3 45 · U4 45 · U5 30).

All links were pulled from live YouTube search on Sep 1, 2026 (via
`scripts/yt_search.py` — rerun it if any link ever dies).

Watch order: straight down the core column; deep dives only if the topic
is yours on demo day.

---

## Unit 1 — TCP/IP primitives (core ≈ 40 min, deep dive +61)

| Topic | Video | Length |
|---|---|---|
| 3-way handshake | [TCP - Three-way handshake in details — Sunny Classroom](https://www.youtube.com/watch?v=xMtP5ZB3wSk) | 4:17 |
| FIN vs RST (our flag features!) | [How TCP Works - FINs vs Resets — Chris Greer](https://www.youtube.com/watch?v=-vgk9P-6dPY) | 7:04 |
| Ports (well-known ranges) | [Network Ports Explained — PowerCert Animated Videos](https://www.youtube.com/watch?v=g2fT-g9PX9o) | 10:33 |
| What a connection really looks like | [TCP connection walkthrough — Ben Eater](https://www.youtube.com/watch?v=F27PLin3TV0) | 9:31 |
| NetFlow / IPFIX records | [MicroNugget: What is Netflow? — CBT Nuggets](https://www.youtube.com/watch?v=aqTpUmUibB8) | 7:46 |
| *Deep dive (optional)* | [*How TCP really works — David Bombal*](https://www.youtube.com/watch?v=rmFX1V49K8U) | *1:01:10* |

Self-checks (battle plan): What does a SYN without ACK suggest? Why do
scanners touch many ports on one host? What's a "flow record"?

## Unit 2 — Attack families in CSE-CIC-IDS2018 (core ≈ 60 min)

| Family in our data | Video | Length |
|---|---|---|
| DDoS (LOIC) | [DDoS Attack Explained — PowerCert Animated Videos](https://www.youtube.com/watch?v=ilhGh9CEIwM) | 5:43 |
| DoS — slow attacks (Slowloris) | [Slow Loris Attack — Computerphile](https://www.youtube.com/watch?v=XiFkyR35v2Y) | 8:25 |
| Brute force (FTP/SSH) | [Brute Force Attack — Neso Academy](https://www.youtube.com/watch?v=DoBqnt7Bf24) | 8:46 |
| Botnet (Ares) | [What is botnet and how does it spread? — ESET](https://www.youtube.com/watch?v=s0sgiY93w9c) | 3:07 |
| Heartbleed | [Heartbleed explained in under 2 minutes — Keith Rozario](https://www.youtube.com/watch?v=6Sz5wBBXzpc) | 2:01 |
| XSS (web attacks) | [Cross-Site Scripting (XSS) Explained — PwnFunction](https://www.youtube.com/watch?v=EoaDgUgS6QA) | 11:27 |
| SQL injection (web attacks) | [SQL Injections are scary!! — NetworkChuck](https://www.youtube.com/watch?v=2OPVViV-GQk) | 10:14 |
| Lateral movement (Infiltration) | [Lateral Movement Explained in 90 Seconds — Illumio](https://www.youtube.com/watch?v=AqAUDnef738) | 1:42 |
| Scanning (our demo Acts 1 & 2) | [Port Scanning: UDP and TCP — Network Insight](https://www.youtube.com/watch?v=Mx1BhMqGhio) | 7:44 |
| *Heartbleed, deeper (optional)* | [*Heartbleed Exploit — HackerSploit*](https://www.youtube.com/watch?v=SgJm0C6jzbo) | *14:29* |

Self-checks: which families port-scan first? Which produce east-west
internal connections? Which flood bandwidth?

## Unit 3 — MITRE ATT&CK + kill chain (core ≈ 18 min, deep dive +30)

| Topic | Video | Length |
|---|---|---|
| ATT&CK, from MITRE itself | [MITRE ATT&CK® Framework — The MITRE Corporation](https://www.youtube.com/watch?v=Yxv1suJYMI8) | 3:43 |
| Using it as a practitioner | [How to Actually Use MITRE ATT&CK as a Beginner — MyDFIR](https://www.youtube.com/watch?v=8Q6fts0KJ4o) | 6:42 |
| Lockheed-Martin kill chain | [Cyber Kill Chain — edureka!](https://www.youtube.com/watch?v=m8xWhpGny2Y) | 7:22 |
| *Deep dive (optional)* | [*How to Use MITRE ATT&CK Framework, Detailed — Prabh Nair*](https://www.youtube.com/watch?v=huPMWB-gCsY) | *30:21* |

Self-checks: where do Botnet beacons sit? Where does SSH brute-force sit?

## Unit 4 — Dataset semantics (core ≈ 45 min)

| Topic | Video | Length |
|---|---|---|
| **Errors in our exact dataset** | [Error Prevalence in NIDS datasets: CIC-IDS-2017 and CSE-CIC-IDS2018 — PIRAT Research Team](https://www.youtube.com/watch?v=sJvZKhw3lYo) | 34:32 |
| Why chronological split (leakage) | [What is Data Leakage In Machine Learning? — Krish Naik](https://www.youtube.com/watch?v=n9jz7G68pVg) | 10:49 |
| *Class imbalance, deeper (optional)* | [*Handling imbalanced datasets — codebasics*](https://www.youtube.com/watch?v=JnlM4yLFNuo) | *38:26* |

The PIRAT talk is the single most on-point video in this list — it is
about the exact benchmark we train on, including its labeling errors.
Pair it with our own verified-quirks table in `docs/TEAM_GUIDE.md` §II.2.

Self-checks: why must we split chronologically? What does class imbalance
look like here?

## Unit 5 — SOC vocabulary (core ≈ 20 min)

| Topic | Video | Length |
|---|---|---|
| SIEM | [What Is SIEM? — IBM Technology](https://www.youtube.com/watch?v=9RfsRn7m7OE) | 4:29 |
| IDS vs IPS | [IDS vs IPS: Which to Use and When — CBT Nuggets](https://www.youtube.com/watch?v=wQSd_piqxQo) | 5:39 |
| Precision vs recall | [Never Forget Again! Precision vs Recall — Kimberly Fessel](https://www.youtube.com/watch?v=qWfzIYCvBqo) | 5:24 |
| False positives/negatives | [ML Basics: False Positives, False Negatives — ML Tidbits](https://www.youtube.com/watch?v=Ivc8c9ijWIQ) | 4:04 |

Self-check: explain precision/recall/FPR the way a SOC operator feels them
("another false page at 3am" vs "the one real attack we missed").

---

## Bonus — ML pair only (not in the study budget)

| Topic | Video | Length |
|---|---|---|
| LSTM intuition | [Long Short-Term Memory (LSTM), Clearly Explained — StatQuest](https://www.youtube.com/watch?v=YCzL96nL7j0) | 20:45 |
| LSTM, short version | [What is LSTM? — IBM Technology](https://www.youtube.com/watch?v=b61DPVFX03I) | 8:19 |
| Wireshark literacy (for live-debug days) | [Learn Wireshark in 10 minutes — Vinsloev Academy](https://www.youtube.com/watch?v=lb1Dw0elw0Q) | 10:38 |

**Reminder from the battle plan:** SKIP penetration-testing rooms, exploit
development, malware reversing, firewall admin, certifications, and deep
Wireshark analysis — none of it is in the deliverable.
