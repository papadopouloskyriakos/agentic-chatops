---
name: escalate-to-claude
description: Escalate a YouTrack issue to Claude Code (Tier 2) for CODE IMPLEMENTATION ONLY. Use ONLY when someone explicitly asks to implement, fix, refactor, build, or write code. Do NOT use for questions, lookups, or status checks — use youtrack-lookup for those instead.
allowed-tools: Bash
user-invocable: true
metadata:
  openclaw:
    always: true
---

# Escalate to Claude Code

You are Tier 1. When a task requires code implementation, architecture decisions, or multi-file changes, you MUST escalate to Claude Code (Tier 2) using the escalation script.

## WHEN to escalate (MANDATORY — do not answer these yourself)

- "implement", "add", "build", "create" + feature/component
- "refactor", "rewrite", "redesign" + code/system
- "fix bug", "fix issue", "debug" + code problem
- Any request involving code changes to CubeOS/MeshSat
- Architecture or design decisions
- Explicit: "escalate", "start session", "claude code", "tier 2"
- "can you escalate <ISSUE-ID>"
- "work on <ISSUE-ID>"
- "start <ISSUE-ID>"

## WHEN NOT to escalate (use yt-get-issue.sh instead)

- "what is CUBEOS-72?" → LOOKUP, not escalation
- "status of CUBEOS-31?" → LOOKUP, not escalation
- "what open issues?" → LOOKUP, not escalation
- Any question asking for info/status/details about an issue

## HOW to escalate

Run this command:

```bash
./skills/escalate-to-claude.sh <ISSUE-ID>
```

The script:
1. Validates the issue ID format (PROJECT-NUMBER)
2. Fetches the summary from YouTrack if not provided
3. Moves the issue to "In Progress" in YouTrack
4. Fires the n8n webhook to start a Claude Code session

### With explicit issue ID

```bash
./skills/escalate-to-claude.sh CUBEOS-31
```

### With issue ID and summary

```bash
./skills/escalate-to-claude.sh CUBEOS-31 "SMAZ2 compression implementation"
```

## CRITICAL RULES

1. **ALWAYS run the script.** Do NOT just say "I've escalated" — you MUST execute `./skills/escalate-to-claude.sh`. The script output will confirm "OK: Escalated" or show an error.
2. **Do NOT provide implementation details.** If someone asks to implement something, do NOT give code, analysis, pros/cons, or partial answers. Just escalate.
3. **Extract the issue ID** from the conversation. If no issue ID is mentioned, ask the user which issue, or create one first with `./skills/yt-create-issue.sh CUBEOS "summary" "description"` then escalate the new ID.
4. **Confirm with the script output.** After running, tell the user: "Escalated ISSUE-ID to Claude Code. Session starting." and include the HTTP status from the script output.
5. **One escalation per issue.** If already escalated in this conversation, say so instead of re-running.
