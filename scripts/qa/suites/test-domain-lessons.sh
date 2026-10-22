#!/usr/bin/env bash
# Harness² reuse R5 follow-up — domain-first lessons block (scripts/domain-lessons.py)
# and the llm_usage fingerprint stamp (migration 030 + stamp-harness-fingerprint.py).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="domain-lessons"
DL="$REPO_ROOT/scripts/domain-lessons.py"
STAMP="$REPO_ROOT/scripts/stamp-harness-fingerprint.py"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
DB="$TMP/t.db"
sqlite3 "$DB" <<'SQL'
CREATE TABLE lessons_learned (id INTEGER PRIMARY KEY, issue_id TEXT, lesson TEXT, source TEXT, created_at TEXT DEFAULT (datetime('now')),
  cue TEXT, evidence TEXT, confidence TEXT, verdict TEXT, domain TEXT, harness_fp TEXT, edits_json TEXT, schema_version INTEGER NOT NULL DEFAULT 1);
INSERT INTO lessons_learned (issue_id, lesson, source, cue, evidence, confidence, verdict, domain) VALUES
 ('IFRNLLEI01PRD-10','Reopen every written file before finishing','reflect-session','when a run writes multiple artefacts','base run skipped reopen in 2/2','high','entry','kubernetes/nl'),
 ('IFRNLLEI01PRD-11','Pin the aggregation grain','reflect-session','when aggregating per channel','grain mismatch observed','medium','entry','kubernetes/nl'),
 ('IFRNLLEI01PRD-12','NO_ENTRY','reflect-session',NULL,NULL,NULL,'no_entry','kubernetes/nl'),
 ('MESHSAT-5','Dev lesson','reflect-session','when building the kit','ci failed','low','entry','dev/MESHSAT');
CREATE TABLE session_harness (session_id TEXT PRIMARY KEY, issue_id TEXT, harness_fp TEXT NOT NULL, repo TEXT, stamped_at TEXT DEFAULT (datetime('now')), schema_version INTEGER DEFAULT 1);
INSERT INTO session_harness VALUES ('s1','IFRNLLEI01PRD-10','abcd1234abcd1234','r',datetime('now'),1);
CREATE TABLE sessions (issue_id TEXT, session_id TEXT, harness_fp TEXT);
CREATE TABLE session_log (issue_id TEXT, session_id TEXT, harness_fp TEXT);
CREATE TABLE llm_usage (id INTEGER PRIMARY KEY, tier INTEGER, model TEXT, issue_id TEXT, cost_usd REAL, recorded_at TEXT, harness_fp TEXT);
INSERT INTO llm_usage (tier, model, issue_id, cost_usd, recorded_at) VALUES (2,'opus','IFRNLLEI01PRD-10',1.0,datetime('now')),(2,'opus','IFRNLLEI01PRD-99',1.0,datetime('now'));
SQL

start_test "compiles"
  python3 -m py_compile "$DL" "$STAMP" || fail_test "py_compile"
end_test

start_test "domain_block_lists_entries_not_no_entry"
  out=$(python3 "$DL" --issue IFRNLLEI01PRD-77 --category kubernetes --db "$DB"); rc=$?
  assert_eq 0 "$rc" "exit"
  assert_contains "$out" "kubernetes/nl" "domain title"
  assert_contains "$out" "when a run writes multiple artefacts" "cue of entry 1"
  assert_contains "$out" "Pin the aggregation grain" "lesson of entry 2"
  assert_not_contains "$out" "NO_ENTRY" "no_entry rows excluded"
  assert_not_contains "$out" "Dev lesson" "other domain excluded"
end_test

start_test "dev_issue_uses_project_domain"
  out=$(python3 "$DL" --issue MESHSAT-9 --db "$DB")
  assert_contains "$out" "dev/MESHSAT" "dev domain"
  assert_contains "$out" "Dev lesson" "dev entry"
end_test

start_test "b64_round_trips"
  b=$(python3 "$DL" --issue IFRNLLEI01PRD-77 --category kubernetes --db "$DB" --b64)
  dec=$(printf '%s' "$b" | base64 -d)
  assert_contains "$dec" "kubernetes/nl" "decoded block"
end_test

start_test "empty_domain_prints_nothing_exit0"
  out=$(python3 "$DL" --issue IFRGRSKG01PRD-3 --category storage --db "$DB"); rc=$?
  assert_eq 0 "$rc" "exit"; assert_eq "" "$out" "empty"
end_test

start_test "pre_migration_schema_is_fail_open"
  sqlite3 "$TMP/old.db" "CREATE TABLE lessons_learned (id INTEGER PRIMARY KEY, issue_id TEXT, lesson TEXT, source TEXT, created_at TEXT);"
  out=$(python3 "$DL" --issue IFRNLLEI01PRD-1 --db "$TMP/old.db"); rc=$?
  assert_eq 0 "$rc" "exit"; assert_eq "" "$out" "empty"
end_test

start_test "stamp_fills_llm_usage_by_issue"
  out=$(python3 "$STAMP" --db "$DB" --json); rc=$?
  assert_eq 0 "$rc" "exit"
  assert_eq "abcd1234abcd1234" "$(sqlite3 "$DB" "SELECT harness_fp FROM llm_usage WHERE issue_id='IFRNLLEI01PRD-10'")" "llm_usage stamped"
  assert_eq "" "$(sqlite3 "$DB" "SELECT COALESCE(harness_fp,'') FROM llm_usage WHERE issue_id='IFRNLLEI01PRD-99'")" "unknown issue stays NULL"
end_test

start_test "metamorphic_monitor_mentions_fingerprint_restriction"
  grep -q 'harness_fp restriction' "$REPO_ROOT/scripts/metamorphic-monitor.sh" || fail_test "monitor not fingerprint-aware"
end_test

start_test "prompt_improver_carries_form"
  grep -q "PATCH_FORM" "$REPO_ROOT/scripts/prompt-improver.py" && grep -q "'form': form" "$REPO_ROOT/scripts/prompt-improver.py" || fail_test "form field missing"
end_test

start_test "mr_review_gates_on_validator"
  grep -q 'HARNESS_NEW_PROBLEMS' "$REPO_ROOT/scripts/mr-review.sh" && grep -q 'validate-harness-tree.py' "$REPO_ROOT/.claude/commands/review.md" || fail_test "review wiring missing"
end_test

start_test "category_table_matches_build_prompt"
  python3 - "$REPO_ROOT" <<'PYQA' || fail_test "BP_CATEGORY_RULES differs from the Runner Build Prompt regex table"
import json, re, sys
root = sys.argv[1]; sys.path.insert(0, root + "/scripts")
from lib.reflection import BP_CATEGORY_RULES, classify_alert_category
w = json.load(open(root + "/workflows/claude-gateway-runner.json"))
code = next(n for n in w["nodes"] if n["name"] == "Build Prompt")["parameters"]["jsCode"]
js = re.findall(r"if \(/((?:[^/\\]|\\.)+)/\.test\(combined\)\) alertCategory = '(\w+)';", code)
assert js, "no category rules found in Build Prompt"
assert [(p, c) for p, c in js] == [(p, c) for p, c in BP_CATEGORY_RULES], (js, BP_CATEGORY_RULES)
assert classify_alert_category("nl-pve01 Device up/down", "") == "availability"
assert classify_alert_category("KubePodCrashLooping", "pod restarting") == "availability"  # "ping" in CrashLooping wins first, exactly like Build Prompt
assert classify_alert_category("KubeClientErrors", "pod restarts") == "kubernetes"
assert classify_alert_category("something else", "") == "general"
PYQA
end_test

start_test "summary_description_drive_the_domain"
  out=$(python3 "$DL" --issue IFRNLLEI01PRD-77 --summary "KubeClientErrors on nlk8s-ctrl01" --db "$DB")
  assert_contains "$out" "kubernetes/nl" "classified from summary"
end_test
