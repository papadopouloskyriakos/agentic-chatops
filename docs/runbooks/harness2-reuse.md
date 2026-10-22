# Harness² reuse — what the gateway borrowed from google-research/harness2 and how to run it

Source: [google-research/harness2](https://github.com/google-research/harness2) @ `1cfe254` (Apache-2.0), paper arXiv 2610.14224 (Xu et al., 2026-10-09). Full comparison and decision record: the plan this batch was built from is reproduced in `memory/harness2_reuse_batch_20261022.md`.

Harness² refines an agent's *harness* (8 editable files around a frozen model: system prompt, guardrails, memory, tool guidance always on; skills, subagents, scripts on demand; a hook inside the tool loop) per task with a Propose → Probe → Compose step and distils a per-domain library of `{cue, lesson, evidence, confidence}` entries. We did **not** adopt the probing loop (an infra incident is not re-runnable and a step costs about seven sessions). We adopted its surface discipline, evidence hygiene, validator, provenance and reflection record. Six items, each with a QA suite:

| # | Item | Entry points | QA suite |
|---|---|---|---|
| R1 | Always-on budget + form-before-prose rule | `scripts/audit-always-on-budget.sh`, holistic §50, `CLAUDE.md` "Form before prose", GEPA generator lens text | `test-always-on-budget.sh` |
| R2 | Evidence boundary + grader-verdict tripwire | `scripts/lib/evidence_guard.py` (wired into `kb-semantic-search.py` output and `archive-session-transcript.py` chunks), Build Prompt `IMPORTANT:` block, chatops-workflow skill, all 11 agents | `test-evidence-guard.sh` |
| R3 | Harness fingerprint on every session | `scripts/lib/harness_fingerprint.py`, hook `scripts/hooks/harness-fingerprint.sh` (UserPromptSubmit + SessionEnd in `config/dispatched-session-settings.json`), `scripts/stamp-harness-fingerprint.py`, trial finalizer restriction (`lib/prompt_patch_trial.py::arm_fingerprints`), judge key `(issue_id, session_id)` | `test-harness-fingerprint.sh` |
| R4 | Harness tree validator with prose feedback | `scripts/lib/harness_tree.py` (vendored), `scripts/validate-harness-tree.py` | `test-harness-tree-validator.sh` |
| R5 | Structured reflection record, per-domain library | `scripts/lib/reflection.py`, `scripts/reflect-session.py`, reconciler hook in `reconcile-completed-sessions.py`, `lessons_learned` v2 columns | `test-reflection-record.sh` |
| R6 | Flywheel identity check (dead-pipeline detector) | `scripts/check-flywheel-identity.py`, holistic §49, alerts `GatewayFlywheelIdentityBroken` / `GatewayFlywheelMetricsStale` | `test-flywheel-identity.sh` |

Schema: migration `scripts/migrations/029_harness_fingerprint_and_reflection.sql` (tables `harness_fingerprints`, `session_harness`; `sessions.harness_fp`, `session_log.harness_fp`; `lessons_learned` v2). Registry bumped in `scripts/lib/schema_version.py`.

## Daily use

```bash
# Where does always-on text stand? (warn >32 KB, fail >48 KB per repo)
bash scripts/audit-always-on-budget.sh

# Does the harness tree validate? (untriggered skills, missing scripts, hooks shape, cap)
python3 scripts/validate-harness-tree.py --runner-build-prompt workflows/claude-gateway-runner.json

# Did every session that ended 2h..26h ago reach every eval stage?
python3 scripts/check-flywheel-identity.py            # exit 0 ok / 1 broken / 3 idle
python3 scripts/check-flywheel-identity.py --out      # also writes flywheel_identity.prom

# Which harness did a session run under?
python3 scripts/lib/harness_fingerprint.py --repo ~/gitlab/infrastructure/nl/production --json
sqlite3 ~/gateway-state/gateway.db "select session_id, issue_id, harness_fp from session_harness order by stamped_at desc limit 5"

# Reflect on one session by hand (model: gemma3:12b via the gateway Ollama generate port)
python3 scripts/reflect-session.py --issue IFRNLLEI01PRD-1234 --dry-run

# Is anything carrying grader output?
python3 scripts/lib/evidence_guard.py some-file.txt
```

## Kill switches and fail-open behaviour

- `REFLECTION_DISABLED=1` — `reflect()` returns `NO_ENTRY` without a model call. The reconciler hook is fail-open (`reflect-session.py` always exits 0).
- The fingerprint hook is exit-0 telemetry with a 10 s timeout; a DB error is logged to `~/logs/claude-gateway/harness-fingerprint.err` and ignored.
- The evidence guard never raises inside writers: an offending RAG line or transcript chunk is **dropped and logged** to `~/logs/claude-gateway/evidence-guard.jsonl`. If it fires, find the read path that leaked grader output. Do not widen the marker list.
- The trial finalizer restricts arms to the dominant `harness_fp` only when ≥ 2 fingerprints are stamped on a trial; unstamped (pre-023) assignments keep the legacy pooled comparison.
- `check-flywheel-identity.py` treats "no eligible session" as **idle** (holistic WARN), never FAIL: a quiet lane is not a broken one. FAIL means sessions ended and a stage is missing.

## Deploy status — DONE 2026-10-22

1. Migration **029** applied on nl-claude01 (numbered 029 because `schema_migrations` already carried a legacy `023` row that made `apply.py --status` report the new file as applied while the tables were missing — verify against the schema, not the table).
2. Cronicle: `flywheel-identity` id `emvjyrfesn5` (hourly at :07, exit 3 = idle mapped to success) and `stamp-harness-fingerprint` id `emvjyrfh4n6` (:03/:18/:33/:48); registered by `registry-seed.py` as `check-flywheel-identity`, `stamp-harness-fingerprint`, `prom:flywheel_identity`.
3. IaC twin: infra MR 669 applied via Atlantis and merged; both rules verified in the NL cluster PrometheusRule `agentic-health-alert-rules`.
4. `~/.claude/agents/` re-synced from `.claude/agents/` (it is a copy, not a symlink — repeat after any agent edit).
5. Live Runner Build Prompt: versionId `f367e18b` (2026-10-22 19:38Z); rollback snapshot `/tmp/claude-gateway-runner.rollback.json`.

## Findings this batch established (verified 2026-10-22)

- Dispatched sessions **cannot invoke the chatops-workflow skill on demand** even when it is discoverable (`~/.claude/skills/<name>` symlinks added; a `claude -p` session in the infra repo lists the skill but invocation fails). The inlined copy in Build Prompt is therefore load-bearing; `check-skill-parity.py` stays.
- `validate-harness-tree.py` on this repo: always-on 171,591 chars (3.6× the cap), `proactive-discovery` and `team-formation` never triggered anywhere, `.claude/rules/infrastructure.md` invokes `scripts/trigger-proactive-scan.sh` which no longer exists.
- The eval flywheel has been idle/dark since 2026-08-26 (no `session_log` rows, no non-CLI transcripts, 2 judgments in October); §49 reports it as idle until the Runner → Session End path produces sessions again. Operator decisions for that are tracked in YouTrack (see the batch memory).

## Follow-ups (2026-10-23, MR !269)

- **Domain-first lessons in Build Prompt:** `scripts/domain-lessons.py --issue ID --summary S --description D [--b64]` renders the last entries of the session's domain; the Runner's Query Knowledge node emits it as `DOMAIN_LESSONS_B64` and Build Prompt injects `<domain_lessons>` before the similarity hits (live versionId `fb1dc29b`). The category is classified server-side by `lib.reflection.classify_alert_category`, a parity-tested mirror of the Build Prompt regex table: if you change one, change both (`test-domain-lessons.sh` fails otherwise).
- **`llm_usage.harness_fp`** (migration 030): filled by issue_id by the stamp job; cost can be grouped by harness version.
- **`metamorphic-monitor.sh`** compares `react_v1`/`react_v2` only within the dominant `harness_fp` of the window (prints the restriction; "none" until stamped rows exist).
- **MR review gate:** `scripts/mr-review.sh` runs the harness tree validator on the MR head and on main for any harness edit in project 30; NEW problems are quoted back and the verdict is forced to REQUEST_CHANGES. The `/review` command has the same step 4.
- **Prompt patches carry a form** (`PATCH_FORM` in `prompt-improver.py`): skill-form patches are trigger lines, not paragraphs.
- **Reflection calibration (open):** replay of 26 archived sessions gave 17 entries / 9 NO_ENTRY with gemma3:12b; consider accepting only `confidence=high` entries or re-judging before storage.

