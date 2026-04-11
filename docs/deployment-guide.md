# Deployment Guide

How to deploy agentic-chatops on fresh infrastructure — from zero to working alert triage.

---

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Alert Sources   │     │   Chat (Matrix)  │     │  Issue Tracker   │
│  LibreNMS        │     │   Synapse + bot  │     │  YouTrack        │
│  Prometheus      │────▶│   accounts       │◀───▶│  webhook trigger │
│  CrowdSec        │     │                  │     │  state sink      │
│  Scanners        │     └────────┬─────────┘     └────────┬─────────┘
└─────────────────┘              │                         │
                                 │                         │
                      ┌──────────▼─────────────────────────▼──────────┐
                      │              n8n (orchestrator)                │
                      │  17 workflows, ~403 nodes                     │
                      │  Receives alerts → dedup → triage → post      │
                      └──────────┬──────────────────┬─────────────────┘
                                 │                  │
                      ┌──────────▼────────┐  ┌─────▼──────────────┐
                      │  OpenClaw (Tier 1) │  │  Claude Code (T2)  │
                      │  GPT-5.1           │  │  Opus 4.6          │
                      │  Fast triage 7-21s │  │  Deep analysis     │
                      │  15 skills         │  │  10 sub-agents     │
                      └───────────────────┘  └────────────────────┘
```

**Data flow:** Alert → n8n webhook → dedup/flap detection → OpenClaw triage (creates YT issue, investigates via SSH, posts findings) → if confidence < 0.7, escalates to Claude Code → Claude investigates, proposes fix via [POLL] → human clicks approval in Matrix → Claude executes → session archived to knowledge base.

---

## Minimum Viable Deployment

You don't need everything. Start with the core loop and add components incrementally.

### Level 1: Core (alert → triage → chat)

| Component | Required | Purpose |
|-----------|----------|---------|
| n8n | Yes | Workflow orchestration |
| Matrix (Synapse) | Yes | Human-in-the-loop chat interface |
| YouTrack | Yes | Issue tracking, webhook trigger |
| Claude Code | Yes | AI agent (Tier 2) |
| SQLite | Yes | Session and knowledge storage |

### Level 2: Smart Triage (adds Tier 1 + RAG)

| Component | Required | Purpose |
|-----------|----------|---------|
| OpenClaw | Recommended | Fast Tier 1 triage (GPT-5.1) |
| Ollama | Recommended | Local embeddings for semantic search |
| NetBox | Recommended | CMDB for device identity |

### Level 3: Full Platform (adds security + observability)

| Component | Required | Purpose |
|-----------|----------|---------|
| Prometheus + Grafana | Optional | Metrics dashboards |
| LibreNMS | Optional | Network monitoring alerts |
| CrowdSec | Optional | Security alerts |
| Security scanners | Optional | Vulnerability scanning |
| AWX | Optional | Maintenance automation |

---

## Step-by-Step Setup

### Step 0: Prerequisites

```bash
# Required on the deployment host
node --version    # v18+ (for n8n)
python3 --version # 3.11+ (for semantic search scripts)
sqlite3 --version # 3.x
claude --version  # Claude Code CLI installed

# Clone the repo
git clone https://github.com/papadopouloskyriakos/agentic-chatops.git
cd agentic-chatops

# Create environment config
cp .env.example .env
# Edit .env with your values — see comments in file for guidance
```

### Step 1: n8n

Install n8n (self-hosted, Docker or npm):

```bash
# Docker (recommended)
docker run -d --name n8n \
  -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  -e N8N_API_ENABLED=true \
  n8nio/n8n:latest

# Or npm
npm install -g n8n
n8n start
```

**Configure:**
1. Open n8n UI at `http://localhost:5678`
2. Go to Settings → API → Create API Key
3. Set `N8N_API_KEY` in your `.env`

**Create credentials in n8n:**
- SSH Private Key credential (for connecting to the Claude Code host)
- HTTP Header Auth credential (for Matrix bot token)
- HTTP Header Auth credential (for YouTrack API token)

Note the credential IDs — you'll need them when importing workflows.

**Verify:** `curl -s -H "X-N8N-API-KEY: $N8N_API_KEY" https://your-n8n/api/v1/workflows | python3 -c "import json,sys; print(json.load(sys.stdin))"`

### Step 2: Matrix (Synapse)

You need a Matrix homeserver with two bot accounts.

```bash
# Register bot users (on the Synapse server)
register_new_matrix_user -c /etc/synapse/homeserver.yaml \
  -u claude -p <password> --no-admin
register_new_matrix_user -c /etc/synapse/homeserver.yaml \
  -u openclaw -p <password> --no-admin
```

**Create access tokens:**
```bash
curl -s -X POST https://matrix.example.com/_matrix/client/r0/login \
  -d '{"type":"m.login.password","user":"claude","password":"<password>"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])"
```

**Create rooms and invite bots:**
- `#chatops` — commands, fallback
- `#alerts` — system alerts
- `#infra-site1` — infrastructure alerts (one per site)
- `#project1`, `#project2` — dev project rooms (optional)

Set room IDs in `.env`. Set bot tokens in `.env` and n8n credentials.

**Verify:** Bot appears online in rooms.

### Step 3: YouTrack

Create a project for infrastructure alerts (e.g., `INFRA`).

**Configure custom fields:**
- State (default workflow)
- Severity (enum: critical, warning, info)
- Alert Source (enum: LibreNMS, Prometheus, CrowdSec, Scanner)
- Hostname (text)
- Alert Rule (text)

**Create webhook:** Project Settings → Workflows → Webhooks → POST to `https://your-n8n/webhook/youtrack-webhook`

**Create API token:** Hub → Users → your-bot → Authentication → New permanent token

Set `YT_URL` and `YT_TOKEN` in `.env`.

**Verify:** `curl -s -H "Authorization: Bearer $YT_TOKEN" "$YT_URL/api/admin/projects?fields=shortName" | python3 -c "import json,sys; [print(p['shortName']) for p in json.load(sys.stdin)]"`

### Step 4: Claude Code Host

The host where Claude Code sessions run. n8n SSHes into this host.

```bash
# On the Claude Code host
# Install Claude Code
curl -fsSL https://claude.ai/install | sh

# Set up API key
export ANTHROPIC_API_KEY=sk-ant-...

# Create workspace
mkdir -p ~/claude-context
```

**Initialize SQLite:**
```bash
sqlite3 ~/claude-context/gateway.db < schema.sql
```

**Deploy scripts:**
```bash
# Copy scripts to the Claude Code host
scp -r scripts/ app-user@host:~/gateway/scripts/
scp -r .claude/ app-user@host:~/gateway/.claude/
chmod +x ~/gateway/scripts/*.sh
```

**Deploy Claude Code config:**
```bash
# Copy sub-agent definitions and hooks
cp -r .claude/agents/ ~/.claude/agents/
cp -r .claude/skills/ ~/.claude/skills/
cp .claude/settings.json ~/.claude/settings.json  # PreToolUse hooks
```

**Verify:** `ssh app-user@host "claude --version && sqlite3 ~/claude-context/gateway.db '.tables'"`

### Step 5: Import n8n Workflows

**Before importing:** Workflow JSON files contain credential IDs specific to the original installation. You must update them.

```bash
# Find and replace credential IDs in workflow JSON files
# Original SSH credential ID: REDACTED_SSH_CRED → your SSH credential ID
# Original Matrix credential ID: REDACTED_MATRIX_CRED → your Matrix credential ID
# Original YT credential ID: REDACTED_YT_CRED → your YT credential ID

# Update all workflow files
for wf in workflows/*.json; do
  sed -i "s/REDACTED_SSH_CRED/YOUR_SSH_CRED_ID/g" "$wf"
  sed -i "s/REDACTED_MATRIX_CRED/YOUR_MATRIX_CRED_ID/g" "$wf"
  sed -i "s/REDACTED_YT_CRED/YOUR_YT_CRED_ID/g" "$wf"
done

# Import workflows via n8n API
for wf in workflows/*.json; do
  curl -s -X POST "https://your-n8n/api/v1/workflows" \
    -H "X-N8N-API-KEY: $N8N_API_KEY" \
    -H "Content-Type: application/json" \
    -d @"$wf"
  echo " → imported $(basename $wf)"
done
```

**Update environment-specific values:**
- Matrix room IDs in Bridge workflow
- YouTrack project IDs in receiver workflows
- SSH hostnames in all SSH nodes
- Webhook URLs

**Activate workflows:** n8n UI → each workflow → toggle Active.

**Verify:** n8n shows all workflows active, webhook endpoints responding.

### Step 6: OpenClaw (Optional — Level 2)

```bash
# On the OpenClaw host
git clone https://github.com/openclaw/openclaw.git /srv/openclaw
cd /srv/openclaw

# Deploy config
cp /path/to/repo/openclaw/openclaw.json /root/.openclaw/openclaw.json
cp /path/to/repo/openclaw/SOUL.md /root/.openclaw/workspace/SOUL.md
cp -r /path/to/repo/openclaw/skills/* /root/.openclaw/workspace/skills/

# Start
docker compose up -d
```

**Verify:** OpenClaw bot responds to `@openclaw /status` in Matrix.

### Step 7: Cron Jobs

```bash
# On the Claude Code host, add to crontab:
crontab -e

# Paste the cron entries from docs/installation.md
# Adjust paths to match your installation
```

### Step 8: Alert Sources

Connect your monitoring tools to the n8n webhook endpoints:

| Source | Webhook URL | Notes |
|--------|-------------|-------|
| LibreNMS | `https://n8n/webhook/librenms-alert` | HTTP transport in LibreNMS |
| Prometheus | `https://n8n/webhook/prometheus-alert` | Alertmanager webhook receiver |
| CrowdSec | `https://n8n/webhook/crowdsec-alert` | HTTP notification plugin |
| Synology DSM | `https://n8n/webhook/synology-alert` | Custom notification provider |

---

## Verification Checklist

After deployment, verify each component:

```bash
# 1. n8n healthy
curl -s https://your-n8n/healthz

# 2. Matrix bot online
# Check bot appears in room member list

# 3. YouTrack webhook fires
# Create a test issue manually — n8n should log an execution

# 4. Claude Code accessible via SSH
ssh app-user@host "claude -p 'say hello' --output-format json"

# 5. SQLite initialized
ssh app-user@host "sqlite3 ~/claude-context/gateway.db '.tables'"

# 6. Golden tests pass
ssh app-user@host "cd ~/gateway && bash scripts/golden-test-suite.sh --offline --set regression"

# 7. End-to-end test
# Trigger a real alert (or simulate one) and watch it flow through:
# Alert → n8n webhook → Matrix notification → OpenClaw triage → YT issue
```

---

## Environment-Specific Values

The following values are hardcoded in scripts and workflows and must be updated for your environment:

| Category | What to Change | Where |
|----------|---------------|-------|
| Hostnames | `nl*`, `gr*` → your hosts | scripts/*.sh, openclaw/skills/*.sh |
| IPs | `192.168.181.*`, `192.168.2.*` → your subnets | scripts/*.sh, CLAUDE.md |
| URLs | `*.example.net` → your domains | workflows/*.json, CLAUDE.md, .claude/rules/ |
| Matrix room IDs | `!xxxxx:matrix.example.net` → your IDs | workflows/*.json, .claude/rules/references.md |
| n8n credential IDs | `REDACTED_SSH_CRED` etc. → your IDs | workflows/*.json |
| YT project IDs | `IFRNLLEI01PRD`, `IFRGRSKG01PRD` → your projects | scripts/*.sh, workflows/*.json |
| SSH keys | `~/.ssh/one_key` → your key path | scripts/*.sh |
| API tokens | Hardcoded tokens → use .env | CLAUDE.md, scripts/*.sh |

**Tip:** Use `grep -rn "examplecorp" .` to find all environment-specific references. The GitHub mirror has 128 sanitization patterns that replace these values — reviewing those patterns shows exactly what needs changing.

---

## Scaling

### Adding a second site

1. Clone the LibreNMS + Prometheus receiver workflows
2. Update webhook paths (`/librenms-alert-site2`, `/prometheus-alert-site2`)
3. Create a new YT project for the site
4. Create a new Matrix room for the site
5. Add site config to `openclaw/skills/site-config.sh`
6. Update `config/tool-profiles.json` if different tool needs

### Adding alert sources

1. Create a new n8n webhook workflow (use existing receivers as template)
2. Map alert fields to the standard format (hostname, rule, severity, state)
3. Wire to the existing triage pipeline (OpenClaw instruction or direct Runner call)

### Adding sub-agents

1. Create `.claude/agents/your-agent.md` with YAML frontmatter
2. Define: name, description, tools (read-only for researchers)
3. Reference in Build Prompt's sub-agent delegation section
4. Add to the eval golden tests

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| n8n webhook returns 404 | Workflow not active | Activate in n8n UI |
| Matrix bot doesn't respond | Token expired or bot not in room | Re-generate token, re-invite |
| Claude session hangs | SSH timeout or PID not found | Check SSH connectivity, increase timeout |
| Empty Claude response | JSONL file not written | Check disk space, verify `nohup` redirect |
| Triage not triggered | Receiver workflow error | Check n8n execution log for errors |
| Semantic search returns nothing | Ollama down or no embeddings | Run `kb-semantic-search.py embed --backfill` |
| Credential redaction too aggressive | Regex matching normal text | Check CREDENTIAL_PATTERNS in Prepare Result |
