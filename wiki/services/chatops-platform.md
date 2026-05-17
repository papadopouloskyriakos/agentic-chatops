# ChatOps Platform

> The agentic infrastructure orchestration system. Compiled 2026-05-06 00:48 UTC.

## Architecture

3 subsystems: **ChatOps** (infra alerts), **ChatSecOps** (security alerts), **ChatDevOps** (dev tasks).

Pipeline: External trigger -> n8n webhook -> OpenClaw triage (Tier 1) -> Claude Code (Tier 2) -> Human approval (Tier 3)

### agentic-agriops project — gradual deploy on defra01agri01

# agentic-agriops — gradual mirror deploy on `defra01agri01`

Companion to `defra01agri01_mirror_target.md` (the host inventory + decision log). This file is the **resume-point** for the deploy work itself.

## Goal

Mirror the NL agentic system (n8n + Claude Code + RAG + chaos + Matrix bridge + YouTrack + monitoring) onto `defra01agri01`, scoped to the agri-ERP tenants under `meshsat.org`. Deploy gradually, one service at a time, with an HAProxy allowlist as the day-1 safety net for internal se

### agentic-agriops 3-lane vision + phased build plan

# What agentic-agriops is FOR (operator-stated 2026-04-27)

The runtime stack on defra01agri01 (steps 1-7 complete, step 8 about to start) is the SUBSTRATE. The product on top is THREE distinct lanes, each with its own agents and human-in-the-loop pattern.

## Lane 1 — Developer flow (mirrors NL claude-gateway pattern)

**Trigger sink:** YouTrack `AGRIOPS` project on https://youtrack.meshsat.org

**Repo:** `github.com/<operator>/agentic-agri` (private; operator creates)
- Cloned to `/home/claude

### agentic-agri Matrix room IDs and YouTrack project mapping

# Matrix rooms (matrix.meshsat.org)

All 3 created 2026-04-27 by operator (kyriakos). All private, encrypted-by-default. Bot `@claude-agri:matrix.meshsat.org` invited to all 3.

| Room name | Room ID | Lane |
|---|---|---|
| `#agri-webapp-dev` | `!fspicPzLQVMbvkWQrQ:matrix.meshsat.org` | **Webapp dev flow** — bug fixes / features for the agri-webapp itself (Python/Django code in `papadopouloskyriakos/agentic-agri-webapp`) |
| `#agri-ops-dev` | `!grMDTffLTdRTjiYGvZ:matrix.meshsat.org` | **Ops dev

### agentic-agri service tokens (operator-authorised storage)

# Long-lived service tokens for agentic-agri MCPs

Operator-authorised storage 2026-04-27. File perms 600. Used by `app-user@defra01agri01`'s MCP servers.

## YouTrack admin token

```
perm-YWRtaW4=.NDEtMA==.FCQUOUquMQGYMT91tFbLCQNBjYKRvf
```

- **User:** `admin` (administrator role on `https://youtrack.meshsat.org`)
- **Use:** Authorisation: Bearer header against YT REST API
- **MCP server:** `tonyzorin/youtrack-mcp:latest` (docker)
- **Verified working** 2026-04-27 against `https://youtra

### Agentic-platform sweep — 2026-04-24

Outcome of the 2026-04-24 "are there any agentic-related open tasks/issues" triage pass. 13 items identified, 10 closed by code shipped the same day across 3 commits, 3 remain as operator-decisions (not code gaps).

## Commits

| Commit | What | Impact |
|---|---|---|
| `ee65ec7` | chaos dedup + TRIAGE_JSON booleans fix (k8s/infra/security triage) + CHAOS_STATE_PATH plumbed into `chaos-test.py` + `chaos-port-shutdown.py` + k8s-triage Step-2 pipefail guard | Closes 04-23 12:09 Matrix "Experiment 

### Agentic-platform sweep — 2026-04-25

Single-session sweep on 2026-04-25 — diagnosis + fix of a regression introduced by the 04-24 batch, plus operational cleanup.

## Commits

| Commit | What | Impact |
|---|---|---|
| `8075721` | `fix(chaos): remove cmd_start outer flock self-conflict` | Restores chaos baseline + on-demand drills (every `chaos-test.py start` had been ABORTing since 2026-04-23 evening) |
| `b0647df` | `docs(chaos): refresh stale references to removed cmd_start outer flock` | Updates docstring in `scripts/lib/chaos_

### agentic_patterns_21_21

## Status (2026-04-07)
All 21/21 patterns implemented. **Tri-source audited: 11/11 dimensions A+ (100%)**. Three knowledge sources: Gulli book (21 patterns) + Anthropic Cert (sub-agent design) + Industry References (6 sources: Anthropic, OpenAI, LangChain, Microsoft). Score: B+ (84%) → A+ (100%) via 16 YT issues (IFRNLLEI01PRD-357 to 372). See `docs/tri-source-audit.md` and `docs/tri-source-eval-report-2026-04-07.md`.

### Scores
- **A+:** Multi-Agent (7), Memory (8), Learning (9), RAG (14), Res

### GitHub PATs for agentic-agri repos (operator-authorised storage)

# GitHub PATs for agentic-agri lane

Saved at operator's explicit instruction on 2026-04-27 (token storage policy = memory). File perms 600.

## PAT 1 — papadopouloskyriakos/agentic-agri-webapp (LONG-LIVED)

```
REDACTED_c664fb4a
```

**Scope:** owns `papadopouloskyriakos/agentic-agri-webapp` (private, the actual webapp source). Used by Claude Code runner on defra for clone, push, PR creation. May also work for any other `papadopouloskyriakos/*` repos (e.g., a future `papa

### gitlab_runner_topology

## NL GitLab — gitlab.example.net

**Topology (2026-04-21):**
- **Runner 4** — `project_type`, online, shared across `websites/withelli.com/beta` (id 34) and `infrastructure/nl/production`. Tags: `cisco, docker, lxc, qemu, k8s`. `run_untagged: false`. The **only** online runner with the `docker` tag.
- **Runner 2** — stale/offline (`nlle01k8s-runner01`).
- **Runner 8** — `group_type`, scoped to `cubeos-multiarch` on gpu01. Will NOT pick up jobs outside that group.

**Failure mode = 

### Matrix Bridge Architecture

## Matrix Bridge (QGKnHGkw4casiWIU) - 69 nodes

Polls Matrix /sync from 4 rooms (#chatops, #cubeos, #meshsat, #infra-nl-prod), extracts messages, routes via Command Router (Switch node).

### Room Routing
Extract Messages outputs `sourceRoom` from /sync. All Matrix post nodes use `$('Extract Messages').first().json.sourceRoom` for dynamic room. Runner/SessionEnd use `resolveRoom(issueId)`: CUBEOS→#cubeos, MESHSAT→#meshsat, IFRNLLEI01PRD→#infra-nl-prod, default→#chatops.

### Command Ro

### Runner and Poller Workflow Flows

## Runner Flow (qadF2WcaBsIR7SWG) — 47 nodes

### Primary Path
Acquire Lock → Pre Stats → Query Knowledge (hybrid RRF search + budget check + cost prediction + lessons) → Build Prompt (XML-tagged RAG + defensive prompt + NetBox STEP 0 + ReAct + tool profiles + A/B variant + sub-agent delegation) → Launch Claude (dynamic timeout) → Fire Poller + Wait for Claude → Parse Response (cost ceiling + tool call count/limit + token tracking + self-consistency + ReAct compliance) → Validation retry loop (4
