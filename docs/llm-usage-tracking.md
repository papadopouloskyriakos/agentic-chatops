# LLM Usage Tracking

Per-model token and cost tracking across 3 tiers, exposed via Prometheus for Grafana and a portfolio stats JSON API. `llm_usage` is the single source of truth — all consumers (Prometheus, portfolio JSON, Grafana) read from it.

## Database

- **`llm_usage` table** — granular per-request: tier (0=local GPU, 1=OpenClaw, 2=Claude Code), model, issue_id, input/output/cache tokens, cost_usd, recorded_at
- **`model` column** on `sessions` + `session_log` — extracted from JSONL `message.model` field by Parse Response

## Data Sources (4 writers)

| Source | How | Frequency | Tier |
|--------|-----|-----------|------|
| Claude Code sessions | Runner Parse Response + Parse Fresh Response extract from JSONL → Write Session File inserts | Per session | 2 |
| Claude Code CLI | `scripts/poll-claude-usage.sh` reads `~/.claude/stats-cache.json` deltas incl. today's partial data (delta-aware: per-model today watermark + subtracts Runner tokens) | `*/30` cron | 2 |
| LLM Judge | `scripts/llm-judge.sh` inserts after each Haiku/Opus API call | Per judgment | 2 |
| OpenClaw | `scripts/poll-openai-usage.sh` polls OpenAI Organization Usage API | Hourly cron | 1 |
| Local GPU (real) | Per-call tracking in kb-semantic-search.py, archive-session-transcript.py, ragas-eval.py, agent-diary.py via `_record_local_usage()` | Per Ollama call | 0 |

## Prometheus Metrics

`scripts/write-model-metrics.sh` (cron `*/5`) → `/var/lib/node_exporter/textfile_collector/model_metrics.prom`:
- `llm_cost_total{tier,model}`, `llm_input_tokens_total`, `llm_output_tokens_total`, `llm_requests_total` (30d)
- `llm_cost_7d{model}`, `llm_cost_today{tier}`, `llm_cost_alltime{tier}`
- `llm_cache_hit_ratio` (Tier 2, 7d), `llm_avg_cost_per_request{model}`, `llm_tokens_per_day_avg{tier}`

## OpenAI Admin Key

The OpenAI Organization Usage API requires an **admin key** (`sk-admin-...`), not a regular API key. Stored in `.env` as `OPENAI_ADMIN_KEY`. Regular API keys lack the `api.usage.read` scope regardless of permission settings.

## Portfolio Stats APIs

Three webhook endpoints serve live data to the Hugo portfolio site (baked at CI build time, not client-side JS):

**Agentic Stats** — LLM usage widget on the projects page
- **Workflow:** `NL - Agentic Stats API` (ID: `ncUp08mWsdrtBwMA`) — 3 nodes
- **Endpoint:** `GET https://n8n.example.net/webhook/agentic-stats` (CORS enabled, 5min cache)
- **Script:** `scripts/agentic-stats.py` — reads exclusively from `llm_usage` for all token data + `sessions`/`session_log` for session counts only (no token estimation) + `incident_knowledge` + `a2a_task_log` + `triage.log` + NetBox API (live device count)
- **Consumer:** Hugo CI → `data/agentic_stats.json`
- **Models reported:** 8 models across 3 tiers (Claude Opus/Haiku/Sonnet/devstral Tier 2, GPT-5.1/4o Tier 1, Nomic/Qwen3 Local GPU)
- **Time series:** daily buckets (last 7 days), key `date`, gap-filled with zero-activity entries. Single source: `llm_usage` real tokens only. No estimation or fabrication.
- **Data integrity (audited 2026-04-10):** DB↔JSON cross-check passes (exact token match). 0 fabricated rows.

**Lab Stats** — "At a Glance" + device inventory on the lab page
- **Workflow:** `NL - Lab Stats API` (ID: `B90NqTknqhInVLYP`) — 3 nodes
- **Endpoint:** `GET https://n8n.example.net/webhook/lab-stats` (CORS enabled, 5min cache)
- **Script:** `scripts/lab-stats.py` — queries NetBox API (devices, VMs, IPs, VLANs, interfaces, cables, roles, per-site breakdown, manufacturers) + kubectl (K8s node count + version from both NL/GR clusters) + ZFS SSH (storage aggregation)
- **Consumer:** Hugo CI → `data/lab_stats.json`
- **Sections powered:** At a Glance (6 cards), Device Inventory by Role, Per-Site Breakdown, Platform Stack counts (sites, manufacturers, workflows)

**VPN Mesh Stats** — live VPN mesh health + BGP data for the status page
- **Workflow:** `NL - VPN Mesh Stats API` (ID: `PrcigdZNWvTj9YaL`) — 3 nodes
- **Endpoint:** `GET https://n8n.example.net/webhook/mesh-stats` (CORS enabled, 5min cache)
- **Script:** `scripts/vpn-mesh-stats.py` — SSH to both ASAs (tunnel interface status, SLA track, live ICMP ping latency) + VPS swanctl (NO↔CH tunnel) + Prometheus (FRR BGP, ClusterMesh, cipSecTun) + LibreNMS (device availability) + RIPE RIS API (public BGP visibility, AS paths, transit ASNs)
- **Consumer:** Hugo CI → `data/mesh_stats.json`
- **Data:** 9 unique VTI tunnels (6 NL ASA + 2 GR ASA + 1 VPS), live latency matrix, Freedom WAN status, failover events from SLA track, BGP peer uptimes, public BGP propagation (AS64512, `2a0c:9a40:8e20::/48`)
