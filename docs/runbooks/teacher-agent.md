# Runbook: Teacher Agent

**Service:** `scripts/teacher-agent.py` (orchestrator) + `claude-gateway-teacher-runner` n8n workflow (id `bGnU1YRaDMA21pna`, ACTIVE)
**Matrix classroom:** `#learning` (`!HdUfKpzHeplqBOYvwY:matrix.example.net`) — membership-based authorisation
**Plan doc:** `docs/plans/teacher-agent-implementation-plan.md` (IFRNLLEI01PRD-651 through -655)
**Tests:** `scripts/qa/suites/test-65[1-5]-teacher-agent-*.sh` — 62/62 PASS across five tiers

This runbook covers ops for the teacher agent: alert response, cron management, operator lifecycle, and the rollback ladder.

## Architecture at a glance

```
#learning room (auth)
        │
        │  !learn / !quiz / !progress / !digest / !leaderboard / !skip / !teach / !grade
        ▼
matrix-bridge Detect Command → Fire Teacher Command (HTTP POST)
        │
        ▼
n8n teacher-runner (webhook /teacher-command)
   → Parse Command (dispatch CLI flags)
   → SSH to app-user@nl-claude01
      python3 scripts/teacher-agent.py <flags>
   → teacher-agent.py posts its own Matrix DM to the operator
   → returns JSON status → logged by n8n
```

## Data surfaces

| Table | Rows | Purpose |
|---|---|---|
| `learning_progress` | per (operator, topic) | SM-2 state + Bloom band + mastery score |
| `learning_sessions` | append-only | every lesson/quiz/grade event |
| `teacher_operator_dm` | per operator | DM room cache + `public_sharing` opt-in |
| `curriculum.json` | 53 topics | foundations 11 / Gulli patterns 15 / platform 20 / memory 7 |

## Prometheus signals

| Metric | Meaning |
|---|---|
| `learning_topics_total{operator}` | curriculum coverage for the operator |
| `learning_topics_mastered{operator}` | mastery_score >= 0.9 |
| `learning_topics_due{operator}` | next_due <= now AND paused=0 |
| `learning_quiz_accuracy_7d{operator}` | avg quiz score over last 7 days |
| `learning_weekly_sessions_total{operator}` | rolling 7-day session count |
| `learning_longest_streak_days{operator}` | consecutive-day session streak |
| `learning_bloom_distribution{operator,bloom_level}` | distribution at each band |
| `learning_operators_total` | `teacher_operator_dm` row count |
| `learning_morning_nudge_last_run_timestamp` | mtime of nudge lockfile |
| `learning_class_digest_last_run_timestamp` | mtime of digest lockfile |

Grafana dashboard: uid `teacher-agent` (title "Teacher Agent — Learning Progress"), 12 panels.

## Alert response

### `TeacherAgentMetricsAbsent` (exporter dead 15m)

The `*/5` cron `scripts/write-learning-metrics.sh` stopped writing to `/var/lib/node_exporter/textfile_collector/learning_progress.prom`.

1. Confirm the cron is enabled:
   ```
   crontab -l | grep write-learning-metrics
   ```
2. Run the exporter by hand and look for errors:
   ```
   bash /app/claude-gateway/scripts/write-learning-metrics.sh
   ls -la /var/lib/node_exporter/textfile_collector/learning_progress.prom
   ```
3. If the textfile dir itself is missing, the host's node_exporter config drifted — check the running config, *do not* silently recreate. Two paths coexist in the repo: `/var/lib/node_exporter/textfile_collector/` (this host's live one) and `/var/lib/prometheus/node-exporter/` (referenced by newer scripts; not mounted here). Use the env `PROMETHEUS_TEXTFILE_DIR=...` for one-off redirects.

### `TeacherAgentMorningNudgeStale` (no nudge 36h)

The daily 08:30 UTC nudge cron didn't touch `/var/lib/claude-gateway/teacher-morning_nudge.last` for 36h.

1. Check the log: `tail /home/app-user/logs/claude-gateway/teacher-morning-nudge.log`
2. Run by hand with a dry operator list to reproduce:
   ```
   python3 scripts/teacher-agent.py --morning-nudge
   ```
3. If Matrix auth fails, the bot token rotated. Compare `.env` `MATRIX_CLAUDE_TOKEN` against the Element account. (This never required a rotation since the token was issued; rotation is manual.)

### `TeacherAgentClassDigestStale` (no digest 14d)

Same pattern as above for the Sunday 16:00 UTC digest cron. Two consecutive missed weeks → operator won't see aggregate activity.

## Operator lifecycle

### Add a new operator

1. Invite them to `#learning` in Element. Membership grants auth; no DB row needed.
2. On their first `!learn`, teacher-agent lazy-creates a `teacher_operator_dm` row and a Matrix DM.
3. Public sharing defaults OFF — the operator must `!learn public on` to appear in leaderboards or post `!progress public`.

### Pause a misbehaving operator (or pause self)

```
scripts/teacher-agent.py --pause --operator '@name:matrix.example.net'
```

Sets `learning_progress.paused=1`. Morning-nudge skips them. Reverse with `--resume`. State is preserved.

### Remove an operator

- From the classroom: kick from `#learning` in Element. Authorisation gate now fail-closes on every command.
- From the DB: **do NOT delete** — Invariant #2 (memory never shrinks) forbids it. Pause them instead. If GDPR-style erasure is genuinely required, document the request out-of-band before running the DELETEs.

## Maintenance mode interaction

Teacher crons do NOT check `/home/app-user/gateway.maintenance` — they're learning-side, not alert-side. If you want them suppressed during a long maintenance:

1. Pause every operator: `for op in $(sqlite3 .../gateway.db 'SELECT operator_mxid FROM teacher_operator_dm'); do scripts/teacher-agent.py --pause --operator "$op"; done`
2. OR comment the 3 teacher crontab lines and `crontab /tmp/saved.crontab`

Reverse after the maintenance window.

## Debugging "!learn is silent in #learning"

Most common culprit is the webhook → SSH → Matrix-DM chain breaking midway. Work backward:

1. **DM not arriving?** Check the n8n execution log for workflow `bGnU1YRaDMA21pna`. If the SSH node errors with "Credential … does not exist for type sshPassword", the cred key got swapped. Fix is to restore `authentication=privateKey` + `credentials.sshPrivateKey` (known-failure rule #3 in `.claude/rules/workflows.md`).
2. **Webhook returned 200 with `{"ok":true}` but no DM?** teacher-agent.py succeeded but bounced before Matrix. Check the live Matrix token and that the bot is still in `#learning`.
3. **Webhook 404?** matrix-bridge didn't dispatch. Verify the bridge's Fire Teacher Command node still points at `http://nl-n8n01:5678/webhook/teacher-command` and the Command Router Switch has the `teacher` outputKey rule with `conditions.options` (known-failure rule: n8n 2.41.3 Switch V3.2 bug — missing `options` block causes extractValue crash).
4. **Bridge never detected the command?** Extract Messages has to include `#learning` in its ROOM_MAP (`!HdUfKpzHeplqBOYvwY:matrix.example.net` → `learning`) and have the `isAllowed(sender, roomId)` helper that whitelists that room for membership-based auth.

Live smoke:

```
curl -sS -X POST http://nl-n8n01:5678/webhook/teacher-command \
  -H 'Content-Type: application/json' \
  -d '{"operator_mxid":"@dominicus:matrix.example.net","source_room_id":"!HdUfKpzHeplqBOYvwY:matrix.example.net","command":"learn","arg":"","session_id":0}'
```

Expected: `{"ok":true,"dm_room_id":"!…","event_id":"$…","topic_id":"gulli-01-tool-use"}`. A new DM event appears in the operator's room.

## Host bootstrap

After a rebuild of `nl-claude01`, install the tmpfiles.d rule that
pre-creates the lockfile directory before the first cron fires:

```bash
sudo install -m 644 -o root -g root \
  /app/claude-gateway/scripts/setup/tmpfiles-claude-gateway.conf \
  /etc/tmpfiles.d/claude-gateway.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/claude-gateway.conf
```

Without this step, `teacher-agent.py._touch_last_run()` logs a warning and
the stale-cron Prometheus alerts never get a fresh timestamp to compare
against (they would anchor on epoch 0 forever, tripping the 36h /14d
thresholds trivially).

## Wiki hosting (https://wiki.example.net/)

Teacher lesson/quiz/grade DMs cite sources as clickable links into the
mkdocs-material build at `wiki.example.net`. Stack:

| Layer | What | Where |
|---|---|---|
| Source | `docs/**`, `wiki/**`, `README.extensive.md` in this repo | claude-gateway |
| Build | `mkdocs-material` via `scripts/build-wiki-site.sh` | `/home/app-user/.wiki-venv/bin/mkdocs` |
| Serve | Caddy systemd service, `/etc/caddy/Caddyfile` | `nl-claude01:8080` |
| TLS + public hostname | nginx-proxy-manager upstream | `wiki.example.net` |
| Deep link map | `scripts/lib/wiki_url.py` | teacher-agent renderers |

### Build cycle

Manual rebuild after editing docs/wiki content:

```bash
bash scripts/build-wiki-site.sh
```

Builds into `wiki-site/site/`. Caddy serves that directory directly —
no reload needed, it picks up new files on the next request. The build
unifies `docs/`, `wiki/`, and `README.extensive.md` into a single
`wiki-site/site-src/` tree before running `mkdocs build`.

Dev mode (live-reload on file change, localhost only):

```bash
bash scripts/build-wiki-site.sh --serve
# browse http://127.0.0.1:8000
```

### Caddy service

`/etc/caddy/Caddyfile` binds to `10.0.181.X:8080`, serves
`/app/claude-gateway/wiki-site/site` with
gzip/zstd compression. Access logs in JSON at
`/var/log/caddy/wiki-access.log` (50 MB rollover, 3 kept).

```bash
systemctl status caddy       # running?
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

Config source-of-truth committed at `scripts/setup/Caddyfile-wiki` for VM
rebuild.

### Deep-link URL shape

mkdocs-material's default heading anchors are generated by
`pymdownx.slugs.slugify(case=lower)`. `scripts/lib/wiki_url.py.slugify`
matches that algorithm byte-for-byte (verified against live HTML output).
URL template:

```
https://wiki.example.net/<path-without-.md>/#<slug(section)>
```

Examples:

- `docs/agentic-patterns-audit.md` + `Summary Scorecard (updated 2026-03-29)` →
  `…/docs/agentic-patterns-audit/#summary-scorecard-updated-2026-03-29`
- `wiki/services/grafana.md` + `""` → `…/wiki/services/grafana/`
- `scripts/anything.py` + `*` → `None` (non-wiki-served path; renderer falls back to inline)

If a section name doesn't correspond to an actual heading (common for
Gulli patterns — they're table rows, not headings), the browser just
ignores the anchor hash and lands on the page top. Harmless.

### Integration with teacher DMs

`scripts/lib/wiki_url.linkify(source_path, section)` is called by
`_render_lesson`, `_render_quiz`, and `_render_grade`. It wraps the source
citation in `[label](url)` markdown, which `matrix_teacher.md_to_html`
converts to `<a href>` in the Matrix `formatted_body`. Element renders
the link clickable.

### Troubleshooting

**Link 404 in the browser:** the source path is on-disk but wasn't built.
Check `wiki-site/site/<path>/index.html` exists. If missing, confirm
`build-wiki-site.sh` completed without errors; note non-fatal warnings
about "unrecognized relative link" are benign.

**Link lands on page top instead of the correct anchor:** the section name
didn't slug-match a heading on the page. Either the source doc lacks a
heading for that content (common for table rows), OR the slugify algorithm
drifted from pymdownx's. Re-run the QA: `wiki_url_slug_matches_pymdownx_samples`.

**Caddy 503 / connection refused:** `systemctl status caddy` +
`journalctl -u caddy --since '5 minutes ago'`. Nginx-proxy-manager will
return 502 upstream if Caddy is down.

**Rebuild cadence:** build is manual for now. Consider a cron after
`wiki-compile.py` (daily 04:30 UTC) if wiki content churn accelerates.

## Rollback ladder

Stage 1 — **Pause one or all operators** (immediate, reversible):
```
scripts/teacher-agent.py --pause --operator '@name:…'
```

Stage 2 — **Disable crons** (comment the 3 `# Teacher agent loop tier` lines in `crontab -l`).

Stage 3 — **Deactivate the n8n workflow** (`bGnU1YRaDMA21pna`) from the UI. Webhooks go 404; matrix-bridge Fire Teacher Command gets a neverError-suppressed failure.

Stage 4 — **Suppress Matrix commands**: revert the Detect Command teacher-alias block + Command Router Switch rule in `claude-gateway-matrix-bridge.json` via `n8n_update_partial_workflow`. State is preserved; the classroom just goes quiet.

Stage 5 (**nuclear**, do NOT run without operator sign-off) — drop `learning_progress` + `learning_sessions` + revert migration 013/014:
```
sqlite3 .../gateway.db "DROP TABLE learning_progress; DROP TABLE learning_sessions; DROP TABLE teacher_operator_dm;"
```
…and delete the corresponding rows from `schema_migrations` + `scripts/lib/schema_version.py` entries. Loses every operator's progress history.

## Invariant audit

Run `scripts/audit-teacher-invariants.sh` any time. Read-only, covers:

- **#1** read-only tool allowlist (no Edit/Write/MultiEdit)
- **#2** no DELETE against `learning_*` / `teacher_operator_dm`
- **#3** mastery_score writes confined to grader path (`cmd_grade` / `_upsert_progress`)
- **#4** `grader_confidence < CONFIDENCE_THRESHOLD (0.6)` forces a `clarifying_question`
- **#5** three-tier pipeline intact (T1 renderers + T2 LLM libs + T3 operator path)
- **#6** `learning_sessions.completed_at IS NULL` means resumable (warns if >24h stale)
- **Privacy** `teacher_operator_dm.public_sharing DEFAULT 0`

Exits 0 iff all pass. Wire into weekly audits or holistic-health as needed.

## Calibration

Grader calibration baseline: `scripts/teacher-calibration-baseline.py`. Three modes:

### Synthetic fixtures (smoke / CI)

12 fixtures across 5 score bands (excellent / good / partial / wrong / irrelevant) at `scripts/qa/fixtures/teacher-calibration-fixtures.json`. Target agreement ≥85%.

- `--offline` → deterministic grader stub (used by QA, no Ollama).
- live mode (default) → calls real Ollama via `quiz_grader.grade`.

Writes a JSON report to `scripts/qa/reports/calibration-<stamp>.json`. Run it whenever the grader prompt, model, or rubric schema changes. A sustained live-mode drop below 85% means the grader regressed — re-prompt or re-tune fixtures.

### Real-data baseline (planned)

Once the classroom has accumulated ≥20 completed quizzes, establish the production calibration baseline:

```bash
# 1. Dump recent completed quizzes to a review template.
python3 scripts/teacher-calibration-baseline.py \
    --export-for-review /tmp/review.json --limit 50

# 2. Operator opens the file, reads each question+answer, sets
#    `operator_band` to excellent/good/partial/wrong/irrelevant reflecting
#    their own judgment (independent of the grader's score). Leaves
#    `operator_band = null` on rows they skip.

# 3. Ingest the reviewed file and compute grader-vs-operator agreement.
python3 scripts/teacher-calibration-baseline.py \
    --from-reviewed /tmp/review.json --threshold 0.85
```

Exit 0 iff agreement ≥ threshold. The JSON report at `scripts/qa/reports/calibration-reviewed-<stamp>.json` lists every pass/fail row with operator-override notes, useful for tuning `quiz_grader.py` rubric + prompt. Re-run after each grader prompt iteration.

## Related reading

- `docs/plans/teacher-agent-implementation-plan.md` — full design spec
- `.claude/agents/teacher-agent.md` — agent definition + read-only allowlist
- `scripts/lib/matrix_teacher.py` — Matrix client + markdown→HTML converter
- `scripts/lib/sm2.py` — SuperMemo-2 scheduler
- `scripts/lib/bloom.py` — 7-level Bloom progression
- `scripts/lib/quiz_generator.py` / `quiz_grader.py` — LLM tier with hallucination gate
- `memory/teacher_agent_foundation.md` — tier-by-tier landing notes
