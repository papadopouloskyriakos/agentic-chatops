# OpenClaw (Tier 1 Agent)

> GPT-5.1 triage agent on nl-openclaw01. Compiled 2026-05-06 00:48 UTC.

## Skills

- **baseline-add** (103 lines): baseline-add.sh — Add a finding to the scanner baseline
Usage: ./skills/baseline-add/baseline-add.sh
- **claude-knowledge-lookup** (234 lines): CLAUDE.md + Memory Knowledge Lookup — extracts procedural context for triage
Usage: ./skills/claude-
- **codegraph-lookup** (59 lines): codegraph-lookup.sh — Query code graph database via SSH to app-user
Usage: codegraph-lookup.sh 
- **correlated-triage** (266 lines): Correlated Alert Triage — multi-host burst handling
Usage: ./skills/correlated-triage/correlated-tri
- **escalate-to-claude** (69 lines): escalate-to-claude.sh — Escalate to Claude Code via n8n webhook

Usage: ./escalate-to-claude.sh <ISS
- **infra-triage** (1386 lines): Infrastructure Alert Triage — automated Level 1 + Level 2
Usage: ./skills/infra-triage/infra-triage.
- **k8s-triage** (1008 lines): Kubernetes Alert Triage — automated L1 + L2 for Prometheus alerts
Usage: ./skills/k8s-triage/k8s-tri
- **lab-lookup** (35 lines): Lab reference lookup — queries 03_Lab for physical layer infrastructure context.
Usage: ./skills/lab
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

## Operational Memory (407 entries)

### triage (407 entries)

- `nl-claude01:TargetDown`: resolved (confidence: 0, duration: 0s, escalated: false)
- `nlrtr01:Port status up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:SkillPrereqMissing`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:SkillPrereqMissing`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:SkillPrereqMissing`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:SkillPrereqMissing`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:SkillPrereqMissing`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nlrtr01:Port status up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:SkillPrereqMissing`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-claude01:SkillPrereqMissing`: escalated (confidence: 0, duration: 0s, escalated: true)
- ... and 397 more
