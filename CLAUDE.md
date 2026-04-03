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

## Maintenance Mode

When `/home/app-user/gateway.maintenance` exists (JSON file with `started`, `reason`, `eta_minutes`, `operator`), alert processing is suppressed:

- **LibreNMS + Prometheus receivers (NL+GR)**: maintenance check piggybacked on existing SSH load — zero extra latency, returns `maintenanceSuppressed: true`
- **WAL Self-Healer (GR)**: skips healing during maintenance
- **Gateway watchdog**: skips all checks (no restarts, no bounces)
- **OpenClaw infra-triage**: exits immediately with confidence 0.1 during maintenance, 50% reduction during 15min post-maintenance cooldown

The file is created/removed by the AWX `chatops/maintenance_mode.yaml` playbook, or automatically by `scripts/asa-reboot-watch.sh` for scheduled ASA reboots. After removal, a 15-minute cooldown period tags alerts as `post-maintenance-recovery`.

### ASA Weekly Reboot Suppression

Both Cisco ASA firewalls have EEM watchdog timers that auto-reload them:
- **nl-fw01 (NL):** `event timer watchdog time 604800` (7 days from last boot)
- **gr-fw01 (GR):** `event timer watchdog time 590400` (~6d 20h from last boot)

Reboot causes total site network outage (~5-10 min) + cross-site VPN drop. A 4-layer suppression system prevents false alerts:

| Layer | Component | How |
|-------|-----------|-----|
| 1 | LibreNMS | `scripts/asa-reboot-watch.sh` (cron `*/5`) checks ASA uptime, sets maintenance on all devices when reboot < 10min away |
| 2 | gateway.maintenance | Same watcher creates/removes the file automatically with `event_id` field |
| 3 | scheduled-events.json | `config/scheduled-events.json` checked by `infra-triage.sh` + `correlated-triage.sh` as fallback |
| 4 | Agent knowledge | SOUL.md, Runner Build Prompt, incident_knowledge DB (3 entries with embeddings) |

**Key:** Watchdog timers count from boot completion, so reboot times drift ~5min/cycle. The predictive watcher adapts automatically — no fixed cron schedule.

### PVE Kernel Maintenance Playbooks

Full-site maintenance automation in `infrastructure/common` repo. **Run via AWX (cross-site)**:
- **GR maintenance** → launch from **NL AWX** template 69 (~60 min)
- **NL maintenance** → launch from **GR AWX** template 21 (~135 min)

Custom AWX EE (`awx-ee-maintenance`) with kubectl, curl, dig, redis-cli, cilium, showmount. SSH key + kubeconfig mounted via K8s secret `awx-ssh-one-key`. Image pre-loaded on all 7 K8s workers (`pull: never`). Dockerfile: `infrastructure/common/ansible/ee/Dockerfile`.

Required extra_vars: `operator`, `dry_run`, `api_token` (LibreNMS), `matrix_api_token`. Optional: `skip_email`, `skip_synology`.

---

## Operating Modes

The file `/home/app-user/gateway.mode` controls which frontend/backend pair is active.

| Mode | Frontend | Backend | Status |
|------|----------|---------|--------|
| `oc-cc` | OpenClaw | Claude Code via n8n | DEFAULT — active |
| `oc-oc` | OpenClaw | OpenClaw/GPT-4o (self-contained) | Available |
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
- n8n version: **2.46.1** (community edition)
- n8n-mcp version: 2.46.1
- **Switch V3.2 known issue (n8n 2.41.3):** Rules created via API/MCP omit `conditions.options` block, causing `extractValue` crash. ALWAYS include `conditions.options: {version: 2, caseSensitive: true, typeValidation: "strict"}` in each rule's conditions when creating Switch V3.2 nodes programmatically. Compare with LibreNMS receiver "Repeat Action" node for reference. After any workflow update via API, toggle deactivate→activate to reload webhook listeners.
- **Full hostnames:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, gr-pve01 not pve01). Multi-site environment makes short forms ambiguous. Applies to all output: playbooks, comments, memory, YT, Matrix messages.
