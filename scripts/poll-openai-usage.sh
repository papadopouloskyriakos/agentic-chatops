#!/bin/bash
# poll-openai-usage.sh — Collect OpenAI API usage for OpenClaw (Tier 1)
# Runs as cron every hour on nl-claude01 as app-user
#
# Strategy:
#   1. Try OpenAI Organization Usage API (needs api.usage.read scope)
#   2. Fallback: parse OpenClaw docker logs for completion usage fields
#
# Model pricing (per 1M tokens):
#   gpt-5.1:      input $1.25,  output $10.00, cache_read $0.125
#   gpt-4o:       input $2.50,  output $10.00, cache_read $1.25
#   gpt-4o-mini:  input $0.15,  output $0.60,  cache_read $0.075

set -euo pipefail

DB=/app/cubeos/claude-context/gateway.db
WATERMARK_FILE=/app/cubeos/claude-context/.openai-usage-watermark
ENV_FILE=/app/claude-gateway/.env
CONFIG=/app/claude-gateway/openclaw/openclaw.json
OPENCLAW_HOST=nl-openclaw01
OPENCLAW_CONTAINER=openclaw-openclaw-gateway-1

[ -f "$DB" ] || exit 0

# Ensure llm_usage table exists
sqlite3 "$DB" "CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tier INTEGER NOT NULL,
  model TEXT NOT NULL,
  issue_id TEXT DEFAULT '',
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cache_write_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);" 2>/dev/null

# Admin key required for Organization Usage API (regular keys lack api.usage.read scope)
OPENAI_ADMIN_KEY=$(grep OPENAI_ADMIN_KEY "$ENV_FILE" 2>/dev/null | cut -d= -f2)

# Regular API key as fallback identifier
OPENAI_KEY=$(python3 -c "
import json
d = json.load(open('$CONFIG'))
print(d['models']['providers']['openai']['apiKey'])
" 2>/dev/null || echo "")

if [ -z "$OPENAI_ADMIN_KEY" ] && [ -z "$OPENAI_KEY" ]; then
  echo "ERROR: No OpenAI keys found"
  exit 1
fi

# ============================================================================
# Method 1: OpenAI Organization Usage API (preferred, needs api.usage.read)
# ============================================================================
try_org_usage_api() {
  if [ -z "$OPENAI_ADMIN_KEY" ]; then
    return 1  # No admin key, skip to fallback
  fi

  local LAST_TS
  if [ -f "$WATERMARK_FILE" ]; then
    LAST_TS=$(cat "$WATERMARK_FILE")
  else
    # Start from 24 hours ago
    LAST_TS=$(date -d '24 hours ago' +%s)
  fi

  local NOW_TS
  NOW_TS=$(date +%s)

  local RESPONSE
  RESPONSE=$(curl -s -w "\n%{http_code}" --max-time 30 -H "Authorization: Bearer $OPENAI_ADMIN_KEY" \
    "https://api.openai.com/v1/organization/usage/completions?start_time=${LAST_TS}&end_time=${NOW_TS}&bucket_width=1h&group_by[]=model" 2>/dev/null)

  local HTTP_CODE
  HTTP_CODE=$(echo "$RESPONSE" | tail -1)
  local BODY
  BODY=$(echo "$RESPONSE" | sed '$d')

  if [ "$HTTP_CODE" != "200" ]; then
    return 1  # API not available, fall through to Method 2
  fi

  # Parse JSON response and insert into llm_usage
  python3 -c "
import json, sys, sqlite3

data = json.loads('''$BODY''')
buckets = data.get('data', [])
if not buckets:
    sys.exit(0)

db = sqlite3.connect('$DB')
c = db.cursor()

# Pricing per 1M tokens
PRICING = {
    'gpt-5.1':     {'input': 1.25,  'output': 10.00, 'cache_read': 0.125},
    'gpt-4o':      {'input': 2.50,  'output': 10.00, 'cache_read': 1.25},
    'gpt-4o-mini': {'input': 0.15,  'output': 0.60,  'cache_read': 0.075},
}
DEFAULT_PRICING = {'input': 2.50, 'output': 10.00, 'cache_read': 1.25}

inserted = 0
for bucket in buckets:
    results = bucket.get('results', [])
    for r in results:
        model = r.get('model', 'unknown')
        in_tok = r.get('input_tokens', 0)
        out_tok = r.get('output_tokens', 0)
        cache_read = r.get('input_cached_tokens', 0)

        prices = PRICING.get(model, DEFAULT_PRICING)
        cost = (in_tok * prices['input'] + out_tok * prices['output'] +
                cache_read * prices['cache_read']) / 1_000_000

        c.execute('''INSERT INTO llm_usage
            (tier, model, input_tokens, output_tokens, cache_read_tokens, cost_usd)
            VALUES (1, ?, ?, ?, ?, ?)''',
            (model, in_tok, out_tok, cache_read, round(cost, 6)))
        inserted += 1

db.commit()
db.close()
print(f'Inserted {inserted} usage records via Organization API')
" 2>/dev/null

  # Update watermark
  echo "$NOW_TS" > "$WATERMARK_FILE"
  return 0
}

# ============================================================================
# Method 2: Parse OpenClaw docker logs for usage data
# ============================================================================
parse_docker_logs() {
  local LAST_TS
  if [ -f "$WATERMARK_FILE" ]; then
    LAST_TS=$(cat "$WATERMARK_FILE")
  else
    LAST_TS=$(date -d '1 hour ago' -Iseconds 2>/dev/null || date -d '1 hour ago' +%FT%TZ)
  fi

  local NOW_TS
  NOW_TS=$(date +%s)

  # Fetch docker logs since last watermark from openclaw host
  local LOGS
  LOGS=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$OPENCLAW_HOST" \
    "docker logs --since='1h' $OPENCLAW_CONTAINER 2>&1" 2>/dev/null || echo "")

  if [ -z "$LOGS" ]; then
    echo "WARN: No docker logs available from $OPENCLAW_HOST"
    echo "$NOW_TS" > "$WATERMARK_FILE"
    return 0
  fi

  # Parse usage from logs using Python
  echo "$LOGS" | python3 -c "
import sys, re, sqlite3, json
from datetime import datetime

# Pricing per 1M tokens
PRICING = {
    'gpt-5.1':     {'input': 1.25,  'output': 10.00, 'cache_read': 0.125},
    'gpt-4o':      {'input': 2.50,  'output': 10.00, 'cache_read': 1.25},
    'gpt-4o-mini': {'input': 0.15,  'output': 0.60,  'cache_read': 0.075},
}
DEFAULT_PRICING = {'input': 2.50, 'output': 10.00, 'cache_read': 1.25}

db = sqlite3.connect('$DB')
c = db.cursor()
inserted = 0

# Look for OpenAI API response patterns in logs
# OpenClaw logs completion responses which include usage fields
for line in sys.stdin:
    line = line.strip()
    # Try to extract JSON objects containing usage data
    # Pattern: {...\"usage\":{\"prompt_tokens\":N,\"completion_tokens\":N,...},...\"model\":\"gpt-5.1\"...}
    for match in re.finditer(r'\{[^{}]*\"usage\"\s*:\s*\{[^}]+\}[^{}]*\"model\"\s*:\s*\"[^\"]+\"[^{}]*\}', line):
        try:
            data = json.loads(match.group())
            usage = data.get('usage', {})
            model = data.get('model', 'unknown')

            in_tok = usage.get('prompt_tokens', 0)
            out_tok = usage.get('completion_tokens', 0)
            cache_read = usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)

            if in_tok == 0 and out_tok == 0:
                continue

            prices = PRICING.get(model, DEFAULT_PRICING)
            cost = (in_tok * prices['input'] + out_tok * prices['output'] +
                    cache_read * prices['cache_read']) / 1_000_000

            c.execute('''INSERT INTO llm_usage
                (tier, model, input_tokens, output_tokens, cache_read_tokens, cost_usd)
                VALUES (1, ?, ?, ?, ?, ?)''',
                (model, in_tok, out_tok, cache_read, round(cost, 6)))
            inserted += 1
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

db.commit()
db.close()
print(f'Inserted {inserted} usage records from docker logs')
" 2>/dev/null

  echo "$NOW_TS" > "$WATERMARK_FILE"
}

# ============================================================================
# Main: try API first, fall back to docker log parsing
# ============================================================================
if try_org_usage_api 2>/dev/null; then
  exit 0
fi

echo "INFO: Organization Usage API unavailable (needs api.usage.read scope), falling back to docker log parsing"
parse_docker_logs
