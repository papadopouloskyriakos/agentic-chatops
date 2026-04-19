# OpenClaw (Tier 1 Agent)

> GPT-5.1 triage agent on nl-openclaw01. Compiled 2026-04-11 14:13 UTC.

## Skills

- **baseline-add** (103 lines): baseline-add.sh — Add a finding to the scanner baseline
Usage: ./skills/baseline-add/baseline-add.sh
- **claude-knowledge-lookup** (234 lines): CLAUDE.md + Memory Knowledge Lookup — extracts procedural context for triage
Usage: ./skills/claude-
- **codegraph-lookup** (59 lines): codegraph-lookup.sh — Query code graph database via SSH to app-user
Usage: codegraph-lookup.sh 
- **correlated-triage** (266 lines): Correlated Alert Triage — multi-host burst handling
Usage: ./skills/correlated-triage/correlated-tri
- **infra-triage** (1299 lines): Infrastructure Alert Triage — automated Level 1 + Level 2
Usage: ./skills/infra-triage/infra-triage.
- **k8s-triage** (972 lines): Kubernetes Alert Triage — automated L1 + L2 for Prometheus alerts
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
- **security-triage** (666 lines): Security Scan Finding Triage — automated investigation of scanner findings
Usage: ./skills/security-
- **site-config** (140 lines): Site configuration for multi-site triage scripts
Usage: source ./skills/site-config.sh [--site nl|gr
- **yt-post-comment** (21 lines): Usage: ./yt-post-comment.sh <issue-id> "<comment text>"
Posts a comment to a YouTrack issue.

## Operational Memory (106 entries)

### triage (106 entries)

- `nl-pve02:Service up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `gr-pve02:-- ALERT -- gr-pve02 - Service up/down - Critical Alert`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nlnc01:Service up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-pve01:Service up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-pve03:Service up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nlnc02:Service up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-pve02:Service up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-pve01:Service up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `nl-pve03:Service up/down`: escalated (confidence: 0, duration: 0s, escalated: true)
- `gr-pve02:-- ALERT -- gr-pve02 - Service up/down - Critical Alert`: escalated (confidence: 0, duration: 0s, escalated: true)
- ... and 96 more
