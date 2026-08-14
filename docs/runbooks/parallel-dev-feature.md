# Runbook: run a parallel-dev feature end-to-end

**Audience:** operator dispatching a feature for ≤4 parallel Claude Code workers (epic IFRNLLEI01PRD-922).

**Prerequisite state:**
- (b) state refactor merged (epic IFRNLLEI01PRD-910)
- Target project has `PROJECT.json` at repo root with `slug`, `youtrack_prefix`, `matrix_room`, `test_command`, `lint_command`, `max_parallel_workers`
- Target project is a SINGLE git repo (cubeos meta-dir doesn't work — see "Architectural notes" below)
- n8n workflows `NL - ChatDevOps Planner` (`AVHleUvGGPzgkbaH`) and `NL - ChatDevOps CI Resume` (`JtDNd1saO7PKM5fh`) **activated** (default inactive)

---

## Happy path

### 1. Create the feature epic in YouTrack

Create a YT issue with prefix `MESHSAT-` (or any slot prefix), Type=Epic, with a clear feature description. The description should be detailed enough that a single Claude session can decompose it into ≤4 independent work units.

### 2. Trigger the Planner

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"featureId":"MESHSAT-1234","dryRun":false}' \
  https://n8n.example.net/webhook/chatops-devops-planner
```

Response includes the inserted task count. Inspect via:

```bash
sqlite3 /home/app-user/gateway-state/gateway.db \
  "SELECT task_id, parallelizable, files_owned FROM work_units WHERE feature_id='MESHSAT-1234'"
```

### 3. Dispatch the first wave

```bash
/home/app-user/gateway-state/bin/distribute-workers.sh MESHSAT-1234
```

Watches: n8n executions UI, Matrix `#meshsat` progress messages, `lsof` for `gateway.lock.meshsat`.

### 4. Wait for workers

Workers complete one of three ways:
- Normal exit → release-worktree.sh marks them `completed` with diff_blob captured
- Wall-clock timeout (30 min default) → `timeout` SIGTERM, status `timeout`
- Worker error → status `failed` with `failure_reason` set

Monitor:

```bash
sqlite3 /home/app-user/gateway-state/gateway.db \
  "SELECT task_id, worker_slot, status, started_at, completed_at FROM work_units WHERE feature_id='MESHSAT-1234'"
```

### 5. Run merge-coordinator

Once all work_units are terminal:

```bash
/home/app-user/gateway-state/bin/merge-coordinator.sh MESHSAT-1234
```

On success: opens GitLab MR. URL printed + recorded in `features.mr_url`.

On `git apply` conflict: STOPs, sets features.status='failed'. LLM-assist reconcile is scaffolded but not invoked (deferred — measure conflict rate first).

### 6. Review + merge the MR

For auto-merge-eligible features (low risk, no failures), GitLab auto-merge can be enabled. For `[NEEDS-HUMAN]` MRs, operator review required.

---

## Failure recovery

### Worker stuck / hung past wall-clock

The `timeout` wrapper in distribute-workers.sh kills past max_wall_clock_minutes. Worker process dies, but the lock + work_unit row stay until release-worktree.sh runs. If the worker didn't release itself (e.g. systemd-run scope killed mid-write), manually:

```bash
/home/app-user/gateway-state/bin/release-worktree.sh MESHSAT-1234 T-001 timeout
```

### Slot exhaustion

All 4 slots in_progress, can't allocate. Either wait, or:

```bash
# Check what's running
sqlite3 /home/app-user/gateway-state/gateway.db \
  "SELECT feature_id, task_id, worker_slot, started_at FROM work_units WHERE status='in_progress'"

# If something's clearly hung, manual release as above
```

### Merge-coordinator failures

- **`git apply` conflict:** read /tmp/apply-err. Either (a) re-run the conflicting worker with updated prompt, (b) hand-edit the merge branch + push manually, or (c) abort the feature and re-decompose.
- **Lint failure:** stop and address whatever the lint surfaces. May be pre-existing (unrelated to this feature) or from worker outputs.
- **Test failure:** same triage. If from a worker output, mark that work_unit `failed`, re-run merge-coordinator (will skip failed work_units but flag the MR `[PARTIAL]`).

### Cleanup a feature entirely (abort)

```bash
FID=MESHSAT-1234
REPO=/app/cubeos/meshsat
for s in 1 2 3 4; do
  git -C $REPO worktree remove --force $REPO/.parallel-dev/slot-$s 2>/dev/null || true
done
git -C $REPO branch -D parallel-dev/$FID/T-001 parallel-dev/$FID/T-002 parallel-dev/$FID/T-003 parallel-dev/$FID/T-004 2>/dev/null || true
git -C $REPO branch -D merge/$FID 2>/dev/null || true
sqlite3 /home/app-user/gateway-state/gateway.db \
  "UPDATE features SET status='aborted' WHERE feature_id='$FID'; \
   UPDATE work_units SET status='skipped' WHERE feature_id='$FID' AND status NOT IN ('completed','failed','timeout')"
```

---

## Architectural notes

### cubeos is a meta-directory, not a single repo

`/app/cubeos/` contains many independent git repos (api, coreapps, dashboard, hal, meshsat, etc.). The worktree allocator requires a SINGLE git repo as `<repo_cwd>`.

**Implication:** for CUBEOS-* features that span sub-repos, parallel-dev today only works within ONE sub-repo at a time. The PROJECT.json in each sub-repo determines its parallel-dev config. CUBEOS-* features touching cubeos meta-dir directly (CLAUDE.md edits, dashboard configs at meta-level) currently can't use parallel-dev — single-agent dispatch is correct for them.

Future enhancement: a multi-repo allocator that creates worktrees in N sub-repos simultaneously. Out of scope for IFRNLLEI01PRD-922.

### Why deterministic merge before LLM-assist

Per the plan AC: "Start with deterministic-merge-only (no LLM reconcile), measure conflict rate, add LLM reconcile if needed."

The plan literature (Cognition's *Don't Build Multi-Agents*, Anthropic's orchestrator-workers pattern) is consistent: deterministic merge is the safety net. If the planner enforces `files_owned` non-overlap correctly, conflicts should be rare. LLM-assist reconcile is a fallback for the rare cases, not the default path. We'll add it when we have data on real conflict patterns.

### Why `files_owned` is the load-bearing invariant

Two parallel workers writing the same file = automatic merge conflict that LLM-assist may or may not handle. The Planner workflow's job is to enforce non-overlap **at decomposition time** so workers physically can't collide. This is the SRE pattern (slot-locks) applied to file-level work assignment.

---

## Operator quickstart command sheet

```bash
# Plan a feature
curl -X POST -d '{"featureId":"MESHSAT-1234"}' https://n8n.example.net/webhook/chatops-devops-planner

# Dispatch wave
/home/app-user/gateway-state/bin/distribute-workers.sh MESHSAT-1234

# Check status
sqlite3 /home/app-user/gateway-state/gateway.db "SELECT task_id, worker_slot, status FROM work_units WHERE feature_id='MESHSAT-1234'"

# Merge once all terminal
/home/app-user/gateway-state/bin/merge-coordinator.sh MESHSAT-1234

# Risk classification (manual check)
/home/app-user/gateway-state/bin/classify-feature-risk.py MESHSAT-1234

# Weekly audit (runs from cron)
/app/claude-gateway/scripts/audit-parallel-dev-decisions.sh
```
