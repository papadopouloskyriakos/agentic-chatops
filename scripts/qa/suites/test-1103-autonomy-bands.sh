#!/usr/bin/env bash
# IFRNLLEI01PRD-1103/-1109 — autonomy-forward band engine test suite.
#
# Covers: flag-OFF byte-parity with legacy, all four bands, the never-auto floor
# (irreversible/reboot/awx/unknown), reversible-MIXED -> AUTO, P0 -> AUTO_NOTICE+SMS,
# the docs/host-blast-radius.md <-> _P0_HOSTS_BASE drift check, schema v2 columns,
# and the audit-row write. Hermetic: INFRAGRAPH_DISABLED=1, temp GATEWAY_DB.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1103-autonomy-bands"
CLS="$REPO_ROOT/scripts/classify-session-risk.py"
TESTDB="$(mktemp --suffix=.db)"
# Pin the appetite sentinels OFF (paths that don't exist) so these baseline/floor tests are
# isolated from the LIVE ~/gateway.{territory_gate,host_reboot_auto}. The gate-ON relaxations
# (host reboot, gate-governed network/container) are covered by their own tests/suites, which
# override these per-test via the classify() env. (Same isolation rule as the conservative suite.)
export TERRITORY_GATE_SENTINEL="$TESTDB.noterritory"
export HOST_REBOOT_AUTO_SENTINEL="$TESTDB.nohostreboot"
trap 'rm -f "$TESTDB"' EXIT

# classify <category> [ENV=VAL ...]   — plan JSON read from $PLAN
classify() {
  local cat="$1"; shift
  printf '%s' "$PLAN" | env GATEWAY_DB="$TESTDB" INFRAGRAPH_DISABLED=1 "$@" \
    python3 "$CLS" --category "$cat" --no-audit
}
jget() { python3 -c "import json,sys;v=json.load(sys.stdin).get('$1');print('null' if v is None else v)"; }

# ─── parity: flag OFF must be byte-identical to legacy (no band keys) ─────────
start_test "flag_off_no_band_key_low"
  PLAN='{"hypothesis":"disk filling","steps":[{"command":"df -h; kubectl get pods"}]}'
  out=$(classify availability AUTONOMY_FORWARD=0)
  assert_eq low "$(echo "$out" | jget risk_level)"
  assert_eq "null" "$(echo "$out" | jget band)" "no band key when flag off"
  assert_eq "null" "$(echo "$out" | jget sms_required)"
end_test

start_test "flag_off_terraform_destroy_still_legacy_mixed"
  # legacy: destroy matches the MIXED iac pattern; irreversible re-tag is gated off
  PLAN='{"hypothesis":"teardown stack","steps":[{"command":"terraform destroy -auto-approve"}]}'
  out=$(classify availability AUTONOMY_FORWARD=0)
  assert_eq mixed "$(echo "$out" | jget risk_level)"
  assert_eq "null" "$(echo "$out" | jget band)"
end_test

# ─── AUTO band (reversible, no SMS, proceeds on timeout) ──────────────────────
start_test "on_readonly_low_to_AUTO"
  PLAN='{"hypothesis":"disk filling","steps":[{"command":"df -h; kubectl get pods"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1)
  assert_eq AUTO "$(echo "$out" | jget band)"
  assert_eq True "$(echo "$out" | jget auto_approve_recommended)"
  assert_eq False "$(echo "$out" | jget sms_required)"
  assert_eq True "$(echo "$out" | jget auto_proceed_on_timeout)"
end_test

start_test "on_reversible_mixed_nonP0_to_AUTO"
  PLAN='{"hypothesis":"bounce svc","hostname":"nl-gpu01","steps":[{"command":"docker restart frigate"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1)
  assert_eq mixed "$(echo "$out" | jget risk_level)"
  assert_eq AUTO "$(echo "$out" | jget band)"
  assert_eq False "$(echo "$out" | jget sms_required)"
end_test

# ─── AUTO_NOTICE (reversible + P0 => auto + SMS, operator Q4) ──────────────────
start_test "on_reversible_mixed_P0_to_AUTO_NOTICE_plus_sms"
  PLAN='{"hypothesis":"bounce svc","hostname":"nl-pve01","steps":[{"command":"docker restart frigate"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1)
  assert_eq AUTO_NOTICE "$(echo "$out" | jget band)"
  assert_eq True "$(echo "$out" | jget auto_approve_recommended)"
  assert_eq True "$(echo "$out" | jget sms_required)"
end_test

# ─── floor: never auto, always SMS where high ─────────────────────────────────
start_test "on_terraform_destroy_to_floor"
  PLAN='{"hypothesis":"teardown stack","steps":[{"command":"terraform destroy -auto-approve"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1)
  assert_eq high "$(echo "$out" | jget risk_level)"
  assert_eq POLL_PAUSE "$(echo "$out" | jget band)"
  assert_eq False "$(echo "$out" | jget auto_approve_recommended)"
  assert_eq True "$(echo "$out" | jget sms_required)"
  assert_contains "$out" "irreversible:iac-destroy"
end_test

start_test "on_mkfs_gap_closed_to_floor"
  # mkfs was UNMATCHED by legacy patterns -> could have been LOW/auto. Now floor.
  PLAN='{"hypothesis":"reformat scratch","steps":[{"command":"mkfs.ext4 /dev/sdb1"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1)
  assert_eq high "$(echo "$out" | jget risk_level)"
  assert_eq POLL_PAUSE "$(echo "$out" | jget band)"
  assert_contains "$out" "irreversible:disk-destroy"
end_test

start_test "on_reboot_to_floor_with_sms"
  PLAN='{"hypothesis":"stuck host","steps":[{"command":"reboot"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1)
  assert_eq high "$(echo "$out" | jget risk_level)"
  assert_eq POLL_PAUSE "$(echo "$out" | jget band)"
  assert_eq True "$(echo "$out" | jget sms_required)"
end_test

start_test "awx_runbooks_available_is_context_not_risk"
  # Runbooks merely ATTACHED as context (every plan gets the category's applicable
  # runbooks) must NOT force MIXED/POLL — else the gate polls 100% of sessions and
  # nothing ever auto-resolves. Read-only planned steps -> AUTO; availability is a signal.
  PLAN='{"hypothesis":"diagnose","awx_templates":[{"name":"restart-svc","description":"restart"}],"steps":[{"command":"kubectl get pods; df -h"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1)
  assert_eq low "$(echo "$out" | jget risk_level)"
  assert_eq AUTO "$(echo "$out" | jget band)"
end_test

start_test "actual_awx_launch_step_still_high_POLL_PAUSE"
  # An actual awx job launch in a planned STEP is a real mutation -> HIGH/POLL_PAUSE.
  PLAN='{"hypothesis":"remediate","awx_templates":[{"name":"patch","description":"x"}],"steps":[{"command":"curl -sk -X POST https://awx/api/v2/job_templates/5/launch/ -H Authorization"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1)
  assert_eq high "$(echo "$out" | jget risk_level)"
  assert_eq POLL_PAUSE "$(echo "$out" | jget band)"
  assert_eq False "$(echo "$out" | jget auto_proceed_on_timeout)"
end_test

# ─── operator-gated P0 reboot opt-in ──────────────────────────────────────────
start_test "P0_reboot_opt_in_to_AUTO_NOTICE"
  PLAN='{"hypothesis":"stuck","hostname":"nl-pve01","steps":[{"command":"reboot"}]}'
  out=$(classify availability AUTONOMY_FORWARD=1 AUTONOMY_P0_REBOOT_AUTO=1)
  assert_eq AUTO_NOTICE "$(echo "$out" | jget band)"
  assert_eq True "$(echo "$out" | jget sms_required)"
end_test

# ─── floor invariant: a corpus of irreversible ops NEVER reaches AUTO/AUTO_NOTICE
start_test "floor_corpus_never_auto"
  for cmd in "kubectl delete ns prod" "helm uninstall app" "tofu destroy" "zpool destroy rpool" "dropdb maindb" "rm -rf /srv/x" "clear crypto ikev2 sa"; do
    PLAN="{\"hypothesis\":\"x\",\"steps\":[{\"command\":\"$cmd\"}]}"
    out=$(classify availability AUTONOMY_FORWARD=1)
    band=$(echo "$out" | jget band)
    case "$band" in
      AUTO|AUTO_NOTICE) fail_test "irreversible '$cmd' reached $band (must be floor)";;
      *) : ;;
    esac
    assert_eq False "$(echo "$out" | jget auto_approve_recommended)" "auto for: $cmd"
  done
end_test

# ─── P0 host doc <-> constant drift ───────────────────────────────────────────
start_test "p0_hosts_doc_matches_constant"
  res=$(python3 - "$REPO_ROOT" <<'PY'
REDACTED_a7b84d63, sys, importlib.util, os
root = sys.argv[1]
spec = importlib.util.spec_from_file_location("c", os.path.join(root, "scripts/classify-session-risk.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
code = set(m._P0_HOSTS_BASE)
doc = open(os.path.join(root, "docs/host-blast-radius.md")).read()
block = re.search(r'p0_hosts:\n((?:\s*-\s*\S+\n)+)', doc)
docset = set(re.findall(r'-\s*(\S+)', block.group(1))) if block else set()
print("MATCH" if code == docset else f"DRIFT code-only={sorted(code-docset)} doc-only={sorted(docset-code)}")
PY
)
  assert_eq MATCH "$res"
end_test

# ─── schema v2: columns + version ─────────────────────────────────────────────
start_test "schema_v2_columns_present"
  tmp=$(mktemp --suffix=.db); sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  cols=$(sqlite3 "$tmp" "SELECT group_concat(name) FROM pragma_table_info('session_risk_audit')")
  assert_contains "$cols" "band"
  assert_contains "$cols" "auto_proceed_on_timeout"
  assert_contains "$cols" "sms_required"
  rm -f "$tmp"
  v=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import current; print(current('session_risk_audit'))")
  assert_eq 2 "$v"
end_test

# ─── audit-write persists the band ────────────────────────────────────────────
start_test "audit_row_persists_band"
  PLAN='{"hypothesis":"bounce","hostname":"nl-pve01","steps":[{"command":"docker restart frigate"}]}'
  # AUTONOMY_SMS_URL points at a dead port so the sms_required page is a no-op (hermetic).
  printf '%s' "$PLAN" | env GATEWAY_DB="$TESTDB" INFRAGRAPH_DISABLED=1 AUTONOMY_FORWARD=1 \
    AUTONOMY_SMS_URL="http://127.0.0.1:9/alert-session" \
    python3 "$CLS" --category availability --issue-id QA-1103 >/dev/null 2>&1
  row=$(sqlite3 "$TESTDB" "SELECT band||'|'||sms_required FROM session_risk_audit WHERE issue_id='QA-1103' ORDER BY id DESC LIMIT 1")
  assert_eq "AUTO_NOTICE|1" "$row"
end_test

# IFRNLLEI01PRD-1408 operator appetite: a NON-P0 host reboot -> AUTO_NOTICE (auto + SMS);
# a P0 host reboot stays POLL_PAUSE; sentinel OFF stays POLL_PAUSE. Sentinel pinned via env
# (a throwaway file) so the suite never touches the live ~/gateway.host_reboot_auto.
_HRA="$TESTDB.hra-on"; : > "$_HRA"
start_test "host_reboot_nonp0_auto_notice"
  PLAN='{"hypothesis":"kernel patch needs reboot","hostname":"nlapp01","steps":[{"command":"reboot"}]}'
  assert_eq AUTO_NOTICE "$(classify availability AUTONOMY_FORWARD=1 HOST_REBOOT_AUTO_SENTINEL="$_HRA" | jget band)"
end_test
start_test "host_reboot_p0_still_poll_pause"
  PLAN='{"hypothesis":"kernel patch needs reboot","hostname":"nl-pve03","steps":[{"command":"reboot"}]}'
  assert_eq POLL_PAUSE "$(classify availability AUTONOMY_FORWARD=1 HOST_REBOOT_AUTO_SENTINEL="$_HRA" | jget band)"
end_test
start_test "host_reboot_sentinel_off_poll_pause"
  PLAN='{"hypothesis":"kernel patch needs reboot","hostname":"nlapp01","steps":[{"command":"reboot"}]}'
  assert_eq POLL_PAUSE "$(classify availability AUTONOMY_FORWARD=1 HOST_REBOOT_AUTO_SENTINEL="$_HRA.absent" | jget band)"
end_test
rm -f "$_HRA"
