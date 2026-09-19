#!/usr/bin/env bash
# IFRNLLEI01PRD-1305 — D14: the A2A agent cards are the authoritative single source of truth,
# enforced by check-a2a-card-drift.py (escalation graph + approval policy + model provenance).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="1305-a2a-card-drift"
V="$REPO_ROOT/scripts/check-a2a-card-drift.py"

# temp repo with just the cards + bridge, for negative (drift-injecting) tests
mk_repo() {
  local d; d=$(mktemp -d)
  mkdir -p "$d/a2a/agent-cards" "$d/workflows"
  cp "$REPO_ROOT"/a2a/agent-cards/*.json "$d/a2a/agent-cards/"
  cp "$REPO_ROOT"/workflows/claude-gateway-matrix-bridge.json "$d/workflows/"
  echo "$d"
}

start_test "live_cards_are_drift_free"
  out=$(python3 "$V" 2>&1); rc=$?
  assert_eq 0 "$rc" "live A2A cards pass the drift gate"
  assert_contains "$out" "no drift"
end_test

start_test "detects_stale_model_provenance"
  d=$(mk_repo)
  sed -i 's/claude-opus-4-8/claude-opus-4-6/' "$d/a2a/agent-cards/claude-code-t2.json"
  GATEWAY_A2A_REPO="$d" python3 "$V" >/dev/null 2>&1
  assert_eq 1 "$?" "a stale model on a card fails the gate"
  rm -rf "$d"
end_test

start_test "detects_approval_policy_drift"
  d=$(mk_repo)
  python3 -c "import json;p='$d/a2a/agent-cards/human-t3.json';x=json.load(open(p));x['_nla2a']['approvalPolicy']['timeoutPause']=9999;open(p,'w').write(json.dumps(x))"
  out=$(GATEWAY_A2A_REPO="$d" python3 "$V" 2>&1)
  assert_contains "$out" "approval drift"
  rm -rf "$d"
end_test

start_test "detects_incoherent_escalation_graph"
  d=$(mk_repo)
  # remove claude-code from human.acceptsFrom -> claude-code.escalateTo=human becomes incoherent
  python3 -c "import json;p='$d/a2a/agent-cards/human-t3.json';x=json.load(open(p));x['_nla2a']['routing']['acceptsFrom']=['openclaw'];open(p,'w').write(json.dumps(x))"
  out=$(GATEWAY_A2A_REPO="$d" python3 "$V" 2>&1)
  assert_contains "$out" "acceptsFrom does not include"
  rm -rf "$d"
end_test
