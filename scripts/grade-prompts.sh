#!/bin/bash
# grade-prompts.sh — Daily prompt scorecard grading for all 15 prompt surfaces
# Grades each prompt on 6 dimensions (0-100): effectiveness, efficiency,
# completeness, consistency, feedback, retry_rate. Composite = weighted average.
#
# Cron: 0 3 * * * (daily 03:00 UTC)
# Output: SQLite prompt_scorecard table + Prometheus metrics
#
# Grading philosophy:
#   - Use EXISTING session data (confidence, cost, turns, feedback, resolution)
#   - No LLM calls — pure SQL analytics
#   - Each surface graded on applicable dimensions only (-1 = N/A)
#   - Composite skips N/A dimensions (weighted average of available)

set -uo pipefail

DB="${GATEWAY_DB:-/app/cubeos/claude-context/gateway.db}"
PROM_OUT="/var/lib/node_exporter/textfile_collector/prompt_scores.prom"
LOG_TAG="[grade-prompts]"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $LOG_TAG $*"; }

# Ensure table exists
sqlite3 "$DB" "
CREATE TABLE IF NOT EXISTS prompt_scorecard (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  prompt_surface TEXT NOT NULL,
  window TEXT NOT NULL,
  graded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  effectiveness INTEGER DEFAULT -1,
  efficiency INTEGER DEFAULT -1,
  completeness INTEGER DEFAULT -1,
  consistency INTEGER DEFAULT -1,
  feedback INTEGER DEFAULT -1,
  retry_rate INTEGER DEFAULT -1,
  composite INTEGER DEFAULT -1,
  n_samples INTEGER DEFAULT 0,
  notes TEXT DEFAULT ''
);" 2>/dev/null

# Helper: compute weighted composite from available dimensions
compute_composite() {
  local eff=$1 effic=$2 comp=$3 cons=$4 fb=$5 retry=$6
  # Weights: effectiveness=30, efficiency=15, completeness=25, consistency=10, feedback=15, retry=5
  local weights=(30 15 25 10 15 5)
  local scores=($eff $effic $comp $cons $fb $retry)
  local total_weight=0 weighted_sum=0

  for i in "${!scores[@]}"; do
    if [ "${scores[$i]}" != "-1" ] && [ "${scores[$i]}" -ge 0 ] 2>/dev/null; then
      weighted_sum=$((weighted_sum + scores[i] * weights[i]))
      total_weight=$((total_weight + weights[i]))
    fi
  done

  if [ "$total_weight" -gt 0 ]; then
    echo $((weighted_sum / total_weight))
  else
    echo -1
  fi
}

# Helper: insert scorecard row
insert_score() {
  local surface="$1" window="$2" eff="$3" effic="$4" comp="$5" cons="$6" fb="$7" retry="$8" n="$9" notes="${10:-}"
  local composite=$(compute_composite "$eff" "$effic" "$comp" "$cons" "$fb" "$retry")

  sqlite3 "$DB" "INSERT INTO prompt_scorecard (prompt_surface, window, effectiveness, efficiency, completeness, consistency, feedback, retry_rate, composite, n_samples, notes)
    VALUES ('$surface', '$window', $eff, $effic, $comp, $cons, $fb, $retry, $composite, $n, '$notes');"
}

log "Starting daily prompt grading"

for WINDOW in 7 30; do
  W="${WINDOW}d"
  DATE_FILTER="datetime('now', '-${WINDOW} days')"

  log "=== Window: $W ==="

  ***REMOVED***
  # 1. BUILD PROMPT (INFRA) — the most data-rich surface
  ***REMOVED***
  N=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE (issue_id LIKE 'IFRNLLEI01PRD%' OR issue_id LIKE 'IFRGRSKG01PRD%') AND confidence > 0 AND started_at > $DATE_FILTER")

  if [ "$N" -gt 0 ]; then
    # Effectiveness: avg confidence mapped to 0-100
    AVG_CONF=$(sqlite3 "$DB" "SELECT CAST(ROUND(AVG(confidence)*100,0) AS INTEGER) FROM sessions WHERE (issue_id LIKE 'IFR%') AND confidence > 0 AND started_at > $DATE_FILTER")
    EFF=${AVG_CONF:-0}

    # Efficiency: cost relative to median (only if cost data available)
    COST_N=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE (issue_id LIKE 'IFR%') AND cost_usd > 0 AND started_at > $DATE_FILTER")
    if [ "$COST_N" -gt 2 ]; then
      # Median turn count as efficiency proxy (lower = more efficient)
      MEDIAN_TURNS=$(sqlite3 "$DB" "SELECT num_turns FROM sessions WHERE (issue_id LIKE 'IFR%') AND num_turns > 0 AND started_at > $DATE_FILTER ORDER BY num_turns LIMIT 1 OFFSET $((COST_N/2))")
      AVG_TURNS=$(sqlite3 "$DB" "SELECT ROUND(AVG(num_turns),0) FROM sessions WHERE (issue_id LIKE 'IFR%') AND num_turns > 0 AND started_at > $DATE_FILTER")
      if [ "$MEDIAN_TURNS" -gt 0 ]; then
        RATIO=$(python3 -c "print(min(100, max(0, int(100 - (($AVG_TURNS / $MEDIAN_TURNS) - 1) * 50))))" 2>/dev/null || echo 70)
        EFFIC=$RATIO
      else
        EFFIC=-1
      fi
    else
      EFFIC=-1
    fi

    # Completeness: % with confidence present
    WITH_CONF=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE (issue_id LIKE 'IFR%') AND confidence > 0 AND started_at > $DATE_FILTER")
    TOTAL_INFRA=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE (issue_id LIKE 'IFR%') AND started_at > $DATE_FILTER AND num_turns > 0")
    if [ "$TOTAL_INFRA" -gt 0 ]; then
      COMP=$((WITH_CONF * 100 / TOTAL_INFRA))
    else
      COMP=-1
    fi

    # Consistency: 100 - (stddev * 200), capped 0-100
    STDDEV=$(sqlite3 "$DB" "SELECT ROUND(
      SQRT(AVG(confidence * confidence) - AVG(confidence) * AVG(confidence)), 3)
      FROM sessions WHERE (issue_id LIKE 'IFR%') AND confidence > 0 AND started_at > $DATE_FILTER" 2>/dev/null || echo "0.1")
    CONS=$(python3 -c "print(max(0, min(100, int(100 - $STDDEV * 200))))" 2>/dev/null || echo 80)

    # Feedback: thumbs_up rate
    UP=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_feedback WHERE reaction='thumbs_up' AND created_at > $DATE_FILTER" 2>/dev/null || echo 0)
    DOWN=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_feedback WHERE reaction='thumbs_down' AND created_at > $DATE_FILTER" 2>/dev/null || echo 0)
    if [ $((UP + DOWN)) -gt 0 ]; then
      FB=$((UP * 100 / (UP + DOWN)))
    else
      FB=-1
    fi

    # Retry rate: % NOT retried (higher = better)
    RETRIED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE (issue_id LIKE 'IFR%') AND retry_count > 0 AND started_at > $DATE_FILTER" 2>/dev/null || echo 0)
    if [ "$TOTAL_INFRA" -gt 0 ]; then
      RETRY=$((100 - RETRIED * 100 / TOTAL_INFRA))
    else
      RETRY=-1
    fi

    insert_score "build_prompt_infra" "$W" "$EFF" "$EFFIC" "$COMP" "$CONS" "$FB" "$RETRY" "$N" ""
    log "  build_prompt_infra ($W): eff=$EFF effic=$EFFIC comp=$COMP cons=$CONS fb=$FB retry=$RETRY n=$N"
  else
    insert_score "build_prompt_infra" "$W" -1 -1 -1 -1 -1 -1 0 "no data"
    log "  build_prompt_infra ($W): no data"
  fi

  ***REMOVED***
  # 2. BUILD PROMPT (DEV) — CUBEOS, MESHSAT, etc.
  ***REMOVED***
  DEV_N=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE issue_id NOT LIKE 'IFR%' AND confidence > 0 AND started_at > $DATE_FILTER")

  if [ "$DEV_N" -gt 0 ]; then
    DEV_EFF=$(sqlite3 "$DB" "SELECT CAST(ROUND(AVG(confidence)*100,0) AS INTEGER) FROM sessions WHERE issue_id NOT LIKE 'IFR%' AND confidence > 0 AND started_at > $DATE_FILTER")
    DEV_COMP=$(sqlite3 "$DB" "SELECT CAST(ROUND(COUNT(CASE WHEN confidence > 0 THEN 1 END)*100.0/COUNT(*),0) AS INTEGER) FROM sessions WHERE issue_id NOT LIKE 'IFR%' AND started_at > $DATE_FILTER AND num_turns > 0" 2>/dev/null || echo -1)
    insert_score "build_prompt_dev" "$W" "${DEV_EFF:-0}" -1 "${DEV_COMP:--1}" -1 -1 -1 "$DEV_N" ""
    log "  build_prompt_dev ($W): eff=$DEV_EFF comp=$DEV_COMP n=$DEV_N"
  else
    insert_score "build_prompt_dev" "$W" -1 -1 -1 -1 -1 -1 0 "no data"
  fi

  ***REMOVED***
  # 3. SOUL.MD (Tier 1 — measured by escalation rate + triage confidence)
  ***REMOVED***
  # Tier 1 effectiveness = % of alerts handled WITHOUT escalation to Tier 2
  TOTAL_ALERTS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE (issue_id LIKE 'IFR%') AND started_at > $DATE_FILTER AND num_turns > 0")
  # All sessions that reached Claude Code were escalated; SOUL.md handles the rest
  # Proxy: avg confidence of sessions that DID escalate (higher = SOUL.md prepped well)
  if [ "$TOTAL_ALERTS" -gt 0 ]; then
    SOUL_EFF=$(sqlite3 "$DB" "SELECT CAST(ROUND(AVG(confidence)*100,0) AS INTEGER) FROM sessions WHERE (issue_id LIKE 'IFR%') AND confidence > 0 AND started_at > $DATE_FILTER")
    insert_score "soul_md" "$W" "${SOUL_EFF:-0}" -1 -1 -1 -1 -1 "$TOTAL_ALERTS" "proxy: T2 confidence reflects T1 prep quality"
  else
    insert_score "soul_md" "$W" -1 -1 -1 -1 -1 -1 0 "no data"
  fi

  ***REMOVED***
  # 4. BUILD RETRY (1+2) — measured by retry success rate
  ***REMOVED***
  RETRIED_TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE retry_count > 0 AND started_at > $DATE_FILTER" 2>/dev/null || echo 0)
  RETRIED_IMPROVED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE retry_count > 0 AND retry_improved = 1 AND started_at > $DATE_FILTER" 2>/dev/null || echo 0)

  if [ "$RETRIED_TOTAL" -gt 0 ]; then
    RETRY_EFF=$((RETRIED_IMPROVED * 100 / RETRIED_TOTAL))
    insert_score "build_retry" "$W" "$RETRY_EFF" -1 -1 -1 -1 -1 "$RETRIED_TOTAL" ""
  else
    insert_score "build_retry" "$W" -1 -1 -1 -1 -1 -1 0 "no retried sessions in window"
  fi

  ***REMOVED***
  # 5. BUILD FALLBACK — recovery rate
  ***REMOVED***
  # No direct tracking yet — placeholder with note
  insert_score "build_fallback" "$W" -1 -1 -1 -1 -1 -1 0 "tracking not yet implemented"

  ***REMOVED***
  # 6. CLAUDE.MD — static config, graded by completeness only
  ***REMOVED***
  CLAUDE_LINES=$(wc -l < /app/claude-gateway/CLAUDE.md 2>/dev/null || echo 0)
  if [ "$CLAUDE_LINES" -le 200 ] && [ "$CLAUDE_LINES" -gt 50 ]; then
    CLAUDE_COMP=100
  elif [ "$CLAUDE_LINES" -gt 200 ]; then
    CLAUDE_COMP=50  # Over limit
  else
    CLAUDE_COMP=25  # Too sparse
  fi
  insert_score "claude_md" "$W" -1 -1 "$CLAUDE_COMP" -1 -1 -1 1 "static: ${CLAUDE_LINES} lines"

  ***REMOVED***
  # 7-12. SUB-AGENTS (6 agents) — graded by file completeness
  ***REMOVED***
  for agent in triage-researcher k8s-diagnostician cisco-asa-specialist storage-specialist security-analyst workflow-validator code-explorer code-reviewer ci-debugger dependency-analyst; do
    AGENT_FILE="/app/claude-gateway/.claude/agents/${agent}.md"
    if [ -f "$AGENT_FILE" ]; then
      # Check structured output format
      SECTIONS=$(grep -c '^### [0-9]' "$AGENT_FILE" 2>/dev/null || echo 0)
      HAS_OBSTACLES=$(grep -q 'Obstacles' "$AGENT_FILE" && echo 1 || echo 0)
      HAS_MODEL=$(grep -q '^model:' "$AGENT_FILE" && echo 1 || echo 0)
      HAS_TOOLS=$(grep -q '^tools:' "$AGENT_FILE" && echo 1 || echo 0)
      HAS_MAXTURNS=$(grep -q '^maxTurns:' "$AGENT_FILE" && echo 1 || echo 0)

      # Completeness: sections + obstacles + model + tools + maxTurns
      TOTAL_CHECKS=5
      SEC_OK=0; [ "$SECTIONS" -gt 3 ] && SEC_OK=1
      PASSED=$((HAS_OBSTACLES + HAS_MODEL + HAS_TOOLS + HAS_MAXTURNS + SEC_OK))
      AGENT_COMP=$((PASSED * 100 / TOTAL_CHECKS))

      insert_score "subagent_${agent}" "$W" -1 -1 "$AGENT_COMP" -1 -1 -1 0 "static: ${SECTIONS} output sections"
    else
      insert_score "subagent_${agent}" "$W" -1 -1 0 -1 -1 -1 0 "file missing"
    fi
  done

  ***REMOVED***
  # 13-15. TRIAGE SCRIPTS — graded by RAG usage + confidence output
  ***REMOVED***
  for script in infra-triage k8s-triage security-triage; do
    SCRIPT_FILE="/app/claude-gateway/openclaw/skills/${script}/${script}.sh"
    if [ -f "$SCRIPT_FILE" ]; then
      HAS_RAG=$(grep -q 'kb-semantic-search' "$SCRIPT_FILE" && echo 1 || echo 0)
      HAS_HOSTNAME_VAL=$(grep -q 'validate_hostname' "$SCRIPT_FILE" && echo 1 || echo 0)
      HAS_ERROR_HANDLER=$(grep -q 'error_handler' "$SCRIPT_FILE" && echo 1 || echo 0)
      HAS_MAINT_CHECK=$(grep -q 'MAINTENANCE' "$SCRIPT_FILE" && echo 1 || echo 0)
      HAS_DEDUP=$(grep -q 'existing.*issue\|dedup' "$SCRIPT_FILE" && echo 1 || echo 0)

      TOTAL_CHECKS=5
      PASSED=$((HAS_RAG + HAS_HOSTNAME_VAL + HAS_ERROR_HANDLER + HAS_MAINT_CHECK + HAS_DEDUP))
      TRIAGE_COMP=$((PASSED * 100 / TOTAL_CHECKS))

      insert_score "triage_${script}" "$W" -1 -1 "$TRIAGE_COMP" -1 -1 -1 0 "rag=${HAS_RAG} validate=${HAS_HOSTNAME_VAL} error=${HAS_ERROR_HANDLER} maint=${HAS_MAINT_CHECK} dedup=${HAS_DEDUP}"
    else
      insert_score "triage_${script}" "$W" -1 -1 0 -1 -1 -1 0 "file missing"
    fi
  done

done  # End window loop

***REMOVED***
# EXPORT TO PROMETHEUS
***REMOVED***
log "Exporting to Prometheus"

TMPOUT="${PROM_OUT}.tmp"
echo "# HELP chatops_prompt_score Prompt surface quality score (0-100, -1=N/A)" > "$TMPOUT"
echo "# TYPE chatops_prompt_score gauge" >> "$TMPOUT"

sqlite3 "$DB" "SELECT prompt_surface, window, effectiveness, efficiency, completeness, consistency, feedback, retry_rate, composite, n_samples FROM prompt_scorecard WHERE graded_at > datetime('now', '-25 hours') ORDER BY prompt_surface, window" | while IFS='|' read -r surface window eff effic comp cons fb retry composite n; do
  for dim_name in effectiveness efficiency completeness consistency feedback retry_rate composite; do
    eval "val=\$$dim_name" 2>/dev/null || val=-1
    case "$dim_name" in
      effectiveness) val=$eff ;; efficiency) val=$effic ;; completeness) val=$comp ;;
      consistency) val=$cons ;; feedback) val=$fb ;; retry_rate) val=$retry ;; composite) val=$composite ;;
    esac
    echo "chatops_prompt_score{surface=\"$surface\",dimension=\"$dim_name\",window=\"$window\"} $val" >> "$TMPOUT"
  done
  echo "chatops_prompt_samples{surface=\"$surface\",window=\"$window\"} $n" >> "$TMPOUT"
done

mv "$TMPOUT" "$PROM_OUT"

# Summary
***REMOVED***
# SUBSYSTEM SUMMARY
***REMOVED***
echo "" >> "$PROM_OUT"
echo "# HELP chatops_subsystem_prompt_avg Average composite prompt score by subsystem" >> "$PROM_OUT"
echo "# TYPE chatops_subsystem_prompt_avg gauge" >> "$PROM_OUT"

# ChatOps surfaces: build_prompt_infra, soul_md, triage_infra, triage_k8s
CHATOPS_AVG=$(sqlite3 "$DB" "SELECT COALESCE(ROUND(AVG(composite),0),-1) FROM prompt_scorecard WHERE window='7d' AND composite >= 0 AND prompt_surface IN ('build_prompt_infra','soul_md','triage_infra-triage','triage_k8s-triage') AND graded_at > datetime('now', '-25 hours')" 2>/dev/null || echo -1)
echo "chatops_subsystem_prompt_avg{subsystem=\"chatops\"} $CHATOPS_AVG" >> "$PROM_OUT"

# ChatSecOps surfaces: triage_security
SECOPS_AVG=$(sqlite3 "$DB" "SELECT COALESCE(ROUND(AVG(composite),0),-1) FROM prompt_scorecard WHERE window='7d' AND composite >= 0 AND prompt_surface IN ('triage_security-triage') AND graded_at > datetime('now', '-25 hours')" 2>/dev/null || echo -1)
echo "chatops_subsystem_prompt_avg{subsystem=\"chatsecops\"} $SECOPS_AVG" >> "$PROM_OUT"

# ChatDevOps surfaces: build_prompt_dev
DEVOPS_AVG=$(sqlite3 "$DB" "SELECT COALESCE(ROUND(AVG(composite),0),-1) FROM prompt_scorecard WHERE window='7d' AND composite >= 0 AND prompt_surface IN ('build_prompt_dev') AND graded_at > datetime('now', '-25 hours')" 2>/dev/null || echo -1)
echo "chatops_subsystem_prompt_avg{subsystem=\"chatdevops\"} $DEVOPS_AVG" >> "$PROM_OUT"

log "Grading complete"
TOTAL_SCORES=$(sqlite3 "$DB" "SELECT COUNT(*) FROM prompt_scorecard WHERE graded_at > datetime('now', '-25 hours')")
log "  $TOTAL_SCORES scores written ($(($TOTAL_SCORES / 2)) surfaces x 2 windows)"
sqlite3 -header -column "$DB" "SELECT prompt_surface, window, composite, n_samples FROM prompt_scorecard WHERE graded_at > datetime('now', '-25 hours') AND window='7d' ORDER BY composite DESC"
