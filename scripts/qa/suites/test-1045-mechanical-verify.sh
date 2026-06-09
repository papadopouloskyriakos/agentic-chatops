#!/usr/bin/env bash
# IFRNLLEI01PRD-1045 (mechanical verify) + -1039 (Phase B shadow + scorecard).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1045-mechanical-verify"
EVAL="$REPO_ROOT/scripts/infragraph-eval.py"
VERIFY="$REPO_ROOT/scripts/infragraph-verify.py"

FIXDB=$(mktemp --suffix=.db)
sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
FIXLOG=$(mktemp --suffix=.log)
cat > "$FIXLOG" << 'LOG'
2026-06-02T11:01:00Z|nl-n8n01|-- ALERT -- nl-n8n01 -  Service up/down  - Critical Alert|nl|escalated|0|0|IFR-A
2026-06-02T11:02:00Z|nl-gpu01|-- ALERT -- nl-gpu01 -  Device Down! Due to no ICMP response.  - Critical Alert|nl|escalated|0|0|IFR-B
2026-06-02T11:03:00Z|gr-sw01|-- ALERT -- gr-sw01 -  Device Down! Due to no ICMP response.  - Critical Alert|gr|escalated|0|0|IFR-C
LOG

# verdict matrix: three backdated action predictions against the same log
sqlite3 "$FIXDB" "
INSERT INTO infragraph_predictions (created_at, kind, parent_issue_id, parent_host, parent_rule, window_seconds, predicted, control_predicted, plan_hash, action_kind, action_target) VALUES
('2026-06-02 11:00:00', 'action', '', 'nl-pve01', 'reboot_host', 900,
 '[{\"host\": \"nl-n8n01\", \"rule\": \"Service up/down\"}, {\"host\": \"nl-gpu01\", \"rule\": \"Device Down! Due to no ICMP response.\"}, {\"host\": \"gr-sw01\", \"rule\": \"Device Down! Due to no ICMP response.\"}]', '[]', 'h-match', 'reboot_host', 'nl-pve01'),
('2026-06-02 11:00:00', 'action', '', 'nl-pve01', 'reboot_host', 900,
 '[{\"host\": \"nl-n8n01\", \"rule\": \"Device rebooted\"}, {\"host\": \"nl-gpu01\", \"rule\": \"Device Down! Due to no ICMP response.\"}, {\"host\": \"gr-sw01\", \"rule\": \"Device Down! Due to no ICMP response.\"}]', '[]', 'h-partial', 'reboot_host', 'nl-pve01'),
('2026-06-02 11:00:00', 'action', '', 'nl-pve01', 'reboot_host', 900,
 '[{\"host\": \"nl-n8n01\", \"rule\": \"Service up/down\"}]', '[]', 'h-dev', 'reboot_host', 'nl-pve01');
"

start_test "eval_pending_writes_mechanical_verdicts"
  out=$(python3 "$EVAL" --db "$FIXDB" --pending --no-notify --log "$FIXLOG")
  assert_contains "$out" '"action_verdicts": 3'
  v=$(sqlite3 "$FIXDB" "SELECT plan_hash || '=' || verdict FROM infragraph_predictions ORDER BY id")
  assert_eq "h-match=match
h-partial=partial
h-dev=deviation" "$v" "match / partial (predicted host, wrong rule) / deviation (unpredicted host)"
end_test

start_test "verdict_detail_carries_the_diff"
  d=$(sqlite3 "$FIXDB" "SELECT verdict_detail FROM infragraph_predictions WHERE plan_hash='h-dev'")
  s=$(printf '%s' "$d" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['surprises']), d['surprises'][0][0], len(d['matched']))")
  assert_eq "2 nl-gpu01 1" "$s" "two surprise hosts recorded, one matched"
end_test

start_test "verify_cli_exit_codes_encode_verdict"
  # fresh row, already past window — verify synchronously
  sqlite3 "$FIXDB" "INSERT INTO infragraph_predictions (created_at, kind, parent_issue_id, parent_host, parent_rule, window_seconds, predicted, plan_hash, action_kind, action_target) VALUES ('2026-06-02 11:00:00', 'action', '', 'nl-pve01', 'reboot_host', 900, '[{\"host\": \"nl-n8n01\", \"rule\": \"Service up/down\"}, {\"host\": \"nl-gpu01\", \"rule\": \"Device Down! Due to no ICMP response.\"}, {\"host\": \"gr-sw01\", \"rule\": \"Device Down! Due to no ICMP response.\"}]', 'h-v', 'reboot_host', 'nl-pve01')"
  pid=$(sqlite3 "$FIXDB" "SELECT MAX(id) FROM infragraph_predictions")
  python3 "$VERIFY" --db "$FIXDB" --prediction-id "$pid" --log "$FIXLOG" >/dev/null; rc=$?
  assert_eq 0 "$rc" "match -> exit 0"
  python3 "$VERIFY" --db "$FIXDB" --prediction-id 99999 --log "$FIXLOG" >/dev/null 2>&1; rc=$?
  assert_eq 4 "$rc" "not found -> exit 4"
end_test

start_test "verify_window_open_refuses"
  sqlite3 "$FIXDB" "INSERT INTO infragraph_predictions (created_at, kind, parent_host, parent_rule, window_seconds, predicted, plan_hash, action_kind, action_target) VALUES (datetime('now'), 'action', 'nl-pve01', 'reboot_host', 3600, '[]', 'h-open', 'reboot_host', 'nl-pve01')"
  pid=$(sqlite3 "$FIXDB" "SELECT MAX(id) FROM infragraph_predictions")
  out=$(python3 "$VERIFY" --db "$FIXDB" --prediction-id "$pid" --log "$FIXLOG"); rc=$?
  assert_eq 3 "$rc" "window open -> exit 3"
  assert_contains "$out" '"window_open": true'
  v=$(sqlite3 "$FIXDB" "SELECT verdict FROM infragraph_predictions WHERE id=$pid")
  assert_eq "" "$v" "no premature verdict written"
end_test

start_test "llm_has_no_verdict_write_path"
  # the only writers of verdict are lib.write_verdict callers: eval + verify
  writers=$(grep -rl --include="*.py" --include="*.sh" "write_verdict\|SET verdict=" "$REPO_ROOT/scripts" | grep -v "test-1045" | sort | tr '\n' ' ')
  assert_eq "$REPO_ROOT/scripts/infragraph-eval.py $REPO_ROOT/scripts/infragraph-verify.py $REPO_ROOT/scripts/lib/infragraph.py " "$writers"
  grep -q "invalid verdict" "$REPO_ROOT/scripts/lib/infragraph.py"; assert_eq 0 $? "vocabulary locked"
end_test

start_test "scorecard_emits_gate_evidence"
  out=$(python3 "$EVAL" --db "$FIXDB" --scorecard --log "$FIXLOG")
  s=$(printf '%s' "$out" | python3 -c "
import json,sys
sc = json.load(sys.stdin)['scorecard']
g = sc['gate_b_to_c']
print(sc['window_30d']['evaluated'] >= 4, 'all_met' in g, g['evaluated_ok'], sc['auto_resolve_baseline_30d']['counting_unit'])")
  assert_eq "True True False incident" "$s" "evidence present; gate correctly NOT met on tiny sample"
end_test

start_test "triage_step_2graph_records_shadow_predictions"
  grep -q -- "--record --issue" "$REPO_ROOT/openclaw/skills/infra-triage/infra-triage.sh"; assert_eq 0 $? "Phase B flag live in triage"
end_test

rm -f "$FIXDB" "$FIXLOG"
