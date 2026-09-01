# Prompt Packet 1 — Codebase Audit, Bug Fixing & Cleanup
**Target project:** CyberForecaster (SIH26153 — AI-based Network Attack Forecasting)
**Repo:** https://github.com/vaibhavyadavvv2007-ai/Cyberforecaster
**Run this packet FIRST**, before Packet 2 (world-model gap) and Packet 3 (deep analysis / learning doc).

---

## 0. Read this before touching anything

This codebase was built mostly solo, under time pressure, for an internal
hackathon round on **Sep 5, 2026**. It already has real engineering rigor
baked into it — a chronological train/val/test split with boundary purge, a
single shared scaling function, honesty modes (REAL/CACHED/SIMULATED), and a
documented bug-fix history (Welford variance bug, per-batch-AP bug,
unfair-baseline-scaling bug). **Your job is not to rewrite this system. Your
job is to find what's actually broken or sloppy, fix it without breaking
anything that currently works, and leave the codebase leaner.**

The single most important rule in this entire packet:

> **Never make a change without first understanding what depends on the
> thing you're changing, and never move to the next fix without confirming
> the previous fix didn't break anything else.**

If you cannot verify a fix didn't cause a regression, treat that fix as
**not done** — flag it for human review instead of leaving it in an unverified
state.

---

## 1. Operating mode: PLAN MODE, always

Do not free-run edits across the repo. For every phase below:

1. **Investigate first.** Read the relevant files, trace how they're
   imported/called elsewhere (grep for usages, not just definitions).
2. **Produce a written plan** before editing: what you found, why it's a
   bug (or why a file is dead weight), what you intend to change, and what
   you expect to be affected downstream.
3. **Only after the plan is written**, implement it — one bug/cleanup item
   at a time, not in batches, unless items are provably independent.
4. **After every change**, run the verification protocol in §5 before
   moving to the next item.
5. Keep a running log (`AUDIT_LOG.md`, create if it doesn't exist) of every
   plan, every change made, every verification result, and every item you
   decided to flag instead of fix. This log is a deliverable — the team
   needs it to know what changed and why.

If, at any point, a fix would require touching model training code that
needs a GPU to re-run (LSTM training, hyperparameter changes, anything in
`src/models/lstm_forecaster.py` that changes architecture or training
config) — **stop, do not implement, and log it as "defer to Packet 2"**.
Training happens on Google Colab by a human, not by you locally.

---

## 2. Phase 1 — Full context pass (no edits yet)

Before finding bugs, build an accurate mental map:

- Walk the entire repo tree (`src/`, `api/`, `web/`, `scripts/`, `data/`,
  `notebooks/`, `app/`, `tests/`, `docs/`, root-level docs).
- For every Python module, note: what it imports, what imports it, what it
  writes to disk / reads from disk, and whether it's actually invoked from
  `rebuild_all.py`, the API, the live pipeline, or is orphaned.
- Read the existing docs (`README.md`, `SIH26153_battle_plan.md`,
  `docs/DEMO_RUNBOOK.md`, `DESIGN.md`) and treat their stated invariants as
  **ground truth constraints**, not suggestions:
  - Scaling (`log1p` + standardize) happens in exactly one place
    (`src/features/scaling.py`) and every model/consumer imports it.
  - The train/val/test split is chronological with boundary purge —
    **never** shuffled.
  - `y_prog` is per-horizon-step, shape `(n, K)` — never a single label
    broadcast across K.
  - Validation AP is computed once over the pooled split, not averaged
    per-batch.
  - Thresholds are picked on validation only, under a stated FPR budget —
    never on test, never hand-tuned.
  - Metrics displayed anywhere (UI, docs) must come from `models/*.json` /
    script output — never hand-typed.
  - Live input conditioning (IP-zeroing, ratio-clamping to training p99)
    happens only in `model_matrix()` for model input; the rule engine must
    still see raw values.
  - Honesty mode badges (REAL/CACHED/SIMULATED) must never silently swap —
    the health endpoint must report the true mode and any boot error.
- Produce a short **CONTEXT_MAP.md** (or a section in `AUDIT_LOG.md`)
  summarizing: file → purpose → depended-on-by → depends-on. This is what
  lets you reason safely about blast radius later.

**Do not skip this phase to save time.** Every bug-fixing mistake in a
codebase like this comes from touching a function without knowing who else
calls it.

---

## 3. Phase 2 — Logical bug hunt

Look specifically for **logical/silent bugs**, not style nits. Categories to
actively hunt, informed by this project's own bug history (meaning: these
are exactly the *class* of mistake that has already happened once here —
assume there are siblings):

1. **Off-by-N / unit confusion in time-series code.** The Welford variance
   bug (`iat_m2 += d * (ts - mean)` instead of `dt - mean`) was an absolute
   timestamp used where a delta was needed. Audit every place that computes
   a rolling statistic, a delta, or a window boundary for the same class of
   mistake — inter-arrival calculations, window closing logic, sequence
   slicing (`L=10, K=5` indexing), and the live packet windower.
2. **Feature/column name drift.** The dataset has known landmines
   (`"Infilteration"` misspelling, `"Pkt Size Avg"` vs `"Avg Pkt Size"`).
   Check every place a column or feature name is referenced as a string
   literal — a typo here fails silently (produces zeros/NaNs) rather than
   erroring. Prefer: a single constants module for feature/column names if
   one doesn't already exist, so a typo becomes a `NameError` instead of a
   silent zero.
3. **Train/inference parity breaks.** Anywhere the live pipeline computes a
   feature differently from how the offline pipeline computed the same
   feature during training is a correctness bug even if it doesn't crash.
   Diff `packet_windower.py` against `window_builder.py` feature-by-feature.
4. **Scaling/threshold leakage.** Confirm nothing anywhere fits a scaler,
   picks a threshold, or computes a normalization statistic using
   validation or test data. Confirm the "one transform, one place" rule
   actually holds in code, not just in the docs — grep for any local
   `(x - mean) / std`-style logic that isn't going through
   `features/scaling.py`.
5. **Split integrity.** Confirm the chronological split + boundary purge
   logic is airtight — that no sequence spans the train/val or val/test
   boundary, and that random-seed-based shuffling isn't sneaking in
   anywhere (e.g. in a DataLoader default).
6. **Error handling that fails silently.** Anywhere a `try/except` swallows
   an exception without logging or surfacing it (especially in the live
   sensor / capture thread, which the docs say "dies silently" without
   Npcap) is a bug class to search for exhaustively, not just where it's
   already been found once.
7. **Config/state consistency.** `verify_state.py` exists specifically
   because `scaler.npz`, split `.npz` files, and `lstm_config.json` can
   drift out of agreement. Confirm this check is actually comprehensive —
   does it check every artifact that must stay in sync, or only some?
8. **API/frontend contract drift.** `web/lib/api.ts` is supposed to mirror
   `api/schemas.py` exactly. Diff them. A silently stale type on the
   frontend means a field renders `undefined` instead of erroring.
9. **Dead branches / unreachable rule logic.** In `mitre_mapper.py`, the
   rule engine is order-dependent ("first match wins"). Check whether any
   rule is unreachable because an earlier, broader rule always fires first
   on its inputs.

For each confirmed bug: log it in `AUDIT_LOG.md` with (a) exact
file/line, (b) why it's wrong, (c) what the correct behavior should be,
(d) blast radius (what else touches this code), (e) the fix, (f) the
verification you ran after fixing it.

---

## 4. Phase 3 — Codebase cleanup (dead files, clutter)

Cleanup is riskier than it looks in a hackathon repo — "unused" files are
sometimes fallback paths (e.g. the Streamlit app is an intentional fallback,
not dead code; `data/processed_60s_backup/` is an intentional backup from a
documented A/B test, not clutter).

Process:
1. **List candidates first**, do not delete on sight. A file is a genuine
   cleanup candidate only if it meets ALL of:
   - Not imported/referenced by any script, module, API route, or doc.
   - Not a documented fallback (check `README.md` and the runbook — the
     Streamlit fallback and the CACHED demo mode are load-bearing, not
     dead).
   - Not a generated artifact someone might rebuild from (be careful with
     `data/`, `models/`, and `notebooks/` — deleting a checkpoint or a
     backup is a one-way door if it can't be regenerated from a script).
   - Not referenced in git history as recently added for a reason you
     don't yet understand (check recent commits before deleting).
2. Present the candidate list with your reasoning in `AUDIT_LOG.md` and
   wait — do not delete anything without this list existing first, so a
   human can veto entries before you act.
3. For files you do delete: delete in small batches, re-run the smoke test
   and `verify_state.py` after each batch, and record exactly what was
   removed and why.
4. Also flag (don't necessarily delete) code smells that pollute
   readability even if not strictly "unused": duplicated logic that should
   call the shared function instead, commented-out old code blocks,
   inconsistent naming that makes the "one transform one place" rule harder
   to verify by eye.

---

## 5. Phase 4 — Regression safety protocol (run after EVERY change)

Before considering any single fix "done":

1. `python tests/smoke_synthetic.py` — must print `SMOKE TEST PASSED`.
2. `python scripts/verify_state.py` — must pass; if it was passing before
   your change and fails after, your change broke artifact consistency —
   revert or fix before proceeding.
3. If the change touches feature computation, scaling, or the model
   forward pass: re-check that `models/*.json` metrics are unchanged
   (unless the fix was specifically supposed to change them — e.g. fixing
   a real leakage bug *should* change metrics, and that's expected and
   good; document the before/after numbers either way).
4. If the change touches the live pipeline: re-run
   `python scripts/live_rehearsal.py --minutes 6 --attack udp-sweep
   --attack-at 0.3 --iface "\\Device\\NPF_Loopback"` if the environment
   supports it, and confirm exit code 0 (attack still flagged). If the
   sandbox can't run live capture (likely, since it needs Npcap/real
   packets), flag this for human verification instead of assuming it's
   fine.
5. If the change touches the API or the frontend contract: run
   `python scripts/check_api.py`.
6. Commit each verified fix as its own atomic commit with a clear message
   referencing the `AUDIT_LOG.md` entry. This is what makes rollback
   possible if something is discovered broken three fixes later.

**If a fix cannot be verified in this sandbox** (no GPU, no Npcap, no real
network interface), say so explicitly in the log rather than marking it
done. A human needs to know which fixes are "verified" vs. "implemented but
needs human verification on the demo laptop."

---

## 6. Phase 5 — "Does this make sense?" sanity pass

After bugs are fixed and clutter is removed, step back and evaluate, module
by module, whether the implementation actually does what its own docs claim
it does, or whether something is thinner than advertised (e.g., a rule that
never fires in practice, an explainability output that's static text rather
than derived from actual attribution values, a benchmark comparison that
isn't actually apples-to-apples).

If you find something that's currently weak-but-fixable **without needing
GPU retraining** (e.g., a rule engine threshold that's clearly wrong, an
explainability sentence-generator that ignores the real top features, a
frontend chart that silently drops data points):

1. Go back to **plan mode**: write out the problem, 2–3 possible fixes with
   trade-offs (effort vs. impact vs. risk of breaking something), and a
   recommendation.
2. Implement the recommended fix step by step, smallest viable change
   first.
3. Re-run the full verification protocol (§5).

If the weakness *does* require retraining or architecture changes (e.g.
improving recall, changing the model's task definition) — **do not touch
it here.** That's explicitly Packet 2's job.

---

## 7. Deliverables from this packet

- `AUDIT_LOG.md` — every bug found, every fix made, every verification
  result, every cleanup decision, every item explicitly deferred to
  Packet 2, with reasoning for each.
- A working, still-passing-`verify_state.py` codebase with atomic commits
  per fix.
- A short list at the end of `AUDIT_LOG.md` titled **"Needs human
  verification"** — anything you implemented but could not test yourself
  (mainly live-capture-dependent changes).
