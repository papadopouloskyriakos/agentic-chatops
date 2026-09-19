#!/usr/bin/env bash
# IFRNLLEI01PRD-940 — tag-based MESHSAT slot disambiguation across 3 sibling
# repos (meshsat / meshsat-hub / meshsat-android). Exercises resolve-issue-slot.sh
# (offline via _TAGS_OVERRIDE — deterministic, no network), the slot-config
# wiring, and that both live workflow exports carry the resolver node.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="940-meshsat-slot-routing"

H=/home/app-user/gateway-state/bin/resolve-issue-slot.sh
RESOLVE=/home/app-user/gateway-state/bin/resolve-slot.sh
SLOTCFG=/home/app-user/gateway-state/slot-config.json

mock() { _TAGS_OVERRIDE="$1" bash "$H" "$2" 2>/dev/null; }

start_test "untagged_meshsat_defaults_to_meshsat"
  assert_eq "meshsat" "$(mock '[]' MESHSAT-1)" "no tags -> meshsat"
end_test

start_test "hub_tag_routes_to_meshsat_hub"
  assert_eq "meshsat-hub" "$(mock '[{"name":"meshsat-hub"}]' MESHSAT-2)" "canonical tag"
  assert_eq "meshsat-hub" "$(mock '[{"name":"hub"}]' MESHSAT-2)" "short alias"
end_test

start_test "android_tag_routes_to_meshsat_android"
  assert_eq "meshsat-android" "$(mock '[{"name":"meshsat-android"}]' MESHSAT-3)" "canonical tag"
  assert_eq "meshsat-android" "$(mock '[{"name":"android"}]' MESHSAT-3)" "short alias"
end_test

start_test "no_false_substring_match"
  assert_eq "meshsat" "$(mock '[{"name":"github"}]' MESHSAT-4)" "github must NOT match hub"
  assert_eq "meshsat" "$(mock '[{"name":"hub-extras"}]' MESHSAT-4)" "hub-extras must NOT match hub"
end_test

start_test "mixed_case_tag_matches"
  assert_eq "meshsat-hub" "$(mock '[{"name":"Meshsat-Hub"}]' MESHSAT-5)"
end_test

start_test "android_wins_when_both_tags_present"
  assert_eq "meshsat-android" "$(mock '[{"name":"hub"},{"name":"android"}]' MESHSAT-6)"
end_test

start_test "non_meshsat_issue_prints_nothing"
  # non-MESHSAT issues keep the caller's prefix-derived slot
  assert_eq "" "$(mock '[{"name":"hub"}]' CUBEOS-9)"
  assert_eq "" "$(mock '[{"name":"android"}]' IFRNLLEI01PRD-1)"
end_test

start_test "always_exits_zero_failsafe"
  assert_exit_code 0 env _TAGS_OVERRIDE='[]' bash "$H" MESHSAT-7
  assert_exit_code 0 bash "$H"            # no arg -> exit 0, empty stdout
  assert_exit_code 0 bash "$H" CUBEOS-1   # non-meshsat -> exit 0
end_test

start_test "slot_config_has_three_meshsat_slots_and_is_valid_json"
  assert_exit_code 0 jq -e . "$SLOTCFG"
  keys="$(jq -r 'keys[]' "$SLOTCFG")"
  for s in meshsat meshsat-hub meshsat-android; do
    assert_contains "$keys" "$s" "slot-config.json has slot $s"
  done
end_test

start_test "distinct_cwds_and_lockfiles_enable_parallel_dispatch"
  assert_contains "$(bash "$RESOLVE" meshsat-hub cwd)" "/meshsat-hub"
  assert_contains "$(bash "$RESOLVE" meshsat-android cwd)" "/meshsat-android"
  assert_ne "$(bash "$RESOLVE" meshsat-hub cwd)" "$(bash "$RESOLVE" meshsat cwd)" "hub cwd != meshsat cwd"
  assert_ne "$(bash "$RESOLVE" meshsat-android cwd)" "$(bash "$RESOLVE" meshsat-hub cwd)" "android != hub cwd"
end_test

start_test "runner_export_wired_for_tag_routing"
  RUNNER="$REPO_ROOT/workflows/claude-gateway-runner.json"
  assert_file_exists "$RUNNER"
  body="$(cat "$RUNNER")"
  assert_contains "$body" "Resolve MESHSAT Slot" "Runner has the resolver SSH node"
  assert_contains "$body" "resolve-issue-slot.sh" "Runner invokes the helper"
  assert_contains "$body" "meshsat-hub" "Runner Derive Slot knows meshsat-hub"
  assert_contains "$body" "meshsat-android" "Runner Derive Slot knows meshsat-android"
end_test

start_test "bridge_export_wired_for_tag_routing"
  BRIDGE="$REPO_ROOT/workflows/claude-gateway-matrix-bridge.json"
  assert_file_exists "$BRIDGE"
  body="$(cat "$BRIDGE")"
  assert_contains "$body" "Resolve MESHSAT Slot" "Bridge has the resolver SSH node"
  assert_contains "$body" "meshsat-hub" "Bridge Derive Slot knows meshsat-hub"
  assert_contains "$body" "meshsat-android" "Bridge Derive Slot knows meshsat-android"
end_test
