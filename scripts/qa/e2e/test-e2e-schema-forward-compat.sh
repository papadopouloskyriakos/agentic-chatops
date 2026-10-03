#!/usr/bin/env bash
# E2E — schema forward-compat fail-fast.
#
# Scenario: a row gets written with schema_version=99 (simulating a future
# writer). Readers MUST refuse to decode rather than silently mis-interpret.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="e2e-schema-forward-compat"
tmp=$(fresh_db)

start_test "reader_raises_SchemaVersionError_on_future_row"
  cd "$REPO_ROOT/scripts"
  sqlite3 "$tmp" "INSERT INTO session_transcripts (issue_id, session_id, chunk_index, role, content, schema_version) VALUES ('Q','s',0,'user','x',99)"
  assert_exit_code 1 env GATEWAY_DB="$tmp" PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
from schema_version import check_row
import sqlite3
conn = sqlite3.connect('$tmp')
row = conn.execute(\"SELECT schema_version FROM session_transcripts WHERE issue_id='Q'\").fetchone()
check_row('session_transcripts', row[0])
"
  assert_contains "$_qa_last_stderr" "SchemaVersionError"
end_test

start_test "reader_accepts_current_and_legacy_v1"
  cd "$REPO_ROOT/scripts"
  sqlite3 "$tmp" "INSERT INTO session_transcripts (issue_id, session_id, chunk_index, role, content, schema_version) VALUES ('Q2','s',0,'user','x',1)"
  assert_exit_code 0 env PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
from schema_version import check_row
check_row('session_transcripts', 1)
check_row('session_transcripts', None)  # legacy row — treated as 1
"
end_test

start_test "envelope_reader_rejects_future_handoff_version"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 1 env PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
import base64, json, zlib
from handoff import HandoffInputData
# Simulate a future sender.
data = {'issue_id':'X','from_agent':'a','to_agent':'b','envelope_version':2}
b64 = base64.urlsafe_b64encode(zlib.compress(json.dumps(data).encode())).decode()
HandoffInputData.from_b64(b64)
"
  assert_contains "$_qa_last_stderr" "envelope_version"
end_test

cleanup_db "$tmp"
