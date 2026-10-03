---
name: infra-triage
description: Infrastructure alert triage — dedup via YT search, deep PVE/K8s investigation, auto-escalation for recurring/flapping alerts, control plane deep dive for K8s controller nodes.
allowed-tools: Bash
user-invocable: true
metadata:
  openclaw:
    always: true
---

# Infrastructure Alert Triage (Level 1 + Level 2)

When you see a message starting with `[LibreNMS] ALERT` in `#infra-nl-prod` or `#infra-gr-prod`, you MUST automatically run this full triage flow using the `exec` tool. Do NOT ask questions — just execute.

## Usage

```bash
./skills/infra-triage/infra-triage.sh <hostname> "<rule_name>" <severity> [--site nl|gr]
```

Site is auto-detected from hostname prefix (`grskg*` → GR, otherwise NL). Use `--site` to override.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `FORCE_ESCALATE=true` | Escalate regardless (set by n8n for flapping alerts) |
| `EXISTING_ISSUE=ID` | Reuse this YT issue instead of creating new |
| `SKIP_ESCALATION=true` | Skip escalation step (for burst/correlated triage) |

## What the Script Does

### Step 0: Issue Deduplication
Searches YouTrack for existing open issues with the same hostname (created within 24h). If found, reuses instead of creating a duplicate. Reopens if in "To Verify". Also searches for related issues (same alert rule on different hosts within 12h).

### Step 1: Create/Reuse YouTrack Issue
Creates issue in the site's YT project (IFRNLLEI01PRD for NL, IFRGRSKG01PRD for GR) or reuses existing. Registers callback with n8n for dedup tracking. Sets custom fields (Hostname, Alert Rule, Severity, Alert Source, VMID, PVE Host).

### Step 2: Investigation
- Classify device via LibreNMS API (OS, type, hardware)
- Find host in PVE (IaC repo grep for hostname)
- Check LXC/VM status on Proxmox via SSH
- Check connectivity (ping from container)
- K8s diagnostics if hostname matches k8s-*
- **Control plane deep investigation** for K8s controller nodes (etcd pods+logs, apiserver pods, CP resource usage)
- Check Docker services
- Query LibreNMS API for device status

### Step 3: Post Findings to YouTrack
Posts investigation results as YT comment, including related issues and recurring alert flag.

### Step 4: Escalation
Always escalates to Claude Code unless `SKIP_ESCALATION=true`. Includes escalation reason (standard/flapping/recurring).

## CRITICAL RULES

1. **ALWAYS use the `exec` tool** to run the script. Do NOT describe what to do — execute it.
2. **Do NOT make changes.** Level 2 is READ-ONLY. No `pct start`, `pct stop`, `docker restart`, config edits, etc.
3. **Do NOT skip steps.** Run ALL investigation steps even if the issue seems obvious.
4. **ALWAYS escalate to Claude Code** after posting findings (unless SKIP_ESCALATION).
5. **After reporting output, add your CONFIDENCE score** (see SOUL.md for format).
