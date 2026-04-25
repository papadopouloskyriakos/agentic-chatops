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

for WF_NAME in "Runner" "Matrix Bridge" "Session End" "Progress Poller" "LibreNMS Receiver" "Prometheus Alert Receiver" "CrowdSec Alert Receiver"; do
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
else warn "no-empty-tables" "${#EMPTY_TABLES[@]} empty: ${EMPTY_TABLES[*]}"; fi

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

# NEW: Per-table staleness with thresholds
for STALE_CHECK in "tool_call_log:created_at:72" "llm_usage:recorded_at:72" "session_transcripts:created_at:168" \
                    "session_judgment:judged_at:168" "wiki_articles:compiled_at:48" "agent_diary:created_at:168" \
                    "otel_spans:created_at:168" "prompt_scorecard:graded_at:336"; do
  S_TBL=$(echo "$STALE_CHECK" | cut -d: -f1)
  S_COL=$(echo "$STALE_CHECK" | cut -d: -f2)
  S_MAX=$(echo "$STALE_CHECK" | cut -d: -f3)
  AGE_H=$(db_max_age_hours "$S_TBL" "$S_COL")
  if (( AGE_H <= S_MAX )); then pass "staleness-$S_TBL" "last write ${AGE_H}h ago (<= ${S_MAX}h)"
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
section "6. OpenClaw Tier 1 (claim: 19 skills)"
OC_SKILLS=$(ssh -o ConnectTimeout=5 nl-openclaw01 "ls /root/.openclaw/workspace/skills/ 2>/dev/null | wc -l" 2>/dev/null || echo 0)
if (( OC_SKILLS >= 19 )); then pass "openclaw-skills" "$OC_SKILLS skills (>= 19)"
else fail "openclaw-skills" "only $OC_SKILLS skills"; fi

OC_PING=$(ssh -o ConnectTimeout=5 nl-openclaw01 "docker exec openclaw-openclaw-gateway-1 echo ok 2>/dev/null" 2>/dev/null || echo "fail")
if [ "$OC_PING" = "ok" ]; then pass "openclaw-container" "container running"
else fail "openclaw-container" "not responding"; fi

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

INJECTION_COUNT=$(grep -A500 'INJECTION_PATTERNS=(' scripts/hooks/unified-guard.sh 2>/dev/null | grep -c '"' || echo 0)
if (( INJECTION_COUNT >= 40 )); then pass "injection-patterns" "$INJECTION_COUNT lines (>= 40)"
else fail "injection-patterns" "only $INJECTION_COUNT"; fi

BLOCKED_COUNT=$(grep -A500 'BLOCKED_PATTERNS=(' scripts/hooks/unified-guard.sh 2>/dev/null | grep -c '"' || echo 0)
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
CRON_COUNT=$(crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$' | wc -l)
if (( CRON_COUNT >= 30 )); then pass "crons" "$CRON_COUNT entries (>= 30)"
else warn "crons" "only $CRON_COUNT"; fi

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
  VTI_RAW=$(python3 -c "
import subprocess
proc=subprocess.Popen(['sshpass','-p','$ASA_PW','ssh','-T','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=no','-o','HostKeyAlgorithms=+ssh-rsa','-o','PubkeyAcceptedAlgorithms=+ssh-rsa','operator@10.0.181.X'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
out,_=proc.communicate(input='enable\n$ASA_PW\nterminal pager 0\nshow crypto ikev2 sa\nexit\n',timeout=10)
print(out)" 2>/dev/null || echo "")
  VTI_UP=$(echo "$VTI_RAW" | grep -c "READY" || echo "0")
  VTI_UP=$((VTI_UP + 0))
  if (( VTI_UP >= 6 )); then pass "vti-tunnels" "$VTI_UP IKEv2 SAs READY (>= 6)"
  elif (( VTI_UP >= 3 )); then warn "vti-tunnels" "only $VTI_UP READY (expected >= 6)"
  else fail "vti-tunnels" "$VTI_UP READY tunnels"; fi

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
  GH_PUSHED=$(curl -sf --connect-timeout 5 "https://api.github.com/repos/papadopouloskyriakos/agentic-chatops" 2>/dev/null | python3 -c "
import sys,json,datetime as dt
d=json.load(sys.stdin)
pushed=d.get('pushed_at','')
if pushed:
  age=(dt.datetime.utcnow()-dt.datetime.fromisoformat(pushed.rstrip('Z'))).total_seconds()/3600
  print(int(age))
else: print(9999)" 2>/dev/null || echo 9999)
  if (( GH_PUSHED <= 72 )); then pass "github-mirror" "last push ${GH_PUSHED}h ago (<= 72h)"
  elif (( GH_PUSHED <= 168 )); then warn "github-mirror" "last push ${GH_PUSHED}h ago (> 72h)"
  else fail "github-mirror" "last push ${GH_PUSHED}h ago (stale > 7d)"; fi
fi

# OpenClaw LLM connectivity (check if OpenAI key works via container)
if $QUICK; then skip "openclaw-llm" "skipped (--quick)"
else
  OC_LLM=$(ssh -o ConnectTimeout=5 nl-openclaw01 "docker exec openclaw-openclaw-gateway-1 python3 -c \"
import urllib.request,json
req=urllib.request.Request('https://api.openai.com/v1/models',headers={'Authorization':'Bearer test'})
try:
  urllib.request.urlopen(req,timeout=3)
  print('OK')
except urllib.error.HTTPError as e:
  print('OK' if e.code==401 else 'NO')
except: print('NO')
\"" 2>/dev/null || echo "NO")
  if [ "$OC_LLM" = "OK" ]; then pass "openclaw-llm" "OpenAI API reachable from container"
  else warn "openclaw-llm" "OpenAI API unreachable from container"; fi
fi

***REMOVED***════════════════
# S32: Infrastructure Health
***REMOVED***════════════════
section "32. Infrastructure Health (K8s, PVE, BGP, GPU)"

# K8s node count
if $QUICK; then skip "k8s-nodes" "skipped (--quick)"
else
  K8S_NODES=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready" || echo 0)
  if (( K8S_NODES >= 7 )); then pass "k8s-nodes" "$K8S_NODES nodes Ready (>= 7)"
  elif (( K8S_NODES >= 4 )); then warn "k8s-nodes" "only $K8S_NODES Ready (expected 7)"
  else fail "k8s-nodes" "$K8S_NODES Ready"; fi
fi

# PVE cluster quorum
if $QUICK; then skip "pve-quorum" "skipped (--quick)"
else
  PVE_STATUS=$(ssh -o ConnectTimeout=5 nl-pve01 "pvecm status 2>/dev/null" 2>/dev/null || echo "")
  PVE_NODES=$(echo "$PVE_STATUS" | grep -c "node-id" || echo "0")
  PVE_NODES=$((PVE_NODES + 0))
  PVE_QUORATE=$(echo "$PVE_STATUS" | grep -ci "Quorate.*Yes" || echo "0")
  PVE_QUORATE=$((PVE_QUORATE + 0))
  if (( PVE_QUORATE > 0 && PVE_NODES >= 3 )); then pass "pve-quorum" "$PVE_NODES PVE nodes, quorum OK"
  elif (( PVE_NODES >= 2 )); then warn "pve-quorum" "$PVE_NODES nodes (quorum uncertain)"
  else warn "pve-quorum" "could not determine cluster status"; fi
fi

# BGP peer count on NL ASA
if $QUICK; then skip "bgp-peers" "skipped (--quick)"
else
  BGP_RAW=$(python3 -c "
import subprocess
proc=subprocess.Popen(['sshpass','-p','$ASA_PW','ssh','-T','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=no','-o','HostKeyAlgorithms=+ssh-rsa','-o','PubkeyAcceptedAlgorithms=+ssh-rsa','operator@10.0.181.X'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
out,_=proc.communicate(input='enable\n$ASA_PW\nterminal pager 0\nshow bgp summary\nexit\n',timeout=10)
print(out)" 2>/dev/null || echo "")
  # ASA shows BGP peers with time durations (1d05h, 11:18:16) for established peers, "never" or "Active" for down
  BGP_ESTAB=$(echo "$BGP_RAW" | grep -cE '[0-9]+d[0-9]+h|[0-9]+:[0-9]+:[0-9]+' || echo "0")
  BGP_ESTAB=$((BGP_ESTAB + 0))
  if (( BGP_ESTAB >= 7 )); then pass "bgp-peers" "$BGP_ESTAB BGP peers established (>= 7)"
  elif (( BGP_ESTAB >= 4 )); then warn "bgp-peers" "only $BGP_ESTAB established (expected 7+)"
  else fail "bgp-peers" "$BGP_ESTAB established"; fi
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

# Incident knowledge embeddings — check they're real 768-dim vectors
EMPTY_EMBED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM incident_knowledge WHERE embedding IS NULL OR embedding = '' OR LENGTH(embedding) < 100;" 2>/dev/null || echo 999)
TOTAL_IK=$(db_count "incident_knowledge")
if (( EMPTY_EMBED == 0 && TOTAL_IK > 0 )); then pass "ik-embeddings" "all $TOTAL_IK entries have embeddings"
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

# OpenClaw memory sync
if $QUICK; then skip "oc-memory-sync" "skipped (--quick)"
else
  OC_MEM=$(ssh -o ConnectTimeout=5 nl-openclaw01 "ls /root/.openclaw/workspace/memory/*.md 2>/dev/null | wc -l" 2>/dev/null || echo 0)
  if (( OC_MEM >= 3 )); then pass "oc-memory-sync" "$OC_MEM memory files on openclaw host"
  else warn "oc-memory-sync" "only $OC_MEM memories"; fi
fi

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
  TODAY=$(date +%Y-%m-%d)
  YM_Y=$(date +%Y); YM_M=$(date +%m)

  NL_SYSLOG=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key root@nlsyslogng01 "wc -l /mnt/logs/syslog-ng/nl-claude01/$YM_Y/$YM_M/nl-claude01-${TODAY}.log 2>/dev/null" 2>/dev/null | awk '{print $1}' || echo 0)
  NL_SYSLOG=$((NL_SYSLOG + 0))
  if (( NL_SYSLOG > 0 )); then pass "nlsyslogng01" "$NL_SYSLOG log lines today"
  else warn "nlsyslogng01" "no logs today"; fi

  GR_SYSLOG=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key root@grsyslogng01 "wc -l /mnt/logs/syslog-ng/gr-pve01/$YM_Y/$YM_M/gr-pve01-${TODAY}.log 2>/dev/null" 2>/dev/null | awk '{print $1}' || echo 0)
  GR_SYSLOG=$((GR_SYSLOG + 0))
  if (( GR_SYSLOG > 0 )); then pass "grsyslogng01" "$GR_SYSLOG log lines today"
  else warn "grsyslogng01" "no logs today"; fi

  # rtr01 syslog — the 2026-04-22 fix pinned 10.0.X.X → nlrtr01
  # in /etc/hosts on the syslog-ng server so rtr01's data-plane ACL logs
  # land under the hostname bucket, not an IP-fallback bucket. Guardrail
  # confirms no regression (no by-IP bucket re-emerged) and the hostname
  # bucket is still receiving.
  RTR_LINES=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key root@nlsyslogng01 "wc -l /mnt/logs/syslog-ng/nlrtr01/$YM_Y/$YM_M/nlrtr01-${TODAY}.log 2>/dev/null" 2>/dev/null | awk '{print $1}' || echo 0)
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
  SLA_RAW=$(python3 -c "
import subprocess
proc=subprocess.Popen(['sshpass','-p','$ASA_PW','ssh','-T','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=no','-o','HostKeyAlgorithms=+ssh-rsa','-o','PubkeyAcceptedAlgorithms=+ssh-rsa','operator@10.0.181.X'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
out,_=proc.communicate(input='enable\n$ASA_PW\nterminal pager 0\nshow track 1\nexit\n',timeout=10)
print(out)" 2>/dev/null || echo "")
  if echo "$SLA_RAW" | grep -q "Reachability is Up"; then pass "freedom-sla" "Freedom WAN SLA track UP"
  elif echo "$SLA_RAW" | grep -q "Reachability is Down"; then fail "freedom-sla" "Freedom WAN DOWN"
  else warn "freedom-sla" "could not parse SLA state"; fi
fi

# Docker containers on OpenClaw host
if $QUICK; then skip "docker-oc" "skipped (--quick)"
else
  OC_CONTAINERS=$(ssh -o ConnectTimeout=5 nl-openclaw01 "docker ps --format '{{.Names}}' 2>/dev/null | wc -l" 2>/dev/null || echo 0)
  if (( OC_CONTAINERS >= 2 )); then pass "docker-oc" "$OC_CONTAINERS containers running on openclaw"
  else warn "docker-oc" "only $OC_CONTAINERS containers"; fi
fi

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

# Risk-classification audit invariant (IFRNLLEI01PRD-632)
if sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND name='session_risk_audit'" 2>/dev/null | grep -q session_risk_audit; then
    RISK_ROWS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_risk_audit WHERE classified_at >= datetime('now','-7 days')" 2>/dev/null || echo 0)
    RISK_INVARIANT_BAD=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_risk_audit WHERE classified_at >= datetime('now','-7 days') AND auto_approved = 1 AND risk_level != 'low'" 2>/dev/null || echo 0)
    if (( RISK_INVARIANT_BAD > 0 )); then
        fail "risk-audit-invariant" "$RISK_INVARIANT_BAD session(s) auto-approved with risk_level != 'low' in last 7d"
    elif (( RISK_ROWS > 0 )); then
        pass "risk-audit-invariant" "$RISK_ROWS classifications in 7d, all auto-approvals were risk=low"
    else
        skip "risk-audit-invariant" "no classifications yet (wiring pending)"
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
  VPS_SAS=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key operator@198.51.100.X "echo '$ASA_PW' | sudo -S swanctl --list-sas 2>/dev/null | grep -c 'ESTABLISHED'" 2>/dev/null || echo 0)
  VPS_SAS=$((VPS_SAS + 0))
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
PROM
fi

exit $(( FAIL > 0 ? 1 : 0 ))
