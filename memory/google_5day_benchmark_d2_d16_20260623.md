# Google 5-Day AI Agents course — new benchmark (Source #10) + D2/D16 remediation

**Date:** 2026-06-23 · **Issues:** IFRNLLEI01PRD-1260 (D2), -1267 (D16)

## The benchmark
Introduced the **"5-Day AI Agents: Intensive Vibe Coding Course With Google"** (Kaggle x Google Cloud) as **Source #10** of the agentic Master Scorecard. Two reports in `docs/`:
- `google-5day-ai-agents-course-knowledge.md` — the standard + a **16-dimension rubric** (D1–D16).
- `google-5day-ai-agents-gap-analysis.md` — file-grounded scorecard. **Overall B+ (3.61/5)**, −1.18 below the prior 9-source A+ 4.79 aggregate. Hardest benchmark yet; gap concentrated in *the cage* (D10 blast-radius C−) and *the contract* (D2 spec-driven). Standout: D3 structured-grounding A. Also `docs/benchmark-standards-catalog.md` (108 standards).

Dimensions below A−: **D10** C−, **D9/D11** B−, **D13/D14/D16** B, **D6** B+ (D2 lifted out, see below).

## D2 — Spec-driven development: B− → **A− (4.5)** (shipped, CI-green)
Targeted slice (NOT full-estate; `adr/0001` records the scope decision — gateway is ~71k SLOC ops code, "code regenerable from spec" is product-dev framing). Root `PROJECT.json` + `constitution.md` (7 articles) + `spec/` (7 contexts, EARS + **executable** Gherkin via `scripts/run-spec-bdd.py`, OpenAPI/AsyncAPI/JSON-Schema) + **content-aware lockstep** (`scripts/check-spec-code-lockstep.py` + `spec/.lockstep.lock`, semantic-hash drift detection) + practiced **git-auditable red-green** (`be8fea1` RED → `316aea7` GREEN). CI `validate_spec`, QA `test-1260` (15/15), holistic §40. Commits `6c2173d`→`316aea7`. **Ceiling: A** (relevance-aware lockstep + deeper orchestration scenarios would reach it; literal 5.0 needs whole-estate regeneration, declined). 4 adversarial re-audits, each verified by execution.

## D16 — Closed-loop self-improvement: B (3.75) → **A− (4.4)** (shipped, CI-green)
Closed the 3 named gaps (`ae87627`, e2e proof `ee7b82b`):
- **S1 (marquee):** `run_decomposition()` implemented in BOTH lanes (`scripts/parallel-dev/planner-decompose.py` + `bootstrap-pack/`) — was `NotImplementedError`. `claude -p` architect → fenced-JSON DAG → existing `validate_work_units()` → `RuntimeError` fail-safe (mirrors GEPA, no API key). **Live-proven**: real `claude -p` produced a valid 3-task DAG (sessions 222a15ab/607251a9/e57dc830, 2026-06-23).
- **S2 (safety):** holdout-integrity-gated **human-review checkpoint** on the live prompt-patch self-mod loop (`prompt_patch_trial._promotion_checkpoint`, default OFF = byte-identical legacy; flags `PROMPT_PROMOTION_REVIEW`/`_HOLDOUT_GATE` + `~/gateway.*` sentinels) + `scripts/apply-prompt-promotion.py` circuit-breaker. **E2E-proven**: a real Welch winner (p=7.5e-12) routes finalize→checkpoint→held→operator-apply→live; flags-off auto-promotes.
- **S3 (loop closure):** `scripts/mine-failures-to-evals.py` mines recurrent `(host,rule)` failures from triage.log → discovery eval cases (dry-run default, dedup; 47 real recurrences found).
- Enforcement: QA `test-1267` 9/9, holistic §41, strict e2e `scripts/qa/e2e/test-1267-self-improvement-e2e.sh` 3/3.
- **Ceiling: A.** Capped below by (a) miner not cron-wired → loop not *autonomously* closed; (b) checkpoint safer-posture defaults OFF; (c) parallel-dev orchestration "body" intentionally out of scope. Literal A+ not honestly reachable for the scoped slice.

### Follow-up (same day): autonomy-by-default + flake fixes (commits `967c593`, `31b6ee0`)
Operator asked to make autonomy the default + fix the pre-existing QA flakes.
- **Self-mod loop now AUTONOMOUS BY DEFAULT** with a holdout-integrity safety rail (default ON): winner auto-promotes when the sealed eval baseline is clean; HELD only if contaminated; proceeds-with-warning if unverifiable (infra flakiness never stalls). `PROMPT_PROMOTION_REVIEW=1`=opt-in human hold; `PROMPT_PROMOTION_HOLDOUT_GATE=0` (or `~/gateway.prompt_promotion_holdout_gate_off`)=disable rail. **Proven e2e** (real Welch winner→auto/held/applied).
- **Failure→eval loop cron-wired** (live crontab `35 4 * * 0`, guarded `[ -f ]` no-op until host runs main): weekly miner `--apply` into the DISCOVERY set (exploration, non-gating = the safe boundary; regression gate stays curated). holistic §41 `failure-eval-cron`.
- **2 pre-existing flakes FIXED**: (1) **643-concurrent** ~50%→deterministic — root cause was PRAGMA ORDER in `handoff_depth._connect` (`busy_timeout` set AFTER `journal_mode=WAL`, so the WAL switch ran with 0ms timeout → 'database is locked' under contention, ~1/8 bumps lost in read()->_connect NOT bump's txn); fix = busy_timeout FIRST + retry. (2) **bench** timing p95 spikes under host load — honored the file's own "warn-only" intent via `bench_soft_lt` (warns at soft target, hard-fails only >10x = catastrophe). Lesson: [[feedback_sqlite_busy_timeout]] — set busy_timeout BEFORE journal_mode=WAL.
- **Deploy-caveat**: all live on `main`; the self-mod default activates on the live `finalize-prompt-trials` cron and the miner cron activates once the host working copy has the code (operator on a feature branch). The parallel-dev execution BODY (autonomous coder dispatch+merge) remains out of scope, operator go-ahead required.

## Method notes / lessons
- Each dimension lifted in an isolated **git worktree off origin/main** (operator's uncommitted feature-branch work untouched), direct-push to main per `[[feedback_direct_push_repos]]`, every claim **adversarially re-audited by execution**, honest **A ceiling** reported rather than gaming to "A+++".
- Hermetic-test lesson: classifier/self-mod tests must isolate `HOME` + neutralize `AUTONOMY_SMS_URL` (the host has autonomy-forward ON + a live Twilio bridge on :9106). See agent-memory `feedback_isolate_home_for_classifier_tests`.
