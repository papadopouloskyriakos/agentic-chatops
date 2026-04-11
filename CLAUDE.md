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

Per-model token/cost tracking across 3 tiers (`llm_usage` table — single source of truth), exposed via Prometheus (`write-model-metrics.sh`, cron `*/5`). 3 portfolio stats APIs serve live data to Hugo: `/webhook/agentic-stats` (IDs: `ncUp08mWsdrtBwMA`), `/webhook/lab-stats` (`B90NqTknqhInVLYP`), `/webhook/mesh-stats` (`PrcigdZNWvTj9YaL`). **4 writers** feed `llm_usage`: (1) Runner `Write Session File` (Tier 2, per-session JSONL extraction), (2) `poll-openai-usage.sh` (Tier 1, hourly, OpenAI Admin API), (3) `poll-claude-usage.sh` (Tier 2, `*/30`, reads `~/.claude/stats-cache.json` deltas including today's partial data — delta-aware with per-day and per-model today watermark to avoid double-counting), (4) `llm-judge.sh` (Tier 2, per-judgment). `agentic-stats.py` reads only from `llm_usage` — no estimation or fabrication. Tier 2 cost = $0 for Max subscription (interactive CLI), API-equivalent cost for n8n-triggered sessions. See [`docs/llm-usage-tracking.md`](docs/llm-usage-tracking.md) for full details.

---

## MemPalace Integration (2026-04-09)

8 patterns ported from [mempalace](https://github.com/milla-jovovich/mempalace). New tables: `session_transcripts` (verbatim chunks + embeddings), `agent_diary` (persistent per-agent memory). Temporal KG via `incident_knowledge.valid_until`. Hooks: Stop (auto-save every 15 msgs) + PreCompact (emergency save). RAG upgraded to **4-signal RRF** (`semantic + keyword + wiki + 0.3*transcript`). See [`docs/mempalace-details.md`](docs/mempalace-details.md) for full details.

---

## Compiled Knowledge Base (Karpathy-Style Wiki)

[Karpathy-style](https://x.com/karpathy/status/2039805659525644595) wiki at `wiki/` — 45 articles compiled from 7+ sources (memories, CLAUDE.md files, incidents, OpenClaw, docs, 03_Lab, Grafana). Compiler: `scripts/wiki-compile.py` (SHA-256 incremental, daily 04:30 UTC cron + `/wiki-compile` skill). All articles embedded into `wiki_articles` table as 3rd RRF signal. Health: `wiki-compile.py --health`. See [`docs/compiled-wiki-details.md`](docs/compiled-wiki-details.md) for source mapping and CLI usage.

---

## Maintenance Mode

When `/home/app-user/gateway.maintenance` exists (JSON with `started`, `reason`, `eta_minutes`, `operator`), alert processing is suppressed across all receivers, watchdog, and OpenClaw triage. Created/removed by AWX playbook or manually. 15-minute post-maintenance cooldown tags alerts as `post-maintenance-recovery`.

**ASA weekly reboot: DISABLED (2026-04-10).** EEM watchdog applets removed from both ASAs after the weekly reboot caused VTI tunnel instability and cascading cross-site outages. `asa-reboot-watch.sh` cron commented out. Manual reloads use the maintenance companion (`/maintenance`). **Freedom ISP:** dual WAN with SLA failover + QoS toggle (with ping fallback) + SMS alerts via Twilio. **PVE kernel:** AWX cross-site automation (GR from NL template 69, NL from GR template 21). **Inter-site routing:** Full BGP via direct ASA-to-ASA peering over VTI (Freedom LP 200, xs4all LP 150, FRR transit LP 100). No static inter-site routes (2026-04-10). See [`docs/maintenance-mode-details.md`](docs/maintenance-mode-details.md) for full details.

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
