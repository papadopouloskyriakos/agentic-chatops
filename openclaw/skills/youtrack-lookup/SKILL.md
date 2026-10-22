---
name: youtrack-lookup
description: Look up YouTrack issues by ID or list open issues. Use this skill FIRST whenever someone mentions an issue ID (CUBEOS-72, MESHSAT-27) or asks about project status, open issues, or issue details. This is for INFORMATION — not implementation. Do NOT escalate lookup requests.
allowed-tools: Bash
user-invocable: true
metadata:
  openclaw:
    always: true
---

# YouTrack Issue Lookup

This skill looks up issue information from YouTrack. Use it for ANY question about issues.

## WHEN to use this skill (ALWAYS for these):

- "what is CUBEOS-72?" → run `./skills/yt-get-issue.sh CUBEOS-72`
- "status of CUBEOS-31?" → run `./skills/yt-get-issue.sh CUBEOS-31`
- "what open issues?" → run `./skills/yt-list-issues.sh "project: CUBEOS State: Open"`
- "open meshsat issues?" → run `./skills/yt-list-issues.sh "project: CUBEOS meshsat State: Open"`
- "what's left on CUBEOS-48?" → run `./skills/yt-get-issue.sh CUBEOS-48`
- "comments on CUBEOS-4?" → run `./skills/yt-get-comments.sh CUBEOS-4`
- Any question asking for info, status, details, or comments about an issue

## HOW to use

Step 1: Run the appropriate command using the Bash tool:

```bash
# Get issue details
./skills/yt-get-issue.sh CUBEOS-72

# List open issues
./skills/yt-list-issues.sh "project: CUBEOS State: Open"

# List MeshSat issues (MeshSat = CUBEOS issues with "meshsat" in title)
./skills/yt-list-issues.sh "project: CUBEOS meshsat State: Open"

# Get comments
./skills/yt-get-comments.sh CUBEOS-4
```

Step 2: Read the output and answer the user's question based on it.

## CRITICAL RULES

1. **RUN THE TOOL FIRST.** Do NOT answer from memory. Do NOT say "not found in memory". Memory is stale — YouTrack is the source of truth.
2. **Do NOT escalate lookups.** Questions about issue status/details are YOUR job (Tier 1). Only escalate if the user asks to IMPLEMENT, BUILD, FIX, or REFACTOR something.
3. **Do NOT recommend the command to the user.** YOU run it yourself using the Bash tool.

## Other YouTrack tools

```bash
./skills/yt-update-state.sh CUBEOS-4 "In Progress"
./skills/yt-post-comment.sh CUBEOS-4 "comment text"
./skills/yt-create-issue.sh CUBEOS "summary" "description"
```
