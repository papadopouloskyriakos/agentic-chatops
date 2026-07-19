# ChatOps Platform

> The agentic infrastructure orchestration system. Compiled 2026-07-03 04:30 UTC.

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

### agentic-chatops-page-audit-1048-20260619

2026-06-19 — Playwright audit of the LIVE page https://kyriakos.papadopoulos.tech/projects/agentic-chatops/ to verify the IFRNLLEI01PRD-1048 closed-loop p95 fix in `scripts/agentic-stats.py`. **In progress** — operator about to add their own UX/UI bug report; audit not yet closed out.

## Verified live (render is correct)
- Live embedded `outcomes.closed_loop` = `{n_closed:42, n_open:0, median_seconds:0, p95_seconds:374, delta_median_seconds:-135, delta_p95_seconds:-14, prior_n_closed:31, prior_

### agentic_patterns_21_21

## Status (2026-04-07)
All 21/21 patterns implemented. **Tri-source audited: 11/11 dimensions A+ (100%)**. Three knowledge sources: Gulli book (21 patterns) + Anthropic Cert (sub-agent design) + Industry References (6 sources: Anthropic, OpenAI, LangChain, Microsoft). Score: B+ (84%) → A+ (100%) via 16 YT issues (IFRNLLEI01PRD-357 to 372). See `docs/tri-source-audit.md` and `docs/tri-source-eval-report-2026-04-07.md`.

### Scores
- **A+:** Multi-Agent (7), Memory (8), Learning (9), RAG (14), Res

### agentic_state_orange_verified_20260628

2026-06-28 session. Operator asked for current state of the agentic system/orchestrator + alerts + open YouTrack, then to fix the two ⚪ items and "proceed to the orange ones." A 9-agent workflow produced an issues table; **on live re-verification before acting, 3 of the orange items were fabricated/misframed by the workflow agents** and dissolved. Textbook instance of [[feedback_verify_agent_generated_doc_claims]] — but sharpened: it now also covers agent *findings/reports* (not just doc-authori

### agentic-stats outcomes block (auto-resolve % + closed-loop median) — MRs !7 / !9

**2026-05-12 coda — superseded:** The "6.0% current vs 40.0% prior" finding below was symptomatic of an event-based metric that double-counts repeat alerts on the same issue_id. On 2026-05-12 commits `1434bb5` + `69bd6f7` flipped the headline to **per-incident, best-outcome semantics** (Google SRE Book Ch 6 / Datadog SRE Maturity Model 2024 / PagerDuty MTTR all use this unit). Same 7d data now reads 28.57% (incident-based, honest); the original 6.74% is preserved as `outcomes.auto_resolve.event_

### kyriakos agentic-stats Token Usage widget audit + fix — 13 findings closed, 17/17 Playwright PASS

2026-05-11 audit + fix of the Token Usage widget on https://kyriakos.papadopoulos.tech/projects/agentic-chatops/.

**Status:** RESOLVED. Audit identified 13 distinct bugs; all 13 fixed in a single commit + deploy + verified live. Pipeline 28833 succeeded in 4m 12s. Live URL now passes 17/17 Playwright tests (13 audit findings + 4 smoke checks).

**Commit:** `kyriakos:729f0bb fix: harden agentic-stats Token Usage widget (13 audit findings)`. Rebased onto `d127441` (BREACH gzip-off). Three files: 

### agentic_top5_fixes_implemented_20260627

**2026-06-27** — implemented the 5 do-now improvements (YT IFRNLLEI01PRD-1446..1450, surfaced by [[definitive_guide_benchmark_20260627]] + [[model_downsizing_audit_20260627]] + the 3-source benchmark). Method: a Workflow of **5 worktree-isolated agents** (one per fix, `isolation:'worktree'`) each implemented+tested+pushed a branch; I **reviewed every diff myself** (verify-claims), then created+merged the MRs. All on main `2ae5c18`, live tree ff-merged + verified.

## WHAT LANDED (all merged)
- *

### feedback-operator-does-not-watch-matrix-polls

The human-in-the-loop has notifications OFF and voted on **almost none** of the Matrix MSC3381 approval polls in the 1–2 months before 2026-06-16. **Exact measurement 2026-06-17 (IFRNLLEI01PRD-1101, via the @claude Matrix CS API over the 3 rooms): 0 of 824 approval polls voted in the trailing 30d (0.0%); ZERO human events of any kind (response/reaction/message) in #infra-nl-prod/#infra-gr-prod/#chatops in 30d; @dominicus's last poll vote was 2026-05-07 (~41 days ago).** So treating Mat

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
- **Runner 8** — `group_type`, scoped to `cubeos-multiarch` on nl-gpu01. Will NOT pick up jobs outside that group.

**Failure 

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
