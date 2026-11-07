#!/usr/bin/env bash
# Harness² reuse R3 — harness fingerprint (scripts/lib/harness_fingerprint.py,
# scripts/hooks/harness-fingerprint.sh, scripts/stamp-harness-fingerprint.py).
# Stability, sensitivity to a one-byte skill edit, hook stamping into a throwaway DB
# (migration 029 applied there), first-stamp-wins, and the copy onto sessions/session_log.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="harness-fingerprint"
LIB="$REPO_ROOT/scripts/lib/harness_fingerprint.py"
HOOK="$REPO_ROOT/scripts/hooks/harness-fingerprint.sh"
STAMP="$REPO_ROOT/scripts/stamp-harness-fingerprint.py"
MIG="$REPO_ROOT/scripts/migrations/029_harness_fingerprint_and_reflection.sql"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"; mkdir -p "$HOME/.claude"
export GATEWAY_REPO="$TMP/gateway"; mkdir -p "$GATEWAY_REPO/config" "$GATEWAY_REPO/workflows"
REPO="$TMP/repo"; mkdir -p "$REPO/.claude/rules" "$REPO/.claude/skills/x" "$REPO/.claude/agents"
echo "# CLAUDE" > "$REPO/CLAUDE.md"; echo "rule" > "$REPO/.claude/rules/a.md"
printf -- '---\nname: x\ndescription: d\nversion: 1.0.0\n---\nbody\n' > "$REPO/.claude/skills/x/SKILL.md"
echo '[{"dimension":"a","category":"c","instruction":"i","active":true},{"dimension":"b","category":"c","instruction":"j","active":false}]' > "$GATEWAY_REPO/config/prompt-patches.json"
echo '{"hooks":{}}' > "$GATEWAY_REPO/config/dispatched-session-settings.json"
echo '{"nodes":[{"name":"Build Prompt","parameters":{"jsCode":"var a=1;"}}]}' > "$GATEWAY_REPO/workflows/claude-gateway-runner.json"
DB="$TMP/t.db"
sqlite3 "$DB" "CREATE TABLE sessions (issue_id TEXT, session_id TEXT, started_at TEXT); CREATE TABLE session_log (issue_id TEXT, session_id TEXT, ended_at TEXT); CREATE TABLE lessons_learned (id INTEGER PRIMARY KEY, issue_id TEXT, lesson TEXT, source TEXT, created_at TEXT);"
python3 "$REPO_ROOT/scripts/migrations/apply.py" --help >/dev/null 2>&1 || true
# apply migration 029 to the throwaway DB statement by statement (apply.py targets the live DB)
python3 - "$DB" "$MIG" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1]); sql = open(sys.argv[2]).read()
for stmt in sql.split(";\n"):
    s = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
    if s:
        try: conn.execute(s)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e) and "already exists" not in str(e): raise
conn.commit()
PY
export GATEWAY_DB="$DB"

start_test "compiles"
  python3 -m py_compile "$LIB" "$STAMP" || fail_test "py_compile"
  bash -n "$HOOK" || fail_test "bash -n hook"
end_test

start_test "fingerprint_is_stable_and_16_hex"
  a=$(python3 "$LIB" --repo "$REPO"); b=$(python3 "$LIB" --repo "$REPO")
  assert_eq "$a" "$b" "two computes agree"
  assert_eq 16 "${#a}" "length"
end_test

start_test "one_byte_skill_edit_changes_fp"
  a=$(python3 "$LIB" --repo "$REPO")
  echo "x" >> "$REPO/.claude/skills/x/SKILL.md"
  b=$(python3 "$LIB" --repo "$REPO")
  assert_ne "$a" "$b" "skill edit must change fp"
end_test

start_test "inactive_patch_does_not_change_fp"
  a=$(python3 "$LIB" --repo "$REPO")
  echo '[{"dimension":"a","category":"c","instruction":"i","active":true},{"dimension":"zz","category":"c","instruction":"new","active":false}]' > "$GATEWAY_REPO/config/prompt-patches.json"
  b=$(python3 "$LIB" --repo "$REPO")
  assert_eq "$a" "$b" "inactive patch ignored"
  echo '[{"dimension":"a","category":"c","instruction":"CHANGED","active":true}]' > "$GATEWAY_REPO/config/prompt-patches.json"
  c=$(python3 "$LIB" --repo "$REPO")
  assert_ne "$a" "$c" "active patch change must change fp"
end_test

start_test "json_lists_components"
  out=$(python3 "$LIB" --repo "$REPO" --json)
  assert_contains "$out" '"repo:CLAUDE.md"' "component listed"
  assert_contains "$out" '"gateway:build-prompt-jscode"' "build prompt listed"
end_test

start_test "hook_stamps_session_first_stamp_wins"
  echo '{"session_id":"sess-1","cwd":"'"$REPO"'"}' | CLAUDE_TERRITORY_ISSUE=IFRNLLEI01PRD-7 bash "$HOOK"; rc=$?
  assert_eq 0 "$rc" "hook exit 0"
  fp1=$(sqlite3 "$DB" "SELECT harness_fp FROM session_harness WHERE session_id='sess-1'")
  assert_eq 16 "${#fp1}" "stamped fp"
  assert_eq "IFRNLLEI01PRD-7" "$(sqlite3 "$DB" "SELECT issue_id FROM session_harness WHERE session_id='sess-1'")" "issue stamped"
  echo "y" >> "$REPO/CLAUDE.md"
  echo '{"session_id":"sess-1","cwd":"'"$REPO"'"}' | CLAUDE_TERRITORY_ISSUE=IFRNLLEI01PRD-7 bash "$HOOK"
  fp2=$(sqlite3 "$DB" "SELECT harness_fp FROM session_harness WHERE session_id='sess-1'")
  assert_eq "$fp1" "$fp2" "re-stamp keeps the first fingerprint"
  n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM harness_fingerprints")
  assert_ge "$n" 1 "dictionary row written"
end_test

start_test "hook_is_silent_and_exit0_without_session_id"
  out=$(echo '{}' | bash "$HOOK" 2>&1); rc=$?
  assert_eq 0 "$rc" "exit 0"
  assert_eq "" "$out" "silent"
end_test

start_test "stamp_script_copies_onto_sessions_and_session_log"
  sqlite3 "$DB" "INSERT INTO sessions (issue_id, session_id, started_at) VALUES ('IFRNLLEI01PRD-7','sess-1',datetime('now')); INSERT INTO session_log (issue_id, session_id, ended_at) VALUES ('IFRNLLEI01PRD-7','', datetime('now'));"
  out=$(python3 "$STAMP" --db "$DB" --json); rc=$?
  assert_eq 0 "$rc" "exit"
  assert_eq "$fp1" "$(sqlite3 "$DB" "SELECT harness_fp FROM sessions WHERE session_id='sess-1'")" "sessions stamped by session_id"
  assert_eq "$fp1" "$(sqlite3 "$DB" "SELECT harness_fp FROM session_log WHERE issue_id='IFRNLLEI01PRD-7'")" "session_log stamped by issue fallback"
end_test

start_test "stamp_script_skips_cleanly_without_migration"
  sqlite3 "$TMP/old.db" "CREATE TABLE sessions (issue_id TEXT, session_id TEXT);"
  out=$(python3 "$STAMP" --db "$TMP/old.db" --json); rc=$?
  assert_eq 0 "$rc" "exit"
  assert_contains "$out" 'not applied' "skip reason"
end_test
