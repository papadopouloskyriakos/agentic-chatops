# OpenClaw (Tier 1 Agent)

> GPT-5.1 triage agent on nl-openclaw01. Compiled 2026-07-03 04:30 UTC.

## Skills

- **baseline-add** (103 lines): baseline-add.sh — Add a finding to the scanner baseline
Usage: ./skills/baseline-add/baseline-add.sh
- **claude-knowledge-lookup** (234 lines): CLAUDE.md + Memory Knowledge Lookup — extracts procedural context for triage
Usage: ./skills/claude-
- **codegraph-lookup** (59 lines): codegraph-lookup.sh — Query code graph database via SSH to app-user
Usage: codegraph-lookup.sh 
- **correlated-triage** (266 lines): Correlated Alert Triage — multi-host burst handling
Usage: ./skills/correlated-triage/correlated-tri
- **escalate-to-claude** (78 lines): escalate-to-claude.sh — Escalate to Claude Code via n8n webhook

Usage: ./escalate-to-claude.sh <ISS
- **infra-triage** (1465 lines): Infrastructure Alert Triage — automated Level 1 + Level 2
Usage: ./skills/infra-triage/infra-triage.
- **k8s-triage** (1022 lines): Kubernetes Alert Triage — automated L1 + L2 for Prometheus alerts
Usage: ./skills/k8s-triage/k8s-tri
- **lab-lookup** (35 lines): Lab reference lookup — queries 03_Lab for physical layer infrastructure context.
Usage: ./skills/lab
- **lib** (186 lines): 
Provides: run_tier1_suppression <hostname> <rule_name> <severity>

On a suppression hit (Phase 1 de
- **memory-recall** (36 lines): memory-recall.sh — Query OpenClaw's episodic memory (past triage outcomes)
Usage: memory-recall.sh <
- **netbox-lookup** (226 lines): NetBox CMDB lookup script for OpenClaw
Usage: ./netbox-lookup.sh <command> <argument>
Commands: devi
- **playbook-lookup** (51 lines): playbook-lookup.sh — Query incident knowledge base for past resolutions
Usage: playbook-lookup.sh <s
- **proactive-scan** (245 lines): proactive-scan.sh — Daily proactive health scan for pre-alert conditions
Usage: proactive-scan.sh [-
- **safe-exec** (122 lines): safe-exec.sh — Enforcement-level exec guardrail for OpenClaw
Wraps command execution with blocklist 
- **security-triage** (668 lines): Security Scan Finding Triage — automated investigation of scanner findings
Usage: ./skills/security-
- **site-config** (163 lines): Site configuration for multi-site triage scripts
Usage: source ./skills/site-config.sh [--site nl|gr
- **yt-create-issue** (24 lines): Usage: ./yt-create-issue.sh <project-short-name> "<summary>" "<description>"
- **yt-get-comments** (14 lines): Usage: ./yt-get-comments.sh <issue-id>
Fetches all comments for a YouTrack issue.
- **yt-get-issue** (14 lines): Usage: ./yt-get-issue.sh <issue-id>
Fetches full issue details including comments from YouTrack.
- **yt-list-issues** (24 lines): Usage: ./yt-list-issues.sh "<query>"
Lists YouTrack issues matching a search query.
Examples:
./yt-l
- **yt-post-comment** (24 lines): Usage: ./yt-post-comment.sh <issue-id> "<comment text>"
Posts a comment to a YouTrack issue.
- **yt-update-state** (35 lines): Usage: ./yt-update-state.sh <issue-id> <state-name>
Updates the State custom field on a YouTrack iss

## Operational Memory (5956 entries)

### blast-radius (4 entries)

- `IFRNLLEI01PRD-1397`: {"hosts": ["nl-claude01"], "host_patterns": ["*k8s-ctrlr*", "*k8s-node*"], "
- `IFRNLLEI01PRD-1046`: {"hosts": ["nlk8s-ctrl01", "nl-n8n01"], "host_patterns": [], "rules": 
- `IFRNLLEI01PRD-894`: {"host_patterns":["nl*"],"rules":["Devices up/down","Service up/down","Port
- `IFRGRSKG01PRD-241`: {"host_patterns":["gr*","gr2*"],"rules":["Service up/down","Devices up/

### infragraph-proposal (1 entries)

- `IFRNLLEI01PRD-1062`: {"hosts": ["nlk8s-ctrl01", "nl-n8n01"], "host_patterns": [], "rules": 

### infragraph-seed (6 entries)

- `librenms`: 2026-07-03T04:10:05Z
- `netbox`: 2026-07-03T04:10:04Z
- `pve`: 2026-07-03T04:10:02Z
- `tunnels`: 2026-07-03T04:10:00Z
- `declared`: 2026-07-03T04:10:00Z
- `learn-chaos-watermark`: freedom-ont-shutdown-202604231207

### triage (5945 entries)

- `nlghostfolio01:Space on / is >= 90% and < 95% in use`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:etcdMemberCommunicationSlow`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:RAGLatencyP95High`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:ContainerOOMKilled`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:ContainerOOMKilled`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:ContainerOOMKilled`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:ContainerOOMKilled`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:HolisticHealthFailing`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:ContainerOOMKilled`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:HolisticHealthFailing`: resolved (confidence: 0, duration: 0s, escalated: false)
- ... and 5935 more
