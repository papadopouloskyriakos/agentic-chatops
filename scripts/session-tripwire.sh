#!/usr/bin/env bash
# Concurrent session tripwire (bench IFRNLLEI01PRD-1423 OpenAI dim9, 2026-06-26).
#
# OpenAI "A Practical Guide to Building Agents": guardrails should run CONCURRENTLY with the
# agent and raise a tripwire that ABORTS on breach. The Progress Poller already watches every
# running dispatched session (tails its JSONL, reads its PID) every 30s but had ZERO kill
# authority. This script gives it that: parse cumulative input+output tokens, tool-call count,
# and reported cost, and on breach of GENEROUS bounds (far above any legitimate session — the
# first real auto-resolve was 26 turns / ~0.5M tokens / ~40 tool calls) terminate the runaway.
#
# Generous-by-design so it NEVER kills a legit session; cache-read tokens are excluded (they
# inflate harmlessly and are $0 on the Max plan). Kill-switch: `touch ~/gateway.tripwire_off`
# downgrades to observe-only (logs the breach, does not abort). Bounds are env-overridable.
#
# Usage: session-tripwire.sh <jsonl> <pid> <issue_id>
# Output (stdout): empty if OK; "ABORT(...)" or "OBSERVE(...)" line on breach.
set -uo pipefail
LOG="${1:-}"; PID="${2:-}"; ISSUE="${3:-}"
[ -z "$LOG" ] || [ ! -f "$LOG" ] && exit 0

MAX_TOKENS="${TRIPWIRE_MAX_TOKENS:-3000000}"    # 3M cumulative input+output (excl. cache)
MAX_TOOLCALLS="${TRIPWIRE_MAX_TOOLCALLS:-250}"
MAX_COST_USD="${TRIPWIRE_MAX_COST_USD:-20}"

read -r TOK TOOLS COST < <(python3 - "$LOG" <<'PY'
import json, sys
tok = tools = 0
cost = 0.0
for line in open(sys.argv[1], errors="ignore"):
    line = line.strip()
    if not line:
        continue
    try:
        e = json.loads(line)
    except Exception:
        continue
    msg = e.get("message", {}) or {}
    content = msg.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                tools += 1
    u = e.get("usage") or msg.get("usage") or {}
    tok += (u.get("input_tokens", 0) or 0) + (u.get("output_tokens", 0) or 0)
    for k in ("total_cost_usd", "cost_usd"):
        if k in e and e[k]:
            cost = max(cost, float(e[k]))
print(tok, tools, round(cost, 2))
PY
)
TOK="${TOK:-0}"; TOOLS="${TOOLS:-0}"; COST="${COST:-0}"

BREACH=""
[ "$TOK" -gt "$MAX_TOKENS" ] 2>/dev/null && BREACH="tokens=$TOK>$MAX_TOKENS"
[ "$TOOLS" -gt "$MAX_TOOLCALLS" ] 2>/dev/null && BREACH="$BREACH toolcalls=$TOOLS>$MAX_TOOLCALLS"
awk "BEGIN{exit !($COST > $MAX_COST_USD)}" 2>/dev/null && BREACH="$BREACH cost=$COST>$MAX_COST_USD"
BREACH="$(echo "$BREACH" | sed 's/^ *//')"
[ -z "$BREACH" ] && exit 0

if [ -f "$HOME/gateway.tripwire_off" ]; then
  echo "OBSERVE($BREACH) issue=$ISSUE pid=$PID — abort disabled by ~/gateway.tripwire_off"
  exit 0
fi

# Abort the runaway: TERM the session, mark the JSONL so the Runner's parser sees the abort.
[ -n "$PID" ] && kill -TERM "$PID" 2>/dev/null
printf '{"type":"tripwire_abort","breach":"%s","issue":"%s","pid":"%s"}\n' "$BREACH" "$ISSUE" "$PID" >> "$LOG"
echo "ABORT($BREACH) issue=$ISSUE killed pid=$PID"
exit 0
