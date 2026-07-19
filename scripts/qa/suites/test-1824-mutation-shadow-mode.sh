#!/bin/bash
# test-1824-mutation-shadow-mode.sh — global MUTATIONS=OFF (shadow) mode (IFRNLLEI01PRD-1824)
# Hermetic: forces shadow via MUTATIONS_OFF env (never touches the live sentinel/DB), isolated
# log dirs. Covers the hook classifier, lib, classify clamp, reconcile guard, bash helper, CLI.
# QA_SUITE_TIMEOUT: 120
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="test-1824-mutation-shadow-mode"

HOOK="$REPO_ROOT/scripts/hooks/mutation-shadow-gate.py"
LIB="$REPO_ROOT/scripts/lib/mutation_mode.py"
CLI="$REPO_ROOT/scripts/mutation-mode.py"

# hook helper: echo a Bash tool-call, return BLOCK/ALLOW
_hook() {  # $1=command ; env MUTATIONS_OFF/ISSUE_ID set by caller
  local rc
  echo "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")},\"session_id\":\"s\"}" \
    | python3 "$HOOK" >/dev/null 2>&1; rc=$?
  [ "$rc" = 2 ] && echo BLOCK || echo ALLOW
}

# ── hook: dark by default (no sentinel/env) ───────────────────────────────────
start_test "hook_dark_by_default_allows_mutation"
( unset MUTATIONS_OFF; export ISSUE_ID=T
  assert_eq "ALLOW" "$(_hook 'pct set 101 -memory 4096')" "no shadow → mutation allowed" )
end_test

# ── hook: shadow blocks infra actuation ───────────────────────────────────────
start_test "hook_blocks_infra_actuation_in_shadow"
export MUTATIONS_OFF=1 ISSUE_ID=T MUTATION_SHADOW_LOG_DIR="$(mktemp -d)"
assert_eq "BLOCK" "$(_hook "ssh nl-pve01 'pct set 101 -memory 4096'")" "ssh remote pct set"
assert_eq "BLOCK" "$(_hook 'kubectl delete pod x -n y')" "kubectl delete"
assert_eq "BLOCK" "$(_hook 'sudo systemctl restart cronicle')" "systemctl restart"
assert_eq "BLOCK" "$(_hook 'mkfs.ext4 /dev/sdb1')" "mkfs"
assert_eq "BLOCK" "$(_hook 'git push origin main')" "git push"
assert_eq "BLOCK" "$(_hook 'echo x > /etc/resolv.conf')" "redirect to /etc"
assert_eq "BLOCK" "$(_hook 'rm -rf /var/lib/foo')" "rm -rf /var"
assert_eq "BLOCK" "$(_hook 'scp /tmp/a h:/opt/b')" "scp to host"
assert_eq "BLOCK" "$(_hook 'curl -X POST $YT/api/issues/IFR-1?fields=customFields -d StateBundleElement')" "YT state-change"
assert_eq "BLOCK" "$(_hook 'curl -X POST $N8N/api/v1/workflows/abc/deactivate')" "n8n deactivate"
end_test

# ── hook: shadow allows reads / scratch / matrix / YT-comment / db ────────────
start_test "hook_allows_reads_and_reporting_in_shadow"
export MUTATIONS_OFF=1 ISSUE_ID=T
assert_eq "ALLOW" "$(_hook 'kubectl get pods -A')" "kubectl get"
assert_eq "ALLOW" "$(_hook 'cat /etc/hosts')" "read cat"
assert_eq "ALLOW" "$(_hook "ssh nl-pve01 'pct config 101'")" "ssh remote read"
assert_eq "ALLOW" "$(_hook 'pvesh get /cluster/resources')" "pvesh get"
assert_eq "ALLOW" "$(_hook 'echo x > /tmp/scratch.txt')" "redirect /tmp"
assert_eq "ALLOW" "$(_hook 'journalctl -u cronicle | grep -i error | tail -20')" "read pipeline"
assert_eq "ALLOW" "$(_hook 'kubectl get pods -A -o json | jq .items')" "kubectl get + jq"
assert_eq "ALLOW" "$(_hook 'curl -X POST $YT/api/issues/IFR-1/comments -d {\"text\":\"why\"}')" "YT comment"
assert_eq "ALLOW" "$(_hook 'curl -XPUT matrix.example.net/_matrix/client/v3/rooms/X/send/m.room.notice/t')" "matrix notice"
assert_eq "ALLOW" "$(_hook 'sqlite3 ~/gateway-state/gateway.db \"INSERT INTO event_log VALUES(1)\"')" "gateway.db write"
end_test

# ── hook: default-DENY blocks obfuscation/indirection (adversarial-review regressions) ────────────
start_test "hook_default_deny_blocks_obfuscation"
export MUTATIONS_OFF=1 ISSUE_ID=T
assert_eq "BLOCK" "$(_hook 'echo c3lzdGVtY3RsIHN0b3A= | base64 -d | bash')" "base64 | bash"
assert_eq "BLOCK" "$(_hook 'eval \"\$MUT\"')" "eval"
assert_eq "BLOCK" "$(_hook 'ssh nl-pve01 \"\$(cat /tmp/p.sh)\"')" "ssh command-substitution"
assert_eq "BLOCK" "$(_hook 'python3 -c \"import os;os.system(chr(114))\"')" "python -c"
assert_eq "BLOCK" "$(_hook 'systemctl stop crit.service  # gateway-state/gateway.db')" "mutation + allow-token comment"
assert_eq "BLOCK" "$(_hook 'systemctl restart pve-cluster & curl https://matrix/_matrix/client/v3/rooms/r/send/m.room.message')" "mutation & matrix (single &)"
assert_eq "BLOCK" "$(_hook 'rm -rf /etc/foo | tee gateway-state/gateway.db')" "mutation | db (single pipe)"
assert_eq "BLOCK" "$(_hook 'find /var/log -name x -delete')" "find -delete"
assert_eq "BLOCK" "$(_hook 'echo x > /etc/resolv.conf')" "safe verb + system redirect"
assert_eq "BLOCK" "$(_hook 'rm -f payload.json')" "rm (not a read) blocked by default-deny"
end_test

# ── hook: interactive (no ISSUE_ID) never gated ───────────────────────────────
start_test "hook_interactive_session_never_gated"
( export MUTATIONS_OFF=1; unset ISSUE_ID
  assert_eq "ALLOW" "$(_hook 'pct set 101 -memory 4096')" "no ISSUE_ID → not a dispatched session" )
end_test

# ── hook: compound command — any mutating segment blocks whole ────────────────
start_test "hook_compound_blocks_if_any_segment_mutates"
export MUTATIONS_OFF=1 ISSUE_ID=T
assert_eq "BLOCK" "$(_hook 'curl matrix.example.net/_matrix/client/v3/rooms/X/send/m.room.notice/t && pct set 101 -memory 4')" "matrix + pct set"
assert_eq "ALLOW" "$(_hook 'cat /etc/hosts && kubectl get pods')" "read + read"
end_test

# ── lib: is_shadow env + sentinel + log_wouldve ───────────────────────────────
start_test "lib_is_shadow_and_log_wouldve"
tmplog="$(mktemp -d)"
out=$( MUTATIONS_OFF=1 MUTATION_SHADOW_LOG_DIR="$tmplog" python3 -c "
import sys; sys.path.insert(0,'$REPO_ROOT/scripts/lib'); import mutation_mode as m
print('shadow', m.is_shadow()); m.log_wouldve('t-act', rationale='why', host='h1')
")
assert_contains "$out" "shadow True" "is_shadow via env"
assert_eq "1" "$(cat "$tmplog"/shadow-*.jsonl 2>/dev/null | grep -c 't-act')" "log_wouldve wrote a JSONL line"
off=$( MUTATIONS_OFF=0 python3 -c "import sys;sys.path.insert(0,'$REPO_ROOT/scripts/lib');import mutation_mode as m;print(m.is_shadow())")
assert_eq "False" "$off" "is_shadow False when env off"
end_test

# ── classify: shadow clamp forces non-auto (both flag states) ─────────────────
start_test "classify_clamp_forces_no_auto"
res=$( cd "$REPO_ROOT/scripts" && MUTATIONS_OFF=1 AUTONOMY_FORWARD=1 python3 - <<'PY'
import importlib.util,sys; sys.path.insert(0,'lib')
s=importlib.util.spec_from_file_location('csr','classify-session-risk.py'); c=importlib.util.module_from_spec(s); s.loader.exec_module(c)
r=c.classify({"actions":["systemctl status nginx"],"summary":"x","confidence":0.9},"availability")
print("OK" if (r.get("mutations_off") and not r.get("auto_approve_recommended") and r.get("band")=="POLL_PAUSE") else f"FAIL {r.get('mutations_off')},{r.get('auto_approve_recommended')},{r.get('band')}")
PY
)
assert_contains "$res" "OK" "classify clamp: mutations_off + no-auto + POLL_PAUSE"
end_test

# ── reconcile: _shadow() detection ────────────────────────────────────────────
start_test "reconcile_shadow_detection"
r=$( cd "$REPO_ROOT/scripts" && MUTATIONS_OFF=1 python3 -c "
import importlib.util,sys; sys.path.insert(0,'lib')
s=importlib.util.spec_from_file_location('rec','reconcile-completed-sessions.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
print(m._shadow())")
assert_eq "True" "$r" "reconcile _shadow() True in shadow"
end_test

# ── bash: mutation_shadow helper ──────────────────────────────────────────────
start_test "bash_mutation_shadow_helper"
if MUTATIONS_OFF=1 bash -c "source '$REPO_ROOT/scripts/lib/suppression-gates.sh'; mutation_shadow"; then
  assert_eq "0" "0" "mutation_shadow rc0 when MUTATIONS_OFF=1"
else
  fail_test "mutation_shadow should be rc0 in shadow"
fi
if MUTATIONS_OFF=0 bash -c "source '$REPO_ROOT/scripts/lib/suppression-gates.sh'; mutation_shadow"; then
  fail_test "mutation_shadow should be rc1 when off"
else
  assert_eq "0" "0" "mutation_shadow rc1 when off"
fi
# check_suppression_gates must be UNAFFECTED by MUTATIONS_OFF (observability preserved). We can't
# isolate its hardcoded /home/app-user/gateway.maintenance path, so assert its rc is IDENTICAL
# across shadow-on vs shadow-off (proves shadow doesn't leak into it, whatever the live maint state).
rc_on=$(MUTATIONS_OFF=1 bash -c "source '$REPO_ROOT/scripts/lib/suppression-gates.sh'; check_suppression_gates"; echo $?)
rc_off=$(MUTATIONS_OFF=0 bash -c "source '$REPO_ROOT/scripts/lib/suppression-gates.sh'; check_suppression_gates"; echo $?)
assert_eq "$rc_off" "$rc_on" "check_suppression_gates rc identical shadow-on vs off (shadow doesn't leak in)"
end_test

# ── CLI: off/on/status toggles the sentinel ───────────────────────────────────
start_test "cli_toggles_sentinel"
qh="$(mktemp -d)"
env_cli() { GATEWAY_HOME="$qh" MUTATION_MODE_PROM="$qh/m.prom" MUTATION_SHADOW_LOG_DIR="$qh/sl" MUTATION_MODE_LOG="$qh/mode.log" python3 "$CLI" "$@"; }
( unset MUTATIONS_OFF
  env_cli off --reason qa >/dev/null
  assert_file_exists "$qh/gateway.mutations_off" "off creates sentinel"
  assert_contains "$(env_cli status)" "OFF (shadow)" "status shows OFF"
  assert_contains "$(cat "$qh/m.prom")" "gateway_mutations_shadow_active 1" "prom active=1"
  env_cli on --reason qa >/dev/null
  assert_eq "0" "$(ls "$qh"/gateway.mutations_off 2>/dev/null | wc -l)" "on removes sentinel"
  assert_contains "$(cat "$qh/m.prom")" "gateway_mutations_shadow_active 0" "prom active=0" )
end_test
