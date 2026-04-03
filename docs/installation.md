# Installation Guide

## Prerequisites

- **n8n** (v2.40+) — workflow automation engine
- **Matrix** (Synapse) — chat server with bot account
- **YouTrack** — issue tracking with webhook support
- **Claude Code** — Anthropic CLI (`~/.local/bin/claude`)
- **OpenClaw** — GPT-4o agent (Docker-based)
- **SQLite3** — session and knowledge storage
- **Python 3.11+** — semantic search and metrics scripts
- **Ollama** (optional) — local embedding model for RAG

## Setup Steps

### 1. Clone and configure

```bash
git clone https://github.com/papadopouloskyriakos/agentic-chatops.git
cd agentic-chatops
cp .env.example .env  # Edit with your credentials
```

### 2. Import n8n workflows

```bash
for wf in workflows/*.json; do
  npx n8n-mcp import "$wf"
done
```

### 3. Configure Matrix bot

- Create a bot user on your Matrix server
- Set Bearer token in n8n credentials
- Join bot to your chat rooms

### 4. Configure OpenClaw

- Deploy `openclaw/openclaw.json` to your OpenClaw instance
- Deploy `openclaw/SOUL.md` as system prompt
- Deploy skills to `/workspace/skills/`

### 5. Initialize SQLite

Tables are auto-created by n8n workflows on first run. Or manually:

```bash
sqlite3 gateway.db < schema.sql
```

### 6. Set up cron jobs

```bash
# Infrastructure + session + agent metrics (every 1-5 min)
* * * * * /path/to/scripts/write-infra-metrics.sh
*/5 * * * * /path/to/scripts/write-session-metrics.sh
*/5 * * * * /path/to/scripts/write-agent-metrics.sh

# Watchdog (every 5 min)
*/5 * * * * /path/to/scripts/gateway-watchdog.sh

# SQLite backup (daily 02:00 UTC)
0 2 * * * /path/to/scripts/backup-gateway-db.sh

# Prompt scorecard grading (daily 03:00 UTC)
0 3 * * * /path/to/scripts/grade-prompts.sh

# Regression detection + metamorphic monitor (every 6h)
0 */6 * * * /path/to/scripts/regression-detector.sh
30 */6 * * * /path/to/scripts/metamorphic-monitor.sh

# Embedding backfill (every 30 min)
*/30 * * * * python3 /path/to/scripts/kb-semantic-search.py embed --backfill

# CrowdSec learning (every 6h)
0 */6 * * * /path/to/scripts/crowdsec-learn.sh

# Weekly lessons digest (Monday 07:00 UTC)
0 7 * * 1 /path/to/scripts/weekly-lessons-digest.sh

# Golden test suite (1st & 15th of month 04:00 UTC)
0 4 1,15 * * /path/to/scripts/golden-test-suite.sh

# Proactive scan (daily 06:03 UTC)
3 6 * * * /path/to/scripts/trigger-proactive-scan.sh
```

### 7. Configure alert sources

- **LibreNMS:** Create HTTP transport pointing to `https://your-n8n/webhook/librenms-alert`
- **Prometheus/Alertmanager:** Add webhook receiver pointing to `https://your-n8n/webhook/prometheus-alert`
- **CrowdSec:** Configure notification to `https://your-n8n/webhook/crowdsec-alert`
- **Synology DSM:** Create webhook notification to `https://your-n8n/webhook/synology-dsm-alert`
- **GitLab CI:** Add pipeline webhook to `https://your-n8n/webhook/gitlab-ci-failure`
