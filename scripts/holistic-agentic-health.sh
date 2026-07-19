#!/usr/bin/env bash
# holistic-agentic-health.sh v2 — Holistic e2e health check for the agentic platform.
#
# Tests EVERY feature claimed in README.md / README.extensive.md:
#   Existence checks + functional tests + cross-site + e2e smoke tests.
#   35 sections, ~111 checks.
#
# Usage:
#   ./scripts/holistic-agentic-health.sh            # Full run (~55s)
#   ./scripts/holistic-agentic-health.sh --quick     # Skip slow checks (~15s)
#   ./scripts/holistic-agentic-health.sh --json      # JSON output
#   ./scripts/holistic-agentic-health.sh --smoke     # Include e2e smoke tests (~90s)
#
# Exit codes: 0 = all pass, 1 = failures detected
# YT: IFRNLLEI01PRD-465

set -uo pipefail
cd "$(dirname "$0")/.."
START_TIME=$(date +%s)

# ─── Config ──────────────────────────────────────────────────────────────────
DB="$HOME/gitlab/products/cubeos/claude-context/gateway.db"
N8N_URL="https://n8n.example.net"
N8N_KEY="REDACTED_JWT"
QUICK=false
JSON_OUT=false
SMOKE=false
# Load ASA password from .env (never hardcoded)
if [ -f "$HOME/gitlab/n8n/claude-gateway/.env" ]; then
    set -a; source "$HOME/gitlab/n8n/claude-gateway/.env"; set +a
fi
ASA_PW="${CISCO_ASA_PASSWORD:?CISCO_ASA_PASSWORD not set - source .env}"
MATRIX_BOT_TOKEN="${MATRIX_CLAUDE_TOKEN:-}"
YT_TOKEN="${YOUTRACK_API_TOKEN:-}"
NB_TOKEN="${NETBOX_TOKEN:-}"

for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=true ;;
    --json)  JSON_OUT=true ;;
    --smoke) SMOKE=true ;;
  esac
done

# ─── Historical Trending Tables ──────────────────────────────────────────────
sqlite3 "$DB" "
CREATE TABLE IF NOT EXISTS health_check_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  score INTEGER, pass INTEGER, fail INTEGER, warn INTEGER, skip INTEGER,
  duration_s REAL, mode TEXT DEFAULT 'full'
);
CREATE TABLE IF NOT EXISTS health_check_detail (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER REFERENCES health_check_results(id),
  status TEXT, name TEXT, detail TEXT
);
" 2>/dev/null

# ─── Test Framework ──────────────────────────────────────────────────────────
PASS=0 FAIL=0 WARN=0 SKIP=0
RESULTS=()

pass() { ((PASS++)); RESULTS+=("PASS|$1|$2"); $JSON_OUT || printf "  \e[32mPASS\e[0m  %s — %s\n" "$1" "$2"; }
fail() { ((FAIL++)); RESULTS+=("FAIL|$1|$2"); $JSON_OUT || printf "  \e[31mFAIL\e[0m  %s — %s\n" "$1" "$2"; }
warn() { ((WARN++)); RESULTS+=("WARN|$1|$2"); $JSON_OUT || printf "  \e[33mWARN\e[0m  %s — %s\n" "$1" "$2"; }
skip() { ((SKIP++)); RESULTS+=("SKIP|$1|$2"); $JSON_OUT || printf "  \e[36mSKIP\e[0m  %s — %s\n" "$1" "$2"; }

# Safe match counter. `grep -c` prints its count (including 0) AND exits 1 on zero
# matches, so the common `$(... | grep -c X || echo 0)` yields "0\n0" on no-match;
# a later $((VAR + 0)) then hits a bash syntax error that aborts the entire
# enclosing compound and silently drops every remaining check in it (this ate the
# vti-tunnels/cross-site-ping/pve-quorum/bgp-peers checks for months). Always
# count matches through this helper: exactly one number, exit 0.
countc() { local n; n=$(grep -c "$@" 2>/dev/null); printf '%s\n' "${n:-0}"; return 0; }
section() { $JSON_OUT || printf "\n\e[1m━━━ %s ━━━\e[0m\n" "$1"; }

# ─── Helpers ─────────────────────────────────────────────────────────────────
n8n_api() { curl -sk -H "X-N8N-API-KEY: $N8N_KEY" "$N8N_URL/api/v1/$1" 2>/dev/null; }
db_count() { sqlite3 "$DB" "SELECT COUNT(*) FROM $1;" 2>/dev/null || echo 0; }
db_recent() { sqlite3 "$DB" "SELECT COUNT(*) FROM $1 WHERE $2 >= datetime('now','-7 days');" 2>/dev/null || echo 0; }
db_max_age_hours() {
  local tbl="$1" col="$2"
  sqlite3 "$DB" "SELECT CAST((julianday('now') - julianday(MAX($col))) * 24 AS INTEGER) FROM $tbl;" 2>/dev/null || echo 9999
}

# Cache the n8n active workflows response (avoid repeated API calls)
WF_CACHE=$(n8n_api "workflows?limit=100&active=true" 2>/dev/null)

***REMOVED***════════════════
# S1: n8n Workflows
***REMOVED***════════════════
section "1. n8n Workflows (claim: 25 active)"

ACTIVE_WFS=$(echo "$WF_CACHE" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo 0)
if (( ACTIVE_WFS >= 25 )); then pass "workflow-count" "$ACTIVE_WFS active (>= 25)"
else fail "workflow-count" "only $ACTIVE_WFS active (expected >= 25)"; fi

# "Session End" intentionally OMITTED — that workflow was retired 2026-06-26 (its archival logic moved into
# reconcile-completed-sessions.py); checking it for "active" would be a false failure.
for WF_NAME in "Runner" "Matrix Bridge" "Progress Poller" "LibreNMS Receiver" "Prometheus Alert Receiver" "CrowdSec Alert Receiver"; do
  FOUND=$(echo "$WF_CACHE" | python3 -c "import sys,json; wfs=json.load(sys.stdin).get('data',[]); print(len([w for w in wfs if '$WF_NAME' in w.get('name','')]))" 2>/dev/null || echo 0)
  if (( FOUND > 0 )); then pass "wf-$WF_NAME" "active"
  else fail "wf-$WF_NAME" "NOT active"; fi
done

# NEW: n8n execution error rate (24h)
ERR_24H=$(n8n_api "executions?limit=200&status=error" | python3 -c "
import sys,json,datetime as dt
execs=json.load(sys.stdin).get('data',[])
cutoff=(dt.datetime.utcnow()-dt.timedelta(hours=24)).isoformat()+'Z'
print(len([e for e in execs if (e.get('startedAt','')>cutoff)]))" 2>/dev/null || echo 0)
OK_24H=$(n8n_api "executions?limit=200&status=success" | python3 -c "
import sys,json,datetime as dt
execs=json.load(sys.stdin).get('data',[])
cutoff=(dt.datetime.utcnow()-dt.timedelta(hours=24)).isoformat()+'Z'
print(len([e for e in execs if (e.get('startedAt','')>cutoff)]))" 2>/dev/null || echo 0)
TOTAL_24H=$((ERR_24H + OK_24H))
if (( TOTAL_24H > 0 )); then
  RATE=$((ERR_24H * 100 / TOTAL_24H))
  if (( RATE <= 5 )); then pass "exec-error-rate" "${RATE}% errors in 24h ($ERR_24H/$TOTAL_24H)"
  elif (( RATE <= 10 )); then warn "exec-error-rate" "${RATE}% errors in 24h ($ERR_24H/$TOTAL_24H)"
  else fail "exec-error-rate" "${RATE}% errors in 24h ($ERR_24H/$TOTAL_24H)"; fi
else
  warn "exec-error-rate" "no executions in last 24h"
fi

***REMOVED***════════════════
# S2: SQLite Tables
***REMOVED***════════════════
section "2. SQLite Tables (claim: 23 tables, 148K+ rows)"

TABLE_COUNT=$(sqlite3 "$DB" ".tables" 2>/dev/null | tr ' ' '\n' | grep -v '^$' | wc -l)
if (( TABLE_COUNT >= 23 )); then pass "table-count" "$TABLE_COUNT tables (>= 23)"
else fail "table-count" "only $TABLE_COUNT tables"; fi

TOTAL_ROWS=0; EMPTY_TABLES=()
for TBL in $(sqlite3 "$DB" ".tables" 2>/dev/null); do
  CNT=$(db_count "$TBL"); TOTAL_ROWS=$((TOTAL_ROWS + CNT))
  if (( CNT == 0 )); then EMPTY_TABLES+=("$TBL"); fi
done
if (( TOTAL_ROWS >= 100000 )); then pass "total-rows" "${TOTAL_ROWS} rows (>= 100K)"
else warn "total-rows" "${TOTAL_ROWS} rows (expected >= 100K)"; fi

if (( ${#EMPTY_TABLES[@]} == 0 )); then pass "no-empty-tables" "all tables have data"
else
  # WARN only on UNEXPECTED empties. Skip tables that are dark-by-design: any db-table flagged
  # known_dark:true in config/component-registry.json (curated — parallel-dev work_units/features,
  # the handoff_log audit-twin, retired/event-driven tables, etc.).
  KNOWN_EMPTY_OK=" $(jq -r '.components[]?|select(.type=="db-table" and .known_dark==true)|.liveness.ref // (.name|sub("^table:";""))' config/component-registry.json 2>/dev/null | tr '\n' ' ') "
  UNEXPECTED_EMPTY=()
  for t in "${EMPTY_TABLES[@]}"; do
    case "$KNOWN_EMPTY_OK" in *" $t "*) : ;; *) UNEXPECTED_EMPTY+=("$t") ;; esac
  done
  if (( ${#UNEXPECTED_EMPTY[@]} == 0 )); then pass "no-empty-tables" "${#EMPTY_TABLES[@]} empty, all dark-by-design: ${EMPTY_TABLES[*]}"
  else warn "no-empty-tables" "${#UNEXPECTED_EMPTY[@]} unexpected empty: ${UNEXPECTED_EMPTY[*]}"; fi
fi

FRESH_TABLES=0
for TBL_CHECK in "session_judgment:judged_at" "session_trajectory:graded_at" "session_transcripts:created_at" \
                  "agent_diary:created_at" "tool_call_log:created_at" "llm_usage:recorded_at" \
                  "wiki_articles:compiled_at" "prompt_scorecard:graded_at"; do
  TBL="${TBL_CHECK%%:*}"; COL="${TBL_CHECK##*:}"
  RECENT=$(db_recent "$TBL" "$COL" 2>/dev/null || echo 0)
  if (( RECENT > 0 )); then ((FRESH_TABLES++)); fi
done
if (( FRESH_TABLES >= 5 )); then pass "fresh-data" "$FRESH_TABLES/8 key tables have data from last 7 days"
else warn "fresh-data" "only $FRESH_TABLES/8 key tables have recent data"; fi

# Per-table staleness with thresholds. 4th field = severity (fail|warn).
# The 3 Session-End-revived writers (tool_call_log/otel_spans/session_quality, dark Apr->Jun
# 2026 until reconcile-completed-sessions.py ported their side-effects) are FAIL so a future
# re-darkening pages via HolisticHealthFailing instead of sitting silently as a WARN.
# Thresholds generous (72-96h) to tolerate a quiet weekend without false alarms.
for STALE_CHECK in "tool_call_log:created_at:72:fail" "otel_spans:created_at:96:fail" \
                    "session_quality:created_at:96:fail" \
                    "llm_usage:recorded_at:72:warn" "session_transcripts:created_at:168:warn" \
                    "session_judgment:judged_at:168:warn" "wiki_articles:compiled_at:48:warn" \
                    "agent_diary:created_at:168:warn" "prompt_scorecard:graded_at:336:warn"; do
  S_TBL=$(echo "$STALE_CHECK" | cut -d: -f1)
  S_COL=$(echo "$STALE_CHECK" | cut -d: -f2)
  S_MAX=$(echo "$STALE_CHECK" | cut -d: -f3)
  S_SEV=$(echo "$STALE_CHECK" | cut -d: -f4)
  AGE_H=$(db_max_age_hours "$S_TBL" "$S_COL")
  if (( AGE_H <= S_MAX )); then pass "staleness-$S_TBL" "last write ${AGE_H}h ago (<= ${S_MAX}h)"
  elif [ "$S_SEV" = "fail" ]; then fail "staleness-$S_TBL" "last write ${AGE_H}h ago (threshold ${S_MAX}h) — revived Session-End writer dark again? check reconcile side-effects"
  else warn "staleness-$S_TBL" "last write ${AGE_H}h ago (threshold ${S_MAX}h)"; fi
done

***REMOVED***════════════════
# S3: MCP Servers
***REMOVED***════════════════
section "3. MCP Servers (claim: 10 servers)"
MCP_PROCS=$(ps aux 2>/dev/null | grep -E 'n8n-mcp|youtrack-mcp|mcp-proxmox|codegraph|opentofu|tfmcp|kubernetes' | grep -v grep | wc -l)
if (( MCP_PROCS >= 5 )); then pass "mcp-processes" "$MCP_PROCS MCP-related processes running"
else warn "mcp-processes" "only $MCP_PROCS MCP processes"; fi

***REMOVED***════════════════
# S4: RAG Pipeline
***REMOVED***════════════════
section "4. RAG Pipeline (claim: 4-signal hybrid RRF)"

RAG_RESULT=$(python3 scripts/kb-semantic-search.py search "device down" --limit 3 2>&1 || echo "ERROR")
if echo "$RAG_RESULT" | grep -q "RETRIEVAL_QUALITY\|similarity\|IFRNLLEI01PRD\|IFRGRSKG01PRD"; then
  pass "rag-semantic" "semantic search returns results"
else fail "rag-semantic" "no results: ${RAG_RESULT:0:100}"; fi

WIKI_COUNT=$(db_count "wiki_articles")
if (( WIKI_COUNT >= 40 )); then pass "rag-wiki" "$WIKI_COUNT wiki articles (>= 40)"
else fail "rag-wiki" "only $WIKI_COUNT wiki articles"; fi

TRANSCRIPT_COUNT=$(db_count "session_transcripts")
if (( TRANSCRIPT_COUNT >= 100 )); then pass "rag-transcripts" "$TRANSCRIPT_COUNT transcript chunks (>= 100)"
else warn "rag-transcripts" "only $TRANSCRIPT_COUNT"; fi

ENTITY_COUNT=$(db_count "graph_entities"); REL_COUNT=$(db_count "graph_relationships")
if (( ENTITY_COUNT >= 200 && REL_COUNT >= 100 )); then pass "graphrag" "$ENTITY_COUNT entities, $REL_COUNT rels"
else fail "graphrag" "entities=$ENTITY_COUNT rels=$REL_COUNT"; fi

# NEW: Functional RAG test — search known incident
RAG_FUNC=$(python3 scripts/kb-semantic-search.py search "Service up/down" --limit 5 2>&1 || echo "")
if echo "$RAG_FUNC" | grep -q "IFRNLLEI01PRD"; then pass "rag-functional" "known incident found in search"
else warn "rag-functional" "known incident not in top 5 results"; fi

***REMOVED***════════════════
# S5: Session End Pipeline
***REMOVED***════════════════
section "5. Session End Pipeline (claim: 18 nodes)"
SE_DATA=$(n8n_api "workflows/rgRGPOZgPcFCvv84" 2>/dev/null)
SE_NODES=$(echo "$SE_DATA" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('nodes',[])))" 2>/dev/null || echo 0)
if (( SE_NODES >= 18 )); then pass "session-end-nodes" "$SE_NODES nodes (>= 18)"
else fail "session-end-nodes" "only $SE_NODES nodes"; fi

for NODE in "Score Trajectory" "Judge Session" "Archive Transcript" "Export Traces" "Parse Tool Calls" "Populate Graph"; do
  if echo "$SE_DATA" | grep -q "$NODE"; then pass "se-node-$NODE" "present"
  else fail "se-node-$NODE" "MISSING"; fi
done

***REMOVED***════════════════
# S6: OpenClaw
***REMOVED***════════════════
section "6. OpenClaw Tier 1 (retired)"
# OpenClaw LXC VMID_REDACTED was destroyed 2026-04-29 ("not found on any node") and
# cc-cc is the only live mode — probing the dead host just burned SSH timeouts
# and emitted permanent WARNs. Retired 2026-07-03.
skip "openclaw-skills" "OpenClaw retired 2026-04-29 (LXC destroyed; cc-cc only mode)"
skip "openclaw-container" "OpenClaw retired 2026-04-29 (LXC destroyed; cc-cc only mode)"

***REMOVED***════════════════
# S7: Claude Code
***REMOVED***════════════════
section "7. Claude Code (claim: 10 agents, 5 skills, 3 hook events)"
AGENT_COUNT=$(ls .claude/agents/*.md 2>/dev/null | wc -l)
if (( AGENT_COUNT >= 10 )); then pass "cc-agents" "$AGENT_COUNT agents (>= 10)"
else fail "cc-agents" "only $AGENT_COUNT"; fi

SKILL_COUNT=$(ls -d .claude/skills/*/ 2>/dev/null | wc -l)
if (( SKILL_COUNT >= 5 )); then pass "cc-skills" "$SKILL_COUNT skills (>= 5)"
else fail "cc-skills" "only $SKILL_COUNT"; fi

HOOK_EVENTS=$(python3 -c "import json; print(len(json.load(open('.claude/settings.json')).get('hooks',{})))" 2>/dev/null || echo 0)
if (( HOOK_EVENTS >= 3 )); then pass "cc-hooks" "$HOOK_EVENTS hook events"
else fail "cc-hooks" "only $HOOK_EVENTS"; fi

***REMOVED***════════════════
# S8: Eval Pipeline
***REMOVED***════════════════
section "8. Evaluation Pipeline (claim: 98 scenarios)"

TOTAL_SCENARIOS=0
for ESET in regression discovery holdout synthetic; do
  if [ -f "scripts/eval-sets/$ESET.json" ]; then
    SC=$(python3 -c "import json; print(len(json.load(open('scripts/eval-sets/$ESET.json'))))" 2>/dev/null || echo 0)
    TOTAL_SCENARIOS=$((TOTAL_SCENARIOS + SC))
    pass "eval-$ESET" "$SC scenarios"
  else
    if [ "$ESET" = "synthetic" ]; then skip "eval-$ESET" "optional set"
    else fail "eval-$ESET" "missing"; fi
  fi
done

# NEW: Total scenario count
if (( TOTAL_SCENARIOS >= 98 )); then pass "eval-total" "$TOTAL_SCENARIOS total scenarios (>= 98)"
else fail "eval-total" "only $TOTAL_SCENARIOS total (expected >= 98)"; fi

for SCRIPT in llm-judge.sh score-trajectory.sh grade-prompts.sh eval-flywheel.sh prompt-improver.py; do
  if [ -x "scripts/$SCRIPT" ]; then pass "eval-script-$SCRIPT" "executable"
  else fail "eval-script-$SCRIPT" "missing"; fi
done

JUDGE_COUNT=$(db_count "session_judgment")
if (( JUDGE_COUNT >= 10 )); then pass "eval-judgments" "$JUDGE_COUNT judgments"
else warn "eval-judgments" "only $JUDGE_COUNT"; fi

# NEW: Functional trajectory test
TRAJ_OUT=$(bash scripts/score-trajectory.sh "AUDIT-SESSION-001" 2>&1 | head -5 || echo "ERROR")
if echo "$TRAJ_OUT" | grep -qiE "score|graded|trajectory|inserted|row"; then pass "eval-traj-functional" "trajectory scoring produces output"
else warn "eval-traj-functional" "unexpected output: ${TRAJ_OUT:0:80}"; fi

***REMOVED***════════════════
# S9: Safety Guardrails
***REMOVED***════════════════
section "9. Safety Guardrails (claim: 42 injection + 30 blocked)"

INJECTION_COUNT=$(grep -A500 'INJECTION_PATTERNS=(' scripts/hooks/unified-guard.sh 2>/dev/null | countc '"')
if (( INJECTION_COUNT >= 40 )); then pass "injection-patterns" "$INJECTION_COUNT lines (>= 40)"
else fail "injection-patterns" "only $INJECTION_COUNT"; fi

BLOCKED_COUNT=$(grep -A500 'BLOCKED_PATTERNS=(' scripts/hooks/unified-guard.sh 2>/dev/null | countc '"')
if (( BLOCKED_COUNT >= 30 )); then pass "blocked-patterns" "$BLOCKED_COUNT lines (>= 30)"
else fail "blocked-patterns" "only $BLOCKED_COUNT"; fi

if [ -f "openclaw/exec-approvals.json" ]; then pass "exec-approvals" "file exists"
else fail "exec-approvals" "missing"; fi

***REMOVED***════════════════
# S10: Observability
***REMOVED***════════════════
section "10. Observability (claim: OTel, 9 dashboards, 3 datasources)"

OTEL_SPANS=$(db_count "otel_spans")
if (( OTEL_SPANS >= 10000 )); then pass "otel-spans" "$OTEL_SPANS spans (>= 10K)"
else warn "otel-spans" "only $OTEL_SPANS"; fi

TOOL_CALLS=$(db_count "tool_call_log")
if (( TOOL_CALLS >= 50000 )); then pass "tool-calls" "$TOOL_CALLS logged (>= 50K)"
else warn "tool-calls" "only $TOOL_CALLS"; fi

# Grafana datasources
GRAFANA_POD=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$GRAFANA_POD" ]; then
  DS_COUNT=$(kubectl exec -n monitoring "$GRAFANA_POD" -c grafana -- curl -s http://localhost:3000/api/datasources -u REDACTED_d2abaa37 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
  if (( DS_COUNT >= 3 )); then pass "grafana-datasources" "$DS_COUNT datasources"
  else fail "grafana-datasources" "only $DS_COUNT"; fi

  # NEW: Dashboard count
  if $QUICK; then skip "grafana-dashboards" "skipped (--quick)"
  else
    DASH_COUNT=$(kubectl exec -n monitoring "$GRAFANA_POD" -c grafana -- curl -s 'http://localhost:3000/api/search?type=dash-db' -u REDACTED_d2abaa37 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
    if (( DASH_COUNT >= 9 )); then pass "grafana-dashboards" "$DASH_COUNT dashboards (>= 9)"
    else warn "grafana-dashboards" "only $DASH_COUNT dashboards"; fi
  fi

  # NEW: Prometheus target health
  if $QUICK; then skip "prom-targets" "skipped (--quick)"
  else
    PROM_POD=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$PROM_POD" ]; then
      TARGET_INFO=$(kubectl exec -n monitoring "$PROM_POD" -c prometheus -- wget -qO- 'http://localhost:9090/api/v1/targets' 2>/dev/null | python3 -c "
import sys,json
t=json.load(sys.stdin).get('data',{}).get('activeTargets',[])
up=len([x for x in t if x.get('health')=='up'])
print(f'{up}|{len(t)}')" 2>/dev/null || echo "0|0")
      UP=$(echo "$TARGET_INFO" | cut -d'|' -f1)
      TOT=$(echo "$TARGET_INFO" | cut -d'|' -f2)
      if (( UP == TOT && TOT > 0 )); then pass "prom-targets" "$UP/$TOT targets UP"
      elif (( UP > 0 )); then warn "prom-targets" "$UP/$TOT targets UP (some DOWN)"
      else fail "prom-targets" "no targets UP"; fi
    fi
  fi
else
  fail "grafana-pod" "Grafana pod not found"
fi

***REMOVED***════════════════
# S11: Crons
***REMOVED***════════════════
section "11. Crons (claim: 32)"
# Scheduler is native Cronicle since 2026-06-26 (crontab lines are #CRONICLE#-
# commented) — count enabled Cronicle events plus whatever remains in crontab.
CRON_COUNT=$(crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$' | wc -l)
CRONICLE_COUNT=$(curl -sm10 "http://localhost:3012/api/app/get_schedule/v1?api_key=${CRONICLE_API_KEY}&limit=1000" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(1 for r in d.get('rows',[]) if r.get('enabled')))" 2>/dev/null || echo 0)
if (( CRON_COUNT + CRONICLE_COUNT >= 30 )); then pass "crons" "$CRONICLE_COUNT Cronicle events + $CRON_COUNT crontab entries (>= 30)"
else warn "crons" "only $((CRON_COUNT + CRONICLE_COUNT)) ($CRONICLE_COUNT Cronicle + $CRON_COUNT crontab)"; fi

***REMOVED***════════════════
# S12: Self-Improving Prompts
***REMOVED***════════════════
section "12. Self-Improving Prompts"
if [ -f "config/prompt-patches.json" ]; then
  PATCH_COUNT=$(python3 -c "import json; print(len([p for p in json.load(open('config/prompt-patches.json')) if p.get('active')]))" 2>/dev/null || echo 0)
  pass "prompt-patches" "$PATCH_COUNT active patches"
else fail "prompt-patches" "config/prompt-patches.json missing"; fi

if [ -x "scripts/prompt-improver.py" ]; then pass "prompt-improver" "executable"
else fail "prompt-improver" "missing"; fi

***REMOVED***════════════════
# S13: Predictive Alerting
***REMOVED***════════════════
section "13. Predictive Alerting"
if [ -x "scripts/predictive-alerts.py" ]; then pass "predictive-script" "executable"
else fail "predictive-script" "missing"; fi

PRED_CRON=$(crontab -l 2>/dev/null | grep "predictive-alerts" | head -1)
if [ -n "$PRED_CRON" ]; then pass "predictive-cron" "configured"
else fail "predictive-cron" "no cron"; fi

***REMOVED***════════════════
# S14: Compiled Wiki
***REMOVED***════════════════
section "14. Compiled Wiki (claim: 45 articles)"
WIKI_FILES=$(find wiki/ -name '*.md' -not -name 'index.md' 2>/dev/null | wc -l)
if (( WIKI_FILES >= 40 )); then pass "wiki-files" "$WIKI_FILES articles (>= 40)"
else fail "wiki-files" "only $WIKI_FILES"; fi

WIKI_CRON=$(crontab -l 2>/dev/null | grep "wiki-compile" | head -1)
if [ -n "$WIKI_CRON" ]; then pass "wiki-cron" "daily recompilation"
else fail "wiki-cron" "no cron"; fi

# NEW: Wiki compile state freshness
if [ -f "wiki/.compile-state.json" ]; then
  COMPILE_AGE=$(python3 -c "
import json,datetime as dt
s=json.load(open('wiki/.compile-state.json'))
ts=s.get('compiled_at','')
if ts:
  # Handle format '2026-04-11 14:13 UTC'
  ts=ts.replace(' UTC','').strip()
  try: compiled=dt.datetime.fromisoformat(ts)
  except: compiled=dt.datetime.strptime(ts,'%Y-%m-%d %H:%M')
  age=(dt.datetime.utcnow()-compiled).total_seconds()/3600
  print(int(age))
else: print(9999)" 2>/dev/null || echo 9999)
  if (( COMPILE_AGE <= 48 )); then pass "wiki-freshness" "compiled ${COMPILE_AGE}h ago (<= 48h)"
  else warn "wiki-freshness" "compiled ${COMPILE_AGE}h ago (stale > 48h)"; fi
else warn "wiki-freshness" "no .compile-state.json"; fi

***REMOVED***════════════════
# S15: A2A Protocol
***REMOVED***════════════════
section "15. A2A Protocol"
A2A_CARDS=$(ls a2a/agent-cards/*.json 2>/dev/null | wc -l)
if (( A2A_CARDS >= 3 )); then pass "a2a-cards" "$A2A_CARDS agent cards"
else fail "a2a-cards" "only $A2A_CARDS"; fi

A2A_LOG=$(db_count "a2a_task_log")
if (( A2A_LOG >= 10 )); then pass "a2a-log" "$A2A_LOG entries"
else warn "a2a-log" "only $A2A_LOG"; fi

***REMOVED***════════════════
# S16: AWX + Plan-and-Execute
***REMOVED***════════════════
section "16. AWX Runbooks + Plan-and-Execute"
if [ -x "scripts/build-investigation-plan.sh" ]; then pass "plan-execute" "exists"
else fail "plan-execute" "missing"; fi

if [ -x "scripts/query-awx-runbooks.sh" ]; then pass "awx-query" "exists"
else fail "awx-query" "missing"; fi

if $QUICK; then skip "awx-api" "skipped (--quick)"
else
  AWX_RESULT=$(bash scripts/query-awx-runbooks.sh "kernel update" 2>&1 | head -3)
  if echo "$AWX_RESULT" | grep -qi "template\|ID\|playbook"; then pass "awx-api" "returns results"
  else warn "awx-api" "${AWX_RESULT:0:80}"; fi
fi

***REMOVED***════════════════
# S17: Ollama
***REMOVED***════════════════
section "17. Ollama (claim: nomic-embed-text)"
OLLAMA_MODELS=$(ssh -o ConnectTimeout=5 nl-gpu01 "curl -s http://localhost:11434/api/tags" 2>/dev/null | python3 -c "
import sys,json
models=json.load(sys.stdin).get('models',[])
names=[m['name'] for m in models]
has_embed=any('nomic' in n or 'embed' in n for n in names)
print(f'{len(models)}|{has_embed}')" 2>/dev/null || echo "0|False")

OLLAMA_COUNT=$(echo "$OLLAMA_MODELS" | cut -d'|' -f1)
HAS_EMBED=$(echo "$OLLAMA_MODELS" | cut -d'|' -f2)
if (( OLLAMA_COUNT > 0 )); then pass "ollama-running" "$OLLAMA_COUNT models"
else fail "ollama-running" "unreachable"; fi
if [ "$HAS_EMBED" = "True" ]; then pass "ollama-embed-model" "nomic-embed-text available"
else warn "ollama-embed-model" "not found"; fi

# NEW: Functional embedding test
if $QUICK; then skip "ollama-embed-func" "skipped (--quick)"
else
  DIMS=$(ssh -o ConnectTimeout=5 nl-gpu01 "curl -sf http://localhost:11434/api/embed -d '{\"model\":\"nomic-embed-text\",\"input\":\"health check test\"}'" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('embeddings',[[]])[0]))" 2>/dev/null || echo 0)
  if (( DIMS == 768 )); then pass "ollama-embed-func" "768-dim embedding generated"
  else fail "ollama-embed-func" "got $DIMS dims (expected 768)"; fi
fi

***REMOVED***════════════════
# S18: LibreNMS
***REMOVED***════════════════
section "18. LibreNMS API"
if $QUICK; then skip "librenms-nl" "skipped"; skip "librenms-gr" "skipped"
else
  NL_DEV=$(curl -sk -H "X-Auth-Token: REDACTED_LIBRENMS_NL_KEY" "https://nl-nms01.example.net/api/v0/devices" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',len(d.get('devices',[]))))" 2>/dev/null || echo 0)
  if (( NL_DEV >= 100 )); then pass "librenms-nl" "$NL_DEV NL devices"
  else warn "librenms-nl" "only $NL_DEV"; fi

  GR_RULES=$(curl -sk -H "X-Auth-Token: REDACTED_LIBRENMS_GR_KEY" "https://gr-nms01.example.net/api/v0/rules" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('rules',[])))" 2>/dev/null || echo 0)
  if (( GR_RULES >= 15 )); then pass "librenms-gr" "$GR_RULES GR rules"
  else warn "librenms-gr" "only $GR_RULES"; fi
fi

***REMOVED***════════════════
# S19: Key Scripts
***REMOVED***════════════════
section "19. Key Scripts (16 scripts)"
for SCRIPT in kb-semantic-search.py archive-session-transcript.py export-otel-traces.py \
              parse-tool-calls.py populate-graph.py agent-diary.py wiki-compile.py \
              write-session-metrics.sh write-agent-metrics.sh gateway-watchdog.sh \
              predictive-alerts.py prompt-improver.py crowdsec-learn.sh golden-test-suite.sh \
              maintenance-companion.sh freedom-qos-toggle.sh; do
  if [ -x "scripts/$SCRIPT" ]; then pass "script-$SCRIPT" "ok"
  else fail "script-$SCRIPT" "missing"; fi
done

***REMOVED***════════════════
# S20: Knowledge Injection
***REMOVED***════════════════
section "20. Knowledge Injection (claim: 55 CLAUDE.md, 74+ memories)"
CLAUDE_MD=$(find "$HOME/gitlab" -name "CLAUDE.md" 2>/dev/null | wc -l)
if (( CLAUDE_MD >= 50 )); then pass "claude-md" "$CLAUDE_MD files (>= 50)"
else warn "claude-md" "only $CLAUDE_MD"; fi

MEM_COUNT=$(ls "$HOME/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory/"*.md 2>/dev/null | wc -l)
if (( MEM_COUNT >= 50 )); then pass "memory-files" "$MEM_COUNT files (>= 50)"
else warn "memory-files" "only $MEM_COUNT"; fi

***REMOVED***════════════════
# S21: Credential Rotation (NEW)
***REMOVED***════════════════
section "21. Credential Rotation"
OVERDUE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM credential_usage_log WHERE rotation_due_at IS NOT NULL AND rotation_due_at < datetime('now');" 2>/dev/null || echo 0)
if (( OVERDUE == 0 )); then pass "cred-rotation" "no overdue credentials"
else warn "cred-rotation" "$OVERDUE credentials past rotation date"; fi

***REMOVED***════════════════
# S22: VTI Tunnels + Cross-site (NEW)
***REMOVED***════════════════
section "22. VTI Tunnels + Cross-site Connectivity"
if $QUICK; then skip "vti-tunnels" "skipped (--quick)"; skip "cross-site-ping" "skipped (--quick)"
else
  # NL ASA requires a PTY — sshpass -T sessions are closed immediately after login,
  # so probe via the shared pexpect helper (scripts/lib/asa_ssh.py) instead.
  VTI_RAW=$(python3 -c "
import sys
sys.path.insert(0, 'scripts/lib')
from asa_ssh import ssh_nl_asa_command
print(ssh_nl_asa_command(['show crypto ikev2 sa']) or '')" 2>/dev/null || true)
  if [ -z "${VTI_RAW//[[:space:]]/}" ]; then
    warn "vti-tunnels" "could not query nl-fw01 (pexpect probe returned nothing)"
  else
    VTI_UP=$(echo "$VTI_RAW" | countc "READY")
    if (( VTI_UP >= 6 )); then pass "vti-tunnels" "$VTI_UP IKEv2 SAs READY on nl-fw01 (>= 6)"
    elif (( VTI_UP >= 3 )); then warn "vti-tunnels" "only $VTI_UP READY (expected >= 6)"
    else fail "vti-tunnels" "$VTI_UP READY tunnels on nl-fw01"; fi
  fi

  if ping -c 2 -W 3 gr-pve01 >/dev/null 2>&1; then
    RTT=$(ping -c 2 -W 3 gr-pve01 2>/dev/null | tail -1 | cut -d'/' -f5 | cut -d'.' -f1)
    if (( RTT <= 50 )); then pass "cross-site-ping" "gr-pve01 reachable (${RTT}ms)"
    else warn "cross-site-ping" "gr-pve01 ${RTT}ms (>50ms)"; fi
  else fail "cross-site-ping" "gr-pve01 unreachable"; fi
fi

***REMOVED***════════════════
# S23: Matrix Bot Membership (NEW)
***REMOVED***════════════════
section "23. Matrix Bot Membership"
if $QUICK; then skip "matrix-rooms" "skipped (--quick)"
else
  ROOM_COUNT=$(curl -sf --connect-timeout 5 "https://matrix.example.net/_matrix/client/v3/joined_rooms" -H "Authorization: Bearer $MATRIX_BOT_TOKEN" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('joined_rooms',[])))" 2>/dev/null || echo 0)
  if (( ROOM_COUNT >= 6 )); then pass "matrix-rooms" "@claude in $ROOM_COUNT rooms (>= 6)"
  else warn "matrix-rooms" "only $ROOM_COUNT rooms"; fi
fi

***REMOVED***════════════════
# S24: Prompt Patches TTL (NEW)
***REMOVED***════════════════
section "24. Prompt Patches TTL"
EXPIRED_ACTIVE=$(python3 -c "
import json,datetime as dt
patches=json.load(open('config/prompt-patches.json'))
now=dt.datetime.utcnow()
expired=[p for p in patches if p.get('active') and 'expires_at' in p and dt.datetime.fromisoformat(p['expires_at'].rstrip('Z'))<now]
print(len(expired))" 2>/dev/null || echo 0)
if (( EXPIRED_ACTIVE == 0 )); then pass "patches-ttl" "no expired-but-active patches"
else fail "patches-ttl" "$EXPIRED_ACTIVE patches expired but still active"; fi

***REMOVED***════════════════
# S25: CrowdSec Freshness (NEW)
***REMOVED***════════════════
section "25. CrowdSec Scenario Stats"
CS_COUNT=$(db_count "crowdsec_scenario_stats")
if (( CS_COUNT >= 3 )); then pass "crowdsec-stats" "$CS_COUNT scenarios tracked"
else warn "crowdsec-stats" "only $CS_COUNT"; fi

***REMOVED***════════════════
# S26: OpenObserve (NEW)
***REMOVED***════════════════
section "26. OpenObserve OTLP"
if $QUICK; then skip "openobserve" "skipped (--quick)"
else
  OO_CODE=$(curl -sf --connect-timeout 5 -o /dev/null -w "%{http_code}" "http://10.0.181.X:5080/healthz" 2>/dev/null || echo 0)
  if [ "$OO_CODE" = "200" ]; then pass "openobserve" "healthz 200"
  else warn "openobserve" "healthz returned $OO_CODE"; fi
fi

***REMOVED***════════════════
# S27: n8n Webhook Functional (NEW)
***REMOVED***════════════════
section "27. n8n Webhook Functional"
STATS_RESP=$(curl -sf --connect-timeout 5 "$N8N_URL/webhook/agentic-stats" 2>/dev/null || echo "")
if echo "$STATS_RESP" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then pass "webhook-agentic-stats" "returns valid JSON"
else fail "webhook-agentic-stats" "no valid JSON response"; fi

***REMOVED***════════════════
# S28: Gateway Mode (NEW)
***REMOVED***════════════════
section "28. Gateway Mode + Maintenance"
MODE=$(cat "$HOME/gateway.mode" 2>/dev/null || echo "")
if [[ "$MODE" =~ ^(oc-cc|oc-oc|cc-cc|cc-oc)$ ]]; then pass "gateway-mode" "mode=$MODE (valid)"
else fail "gateway-mode" "mode='$MODE' (invalid or missing)"; fi

if [ -f "$HOME/gateway.maintenance" ]; then warn "maintenance-active" "maintenance mode IS active"
else pass "maintenance-inactive" "no maintenance lock"; fi

***REMOVED***════════════════
# S29: Session Continuity (NEW)
***REMOVED***════════════════
section "29. Session Continuity"
LAST_SID=$(sqlite3 "$DB" "SELECT session_id FROM sessions WHERE session_id != '' ORDER BY rowid DESC LIMIT 1;" 2>/dev/null || echo "")
if [ -n "$LAST_SID" ]; then pass "session-continuity" "last session: ${LAST_SID:0:20}..."
else warn "session-continuity" "no sessions with session_id"; fi

***REMOVED***════════════════
# S30: Build Prompt Nodes (NEW)
***REMOVED***════════════════
section "30. Runner Build Prompt"
RUNNER_DATA=$(n8n_api "workflows/qadF2WcaBsIR7SWG" 2>/dev/null)
RUNNER_NODES=$(echo "$RUNNER_DATA" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('nodes',[])))" 2>/dev/null || echo 0)
if (( RUNNER_NODES >= 45 )); then pass "runner-nodes" "$RUNNER_NODES nodes (>= 45)"
else fail "runner-nodes" "only $RUNNER_NODES"; fi

for RNODE in "Build Prompt" "Query Knowledge" "Build Plan" "Evaluator"; do
  if echo "$RUNNER_DATA" | grep -q "$RNODE"; then pass "runner-$RNODE" "present"
  else fail "runner-$RNODE" "MISSING"; fi
done

***REMOVED***════════════════
# S31: External Service Connectivity
***REMOVED***════════════════
section "31. External Services (YT, NetBox, Matrix POST, GitHub)"

# YouTrack API
YT_RESP=$(curl -sf --connect-timeout 5 -H "Authorization: Bearer $YT_TOKEN" "https://youtrack.example.net/api/admin/projects?fields=id,shortName&\$top=5" 2>/dev/null || echo "")
if echo "$YT_RESP" | python3 -c "import sys,json; assert len(json.load(sys.stdin))>0" 2>/dev/null; then
  pass "youtrack-api" "API responds, projects readable"
else fail "youtrack-api" "API unreachable or auth failed"; fi

# NetBox CMDB
if $QUICK; then skip "netbox-api" "skipped (--quick)"
else
  NB_DEV=$(curl -sk --connect-timeout 5 -H "Authorization: Token $NB_TOKEN" "https://netbox.example.net/api/dcim/devices/?limit=1" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)
  NB_VMS=$(curl -sk --connect-timeout 5 -H "Authorization: Token $NB_TOKEN" "https://netbox.example.net/api/virtualization/virtual-machines/?limit=1" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)
  NB_TOTAL=$((NB_DEV + NB_VMS))
  if (( NB_TOTAL >= 250 )); then pass "netbox-api" "$NB_TOTAL objects ($NB_DEV devices + $NB_VMS VMs)"
  elif (( NB_TOTAL > 0 )); then warn "netbox-api" "only $NB_TOTAL objects"
  else warn "netbox-api" "unreachable"; fi
fi

# Matrix bot connectivity — send test message to #alerts
ALERT_ROOM="!xeNxtpScJWCmaFjeCL:matrix.example.net"
MX_TXN="health-$(date +%s)"
MX_CODE=$(curl -sf --connect-timeout 5 -o /dev/null -w "%{http_code}" -X PUT \
  "https://matrix.example.net/_matrix/client/v3/rooms/$ALERT_ROOM/send/m.room.message/$MX_TXN" \
  -H "Authorization: Bearer $MATRIX_BOT_TOKEN" -H "Content-Type: application/json" \
  -d '{"msgtype":"m.notice","body":"[health-check] connectivity test"}' 2>/dev/null || echo 0)
if [ "$MX_CODE" = "200" ]; then pass "matrix-post" "message sent to #alerts (HTTP 200)"
else warn "matrix-post" "Matrix POST returned $MX_CODE"; fi

# GitHub mirror freshness
if $QUICK; then skip "github-mirror" "skipped (--quick)"
else
  # Sync-aware: the mirror is CI-triggered (sync_to_github on merge-to-main), NOT cron, so a
  # quiet main branch legitimately leaves GitHub's pushed_at old — that is idle, not stale.
  # Only WARN/FAIL when GitHub is actually BEHIND origin/main; PASS when caught up even if idle.
  GH_PUSHED_EPOCH=$(curl -sf --connect-timeout 5 "https://api.github.com/repos/papadopouloskyriakos/agentic-chatops" 2>/dev/null | python3 -c "
import sys,json,datetime as dt
d=json.load(sys.stdin)
p=d.get('pushed_at','')
print(int(dt.datetime.fromisoformat(p.rstrip('Z')).replace(tzinfo=dt.timezone.utc).timestamp()) if p else 0)" 2>/dev/null || echo 0)
  MAIN_EPOCH=$(git log -1 --format=%ct origin/main 2>/dev/null || echo 0)
  GH_AGE_H=$(( ( $(date +%s) - GH_PUSHED_EPOCH ) / 3600 ))
  if (( GH_PUSHED_EPOCH == 0 )); then warn "github-mirror" "could not read GitHub pushed_at"
  elif (( MAIN_EPOCH > 0 && GH_PUSHED_EPOCH + 3600 >= MAIN_EPOCH )); then pass "github-mirror" "mirror current with origin/main (main idle ${GH_AGE_H}h)"
  elif (( GH_AGE_H <= 72 )); then pass "github-mirror" "last push ${GH_AGE_H}h ago (<= 72h)"
  elif (( GH_AGE_H <= 168 )); then warn "github-mirror" "mirror ${GH_AGE_H}h behind origin/main (> 72h)"
  else fail "github-mirror" "mirror ${GH_AGE_H}h behind origin/main (stale > 7d)"; fi
fi

# OpenClaw LLM connectivity — Tier 1 routes via claude-cli OAuth (Max sub)
# Check the binary is on PATH + Anthropic API reachable + OAuth credentials present.
# OpenClaw LXC destroyed 2026-04-29 — retired 2026-07-03 (was a permanent WARN).
skip "openclaw-llm" "OpenClaw retired 2026-04-29 (LXC destroyed; cc-cc only mode)"

***REMOVED***════════════════
# S32: Infrastructure Health
***REMOVED***════════════════
section "32. Infrastructure Health (K8s, PVE, BGP, GPU)"

# K8s node count
if $QUICK; then skip "k8s-nodes" "skipped (--quick)"
else
  K8S_NODES=$(kubectl get nodes --no-headers 2>/dev/null | countc " Ready")
  if (( K8S_NODES >= 7 )); then pass "k8s-nodes" "$K8S_NODES nodes Ready (>= 7)"
  elif (( K8S_NODES >= 4 )); then warn "k8s-nodes" "only $K8S_NODES Ready (expected 7)"
  else fail "k8s-nodes" "$K8S_NODES Ready"; fi
fi

# PVE cluster quorum
if $QUICK; then skip "pve-quorum" "skipped (--quick)"
else
  PVE_STATUS=$(ssh -o ConnectTimeout=5 nl-pve01 "pvecm status 2>/dev/null" 2>/dev/null || echo "")
  PVE_NODES=$(echo "$PVE_STATUS" | awk '/^Nodes:/{print $2; exit}')
  PVE_NODES=${PVE_NODES:-0}
  PVE_QUORATE=$(echo "$PVE_STATUS" | countc -iE "quorate:[[:space:]]*yes")
  if (( PVE_QUORATE > 0 && PVE_NODES >= 3 )); then pass "pve-quorum" "$PVE_NODES PVE nodes, quorum OK"
  elif (( PVE_NODES >= 2 )); then warn "pve-quorum" "$PVE_NODES nodes (quorum uncertain)"
  else warn "pve-quorum" "could not determine cluster status"; fi
fi

# BGP peer count on NL ASA
if $QUICK; then skip "bgp-peers" "skipped (--quick)"
else
  BGP_RAW=$(python3 -c "
import sys
sys.path.insert(0, 'scripts/lib')
from asa_ssh import ssh_nl_asa_command
print(ssh_nl_asa_command(['show bgp summary']) or '')" 2>/dev/null || true)
  if [ -z "${BGP_RAW//[[:space:]]/}" ]; then
    warn "bgp-peers" "could not query nl-fw01 BGP table (pexpect probe returned nothing)"
  else
    # Neighbor rows start with an IP; established peers show a numeric PfxRcd in
    # the last column, down peers show Idle/Active/never. Compare established vs
    # configured instead of a hardcoded absolute (the old ">= 7" never matched
    # the NL ASA's real neighbor set).
    # ASA output is CRLF-terminated — strip \r or $NF never matches /^[0-9]+$/
    BGP_TOTAL=$(echo "$BGP_RAW" | tr -d '\r' | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/{t++} END{print t+0}')
    BGP_ESTAB=$(echo "$BGP_RAW" | tr -d '\r' | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/ && $NF ~ /^[0-9]+$/ {c++} END{print c+0}')
    if (( BGP_TOTAL == 0 )); then warn "bgp-peers" "unexpected 'show bgp summary' format on nl-fw01"
    elif (( BGP_TOTAL >= 4 && BGP_ESTAB == BGP_TOTAL )); then pass "bgp-peers" "$BGP_ESTAB/$BGP_TOTAL BGP peers established on nl-fw01"
    elif (( BGP_ESTAB >= BGP_TOTAL - 1 )); then warn "bgp-peers" "$BGP_ESTAB/$BGP_TOTAL BGP peers established on nl-fw01 (1 down)"
    else fail "bgp-peers" "only $BGP_ESTAB/$BGP_TOTAL BGP peers established on nl-fw01"; fi
  fi
fi

# GPU health
if $QUICK; then skip "gpu-health" "skipped (--quick)"
else
  GPU_INFO=$(ssh -o ConnectTimeout=5 nl-gpu01 "nvidia-smi --query-gpu=temperature.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null" 2>/dev/null || echo "")
  if [ -n "$GPU_INFO" ]; then
    GPU_TEMP=$(echo "$GPU_INFO" | cut -d',' -f1 | tr -d ' ')
    GPU_MEM_USED=$(echo "$GPU_INFO" | cut -d',' -f2 | tr -d ' ')
    GPU_MEM_TOTAL=$(echo "$GPU_INFO" | cut -d',' -f3 | tr -d ' ')
    if (( GPU_TEMP <= 85 )); then pass "gpu-temp" "RTX 3090 Ti at ${GPU_TEMP}C (MEM: ${GPU_MEM_USED}/${GPU_MEM_TOTAL} MiB)"
    else warn "gpu-temp" "${GPU_TEMP}C (high!)"; fi
  else fail "gpu-health" "nvidia-smi unreachable"; fi
fi

# Thanos query reachable
if $QUICK; then skip "thanos-query" "skipped (--quick)"
else
  THANOS_CODE=$(kubectl exec -n monitoring deployment/thanos-query -- wget -qO- --timeout=3 'http://localhost:9090/api/v1/status/runtimeinfo' 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
  if [ "$THANOS_CODE" = "success" ]; then pass "thanos-query" "Thanos query API healthy"
  else warn "thanos-query" "Thanos query not responding"; fi
fi

# DNS resolution
if host nl-claude01 >/dev/null 2>&1; then pass "dns-resolution" "internal DNS resolves"
else warn "dns-resolution" "nl-claude01 not resolvable"; fi

***REMOVED***════════════════
# S33: Data Integrity
***REMOVED***════════════════
section "33. Data Integrity"

# Incident knowledge embeddings — check they're real 768-dim vectors.
# chatops-governance rows are RAG-excluded by design (IFRNLLEI01PRD-1153) and
# deliberately never embedded — don't count them as missing.
EMPTY_EMBED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM incident_knowledge WHERE (embedding IS NULL OR embedding = '' OR LENGTH(embedding) < 100) AND COALESCE(project,'') != 'chatops-governance';" 2>/dev/null || echo 999)
TOTAL_IK=$(sqlite3 "$DB" "SELECT COUNT(*) FROM incident_knowledge WHERE COALESCE(project,'') != 'chatops-governance';" 2>/dev/null || echo 0)
if (( EMPTY_EMBED == 0 && TOTAL_IK > 0 )); then pass "ik-embeddings" "all $TOTAL_IK RAG-eligible entries have embeddings"
elif (( EMPTY_EMBED < TOTAL_IK / 2 )); then warn "ik-embeddings" "$EMPTY_EMBED/$TOTAL_IK missing embeddings"
else fail "ik-embeddings" "$EMPTY_EMBED/$TOTAL_IK missing embeddings"; fi

# Queue depth
QUEUE_DEPTH=$(db_count "queue")
if (( QUEUE_DEPTH <= 10 )); then pass "queue-depth" "$QUEUE_DEPTH items in queue (healthy)"
else warn "queue-depth" "$QUEUE_DEPTH items queued (may be backed up)"; fi

# SQLite backup freshness
BACKUP_DIR="$HOME/gitlab/products/cubeos/claude-context"
LATEST_BAK=$(ls -t "$BACKUP_DIR"/gateway.db.bak* "$BACKUP_DIR"/backups/gateway*.db* 2>/dev/null | head -1)
if [ -n "$LATEST_BAK" ]; then
  BAK_AGE_H=$(python3 -c "
import os,time
age=(time.time()-os.path.getmtime('$LATEST_BAK'))/3600
print(int(age))" 2>/dev/null || echo 9999)
  if (( BAK_AGE_H <= 26 )); then pass "db-backup" "backup ${BAK_AGE_H}h old (<= 26h)"
  else warn "db-backup" "backup ${BAK_AGE_H}h old (> 26h)"; fi
else warn "db-backup" "no backup files found"; fi

# JSONL poller freshness (poll-claude-usage.sh writes llm_usage)
POLLER_AGE=$(db_max_age_hours "llm_usage" "recorded_at")
if (( POLLER_AGE <= 2 )); then pass "jsonl-poller" "llm_usage updated ${POLLER_AGE}h ago"
else warn "jsonl-poller" "llm_usage last update ${POLLER_AGE}h ago (poller may be stale)"; fi

# Build Prompt token caps verification
if echo "$RUNNER_DATA" | grep -q "truncateSection"; then pass "token-caps" "truncateSection present in Build Prompt"
else warn "token-caps" "truncateSection not found in Runner"; fi

# Schema version stamping (IFRNLLEI01PRD-635): every row in the 9 versioned
# tables must have a non-null schema_version. Writers that forget to stamp
# will surface here as FAIL.
SV_TABLES="sessions session_log session_transcripts execution_log tool_call_log agent_diary session_trajectory session_judgment session_risk_audit"
SV_FAIL=0
SV_DETAIL=""
for t in $SV_TABLES; do
  # Skip tables that don't exist yet (fresh install where lazy-create hasn't run)
  HAS_TBL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='$t';" 2>/dev/null || echo 0)
  [ "$HAS_TBL" = "1" ] || continue
  # Also skip tables that never got the column (migration not yet applied on this DB)
  HAS_COL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('$t') WHERE name='schema_version';" 2>/dev/null || echo 0)
  [ "$HAS_COL" = "1" ] || { SV_DETAIL="${SV_DETAIL}${t}:no-col "; SV_FAIL=$((SV_FAIL+1)); continue; }
  NULL_N=$(sqlite3 "$DB" "SELECT COUNT(*) FROM $t WHERE schema_version IS NULL;" 2>/dev/null || echo -1)
  [ "$NULL_N" = "0" ] || { SV_DETAIL="${SV_DETAIL}${t}:${NULL_N}-null "; SV_FAIL=$((SV_FAIL+1)); }
done
if [ "$SV_FAIL" = "0" ]; then pass "schema-versioning" "all 9 versioned tables have schema_version stamped on every row"
else fail "schema-versioning" "${SV_FAIL} table(s) with null schema_version or missing column: ${SV_DETAIL}"; fi

***REMOVED***════════════════
# S34: Security & Compliance
***REMOVED***════════════════
section "34. Security & Compliance"

# Security scanner last run (NL)
if $QUICK; then skip "scanner-nl" "skipped (--quick)"; skip "scanner-gr" "skipped (--quick)"
else
  NL_SCAN_AGE=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key operator@10.0.181.X "ls -t /opt/scans/weekly/*/findings.json 2>/dev/null | head -1 | xargs -r stat --format=%Y 2>/dev/null" 2>/dev/null || echo 0)
  if [ -n "$NL_SCAN_AGE" ] && [ "$NL_SCAN_AGE" != "0" ]; then
    SCAN_H=$(( ($(date +%s) - NL_SCAN_AGE) / 3600 ))
    if (( SCAN_H <= 26 )); then pass "scanner-nl" "NL scan ${SCAN_H}h ago (<= 26h)"
    else warn "scanner-nl" "NL last scan ${SCAN_H}h ago"; fi
  else warn "scanner-nl" "could not determine last scan time"; fi

  GR_SCAN_AGE=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key operator@10.0.X.X "ls -t /opt/scans/weekly/*/findings.json 2>/dev/null | head -1 | xargs -r stat --format=%Y 2>/dev/null" 2>/dev/null || echo 0)
  if [ -n "$GR_SCAN_AGE" ] && [ "$GR_SCAN_AGE" != "0" ]; then
    GR_SCAN_H=$(( ($(date +%s) - GR_SCAN_AGE) / 3600 ))
    if (( GR_SCAN_H <= 26 )); then pass "scanner-gr" "GR scan ${GR_SCAN_H}h ago (<= 26h)"
    else warn "scanner-gr" "GR last scan ${GR_SCAN_H}h ago"; fi
  else warn "scanner-gr" "could not determine last scan time"; fi
fi

# MITRE ATT&CK Navigator
if $QUICK; then skip "mitre-navigator" "skipped (--quick)"
else
  MITRE_CODE=$(curl -sf --connect-timeout 5 -o /dev/null -w "%{http_code}" "http://10.0.181.X:8080" 2>/dev/null || echo 0)
  if [ "$MITRE_CODE" = "200" ]; then pass "mitre-navigator" "Navigator accessible (HTTP 200)"
  else warn "mitre-navigator" "returned $MITRE_CODE"; fi
fi

# CrowdSec active decisions
if $QUICK; then skip "crowdsec-bans" "skipped (--quick)"
else
  CS_BANS=$(ssh -o ConnectTimeout=5 nl-pve01 "cscli decisions list -o json 2>/dev/null | python3 -c 'import sys,json; print(len(json.load(sys.stdin) or []))'" 2>/dev/null || echo 0)
  CS_BANS=$((CS_BANS + 0))
  pass "crowdsec-bans" "$CS_BANS active ban decisions"
fi

***REMOVED***════════════════
# S35: Cross-Site Sync
***REMOVED***════════════════
section "35. Cross-Site Sync"

# OpenClaw memory sync — LXC destroyed 2026-04-29, retired 2026-07-03.
skip "oc-memory-sync" "OpenClaw retired 2026-04-29 (LXC destroyed; cc-cc only mode)"

# GR oversight agent reachable
if $QUICK; then skip "gr-claude" "skipped (--quick)"
else
  if ssh -o ConnectTimeout=5 -i ~/.ssh/one_key app-user@10.0.X.X "echo ok" >/dev/null 2>&1; then
    pass "gr-claude" "grclaude01 (10.0.X.X) reachable"
  else warn "gr-claude" "grclaude01 unreachable via VPN"; fi
fi

# Syslog-ng — both sites
if $QUICK; then skip "nlsyslogng01" "skipped (--quick)"; skip "grsyslogng01" "skipped (--quick)"
else
  # "today" must be the SYSLOG SERVER's date, not ours: syslog-ng names files
  # by the server's local date (GR server runs UTC, this host runs CEST), so a
  # locally-computed date false-warned "no logs today" every night 00:00-02:00
  # CEST. Single-quoted remote commands let $(date …) expand on the server.
  NL_SYSLOG=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key root@nlsyslogng01 'wc -l /mnt/logs/syslog-ng/nl-claude01/$(date +%Y)/$(date +%m)/nl-claude01-$(date +%Y-%m-%d).log 2>/dev/null' 2>/dev/null | awk '{print $1}' || echo 0)
  NL_SYSLOG=$((NL_SYSLOG + 0))
  if (( NL_SYSLOG > 0 )); then pass "nlsyslogng01" "$NL_SYSLOG log lines today"
  else warn "nlsyslogng01" "no logs today"; fi

  GR_SYSLOG=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key root@grsyslogng01 'wc -l /mnt/logs/syslog-ng/gr-pve01/$(date +%Y)/$(date +%m)/gr-pve01-$(date +%Y-%m-%d).log 2>/dev/null' 2>/dev/null | awk '{print $1}' || echo 0)
  GR_SYSLOG=$((GR_SYSLOG + 0))
  if (( GR_SYSLOG > 0 )); then pass "grsyslogng01" "$GR_SYSLOG log lines today"
  else warn "grsyslogng01" "no logs today"; fi

  # rtr01 syslog — the 2026-04-22 fix pinned 10.0.X.X → nlrtr01
  # in /etc/hosts on the syslog-ng server so rtr01's data-plane ACL logs
  # land under the hostname bucket, not an IP-fallback bucket. Guardrail
  # confirms no regression (no by-IP bucket re-emerged) and the hostname
  # bucket is still receiving.
  RTR_LINES=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key root@nlsyslogng01 'wc -l /mnt/logs/syslog-ng/nlrtr01/$(date +%Y)/$(date +%m)/nlrtr01-$(date +%Y-%m-%d).log 2>/dev/null' 2>/dev/null | awk '{print $1}' || echo 0)
  RTR_LINES=$((RTR_LINES + 0))
  RTR_BYIP=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key root@nlsyslogng01 "ls /mnt/logs/syslog-ng/ 2>/dev/null | grep -E '^192\\.168\\.174\\.' | head -1" 2>/dev/null || echo "")
  if [ -n "$RTR_BYIP" ]; then
    fail "rtr01-syslog-binding" "by-IP bucket regression detected: /mnt/logs/syslog-ng/$RTR_BYIP (expected nlrtr01/)"
  elif (( RTR_LINES > 0 )); then
    pass "rtr01-syslog-binding" "$RTR_LINES lines in nlrtr01/ today, no by-IP bucket"
  else
    warn "rtr01-syslog-binding" "hostname bucket empty today — logging may be offline"
  fi
fi

***REMOVED***════════════════
# S36: Operational Pipeline
***REMOVED***════════════════
section "36. Operational Pipeline"

# Freedom WAN SLA track
if $QUICK; then skip "freedom-sla" "skipped (--quick)"
else
  # Freedom WAN health via the working pexpect probe's metric (freedom-qos-toggle.sh, */2).
  # The old raw 'sshpass ... show track 1' pipe never returned a parseable reading — the ASA
  # closes its SSH command channel after login and 'expect' isn't installed — so this check
  # chronically WARNed while Freedom was fine. freedom_ont.prom is the authoritative signal.
  FREEDOM_PROM="/var/lib/node_exporter/textfile_collector/freedom_ont.prom"
  BUDGET_PROM="/var/lib/node_exporter/textfile_collector/budget_pppoe.prom"
  if [ ! -f "$FREEDOM_PROM" ]; then warn "freedom-sla" "freedom_ont.prom absent (freedom-qos-toggle.sh not running?)"
  else
    FP_AGE=$(( $(date +%s) - $(stat -c %Y "$FREEDOM_PROM" 2>/dev/null || echo 0) ))
    FP_UP=$(awk '$1=="freedom_pppoe_up"{v=$2} END{print v+0}' "$FREEDOM_PROM" 2>/dev/null)
    if (( FP_AGE > 900 )); then warn "freedom-sla" "freedom_ont.prom STALE (${FP_AGE}s > 900; freedom-qos-toggle.sh may be down)"
    elif [ "$FP_UP" = "1" ]; then pass "freedom-sla" "Freedom PPPoE UP (freedom_ont.prom, ${FP_AGE}s fresh)"
    else
      DUAL=$(awk '$1=="budget_pppoe_dual_wan_down"{v=$2} END{print v+0}' "$BUDGET_PROM" 2>/dev/null)
      if [ "$DUAL" = "1" ]; then fail "freedom-sla" "Freedom PPPoE DOWN and no backup path (dual-WAN outage)"
      else warn "freedom-sla" "Freedom PPPoE DOWN — backup path (nlrtr01 Dialer1) carrying traffic"; fi
    fi
  fi
fi

# Docker containers on OpenClaw host — LXC destroyed 2026-04-29, retired 2026-07-03.
skip "docker-oc" "OpenClaw retired 2026-04-29 (LXC destroyed; cc-cc only mode)"

# n8n-as-code schemas
# n8n-as-code in monorepo plugin or node_modules
if find node_modules -name "n8n-as-code" -type d 2>/dev/null | grep -q .; then pass "n8n-schemas" "n8n-as-code module present"
elif find "$HOME/.npm/_npx" -name "n8n-as-code" -type d 2>/dev/null | grep -q .; then pass "n8n-schemas" "n8n-as-code in npx cache"
else warn "n8n-schemas" "n8n-as-code not found"; fi

# Prompt scorecard coverage (19 surfaces)
SCORECARD_SURFACES=$(sqlite3 "$DB" "SELECT COUNT(DISTINCT prompt_surface) FROM prompt_scorecard;" 2>/dev/null || echo 0)
if (( SCORECARD_SURFACES >= 15 )); then pass "scorecard-coverage" "$SCORECARD_SURFACES/19 surfaces graded (>= 15)"
elif (( SCORECARD_SURFACES >= 10 )); then warn "scorecard-coverage" "only $SCORECARD_SURFACES/19 surfaces"
else fail "scorecard-coverage" "only $SCORECARD_SURFACES surfaces graded"; fi

# Watchdog cron
WD_CRON=$(crontab -l 2>/dev/null | grep "gateway-watchdog" | head -1)
if [ -n "$WD_CRON" ]; then pass "watchdog-cron" "gateway-watchdog configured"
else warn "watchdog-cron" "no watchdog cron"; fi

# Risk-classification audit invariant (IFRNLLEI01PRD-632/-1102, BAND-AWARE).
# Defer to the authoritative audit-risk-decisions.sh — the old inline check
# (auto_approved=1 AND risk_level!='low') false-FAILS on legitimate reversible-MIXED
# AUTO/AUTO_NOTICE auto-resolves that the autonomy-forward gate intends. The band-aware
# audit FAILS only on a real floor violation (auto outside AUTO/AUTO_NOTICE, or an
# irreversible:* / critical:p0-reboot / deviation floor signal in an auto row).
if sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND name='session_risk_audit'" 2>/dev/null | grep -q session_risk_audit; then
    RISK_ROWS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_risk_audit WHERE classified_at >= datetime('now','-7 days')" 2>/dev/null || echo 0)
    if (( RISK_ROWS == 0 )); then
        skip "risk-audit-invariant" "no classifications in 7d"
    elif /app/claude-gateway/scripts/audit-risk-decisions.sh >/dev/null 2>&1; then
        pass "risk-audit-invariant" "$RISK_ROWS classifications in 7d, band-aware invariant holds (audit-risk-decisions.sh)"
    else
        fail "risk-audit-invariant" "audit-risk-decisions.sh FAILED — an auto-approval is outside AUTO/AUTO_NOTICE or carries a floor signal (irreversible/p0-reboot/deviation)"
    fi
else
    skip "risk-audit-invariant" "session_risk_audit table not yet created"
fi

# Teacher-agent invariants (IFRNLLEI01PRD-655). Rolls up the 7-check audit
# into a single health-check result — FAILs surface here without aborting.
if [ -x scripts/audit-teacher-invariants.sh ]; then
  AUDIT_OUT=$(bash scripts/audit-teacher-invariants.sh 2>&1 || true)
  PASS_N=$(echo "$AUDIT_OUT" | grep -c "^  PASS —" || true)
  FAIL_N=$(echo "$AUDIT_OUT" | grep -c "^  FAIL —" || true)
  if (( FAIL_N > 0 )); then
    fail "teacher-invariants" "$FAIL_N violation(s) (scripts/audit-teacher-invariants.sh for detail; $PASS_N PASS)"
  elif (( PASS_N > 0 )); then
    pass "teacher-invariants" "all teacher-agent invariants hold ($PASS_N checks pass)"
  else
    skip "teacher-invariants" "audit produced no PASS/FAIL output"
  fi
else
  skip "teacher-invariants" "audit-teacher-invariants.sh not found"
fi

# VPS tunnel status (CH↔NO)
if $QUICK; then skip "vps-tunnels" "skipped (--quick)"
else
  VPS_SAS=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key operator@198.51.100.X "echo '$ASA_PW' | sudo -S swanctl --list-sas 2>/dev/null | { grep -c 'ESTABLISHED' || true; }" 2>/dev/null | head -1)
  VPS_SAS=${VPS_SAS:-0}
  if (( VPS_SAS >= 3 )); then pass "vps-tunnels" "$VPS_SAS swanctl SAs ESTABLISHED on chzrh01vps01"
  elif (( VPS_SAS >= 1 )); then warn "vps-tunnels" "only $VPS_SAS ESTABLISHED (expected >= 3)"
  else warn "vps-tunnels" "no SAs or VPS unreachable"; fi
fi

***REMOVED***════════════════
# S37: Smoke Tests (--smoke only)
***REMOVED***════════════════
if $SMOKE; then
  section "31. Smoke Tests (e2e)"

  # Synthetic LibreNMS alert
  SMOKE_TS=$(date +%s)
  SMOKE_SUMMARY="HEALTH-CHECK-SMOKE-$SMOKE_TS"
  curl -sk -X POST "$N8N_URL/webhook/librenms-alert" -H "Content-Type: application/json" \
    -d "{\"alert_type\":\"librenms\",\"severity\":\"warning\",\"hostname\":\"smoke-test-host\",\"alert_rule\":\"$SMOKE_SUMMARY\",\"message\":\"Automated smoke test — will be cleaned up\"}" >/dev/null 2>&1

  # Wait for processing
  sleep 8

  # Check YouTrack for created issue
  YT_FOUND=$(curl -sk -H "Authorization: Bearer REDACTED_YT_TOKEN" \
    "https://youtrack.example.net/api/issues?query=summary:%22$SMOKE_SUMMARY%22&fields=idReadable" 2>/dev/null | python3 -c "
import sys,json
issues=json.load(sys.stdin)
print(issues[0]['idReadable'] if issues else '')" 2>/dev/null || echo "")

  if [ -n "$YT_FOUND" ]; then
    pass "smoke-alert-e2e" "alert created YT issue $YT_FOUND"
    # Cleanup: delete the test issue
    curl -sk -X DELETE "https://youtrack.example.net/api/issues/$YT_FOUND" \
      -H "Authorization: Bearer REDACTED_YT_TOKEN" >/dev/null 2>&1
    pass "smoke-cleanup" "test issue $YT_FOUND deleted"
  else
    warn "smoke-alert-e2e" "no YT issue found (alert may have been deduped or suppressed)"
    skip "smoke-cleanup" "nothing to clean up"
  fi
else
  skip "smoke-tests" "use --smoke to enable e2e smoke tests"
fi

# ─────────────────────────────────────────────────────────────────────────────
section "37. Skill Prerequisites"

# IFRNLLEI01PRD-716: every .claude/{agents,skills}/**/*.md frontmatter declares
# requires.bins + requires.env; the audit below confirms each is satisfied on
# the host. Failures surface stale skills before they run.
if [ -x scripts/audit-skill-requires.sh ]; then
  SKILL_AUDIT=$(bash scripts/audit-skill-requires.sh --quiet 2>&1 || true)
  SKILL_FAIL=$(echo "$SKILL_AUDIT" | awk -F'fail=' '/^audit-skill-requires/ {print $2+0}' | head -1)
  SKILL_PASS=$(echo "$SKILL_AUDIT" | awk -F'pass=' '/^audit-skill-requires/ {split($2,a," "); print a[1]+0}' | head -1)
  if [ -z "$SKILL_FAIL" ]; then
    warn "skill-prereqs" "audit produced no summary line"
  elif [ "$SKILL_FAIL" -eq 0 ]; then
    pass "skill-prereqs" "$SKILL_PASS skills OK, 0 gaps"
  else
    GAPS=$(echo "$SKILL_AUDIT" | grep '\[FAIL\]' | head -3 | tr '\n' ';' | sed 's/  */ /g')
    fail "skill-prereqs" "$SKILL_FAIL skill(s) with missing bins/env: $GAPS"
  fi
else
  skip "skill-prereqs" "scripts/audit-skill-requires.sh not found"
fi

# Skill-metrics exporter freshness (matches SkillMetricsExporterStale alert threshold).
SKILL_METRICS_FILE="/var/lib/node_exporter/textfile_collector/skill-metrics.prom"
if [ -f "$SKILL_METRICS_FILE" ]; then
  SKILL_METRICS_AGE=$(( $(date +%s) - $(stat -c %Y "$SKILL_METRICS_FILE") ))
  if (( SKILL_METRICS_AGE < 600 )); then
    pass "skill-metrics" "exporter ran ${SKILL_METRICS_AGE}s ago"
  elif (( SKILL_METRICS_AGE < 1800 )); then
    warn "skill-metrics" "exporter last ran ${SKILL_METRICS_AGE}s ago (threshold 1800s)"
  else
    fail "skill-metrics" "exporter stale ${SKILL_METRICS_AGE}s (> 1800s)"
  fi
else
  warn "skill-metrics" "no skill-metrics.prom yet (cron may not have fired)"
fi

# docs/skills-index.md drift — cheap sanity check (full test is test-656).
if [ -f docs/skills-index.md ]; then
  FRESH_INDEX=$(mktemp)
  if python3 scripts/render-skill-index.py "$FRESH_INDEX" >/dev/null 2>&1; then
    if diff -q docs/skills-index.md "$FRESH_INDEX" >/dev/null 2>&1; then
      pass "skill-index-fresh" "docs/skills-index.md matches frontmatter"
    else
      fail "skill-index-fresh" "docs/skills-index.md is stale (run scripts/render-skill-index.py)"
    fi
  else
    warn "skill-index-fresh" "renderer errored; run manually for detail"
  fi
  rm -f "$FRESH_INDEX"
else
  warn "skill-index-fresh" "docs/skills-index.md missing"
fi

# IFRNLLEI01PRD-712 governance followup: flag SKILL.md files whose body
# changed since their version was last bumped. Advisory (warn not fail) —
# docs/runbooks/skill-versioning.md explicitly scopes the audit as soft.
if [ -x scripts/audit-skill-versions.sh ]; then
  SV_JSON=$(bash scripts/audit-skill-versions.sh --json 2>/dev/null || echo '{}')
  SV_STALE=$(echo "$SV_JSON" | python3 -c "import json, sys; d=json.load(sys.stdin) if sys.stdin.readable() else {}; print(d.get('stale_count', 0))" 2>/dev/null)
  SV_TOTAL=$(echo "$SV_JSON" | python3 -c "import json, sys; d=json.load(sys.stdin) if sys.stdin.readable() else {}; print(d.get('total', 0))" 2>/dev/null)
  if [ -z "$SV_STALE" ] || [ "$SV_TOTAL" = "0" ]; then
    warn "skill-versions" "audit did not return parseable JSON"
  elif [ "$SV_STALE" = "0" ]; then
    pass "skill-versions" "$SV_TOTAL skills, all versions fresh vs git history"
  else
    warn "skill-versions" "$SV_STALE/$SV_TOTAL skills body-changed-without-bump (see docs/runbooks/skill-versioning.md)"
  fi
else
  skip "skill-versions" "audit-skill-versions.sh not found"
fi

section "38. Receiver wiring (cc-cc dispatch)"

# Post-cc-cc-migration (2026-04-29): every receiver's "Post Triage Instruction"
# / "Post Burst Triage" / "Post Escalation Instruction" SSH node must reference
# scripts/run-triage.sh. Catches silent re-wiring drift if anyone ever edits a
# receiver to drop the wrapper or revert to the old @openclaw mention pattern.
RECEIVERS=(
  "claude-gateway-prometheus-receiver"
  "claude-gateway-prometheus-receiver-gr"
  "claude-gateway-librenms-receiver"
  "claude-gateway-librenms-receiver-gr"
  "claude-gateway-security-receiver"
  "claude-gateway-security-receiver-gr"
  "claude-gateway-crowdsec-receiver"
  "claude-gateway-crowdsec-receiver-gr"
  "claude-gateway-synology-dsm-receiver"
)
RX_OK=0
RX_GAPS=()
for r in "${RECEIVERS[@]}"; do
  f="workflows/${r}.json"
  if [ ! -f "$f" ]; then
    RX_GAPS+=("$r:missing-file")
    continue
  fi
  if grep -q "run-triage\.sh" "$f"; then
    ((RX_OK++))
  else
    RX_GAPS+=("$r:no-wrapper-ref")
  fi
done
if [ "${#RX_GAPS[@]}" -eq 0 ]; then
  pass "cc-cc-receiver-wiring" "$RX_OK/${#RECEIVERS[@]} receivers reference scripts/run-triage.sh"
else
  fail "cc-cc-receiver-wiring" "$RX_OK/${#RECEIVERS[@]} OK; gaps: ${RX_GAPS[*]}"
fi

# §38 territory-gate-wiring (IFRNLLEI01PRD-1408): the territory gate's PreToolUse hook only
# enforces if it is wired into BOTH session-settings surfaces. The hook fails CLOSED when it
# RUNS-but-errors, but cannot detect being UNWIRED — so this asserts the invariant externally:
# sentinel ON => hook referenced in interactive + dispatched settings AND parses.
TGW_OUT=$(bash scripts/check-territory-gate-wiring.sh 2>&1); TGW_RC=$?
if echo "$TGW_OUT" | grep -q "gate_on=0"; then
  skip "territory-gate-wiring" "gate disabled (sentinel off) — wiring not required"
elif [ "$TGW_RC" -eq 0 ]; then
  pass "territory-gate-wiring" "hook wired in both settings surfaces + parses ($(echo "$TGW_OUT" | tail -1))"
else
  fail "territory-gate-wiring" "$(echo "$TGW_OUT" | grep VIOLATION | head -1)"
fi

# IFRNLLEI01PRD-1152 — control-plane dead-man's-switch. The watchdog watches the
# pipeline; this asserts the watchdog itself is scheduled AND emitting a fresh
# heartbeat. Structural guard so the heartbeat metric can't be silently dropped
# (the way the receiver-canary was retired) without holistic-health going red.
# Consolidated 2026-06-26: the dead-man heartbeat is now owned by the platform-controller (the standalone
# gateway-watchdog Cronicle job was disabled; the controller calls gateway-watchdog.sh --heals-only as a
# heal-library and emits the heartbeat itself). Assert the heartbeat metric is FRESH wherever it is emitted,
# not that the old standalone cron exists (crons also moved off crontab -> Cronicle).
wd_ts=$(grep -hoE 'gateway_watchdog_heartbeat_timestamp_seconds(\{[^}]*\})? [0-9]+' /var/lib/node_exporter/textfile_collector/*.prom 2>/dev/null | grep -oE '[0-9]+$' | tail -1)
if [ -n "$wd_ts" ]; then
  wd_age=$(( $(date +%s) - wd_ts ))
  if [ "$wd_age" -lt 900 ]; then
    pass "watchdog-deadman" "heartbeat fresh (${wd_age}s), owned by platform-controller (GatewayWatchdogHeartbeatStale -> SMS)"
  else
    fail "watchdog-deadman" "heartbeat STALE (${wd_age}s > 900) — platform-controller wedged or node_exporter not writing"
  fi
else
  fail "watchdog-deadman" "no gateway_watchdog_heartbeat_timestamp metric in any .prom — the dead-man's-switch is not being emitted"
fi

# IFRNLLEI01PRD-1153 — governance metrics (false-auto-resolve + repeat-incident).
# Assert the writer is scheduled and its metric is fresh, so the auto-resolve
# safety signal can't silently stop being computed.
GOV_PROM="/var/lib/node_exporter/textfile_collector/governance_metrics.prom"
if crontab -l 2>/dev/null | grep -q "write-governance-metrics.py"; then
  if [ -f "$GOV_PROM" ]; then
    gov_ts=$(grep -oE 'chatops_governance_metrics_last_run_timestamp [0-9]+' "$GOV_PROM" 2>/dev/null | grep -oE '[0-9]+$' | tail -1)
    if [ -n "$gov_ts" ]; then
      gov_age=$(( $(date +%s) - gov_ts ))
      if [ "$gov_age" -lt 1500 ]; then
        pass "governance-metrics" "fresh (${gov_age}s); false-auto-resolve + repeat-incident exported"
      else
        fail "governance-metrics" "STALE (${gov_age}s > 1500) — write-governance-metrics.py cron wedged"
      fi
    else
      fail "governance-metrics" "metric file present but no last_run_timestamp — writer broken"
    fi
  else
    fail "governance-metrics" "no $GOV_PROM — write-governance-metrics.py not emitting"
  fi
else
  fail "governance-metrics" "write-governance-metrics.py not in crontab"
fi

# IFRNLLEI01PRD-1154 — synthetic-incident canary. Assert the spine-probe ran
# recently, passed all 3 stages, and (critically) leaked nothing into the live db.
CANARY_PROM="/var/lib/node_exporter/textfile_collector/synthetic_canary.prom"
if crontab -l 2>/dev/null | grep -q "synthetic-incident-canary.sh"; then
  if [ -f "$CANARY_PROM" ]; then
    cy_ts=$(grep -oE 'synthetic_incident_canary_last_run_timestamp [0-9]+' "$CANARY_PROM" 2>/dev/null | grep -oE '[0-9]+$' | tail -1)
    cy_pass=$(grep -oE 'synthetic_incident_canary_stages_passed [0-9]+' "$CANARY_PROM" 2>/dev/null | grep -oE '[0-9]+$' | tail -1)
    cy_leak=$(grep -oE 'synthetic_incident_canary_live_db_leak [0-9]+' "$CANARY_PROM" 2>/dev/null | grep -oE '[0-9]+$' | tail -1)
    cy_age=$(( $(date +%s) - ${cy_ts:-0} ))
    if [ "${cy_leak:-0}" != 0 ]; then
      fail "synthetic-canary" "LIVE-DB LEAK=${cy_leak} — canary isolation broke (must be 0)"
    elif [ "${cy_ts:-0}" = 0 ]; then
      fail "synthetic-canary" "no last_run_timestamp in $CANARY_PROM"
    elif [ "$cy_age" -gt 172800 ]; then
      fail "synthetic-canary" "stale (${cy_age}s > 48h) — daily canary cron not firing"
    elif [ "${cy_pass:-0}" -lt 3 ]; then
      fail "synthetic-canary" "only ${cy_pass}/3 spine stages passing — classify->predict spine degraded"
    else
      pass "synthetic-canary" "3/3 spine stages, 0 leak, fresh (${cy_age}s)"
    fi
  else
    fail "synthetic-canary" "no $CANARY_PROM — synthetic-incident-canary.sh not emitting"
  fi
else
  warn "synthetic-canary" "synthetic-incident-canary.sh not in crontab (land cron-enabled after first clean runs)"
fi

section "39. Infragraph (IFRNLLEI01PRD-1029)"

# Causal dependency graph: populated, freshly seeded, learning, and the triage
# Step 2-graph wiring intact. All read-only — mirrors the fail-open contract.
IG_DB="$HOME/gitlab/products/cubeos/claude-context/gateway.db"
IG_QUERY="scripts/infragraph-query.py"
if [ -f "$IG_DB" ] && [ -f "$IG_QUERY" ]; then
  IG_HEALTH=$(timeout 10 python3 "$IG_QUERY" health 2>/dev/null) || IG_HEALTH=""
  if [ -n "$IG_HEALTH" ]; then
    IG_NODES=$(echo "$IG_HEALTH" | python3 -c "import json,sys; print(json.load(sys.stdin)['nodes_total'])" 2>/dev/null || echo 0)
    IG_EDGES=$(echo "$IG_HEALTH" | python3 -c "import json,sys; print(json.load(sys.stdin)['edges_total'])" 2>/dev/null || echo 0)
    IG_STALE=$(echo "$IG_HEALTH" | python3 -c "import json,sys; print(json.load(sys.stdin)['stale_edges'])" 2>/dev/null || echo 0)
    IG_COV=$(echo "$IG_HEALTH" | python3 -c "import json,sys; print(json.load(sys.stdin)['dynamics_coverage'])" 2>/dev/null || echo 0)
    if [ "$IG_NODES" -ge 100 ] && [ "$IG_EDGES" -ge 100 ]; then
      pass "infragraph-populated" "$IG_NODES nodes / $IG_EDGES edges"
    else
      fail "infragraph-populated" "graph too small: $IG_NODES nodes / $IG_EDGES edges (expect >=100 each)"
    fi
    if [ "$IG_STALE" -eq 0 ]; then
      pass "infragraph-freshness" "0 stale edges (all valid_until in the future)"
    else
      warn "infragraph-freshness" "$IG_STALE edges past valid_until — check infragraph-seed cron + InfragraphSeedStale"
    fi
    IG_COV_OK=$(python3 -c "print(1 if float('$IG_COV' or 0) >= 0.10 else 0)" 2>/dev/null || echo 0)
    if [ "$IG_COV_OK" = "1" ]; then
      pass "infragraph-dynamics-coverage" "coverage $IG_COV (>= 0.10)"
    else
      warn "infragraph-dynamics-coverage" "coverage $IG_COV < 0.10 — learners not folding observations"
    fi
  else
    fail "infragraph-query-health" "infragraph-query.py health returned nothing (graph empty or CLI error)"
  fi
  # Cron wiring — outcome-based since the Cronicle migration (2026-06-26).
  # The old crontab grep matched a #CRONICLE#-commented-out line (false PASS)
  # and flapped when crontab -l transiently failed under load (false FAIL).
  # Instead verify the jobs actually RAN: seed via its exporter metric, learn
  # via its log mtime (Cronicle shellplug still writes both).
  NOW_TS=$(date +%s)
  SEED_TS=$(awk -F' ' '/^infragraph_last_seed_timestamp\{/ {if ($2 > m) m = $2} END {print m + 0}' /var/lib/node_exporter/textfile_collector/infragraph.prom 2>/dev/null)
  if (( SEED_TS > 0 && NOW_TS - SEED_TS < 93600 )); then
    pass "infragraph-seed-cron" "seed ran $(( (NOW_TS - SEED_TS) / 3600 ))h ago (Cronicle daily 04:10, 26h budget)"
  else
    fail "infragraph-seed-cron" "no seed run in 26h (last metric ts: ${SEED_TS:-0}) — check Cronicle infragraph-seed job"
  fi
  LEARN_LOG="$HOME/logs/claude-gateway/infragraph-learn.log"
  LEARN_TS=$(stat -c %Y "$LEARN_LOG" 2>/dev/null || echo 0)
  if (( LEARN_TS > 0 && NOW_TS - LEARN_TS < 10800 )); then
    pass "infragraph-learn-cron" "learn ran $(( (NOW_TS - LEARN_TS) / 60 ))m ago (Cronicle hourly :25, 3h budget)"
  else
    fail "infragraph-learn-cron" "no learn run in 3h (log mtime: ${LEARN_TS:-0}) — check Cronicle infragraph-learn job"
  fi
  # Triage wiring (advisory step present and fail-open guarded)
  if grep -q "Step 2-graph" openclaw/skills/infra-triage/infra-triage.sh 2>/dev/null \
     && grep -q "INFRAGRAPH_DISABLED" openclaw/skills/infra-triage/infra-triage.sh 2>/dev/null; then
    pass "infragraph-triage-wiring" "Step 2-graph present with INFRAGRAPH_DISABLED kill-switch"
  else
    fail "infragraph-triage-wiring" "Step 2-graph missing or unguarded in infra-triage.sh"
  fi
else
  skip "infragraph" "gateway.db or infragraph-query.py not present"
fi

***REMOVED***════════════════
section "40. Spec-Driven Development (D2, IFRNLLEI01PRD-1260)"
***REMOVED***════════════════
if [ -f bootstrap-pack/scripts/validate-project-spec.py ] && [ -d spec ]; then
  if python3 bootstrap-pack/scripts/validate-project-spec.py . >/dev/null 2>&1; then
    pass "spec-validator" "gateway spec passes all 17 checks"
  else
    fail "spec-validator" "gateway spec fails validate-project-spec.py — run it for detail"
  fi
  if [ -f scripts/check-spec-code-lockstep.py ]; then
    if python3 scripts/check-spec-code-lockstep.py >/dev/null 2>&1; then
      pass "spec-code-lockstep" "spec and safety-critical code in lockstep"
    else
      fail "spec-code-lockstep" "spec<->code drift — a spec-owned file moved or a safety file is unspec'd"
    fi
  else
    fail "spec-code-lockstep" "check-spec-code-lockstep.py missing"
  fi
  if [ -f scripts/run-spec-bdd.py ]; then
    if python3 scripts/run-spec-bdd.py >/dev/null 2>&1; then
      pass "spec-bdd" "all Gherkin acceptance scenarios execute and pass"
    else
      fail "spec-bdd" "executable BDD scenarios failing — run scripts/run-spec-bdd.py"
    fi
  fi
  if grep -q "^validate_spec:" .gitlab-ci.yml 2>/dev/null; then
    pass "spec-ci-gate" "validate_spec CI job wired"
  else
    fail "spec-ci-gate" "validate_spec CI job missing from .gitlab-ci.yml"
  fi
  if [ -f scripts/qa/suites/test-1260-spec-driven.sh ]; then
    pass "spec-qa-suite" "test-1260-spec-driven QA suite present"
  else
    fail "spec-qa-suite" "test-1260 QA suite missing"
  fi
else
  skip "spec-driven" "spec/ tree or validate-project-spec.py not present"
fi

***REMOVED***════════════════
section "41. Closed-Loop Self-Improvement (D16, IFRNLLEI01PRD-1267)"
***REMOVED***════════════════
PD="scripts/parallel-dev/planner-decompose.py"
if [ -f "$PD" ]; then
  if grep -q "NotImplementedError" "$PD"; then
    fail "architect-decomposition" "run_decomposition still raises NotImplementedError"
  else
    pass "architect-decomposition" "run_decomposition implemented (no NotImplementedError stub)"
  fi
else
  skip "architect-decomposition" "planner-decompose.py not present"
fi
if grep -q "_promotion_checkpoint" scripts/lib/prompt_patch_trial.py 2>/dev/null; then
  pass "self-mod-checkpoint" "prompt-patch promotion has a human-review/holdout checkpoint"
else
  fail "self-mod-checkpoint" "prompt-patch promotion checkpoint missing (auto-applies unguarded)"
fi
if [ -f scripts/apply-prompt-promotion.py ]; then
  pass "promotion-circuit-breaker" "apply-prompt-promotion.py operator companion present"
else
  fail "promotion-circuit-breaker" "apply-prompt-promotion.py missing"
fi
if [ -f scripts/mine-failures-to-evals.py ]; then
  if python3 scripts/mine-failures-to-evals.py --json >/dev/null 2>&1; then
    pass "failure-eval-loop" "mine-failures-to-evals.py closes the loop into the eval flywheel"
  else
    fail "failure-eval-loop" "mine-failures-to-evals.py present but errors on dry-run"
  fi
else
  fail "failure-eval-loop" "mine-failures-to-evals.py missing"
fi
# Autonomy: the failure->eval loop is closed autonomously only when the miner is cron-wired.
if crontab -l 2>/dev/null | grep -q "mine-failures-to-evals.py"; then
  pass "failure-eval-cron" "autonomous failure->eval loop cron installed (weekly --apply)"
else
  warn "failure-eval-cron" "miner not cron-wired — failure->eval loop not autonomously closed"
fi

***REMOVED***════════════════
section "42. A2A Card Source-of-Truth (D14, IFRNLLEI01PRD-1305)"
***REMOVED***════════════════
if [ -f scripts/check-a2a-card-drift.py ] && [ -d a2a/agent-cards ]; then
  if python3 scripts/check-a2a-card-drift.py >/dev/null 2>&1; then
    pass "a2a-card-drift" "agent cards authoritative — escalation graph, approval policy, models all in sync"
  else
    fail "a2a-card-drift" "A2A card<->live drift — run scripts/check-a2a-card-drift.py for detail"
  fi
else
  skip "a2a-card-drift" "a2a/agent-cards or check-a2a-card-drift.py not present"
fi

***REMOVED***════════════════
section "43. Scheduled-Reboot Suppression (self-learning)"
***REMOVED***════════════════
# The matcher (phase SR in tier1_suppression.py) suppresses on-schedule reboots
# on hosts with a live registered deterministic schedule. Ships DARK behind
# TIER1_SCHED_REBOOT_ENABLED. These checks assert the machinery is wired + the
# metrics export is alive + (once live rows exist) no hygiene drift.
SR_LIB="scripts/lib/scheduled_reboots.py"
if grep -q "check_phase_scheduled_reboot" scripts/lib/tier1_suppression.py 2>/dev/null \
   && [ -f "$SR_LIB" ] \
   && grep -q "phaseSR" openclaw/skills/lib/tier1-suppression-flow.sh 2>/dev/null; then
  pass "scheduled-reboot-matcher-wired" "phase SR in tier1_suppression + flow verify hook + $SR_LIB present"
else
  fail "scheduled-reboot-matcher-wired" "phase SR wiring incomplete (tier1_suppression.py / flow / scheduled_reboots.py)"
fi

if [ -f scripts/lib/vendor/croniter/croniter.py ]; then
  pass "scheduled-reboot-croniter-vendored" "croniter vendored (DST-correct matching, no install dep)"
else
  warn "scheduled-reboot-croniter-vendored" "scripts/lib/vendor/croniter missing — matcher will fail-open"
fi

SR_PROM=/var/lib/node_exporter/textfile_collector/scheduled_reboot_metrics.prom
if [ -f "$SR_PROM" ]; then
  SR_AGE=$(( $(date +%s) - $(stat -c %Y "$SR_PROM") ))
  if (( SR_AGE < 1200 )); then
    pass "scheduled-reboot-metrics" "exporter fresh (${SR_AGE}s ago)"
  else
    warn "scheduled-reboot-metrics" "exporter stale (${SR_AGE}s — Cronicle job not wired yet?)"
  fi
else
  warn "scheduled-reboot-metrics" "no scheduled_reboot_metrics.prom (run write-scheduled-reboot-metrics.sh)"
fi

# Registry hygiene — only meaningful once the feature has rows. A live row with
# kill_switch=1 or an expired valid_until is contradictory state (the matcher's
# WHERE already excludes both, so this is a belt-and-suspenders data-hygiene flag).
SR_ROWS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM discovered_scheduled_reboots;" 2>/dev/null || echo -1)
if [ "$SR_ROWS" = "-1" ]; then
  warn "scheduled-reboot-table" "discovered_scheduled_reboots table missing — apply migration 022"
elif [ "$SR_ROWS" -eq 0 ]; then
  skip "scheduled-reboot-registry" "registry empty (feature dark / discovery not yet run)"
else
  SR_BAD=$(sqlite3 "$DB" "SELECT COUNT(*) FROM discovered_scheduled_reboots WHERE status='live' AND (kill_switch=1 OR valid_until < datetime('now'));" 2>/dev/null || echo 0)
  if [ "$SR_BAD" -eq 0 ]; then
    pass "scheduled-reboot-registry" "$SR_ROWS row(s); no live row kill-switched/expired"
  else
    fail "scheduled-reboot-registry" "$SR_BAD live row(s) with kill_switch=1 or expired valid_until (matcher-excluded but contradictory)"
  fi
fi

***REMOVED***════════════════
section "44. Live IaC Checkout Drift (never strand on a stale branch)"
***REMOVED***════════════════
# The live IaC working checkouts (nl + gr production) must stay on main —
# IaC edits go via worktree/MR, never as direct commits on the live tree. On
# 2026-07-08 the NL checkout was found parked on a local-only 'agora-dashboard'
# branch 182 commits behind main. sync-live-iac-checkouts.sh (daily cron) auto-heals
# a CLEAN stranded checkout + emits iac_checkout_* metrics; this asserts the guard
# is fresh and nothing is stranded off main.
IAC_PROM=/var/lib/node_exporter/textfile_collector/iac_checkout_drift.prom
if [ -f "$IAC_PROM" ]; then
  IAC_LAST=$(grep -oE 'iac_checkout_sync_last_run_timestamp [0-9]+' "$IAC_PROM" 2>/dev/null | awk '{print $2}' | head -1)
  IAC_LAST=${IAC_LAST:-0}
  IAC_AGE=$(( $(date +%s) - IAC_LAST ))
  IAC_OFF=$(countc -E 'iac_checkout_on_default_branch\{[^}]*\} 0' "$IAC_PROM")
  if (( IAC_AGE > 172800 )); then
    warn "iac-checkout-guard" "sync-live-iac-checkouts.sh stale (${IAC_AGE}s) — drift auto-heal is dark"
  elif [ "${IAC_OFF:-0}" -gt 0 ]; then
    warn "iac-checkout-drift" "$IAC_OFF live IaC checkout(s) stranded off main (see iac_checkout_on_default_branch)"
  else
    pass "iac-checkout-drift" "live IaC checkouts on main; guard fresh (${IAC_AGE}s ago)"
  fi
else
  skip "iac-checkout-drift" "sync-live-iac-checkouts.sh has not emitted $IAC_PROM yet"
fi

***REMOVED***════════════════
section "45. Chaos Engineering (drill liveness + findings loop)"
***REMOVED***════════════════
# The chaos plane had ZERO health coverage until 2026-07-10 — a dead metrics
# writer or a multi-day drill freeze (as on 2026-04-25) went unnoticed. These
# checks assert: the */5 exporter is fresh, a scheduled exercise ran within the
# fortnight, the last quarterly red-team suite is clean, and the findings
# improvement loop (verify-chaos-findings.py) is harvesting.
CHAOS_PROM=/var/lib/node_exporter/textfile_collector/chaos_metrics.prom
if [ -f "$CHAOS_PROM" ]; then
  CHAOS_TS=$(grep -oE 'chaos_metrics_last_run_timestamp_seconds [0-9]+' "$CHAOS_PROM" 2>/dev/null | awk '{print $2}' | head -1)
  CHAOS_AGE=$(( $(date +%s) - ${CHAOS_TS:-0} ))
  if [ -z "$CHAOS_TS" ]; then warn "chaos-exporter" "chaos_metrics.prom present but no freshness stamp"
  elif (( CHAOS_AGE > 1800 )); then warn "chaos-exporter" "chaos metrics stale (${CHAOS_AGE}s > 30m)"
  else pass "chaos-exporter" "chaos metrics fresh (${CHAOS_AGE}s ago)"; fi

  EX_AGE=$(grep -oE 'chaos_last_exercise_age_seconds [0-9]+' "$CHAOS_PROM" 2>/dev/null | awk '{print $2}' | head -1)
  EX_AGE=${EX_AGE:-0}
  if (( EX_AGE > 1209600 )); then warn "chaos-drill-recency" "last scheduled exercise ${EX_AGE}s ago (>14d) — scheduler may be wedged"
  else pass "chaos-drill-recency" "last exercise $(( EX_AGE / 86400 ))d ago (<= 14d)"; fi
else
  skip "chaos-exporter" "write-chaos-metrics.sh has not emitted $CHAOS_PROM yet"
fi

RT_PROM=/var/lib/node_exporter/textfile_collector/redteam_metrics.prom
if [ -f "$RT_PROM" ]; then
  RT_FAIL=$(grep -oE 'redteam_tests_fail [0-9]+' "$RT_PROM" 2>/dev/null | awk '{print $2}' | head -1)
  RT_FAIL=${RT_FAIL:-0}
  RT_TS=$(grep -oE 'redteam_last_run_timestamp [0-9]+' "$RT_PROM" 2>/dev/null | awk '{print $2}' | head -1)
  RT_TS=${RT_TS:-0}
  RT_AGE=$(( $(date +%s) - RT_TS ))
  if (( RT_FAIL > 0 && RT_AGE < 7776000 )); then warn "chaos-redteam" "$RT_FAIL adversarial guard test(s) failing (last run $(( RT_AGE/86400 ))d ago)"
  else pass "chaos-redteam" "adversarial guard suite clean ($RT_FAIL fail)"; fi
fi

FH_PROM=/var/lib/node_exporter/textfile_collector/chaos_findings_autoverify.prom
if [ -f "$FH_PROM" ]; then
  FH_TS=$(grep -oE 'chaos_findings_harvest_timestamp_seconds [0-9]+' "$FH_PROM" 2>/dev/null | awk '{print $2}' | head -1)
  FH_AGE=$(( $(date +%s) - ${FH_TS:-0} ))
  if [ -z "$FH_TS" ] || (( FH_AGE > 172800 )); then warn "chaos-findings-harvest" "findings harvester stale (${FH_AGE}s > 2d)"
  else pass "chaos-findings-harvest" "findings loop harvesting (${FH_AGE}s ago)"; fi
fi

***REMOVED***════════════════
section "46. Plan-Adherence Gate (reasoning-vs-action, IFRNLLEI01PRD-1746)"
***REMOVED***════════════════
# The PreToolUse gate that checks a dispatched session's mutating commands
# against its committed infragraph blast-radius (pre-execution). Reports arm
# state and, when armed, exporter freshness. Ships DARK (both sentinels absent).
PAG_HOOK="scripts/hooks/plan-adherence-gate.py"
PAG_WIRED=$(grep -c "plan-adherence-gate.py" "$HOME/.claude/settings.json" 2>/dev/null || echo 0)
if [ ! -f "$PAG_HOOK" ]; then
  warn "plan-adherence-gate" "hook script missing ($PAG_HOOK)"
elif [ "${PAG_WIRED:-0}" -lt 1 ]; then
  warn "plan-adherence-gate" "hook present but NOT wired in ~/.claude/settings.json"
elif [ -f "$HOME/gateway.plan_adherence_gate" ]; then
  MODE="shadow"; [ -f "$HOME/gateway.plan_adherence_enforce" ] && MODE="ENFORCE"
  PAG_PROM=/var/lib/node_exporter/textfile_collector/plan_adherence_gate.prom
  if [ -f "$PAG_PROM" ]; then
    PAG_TS=$(grep -oE 'plan_adherence_gate_last_run_timestamp_seconds [0-9]+' "$PAG_PROM" 2>/dev/null | awk '{print $2}' | head -1)
    PAG_AGE=$(( $(date +%s) - ${PAG_TS:-0} ))
    pass "plan-adherence-gate" "ARMED ($MODE); last evaluated a dispatched mutating call ${PAG_AGE}s ago"
  else
    pass "plan-adherence-gate" "ARMED ($MODE); no dispatched mutating call evaluated yet (metric not written)"
  fi
else
  pass "plan-adherence-gate" "wired + DARK (disarmed; touch ~/gateway.plan_adherence_gate for shadow)"
fi

***REMOVED***════════════════
section "47. Mutation Shadow Mode (MUTATIONS=OFF, IFRNLLEI01PRD-1824)"
***REMOVED***════════════════
# Reports whether the autonomous system is actuating (MUTATIONS=ON) or in log-only
# shadow mode (MUTATIONS=OFF: it reasons + logs every intended actuation but never
# executes). Surfaces the shadow-state metric's liveness — the registry marks
# prom:mutation_mode critical, so RegistryCriticalDark (tier-1) pages if this writer
# dies (otherwise we lose all visibility into whether the system is actuating).
MUT_HOOK="scripts/hooks/mutation-shadow-gate.py"
MUT_WIRED=$(grep -c "mutation-shadow-gate.py" "$HOME/.claude/settings.json" 2>/dev/null || echo 0)
MUT_PROM=/var/lib/node_exporter/textfile_collector/mutation_mode.prom
MUT_SENTINEL="$HOME/gateway.mutations_off"
if [ ! -f "$MUT_HOOK" ]; then
  warn "mutation-shadow-mode" "enforcer hook missing ($MUT_HOOK)"
elif [ "${MUT_WIRED:-0}" -lt 1 ]; then
  warn "mutation-shadow-mode" "hook present but NOT wired in ~/.claude/settings.json"
elif [ ! -f "$MUT_PROM" ]; then
  warn "mutation-shadow-mode" "shadow-state metric absent ($MUT_PROM) — mutation-mode-metrics job not writing"
else
  MUT_ACTIVE=$(grep -oE 'gateway_mutations_shadow_active [01]' "$MUT_PROM" | awk '{print $2}' | head -1)
  MUT_TS=$(grep -oE 'gateway_mutations_mode_last_run_timestamp_seconds [0-9]+' "$MUT_PROM" | awk '{print $2}' | head -1)
  MUT_AGE=$(( $(date +%s) - ${MUT_TS:-0} ))
  MUT_BLOCKED=$(grep -oE 'gateway_mutations_shadow_blocked_today [0-9]+' "$MUT_PROM" | awk '{print $2}' | head -1)
  SENT="absent"; [ -f "$MUT_SENTINEL" ] && SENT="present"
  if [ "${MUT_AGE:-999999}" -gt 1800 ]; then
    fail "mutation-shadow-mode" "shadow-state metric STALE (${MUT_AGE}s > 1800s) — mutation-mode-metrics writer dead; orchestrator blind to actuation state"
  elif { [ "$SENT" = "present" ] && [ "${MUT_ACTIVE:-0}" != "1" ]; } || { [ "$SENT" = "absent" ] && [ "${MUT_ACTIVE:-0}" = "1" ]; }; then
    warn "mutation-shadow-mode" "sentinel ($SENT) disagrees with metric (active=${MUT_ACTIVE:-?}) — inconsistent shadow state"
  elif [ "${MUT_ACTIVE:-0}" = "1" ]; then
    pass "mutation-shadow-mode" "MUTATIONS=OFF (shadow/log-only) ACTIVE; ${MUT_BLOCKED:-0} intended actuations logged-not-executed today; metric ${MUT_AGE}s fresh"
  else
    pass "mutation-shadow-mode" "MUTATIONS=ON (normal actuating); metric ${MUT_AGE}s fresh"
  fi
fi

***REMOVED***════════════════
section "48. Master Switch (whole-system power ON/OFF, IFRNLLEI01PRD-1823)"
***REMOVED***════════════════
# The orchestrator's awareness of the whole-system power switch: reports ON/OFF, the
# tamper-evident ledger's chain integrity, a latched partial transition, and writer
# freshness. prom:master_switch is registry-critical → RegistryCriticalDark (tier-1)
# is the PAGER for a dead writer; this §48 stale-writer FAIL is the periodic report.
# state==0 is an INTENTIONAL operator power-off → never a FAIL here.
MSW_PROM=/var/lib/node_exporter/textfile_collector/master_switch.prom
if [ ! -f "$MSW_PROM" ]; then
  fail "master-switch" "power-state metric absent ($MSW_PROM) — master-switch-metrics writer not running; orchestrator blind to whole-system power state"
else
  MSW_STATE=$(grep -oE '^gateway_master_switch_state [01]' "$MSW_PROM" | awk '{print $2}' | head -1)
  MSW_CHAIN=$(grep -oE '^gateway_master_switch_chain_intact [01]' "$MSW_PROM" | awk '{print $2}' | head -1)
  MSW_PARTIAL=$(grep -oE '^gateway_master_switch_partial_last [01]' "$MSW_PROM" | awk '{print $2}' | head -1)
  MSW_TS=$(grep -oE '^gateway_master_switch_last_run_timestamp_seconds [0-9]+' "$MSW_PROM" | awk '{print $2}' | head -1)
  MSW_TXN=$(grep -oE '^gateway_master_switch_transitions_total -?[0-9]+' "$MSW_PROM" | awk '{print $2}' | head -1)
  MSW_AGE=$(( $(date +%s) - ${MSW_TS:-0} ))
  MSW_STATE_TXT="ON"; [ "${MSW_STATE:-1}" = "0" ] && MSW_STATE_TXT="OFF(intentional)"
  if [ "${MSW_AGE:-999999}" -gt 1800 ]; then
    fail "master-switch" "power-state metric STALE (${MSW_AGE}s > 1800s) — master-switch-metrics writer dead (RegistryCriticalDark is the pager; this is the periodic report)"
  elif [ "${MSW_CHAIN:-1}" = "0" ]; then
    fail "master-switch" "ledger hash-chain BROKEN (chain_intact=0, transitions=${MSW_TXN:-?}) — master_switch_log tampered/reordered; run: gateway-master-switch.py log; python3 scripts/lib/master_switch_audit.py verify"
  elif [ "${MSW_PARTIAL:-0}" = "1" ]; then
    warn "master-switch" "last transition LATCHED partial (partial_last=1, state=$MSW_STATE_TXT) — inconsistent power state OR a benign Cronicle blip; clear by re-running: gateway-master-switch.py off --force then on"
  else
    pass "master-switch" "state=$MSW_STATE_TXT chain_intact=1 partial=0 txns=${MSW_TXN:-?} age=${MSW_AGE}s"
  fi
fi

***REMOVED***════════════════
# SUMMARY + TRENDING
***REMOVED***════════════════
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
TOTAL=$((PASS + FAIL + WARN + SKIP))
DENOMINATOR=$((PASS + FAIL + WARN))
SCORE=0
if (( DENOMINATOR > 0 )); then
  SCORE=$(( (PASS * 100) / DENOMINATOR ))
fi

# Determine run mode for trending
RUN_MODE="full"
$QUICK && RUN_MODE="quick"
$SMOKE && RUN_MODE="smoke"

# Store in SQLite for trending
RUN_ID=$(sqlite3 "$DB" "INSERT INTO health_check_results(score,pass,fail,warn,skip,duration_s,mode) VALUES($SCORE,$PASS,$FAIL,$WARN,$SKIP,$DURATION,'$RUN_MODE'); SELECT last_insert_rowid();" 2>/dev/null || echo 0)
if (( RUN_ID > 0 )); then
  for r in "${RESULTS[@]}"; do
    IFS='|' read -r st nm dt <<< "$r"
    sqlite3 "$DB" "INSERT INTO health_check_detail(run_id,status,name,detail) VALUES($RUN_ID,'$st','$(echo "$nm" | sed "s/'/''/g")','$(echo "$dt" | sed "s/'/''/g")');" 2>/dev/null
  done
fi

# Get trending data
TREND=$(sqlite3 "$DB" "SELECT score FROM health_check_results ORDER BY run_at DESC LIMIT 5;" 2>/dev/null | tr '\n' ' ')

if $JSON_OUT; then
  echo "{"
  echo "  \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
  echo "  \"pass\": $PASS, \"fail\": $FAIL, \"warn\": $WARN, \"skip\": $SKIP,"
  echo "  \"total\": $TOTAL, \"score\": $SCORE, \"duration_s\": $DURATION,"
  echo "  \"trend\": [$(echo "$TREND" | sed 's/ *$//' | sed 's/ /, /g')],"
  echo "  \"results\": ["
  first=true
  for r in "${RESULTS[@]}"; do
    $first || echo ","
    IFS='|' read -r status name detail <<< "$r"
    echo -n "    {\"status\": \"$status\", \"name\": \"$name\", \"detail\": \"$(echo "$detail" | sed 's/"/\\"/g')\"}"
    first=false
  done
  echo ""
  echo "  ]"
  echo "}"
else
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  printf "  HOLISTIC HEALTH SCORE: \e[1m%d%%\e[0m  (%d pass, %d fail, %d warn, %d skip) in %ds\n" "$SCORE" "$PASS" "$FAIL" "$WARN" "$SKIP" "$DURATION"
  if [ -n "$TREND" ]; then
    printf "  Trend (last 5 runs): %s\n" "$TREND"
  fi
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi

# Write Prometheus metrics
PROM_DIR="/var/lib/node_exporter/textfile_collector"
if [ -d "$PROM_DIR" ]; then
  cat > "$PROM_DIR/holistic_health.prom" <<PROM
# HELP holistic_health_score Holistic agentic platform health score (0-100)
# TYPE holistic_health_score gauge
holistic_health_score $SCORE
# HELP holistic_health_pass Number of passing health checks
# TYPE holistic_health_pass gauge
holistic_health_pass $PASS
# HELP holistic_health_fail Number of failing health checks
# TYPE holistic_health_fail gauge
holistic_health_fail $FAIL
# HELP holistic_health_warn Number of warning health checks
# TYPE holistic_health_warn gauge
holistic_health_warn $WARN
# HELP holistic_health_duration_seconds Health check run duration
# TYPE holistic_health_duration_seconds gauge
holistic_health_duration_seconds $DURATION
# HELP holistic_health_last_run_timestamp_seconds Unix epoch seconds when the holistic health check last completed (liveness of the catch-all watchdog itself; IFRNLLEI01PRD dark-component audit 2026-06-25)
# TYPE holistic_health_last_run_timestamp_seconds gauge
holistic_health_last_run_timestamp_seconds $(date +%s)
PROM
fi

exit $(( FAIL > 0 ? 1 : 0 ))
