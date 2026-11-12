---
name: error-propagation
description: Structured error reporting format for triage failures — ERROR_CONTEXT format so next tier can resume without re-doing completed work.
allowed-tools: Bash
user-invocable: false
metadata:
  openclaw:
    always: true
---

# Error Propagation — MANDATORY for all triage failures

When a triage script fails or you encounter errors during investigation, you MUST
report structured error context so the next tier (Claude Code or human) can pick up
where you left off without re-doing completed work.

## Format
If the triage script fails or exits with an error, report:

```
ERROR_CONTEXT:
- Failed at: Step N (step description)
- Completed steps: Step 1 (done), Step 2 (done), Step 3 (FAILED)
- Error: <raw error message>
- Partial findings: <what was discovered before failure>
- Issue ID: <if created before failure, otherwise "not created">
- Suggested next action: <what the next tier should do>
```

## Rules
- ALWAYS include the issue ID if one was created before the failure
- ALWAYS list which steps completed successfully — don't make Claude Code re-do them
- If the script fails to create a YT issue, report that explicitly
- If SSH to a PVE host fails, note which host and what error — it may be down
- If kubectl fails, note whether the cluster is unreachable vs a specific resource error

## Example
```
ERROR_CONTEXT:
- Failed at: Step 3 (Check status on nl-pve03)
- Completed steps: Step 0 (no existing issues), Step 1 (issue IFRNLLEI01PRD-110 created), Step 2 (LibreNMS: linux, LXC VMID_REDACTED on nl-pve03)
- Error: SSH to nl-pve03 timed out after 10s
- Partial findings: Device is LXC on nl-pve03, LibreNMS shows status=down
- Issue ID: IFRNLLEI01PRD-110
- Suggested next action: Check if nl-pve03 itself is down (ping, Proxmox MCP pve_node_status)

CONFIDENCE: 0.2 — Investigation incomplete due to SSH timeout. Cannot determine container state.
```
