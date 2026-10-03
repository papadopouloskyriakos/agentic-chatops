# Agent Decommissioning Procedure

**Date:** 2026-04-15
**Reference:** NIST AI RMF AG-MG.3 (Manage -- General -- Lifecycle Management)
**Scope:** All agent tiers in the Example Corp ChatOps platform
**Related:** `docs/a2a-protocol.md`, `docs/compliance-mapping.md`, `docs/architecture.md`

---

## Overview

This document defines the lifecycle management and decommissioning procedure for AI agents
in the claude-gateway platform. The platform operates a 3-tier agent hierarchy:

- **Tier 1 (OpenClaw):** GPT-5.1, host nl-openclaw01, fast triage (7-21s)
- **Tier 2 (Claude Code):** Claude Opus 4.6, host nl-claude01, deep analysis + remediation
- **Tier 3 (Human):** Approval gates, plan selection, override via Matrix

Each tier has distinct credential sets, state stores, communication channels, and audit
surfaces that must be addressed during decommissioning.

---

## State Transitions

Agent lifecycle follows three mandatory state transitions. Each transition requires
explicit operator approval and produces an audit trail in `a2a_task_log`.

### active -> deprecated

**Trigger:** Decision to replace agent with successor (model upgrade, architecture change, EOL).

| Step | Action | Owner |
|------|--------|-------|
| 1 | Announce sunset date in `#chatops` Matrix room (minimum 7 days notice) | Operator |
| 2 | Update agent card status field to `"deprecated"` in `a2a/agent-cards/` | Operator |
| 3 | Configure Runner workflow to prefer replacement agent for new sessions | Operator |
| 4 | Enable dual-run mode: both old and new agent process alerts, old agent results discarded after comparison | Operator |
| 5 | Monitor replacement agent performance for minimum 48 hours | Automated |
| 6 | Record deprecation event in `a2a_task_log` with `type: "lifecycle"` | Automated |

**Exit criteria:** Replacement agent matches or exceeds deprecated agent on: confidence scores,
resolution rate, cost per session, and zero critical failures in dual-run period.

### deprecated -> decommissioned

**Trigger:** Dual-run validation complete, replacement agent confirmed operational.

| Step | Action | Owner |
|------|--------|-------|
| 1 | Stop routing all new traffic to deprecated agent | Operator |
| 2 | Wait for in-flight sessions to complete (check `sessions` table for active entries) | Automated |
| 3 | Execute per-tier decommissioning checklist (see below) | Operator |
| 4 | Update agent card status to `"decommissioned"` | Operator |
| 5 | Run `holistic-agentic-health.sh` -- decommissioned agent checks should SKIP (not FAIL) | Operator |
| 6 | Post decommissioning confirmation to `#chatops` and `#alerts` | Operator |

**Exit criteria:** Zero active sessions, all credentials revoked, health checks pass with SKIP status.

### decommissioned -> archived

**Trigger:** 30-day post-decommission observation period complete with no issues.

| Step | Action | Owner |
|------|--------|-------|
| 1 | Execute audit log preservation (see retention policy below) | Operator |
| 2 | Archive agent card to `a2a/agent-cards/archive/` | Operator |
| 3 | Remove agent-specific cron entries | Operator |
| 4 | Archive host configuration (container snapshot or VM backup) | Operator |
| 5 | Update CLAUDE.md and memory files to remove active references | Operator |
| 6 | Final `a2a_task_log` entry with `type: "archived"` | Automated |

**Exit criteria:** All audit logs preserved per retention policy, no remaining active references.

---

## Per-Tier Decommissioning Checklists

### Tier 1 (OpenClaw) Decommissioning

OpenClaw runs as a Docker container on nl-openclaw01 (10.0.181.X), model GPT-5.1
via OpenAI API, version 2026.4.11 with 7 plugins including Active Memory.

**1. Credentials**

| Credential | Location | Action |
|------------|----------|--------|
| OPENAI_API_KEY | `/root/.openclaw/workspace/.env` | Revoke key in OpenAI dashboard, remove from .env |
| SCANNER_SUDO_PASS | `/root/.openclaw/workspace/.env` | Remove from .env |
| Matrix @openclaw token | Matrix Synapse admin API | Revoke access token, deactivate account |
| GITLAB_TOKEN | `/root/.openclaw/workspace/.env` | Revoke in GitLab |
| YOUTRACK_TOKEN | `/root/.openclaw/workspace/.env` | Revoke in YouTrack |
| N8N_TOKEN | `/root/.openclaw/workspace/.env` | Revoke in n8n |
| LIBRENMS_API_KEY (NL+GR) | `/root/.openclaw/workspace/.env` | Revoke in LibreNMS |
| NETBOX_TOKEN | `/root/.openclaw/workspace/.env` | Revoke in NetBox |
| exec-approvals socket token | `openclaw/exec-approvals.json` | Invalidate token |

**2. Memory and Knowledge**

| Data | Location | Action |
|------|----------|--------|
| `openclaw_memory` table | `gateway.db` | Export to `archive/openclaw-memory-YYYY-MM-DD.sql`, keep in DB |
| `agent_diary` entries | `gateway.db` | Export entries where agent='openclaw' to archive file |
| Active Memory plugin data | Container `/root/.openclaw/` | Export before container removal |
| Feedback memories (51 files) | `openclaw/` repo directory | Retain in repo (historical reference) |
| SOUL.md | `openclaw/SOUL.md` | Retain in repo, add deprecation header |

**3. Trust and Routing**

| Component | Location | Action |
|-----------|----------|--------|
| Agent card | `a2a/agent-cards/openclaw-t1.json` | Set `_nla2a.status: "decommissioned"` |
| Bridge workflow routing | n8n workflow `QGKnHGkw4casiWIU` | Remove OpenClaw routing paths |
| Operating mode config | `~/gateway.mode` | Remove `oc-oc` and `oc-cc` modes |
| LibreNMS/Prometheus receivers | n8n alert workflows | Remove OpenClaw triage delegation |
| escalate-to-claude webhook | n8n | Disable or reroute |

**4. State and Runtime**

| Item | Location | Action |
|------|----------|--------|
| `queue` table entries | `gateway.db` | Clear entries for openclaw agent |
| Active sessions | `sessions` table | Verify none active, clear stale |
| `/tmp/openclaw-*` files | nl-openclaw01 | Remove temporary files |
| Docker container logs | Container runtime | Export last 30 days before removal |
| mcporter config | `/root/.mcporter/mcporter.json` | Remove (inside container) |

**5. Communication**

| Channel | Action |
|---------|--------|
| Matrix rooms (6 active) | Remove @openclaw from `#chatops`, `#cubeos`, `#meshsat`, `#infra-nl-prod`, `#infra-gr-prod`, `#alerts` |
| SOUL.md references | Add `DECOMMISSIONED` header, retain for audit |
| Command prefix (`/`) | Document that `/` prefix commands no longer active |

**6. Host**

| Action | Command/Detail |
|--------|----------------|
| Stop container | `docker stop openclaw-openclaw-gateway-1` on nl-openclaw01 |
| Disable auto-restart | `docker update --restart=no openclaw-openclaw-gateway-1` |
| Remove from repo sync cron | Edit crontab on nl-openclaw01, comment out `*/30` sync |
| Remove from Docker socket mount | Revoke GID 996 access |
| Archive container image | `docker save` to backup storage |
| Snapshot LXC/VM | PVE snapshot of nl-openclaw01 for forensic preservation |

---

### Tier 2 (Claude Code) Decommissioning

Claude Code runs on nl-claude01 as user `app-user`, orchestrated by n8n workflows,
with 10 MCP servers (153 tools) and 10 sub-agents.

**1. Credentials**

| Credential | Location | Action |
|------------|----------|--------|
| ANTHROPIC_API_KEY | `~/.claude/.credentials.json` or env | Rotate key in Anthropic dashboard |
| SSH key (app-user) | `~/.ssh/` on nl-claude01 | Remove public key from all authorized_keys |
| n8n SSH credential | n8n credential ID `REDACTED_SSH_CRED` | Delete credential in n8n |
| Matrix @claude token | n8n credential ID `REDACTED_MATRIX_CRED` | Revoke in Matrix Synapse |
| YouTrack API token | n8n credential ID `REDACTED_YT_CRED` | Revoke in YouTrack |
| `~/.ssh/one_key` | SSH key for cross-host access | Remove from all remote authorized_keys |

**2. Memory and Knowledge**

| Data | Location | Action |
|------|----------|--------|
| `session_transcripts` | `gateway.db` | Export to archive (see retention policy) |
| `session_log` | `gateway.db` | Keep indefinitely in gateway.db |
| `incident_knowledge` | `gateway.db` | Keep indefinitely (core KB, includes embeddings) |
| `lessons_learned` | `gateway.db` | Keep indefinitely |
| `wiki_articles` | `gateway.db` | Keep indefinitely |
| `agent_diary` | `gateway.db` | Keep indefinitely |
| CLAUDE.md files (55) | Repo + `~/.claude/` | Archive `~/.claude/` directory |
| Feedback memories (74) | `~/.claude/projects/` | Archive before removal |
| JSONL session files | `~/.claude/projects/**/*.jsonl` | Archive then purge |

**3. Trust and Routing**

| Component | Location | Action |
|-----------|----------|--------|
| Agent card | `a2a/agent-cards/claude-code-t2.json` | Set `_nla2a.status: "decommissioned"` |
| Runner workflow | n8n workflow `qadF2WcaBsIR7SWG` | Deactivate |
| Poller workflow | n8n workflow `uRRkYbRfWuPXrv3b` | Deactivate |
| Session End workflow | n8n workflow `rgRGPOZgPcFCvv84` | Deactivate |
| YouTrack trigger | n8n workflow `e3e2SFPKc1DLsisi` | Deactivate |
| Matrix Bridge | n8n workflow `QGKnHGkw4casiWIU` | Disable polling and command routing |
| Operating mode config | `~/gateway.mode` | Remove `cc-cc` and `oc-cc` modes |

**4. State and Runtime**

| Item | Location | Action |
|------|----------|--------|
| `sessions` table | `gateway.db` | Verify none active, clear stale entries |
| `/tmp/claude-run-*.jsonl` | nl-claude01 | Remove JSONL run files |
| `/tmp/claude-pid-*` | nl-claude01 | Remove PID files |
| Lock files | `~/gateway.lock.*` | Remove per-slot locks (dev, infra-nl, infra-gr) |
| `/tmp/claude-code-bash-audit.log` | nl-claude01 | Archive then remove |
| `/tmp/claude-code-file-audit.log` | nl-claude01 | Archive then remove |

**5. Communication**

| Channel | Action |
|---------|--------|
| Matrix rooms (6 active) | Remove @claude from `#chatops`, `#cubeos`, `#meshsat`, `#infra-nl-prod`, `#infra-gr-prod`, `#alerts` |
| Matrix Bridge listener | Disable webhook and polling in Bridge workflow |
| `!` command prefix | Document that `!` prefix commands no longer active |

**6. Host**

| Action | Command/Detail |
|--------|----------------|
| Disable crons | Comment out all entries in `crontab -l` on nl-claude01 |
| List of crons (33 total) | write-session-metrics, write-agent-metrics, write-model-metrics, write-infra-metrics, write-security-metrics, gateway-watchdog, regression-detector, grade-prompts, trigger-proactive-scan, poll-claude-usage, poll-openai-usage, wiki-compile, dead-man watchdog, vti-freedom-recovery, chaos weekly, and others |
| Archive `~/.claude/` | `tar czf claude-archive-YYYY-MM-DD.tar.gz ~/.claude/` |
| Archive gateway.db | `cp gateway.db gateway.db.decommission-YYYY-MM-DD` |
| Stop n8n (if dedicated) | Only if n8n instance serves no other purpose |

---

### Sub-Agent Decommissioning

Sub-agents are defined in `.claude/agents/*.md` and do not have independent credentials
or persistent state. They share the Tier 2 Claude Code session.

**10 sub-agents:** triage-researcher, k8s-diagnostician, cisco-asa-specialist,
storage-specialist, security-analyst, workflow-validator (infra), code-explorer,
code-reviewer, ci-debugger, dependency-analyst (dev).

| Step | Action |
|------|--------|
| 1 | Remove agent definition files from `.claude/agents/` |
| 2 | Remove agent references from `.claude/settings.json` |
| 3 | Archive any agent-specific `agent_diary` entries from gateway.db |
| 4 | Update `config/tool-profiles.json` to remove routing references |
| 5 | Remove sub-agent delegation instructions from Build Prompt (Runner workflow) |
| 6 | Update `docs/architecture.md` to reflect removal |

---

## Audit Log Preservation Policy

All tables reside in `~/gitlab/products/cubeos/claude-context/gateway.db` (SQLite).
Daily backup runs at 02:00 UTC with 7-day retention.

| Table | Row Count (approx) | Retention | Archive Method | Justification |
|-------|--------------------|-----------|--------------------|---------------|
| `session_log` | ~2K | Indefinite | Keep in gateway.db | Core session history, cost tracking |
| `tool_call_log` | ~88K | 1 year | `sqlite3 .dump` + gzip archive | High volume, diminishing value |
| `execution_log` | ~18K | 1 year | `sqlite3 .dump` + gzip archive | High volume, diminishing value |
| `a2a_task_log` | ~500 | Indefinite | Keep in gateway.db | Inter-tier audit trail |
| `otel_spans` | Variable | 90 days | Export to OpenObserve before purge | Trace data, high volume |
| `session_transcripts` | ~1K | 6 months | `sqlite3 .dump` + gzip archive | Verbatim exchanges, privacy |
| `agent_diary` | ~200 | Indefinite | Keep in gateway.db | Persistent agent memory |
| `incident_knowledge` | ~500 | Indefinite | Keep in gateway.db (core KB) | RAG knowledge base with embeddings |
| `lessons_learned` | ~300 | Indefinite | Keep in gateway.db | Operational lessons |
| `llm_usage` | ~5K | Indefinite | Keep in gateway.db | Cost tracking, billing |
| `wiki_articles` | 45 | Indefinite | Keep in gateway.db | Compiled knowledge base |
| `session_feedback` | ~200 | Indefinite | Keep in gateway.db | Quality signal |
| `session_judgment` | ~100 | Indefinite | Keep in gateway.db | LLM-as-a-Judge results |
| `session_trajectory` | ~200 | Indefinite | Keep in gateway.db | Step sequence scores |
| `session_quality` | ~200 | Indefinite | Keep in gateway.db | Computed quality scores |
| `prompt_scorecard` | ~500 | 1 year | `sqlite3 .dump` + gzip archive | Daily prompt grades |
| `chaos_experiments` | ~50 | Indefinite | Keep in gateway.db | Chaos engineering baselines |
| `chaos_exercises` | ~20 | Indefinite | Keep in gateway.db | Weekly chaos runs |
| `chaos_findings` | ~30 | Indefinite | Keep in gateway.db | Chaos findings |
| `chaos_retrospectives` | ~10 | Indefinite | Keep in gateway.db | Chaos retros |
| `openclaw_memory` | ~500 | Indefinite | Keep in gateway.db | T1 agent memory |
| `crowdsec_scenario_stats` | ~100 | Indefinite | Keep in gateway.db | Security metrics |
| `graph_entities` | Variable | 1 year | `sqlite3 .dump` + gzip archive | Code graph nodes |
| `graph_relationships` | Variable | 1 year | `sqlite3 .dump` + gzip archive | Code graph edges |
| `credential_usage_log` | ~50 | Indefinite | Keep in gateway.db | Credential audit |
| `health_check_results` | Variable | 90 days | Purge old rows | Health check history |
| `health_check_detail` | Variable | 90 days | Purge old rows | Health check detail |
| `queue` | Transient | N/A | Clear on decommission | Work queue |
| `sessions` | Transient | N/A | Clear on decommission | Active sessions |

### Archive Procedure

```bash
# 1. Create dated archive directory
ARCHIVE_DIR="/home/app-user/archive/decommission-$(date +%Y-%m-%d)"
mkdir -p "$ARCHIVE_DIR"

# 2. Full database backup
cp ~/gitlab/products/cubeos/claude-context/gateway.db "$ARCHIVE_DIR/gateway.db.full"

# 3. Export time-limited tables before purge
for TABLE in tool_call_log execution_log prompt_scorecard graph_entities graph_relationships; do
  sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db ".dump $TABLE" | \
    gzip > "$ARCHIVE_DIR/${TABLE}.sql.gz"
done

# 4. Export session transcripts (privacy-sensitive)
sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db ".dump session_transcripts" | \
  gzip > "$ARCHIVE_DIR/session_transcripts.sql.gz"

# 5. Export OTEL spans
python3 scripts/export-otel-traces.py --export-to "$ARCHIVE_DIR/otel_spans.json"

# 6. Archive Claude config
tar czf "$ARCHIVE_DIR/claude-config.tar.gz" ~/.claude/

# 7. Archive JSONL session files
tar czf "$ARCHIVE_DIR/jsonl-sessions.tar.gz" ~/.claude/projects/

# 8. Verify archive integrity
for f in "$ARCHIVE_DIR"/*.gz; do gzip -t "$f" && echo "OK: $f"; done
sqlite3 "$ARCHIVE_DIR/gateway.db.full" "SELECT COUNT(*) FROM session_log;"
```

---

## Post-Decommission Verification

Run this checklist after completing the per-tier decommissioning steps.

### Automated Checks

```bash
# 1. Health check (decommissioned agent should SKIP, not FAIL)
./scripts/holistic-agentic-health.sh

# 2. Verify no active sessions reference the decommissioned agent
sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db \
  "SELECT COUNT(*) FROM sessions WHERE status = 'active';"
# Expected: 0

# 3. Verify n8n workflows are deactivated
# Use n8n-mcp to check workflow status, or:
curl -s -H "X-N8N-API-KEY: $N8N_TOKEN" \
  https://n8n.example.net/api/v1/workflows | \
  jq '.data[] | select(.name | test("Runner|Poller|Session End")) | {name, active}'
```

### Manual Checks

| Check | Method | Expected |
|-------|--------|----------|
| Matrix room membership | Element client, check room members | Agent bot not listed |
| n8n webhook listeners | n8n UI, check active webhooks | No webhooks for decommissioned agent |
| Cron jobs | `crontab -l` on agent host | All agent crons commented or removed |
| SSH key access | Attempt SSH from decommissioned host | Connection refused or key rejected |
| API key validity | Attempt API call with revoked key | 401 Unauthorized |
| Mode file | `cat ~/gateway.mode` | Only valid modes for remaining agents |
| Lock files | `ls ~/gateway.lock.*` | No stale locks |
| PID files | `ls /tmp/claude-pid-*` | No orphan PIDs |

### Monitoring (30-day observation)

After decommissioning, monitor for 30 days:

- `#alerts` Matrix room for unexpected errors referencing the decommissioned agent
- Prometheus metrics for anomalous patterns (missing data points from removed exporters)
- n8n execution history for failed webhook triggers
- Gateway watchdog alerts for stale locks or orphan sessions
- LibreNMS/Prometheus alert pipeline for unprocessed alerts

---

## Rollback Procedure

If decommissioning causes unexpected issues within the 30-day observation window:

| Tier | Rollback Action | Time Estimate |
|------|----------------|---------------|
| T1 (OpenClaw) | Restart container, restore .env from archive, re-add to Matrix rooms | 15 minutes |
| T2 (Claude Code) | Restore credentials, reactivate n8n workflows, restore crons | 30 minutes |
| Sub-agents | Restore `.claude/agents/` files from git history | 5 minutes |

**Pre-requisite for rollback:** Archive snapshot must exist (Step 3 of archive procedure).
Revoked API keys require new key generation (cannot restore old keys).

---

## Cross-References

| Document | Relevance |
|----------|-----------|
| `docs/a2a-protocol.md` | Agent card schema, task lifecycle states |
| `docs/compliance-mapping.md` | NIST CSF 2.0 and CIS Controls mapping |
| `docs/architecture.md` | System architecture and workflow topology |
| `docs/aci-tool-audit.md` | Tool interface audit (8-point ACI checklist) |
| `docs/tool-risk-classification.md` | Tool risk tiers and guardrail mapping |
| `docs/maintenance-mode-details.md` | Alert suppression during lifecycle changes |
| `scripts/holistic-agentic-health.sh` | 110-check health validation (v2) |
