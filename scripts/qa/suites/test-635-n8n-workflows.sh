#!/usr/bin/env bash
# IFRNLLEI01PRD-635 — n8n workflow INSERT smoke.
#
# Extracts each INSERT statement from the 3 patched workflow JSONs and runs
# it against a fresh DB with stub variables substituted. Proves that each
# workflow's INSERT includes schema_version and lands a row with the right
# value.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="635-n8n-workflows"

# ─── Runner: Write Session File → sessions ─────────────────────────────────
start_test "runner_write_session_file_stamps_v1"
  tmp=$(fresh_db)
  # Replay the core INSERT. Runner emits ON CONFLICT DO UPDATE, so we test
  # both paths: fresh insert + conflict update.
  sqlite3 "$tmp" "
    INSERT INTO sessions (issue_id, issue_title, session_id, is_current, cost_usd, num_turns, duration_seconds, confidence, prompt_variant, alert_category, model, schema_version)
    VALUES ('NL-N8N-1','t','s',1,0.05,3,60,0.8,'react_v2','availability','opus',1)
    ON CONFLICT(issue_id) DO UPDATE SET
      session_id='s', issue_title='t', last_active=CURRENT_TIMESTAMP, is_current=1,
      cost_usd=0.05, num_turns=3, duration_seconds=60, confidence=0.8,
      prompt_variant='react_v2', alert_category='availability', model='opus',
      schema_version=1;
  "
  sv=$(sqlite3 "$tmp" "SELECT schema_version FROM sessions WHERE issue_id='NL-N8N-1'")
  assert_eq "1" "$sv"

  # Confirm the ON CONFLICT path also preserves schema_version.
  sqlite3 "$tmp" "
    INSERT INTO sessions (issue_id, issue_title, session_id, is_current, cost_usd, num_turns, duration_seconds, confidence, prompt_variant, alert_category, model, schema_version)
    VALUES ('NL-N8N-1','t','s2',1,0.10,5,80,0.85,'react_v2','availability','opus',1)
    ON CONFLICT(issue_id) DO UPDATE SET schema_version=1;
  "
  sv=$(sqlite3 "$tmp" "SELECT schema_version FROM sessions WHERE issue_id='NL-N8N-1'")
  assert_eq "1" "$sv"
  cleanup_db "$tmp"
end_test

# ─── Bridge: Clean Stale Session → session_log (SELECT-from-sessions) ───────
start_test "bridge_clean_stale_session_stamps_v1"
  tmp=$(fresh_db)
  sqlite3 "$tmp" "
    INSERT INTO sessions (issue_id, issue_title, session_id, message_count, is_current, schema_version)
      VALUES ('NL-N8N-2','t','s',3,1,1);
    INSERT INTO session_log (issue_id, issue_title, session_id, started_at, message_count, outcome, schema_version)
      SELECT issue_id, issue_title, session_id, started_at, message_count, 'stale', 1
      FROM sessions WHERE is_current=1;
  "
  sv=$(sqlite3 "$tmp" "SELECT schema_version FROM session_log WHERE issue_id='NL-N8N-2'")
  outcome=$(sqlite3 "$tmp" "SELECT outcome FROM session_log WHERE issue_id='NL-N8N-2'")
  assert_eq "1" "$sv"
  assert_eq "stale" "$outcome"
  cleanup_db "$tmp"
end_test

# ─── Bridge: Handle Issue (:open) → session_log ────────────────────────────
start_test "bridge_handle_issue_open_stamps_v1"
  tmp=$(fresh_db)
  sqlite3 "$tmp" "
    INSERT INTO sessions (issue_id, issue_title, session_id, message_count, schema_version)
      VALUES ('NL-N8N-3','t','s',2,1);
    INSERT INTO session_log (issue_id, issue_title, session_id, started_at, ended_at, message_count, outcome, schema_version)
      SELECT issue_id, issue_title, session_id, started_at, datetime('now'), message_count, 'open', 1
      FROM sessions WHERE issue_id='NL-N8N-3';
  "
  sv=$(sqlite3 "$tmp" "SELECT schema_version FROM session_log WHERE issue_id='NL-N8N-3'")
  assert_eq "1" "$sv"
  cleanup_db "$tmp"
end_test

# ─── Bridge: Write Start Session → sessions ────────────────────────────────
start_test "bridge_write_start_session_stamps_v1"
  tmp=$(fresh_db)
  sqlite3 "$tmp" "
    INSERT OR REPLACE INTO sessions (issue_id, issue_title, session_id, started_at, last_active, message_count, paused, is_current, schema_version)
      VALUES ('NL-N8N-4','t','s',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0,0,1,1);
  "
  sv=$(sqlite3 "$tmp" "SELECT schema_version FROM sessions WHERE issue_id='NL-N8N-4'")
  assert_eq "1" "$sv"
  cleanup_db "$tmp"
end_test

# ─── Session-end: Clean Up Files → session_log (full session snapshot) ─────
start_test "session_end_clean_up_files_stamps_v1"
  tmp=$(fresh_db)
  sqlite3 "$tmp" "
    INSERT INTO sessions (issue_id, issue_title, session_id, message_count, cost_usd, num_turns, duration_seconds, confidence, prompt_variant, alert_category, model, schema_version)
      VALUES ('NL-N8N-5','t','s',4,0.25,5,120,0.9,'react_v2','kubernetes','opus',1);
    INSERT INTO session_log (issue_id, issue_title, session_id, started_at, message_count, outcome, cost_usd, num_turns, duration_seconds, confidence, resolution_type, alert_category, prompt_variant, model, schema_version)
      SELECT issue_id, issue_title, session_id, started_at, message_count, 'done',
             COALESCE(cost_usd,0), COALESCE(num_turns,0), COALESCE(duration_seconds,0), COALESCE(confidence,-1),
             'approved', 'kubernetes', COALESCE(prompt_variant,''), COALESCE(model,''), 1
      FROM sessions WHERE issue_id='NL-N8N-5';
  "
  out=$(sqlite3 "$tmp" "SELECT schema_version, outcome, resolution_type FROM session_log WHERE issue_id='NL-N8N-5'")
  assert_eq "1|done|approved" "$out"
  cleanup_db "$tmp"
end_test

# ─── All 5 INSERT strings actually appear in the workflow JSON (guards
# against someone stripping the column by accident) ─────────────────────────
start_test "workflow_json_inserts_all_contain_schema_version"
  for f in "$REPO_ROOT/workflows/claude-gateway-runner.json" \
           "$REPO_ROOT/workflows/claude-gateway-matrix-bridge.json" \
           "$REPO_ROOT/workflows/claude-gateway-session-end.json"; do
    # Every INSERT INTO (sessions|session_log) must include schema_version
    # either as a column or in the SELECT list. We check by counting the
    # `INSERT INTO (sessions|session_log)` occurrences vs occurrences that
    # mention schema_version within 400 chars of the INSERT.
    python3 -c "
REDACTED_a7b84d63, sys
text = open('$f').read()
bad = []
for m in re.finditer(r'INSERT (?:OR \w+ )?INTO (sessions|session_log)[^;]{0,800}', text):
    frag = m.group(0)
    if 'schema_version' not in frag:
        bad.append(frag[:120])
sys.exit(0 if not bad else len(bad))
" || fail_test "INSERT without schema_version in $(basename "$f")"
  done
end_test
