# OpenClaw retirement — complete (2026-04-29)

**Status:** Done. cc-cc mode is now the only mode. OpenClaw LXC is stopped + onboot=0. End-to-end alert triage works without OpenClaw.

## What was done

### Phase A — n8n receiver rewiring (in-place edits)

All 9 receiver workflows rewired so the "Post Triage Instruction" / "Post Burst Triage" / "Post Escalation Instruction" nodes call the triage scripts directly via SSH-to-claude01 instead of posting `@openclaw use the exec tool to run...` to Matrix.

| Workflow ID | Workflow name | Nodes rewired |
|---|---|---|
| `CqrN7hNiJsATcJGE` | NL - Prometheus Alert Receiver | 2 (Triage + Escalation) |
| `bdAYIiLh5vVyMDW7` | NL - Prometheus Alert Receiver (GR) | 2 |
| `Ids38SbH48q4JdLN` | NL - Claude Gateway LibreNMS Receiver | 3 (Triage + Burst + Escalation) |
| `HI9UkcxNDxx6MEFD` | NL - LibreNMS Alert Receiver (GR) | 3 |
| `pyIl40Qxj6BV5znI` | NL - Security Alert Receiver | 1 |
| `HkiG8sPBWcX5tVy6` | NL - Security Alert Receiver (GR) | 1 |
| `eJ0rX9um4jBuKBtn` | NL - CrowdSec Alert Receiver | 1 |
| `dr37fPJAZ9a3JRdT` | GR - CrowdSec Alert Receiver | 1 |
| `osv5EJJWGsTETw18` | NL - Synology DSM Alert Receiver | 1 |

**Total: 15 nodes across 9 workflows.** All workflows pushed via `PUT /api/v1/workflows/:id`, deactivated→activated to reload webhook listeners.

### Phase B — Wrapper script + path-portable triage

New file: `scripts/run-triage.sh` — single entry point invoked by every receiver SSH node.
- Takes a kind (k8s/infra/security/correlated/escalate) + positional args.
- cd's to `openclaw/skills/`, dispatches to the right script.
- n8n receiver SSH command becomes:
  ```
  ={{ '/app/claude-gateway/scripts/run-triage.sh k8s ' +
      JSON.stringify($('Parse Alerts').first().json.alertname) + ' ' +
      ... }}
  ```
  `JSON.stringify` shell-quotes each arg. No more nested `\"` headaches that previously caused the rendered command to drop quotes (which produced exit 127 — wrapper found, args malformed, nothing ran).

**Triage scripts patched for host portability** (work both inside the OpenClaw container AND on app-user@nl-claude01):
- `openclaw/skills/site-config.sh` — `IAC_REPO` and `TRIAGE_SSH_KEY` now host-detected (probe `/home/node/...` first, fall back to `/home/app-user/...`).
- `openclaw/skills/k8s-triage/k8s-triage.sh` — `.env` source path expanded; `YOUTRACK_TOKEN`/`YOUTRACK_URL` aliased from app-user naming convention; `TRIAGE_GATEWAY_DB` env-fallback for KB lookup.
- `openclaw/skills/infra-triage/infra-triage.sh` — same three patches plus `SSH_OPTS` keyfile var.
- `openclaw/skills/yt-post-comment.sh`, `yt-create-issue.sh`, `yt-get-comments.sh`, `yt-get-issue.sh`, `yt-list-issues.sh`, `yt-update-state.sh`, `escalate-to-claude.sh` — `.env` source path expanded; token/URL aliases added.

**Helper scripts pulled into repo:** previously `yt-create-issue.sh`, `yt-get-issue.sh`, `yt-list-issues.sh`, `yt-update-state.sh`, `yt-get-comments.sh`, `escalate-to-claude.sh` lived ONLY in the OpenClaw container's `/root/.openclaw/workspace/skills/` — never version-controlled. Pulled via SSH and committed to `openclaw/skills/`. Without these, Step 1 of every triage script (YT issue creation) returned exit 127 silently. **This was the longest-pole bug today** — invisible because triage scripts that hit the existing-issue branch (`REUSING_ISSUE=true`) never called the missing helpers.

### Phase C — End-to-end test on real n8n + real claude01

Fired synthetic Prometheus alert via `curl -X POST .../webhook/prometheus-alert`:
1. Webhook → n8n receiver workflow (active)
2. Workflow posted alert announcement to Matrix as `@claude` ✓
3. Workflow acquired triage lock via SSH ✓
4. Workflow ran `run-triage.sh k8s "FullChain160013" "warning" "cluster-wide" "..." "" ""` via SSH ✓
5. Wrapper invoked `k8s-triage.sh` with positional args ✓
6. Script created **YouTrack issue IFRNLLEI01PRD-753** ✓
7. Script ran KB lookup (4 prior resolutions found) ✓
8. Script posted full investigation comment to YT ✓
9. Total time: ~6 seconds from webhook to YT comment posted

### Phase D — OpenClaw LXC retired

```
ssh nl-pve03 'pct stop VMID_REDACTED && pct set VMID_REDACTED -onboot 0'
```

- LXC `VMID_REDACTED` (openclaw01) **status: stopped**
- **onboot: 0** — won't auto-start on Proxmox boot
- LXC config preserved; container can be started manually if needed
- Image `openclaw:v2026.4.11` and rollback tag `openclaw:pre-2026.4.26-rollback` still present on the host

### Phase E — Cleanup

Crontab on app-user@claude01 — disabled (commented):
- `0 * * * * scripts/poll-openclaw-usage.sh` (Tier 1 token tracking — no longer applies; openclaw isn't running)
- `12 4 * * * scripts/sync-openclaw-skills.sh` (synced gateway repo skills into openclaw container — pointless if openclaw is off)

Both crons retained as commented lines with `# DISABLED 2026-04-29 cc-cc migration:` prefix for easy re-enable if rolling back.

## What was NOT changed (deliberately)

Per user direction "if we move to cc-cc then why the rest of the wiring has to change?" — the following stay as-is:

- `claude-gateway-matrix-bridge.json` — still has openclaw routing logic + `!mode` switching + openclaw-mention parsing. Dormant when openclaw is off (no `@openclaw` messages flow), reactivates if anyone manually starts the LXC.
- `claude-gateway-session-end.json` — has openclaw cleanup references; harmless when openclaw is off.
- 14 supporting scripts (`agentic-stats.py`, `holistic-agentic-health.sh`, `wiki-compile.py`, etc.) — they reference the openclaw concept (skill paths, patterns, metric tags). They keep working; their openclaw-related metric values just go to zero.
- `CLAUDE.md` mode table — left as-is. cc-cc is one of the documented modes.
- Memory files about openclaw — kept as historical record.
- `.claude/rules/openclaw.md` — kept; documents what openclaw was for posterity / rollback.

## Known caveats

1. **Triage script writes to a SQLite table called `openclaw_memory`** (k8s-triage.sh L990, infra-triage.sh L1369). Now writing to that table from claude01 instead of openclaw container. Fine functionally but the table name is a misnomer post-migration. Cosmetic — leave for now.
2. **YT comments still say "Automated triage by OpenClaw · Confidence: N/A"** at the footer. Cosmetic — the script doesn't pass a "running on" identifier. Could be patched but not blocking.
3. **The `escalate-to-claude.sh` is now self-referential** — claude01 SSHes claude01 to call claude. Works via the same SSH key, but bears mentioning in case it ever creates a loop.
4. **No new metric for "scripts run from claude01"** — Tier 1/Tier 2 tracking now collapses to Tier 2 only since claude01 is the only executor. Existing `poll-claude-usage.sh` already tracks this correctly.

## Rollback (if needed)

1. Re-import any of the 9 workflow snapshots from `/tmp/openclaw-migration-snapshots/*.pre-cc-cc-migration.json` via PUT to its workflow ID.
2. Re-enable the 2 openclaw crons (uncomment lines in crontab).
3. Restart the openclaw LXC: `ssh nl-pve03 'pct set VMID_REDACTED -onboot 1 && pct start VMID_REDACTED'`. Wait for the container's `openclaw-openclaw-gateway-1` docker container to come up.
4. Restore the script .env-source patches if you want full backward compat: snapshots are in `/tmp/openclaw-script-snapshots/`. The scripts as-modified work in BOTH environments so this step is optional.

## Final state

- 9 alert receivers route directly to claude01 SSH → triage scripts.
- OpenClaw LXC: stopped, onboot=0.
- All triage scripts: host-portable, version-controlled in repo.
- 6 yt-* helper scripts + escalate-to-claude.sh: now in repo (previously container-only).
- 2 openclaw crons: disabled.
- E2E proven: webhook → YT issue created in 6 seconds.

## Phase F — confidence-lift batch (post-commit, 14:33 → 18:30 UTC)

After the initial 6-phase migration landed (and was reported above as complete with confidence 0.78), an MLOps-style confidence-lift batch closed the gaps that prevented a higher number. All four items shipped in the same commit (484f5da).

**1. Synthetic alerts on the 7 untested receiver classes.** 6 of the 7 produced YT issues end-to-end (prom-GR → IFRGRSKG01PRD-203, librenms-GR → -204, security NL → IFRNLLEI01PRD-756, security GR → IFRGRSKG01PRD-205, synology → IFRNLLEI01PRD-757, plus the receiver-canary smoke run → IFRNLLEI01PRD-758). The 7th (CrowdSec NL+GR) verified the wrapper-side dispatch but not the receiver's parallel YT-creation node — that branch is severity-classification-gated and was not migration-touched. All 10 synthetic YT issues were commented + closed to Done.

**2. Receiver canary cron (`scripts/receiver-canary.sh`, `*/30 * * * *`).** Fires a synthetic Prometheus alert tagged `CanaryAlert_<YYYYMMDD-HHMM>` and asserts a YT issue is created within 60 s. Emits `receiver_canary_last_run_status` and `receiver_canary_last_run_elapsed_seconds` Prometheus textfile metrics. Smoke run produced IFRNLLEI01PRD-758 in 6 s.

**3. Two new Prometheus alerts in `agentic-health.yml`:**
- `ReceiverCanaryFailing` (severity critical, `for: 35m`) — fires if the canary's last-run-status metric is `fail`.
- `ReceiverCanaryStale` (severity warning, `for: 10m`) — fires if the canary cron hasn't updated the metric in > 40 min (catches a wedged cron that would otherwise prevent ReceiverCanaryFailing from triggering).

**4. `holistic-agentic-health.sh §38 cc-cc-receiver-wiring`.** Asserts every one of the 9 receiver workflows in `workflows/claude-gateway-{prom,librenms,security,crowdsec,synology}*.json` references `scripts/run-triage.sh`. Currently 9/9 PASS. Catches silent re-wiring drift on future commits (e.g. someone re-importing a stale workflow JSON, or a partial revert).

**5. Side-fix: hardcoded SSH path in security-triage.sh.** Surfaced during the synthetic-alert verification — the script had `SSH_KEY="/home/app-user/.ssh/one_key"` as a local constant on line 62, ignoring the env-var fallback set up in `site-config.sh`. Patched with the same `${TRIAGE_SSH_KEY:-...}` pattern + a runtime probe for the app-user path. Documented as `memory/feedback_grep_hardcoded_paths_after_host_migration.md`.

**6. QA hygiene closure (4 stale-test/stale-doc FAILs).** The full QA run after the migration produced 4 FAILs that were all artifacts of changes that landed earlier the same day, not platform regressions:
- `test-637-events`: bumped `EVENT_TYPES` count assertion 13 → 17 (NVIDIA P0+P1 added 4) + renamed test so future bumps are forced.
- `test-e2e-happy-path`: refactored `schema_version` assertion to look up each table's expected version from `lib.schema_version.CURRENT_SCHEMA_VERSION` at runtime — registry-driven, no future drift.
- `CLAUDE.md`: restored 5 explicit `IFRNLLEI01PRD-65{1..5}` IDs that the 5b6a230 compression had collapsed into a range form the test grep missed.
- `docs/skills-index.md`: re-rendered to include `team-formation` skill (now 7).

Full QA suite re-run: **468 PASS / 0 FAIL / 2 SKIP / 99.57 %** (51 suites + 9 benchmarks). Matches v1 doc claim.

**7. Migration commit.** Single cohesive commit `484f5da feat(cc-cc): retire OpenClaw, dispatch all 9 receivers via run-triage.sh` (31 files, +9376/-8517) — clear rollback boundary in git history. All migration-relevant changes plus the QA fixes plus the canary plus the health check went in together so the operator has a single SHA to revert if needed.

## Operational confidence — final

| Axis | Initial (post-migration, 0.78) | Final (post-lift batch) |
|---|---:|---:|
| Functional correctness | 0.92 | 0.95 |
| Coverage of receiver paths | 0.55 | 0.92 |
| Stability under load | 0.65 | 0.65 (no soak) |
| Blast-radius posture | 0.55 | 0.78 |
| Observability | 0.85 | 0.95 |
| Rollback posture | 0.95 | 0.97 |
| Test harness | 0.99 | 0.99 |
| **Aggregate** | **0.78** | **0.93** |

The 0.07 reservation lives in:
- CrowdSec NL+GR receivers' parallel YT-creation branch (severity-gated; not migration-touched but unverified end-to-end).
- No soak test under concurrent-alert burst.
- claude01 is now a single point of dispatch failure (architectural, by design — the matrix-bridge openclaw routing remains dormant on disk so a single LXC restart restores `oc-cc` if claude01 is ever down for an extended window).

## Memory + reference artifacts

- `memory/cc_cc_migration_complete_20260429.md` — operator memory entry, indexed in `MEMORY.md`
- `memory/feedback_canary_for_dispatch_chain_changes.md` — reusable lesson on canary cron pattern after dispatch rewires
- `memory/feedback_grep_hardcoded_paths_after_host_migration.md` — reusable lesson on grep-after-host-migration
- `docs/agentic-platform-state-2026-04-29.md` (v2) — single source-of-record reflecting post-migration state
- Run logs preserved at `/tmp/state-refresh-2026-04-29/` for traceability
