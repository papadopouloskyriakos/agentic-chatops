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

Per-model token/cost tracking across 3 tiers (`llm_usage` table — single source of truth), exposed via Prometheus (`write-model-metrics.sh`, cron `*/5`). 3 portfolio stats APIs serve live data to Hugo: `/webhook/agentic-stats` (IDs: `ncUp08mWsdrtBwMA`), `/webhook/lab-stats` (`B90NqTknqhInVLYP`), `/webhook/mesh-stats` (`PrcigdZNWvTj9YaL`). **6 writers** feed `llm_usage`: (1) Runner `Write Session File` (Tier 2, per-session JSONL extraction, has issue_id), (2) `poll-openclaw-usage.sh` (Tier 1, hourly, SSH+docker exec to read container's `~/.claude/projects/**/*.jsonl` with byte-offset watermark — added 2026-04-28 IFRNLLEI01PRD-746, replaces poll-openai-usage.sh after Tier 1 OAuth migration; rows `issue_id='openclaw-cli'`), (3) `poll-claude-usage.sh` (Tier 2, `*/30`, reads JSONL session files from `~/.claude/projects/**/*.jsonl` with byte-offset watermark — rewritten 2026-04-10, was stats-cache.json which stopped updating after Claude Code 2.1.x; rows marked `issue_id='cli-session'`), (4) `llm-judge.sh` (Tier 2, per-judgment), (5) `_record_local_usage()` in 4 scripts (Tier 0, per-Ollama-call: kb-semantic-search.py, archive-session-transcript.py, ragas-eval.py, agent-diary.py), (6) `poll-openai-usage.sh` (Tier 1, retired 2026-04-28 — cron commented out, script kept for historical replay). `agentic-stats.py` reads only from `llm_usage` — no estimation or fabrication. Token formula: full count (input+output+cache_read+cache_write) for rows with `issue_id != ''`; `input+output` only for old Claude poller rows with empty issue_id (inflated cache values). Tier 2 cost = $0 for Max subscription (interactive CLI), API-equivalent ~$16,420 total. **Portfolio widget** (`agentic-stats.html`): client-side JS with data inlined at Hugo build time via `site.Data` (n8n API is internal-only). CI schedule `*/5` on website repo refreshes data. See [`docs/llm-usage-tracking.md`](docs/llm-usage-tracking.md) for full details.

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
- **HAHA + FISHA reliability hardening (2026-04-30)** — closed IFRNLLEI01PRD-704, -801, -802, -803, -804, -805, -815 in one session after the 2026-04-27→04-30 ~66h HAHA outage. Memory entries: [`incident_haha_nfs_stale_fh_20260430.md`](memory/incident_haha_nfs_stale_fh_20260430.md), [`haha_reliability_hardening_20260430.md`](memory/haha_reliability_hardening_20260430.md), [`haha_chaos_engineering_20260430.md`](memory/haha_chaos_engineering_20260430.md). Components live: (a) `monitor_cmd` on all 5 OCF docker resources (HA `/manifest.json`, ESPHome `/`, Z2M wget, Node-RED `/`, Mosquitto `nc -z 1883`); (b) start/stop timeouts raised from 90s to 120-180s on the 4 sidecar resources to avoid fence-on-restart (caught by chaos C9); (c) `nfs-stale-fh-exporter.py` (HTTP/1.1 ThreadingHTTPServer, port 9101) on file01/02 + `exportfs-flush-webhook.py` (port 9107, bearer-token, IP-allowlist 10.0.X.X/27 + 10.0.181.X/24) on file01/02; (d) Pacemaker alert `alert_post_nfs_flush` on FISHA + `clear_arp_nfs.sh` on iot01/02 wired to call the exportfs-flush webhook on `p_fs_iot start` failures with stale-fh signature; (e) `alertmanager-twilio-bridge.py` user-systemd service on nl-claude01:9106 + Alertmanager `twilio-tier1` route matching `tier=1, severity=critical`; (f) Gatus `custom` Twilio provider with API-Key auth (`/srv/atlantis/twilio.env` env_file mounted into Atlantis runner), tier-1 endpoints for HA + NL K8s API + FISHA file01 + FISHA file02; (g) 7 PrometheusRules — `NFSStaleFhPoisoning`, `NFSStaleFhExporterDown`, `NFSStaleFhExporterStalePackets`, `PVEMemoryPressureHigh/Critical`, `PVELoadHigh`, `PVEZramSwapNearFull`; (h) ARP refresh cron on iot01/02 every 5 min (`ping -c 1 -W 2 -I enp6s19 10.0.X.X`); (i) `fence_pve` Python TypeError patched with `dpkg-divert --rename` on iot01/02/iotarb01 + file01/02/filearb01 (survives `apt upgrade fence-agents-pve`); (j) IFRNLLEI01PRD-704 balloon floors set on 6 VMs on nl-pve01 (75% on HA-critical iot01+file01, 50% on others) + balloon device attached on nlk8s-ctrl01 — immediate 5 GiB host memory recovered, ~14 GiB total reclaimable headroom. **14-test chaos catalog run end-to-end**; 12 of 14 confidence rows now >0.90 detection AND recovery. Two rows at acknowledged structural ceilings (in-container freeze rec 0.85 = OCF docker agent limit; FISHA migration rec 0.85 = recorder DB on NFS by operator decision).

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
| `cc-cc` | n8n/Claude Code | Claude Code (direct SSH dispatch) | **DEFAULT — active 2026-04-29** |
| `oc-cc` | OpenClaw | Claude Code via n8n | Dormant (LXC stopped, onboot=0) |
| `oc-oc` | OpenClaw | OpenClaw/Sonnet 4.6 (self-contained, OAuth Max) | Dormant |
| `cc-oc` | n8n session mgmt | OpenClaw as backend (via docker exec) | Dormant |

Switch modes with the `!mode <mode>` command in any Matrix room where OpenClaw is present. (Restoring `oc-cc`/`oc-oc`/`cc-oc` requires `pct start VMID_REDACTED` on `nl-pve03` + uncommenting the 2 disabled `*-openclaw-*` crons.)

**cc-cc migration (2026-04-29, commit 484f5da):** Anthropic April-4 OAuth-for-third-party ban + OpenClaw 2026.4.26 MCP-bind regression made the `oc-cc` triage path unreliable (alerts silent for 5+ hours on 2026-04-29). Migrated to `cc-cc`: 9 alert receivers SSH directly to claude01 and invoke `scripts/run-triage.sh <kind> <args...>` instead of posting `@openclaw use exec to run...` to Matrix. 6 yt-* helpers + escalate-to-claude.sh that lived only in the OpenClaw container's `/root/.openclaw/workspace/skills/` were pulled into the repo. All triage scripts patched for host portability via `${TRIAGE_X:-default}` env-var fallbacks (work on claude01 today, openclaw container tomorrow). LXC `VMID_REDACTED` stopped + `onboot=0` on `nl-pve03`; 2 openclaw crons disabled with rollback comments. **E2E proven on 8 paths** (prom NL+GR, librenms NL+GR, security NL+GR, synology, receiver-canary smoke). Durable structural check is **`holistic-agentic-health.sh §38 cc-cc-receiver-wiring`** — asserts all 9 receivers reference the wrapper (catches silent re-wiring drift). The receiver-canary cron + 2 Prometheus alerts that ran during cutover were **retired 2026-04-30** (real alert volume ≈ hourly already exercises the chain; canary was producing 48 synthetic YT issues/day with no added signal). Full memory: `memory/cc_cc_migration_complete_20260429.md` + `docs/openclaw-retirement-complete-2026-04-29.md`. Reusable lessons: `memory/feedback_canary_for_dispatch_chain_changes.md` (cutover-only, retire after steady state) + `memory/feedback_canary_must_clean_its_own_artifacts.md` + `memory/feedback_grep_hardcoded_paths_after_host_migration.md`.

**Tier 1 model migration (2026-04-28, IFRNLLEI01PRD-746):** OpenClaw Tier 1 was switched from `openai/gpt-5.1` (OpenAI API, paid service-account key) to `claude-cli/claude-sonnet-4-6` (Max-subscription OAuth, $0). OpenClaw 2026.4.11 ships native `--auth-choice claude-cli` support; configured via `openclaw configure --section model` inside the container, no shim. `claude` binary at `/usr/local/bin/claude` (v2.1.121, npm-installed in `~/.npm-global` symlinked from `/usr/local/bin`). Independent OAuth token on openclaw01 (separate from claude01's). Fallback ladder: Opus 4.6 → Opus 4.5 → Sonnet 4.5 → Haiku 4.5 — all via OAuth, no paid keys retained. Cost tracking flows from container's `~/.claude/projects/**/*.jsonl` via `scripts/poll-openclaw-usage.sh` (mirror of poll-claude-usage.sh, SSHes + docker execs into the container). **Note (2026-04-29):** `poll-openclaw-usage.sh` cron disabled by the cc-cc migration; reactivate alongside the LXC if rolling back to `oc-cc`.

**GitHub mirror sync chain hardening (2026-05-01, IFRNLLEI01PRD-835):** Three independent failure modes had `sync_to_github` red on every push since 2026-04-30 (~65h public-mirror lag). All three reproduced + fixed in one session. (1) `.gitignore` rule `docs/*-audit-*.md` matched the NVIDIA cross-audit doc → squash-flow re-ignored it → unsanitized contents survived on disk → verification grep aborted. Fix: `git clean -fdx -q` between `git add -A` and `git commit` in `github-sync/sync-to-github.sh` (`5e7ff45`). (2) Transient `fatal: couldn't find remote ref refs/pipelines/<id>` from Gitaly. Fix: `GIT_STRATEGY: empty` + manual `git clone` in before_script for `sync_to_github`+`sync_to_github_dry_run` (`63be431`); verified in gitlab-runner v18.6.1 source `shells/abstract.go:740-744`. (3) Concurrent github push race on `refs/heads/main` server-side CAS surfaced once both above were in. Fix: `resource_group: github_mirror_push_v2` for serialization (`54ea10d`); deliberately NO `interruptible: true` because the combination deadlocks (canceling state holds the lock). Companion: `workflow.auto_cancel.on_new_commit: interruptible` at top of `.gitlab-ci.yml` (no-op currently, lets future jobs opt in cleanly). Validation: 4-rapid-push stress test post-fix → 4/4 success serialized via resource_group, no GitHub race, no deadlock; final sanity push `25569` → success, mirror caught up to `6dcef81d`. Stuck `canceling` pipelines (lock orphans) recoverable via admin `DELETE /api/v4/projects/<id>/pipelines/<stuck-id>` with `is_admin=True` token. Reusable lessons: `memory/feedback_classify_pipeline_failures_by_step.md` + `memory/feedback_resource_group_interruptible_deadlock.md` + `memory/feedback_admin_api_first_then_say_cant.md` + `memory/feedback_git_strategy_empty_bypass.md`. Full memory: `memory/github_sync_chain_hardening_20260501.md`. Sibling YT: IFRNLLEI01PRD-836 (portfolio page Opus 4.7 + cc-cc + Sonnet 4.6 widget label fix).

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
- **[P0] Full hostnames, no exceptions:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, nlcl01iot01 not iot01, nlcl01file02 not file02, gr-pve01 not pve01). Never use generic role labels ("the ASA", "the router", "the active node") as a substitute. Applies to all output: playbooks, comments, memory, YT, Matrix messages, tables, diagram labels, filenames. Reinforced 2026-04-30 after multiple session slips.
- **[P0] VLAN naming — never use the subnet third octet as a VLAN tag:** `10.0.181.X/24` is **inside_mgmt VLAN 10**, not "VLAN 181". `10.0.X.X/27` is the storage subnet, not "VLAN 88". `10.0.X.X/28` is **VLAN 12 (CCTV)**, not "VLAN 183". The third IP octet is not the 802.1Q tag. Refer to subnets by name (inside_mgmt), tag (VLAN 10), or CIDR (10.0.181.X/24) — never by octet-as-tag.
- **Code-node edits require validator (post-14h-outage gate):** Before any `curl -X PUT /api/v1/workflows/<id>` that modifies a Code node's `jsCode`, run `scripts/validate-n8n-code-nodes.sh --file <patched-workflow.json>` (or `<workflow-id>` to fetch live). Must return **VALIDATION PASSED** — checks `node --check`, `new Function()` parse, exactly 1 top-level `return` (dead code is a `[FAIL]`), and flags duplicate top-level `var` declarations. The Build Prompt node was cleaned 2026-04-19 (90 KB → 36 KB, 3 returns → 1); the validator prevents the 14h-outage-class regression. Full runbook: `docs/runbooks/n8n-code-node-safety.md`.
- **Risk-based auto-approval (IFRNLLEI01PRD-632, 2026-04-19):** Runner has `Classify Risk` SSH node between Build Plan and Build Prompt. Classifier (`scripts/classify-session-risk.py`) emits `{risk_level, auto_approve_recommended, signals, plan_hash}`; Build Prompt injects `## SESSION RISK:` section instructing Claude to end with `[AUTO-RESOLVE]` (low-risk) or `[POLL]` (mixed/high). Matrix Bridge parses `[AUTO-RESOLVE]` and posts as `m.notice` (no ping). Every classification writes to `session_risk_audit` table; `scripts/audit-risk-decisions.sh` + holistic-health enforce the invariant "no `auto_approved=1` row with `risk_level != 'low'`." Integration replay in `scripts/test-risk-integration.sh` (10/10 deterministic cases). HIGH-risk categories: `maintenance`, `security-incident`, `deployment`. Fail-closed: `RISK_FAIL_CLOSED=1` forces `high` on parse errors.
- **RAG circuit breakers (IFRNLLEI01PRD-631, 2026-04-19):** 4 named breakers guard the RAG external-call path — `rag_rerank_crossencoder`, `rag_embed_ollama`, `rag_synth_haiku`, `rag_synth_ollama`. SQLite-backed state (`circuit_breakers` table); Prometheus metrics via `scripts/write-circuit-breaker-metrics.sh` cron `*/5`. `CircuitBreakerOpen` alert fires if any stays OPEN ≥10 min. Inspect: `cd scripts && python3 -m lib.circuit_breaker list`. Reset: `python3 -m lib.circuit_breaker reset <name>`. Lib at `scripts/lib/circuit_breaker.py` — imperative `allow()/record_success()/record_failure()` API or decorator.
- **Schema versioning (IFRNLLEI01PRD-635, 2026-04-20):** All session/audit tables (now 19, was 9 at landing) carry `schema_version INTEGER DEFAULT 1` stamped by every writer. Canonical registry: `scripts/lib/schema_version.py` (`CURRENT_SCHEMA_VERSION` dict + `SCHEMA_VERSION_SUMMARIES`, mirroring OpenAI Agents SDK `run_state.py:131`). Python writers `from schema_version import current as schema_current`; bash writers hardcode `1` with registry pointer. Readers call `check_row(table, row.schema_version)` which raises `SchemaVersionError` on future versions. Migration `scripts/migrations/006_schema_versioning.sql` (idempotent via apply.py). Holistic-health §33 asserts no null `schema_version`. **Operational rule: when you change the JSON shape of any payload column in these tables, bump `CURRENT_SCHEMA_VERSION[table]` AND add a new line to `SCHEMA_VERSION_SUMMARIES[table]` describing the change.** Full reference: `memory/openai_sdk_adoption_batch.md`.
- **OpenAI SDK adoption batch (IFRNLLEI01PRD-635..643, 2026-04-20):** 9 structural upgrades from `openai/openai-agents-python` v0.14.2: schema versioning on 9 tables (-635), immutable per-turn snapshots (-636), 13 typed events in `event_log` (-637), per-turn lifecycle hooks (-638), 3-behavior rejection taxonomy allow/reject_content/deny (-639), `HandoffInputData` zlib+b64 envelope 0.43% ratio (-640), gemma3:12b transcript compaction (-641), `agent_as_tool.py` for ambiguous-risk band 0.4-0.6 (-642), `handoff_depth` + cycle detection ≥5 forces `[POLL]` / ≥10 hard-halts (-643). 4 new tables → 35. **Not adopted:** OutputGuardrail (deferred), per-tool `needs_approval`, auto-trace to OpenAI, strict Pydantic sub-agent output, always-on `nest_handoff_history`. Full reference: `memory/openai_sdk_adoption_batch.md` + `README.extensive.md` §22.
- **QA suite (2026-04-20, expanded 2026-04-23):** `scripts/qa/run-qa-suite.sh` — pytest-style bash harness, **44 suite files** (was 30+), **~3-5 min runtime** under full-suite load, JSON scorecard in `scripts/qa/reports/`. **Per-suite timeout guard** (IFRNLLEI01PRD-724, default `QA_PER_SUITE_TIMEOUT=120s`, override via env) prevents any single slow/hung suite from wedging the orchestrator; synthetic FAIL record emitted to scorecard on timeout. Covers: writer coverage (schema_version=1 across 11 writers + 5 n8n INSERT sites), 85 rejection patterns (53 deny + 32 reject_content), 13 event-class payload shapes, 8-parallel concurrent fuzz, local HTTP mock for offline compaction, 6 e2e scenarios, 16 prompt-patcher tests, 7 benchmarks, plus 9 umbrella-added tests (test-656/-660/-718/-724/-726/-727). **Last hardened run (2026-04-23): 411/0/2 = 99.52%**, up from 368/4/2. **Run after any change to the adoption-batch surfaces or the patcher.**
- **Teacher-agent reliability pass (2026-04-23):** 5 post-ship bugs closed after operator DM audit: Command Router double-wiring (`501ff47`); `cmd_grade` UPDATE wrong PK left `completed_at=NULL` (`3d9c0da`); Mastery/SM-2/Bloom advanced on low grader_confidence — `low_conf` branch now holds schedule steady (`3d9c0da`); teacher-runner webhook `responseMode: responseNode→onReceived` + removed terminal Respond node (`33d64c8`+`99dc9fc`); `cmd_chat` SQLite-lock crash — fixed with `timeout=30` + `PRAGMA busy_timeout=30000` + post-to-Matrix-before-audit-UPDATE + try/except around DB block (`feb2bae`). Also `cec2c0c`: `docs/gulli-book-overview.md` + 30 chapter extracts (embeddings 1189→1309). Reusable: `memory/feedback_sqlite_busy_timeout.md` + `.claude/rules/workflows.md`. Full detail: `memory/teacher_agent_dm_audit_20260423.md`.
- **Teacher-agent — all 5 tiers (IFRNLLEI01PRD-651, IFRNLLEI01PRD-652, IFRNLLEI01PRD-653, IFRNLLEI01PRD-654, IFRNLLEI01PRD-655, 2026-04-20):** Five-tier introspective learning module teaching the operator agentic-systems theory using the system's own docs. **-651 foundation** (migration 013 `learning_progress` + `learning_sessions`; `scripts/lib/sm2.py` SuperMemo-2 EF clamped `[1.3, 2.5]`; `config/curriculum.json` + `scripts/rebuild-curriculum.py` 53 topics × 4 curricula auto-derived from wiki/docs/memory; **13/13 PASS**). **-652 intelligence** (`scripts/lib/bloom.py` 7-level progression `recall→teaching_back`; `scripts/lib/quiz_generator.py` + `quiz_grader.py` Ollama gemma3:12b `format=json` with hallucination gate — `verbatim_text` substring of sources — and Invariant #4 confidence-clarifier <0.6; breaker-aware via `rag_synth_ollama`; **17/17 PASS**). **-653 interface** (migration 014 `teacher_operator_dm` `public_sharing DEFAULT 0` privacy-first; `scripts/lib/matrix_teacher.py`; `scripts/teacher-agent.py` orchestrator with 12 subcommands; `.claude/agents/teacher-agent.md` read-only tool allowlist Read/Grep/Glob/Bash/ToolSearch — Edit/Write/MultiEdit excluded; `workflows/claude-gateway-teacher-runner.json` `/teacher-command` webhook; multi-user classroom `#learning` design; **14/14 PASS**). **-654 loop** (3 crons `30 8 * * *` morning-nudge / `0 16 * * 0` class-digest / `*/5` metrics-exporter; 10 `learning_*` metrics; 3 alerts in `prometheus/alert-rules/teacher-agent.yml` — `TeacherAgentMetricsAbsent`/`TeacherAgentMorningNudgeStale`/`TeacherAgentClassDigestStale`; 12-panel `grafana/teacher-agent.json` dashboard; **9/9 PASS**). **-655 gate** (`scripts/audit-teacher-invariants.sh` enforces 6 invariants + privacy default; `scripts/teacher-calibration-baseline.py` 12-fixture / 5-band harness with `--offline` deterministic stub; `docs/runbooks/teacher-agent.md` ops runbook with `!learn is silent` debug ladder + 5-stage rollback; **9/9 PASS**). **Combined: 62/62 QA tests.** Real-data calibration (≥20 graded answers) deferred to natural accumulation. Plan: `docs/plans/teacher-agent-implementation-plan.md`. Full memory: `memory/teacher_agent_foundation.md` (named "all 5 tiers done").
- **CLI-session RAG capture (IFRNLLEI01PRD-646/-647/-648, 2026-04-20, ALL WIRED 2026-04-24):** Interactive `claude` CLI sessions flow into RAG tables (closes ~2,300 JSONL gap). Tier 1 `backfill-cli-transcripts.sh` (archive + parse-tool-calls + extract-cli-knowledge, tagged `issue_id='cli-<uuid>'`, watermark file). Tier 2 gemma3:12b over summary rows → structured incident_knowledge (`project='chatops-cli'`, breaker-aware). Tier 3 `parse-tool-calls.py::extract_issue_id_from_path` resolves JSONL → `cli-<uuid>`. `kb-semantic-search.py` `CLI_INCIDENT_WEIGHT=0.75` discounts cli rows at retrieval. QA `test-646-cli-session-rag-capture.sh` 12/12 PASS. **Cron installed** (`30 4 * * *`) + firing nightly — 04-24 run processed 50 files / 255 transcript chunks / 2831 tool-call rows / 25 knowledge extractions. Details: `memory/cli_session_rag_capture.md`.
- **Preference-iterating prompt patcher (IFRNLLEI01PRD-645, 2026-04-20, ALL WIRED):** Policy iteration at the prompt level. Low-scoring (surface, dimension) → `scripts/prompt-patch-trial.py --start` generates 3 candidate variants (concise/detailed/examples) + control. Build Prompt deterministically buckets via `hash(issue_id|trial_id) % (N+1)` (lines 393-417). `scripts/finalize-prompt-trials.py` (cron `17 3 * * *`) runs one-sided Welch t-test at ≥15 samples per arm; promotes if lift ≥0.05 & p<0.1, else aborts (or 14d timeout). Library: `scripts/lib/prompt_patch_trial.py` (race-safe SQLite). Enable: `PROMPT_TRIAL_ENABLED=1`. Prometheus via `scripts/write-trial-metrics.sh` (`*/10`). 2 new tables → 37 total. QA `test-645-prompt-trials.sh` 16/16 PASS. **5 active trials** since 2026-04-20 (investigation_quality, evidence_based, actionability, safety_compliance, completeness). Runbook: `docs/runbooks/prompt-patch-trials.md`. Details: `memory/preference_iterating_prompt_patcher.md`.
- **Agentic-platform sweep (2026-04-24):** 13-item triage; 10 closed in 4 commits — `ee65ec7` (chaos dedup + TRIAGE_JSON booleans + CHAOS_STATE_PATH), `b9c0661` (cmd_recover lock + 3-line end format + ETA + collision ABORT + MTBF cron + teacher hint renderer + SEARCH_BUDGET_S), `65b1e23` (RAG cohort split — `RAGLatencyP95High` now scoped to `category="real"`), `f4f2cd4` (`ChaosCollisionError` carries marker data on the exception, not re-read from except block — observed live 20:05/20:15 UTC as `scenario=unknown` posts). Infra MR `nl/production!270` `12cd22b6` via Atlantis. New metrics: `chaos_mtbf_seconds`/`chaos_last_failure_ago_seconds`/`chaos_success_streak`/`chaos_failure_count`/`chaos_availability_ratio` per chaos_type × rolling window (cron `*/5`). YT closed: `-695`, `-707`, `-703`. Three items deferred **as operator decisions, not code gaps**: real-data teacher calibration (needs ≥20 graded answers), OpenClaw v4.22 upgrade path selection, chaos-drill cadence policy. Reusable lesson: `memory/feedback_capture_state_on_exception_raise.md` (on `with lock:` raise the lock releases before `except` runs — capture state at raise time, never re-read in `except`). Full summary: `memory/agentic_batch_20260424.md`.
- **parsePoll hardening (IFRNLLEI01PRD-736, 2026-04-25):** Operator reported "the poll has bugs" in `#infra-nl-prod`. Three deep-sweep rounds across Runner `Prepare Result` and Bridge `Prepare Bridge Response` Code nodes closed **8 distinct parser bugs** in 5 commits (`9f680fc` → `eec74a9` → `fdb0971` → `c4eae6c`): early-`[POLL]` hijack via unanchored regex, trailing-prose absorption (17/70 historical polls), latent-fallback wrong field name, code-fence delimiter as phantom option, parser duplicated in Bridge (caught via repo-wide grep), single-blank-line break too aggressive (broke MESHSAT-664 loose-list), nested sub-bullets absorbed (MESHSAT-623), Markdown horizontal rule absorbed. **Verification corpus:** 250 historical executions / 34 PASS · 21 adversarial / 21 PASS · 25 real JSONL / 25 PASS · 70 round-trip / 53 PASS + 17 GOOD-FAIL · 8/8 bridge · 12/12+10/10 QA test-635/-727. Live state: Runner `qadF2WcaBsIR7SWG` versionId `1b9d71df`, Bridge `QGKnHGkw4casiWIU` versionId `21a9b2c3`, both `active=True`, live ↔ repo ↔ HEAD SHA-matched. Reusable lessons: `memory/feedback_anchor_llm_output_markers.md`, `memory/feedback_explicit_stop_conditions_when_sweeping_llm_lists.md`, `memory/feedback_grep_for_parser_duplication.md`, `memory/feedback_use_real_execution_data_for_regression.md`. Full incident: `memory/parsepoll_fix_20260425.md`.
- **Agentic-platform sweep (2026-04-25):** Diagnosed + fixed regression introduced by 04-24 `b9c0661`: `chaos-test.py:cmd_start` outer `fcntl.flock` + `b9c0661`'s inner `marker_lock()` re-flocked the same file on a separate fd → Linux per-fd EAGAIN against the same process → every `chaos-test.py start` ABORTed since 2026-04-23 evening (counter stuck at 122/107 = 6 lost intensives / 18 baseline experiments). Fixed in `8075721` (remove outer flock; inner `marker_lock()` preserves cross-drill protection via `chaos_marker.py:install_marker`) + `b0647df` (refresh stale references in docstring + `save_state` comment). Validated: `test-709-chaos-marker-lock` 5/5 PASS + scratch-isolated 7-step e2e (marker_lock + check + write + own-drill identity + cross-drill raise + exception-attrs + cross-process contention). Side-fix: `node_exporter` on `nl-openclaw01` `Exited(143)` since 2026-04-22 (deliberate `docker stop`) — restored. YT closed: `-728`, `-731`, `-732`. New: `-733` filed for `gemma3:12b` `num_gpu 49` Modelfile pinning. Reusable lesson: `memory/feedback_no_double_flock_same_path.md`. Full summary: `memory/agentic_batch_20260425.md`.
- **NVIDIA DLI cross-audit + P0+P1 implementation (IFRNLLEI01PRD-747..-751, 2026-04-29):** 19-transcript NVIDIA DLI Agentic-AI cross-audit graded the system **A (4.4/5.0)** on the 12-dim rubric — lowest of the 9 sources audited so far. Same-day implementation of all 7 P0+P1 items in 4 commits lifted to **A+ (4.83)**; 9-source aggregate **A+ (4.79)**. Commits: G1 `8aabf27` (long-horizon replay + 39-fixture jailbreak corpus incl. **8 Greek**), G2 `cac272a` (intermediate semantic rail DARK-FIRST + grammar-constrained decoding), G3 `4af78cf` (team-formation skill + ITS budget), G4 `2e3fb9f` (server-side session-replay endpoint `lJEGboDYLmx25kBo`). Operator gates closed cert-pass-2 `cac226a`: 5 cron entries, `Check Intermediate Rail` Code node in Runner (now 50 nodes), session-replay ACTIVE, Greek fixtures, YT 747-751 → Done via direct REST workaround. Schema: `event_log` v=1→4 (+4 event_types: `team_charter`, `its_budget_consumed`, `intermediate_rail_check`, `session_replay_invoked`); +1 versioned table `long_horizon_replay_results` (migration 015); 18→19 versioned, 26→27 workflows, 6→7 skills, 44→51 QA suite files (+57 tests, 411→468 PASS = 99.57%). Reusable lessons: `memory/feedback_youtrack_mcp_state_bug.md`, `memory/feedback_n8n_sandbox_no_child_process.md`, `memory/feedback_dataclass_importlib_quirk.md`. Single source-of-record: `docs/agentic-platform-state-2026-04-29.md`. Full memory: `memory/nvidia_dli_cross_audit_20260429.md`.
