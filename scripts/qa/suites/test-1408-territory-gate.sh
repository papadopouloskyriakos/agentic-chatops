#!/usr/bin/env bash
# IFRNLLEI01PRD-1408 territory gate — resolver, PreToolUse hook, ack, and the
# sentinel-gated stateful relaxation. Hermetic: temp ack dir + temp sentinel.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1408-territory-gate"
LIB="$REPO_ROOT/scripts/lib/territory.py"
GATE="$REPO_ROOT/scripts/hooks/territory-gate.py"
ACK="$REPO_ROOT/scripts/hooks/territory-ack.py"
CLS="$REPO_ROOT/scripts/classify-session-risk.py"
CWD=/app/infrastructure/nl/production
export ACKTEST="/tmp/qa-territory-acks-$$"
# THROWAWAY sentinel via the TERRITORY_GATE_SENTINEL override — the suite must NEVER touch
# the live ~/gateway.territory_gate (doing so would turn the production gate off mid-run).
export TERRITORY_GATE_SENTINEL="$ACKTEST/sentinel"
SENT="$TERRITORY_GATE_SENTINEL"
mkdir -p "$ACKTEST"
trap 'rm -rf "$ACKTEST"' EXIT

# resolver field extractor
rfield() { python3 "$LIB" "$@" 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin).get('$RF'))"; }

# ── resolver: territory + stateful ───────────────────────────────────────────
RF=territory
start_test "resolve_kubectl_to_k8s";        assert_eq k8s     "$(rfield command='kubectl apply -f x')"; end_test
start_test "resolve_qm_to_pve";             assert_eq pve     "$(rfield command='qm reboot 999')"; end_test
start_test "resolve_netmiko_to_network";    assert_eq network "$(rfield command='netmiko push; show run')"; end_test
start_test "resolve_path_to_territory";     assert_eq network "$(rfield path=$CWD/network/devices.py)"; end_test
start_test "resolve_stateful_vmid_dominates_to_k8s"; assert_eq k8s "$(rfield command='qm reboot VMID_REDACTED')"; end_test
start_test "resolve_nonterritory_none";     assert_eq None    "$(rfield command='df -h; free -m')"; end_test
RF=is_stateful
start_test "stateful_k8s_ctrlr_true";       assert_eq True    "$(rfield host=nlk8s-ctrl01)"; end_test
start_test "stateful_syno_true";            assert_eq True    "$(rfield host=nl-nas01)"; end_test
start_test "stateful_gpu01_false";          assert_eq False   "$(rfield host=nl-gpu01 command='qm reboot VMID_REDACTED')"; end_test

# ── PreToolUse hook flow ─────────────────────────────────────────────────────
hook() {  # $1 json  -> exit code  (HOME points ack dir via env in the hook? no: hook uses /tmp/claude-territory-acks)
  printf '%s' "$1" | python3 "$GATE" >/dev/null 2>&1; echo $?
}
# isolate ack dir: the hook reads /tmp/claude-territory-acks; use a unique session id
SID="qa-$$"
rm -rf /tmp/claude-territory-acks/$SID.txt 2>/dev/null
jcmd() { printf '{"session_id":"%s","cwd":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}' "$SID" "$CWD" "$1"; }
jedit() { printf '{"session_id":"%s","cwd":"%s","tool_name":"Edit","tool_input":{"file_path":"%s"}}' "$SID" "$CWD" "$1"; }

rm -f "$SENT"
start_test "gate_off_is_noop";              assert_eq 0 "$(hook "$(jcmd 'kubectl apply -f x')")"; end_test
touch "$SENT"
start_test "readonly_allowed";              assert_eq 0 "$(hook "$(jcmd 'kubectl get pods')")"; end_test
start_test "highstakes_write_unacked_blocks"; assert_eq 2 "$(hook "$(jcmd 'kubectl apply -f x')")"; end_test
start_test "nonterritory_allowed";          assert_eq 0 "$(hook "$(jcmd 'df -h')")"; end_test
start_test "network_edit_unacked_blocks";   assert_eq 2 "$(hook "$(jedit $CWD/network/devices.py)")"; end_test
start_test "stateful_vmid_reboot_blocks_unacked"; assert_eq 2 "$(hook "$(jcmd 'qm reboot VMID_REDACTED')")"; end_test
# ack the k8s manual, then the k8s write is allowed
printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"%s/k8s/CLAUDE.md"}}' "$SID" "$CWD" | python3 "$ACK"
start_test "k8s_write_allowed_after_read";  assert_eq 0 "$(hook "$(jcmd 'kubectl apply -f x')")"; end_test
start_test "other_territory_still_blocked"; assert_eq 2 "$(hook "$(jedit $CWD/network/devices.py)")"; end_test
start_test "malformed_input_failopen";      assert_eq 0 "$(hook 'not json{{{')"; end_test
# cwd-scope: a Bash WRITE that merely mentions an infra verb but runs from a NON-infra cwd
# (gateway dev / meta / /tmp) is NOT gated — Edit/Write stays path-scoped.
jcmd_cwd() { printf '{"session_id":"%s","cwd":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}' "$SID" "$2" "$1"; }
start_test "gateway_cwd_write_not_gated"; assert_eq 0 "$(hook "$(jcmd_cwd 'kubectl apply -f x' "$REPO_ROOT")")"; end_test
start_test "tmp_cwd_write_not_gated";     assert_eq 0 "$(hook "$(jcmd_cwd 'helm upgrade x' /tmp)")"; end_test
# Edit of an infra path is gated regardless of cwd (path-scoped). Use the network
# territory (this SID acked only k8s above, so network is still unacked).
start_test "infra_path_edit_gated_any_cwd"; assert_eq 2 "$(hook "$(printf '{"session_id":"%s","cwd":"%s","tool_name":"Edit","tool_input":{"file_path":"%s/network/x.cfg"}}' "$SID" "$REPO_ROOT" "$CWD")")"; end_test
rm -f "$SENT"; rm -rf /tmp/claude-territory-acks/$SID.txt

# ── sentinel-gated stateful relaxation in the classifier ─────────────────────
band() { echo "$1" | env AUTONOMY_FORWARD=1 CONSERVATIVE_REMEDIATION=1 INFRAGRAPH_DISABLED=1 python3 "$CLS" --category resource --no-audit 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin)['band'])"; }
PETC='{"hypothesis":"fix","hostname":"nlk8s01","steps":[{"command":"kubectl rollout restart sts/etcd"}]}'
PDESTROY='{"hypothesis":"fix","hostname":"nlk8s01","steps":[{"command":"qm reboot 101; qm destroy 102"}]}'
rm -f "$SENT"
start_test "stateful_rollout_floor_when_gate_off"; assert_eq POLL_PAUSE "$(band "$PETC")"; end_test
touch "$SENT"
start_test "stateful_rollout_gate_governed_when_on"; assert_eq AUTO "$(band "$PETC")"; end_test
start_test "destructive_guest_op_blocks_either_way"; assert_eq POLL_PAUSE "$(band "$PDESTROY")"; end_test
rm -f "$SENT"

# ── Fail-CLOSED when the resolver is broken (adversarial-review hardening, commit 5249f1a) ──
# A silently-dead resolver must not wave through a confirmed infra write. Run a COPY of the
# hook against a deliberately-broken territory lib: BLOCK (exit 2) a confirmed infra write,
# but still fail OPEN (exit 0) for non-infra / unclassifiable work so a hook bug can't wedge.
FCDIR="$ACKTEST/fc"; mkdir -p "$FCDIR/hooks" "$FCDIR/lib"
cp "$GATE" "$FCDIR/hooks/territory-gate.py"
INFRA_FP="/app/infrastructure/nl/production/k8s/x.tf"
INFRA_CWD="/app/infrastructure/nl"
fchook() { printf '%s' "$1" | env TERRITORY_GATE_SENTINEL="$SENT" python3 "$FCDIR/hooks/territory-gate.py" >/dev/null 2>&1; echo $?; }
touch "$SENT"
printf 'raise RuntimeError("broken import")\n' > "$FCDIR/lib/territory.py"
start_test "failclosed_import_edit_into_infra_blocks"
  assert_eq 2 "$(fchook "{\"session_id\":\"x\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$INFRA_FP\"}}")"
end_test
start_test "failopen_import_edit_noninfra_allows"
  assert_eq 0 "$(fchook '{"session_id":"x","tool_name":"Edit","tool_input":{"file_path":"/tmp/scratch.txt"}}')"
end_test
start_test "failopen_import_bash_allows_no_wedge"
  assert_eq 0 "$(fchook "{\"session_id\":\"x\",\"cwd\":\"$INFRA_CWD\",\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"kubectl apply -f x\"}}")"
end_test
cat > "$FCDIR/lib/territory.py" <<'PY'
INFRA_ROOT = "/app/infrastructure"
def is_write_command(c): return True
def resolve(**k): raise RuntimeError("resolve boom")
PY
start_test "failclosed_resolve_throw_bash_write_in_infra_blocks"
  assert_eq 2 "$(fchook "{\"session_id\":\"x\",\"cwd\":\"$INFRA_CWD\",\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"kubectl apply -f x\"}}")"
end_test
start_test "failopen_resolve_throw_edit_noninfra_allows"
  assert_eq 0 "$(fchook '{"session_id":"x","tool_name":"Edit","tool_input":{"file_path":"/tmp/x.txt"}}')"
end_test
start_test "failclosed_disabled_when_sentinel_off"
  out=$(printf '%s' "{\"session_id\":\"x\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$INFRA_FP\"}}" | env TERRITORY_GATE_SENTINEL="$ACKTEST/nope" python3 "$FCDIR/hooks/territory-gate.py" >/dev/null 2>&1; echo $?)
  assert_eq 0 "$out"
end_test
rm -f "$SENT"
