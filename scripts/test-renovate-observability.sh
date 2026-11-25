#!/bin/bash
# Hermetic test for the Renovate MR Autonomy observability + tamper-evidence layer (Dim-6):
# seed an isolated, hash-chained DB with a deliberate floor breach; confirm the metrics writer's
# invariant counter + the weekly auditor catch it; then TAMPER a committed row and confirm the hash
# chain detects it (chain_ok→0) and the weekly audit-metrics writer emits its metrics.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="$(mktemp)"; OUT="$(mktemp)"; AUD="$(mktemp)"; PASS=0; FAIL=0
export GATEWAY_DB="$DB"
ck(){ if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf 'PASS  %-44s %s\n' "$1" "$2"; else FAIL=$((FAIL+1)); printf 'FAIL  %-44s got %s want %s\n' "$1" "$2" "$3"; fi; }
verify(){ python3 "$DIR/lib/renovate_audit.py" verify --db "$DB" >/dev/null 2>&1; echo $?; }

ins(){ # mode decision tier ci verdict snap_req gates  — appended THROUGH the tamper-evident chain
  python3 "$DIR/lib/renovate_audit.py" append --db "$DB" --json \
    "$(jq -nc --arg m "$1" --arg d "$2" --arg t "$3" --arg ci "$4" --arg v "$5" --arg sr "$6" --arg g "$7" \
       '{project_id:"30",mr_iid:"1",mode:$m,decision:$d,tier:$t,ci_status:$ci,review_verdict:$v,snapshot_required:$sr,gates_json:$g,schema_version:1}')" >/dev/null
}
#   mode   decision tier     ci      verdict  snap_req gates
ins shadow AUTO     critical success APPROVE  true    '{"snapshot_verified":true}'   # exempt (shadow)
ins live   AUTO     critical success APPROVE  true    '{"snapshot_verified":true}'   # clean
ins live   AUTO     critical success APPROVE  true    '{"snapshot_verified":false}'  # BREACH
ins live   POLL     critical success APPROVE  true    '{"snapshot_verified":false}'  # not AUTO → exempt
ins live   AUTO     routine  success APPROVE  false   '{"snapshot_verified":true}'   # routine, no snap → clean

RENOVATE_METRICS_OUT="$OUT" python3 "$DIR/write-renovate-autonomy-metrics.py"
ck "metric: invariant counter = 1 breach" "$(grep -E '^renovate_autonomy_merged_without_snapshot_total ' "$OUT" | awk '{print $2}')" "1"
ck "metric: chain_ok = 1 (intact)"        "$(grep -E '^renovate_autonomy_chain_ok ' "$OUT" | awk '{print $2}')" "1"
ck "metric: last_run emitted"             "$(grep -qc '^renovate_autonomy_last_run_timestamp_seconds ' "$OUT" && echo yes)" "yes"
ck "metric: decisions series present"     "$([ "$(grep -c '^renovate_autonomy_decisions_total{' "$OUT")" -ge 3 ] && echo ok)" "ok"
ck "auditor: exit 1 on breach"            "$(bash "$DIR/audit-renovate-decisions.sh" >/dev/null 2>&1; echo $?)" "1"
ck "chain: OK before tamper"              "$(verify)" "0"

# TAMPER: silently edit a committed row → the hash chain MUST catch it
sqlite3 "$DB" "UPDATE renovate_autonomy_audit SET review_verdict='REQUEST_CHANGES' WHERE gates_json='{\"snapshot_verified\":false}' AND decision='AUTO';"
ck "chain: BROKEN after row edit"         "$(verify)" "1"
RENOVATE_METRICS_OUT="$OUT" python3 "$DIR/write-renovate-autonomy-metrics.py"
ck "metric: chain_ok = 0 after tamper"    "$(grep -E '^renovate_autonomy_chain_ok ' "$OUT" | awk '{print $2}')" "0"

# weekly audit-metrics writer (the previously-missing file) emits its 3 metrics
RENOVATE_AUDIT_METRICS_OUT="$AUD" bash "$DIR/write-renovate-audit-metrics.sh"
ck "audit-metrics: chain_broken=1"        "$(grep -E '^renovate_autonomy_chain_broken ' "$AUD" | awk '{print $2}')" "1"
ck "audit-metrics: audit_fail emitted"    "$(grep -qc '^renovate_autonomy_audit_fail ' "$AUD" && echo yes)" "yes"
ck "audit-metrics: last_run emitted"      "$(grep -qc '^renovate_autonomy_audit_last_run_timestamp_seconds ' "$AUD" && echo yes)" "yes"

ck "alerts yaml parses"                   "$(python3 -c "import yaml;yaml.safe_load(open('$DIR/../prometheus/alert-rules/renovate-autonomy.yml'))" >/dev/null 2>&1 && echo ok)" "ok"

rm -f "$DB" "$OUT" "$AUD"
echo; echo "$((PASS+FAIL)) checks, $FAIL failure(s)"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
