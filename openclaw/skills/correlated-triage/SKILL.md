---
name: correlated-triage
description: When multiple hosts alert simultaneously (burst), create a master YouTrack issue, run per-host triage, link children, analyze correlation, and escalate the master to Claude Code.
allowed-tools: Bash
user-invocable: true
metadata:
  openclaw:
    always: true
---

# Correlated Alert Triage (Multi-Host Burst)

When you receive a message containing `correlated-triage.sh` in `#infra-nl-prod` or `#infra-gr-prod`, you MUST immediately execute the triage using the `exec` tool. Do NOT ask questions — just execute.

## Execution

Use the `exec` tool to run the correlated triage script:

```bash
source /home/app-user/.openclaw/workspace/.env && ./skills/correlated-triage/correlated-triage.sh "<comma-separated-hosts>" "<comma-separated-rules>" "<comma-separated-severities>"
```

The script will:
1. Create a MASTER YouTrack issue summarizing the burst
2. Run per-host triage (reusing `infra-triage.sh`) without individual escalation
3. Link each child issue as a subtask of the master
4. Post a correlation analysis comment on the master issue
5. Escalate the MASTER issue only to Claude Code (Level 3)

## CRITICAL RULES

1. **ALWAYS use the `exec` tool** to run the command. Do NOT describe what to do — execute it.
2. **Run the ENTIRE command as given.** Do not modify arguments or split into multiple calls.
3. **Do NOT run individual infra-triage.sh calls** — the correlated script handles all hosts sequentially.
4. **React immediately** when you see `correlated-triage.sh` in a message. Do NOT wait to be asked.
