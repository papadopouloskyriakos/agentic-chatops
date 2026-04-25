# claude-gateway — n8n Workflow Project

## Context

This repository manages three agentic subsystems for Example Corp Network:
- **ChatOps** — infrastructure alerts (LibreNMS, Prometheus) → `#infra-nl-prod`, `#infra-gr-prod`
- **ChatSecOps** — security alerts (CrowdSec, vulnerability scanners) → same infra rooms
- **ChatDevOps** — development tasks (CI/CD, features) → `#cubeos`, `#meshsat`

All share the same orchestration: n8n workflows bridge external triggers to Claude Code sessions.

- **n8n instance:** https://n8n.example.net
- **GitLab:** https://gitlab.example.net/n8n/claude-gateway (project ID: 30)
- **Claude Code host (NL):** `nl-claude01` — SSH as `app-user`
- **Claude Code host (GR):** `grclaude01` (10.0.X.X) — SSH as `app-user`, oversight agent for NL maintenance
- **Claude Code workspace:** `/app/cubeos`
- **Matrix server:** matrix.example.net
- **Matrix rooms:** `#chatops`, `#cubeos`, `#meshsat`, `#infra-nl-prod`, `#infra-gr-prod` (routed by project prefix; `#claude-gateway` decommissioned)
- **LibreNMS (NL):** https://nl-nms01.example.net (API key in .env, self-signed cert)
- **LibreNMS (GR):** https://gr-nms01.example.net (dedicated GR instance, self-signed cert)
- **IaC repo (NL):** `/app/infrastructure/nl/production`
- **IaC repo (GR):** `/app/infrastructure/gr/production`
- **GR GitLab:** https://gr-gitlab.example.net/ (project ID: 5)
- **GR AWX:** https://gr-awx.example.net
- **Matrix bot:** `@claude:matrix.example.net` (MXID; homeserver is `matrix.example.net`)
- **Mattermost:** mattermost.example.net
- **YouTrack:** https://youtrack.example.net

---

## Available MCP Tools

These MCP servers are configured at user scope and available in every Claude Code session:

| MCP | What to use it for |
|-----|-------------------|
| `netbox` | Query devices, VMs, IPs, VLANs, cables, interfaces, changelogs from NetBox CMDB (310 devices/VMs, 421 IPs, 39 VLANs across 6 sites). **Prefer over LibreNMS for device identification.** |
| `n8n-mcp` | Build and manage n8n workflows — **use this to create, update, activate, and test workflows directly on the n8n instance**. Do NOT just generate JSON files; use the MCP to push and verify. |
| `gitlab-mcp` | Create MRs, check pipeline status, commit workflow exports — use instead of curl for all GitLab operations. |
| `youtrack` | Read issue context at session start, post completion comments at session end. |
| `proxmox` | Proxmox VE API — list nodes/VMs/LXC, get configs and status, start/stop/reboot guests. 15 tools, uses API tokens (no SSH). Lifecycle ops gated by `PVE_ALLOW_LIFECYCLE` env var. |
| `codegraph` | CodeGraphContext — code graph database (KuzuDB). Query function callers/callees, call chains, dependencies, dead code. Indexed repos: CubeOS (355K lines), MeshSat. Venv at `/home/app-user/.cgc-venv/`. |
| `opentofu` | OpenTofu Registry — provider docs, resource schemas, module metadata. Use when writing/editing `.tf` files to get correct argument names and types. |
| `tfmcp` | Terraform/OpenTofu local analysis — module dependency graph, resource dependencies, module health scoring. Use for K8s module dependency analysis. Experimental (v0.1.9). |

---

## Master workflow skill (read first on every infra/security session)

Every session triggered by an alert, YouTrack state change, or Matrix command must load `/chatops-workflow` first. It contains the Phase 0→6 choreography (triage → drift-check → context → propose → approve → execute → post-incident), the Debugging Protocol (Reproduce → Localize → Fix one → Verify → Guard), the Proving-Your-Work directive (pair every CONFIDENCE ≥ 0.8 with visible evidence — enforced by `scripts/classify-session-risk.py`'s `evidence_missing` signal), the general Shortcuts-to-Resist list, and the operator-vocabulary map. Re-read at every phase boundary; context compaction may drop skill bodies. Source: `.claude/skills/chatops-workflow/SKILL.md`. Pure-dev sessions (code-explorer / CI-debugger / workflow-validator) do NOT need this skill.

---

## 03_Lab Reference Library

Path: `/app/reference-library/` (~10 GB, ~5,200 files, synced via Syncthing to nl-claude01 + nl-openclaw01).

Supplementary reference library covering everything that NetBox (CMDB) and GitLab (IaC) don't store: hardware documentation, physical wiring, change history, firmware, topology diagrams, ISP records, and per-host operational notes. You can read any file directly.

Structure: `NL/Servers|Inventory|Changes|Firmware/`, `GR/gr/`, `Cross-Site/network_info.xlsx|Designs/`, `Research/`.

Queryable via `./openclaw/skills/lab-lookup/lab-lookup.sh`: `port-map`, `nic-config`, `vlan-devices`, `switch-ports`, `docs`, `ups-pdu`. Read files directly: `Read /app/reference-library/NL/Servers/<host>/`.

### Data trust hierarchy (ALWAYS follow this order):
1. **Running config on the live device** — SSH and check (`show run`, `ip a`, `pct config`, `kubectl get`). This is the ONLY 100% truth.
2. **LibreNMS** — active monitoring, real-time status. What's happening NOW.
3. **NetBox** — CMDB inventory (devices, IPs, VLANs). Accurate but manually maintained — can drift.
4. **03_Lab, GitLab IaC, backups** — supplementary reference. Useful context but can be stale.

**If 03_Lab contradicts a live device, the live device wins. Always.** Never modify 03_Lab files.

---

## Syslog-ng Central Logging

Both sites have syslog-ng servers collecting logs from all hosts:

| Site | Server | Base Path |
|------|--------|-----------|
| NL | `nlsyslogng01` | `/mnt/logs/syslog-ng/` |
| GR | `grsyslogng01` | `/mnt/logs/syslog-ng/` |

Log path: `{base}/{hostname}/{year}/{month}/{hostname}-{date}.log`

**Terminal session logging:** All hosts forward terminal commands to syslog-ng, tagged `terminal-session:`. Format:
```
terminal-session: user=root tty=/dev/pts/3 pwd=/root ssh=10.0.181.X cmd=claude
```

To query terminal sessions for a host (answers "what did someone do on this host?"):
```bash
ssh -i ~/.ssh/one_key root@nlsyslogng01 \
  "cat /mnt/logs/syslog-ng/<hostname>/2026/04/<hostname>-2026-04-08.log | grep 'terminal-session:' | grep -v 'message repeated' | tail -15"
```

OpenClaw's `fetch_terminal_sessions()` in `site-config.sh` does this automatically during infra-triage (Step 2b).

---

## n8n Node Schemas

n8n-as-code is installed at `node_modules/n8n-as-code`. It contains offline schemas for 537 n8n nodes, 10,209 properties, and 7,702 workflow templates.

**MANDATORY:** Before configuring any n8n node, look up its exact schema first:
- Search nodes: `npx n8n-as-code search <node-name>`
- Get full schema: `npx n8n-as-code schema <node-name>`
- Find templates: `npx n8n-as-code templates <keyword>`

Never guess n8n node parameter names, field paths, or valid values. Every gateway bug so far (sessionExpired false positive, wrong routing, missing subcommands) was caused by hallucinated node configs. The schemas are available — use them.

---

## Architecture

```
YouTrack issue state → In Progress
          ↓
    n8n webhook trigger
          ↓
    n8n SSH: Launch Claude in background with nohup
    runs: claude -p "prompt" --output-format stream-json --verbose
    returns PID + session_id immediately
          ↓
    n8n fires Progress Poller workflow (async)
    Poller polls JSONL log every 30s, posts tool activity to Matrix as m.notice
          ↓
    n8n SSH: Wait for Claude (polls PID every 5s)
    extracts final result from JSONL when PID exits
          ↓
    n8n → Matrix room message
          ↓
    User replies in Matrix
          ↓
    n8n SSH Execute Command node (resume session)
    runs: claude -r <session-id> -p "message" --output-format json
          ↓
    Loop until done
          ↓
    n8n posts completion comment to YouTrack issue
```

### Key Design Decisions

- **Background launch + progress polling** — Claude runs via `nohup ... &` with `--output-format stream-json --verbose`, writing JSONL to `/tmp/claude-run-<ISSUE>.jsonl`. A separate Poller workflow reads new lines every 30s and posts tool activity to Matrix as `m.notice`. A Wait node polls the PID every 5s and extracts the final result when Claude exits. This gives users real-time visibility into what Claude is doing during 5-15 minute runs.
- **Session continuity via `-r` flag** — first invocation creates a session and returns a `session_id`. Subsequent invocations use `claude -r <session-id> -p "message" --output-format stream-json` to resume the conversation. The `session_id` is stored in SQLite between workflow executions.
- **Matrix as the human-in-the-loop interface** — Claude Code response posted to Matrix, user replies trigger next workflow execution which resumes the session.
- **YouTrack as the trigger and sink** — webhook starts the session, completion comment ends it.

---

## LLM Usage Tracking

Per-model token/cost tracking across 3 tiers (`llm_usage` table — single source of truth), exposed via Prometheus (`write-model-metrics.sh`, cron `*/5`). 3 portfolio stats APIs serve live data to Hugo: `/webhook/agentic-stats` (IDs: `ncUp08mWsdrtBwMA`), `/webhook/lab-stats` (`B90NqTknqhInVLYP`), `/webhook/mesh-stats` (`PrcigdZNWvTj9YaL`). **5 writers** feed `llm_usage`: (1) Runner `Write Session File` (Tier 2, per-session JSONL extraction, has issue_id), (2) `poll-openai-usage.sh` (Tier 1, hourly, OpenAI Admin API), (3) `poll-claude-usage.sh` (Tier 2, `*/30`, reads JSONL session files from `~/.claude/projects/**/*.jsonl` with byte-offset watermark — rewritten 2026-04-10, was stats-cache.json which stopped updating after Claude Code 2.1.x; rows marked `issue_id='cli-session'`), (4) `llm-judge.sh` (Tier 2, per-judgment), (5) `_record_local_usage()` in 4 scripts (Tier 0, per-Ollama-call: kb-semantic-search.py, archive-session-transcript.py, ragas-eval.py, agent-diary.py). `agentic-stats.py` reads only from `llm_usage` — no estimation or fabrication. Token formula: full count (input+output+cache_read+cache_write) for rows with `issue_id != ''`; `input+output` only for old Claude poller rows with empty issue_id (inflated cache values). Tier 2 cost = $0 for Max subscription (interactive CLI), API-equivalent ~$16,420 total. **Portfolio widget** (`agentic-stats.html`): client-side JS with data inlined at Hugo build time via `site.Data` (n8n API is internal-only). CI schedule `*/5` on website repo refreshes data. See [`docs/llm-usage-tracking.md`](docs/llm-usage-tracking.md) for full details.

**Local-first judge + synth defaults (2026-04-19):** `JUDGE_BACKEND=local` (gemma3:12b via Ollama, qwen2.5:7b fallback) across `run-hard-eval.py`, `ragas-eval.py`, `llm-judge.sh`. `SYNTH_BACKEND=qwen` in `kb-semantic-search.py`. Max-effort flagged sessions still use Opus. Calibration = 85% agreement with Haiku across 60 dual-scored queries, +5pp looser (local calls more borderline cases "hit"). **Never compare hit-rate numbers across 2026-04-19 without stamping the judge source** — the +5pp calibration gap means a bump could be zero real improvement. Flip `JUDGE_BACKEND=haiku` for KG/policy/meta/specific-incident benchmarks or calibration re-runs. Full baseline: `docs/judge-calibration-2026-04-19.md`.

---

## MemPalace Integration (2026-04-09)

8 patterns ported from [mempalace](https://github.com/milla-jovovich/mempalace). New tables: `session_transcripts` (verbatim chunks + embeddings), `agent_diary` (persistent per-agent memory). Temporal KG via `incident_knowledge.valid_until`. Hooks: Stop (auto-save every 15 msgs) + PreCompact (emergency save). RAG upgraded to **5-signal RRF** (`semantic + keyword + wiki + 0.3*transcript + 0.25*chaos_baselines`). See [`docs/mempalace-details.md`](docs/mempalace-details.md) for full details.

---

## Compiled Knowledge Base (Karpathy-Style Wiki)

[Karpathy-style](https://x.com/karpathy/status/2039805659525644595) wiki at `wiki/` — 45 articles compiled from 7+ sources (memories, CLAUDE.md files, incidents, OpenClaw, docs, 03_Lab, Grafana). Compiler: `scripts/wiki-compile.py` (SHA-256 incremental, daily 04:30 UTC cron + `/wiki-compile` skill). All articles embedded into `wiki_articles` table as 3rd RRF signal. Health: `wiki-compile.py --health`. See [`docs/compiled-wiki-details.md`](docs/compiled-wiki-details.md) for source mapping and CLI usage.

---

## Operational runbooks

- **Rerank service (bge-reranker-v2-m3 at nl-gpu01:11436)** — [`docs/runbooks/rerank-service.md`](docs/runbooks/rerank-service.md). Rollback via `RERANK_BACKEND=ollama` env, container restart, model cache rebuild. Prometheus alert: `RAGRerankServiceDown`.
- **n8n Code-node safety (post 14h-outage)** — [`docs/runbooks/n8n-code-node-safety.md`](docs/runbooks/n8n-code-node-safety.md). Mandatory pre-push validator (`scripts/validate-n8n-code-nodes.sh`) for any Code-node edit. Required sequence: fetch → snapshot → edit → `--check` → splice → validate → PUT → re-fetch → re-validate → test-fire → commit.
- **Risk-based auto-approval integration** — [`docs/runbooks/risk-based-auto-approval.md`](docs/runbooks/risk-based-auto-approval.md). How the Classify Risk SSH → Build Prompt risk-section → Bridge `[AUTO-RESOLVE]` chain is wired. Weekly audit at `scripts/audit-risk-decisions.sh` enforces the no-false-positive invariant.
- **Memory promotion pipeline** — [`docs/runbooks/memory-promotion-pipeline.md`](docs/runbooks/memory-promotion-pipeline.md). Operator workflow for running `scripts/memory-audit.py` and distilling clusters.
- **Skill versioning (SKILL.md semver)** — [`docs/runbooks/skill-versioning.md`](docs/runbooks/skill-versioning.md). When to bump patch/minor/MAJOR on a SKILL.md. `scripts/audit-skill-versions.sh` is advisory stale-skill detection via git history; `scripts/audit-skill-requires.sh` checks the declared `requires.bins` + `requires.env` against host state; Prometheus alerts `SkillPrereqMissing` + `SkillMetricsExporterStale` in `prometheus/alert-rules/agentic-health.yml`. Full e2e proofs (vocab hook → event_log row, promtool test rules inside live Prom pod, real Runner session grepping injected master-skill body, evidence_missing forces [POLL]) landed 2026-04-23 under IFRNLLEI01PRD-712..-724. Public-surface parity (README.md + README.extensive.md + portfolio page) caught up 2026-04-24 under IFRNLLEI01PRD-725 — commits `b0fb968` (claude-gateway) + `149bef8` (website); GitHub mirror `papadopouloskyriakos/agentic-chatops@920bd33` reflects the uplift.

Other ops docs: [`docs/rag-architecture-current.md`](docs/rag-architecture-current.md) (auto-refreshed), [`docs/rag-metrics-reference.md`](docs/rag-metrics-reference.md), [`docs/crontab-reference.md`](docs/crontab-reference.md), [`docs/network-addresses.md`](docs/network-addresses.md), [`docs/host-blast-radius.md`](docs/host-blast-radius.md), [`docs/scorecard-post-agents-cli-adoption.md`](docs/scorecard-post-agents-cli-adoption.md).

---

## Maintenance Mode

When `/home/app-user/gateway.maintenance` exists (JSON with `started`, `reason`, `eta_minutes`, `operator`), alert processing is suppressed across all receivers, watchdog, and OpenClaw triage. Created/removed by AWX playbook or manually. 15-minute post-maintenance cooldown tags alerts as `post-maintenance-recovery`.

**ASA weekly reboot: DISABLED (2026-04-10).** EEM watchdog applets removed from both ASAs after the weekly reboot caused VTI tunnel instability and cascading cross-site outages. `asa-reboot-watch.sh` cron commented out. Manual reloads use the maintenance companion (`/maintenance`). **Freedom ISP:** dual WAN with SLA failover + QoS toggle (with ping fallback) + SMS alerts via Twilio. **PVE kernel:** AWX cross-site automation (GR from NL template 69, NL from GR template 21). **Inter-site routing:** Full BGP via direct peering over VTI. Freedom path on NL fw01 (LP 200 via route-map FREEDOM_IN). Budget path (formerly xs4all; renamed 2026-04-21) terminates on dedicated edge router `nlrtr01` (ISR 4321) with dedicated /30 transit subnet 10.0.X.X/30 to fw01 `outside_budget` sec-0. rtr01 peers iBGP with fw01, NL FRRs, GR ASA, and both VPSs (LP 100 default → backup path). GR side has route-map BUDGET_IN (LP 150). FRR transit LP 100. No static inter-site routes (2026-04-10). rtr01 is fully isolated from VLAN 10/inside_mgmt — mirrors the lte01 edge-router design pattern. **VPS BGP peering:** VPS nodes MUST use VTI point-to-point addresses (not loopback) as `update-source` for site RR peers -- loopback next-hops are unresolvable by ASAs. `maximum-paths ibgp 1` on VPS prevents cross-tunnel ECMP asymmetric routing through stateful ASAs (2026-04-14). 8 FRR instances: 4 RRs (2 per site, cluster-id 1.1.1.1 NL / 2.2.2.2 GR) + 2 VPS + 2 ASAs as RR clients. See [`docs/maintenance-mode-details.md`](docs/maintenance-mode-details.md) for full details.

---

## Known Host Pressure: nl-pve01 (remediated 2026-04-19, re-drift 2026-04-22)

n8n LXC (CT VMID_REDACTED, hostname `nl-n8n01`, 10.0.181.X) lives on **nl-pve01**. Two remediations landed 2026-04-19 after IFRNLLEI01PRD-622 (LXC cgroup OOM-kill every ~90 min, 69 lifetime events):

- **LXC RAM bumped 2G → 4G** via `pct set VMID_REDACTED -memory 4096` (hot cgroup resize, no restart). RSS stable at ~140 MB post-fix; cron `scripts/n8n-rss-watch.sh` (*/15) alerts to Matrix if RSS crosses 3 GiB (leak canary). Baseline log at `~/logs/claude-gateway/n8n-rss.log`.
- **pve01 zramswap** installed (zstd, PERCENT=10 → 9.4 GiB, priority 100). Previously zero-swap amplified every host-IO pressure incident.

**2026-04-22 re-drift (IFRNLLEI01PRD-692 + -704).** Host drifted back into the same class of memory pressure — load avg 13-25, zramswap 99.96% saturated, 8G free of 94G. Caused `KubeAPIErrorBudgetBurn` via `kube-apiserver-nlk8s-ctrl01` (791 restarts) whose local etcd fsyncs stall under host pressure. Root cause: **no balloon floor on any pve01 VM** — `ctrl01` has `balloon: 0` (device disabled), the other 6 VMs have the device but `balloon:` unset (min=max = no reclaim). `pvestatd auto_balloon` cannot reclaim without a floor. **Remediation pending in IFRNLLEI01PRD-704** (on hold): attach balloon device on ctrl01 (`qm set VMID_REDACTED -balloon 4096`, ~60s downtime, quorum 2-of-3 holds) + set floors on the other 6 live (zero downtime). Total reclaimable headroom ~17 GiB across the fleet.

Prior failure modes: SQLite writer-mutex 200 ms timeout on host IO spike (IFRNLLEI01PRD-589, 2026-04-16) and LXC cgroup OOM on n8n RSS creep (IFRNLLEI01PRD-622, 2026-04-19) should no longer recur under normal load. When debugging brief n8n unavailability, still check pve01 host pressure first — cron alert + the zram cushion buys time, but the host is still memory-overcommitted under heavy VM load.

---

## Operating Modes

The file `/home/app-user/gateway.mode` controls which frontend/backend pair is active.

| Mode | Frontend | Backend | Status |
|------|----------|---------|--------|
| `oc-cc` | OpenClaw | Claude Code via n8n | DEFAULT — active |
| `oc-oc` | OpenClaw | OpenClaw/GPT-5.1 (self-contained) | Available |
| `cc-cc` | n8n/Claude Code | Claude Code (legacy) | Available |
| `cc-oc` | n8n session mgmt | OpenClaw as backend (via docker exec) | Available |

Switch modes with the `!mode <mode>` command in any Matrix room where OpenClaw is present.

---

## Conventions

- Branch naming: `feature/description` or `fix/description`
- Create MRs, don't push directly to main
- Workflow names prefixed with `"NL - "`
- Export workflow JSON after every change via n8n-mcp, save to `workflows/`
- Workflow JSON filenames: `claude-gateway-{workflow-slug}.json`
- n8n node versions: use httpRequest v4.2, webhook v2
- n8n version: **2.47.6** (community edition)
- n8n-mcp version: 2.47.1
- **Switch V3.2 known issue (n8n 2.41.3):** Rules created via API/MCP omit `conditions.options` block, causing `extractValue` crash. ALWAYS include `conditions.options: {version: 2, caseSensitive: true, typeValidation: "strict"}` in each rule's conditions when creating Switch V3.2 nodes programmatically. Compare with LibreNMS receiver "Repeat Action" node for reference. After any workflow update via API, toggle deactivate→activate to reload webhook listeners.
- **Full hostnames:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, gr-pve01 not pve01). Multi-site environment makes short forms ambiguous. Applies to all output: playbooks, comments, memory, YT, Matrix messages.
- **Code-node edits require validator (post-14h-outage gate):** Before any `curl -X PUT /api/v1/workflows/<id>` that modifies a Code node's `jsCode`, run `scripts/validate-n8n-code-nodes.sh --file <patched-workflow.json>` (or `<workflow-id>` to fetch live). Must return **VALIDATION PASSED** — checks `node --check`, `new Function()` parse, exactly 1 top-level `return` (dead code is a `[FAIL]`), and flags duplicate top-level `var` declarations. The Build Prompt node was cleaned 2026-04-19 (90 KB → 36 KB, 3 returns → 1); the validator prevents the 14h-outage-class regression. Full runbook: `docs/runbooks/n8n-code-node-safety.md`.
- **Risk-based auto-approval (IFRNLLEI01PRD-632, 2026-04-19):** Runner has `Classify Risk` SSH node between Build Plan and Build Prompt. Classifier (`scripts/classify-session-risk.py`) emits `{risk_level, auto_approve_recommended, signals, plan_hash}`; Build Prompt injects `## SESSION RISK:` section instructing Claude to end with `[AUTO-RESOLVE]` (low-risk) or `[POLL]` (mixed/high). Matrix Bridge parses `[AUTO-RESOLVE]` and posts as `m.notice` (no ping). Every classification writes to `session_risk_audit` table; `scripts/audit-risk-decisions.sh` + holistic-health enforce the invariant "no `auto_approved=1` row with `risk_level != 'low'`." Integration replay in `scripts/test-risk-integration.sh` (10/10 deterministic cases). HIGH-risk categories: `maintenance`, `security-incident`, `deployment`. Fail-closed: `RISK_FAIL_CLOSED=1` forces `high` on parse errors.
- **RAG circuit breakers (IFRNLLEI01PRD-631, 2026-04-19):** 4 named breakers guard the RAG external-call path — `rag_rerank_crossencoder`, `rag_embed_ollama`, `rag_synth_haiku`, `rag_synth_ollama`. SQLite-backed state (`circuit_breakers` table); Prometheus metrics via `scripts/write-circuit-breaker-metrics.sh` cron `*/5`. `CircuitBreakerOpen` alert fires if any stays OPEN ≥10 min. Inspect: `cd scripts && python3 -m lib.circuit_breaker list`. Reset: `python3 -m lib.circuit_breaker reset <name>`. Lib at `scripts/lib/circuit_breaker.py` — imperative `allow()/record_success()/record_failure()` API or decorator.
- **Schema versioning (IFRNLLEI01PRD-635, 2026-04-20):** 9 session/audit tables (`sessions`, `session_log`, `session_transcripts`, `execution_log`, `tool_call_log`, `agent_diary`, `session_trajectory`, `session_judgment`, `session_risk_audit`) carry a `schema_version INTEGER DEFAULT 1` column stamped by every writer. Canonical registry lives at `scripts/lib/schema_version.py` (`CURRENT_SCHEMA_VERSION` dict + `SCHEMA_VERSION_SUMMARIES`, mirroring OpenAI Agents SDK `run_state.py:131`). Python writers import `from schema_version import current as schema_current` and stamp via INSERT; bash writers hardcode `1` with a comment pointing to the registry (bump both when a version rolls). Readers that decode structured payload columns call `check_row(table, row.schema_version)` which raises `SchemaVersionError` if a row was written by a newer schema than the reader understands. Migration: `scripts/migrations/006_schema_versioning.sql` (idempotent via apply.py). Holistic-health section 33 asserts no null `schema_version` across the 9 tables. **When you change the JSON shape of any payload column in these tables, bump the corresponding `CURRENT_SCHEMA_VERSION[table]` value AND add a new line to `SCHEMA_VERSION_SUMMARIES[table]` describing the change.**
- **OpenAI SDK adoption batch (IFRNLLEI01PRD-635..643, 2026-04-20):** 9 structural upgrades adapted from `openai/openai-agents-python` v0.14.2 — schema versioning on 9 tables (-635), immutable per-turn snapshots (-636), 13 typed events in `event_log` (-637), per-turn lifecycle hooks (-638), 3-behavior rejection taxonomy allow/reject_content/deny (-639), `HandoffInputData` zlib+b64 envelope with 0.43% ratio (-640), optional gemma3:12b transcript compaction (-641), `agent_as_tool.py` wrapper for ambiguous-risk band 0.4-0.6 (-642), `handoff_depth`+`handoff_chain` with ≥5 forces `[POLL]`/≥10 hard-halts/cycles refused (-643). 4 new tables → 35 total. **NOT adopted:** OutputGuardrail (deferred), per-tool `needs_approval`, auto-trace to OpenAI, strict Pydantic sub-agent output, always-on `nest_handoff_history`. Full reference: `memory/openai_sdk_adoption_batch.md` + `README.extensive.md` §22.
- **QA suite (2026-04-20, expanded 2026-04-23):** `scripts/qa/run-qa-suite.sh` — pytest-style bash harness, **44 suite files** (was 30+), **~3-5 min runtime** under full-suite load, JSON scorecard in `scripts/qa/reports/`. **Per-suite timeout guard** (IFRNLLEI01PRD-724, default `QA_PER_SUITE_TIMEOUT=120s`, override via env) prevents any single slow/hung suite from wedging the orchestrator; synthetic FAIL record emitted to scorecard on timeout. Covers: writer coverage (schema_version=1 across 11 writers + 5 n8n INSERT sites), 85 rejection patterns (53 deny + 32 reject_content), 13 event-class payload shapes, 8-parallel concurrent fuzz, local HTTP mock for offline compaction, 6 e2e scenarios, 16 prompt-patcher tests, 7 benchmarks, plus 9 umbrella-added tests (test-656/-660/-718/-724/-726/-727). **Last hardened run (2026-04-23): 411/0/2 = 99.52%**, up from 368/4/2. **Run after any change to the adoption-batch surfaces or the patcher.**
- **Teacher-agent reliability pass (2026-04-23):** 5 post-ship bugs closed after operator DM audit (full detail: `memory/teacher_agent_dm_audit_20260423.md`): Command Router double-wiring (`501ff47`); `cmd_grade` UPDATE using wrong PK left `completed_at=NULL` forever (`3d9c0da`); Mastery/SM-2/Bloom moved even on low grader_confidence — now `low_conf` branch holds schedule steady (`3d9c0da`); teacher-runner webhook `responseMode: responseNode→onReceived` + removed now-unreachable Respond node (they're coupled; onReceived+terminal-Respond returns HTTP 500 that `neverError:true` swallows) (`33d64c8`+`99dc9fc`); `cmd_chat` SQLite-lock crash masked by Ollama success — fixed with `timeout=30`+`PRAGMA busy_timeout=30000` + post-to-Matrix-before-audit-UPDATE + try/except around `cmd_grade` DB block (`feb2bae`). Also added `docs/gulli-book-overview.md` + 30 chapter extracts under `docs/gulli-book/` (embeddings 1189→1309 rows, `cec2c0c`). Reusable feedback: `memory/feedback_sqlite_busy_timeout.md` + `.claude/rules/workflows.md`.
- **Teacher-agent gate (IFRNLLEI01PRD-655, 2026-04-20):** Fifth and final tier. Gate deliverables: **(a)** `scripts/audit-teacher-invariants.sh` — enforces all 6 invariants + the privacy default from the plan §8 against the live repo/DB (tool allowlist, no DELETEs on learning_*/teacher_operator_dm, mastery_score writes confined to cmd_grade+_upsert_progress, grader_confidence<0.6 gate present in quiz_grader.py, three-tier renderers+LLM+operator pipeline intact, learning_sessions.completed_at NULL-is-resumable, `teacher_operator_dm.public_sharing DEFAULT 0`); read-only, exits 0 iff all pass. **(b)** `scripts/teacher-calibration-baseline.py` — grader calibration harness with 12 synthetic fixtures spanning 5 bands (excellent / good / partial / wrong / irrelevant) at `scripts/qa/fixtures/teacher-calibration-fixtures.json`; `--offline` uses a deterministic `_ollama_fn` stub (used by QA, 100% agreement on seeded scores); live mode calls the real gemma3:12b grader and asserts band agreement ≥ `--threshold` (default 0.85). Writes JSON report to `scripts/qa/reports/calibration-<stamp>.json`. **(c)** `docs/runbooks/teacher-agent.md` — ops runbook covering architecture, data surfaces, Prometheus signals, alert response for all 3 alerts, operator lifecycle (add/pause/remove), maintenance-mode interaction, "!learn is silent" debug ladder, 5-stage rollback. **(d)** QA `scripts/qa/suites/test-655-teacher-agent-gate.sh` — **9/9 PASS** covering invariant-audit-passes-live, invariant-audit-detects-seeded-Edit-violation (sandboxed mutation), calibration-offline-hits-85%, fixtures-cover-all-5-bands, runbook-exists-and-references-audit-and-calibration, all-5-tier-suites-auto-discoverable, CLAUDE.md references every tier issue ID, plan doc exists with -655 reference, crontab-reference.md catalogs teacher entries. **Combined teacher-agent test count: 62/62** (13 foundation + 17 intelligence + 14 interface + 9 loop + 9 gate). The full teacher-agent stack — migration 013+014, SM-2, Bloom, quiz gen with hallucination gate, quiz grade with confidence clarifier, Matrix client, matrix-bridge integration (Switch V3.2 `conditions.options` block included), HTML lesson rendering, 10 Prometheus metrics, 3 alerts, 12-panel Grafana dashboard, 3 crons, invariant audit, calibration baseline, ops runbook — is now feature-complete. Real-data calibration (operator's quiz history replacing synthetic fixtures) is the natural follow-up but requires ≥20 graded answers to be meaningful, which only accumulates after normal use.
- **Teacher-agent loop (IFRNLLEI01PRD-654, 2026-04-20):** Fourth of 5 tiers. Operational scaffolding: **3 crons** — `30 8 * * *` morning-nudge (DM each operator with due topics), `0 16 * * 0` weekly class-digest (aggregate post to `#learning`), `*/5 * * * *` `scripts/write-learning-metrics.sh` (Prometheus exporter). **10 metrics**: `learning_topics_total/mastered/due{operator}`, `learning_quiz_accuracy_7d{operator}`, `learning_weekly_sessions_total{operator}`, `learning_longest_streak_days{operator}`, `learning_bloom_distribution{operator,bloom_level}`, `learning_operators_total`, `learning_morning_nudge_last_run_timestamp`, `learning_class_digest_last_run_timestamp`. Streak is computed in Python (walk distinct session dates backwards from today, allowing today-or-yesterday as alive anchor). **3 alerts** in `prometheus/alert-rules/teacher-agent.yml` — `TeacherAgentMetricsAbsent` (exporter dead 15m), `TeacherAgentMorningNudgeStale` (no nudge in 36h), `TeacherAgentClassDigestStale` (no digest in 14d). Stale-cron alerts key off `time() - learning_*_last_run_timestamp` where the timestamp is bumped by `_touch_last_run(kind)` writing to `/var/lib/claude-gateway/teacher-<kind>.last`. **Grafana dashboard** `grafana/teacher-agent.json` (uid=`teacher-agent`): 12 panels — 6 stat headers + mastery bargauge + Bloom piechart + 4 timeseries (weekly sessions, quiz accuracy, due topics, cron freshness). QA `scripts/qa/suites/test-654-teacher-agent-loop.sh` — **9/9 PASS** covering exporter emission (all 10 metric families + seeded-row value assertions), atomic tmp→rename, pre-migration graceful degrade, alert YAML parse, dashboard metric coverage, last-run lockfile touch, crontab presence, crontab-reference.md update. Combined -651+-652+-653+-654 teacher-agent test count: **53/53**. Textfile dir is `/var/lib/node_exporter/textfile_collector/` (matches write-agent-metrics.sh et al. — the `/var/lib/prometheus/node-exporter/` path used by some newer scripts does not exist on this host). Only **-655 gate** (full QA + runbook + invariant audits + judge calibration baseline) remains.
- **Teacher-agent interface (IFRNLLEI01PRD-653, 2026-04-20, COMPLETE):** Third of 5 tiers. Landed: migration 014 (`teacher_operator_dm` table — brings total to **42 tables**); `scripts/lib/matrix_teacher.py` — minimal Matrix client-server API helper (membership check, lazy DM create/cache, m.text + m.notice posters) via `MATRIX_CLAUDE_TOKEN` bearer; `scripts/teacher-agent.py` orchestrator — subcommands `--next/--lesson/--quiz/--grade/--progress/--class-digest/--morning-nudge/--pause/--resume/--public-on/--public-off/--resolve-dm`, source-room-aware (in-channel ack + DM delivery), authorization-gated via membership in `#learning` (`!HdUfKpzHeplqBOYvwY:matrix.example.net`); `.claude/agents/teacher-agent.md` with read-only tool allowlist (Read/Grep/Glob/Bash/ToolSearch — Edit/Write/MultiEdit explicitly excluded); `workflows/claude-gateway-teacher-runner.json` new workflow (webhook `/teacher-command` → Code parser → SSH node → Code output-parser → RespondToWebhook). **Multi-user classroom design**: `#learning` is the authorization room; bot DMs each operator privately for lessons/quizzes/private progress; in-channel posts only for aggregate class-digest + opt-in leaderboard. Per-operator `public_sharing` flag defaults OFF — **privacy-first invariant**. QA `scripts/qa/suites/test-653-teacher-agent-interface.sh` 14/14 PASS (offline: Matrix API + Ollama both stubbed via injection). Combined -651+-652+-653 teacher-agent test count: **44/44**. **REMAINING for -653**: matrix-bridge partial-workflow patch to add `!learn`/`!quiz`/`!progress`/`!digest` command handlers routing to `/teacher-command` webhook; validator-gated per `docs/runbooks/n8n-code-node-safety.md`.
- **Teacher-agent intelligence (IFRNLLEI01PRD-652, 2026-04-20):** Second of 5 tiers. `scripts/lib/bloom.py` — 7-level progression (`BLOOM_LEVELS`, `band_for`, `candidates_for`, `select_target_bloom(mastery, repetition)` rotates within-band, `is_advance`). `scripts/lib/quiz_generator.py` — Ollama gemma3:12b `format=json` with **hallucination gate**: every `source_snippets[i].verbatim_text` must be ≥8 chars AND substring of concatenated sources, `bloom_level`/`question_type` must match target; retries 3× with tightened prompt including prior rejection; breaker-aware via `rag_synth_ollama`. `scripts/lib/quiz_grader.py` — outputs score (clamped [0,1]), feedback (must cite source), bloom_demonstrated, citation_check, clarifying_question, grader_confidence; **Invariant #4 enforcement**: low grader_confidence (<0.6) forces a clarifying_question so we never advance progression on a dubious score. All three libs accept `_ollama_fn` injection for offline tests. QA: `scripts/qa/suites/test-652-teacher-agent-intelligence.sh` — **17/17 PASS**, zero network dependency. Combined -651+-652 suite count: 30/30 PASS. Judge calibration (20-answer ≥85% agreement baseline) deferred to -655 gate with real data.
- **Teacher-agent foundation (IFRNLLEI01PRD-651, 2026-04-20):** First of 5 tiers of an introspective learning module that teaches the operator about agentic-systems theory using the system's own documentation. Landed: migration 013 (`learning_progress` + `learning_sessions` tables, bringing total to **41 tables**), `scripts/lib/sm2.py` (pure SuperMemo-2 scheduler with EF clamped to `[1.3, 2.5]`, `quality_from_score` mapping grader 0-1 to SM-2 0-5 via `round(score*5)`, `due_topics()` sort by next_due asc then mastery asc), `config/curriculum.json` + `scripts/rebuild-curriculum.py` (auto-derives 53 topics across 4 curricula — foundations/patterns/platform/memory — from wiki + docs + memory; operator edits preserved via `origin: operator-edited` on re-run), schema-version registry updated. QA `scripts/qa/suites/test-651-teacher-agent-foundation.sh` 13/13 PASS covering SM-2 math, schema registry, migration idempotency, uniqueness constraint, ≥30-topic gate, 4-curricula shape, stability on re-run. Next tiers: -652 intelligence (quiz gen+grade, hallucination gate), -653 interface (CLI+agent+n8n+Matrix), -654 loop (crons+metrics), -655 gate (full QA suite + invariant audits). Plan: `docs/plans/teacher-agent-implementation-plan.md`.
- **CLI-session RAG capture (IFRNLLEI01PRD-646/-647/-648, 2026-04-20, ALL WIRED 2026-04-24):** Interactive `claude` CLI sessions flow into RAG tables (closes ~2,300 JSONL gap). Tier 1 `backfill-cli-transcripts.sh` (archive + parse-tool-calls + extract-cli-knowledge, tagged `issue_id='cli-<uuid>'`, watermark file). Tier 2 gemma3:12b over summary rows → structured incident_knowledge (`project='chatops-cli'`, breaker-aware). Tier 3 `parse-tool-calls.py::extract_issue_id_from_path` resolves JSONL → `cli-<uuid>`. `kb-semantic-search.py` `CLI_INCIDENT_WEIGHT=0.75` discounts cli rows at retrieval. QA `test-646-cli-session-rag-capture.sh` 12/12 PASS. **Cron installed** (`30 4 * * *`) + firing nightly — 04-24 run processed 50 files / 255 transcript chunks / 2831 tool-call rows / 25 knowledge extractions. Details: `memory/cli_session_rag_capture.md`.
- **Preference-iterating prompt patcher (IFRNLLEI01PRD-645, 2026-04-20, ALL WIRED):** Policy iteration at the prompt level. When a (surface, dimension) score drops below threshold, `scripts/prompt-patch-trial.py --start` generates 3 candidate variants (concise/detailed/examples) + control. Build Prompt deterministically buckets sessions via `hash(issue_id|trial_id) % (N+1)`. `scripts/finalize-prompt-trials.py` (cron daily 03:17 UTC) runs one-sided Welch t-test when all arms reach 15 samples; promotes winner to `config/prompt-patches.json` if lift ≥0.05 with p<0.1. Aborts on timeout (14d) or no-winner. Library: `scripts/lib/prompt_patch_trial.py` (race-safe SQLite). Enable: `PROMPT_TRIAL_ENABLED=1`. Prometheus via `scripts/write-trial-metrics.sh` (`*/10`). 2 new tables → 37 total. QA `test-645-prompt-trials.sh` 16/16 PASS. **Fully wired:** `scripts/prompt-trial-assign.py` invoked by Query Knowledge → emits `PROMPT_TRIAL_INSTRUCTIONS:` line → parsed + merged in Build Prompt (lines 393-417). **5 active trials** running since 2026-04-20 (investigation_quality, evidence_based, actionability, safety_compliance, completeness). Runbook: `docs/runbooks/prompt-patch-trials.md`. Details: `memory/preference_iterating_prompt_patcher.md`.
- **Agentic-platform sweep (2026-04-24):** Post-sanity-audit batch closed 10/13 items. Commits `ee65ec7` (chaos dedup + TRIAGE_JSON + CHAOS_STATE_PATH), `b9c0661` (chaos hygiene + clarity + MTBF + hint renderer + SEARCH_BUDGET_S), `65b1e23` (RAG cohort split), `f4f2cd4` (ABORT race fix — `ChaosCollisionError` carries marker data via exception attrs, not re-read from except block; observed live 20:05:02 + 20:15:23 UTC as `scenario=unknown`/`experiment_id=n/a` posts). Infra MR `nl/production!270` `12cd22b6` applied via Atlantis — live PrometheusRule `rag-alert-rules` now scopes RAGLatencyP95High to `category="real"` queries only (novel-cohort 15-22s latency is inherent-expected, tracked in Grafana via `{category="novel"}` but no longer alerts). New metrics surface: `chaos_mtbf_seconds`/`chaos_last_failure_ago_seconds`/`chaos_success_streak`/`chaos_failure_count`/`chaos_availability_ratio` per chaos_type × rolling window (cron `*/5`). YT closed: `-695`, `-707`, `-703`. Reusable lesson in `memory/feedback_capture_state_on_exception_raise.md`: when a `with lock:` block raises, the lock releases before `except` runs — always capture state on the exception at raise time, never re-read from `except`. Three items remain deferred **as operator decisions, not code gaps**: real-data teacher calibration (needs ≥20 graded answers), OpenClaw v4.22 upgrade path selection, chaos-drill cadence policy. Full summary: `memory/agentic_batch_20260424.md`.
- **parsePoll hardening (IFRNLLEI01PRD-736, 2026-04-25):** Operator reported `the poll has bugs` in `#infra-nl-prod`. Three deep-sweep rounds across the Runner `Prepare Result` and Bridge `Prepare Bridge Response` Code nodes closed **8 distinct parser bugs** in 5 commits (`9f680fc` → `eec74a9` → `fdb0971` → `c4eae6c`): (1) early-`[POLL]` hijack — quoted prompt instructions stole the question, fixed by anchoring to start-of-line + taking last match; (2) trailing prose absorbed (`Awaiting approval`/`My recommendation`/`Then file...` swept as fake clickable options in 17/70 historical polls), fixed by per-line STOP_RE; (3) latent fallback returned wrong field name; (4) closing ```` ``` ```` swept as phantom option; (5) same buggy parser duplicated in Bridge — caught by repo-wide grep, same fix applied with bridge's `org.matrix.msc3381.text.body` field; (6) v2 broke MESHSAT-664 Markdown loose-list spacing on first blank line (regression in own fix), fixed by skipping blank lines silently and only breaking on STOP_RE or 3+ consecutive blanks; (7) MESHSAT-623 nested `- Plan A` with indented sub-bullets produced 10 options instead of 2, fixed by tracking first option's indent as top level and skipping deeper-indented lines; (8) Markdown `---` / `===` horizontal rule absorbed, added to STOP_RE. **Verification corpus:** 250 paginated historical executions scanned, 34 with bug indicators all replay clean through live v5 (34/34 PASS); 21/21 adversarial inputs (Unicode, very long, embedded `[POLL]` keyword, multi-poll, code fences, tab indentation, HR `===`/`---`, CRLF, emoji); 25/25 real on-disk JSONL inputs through full Prepare Result; 70 historical polls round-tripped (53 PASS + 17 GOOD-FAIL correctly refused to reproduce buggy shapes + 0 BAD-FAIL); 8/8 bridge poll-response round-trip; 6/6 non-poll paths regression; 12/12 + 10/10 QA test-635/-727; CI `test-workflow-nodes.sh::test_poll_detection_*` rewritten to drive the *real* parsePoll out of each workflow JSON via `node`, with `PASS:9` fixtures including nested-bullet + HR + spaced-markdown regression cases. Live state: Runner `qadF2WcaBsIR7SWG` versionId `1b9d71df` / Bridge `QGKnHGkw4casiWIU` versionId `21a9b2c3`, both `active=True`, live ↔ repo ↔ HEAD all SHA-matched. Connection graph clean across all 5 commits. **Reusable lessons** saved in `memory/feedback_anchor_llm_output_markers.md` (anchor literal markers in LLM output to start-of-line, take last match — quoted instructions otherwise hijack the parse), `memory/feedback_explicit_stop_conditions_when_sweeping_llm_lists.md` (define explicit stops or trailing prose gets absorbed), `memory/feedback_grep_for_parser_duplication.md` (after fixing a parser bug, grep ALL workflows for the buggy pattern — workflow Code nodes copy-paste parsers), `memory/feedback_use_real_execution_data_for_regression.md` (use n8n executions API + `?includeData=true` to pull real production inputs; synthetic fixtures miss the formatting variants Claude actually emits — caught bugs 6, 7, 8). Full incident: `memory/parsepoll_fix_20260425.md`.
- **Agentic-platform sweep (2026-04-25):** Diagnosed + fixed a regression introduced by the 04-24 batch's `b9c0661`. `chaos-test.py:cmd_start` was already taking a `fcntl.flock(LOCK_EX|LOCK_NB)` on `chaos-active.json.lock` and `b9c0661` added an inner `with marker_lock():` (chaos_marker.py) that re-flocks the SAME file on a separate fd — Linux flock per-fd semantics produced EAGAIN against the same process, so EVERY `chaos-test.py start` ABORTed with `scenario=unknown, experiment_id=n/a` (lock-contention path with no marker file present, attrs default to empty). Counter trajectory in `/tmp/chaos-intensive.log`: stuck at `122/107` from 2026-04-23 12:29 UTC through 2026-04-25 12:25 UTC = 6 intensive sessions / 18 baseline experiments lost + every on-demand drill via the website also broken. Surfaced in `#infra-nl-prod` as three identical ABORT posts at 12:05/12:15/12:25 UTC matching the 3 experiments per intensive run. Fixed in `8075721` (remove outer flock; inner `marker_lock()` is unified with `chaos-port-shutdown.py` via `chaos_marker.py:install_marker`, so cross-drill protection preserved exactly) + `b0647df` (refresh stale `cmd_start fcntl lock` references in docstring + `save_state` comment). Validated: QA `test-709-chaos-marker-lock` 5/5 PASS, scratch-isolated 7-step e2e covers marker_lock + check + write + own-drill identity + cross-drill raise + exception-attrs-populated + cross-process contention. node_exporter on `nl-openclaw01` was also `Exited(143)` since 2026-04-22T13:56:37Z (deliberate `docker stop`, OOMKilled=false; not in compose; restart-policy `unless-stopped` would have held had it been auto-stopped) — restored via `docker start node_exporter`, sustained `Up`, `:9100` listening, Prometheus `up=1`, TargetDown auto-resolved 14:07:25 UTC. YT closed: `-728`, `-731`, `-732`. New: `-733` filed for `gemma3:12b` Modelfile `num_gpu 49` pinning to prevent silent CPU fallback when VRAM contested. Reusable lesson in `memory/feedback_no_double_flock_same_path.md`: don't add a second flock on the same file path inside a function the outer caller already flocked — different fds in the same process self-conflict via EAGAIN. Full summary: `memory/agentic_batch_20260425.md`.
