# Runbooks (OpenClaw Skills)

> 15 operational skills. Compiled 2026-04-09 06:19 UTC.

| Skill | Lines | Purpose |
|-------|-------|---------|
| baseline-add | 103 | baseline-add.sh — Add a finding to the scanner baseline |
| claude-knowledge-lookup | 234 | CLAUDE.md + Memory Knowledge Lookup — extracts procedural context for triage |
| codegraph-lookup | 59 | codegraph-lookup.sh — Query code graph database via SSH to app-user |
| correlated-triage | 266 | Correlated Alert Triage — multi-host burst handling |
| infra-triage | 1299 | Infrastructure Alert Triage — automated Level 1 + Level 2 |
| k8s-triage | 972 | Kubernetes Alert Triage — automated L1 + L2 for Prometheus alerts |
| lab-lookup | 35 | Lab reference lookup — queries 03_Lab for physical layer infrastructure context. |
| memory-recall | 36 | memory-recall.sh — Query OpenClaw's episodic memory (past triage outcomes) |
| netbox-lookup | 226 | NetBox CMDB lookup script for OpenClaw |
| playbook-lookup | 51 | playbook-lookup.sh — Query incident knowledge base for past resolutions |
| proactive-scan | 245 | proactive-scan.sh — Daily proactive health scan for pre-alert conditions |
| safe-exec | 122 | safe-exec.sh — Enforcement-level exec guardrail for OpenClaw |
| security-triage | 666 | Security Scan Finding Triage — automated investigation of scanner findings |
| site-config | 140 | Site configuration for multi-site triage scripts |
| yt-post-comment | 21 | Usage: ./yt-post-comment.sh <issue-id> "<comment text>" |

## baseline-add

**Path:** `openclaw/skills/baseline-add/baseline-add.sh`
**Lines:** 103

```
baseline-add.sh — Add a finding to the scanner baseline
Usage: ./skills/baseline-add/baseline-add.sh <target_ip> <port> <scanner> [baseline_type]
baseline_type: ports (default), nuclei, tls

SSHes to the correct scanner VM and appends the entry to the baseline file.
Logs the change for audit trail.
```

## claude-knowledge-lookup

**Path:** `openclaw/skills/claude-knowledge-lookup.sh`
**Lines:** 234

```
CLAUDE.md + Memory Knowledge Lookup — extracts procedural context for triage
Usage: ./skills/claude-knowledge-lookup.sh <hostname> <alert_category> [--site nl|gr]
Returns compact relevant knowledge from CLAUDE.md files + feedback memory files.
Designed to be called by infra-triage.sh, k8s-triage.sh, correlated-triage.sh.

Reads CLAUDE.md from local IaC repo ($IAC_REPO, set by site-config.sh).
Reads feedback memories from local memory dirs (synced by repo-sync cron).
Output capped at ~2000 chars to stay token-efficient.
```

## codegraph-lookup

**Path:** `openclaw/skills/codegraph-lookup/codegraph-lookup.sh`
**Lines:** 59

```
codegraph-lookup.sh — Query code graph database via SSH to app-user
Usage: codegraph-lookup.sh <callers|callees|search|deadcode> <function_name|keyword|repo>
```

## correlated-triage

**Path:** `openclaw/skills/correlated-triage/correlated-triage.sh`
**Lines:** 266

```
Correlated Alert Triage — multi-host burst handling
Usage: ./skills/correlated-triage/correlated-triage.sh "host1,host2,host3" "rule1,rule2,rule3" "sev1,sev2,sev3" [--site nl|gr]
Creates a master YT issue, runs per-host triage, links children, analyzes correlation.
```

## infra-triage

**Path:** `openclaw/skills/infra-triage/infra-triage.sh`
**Lines:** 1299

```
Infrastructure Alert Triage — automated Level 1 + Level 2
Usage: ./skills/infra-triage/infra-triage.sh <hostname> <rule_name> <severity> [--site nl|gr]
Runs the complete triage flow: dedup via YT, create/reuse issue, investigate, post findings, escalate.

Env vars:
FORCE_ESCALATE=true  — escalate regardless (set by n8n for flapping alerts)
EXISTING_ISSUE=ID    — reuse this issue instead of creating new
SKIP_ESCALATION=true — skip escalation step (for burst/correlated triage)
TRIAGE_SITE=nl|gr    — site override (alternative to --site flag)
```

## k8s-triage

**Path:** `openclaw/skills/k8s-triage/k8s-triage.sh`
**Lines:** 972

```
Kubernetes Alert Triage — automated L1 + L2 for Prometheus alerts
Usage: ./skills/k8s-triage/k8s-triage.sh "<alertname>" "<severity>" "<namespace>" "<summary>" "<node>" "<pod>" [--site nl|gr]
Creates YT issue (or reuses existing), investigates via kubectl, posts findings, escalates.

Env vars:
FORCE_ESCALATE=true  — escalate regardless of severity (set by n8n for flapping alerts)
EXISTING_ISSUE=ID    — reuse this issue instead of creating new
TRIAGE_SITE=nl|gr    — site override (alternative to --site flag)
```

## lab-lookup

**Path:** `openclaw/skills/lab-lookup/lab-lookup.sh`
**Lines:** 35

```
Lab reference lookup — queries 03_Lab for physical layer infrastructure context.
Usage: ./skills/lab-lookup/lab-lookup.sh <command> <arg>

Commands:
port-map <hostname>      Switch port, VLAN, patchpanel for a device
nic-config <hostname>    NIC interfaces, bonds, VLANs, IPs
vlan-devices <vlan_id>   All devices on a VLAN
switch-ports <switch>    All populated ports on a switch
docs <hostname>          List reference files in 03_Lab for a host
ups-pdu <site>           UPS and PDU port assignments (nl or gr)

Runs locally on nl-claude01, or SSHes there from OpenClaw container.
```

## memory-recall

**Path:** `openclaw/skills/memory-recall/memory-recall.sh`
**Lines:** 36

```
memory-recall.sh — Query OpenClaw's episodic memory (past triage outcomes)
Usage: memory-recall.sh <search_term>
```

## netbox-lookup

**Path:** `openclaw/skills/netbox-lookup/netbox-lookup.sh`
**Lines:** 226

```
NetBox CMDB lookup script for OpenClaw
Usage: ./netbox-lookup.sh <command> <argument>
Commands: device, vmid, ip, vlans, site-vms, site-devices, interfaces, search

Requires: NETBOX_URL, NETBOX_TOKEN in environment (loaded from .env)
```

## playbook-lookup

**Path:** `openclaw/skills/playbook-lookup/playbook-lookup.sh`
**Lines:** 51

```
playbook-lookup.sh — Query incident knowledge base for past resolutions
Usage: playbook-lookup.sh <search_term>
Search term can be: hostname, alert rule name, or issue ID
```

## proactive-scan

**Path:** `openclaw/skills/proactive-scan/proactive-scan.sh`
**Lines:** 245

```
proactive-scan.sh — Daily proactive health scan for pre-alert conditions
Usage: proactive-scan.sh [--site nl|gr]
```

## safe-exec

**Path:** `openclaw/skills/safe-exec.sh`
**Lines:** 122

```
safe-exec.sh — Enforcement-level exec guardrail for OpenClaw
Wraps command execution with blocklist + rate limiting + logging
This is CODE enforcement, not prompt-level (LLM cannot bypass it)

Usage: safe-exec.sh <command...>
Returns: exit code of the command, or 99 if blocked
```

## security-triage

**Path:** `openclaw/skills/security-triage/security-triage.sh`
**Lines:** 666

```
Security Scan Finding Triage — automated investigation of scanner findings
Usage: ./skills/security-triage/security-triage.sh <target_ip> "<finding_title>" <severity> [scanner] [category] [port] [issue_id]

Tier 1 quick triage: NetBox lookup, baseline check, latest report context.
Posts findings as YT comment, registers callback to n8n, outputs TRIAGE_JSON.
Deep verification (nuclei/nmap/testssl re-scan) left to Tier 2 escalation.

Scanner mapping (cross-site scan design):
nlsec01 (NL) → scans GR + VPS targets
grsec01 (GR) → scans NL + VPS targets
```

## site-config

**Path:** `openclaw/skills/site-config.sh`
**Lines:** 140

```
Site configuration for multi-site triage scripts
Usage: source ./skills/site-config.sh [--site nl|gr]
Defaults to NL site if no --site flag is provided.
Sets: YT_PROJECT, IAC_REPO, SSH_RELAY, SWITCH_REF, LIBRENMS_WEBHOOK, PROM_WEBHOOK, SECURITY_WEBHOOK, CROWDSEC_WEBHOOK, K8S_CONTEXT, SITE_PREFIX
Parse --site from caller's args (passed as $TRIAGE_SITE or from env)
```

## yt-post-comment

**Path:** `openclaw/skills/yt-post-comment.sh`
**Lines:** 21

```
Usage: ./yt-post-comment.sh <issue-id> "<comment text>"
Posts a comment to a YouTrack issue.
```
