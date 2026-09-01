# Prompt Packet 3 — Master Learning Document
**Target project:** CyberForecaster (SIH26153)
**Run this LAST**, after Packet 1 (audit/cleanup) and Packet 2 (world-model
gap + training prep) are complete, so this document reflects the final
state of the codebase before the internal round.

---

## 0. Why this document exists

The team is under-coordinated — one person built most of this, and the rest
of the team risks not being able to explain it under jury questioning. In a
stringent internal round, a team that clearly understands its own project
beats a team with a slightly better model but visible confusion when
questioned. **This document's entire purpose is to let every team member —
regardless of role or how much of the code they personally wrote — explain
any part of this system confidently, at both a beginner level and a
technical level, and anticipate the "why did you do X instead of Y"
questions before a judge asks them.**

This is not a duplicate of `AUDIT_LOG.md` or `TRAINING_HANDOFF.md` — it's
the thing a teammate reads the night before the demo to feel prepared, and
the thing they can flip open live if a judge asks something specific.

---

## 1. Operating instructions for the agent

1. Read literally every file in the repo — every module, script, config,
   and existing doc — nothing skipped, including files that seem minor.
   Small files (a constants file, a tiny utility) still need an entry;
   "small" is not the same as "unimportant" when a judge asks about it.
2. For anything changed by Packet 1 or Packet 2, document the **final**
   state, not the pre-fix state — but include a short "what changed and
   why" note for anything materially different from the original teammate
   documentation, so the team can also explain *why* something looks
   different from what they remember building.
3. Write for two audiences in the same document, clearly separated per
   section (not two separate documents — teammates need to move fluidly
   between "explain like I'm new to this" and "explain like a judge with a
   CS background is grilling me"):
   - **Beginner pass**: assume the reader knows general programming but not
     necessarily networking or ML specifics. Explain concepts from first
     principles where they first appear (what's a TCP flag, what's an
     LSTM, what's PR-AUC, what's MITRE ATT&CK) — but only once each, then
     reference back.
   - **Technical pass**: immediately after each beginner explanation, give
     the precise technical version — actual shapes, actual formulas, actual
     function/file references, actual numbers from the real metrics files
     (never hand-typed — pull from `models/*.json` and script outputs, same
     rule as everywhere else in this project).
4. Structure the document so it can be skimmed by section during a live
   Q&A — use clear headers per file/module and per concept, not one long
   wall of prose.

---

## 2. Required structure

### Part A — The one-paragraph pitch (memorize-ready)
Restate what the system does, in the team's own established framing
("we don't classify traffic, we forecast how it evolves") — updated to
reflect any Packet 2 changes (e.g. if the state-reconstruction head made it
into the final build, the pitch should say so; if Packet 2 fell back to
Option A framing, use that language instead — check `TRAINING_HANDOFF.md`
for which applies).

### Part B — Concepts glossary (beginner → technical)
For every concept the project depends on, in the order a newcomer would
need them: packets/flows/flags, windows, MITRE ATT&CK stages, the dataset,
forecasting vs. classification, LSTMs and what "hidden state" means here,
PR-AUC and why it's the right metric under class imbalance, precision vs.
recall and what the 88%/14% numbers actually mean in plain English,
explainability methods used (Integrated Gradients — what it actually
computes, in one plain sentence and one technical sentence), and (if
Packet 2's state head made it in) what a "state transition model" is and
how this project's version compares literally to the PS's definition.

### Part C — File-by-file walkthrough
For every file in the repo (grouped by the folders in the existing repo
map — `src/ingestion/`, `src/preprocessing/`, `src/features/`,
`src/models/`, `src/forecasting/`, `src/evaluation/`,
`src/explainability/`, `src/attack_mapping/`, `src/live/`, `api/`, `web/`,
`scripts/`, `app/`, `tests/`), give:
- **What it does** (one sentence, beginner-readable).
- **How it does it** (technical: key functions, data shapes in/out, key
  algorithm or library used).
- **Why it exists / why this approach and not an obvious alternative** —
  this is the highest-value section for jury prep. Explicitly answer
  "why not X instead" for every non-obvious design decision already
  documented by the team (e.g. why chronological split not random, why
  window-level forecasting across families instead of infiltration-only,
  why log1p+standardize instead of min-max, why LSTM instead of a plain
  feedforward classifier, why Integrated Gradients instead of SHAP, why
  rule engine AND model instead of just one). Where Packet 1 or 2 made a
  new decision (a bug fix approach, the state-head addition), document that
  reasoning here too.
- **What could go wrong here / known limitations**, pulled from the
  existing "honesty rails" and dataset-limitations sections, plus anything
  newly discovered during Packet 1's audit.

### Part D — "Why implement this when we could implement that" bank
A dedicated Q&A section, framed as direct judge questions with prepared
answers, at both beginner and technical depth. Include at minimum:
- Why is this a "world model" and not just a classifier with extra steps?
  (Give the honest answer reflecting whichever of Option A/B from Packet 2
  ended up shipped — do not overclaim.)
- Why 30-second windows and not some other size?
- Why only 14% recall on the test split, and why is that acceptable?
- Why is the split chronological and why does that matter?
- Why do you have both a rule engine and an ML model — isn't that
  redundant?
- What happens if the live network doesn't match the training data
  distribution — how do you handle that live conditioning, and is that
  "cheating"?
- What's the single biggest weakness of this system, honestly?
- If you had two more weeks, what would you fix first?
Add any other question a domain-literate judge would obviously ask given
the PS wording — cross-reference the PS requirements list and make sure
every requirement (flow+packet features, explainability, MITRE mapping,
benchmark vs. logistic regression, offline demo) has a corresponding
prepared answer for "how did you satisfy this, specifically."

### Part E — Change log since the original team doc
A short section listing what Packet 1 and Packet 2 changed relative to the
prototype doc the team started with — bugs fixed, files removed, the
world-model gap decision and outcome — so nobody is caught explaining
outdated behavior.

### Part F — Role-based quick reference
Mirror the existing role-handbook structure (ML pair / Data Engineering /
Backend / Frontend / Domain-Pitch) but make each section self-contained
enough that a teammate who was not previously engaged can read *only* their
section plus Parts A, B, and D and be demo-ready — since the packet exists
partly because not everyone was involved so far.

---

## 3. Tone and quality bar

- No invented numbers, ever — every metric must trace to an actual file or
  script output, cited by filename.
- No padding — if a file is genuinely simple, say so briefly rather than
  manufacturing false depth. Depth should scale with the file's actual
  importance to the pitch and to likely questions, not be uniform.
- Prefer analogies for beginner explanations, but always follow the analogy
  with the literal technical fact — an analogy alone is not enough to
  survive a follow-up question.
- Write in a way that sounds like the team actually understands and built
  this together, not like a wiki dump — this document is rehearsal
  material, not just reference material.

---

## 4. Deliverable

A single comprehensive file, e.g. `MASTER_LEARNING.md`, at the repo root,
structured per §2, reflecting the fully audited and (if applicable)
retrained final state of the project. This is the document the whole team
studies before Sep 5.
