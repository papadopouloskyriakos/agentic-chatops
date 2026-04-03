#!/bin/bash
# score-trajectory.sh — Parse JSONL session transcript and score agent trajectory
#
# Evaluates whether the agent followed the expected step sequence for the
# alert category. Infra sessions have stricter requirements than dev.
#
# Usage:
#   score-trajectory.sh <issue_id>                    # Score specific session
#   score-trajectory.sh --recent                      # Score all unscored sessions
#
# Reads from /tmp/claude-run-<ISSUE>.jsonl
# Writes to session_trajectory table

set -uo pipefail

DB="${GATEWAY_DB:-/app/cubeos/claude-context/gateway.db}"
LOG_TAG="[trajectory]"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $LOG_TAG $*"; }

score_session() {
  local ISSUE_ID="$1"
  local JSONL="/tmp/claude-run-${ISSUE_ID}.jsonl"

  if [ ! -f "$JSONL" ]; then
    log "SKIP: $ISSUE_ID — no JSONL file"
    return 0
  fi

  # Already scored?
  local ALREADY=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_trajectory WHERE issue_id='$ISSUE_ID'" 2>/dev/null)
  [ "${ALREADY:-0}" -gt 0 ] && return 0

  # Determine if infra or dev
  local PREFIX=$(echo "$ISSUE_ID" | cut -d- -f1)
  local IS_INFRA=0
  [[ "$PREFIX" == "IFRNLLEI01PRD" || "$PREFIX" == "IFRGRSKG01PRD" ]] && IS_INFRA=1

  # Parse JSONL for trajectory markers
  local FULL_TEXT=$(python3 -c "
import json, sys
texts = []
tool_calls = 0
turns = 0
with open('$JSONL') as f:
    for line in f:
        try:
            d = json.loads(line.strip())
            if d.get('type') == 'assistant':
                turns += 1
                for block in d.get('message', {}).get('content', []):
                    if block.get('type') == 'text':
                        texts.append(block['text'])
                    if block.get('type') == 'tool_use':
                        tool_calls += 1
        except: pass
print(f'TURNS:{turns}')
print(f'TOOLS:{tool_calls}')
print('TEXT_START')
print('\n'.join(texts[-5:]))  # Last 5 text blocks (most relevant)
print('TEXT_END')
" 2>/dev/null)

  local TURNS=$(echo "$FULL_TEXT" | grep '^TURNS:' | cut -d: -f2)
  local TOOLS=$(echo "$FULL_TEXT" | grep '^TOOLS:' | cut -d: -f2)
  local RESPONSE=$(echo "$FULL_TEXT" | sed -n '/^TEXT_START$/,/^TEXT_END$/p' | grep -v 'TEXT_')

  # Score each trajectory step
  local HAS_NETBOX=0 HAS_KB=0 HAS_REACT=0 HAS_POLL=0 HAS_CONF=0 HAS_EVIDENCE=0 HAS_SSH=0 HAS_YT=0

  # Check tool calls in full JSONL
  grep -q 'netbox\|NetBox' "$JSONL" 2>/dev/null && HAS_NETBOX=1
  grep -q 'kb-semantic-search\|incident_knowledge\|knowledge' "$JSONL" 2>/dev/null && HAS_KB=1
  echo "$RESPONSE" | grep -qiE 'THOUGHT:|OBSERVATION:|SYNTHESIS:' && HAS_REACT=1
  echo "$RESPONSE" | grep -qiE '\[POLL\]|awaiting approval|Which approach' && HAS_POLL=1
  echo "$RESPONSE" | grep -qiE 'CONFIDENCE:\s*[0-9]' && HAS_CONF=1
  grep -qiE 'ssh |kubectl |curl |show run|show version' "$JSONL" 2>/dev/null && HAS_EVIDENCE=1
  grep -q 'ssh' "$JSONL" 2>/dev/null && HAS_SSH=1
  grep -qiE 'youtrack|yt-post-comment|post.*comment' "$JSONL" 2>/dev/null && HAS_YT=1

  # Calculate score based on type
  local STEPS_COMPLETED=$((HAS_NETBOX + HAS_KB + HAS_REACT + HAS_POLL + HAS_CONF + HAS_EVIDENCE + HAS_SSH + HAS_YT))
  local STEPS_EXPECTED=8
  local NOTES=""

  if [ "$IS_INFRA" -eq 0 ]; then
    # Dev sessions: only need confidence + evidence + some tool usage
    STEPS_EXPECTED=4
    STEPS_COMPLETED=$((HAS_CONF + HAS_EVIDENCE + (TOOLS > 3 ? 1 : 0) + (TURNS > 2 ? 1 : 0)))
    NOTES="dev session"
  fi

  local SCORE=0
  [ "$STEPS_EXPECTED" -gt 0 ] && SCORE=$((STEPS_COMPLETED * 100 / STEPS_EXPECTED))
  [ "$SCORE" -gt 100 ] && SCORE=100

  # Insert
  sqlite3 "$DB" "INSERT INTO session_trajectory (
    issue_id, has_netbox_lookup, has_incident_kb_query, has_react_structure,
    has_poll_or_approval, has_confidence, has_evidence_commands, has_ssh_investigation,
    has_yt_comment, steps_completed, steps_expected, trajectory_score,
    tool_calls, turns, notes
  ) VALUES (
    '$ISSUE_ID', $HAS_NETBOX, $HAS_KB, $HAS_REACT,
    $HAS_POLL, $HAS_CONF, $HAS_EVIDENCE, $HAS_SSH,
    $HAS_YT, $STEPS_COMPLETED, $STEPS_EXPECTED, $SCORE,
    ${TOOLS:-0}, ${TURNS:-0}, '$NOTES'
  );" 2>/dev/null

  log "  $ISSUE_ID: score=$SCORE ($STEPS_COMPLETED/$STEPS_EXPECTED) turns=$TURNS tools=$TOOLS"
}

# Main
if [ "${1:-}" = "--recent" ]; then
  log "Scoring recent unscored sessions..."
  for jsonl in /tmp/claude-run-*.jsonl; do
    [ -f "$jsonl" ] || continue
    ISSUE=$(basename "$jsonl" | sed 's/claude-run-//' | sed 's/.jsonl//')
    score_session "$ISSUE"
  done
elif [ -n "${1:-}" ]; then
  score_session "$1"
else
  echo "Usage: score-trajectory.sh <issue_id> | --recent"
fi

log "Done"
