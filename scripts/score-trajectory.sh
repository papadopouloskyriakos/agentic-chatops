#!/bin/bash
# score-trajectory.sh — Parse JSONL session transcript and score agent trajectory
#
# Evaluates whether the agent followed the expected step sequence for the
# alert category. Infra sessions have stricter requirements than dev.
#
# Usage:
#   score-trajectory.sh <issue_id>                    # Score specific session
#   score-trajectory.sh --recent                      # Score all unscored sessions (JSONL + b64 fallback)
#   score-trajectory.sh --backfill [limit]            # Score archived session_log entries (default limit: 50)
#
# Data sources (in priority order):
#   1. /tmp/claude-run-<ISSUE>.jsonl (live session, full structured data)
#   2. sessions.last_response_b64 (decoded plain text, text-based marker detection)
#   3. session_log metadata (turns/confidence only, minimal scoring)
# Writes to session_trajectory table

set -uo pipefail

DB="${GATEWAY_DB:-/app/cubeos/claude-context/gateway.db}"
LOG_TAG="[trajectory]"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $LOG_TAG $*"; }

score_session() {
  local ISSUE_ID="$1"
  local JSONL="/tmp/claude-run-${ISSUE_ID}.jsonl"
  local USING_B64=0
  local TMP_B64=""

  # Already scored?
  local ALREADY=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_trajectory WHERE issue_id='$ISSUE_ID'" 2>/dev/null)
  [ "${ALREADY:-0}" -gt 0 ] && return 0

  # Fallback: when JSONL is missing, try b64 response from sessions table
  if [ ! -f "$JSONL" ]; then
    local B64=$(sqlite3 "$DB" "SELECT last_response_b64 FROM sessions WHERE issue_id='$ISSUE_ID'" 2>/dev/null)
    if [ -n "$B64" ]; then
      TMP_B64="/tmp/claude-traj-${ISSUE_ID}.tmp"
      echo "$B64" | base64 -d > "$TMP_B64" 2>/dev/null
      if [ -s "$TMP_B64" ]; then
        USING_B64=1
        log "  $ISSUE_ID — using b64 response fallback (no JSONL)"
      else
        rm -f "$TMP_B64"
      fi
    fi
  fi

  # If neither JSONL nor b64 is available, try session_log metadata-only scoring
  if [ ! -f "$JSONL" ] && [ "$USING_B64" -eq 0 ]; then
    local LOG_DATA=$(sqlite3 -separator '|' "$DB" "
      SELECT COALESCE(num_turns,0), COALESCE(confidence,-1), COALESCE(alert_category,'')
      FROM session_log WHERE issue_id='$ISSUE_ID'
      ORDER BY ended_at DESC LIMIT 1
    " 2>/dev/null)
    if [ -z "$LOG_DATA" ]; then
      log "SKIP: $ISSUE_ID — no JSONL, no b64, no session_log"
      return 0
    fi
    # Metadata-only scoring: limited trajectory info from session_log
    local META_TURNS=$(echo "$LOG_DATA" | cut -d'|' -f1)
    local META_CONF=$(echo "$LOG_DATA" | cut -d'|' -f2)

    local PREFIX=$(echo "$ISSUE_ID" | cut -d- -f1)
    local IS_INFRA=0
    [[ "$PREFIX" == "IFRNLLEI01PRD" || "$PREFIX" == "IFRGRSKG01PRD" ]] && IS_INFRA=1

    local HAS_CONF=0
    [ "$META_CONF" != "-1" ] && [ "$META_CONF" != "" ] && HAS_CONF=1
    local STEPS_COMPLETED=$HAS_CONF
    local STEPS_EXPECTED=8
    local NOTES="metadata-only (no JSONL/b64)"
    if [ "$IS_INFRA" -eq 0 ]; then
      STEPS_EXPECTED=4
      STEPS_COMPLETED=$((HAS_CONF + (META_TURNS > 2 ? 1 : 0)))
      NOTES="dev session, metadata-only"
    fi
    local SCORE=0
    [ "$STEPS_EXPECTED" -gt 0 ] && SCORE=$((STEPS_COMPLETED * 100 / STEPS_EXPECTED))

    sqlite3 "$DB" "INSERT INTO session_trajectory (
      issue_id, has_netbox_lookup, has_incident_kb_query, has_react_structure,
      has_poll_or_approval, has_confidence, has_evidence_commands, has_ssh_investigation,
      has_yt_comment, steps_completed, steps_expected, trajectory_score,
      tool_calls, turns, notes
    ) VALUES (
      '$ISSUE_ID', 0, 0, 0, 0, $HAS_CONF, 0, 0, 0,
      $STEPS_COMPLETED, $STEPS_EXPECTED, $SCORE,
      0, ${META_TURNS:-0}, '$NOTES'
    );" 2>/dev/null

    log "  $ISSUE_ID: score=$SCORE ($STEPS_COMPLETED/$STEPS_EXPECTED) turns=$META_TURNS [metadata-only]"
    return 0
  fi

  # Determine if infra or dev
  local PREFIX=$(echo "$ISSUE_ID" | cut -d- -f1)
  local IS_INFRA=0
  [[ "$PREFIX" == "IFRNLLEI01PRD" || "$PREFIX" == "IFRGRSKG01PRD" ]] && IS_INFRA=1

  local TURNS=0 TOOLS=0 RESPONSE=""

  if [ -f "$JSONL" ]; then
    # Parse JSONL for trajectory markers (full structured data)
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

    TURNS=$(echo "$FULL_TEXT" | grep '^TURNS:' | cut -d: -f2)
    TOOLS=$(echo "$FULL_TEXT" | grep '^TOOLS:' | cut -d: -f2)
    RESPONSE=$(echo "$FULL_TEXT" | sed -n '/^TEXT_START$/,/^TEXT_END$/p' | grep -v 'TEXT_')
  elif [ "$USING_B64" -eq 1 ]; then
    # b64 fallback: plain text response, not JSONL structure
    RESPONSE=$(cat "$TMP_B64" | head -c 10000)
    # Estimate turns/tools from session metadata
    TURNS=$(sqlite3 "$DB" "SELECT COALESCE(num_turns,0) FROM sessions WHERE issue_id='$ISSUE_ID'" 2>/dev/null || echo 0)
    TOOLS=0  # Cannot determine from plain text
  fi

  # Score each trajectory step
  local HAS_NETBOX=0 HAS_KB=0 HAS_REACT=0 HAS_POLL=0 HAS_CONF=0 HAS_EVIDENCE=0 HAS_SSH=0 HAS_YT=0

  if [ -f "$JSONL" ]; then
    # Check tool calls in full JSONL (structured)
    grep -q 'netbox\|NetBox' "$JSONL" 2>/dev/null && HAS_NETBOX=1
    grep -q 'kb-semantic-search\|incident_knowledge\|knowledge' "$JSONL" 2>/dev/null && HAS_KB=1
    grep -qiE 'ssh |kubectl |curl |show run|show version' "$JSONL" 2>/dev/null && HAS_EVIDENCE=1
    grep -q 'ssh' "$JSONL" 2>/dev/null && HAS_SSH=1
    grep -qiE 'youtrack|yt-post-comment|post.*comment' "$JSONL" 2>/dev/null && HAS_YT=1
  elif [ "$USING_B64" -eq 1 ]; then
    # Text-based detection from b64 response (less reliable but still useful)
    echo "$RESPONSE" | grep -qiE 'netbox|NetBox' && HAS_NETBOX=1
    echo "$RESPONSE" | grep -qiE 'incident.knowledge|knowledge.base|kb.search|past.incident' && HAS_KB=1
    echo "$RESPONSE" | grep -qiE 'ssh|kubectl|curl|show run|show version|command output' && HAS_EVIDENCE=1
    echo "$RESPONSE" | grep -qi 'ssh' && HAS_SSH=1
    echo "$RESPONSE" | grep -qiE 'youtrack|posted.*comment|YT.*comment' && HAS_YT=1
  fi

  # Text-based checks (work for both JSONL response text and b64 plain text)
  echo "$RESPONSE" | grep -qiE 'THOUGHT:|OBSERVATION:|SYNTHESIS:' && HAS_REACT=1
  echo "$RESPONSE" | grep -qiE '\[POLL\]|awaiting approval|Which approach' && HAS_POLL=1
  echo "$RESPONSE" | grep -qiE 'CONFIDENCE:\s*[0-9]' && HAS_CONF=1

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

  # Add source note for b64 fallback
  [ "$USING_B64" -eq 1 ] && NOTES="${NOTES:+$NOTES, }b64-fallback"

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

  # Cleanup temp b64 file
  [ -n "$TMP_B64" ] && rm -f "$TMP_B64"

  log "  $ISSUE_ID: score=$SCORE ($STEPS_COMPLETED/$STEPS_EXPECTED) turns=$TURNS tools=$TOOLS"
}

# Main
if [ "${1:-}" = "--recent" ]; then
  log "Scoring recent unscored sessions..."
  # First: score sessions with JSONL files
  for jsonl in /tmp/claude-run-*.jsonl; do
    [ -f "$jsonl" ] || continue
    ISSUE=$(basename "$jsonl" | sed 's/claude-run-//' | sed 's/.jsonl//')
    score_session "$ISSUE"
  done
  # Second: score active sessions with b64 data but no JSONL
  while IFS= read -r ISSUE; do
    [ -z "$ISSUE" ] && continue
    score_session "$ISSUE"
  done < <(sqlite3 "$DB" "
    SELECT s.issue_id FROM sessions s
    LEFT JOIN session_trajectory t ON s.issue_id = t.issue_id
    WHERE t.issue_id IS NULL
      AND (s.last_response_b64 IS NOT NULL AND s.last_response_b64 != '')
  " 2>/dev/null)

elif [ "${1:-}" = "--backfill" ]; then
  LIMIT="${2:-50}"
  log "Backfilling unscored archived sessions (limit: $LIMIT)..."
  # Iterate session_log entries that have no trajectory score yet
  while IFS= read -r ISSUE; do
    [ -z "$ISSUE" ] && continue
    score_session "$ISSUE"
  done < <(sqlite3 "$DB" "
    SELECT DISTINCT sl.issue_id FROM session_log sl
    LEFT JOIN session_trajectory t ON sl.issue_id = t.issue_id
    WHERE t.issue_id IS NULL
    ORDER BY sl.ended_at DESC
    LIMIT $LIMIT
  " 2>/dev/null)

elif [ -n "${1:-}" ]; then
  score_session "$1"
else
  echo "Usage: score-trajectory.sh <issue_id> | --recent | --backfill [limit]"
fi

log "Done"
