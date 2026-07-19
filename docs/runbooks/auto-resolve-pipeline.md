# Auto-resolve pipeline — operations + troubleshooting

End-to-end path an alert takes, and how to verify/debug it. Repaired 2026-06-17 (it was
dark for months across several layers — see `memory/pipeline_autoresolve_repair_20260617.md`).

## The flow

```
alert (LibreNMS / Prometheus)
  -> n8n receiver (/webhook/prometheus-alert, /security-alert, ...)
  -> SSH claude01: scripts/run-triage.sh <k8s|infra|security|correlated>
       -> openclaw/skills/<k8s|infra>-triage.sh   (L1: investigate, post YT comment)
          -> Tier-1 suppression (scripts/lib/tier1_suppression.py): known-transient /
             dedup / blast-radius  -> SUPPRESS (no escalation) or pass through
          -> escalate (critical / low-confidence / always-for-infra)
             -> escalate-to-claude.sh -> POST /webhook/youtrack-webhook
  -> Runner workflow (qadF2WcaBsIR7SWG)
       Build Plan -> Classify Risk (classify-session-risk.py -> session_risk_audit + band)
       -> Build Prompt (injects the band's [AUTO-RESOLVE]/[POLL] directive)
       -> Launch Claude session -> Prepare Result -> Post to Matrix
  -> reconcile-completed-sessions.py (cron */15): archive + band-aware YT close
       AUTO/AUTO_NOTICE -> Done ; completed/unknown -> To Verify ; POLL -> leave for human
```

## One-command diagnosis

Every stage logs a JSON line keyed by issue_id. **Follow any incident end-to-end:**
```bash
grep <ISSUE-ID> /home/app-user/logs/claude-gateway/pipeline-debug.log
```
You should see: `triage_start` -> `escalate_decision(escalate=yes)` -> `escalate_result(http=200)`
-> `invoke(autonomy_forward=True)` -> `stdin(length=NNNN)` -> `classified(band=...)` ->
`audit_write(outcome=ok)` -> later `reconcile_session(yt_state=Done|To Verify)`.

**Red flags in the log:** `stdin length=0` + `plan_parse_fail` = an upstream n8n node is
passing an empty plan (the expression-mode/Buffer bug — see
`memory/feedback_n8n_expression_mode_and_buffer.md`); `audit_write outcome=failed` = DB
lock; `escalate_result http!=200` = the Runner webhook is unreachable.

## Quick health checks

```bash
DB=/home/app-user/gateway-state/gateway.db
sqlite3 $DB "SELECT count(*), max(classified_at) FROM session_risk_audit;"   # gate recording?
sqlite3 $DB "SELECT count(*) FROM sessions;"                                  # should stay low (<~100)
sqlite3 $DB "SELECT max(ended_at) FROM session_log;"                          # archival current?
crontab -l | grep reconcile-completed-sessions                               # close-out cron present?
python3 scripts/reconcile-completed-sessions.py --dry-run                    # what it would close now
scripts/audit-risk-decisions.sh                                              # band invariant (never auto a floor signal)
```

## Knobs / kill-switches

- **Autonomy-forward gate:** `~/gateway.autonomy_forward` + `~/gateway.autonomy_session_sms`
  sentinels (`touch`=on, `rm`=off). When ON, AUTO/AUTO_NOTICE auto-resolve; the irreversible
  floor (mkfs/dropdb/zpool destroy/terraform destroy/reboot -> POLL_PAUSE) is active.
  **Note:** turning it OFF reverts to legacy risk handling, which is *less* strict on
  destructive ops — keep it ON.
- **Reconciler:** `--dry-run`, `--backfill` (drain a session backlog), `--recent-h N`
  (only change YT state for sessions newer than N h), `--min-idle-min`, `--max-per-run`.
- **Suppression:** host-agnostic transient rows live in `incident_knowledge` (hostname='*');
  re-seed with `scripts/seed-host-agnostic-suppression.sh`. Critical + unknown always escalate.

## Common failure modes (all seen 2026-06-17)

| Symptom | Cause | Check |
|---|---|---|
| `session_risk_audit` empty / everything fail-closes `high` | a Runner SSH node lost its `=` expr-mode prefix or uses `Buffer` in an expression | sweep workflows; `grep <id> pipeline-debug.log` shows `stdin length=0` |
| Everything classifies POLL_PAUSE, nothing auto-resolves | classifier treating *available* AWX runbooks as risk | classify a read-only plan — should be low/AUTO |
| `sessions` table bloats, issues never close, `session_log` stale | reconciler cron not running / off | `crontab -l`, `tail reconcile.log` |
| Same flappy alert keeps escalating on non-claude01 hosts | transient suppression host-pinned / window-expired | check `incident_knowledge` hostname='*' rows |
| `docs/host-blast-radius.md` empty / P0 drift | `refresh-host-blast-radius.py` crashed (doc-gen) | run it by hand, check it emits `p0_hosts:` |
