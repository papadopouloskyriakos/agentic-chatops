---
name: playbook-lookup
description: Query past incident resolutions from the knowledge base. Use when asked about prior incidents, what fixed a host/alert before, or playbooks for similar alerts. Searches by hostname or alert rule name.
allowed-tools: Bash
user-invocable: true
metadata:
  openclaw:
    always: true
---

# Incident Playbook Lookup

Queries the incident knowledge base for past resolutions. Use this skill when:
- "what fixed CPU high on nl-pve01?"
- "past incidents for CiliumAgentNotReady"
- "playbook for disk space alerts"
- "what was the resolution for IFRNLLEI01PRD-109?"
- "has this alert happened before?"
- Any question about prior incident resolutions or playbooks

## HOW to use

Run the lookup script with a search term (hostname, alert rule name, or issue ID):

```bash
./skills/playbook-lookup/playbook-lookup.sh nl-pve01
./skills/playbook-lookup/playbook-lookup.sh CiliumAgentNotReady
./skills/playbook-lookup/playbook-lookup.sh IFRNLLEI01PRD-109
```

The script queries the `incident_knowledge` SQLite table on claude-runner and returns matching past resolutions with:
- Issue ID and date
- Hostname and alert rule
- Resolution summary
- Confidence score

## CRITICAL RULES

1. **RUN THE TOOL FIRST.** Do not answer from memory about past incidents.
2. **Present the results clearly.** Include the issue ID, date, and confidence.
3. **Note if no results found.** The knowledge base only contains resolved infra sessions.
