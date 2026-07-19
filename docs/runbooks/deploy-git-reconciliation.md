# Deploy/Git Reconciliation Runbook

**Created 2026-06-26 (fundamentals-paydown, step 1 of deploy/git hygiene).**

## The situation

The live working tree at `/app/claude-gateway` — **what the crons actually run** —
sits on branch `fix/governance-autodemote-autonomy-forward`, which is **~101 commits behind `main` and ~6
ahead**. As of 2026-06-26 the entire physical state was **checkpoint-committed and pushed** (commit `af3720d`),
so the tree is now CLEAN and fully recoverable — there is no longer any untracked/unstaged limbo at risk of a
`git clean`/`reset`. The crons were not disrupted (a commit does not change the physical files).

**Deploy-copy drift is already resolved:** 0 Cronicle jobs run the old un-versioned `/home/app-user/scripts/`
copies — they all run the repo path. (Verified 2026-06-26.)

## What is genuinely local (must be preserved on advancement)

- **Operator WIP — the unified-guard disable** in `.claude/settings.json` (main has the guard ON; the operator
  deliberately removed `unified-guard.sh` from the dispatched hook chain). **Intentional — do not revert.**
- **3 unique ahead-commits** (`git cherry origin/main HEAD` → 3 of the ahead set): Loop-Engineering benchmark
  docs, the proactive-discovery scan feat, and the wip-checkpoint.
- **The stranded reconcile changes** in `scripts/reconcile-completed-sessions.py` — the dark-fix
  `_post_archive_side_effects` + langfuse export + session obs_log shipping + the 2026-06-26 OTLP `--otlp`
  fresh-push. main has **0** refs to `_post_archive_side_effects`; the diff vs main is **+187 / -3** (the 3
  deletions mean a blind file-copy would revert 3 lines of main → needs a real merge, not a copy).

## Why this is NOT done autonomously

Per the standing rule (`memory/gateway_governance_branch_is_active_wip_20260624`): **don't clean/reset/rebase
blind.** A merge/rebase of a 101-behind branch conflicts heavily (~8 markers historically); resolving those
blind risks reverting the operator's unified-guard choice or the live MemPalace hooks. While the operator is
AFK there is no one to adjudicate the conflicts, so the safe action was preservation + this plan.

## Recommended staged advancement (operator-supervised)

1. **Confirm the backup:** the branch is pushed; `git log af3720d` is the recoverable record. ✓ (done)
2. **Land the stranded reconcile on main first** (so the dark-fix infra exists on main): open an MR that
   merges *just* `reconcile-completed-sessions.py`'s good changes onto main — a 3-way merge, NOT a copy
   (the -3 deletions must be reviewed). Verify `_post_archive_side_effects` runs + the 4 side-effects land.
3. **Cherry-pick the 3 unique ahead-commits** onto main (Loop docs, proactive-discovery) if still wanted.
4. **Decide the unified-guard disable:** keep it as a deliberate off-main operator choice (re-apply after
   advancement) OR land it on main if the decision is now permanent. Do NOT silently revert it.
5. **Advance the working tree:** once main holds everything above, `git merge origin/main` on the branch (or
   move the working tree to a fresh main-based branch), resolving the now-smaller conflict set, then re-apply
   the unified-guard disable. Verify the crons still run cleanly (`scripts/qa/run-qa-suite.sh`).
6. **Add a drift guard:** a weekly check that `HEAD` is not >N commits behind `origin/main` (or that the
   running scripts match a committed ref) so this can't silently re-accrue.

## Per-file stale audit (run when advancing)

`git diff origin/main --stat` on the checkpoint shows the exact divergence. Most "deletions" are this
session's work that main already has via separate MRs (redundant); the real review set is the genuinely-local
list above. Spot-check any RUNNING script that shows a large delta and is NOT in that list — that is a
genuinely-stale running script (a prior-session main improvement not yet in the live tree).
