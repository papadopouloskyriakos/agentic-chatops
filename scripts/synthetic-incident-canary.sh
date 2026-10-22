#!/bin/bash
# synthetic-incident-canary.sh — IFRNLLEI01PRD-1154 (roadmap Stage-0 "I3").
#
# Cron-fired end-to-end probe of the autonomy SPINE: classify-session-risk.py ->
# infragraph-predict-plan.py, asserting each stage produces its artifact
# (band + plan_hash from classify; plan_hash + gate from predict; coherent
# plan_hash across both). This is the structural defense against the
# months-long-silent-dark class (empty plan, no band, gate logic broken).
#
# SAFETY (the synthesis's #1 risk was prod pollution / tripping real remediation):
# the spine runs against an ISOLATED throwaway DB (GATEWAY_DB=$(mktemp), seeded
# from schema.sql), NOT the live gateway.db. That structurally eliminates all
# three top risks — it cannot write the real session_risk_audit/infragraph_predictions,
# cannot collide plan_hash with a real in-flight session's fail-closed gate, and
# never touches n8n / real hosts. The plan is read-only (no remediation, no
# awx_templates) so even the in-temp-db gate is benign. Only the per-stage
# Prometheus gauges are written to the REAL textfile collector.
#
# Flags: --dry-run (build + run but do not write metrics), --verbose, --notify.
#
# EVAL-AWARENESS CAVEAT (IFRNLLEI01PRD-1667, from the "Global Workspace in LLMs"
# audit, transformer-circuits.pub/2026/workspace): this is a STRUCTURAL spine
# probe — it exercises classify->predict->verify against an isolated DB, NOT a
# live Claude session. It therefore cannot detect behavioural eval-awareness
# (models can behave differently when they recognise a probe/test). A green
# canary attests to spine LIVENESS/structural integrity, NOT that a model
# behaves on a real incident as it does on a known synthetic one. The same
# caveat applies to chaos drills. Surfaced as an info gauge below.
set -uo pipefail   # NOT -e: capture per-stage failure rather than abort.

REPO="/app/claude-gateway"
OUT="${SYNTHETIC_CANARY_OUT:-/var/lib/node_exporter/textfile_collector/synthetic_canary.prom}"
DRY=0; VERBOSE=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --verbose) VERBOSE=1 ;;
    --notify)  : ;;  # alerting is via the Prometheus rule on the emitted gauge
  esac
done
vlog() { [ "$VERBOSE" = 1 ] && echo "[canary] $*" >&2 || true; }

CANARY_DB="$(mktemp --suffix=.canary.db)"
PLAN_FILE="$(mktemp --suffix=.canary.json)"
cleanup() { rm -f "$CANARY_DB" "$CANARY_DB-wal" "$CANARY_DB-shm" "$PLAN_FILE" 2>/dev/null || true; }
trap cleanup EXIT

UUID="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || date +%s%N)"
ISSUE="canary-$UUID"
HOST="canary-host-$UUID"

# Synthetic READ-ONLY plan (no remediation verbs, no awx_templates => benign).
cat > "$PLAN_FILE" <<JSON
{"hostname":"$HOST","summary":"synthetic incident canary $UUID (read-only, isolated db)","steps":["read-only diagnostic check"],"tools_needed":["Read","Grep"],"draft_reply":"synthetic canary probe — no action taken"}
JSON

# Isolated schema (+ idempotent migrations so every column the spine reads exists).
sqlite3 "$CANARY_DB" < "$REPO/schema.sql" 2>/dev/null || true
GATEWAY_DB="$CANARY_DB" python3 "$REPO/scripts/migrations/apply.py" >/dev/null 2>&1 || true

jget() { python3 -c "import sys,json
try: print(json.load(sys.stdin).get('$1') or '')
except Exception: print('')" 2>/dev/null; }

classify_ok=0; predict_ok=0; verify_ok=0

# --- Stage 1: classify-session-risk.py ---
C_OUT="$(GATEWAY_DB="$CANARY_DB" ISSUE_ID="$ISSUE" python3 "$REPO/scripts/classify-session-risk.py" \
          --category test --issue-id "$ISSUE" --plan "$PLAN_FILE" 2>/dev/null)"
C_HASH="$(printf '%s' "$C_OUT" | jget plan_hash)"
C_BAND="$(printf '%s' "$C_OUT" | jget band)"
C_RISK="$(printf '%s' "$C_OUT" | jget risk_level)"
ROW="$(sqlite3 "$CANARY_DB" "SELECT COUNT(*) FROM session_risk_audit WHERE issue_id='$ISSUE';" 2>/dev/null || echo 0)"
if [ -n "$C_HASH" ] && [ -n "$C_BAND" ] && [ -n "$C_RISK" ] && [ "${ROW:-0}" -ge 1 ]; then classify_ok=1; fi
vlog "classify: hash=$C_HASH band=$C_BAND risk=$C_RISK audit_rows=$ROW ok=$classify_ok"

# --- Stage 2: infragraph-predict-plan.py ---
P_OUT="$(python3 "$REPO/scripts/infragraph-predict-plan.py" --db "$CANARY_DB" --issue "$ISSUE" < "$PLAN_FILE" 2>/dev/null)"
P_HASH="$(printf '%s' "$P_OUT" | jget plan_hash)"
P_GATE="$(printf '%s' "$P_OUT" | jget gate)"
if [ -n "$P_HASH" ] && [ -n "$P_GATE" ]; then predict_ok=1; fi
vlog "predict: hash=$P_HASH gate=$P_GATE ok=$predict_ok"

# --- Stage 3: spine coherence (deterministic plan_hash across both stages) ---
if [ "$classify_ok" = 1 ] && [ "$predict_ok" = 1 ] && [ -n "$C_HASH" ] && [ "$C_HASH" = "$P_HASH" ]; then verify_ok=1; fi
vlog "verify: classify_hash==predict_hash -> ok=$verify_ok"

PASSED=$((classify_ok + predict_ok + verify_ok))

# --- Stage 4: tier-1 suppression LIVENESS (IFRNLLEI01PRD-1155 fault-5) ---
# The 06-21 deferral left "tier-1 silently inert" (host-pinned/expired suppression rows -> the
# whole suppression path stops firing) with no injection-proves-detection test. Seed a synthetic
# blast-radius row in the ISOLATED canary DB and assert tier1_suppression actually folds a matching
# alert. If tier1 is silently broken (import error, schema drift, logic regression), this dedup does
# NOT happen and the stage fails — catching the dark-inert class the spine stages cannot see.
tier1_ok=0
sqlite3 "$CANARY_DB" "CREATE TABLE IF NOT EXISTS openclaw_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL DEFAULT 'triage', key TEXT NOT NULL, value TEXT NOT NULL, issue_id TEXT DEFAULT '', updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
  INSERT INTO openclaw_memory (category,key,value,issue_id) VALUES ('blast-radius','CANARY-PARENT','{\"hosts\":[\"canary-host-xyz\"],\"rules\":[\"*Canary Probe*\"],\"description\":\"synthetic canary liveness probe\"}','CANARY-PARENT');" 2>/dev/null
T1_OUT="$(python3 "$REPO/scripts/lib/tier1_suppression.py" --hostname canary-host-xyz --rule-name 'Canary Probe Alert' --severity warning --db "$CANARY_DB" --triage-log /dev/null --no-yt-check --current-issue-id canary-child 2>/dev/null)"
if echo "$T1_OUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get("outcome")=="dedup" else 1)' 2>/dev/null; then tier1_ok=1; fi
vlog "tier1-suppress: synthetic blast-radius fold -> ok=$tier1_ok"

TS="$(date +%s)"

# Belt-and-suspenders: assert nothing leaked into the REAL db (issue is canary-*).
LIVE_DB="${GATEWAY_DB:-/app/cubeos/claude-context/gateway.db}"
LEAK="$(sqlite3 "$LIVE_DB" "SELECT COUNT(*) FROM session_risk_audit WHERE issue_id='$ISSUE';" 2>/dev/null || echo 0)"
[ "${LEAK:-0}" != 0 ] && echo "[canary] WARNING: $LEAK leaked rows in live db for $ISSUE" >&2

echo "[canary] $ISSUE stages_passed=$PASSED/3 classify=$classify_ok predict=$predict_ok verify=$verify_ok leak=$LEAK"
vlog "eval-awareness caveat: structural probe only — attests spine liveness, not real-incident behavioural fidelity (IFRNLLEI01PRD-1667)"

if [ "$DRY" = 1 ]; then
  vlog "dry-run: not writing $OUT"
  exit 0
fi

{
  echo "# HELP synthetic_incident_canary_stage_ok Per-stage pass (1) / fail (0) of the autonomy-spine canary (IFRNLLEI01PRD-1154)."
  echo "# TYPE synthetic_incident_canary_stage_ok gauge"
  echo "synthetic_incident_canary_stage_ok{stage=\"classify\"} $classify_ok"
  echo "synthetic_incident_canary_stage_ok{stage=\"predict\"} $predict_ok"
  echo "synthetic_incident_canary_stage_ok{stage=\"verify\"} $verify_ok"
  echo "synthetic_incident_canary_stage_ok{stage=\"tier1_suppress\"} $tier1_ok"
  echo "# HELP synthetic_incident_canary_stages_passed Number of spine stages that passed (0-3)."
  echo "# TYPE synthetic_incident_canary_stages_passed gauge"
  echo "synthetic_incident_canary_stages_passed $PASSED"
  echo "# HELP synthetic_incident_canary_live_db_leak Rows the canary leaked into the live db (must be 0)."
  echo "# TYPE synthetic_incident_canary_live_db_leak gauge"
  echo "synthetic_incident_canary_live_db_leak ${LEAK:-0}"
  echo "# HELP synthetic_incident_canary_last_run_timestamp Unix time of last canary run."
  echo "# TYPE synthetic_incident_canary_last_run_timestamp gauge"
  echo "synthetic_incident_canary_last_run_timestamp $TS"
  echo "# HELP synthetic_incident_canary_eval_awareness_caveat Info gauge (always 1). This is a STRUCTURAL spine probe (classify->predict->verify on an isolated DB), not a live model session, so it cannot detect behavioural eval-awareness. A green canary attests to spine liveness, NOT that a model behaves on a real incident as it does on a known probe; same caveat applies to chaos drills. Ref IFRNLLEI01PRD-1667 / transformer-circuits.pub/2026/workspace."
  echo "# TYPE synthetic_incident_canary_eval_awareness_caveat gauge"
  echo "synthetic_incident_canary_eval_awareness_caveat 1"
} > "${OUT}.tmp" 2>/dev/null && mv "${OUT}.tmp" "$OUT" 2>/dev/null || { echo "[canary] metric write failed" >&2; exit 1; }

exit 0
