# Prompt Packet 2 — Closing the "World Model" Gap + Colab Training Prep
**Target project:** CyberForecaster (SIH26153)
**Run this SECOND**, after Packet 1 (audit/bugfix/cleanup) is complete and verified.
**Human constraint (do not violate):** any actual model training happens on
**Google Colab, on GPU, by a human team member** — not in this environment.
Your job is to get everything *ready* for that training run, not to run it.

---

## 0. The problem this packet exists to solve

The problem statement (PS26153) asks for a **world model**: something that
represents network state `S_t` as a vector or graph, learns the transition
dynamics `P(S_t+1 | S_t)`, and performs **K-step forward simulation of
state** to derive infiltration probability, attack stage, and driving
features.

The current model does something adjacent but not identical: given 10
windows of history, it directly predicts, for each of the next 5 windows,
(a) an attack-probability logit and (b) a dominant ATT&CK stage — a
multi-horizon, multi-task **label forecaster**. It never reconstructs a
future feature vector. This is a real and defensible engineering choice
(the team's own docs call it a "mature trade-off"), but it is also the most
likely point a stringent jury pushes on, because it's the literal
definition given in the PS.

You have two options. **Do not silently pick one — lay out both with
trade-offs, then implement the one specified below (Option B), because it
gets closer to PS-literal compliance without discarding the working label
forecaster.**

### Option A — Reframe only (no architecture change)
- What it is: keep the current model exactly as-is; change only the
  language used to describe it — "we forecast future network state
  *indirectly*, via a learned temporal representation, and predict
  attack-relevant outcomes (probability, stage) as a function of that
  representation" rather than claiming explicit state simulation.
- Pros: zero risk of breaking anything, zero additional training needed,
  can be done entirely in Packet 1/3 territory (documentation only).
- Cons: doesn't actually close the gap — a jury member who has read the PS
  closely may still call this out as not being a world model in the sense
  asked for. Purely a rhetorical fix.

### Option B — Add an auxiliary next-state reconstruction head (recommended)
- What it is: add a **second output head** to the existing LSTM that
  predicts the actual next-window feature vector(s) — i.e., a true
  `Ŝ_{t+1}, ..., Ŝ_{t+K}` reconstruction — trained with an additional
  regression loss (e.g. MSE on the scaled 18-dim feature vector) alongside
  the existing progression/stage losses. The existing heads and their
  outputs are **not removed or changed** — this is additive multi-task
  learning. The forward-simulation story becomes literal: "we predict
  future state vectors, and derive infiltration probability and attack
  stage from that predicted trajectory" (even if in practice the
  progression head is still doing the heavy lifting for the demo-critical
  numbers).
- Pros: directly answers the PS's own architecture spec; gives you a
  legitimate, literal answer to "where is your state-transition model";
  strengthens the explainability story (you can show a predicted vs. actual
  future feature trajectory, not just a probability curve).
- Cons: requires retraining (GPU, Colab) — new loss term, new head, needs a
  full training run to produce valid weights; risk of the added loss term
  hurting the existing progression/stage metrics if not weighted carefully
  (needs a loss-weighting sweep, not just "add it and hope"); adds
  complexity to an already time-pressured pre-demo schedule.

**Decision: implement Option B's code changes now, but treat the actual
training as a separate, human-run step on Colab.** If time before Sep 5
turns out too short to safely retrain and re-verify, Option A is the
fallback framing and should already be written up as backup in the
documentation (see §4) so the team isn't stuck without a story.

---

## 1. What to actually implement (code, not training)

Work in plan mode: write out the plan, get it right on paper, then
implement incrementally.

1. **Model architecture change** (`src/models/lstm_forecaster.py`):
   - Add a state-reconstruction output head predicting the scaled 18-dim
     feature vector for each of the K horizon steps, alongside the existing
     progression (`y_prog`) and stage (`y_stage`) heads.
   - Keep the existing heads' input/output shapes and behavior byte-for-byte
     identical — this must be a strictly additive change. Anything
     depending on the current model output shape (API, frontend, rollout
     logic, explainability) must keep working unmodified for the existing
     heads.
   - Add a config flag (e.g. `predict_next_state: true/false`) so the new
     head can be toggled off and the model reverts to exactly current
     behavior — this is your safety net if the new head underperforms.

2. **Loss function** (wherever the training loop lives):
   - Add an MSE (or Huber, to be less sensitive to outliers in log1p-scaled
     features) loss term on the reconstructed state vectors.
   - Make the loss weighting between progression/stage/state-reconstruction
     a named, documented hyperparameter — not a hardcoded magic number —
     so it can be swept during the Colab run without code changes.
   - Do NOT change how `y_prog`/`y_stage` losses are computed — only add to
     the total loss.

3. **Rollout / inference path** (`src/forecasting/rollout.py`):
   - Extend the `Forecaster` bundle to also return the predicted future
     state vectors when the new head is enabled, so the API/frontend can
     optionally surface "predicted vs. actual next-window features" as an
     explainability artifact.
   - Keep this fully backward compatible: when `predict_next_state=false`
     (or weights don't include the head), behavior must be identical to
     today.

4. **Explainability extension** (`src/explainability/attribution.py`):
   - If time allows, add a simple visualization/derivation of "predicted
     future state vs. what actually happened" for demo scenarios where
     ground truth is available (offline scenario console only — you have
     the labels there). This is optional polish, not required for the core
     fix — note it in the plan as a stretch goal.

5. **API/frontend surfacing** — only if the head is enabled and produces
   sensible output after training: add an optional field to the
   `/api/forecast` response schema for the predicted state trajectory.
   Do not add UI for this until real trained weights exist and have been
   sanity-checked — an empty/placeholder chart is worse than no chart.

6. **Model import path** — since training happens elsewhere:
   - Confirm (or add) a clean, documented path for **importing** a model
     trained on Colab back into the repo: exact file(s) expected
     (`lstm_forecaster.pt`, `lstm_config.json`, `metrics_lstm.json`), exact
     directory (`models/`), and a validation step (`verify_state.py` should
     already check config/artifact consistency — extend it to also check
     the new head's config key is present and consistent if enabled).
   - Write this up explicitly as its own section titled **"Importing a
     Colab-trained model"** in a new file: `TRAINING_HANDOFF.md`.

---

## 2. What NOT to do in this environment

- Do not attempt to train the model here, even on a tiny subset "just to
  check it runs." If a smoke-level forward/backward pass check is useful to
  confirm the new head doesn't crash, that's fine (few iterations, synthetic
  data, purely a shape/wiring check) — but this is not training, and must
  be clearly labeled as such in logs and comments.
- Do not touch the existing chronological split, scaling function, or
  threshold-selection logic as part of this packet — those are Packet 1's
  domain (bug fixing) and must stay exactly as verified.
- Do not silently change existing metrics files (`models/*.json`) — those
  reflect the currently-deployed model and must remain valid/usable as a
  fallback until new trained weights are actually validated and swapped in.

---

## 3. `TRAINING_HANDOFF.md` — required deliverable

This file is what tells the human (who will run Colab) exactly what to do.
It must include:

1. **What changed and why** — plain summary of the new head, in 3–5
   sentences, linking back to the PS requirement it addresses.
2. **Exact training command / notebook cell(s)** to run on
   `notebooks/Colab_Training.ipynb`, including the new loss-weight
   hyperparameter(s) and suggested starting values/ranges to sweep (don't
   pick just one value blindly — suggest 2–3 to try, e.g. state-loss weight
   ∈ {0.1, 0.3, 0.5} relative to the existing task losses).
3. **What to bring back from Colab**, exactly: updated
   `lstm_forecaster.pt`, `lstm_config.json` (with the new config flag set),
   `metrics_lstm.json` (must now also include the state-reconstruction
   loss/MSE alongside existing PR-AUC/precision/recall/FPR).
4. **How to re-verify locally after import**: run `verify_state.py`, run
   the smoke test, re-check that PR-AUC/precision/recall on the existing
   heads have not regressed compared to the pre-change baseline (this is
   the critical check — if adding the state head makes the actual
   demo-critical numbers worse, the loss weight needs to go down, or the
   feature should be disabled for demo day and kept as a documented
   "implemented but not enabled" capability instead).
5. **Fallback plan** if training doesn't finish in time or hurts existing
   metrics: keep `predict_next_state=false`, ship the existing model
   unchanged, and use the **Option A reframing language** (§0) instead —
   write that reframed description here too, ready to paste into pitch
   materials, so there's no scramble on demo day.
6. **Time estimate** — give an honest estimate of Colab GPU time needed
   (training epochs × data size), and flag if this realistically doesn't
   fit before Sep 5 given when this packet is run.

---

## 4. Also address: the 14% recall problem

This is a separate, smaller issue from the world-model gap but sits in the
same "needs retraining" bucket, so handle it in the same packet.

The current model has 88% precision but only 14% recall on the unseen
attack family in the test split. Lay out — with trade-offs, don't just pick
one — options such as:
- Class-weighted loss / focal loss to push recall up (trade-off: will move
  the precision/recall point, may raise false-positive rate — needs
  re-tuning the threshold under the same FPR budget methodology already
  documented).
- Threshold adjustment alone (no retraining) — cheapest option, but the
  team's own docs already note the threshold is chosen for a 5% FPR budget
  on validation deliberately; moving it without changing that policy is
  just picking a different point on the same curve, not a real
  improvement, and should be presented honestly as such.
- More training data / different windowing — likely too slow to redo before
  Sep 5; note as a "future work" item rather than something to attempt now.

Document the chosen approach (if any) in `TRAINING_HANDOFF.md` alongside the
state-head changes, since both require the same Colab round-trip — don't
make the team do two separate training cycles if one will do.

---

## 5. Deliverables from this packet

- Code changes implementing the additive state-reconstruction head,
  fully backward-compatible, with a config flag to disable it.
- `TRAINING_HANDOFF.md` with exact Colab instructions, what to bring back,
  how to re-verify, and the Option A fallback language ready to use.
- No locally-run training. No changes to existing verified metrics files
  until new trained weights are validated.
