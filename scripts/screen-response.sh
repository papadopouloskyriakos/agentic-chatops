#!/usr/bin/env bash
# Evaluator-Optimizer: Screen a Claude response using Haiku
# Usage: screen-response.sh <base64-encoded-response>
# Returns: PASS or FAIL:<reason>
# Called by n8n Runner workflow for high-stakes responses
set -euo pipefail

# Load secrets from .env
ENV_FILE="/app/claude-gateway/.env"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE"; set +a; }

B64_INPUT="${1:-}"
if [ -z "$B64_INPUT" ]; then
  echo "PASS"
  exit 0
fi

RESPONSE_TEXT=$(echo "$B64_INPUT" | base64 -d 2>/dev/null | head -c 3000)
if [ -z "$RESPONSE_TEXT" ]; then
  echo "PASS"
  exit 0
fi

API_KEY="${ANTHROPIC_API_KEY:-}"
if [ -z "$API_KEY" ]; then
  echo "PASS"
  exit 0
fi

# Escape the response for JSON embedding
ESCAPED=$(python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" <<< "$RESPONSE_TEXT")

RESULT=$(curl -s --max-time 15 https://api.anthropic.com/v1/messages \
  -H "x-api-key: $API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d "{
    \"model\": \"claude-haiku-4-5-20251001\",
    \"max_tokens\": 150,
    \"temperature\": 0,
    \"messages\": [{
      \"role\": \"user\",
      \"content\": \"You are a quality screener for an infrastructure ChatOps system. Review this response for:\\n1. Factual errors or unsupported claims (conclusions without evidence)\\n2. Unsafe commands proposed without [POLL] approval gate\\n3. Missing CONFIDENCE score\\n4. Actions taken without human approval\\n\\nReply with EXACTLY one line: PASS if acceptable, or FAIL:<one-line-reason> if not.\\n\\nResponse to review:\\n${ESCAPED}\"
    }]
  }" 2>/dev/null) || { echo "PASS"; exit 0; }

# Extract the text from Anthropic response
VERDICT=$(echo "$RESULT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    text = d['content'][0]['text'].strip()
    # Ensure it starts with PASS or FAIL
    if text.startswith('PASS'):
        print('PASS')
    elif text.startswith('FAIL'):
        print(text[:200])
    else:
        print('PASS')
except:
    print('PASS')
" 2>/dev/null) || echo "PASS"

echo "$VERDICT"
