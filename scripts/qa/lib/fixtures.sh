#!/usr/bin/env bash
# Fresh-DB + mocked-service fixtures for QA tests.
# shellcheck shell=bash
set -u

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"

# ------------------------------------------------------------------------------
# Fresh DB: new tempfile loaded with schema.sql + a fake schema_migrations row
# for 004/005 (our migrations start at 006).
# ------------------------------------------------------------------------------

fresh_db() {
  local tmp
  tmp=$(mktemp --suffix=.db) || return 1
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  sqlite3 "$tmp" "CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY, name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    filename TEXT NOT NULL);
  INSERT INTO schema_migrations VALUES ('004','content_preview_and_chaos_embedding','2026-04-01','004.sql');
  INSERT INTO schema_migrations VALUES ('005','wiki_source_mtime','2026-04-01','005.sql');"
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1 || true
  printf '%s' "$tmp"
}

cleanup_db() {
  [ -n "${1:-}" ] && [ -f "${1:-}" ] && rm -f "$1"
}

# ------------------------------------------------------------------------------
# Mocked Claude CLI: writes deterministic stream-json then exits 0.
#
# Usage (important — must export CLAUDE_BIN in the CALLER'S shell, not in a
# subshell, else $() would swallow the export):
#
#     make_mock_claude; export CLAUDE_BIN="$MOCK_CLAUDE_BIN"
#     ... ; unset_mock_claude
#
# Sets the global variable MOCK_CLAUDE_BIN to the absolute path of the mock.
# ------------------------------------------------------------------------------

make_mock_claude() {
  local dir=/tmp/.qa_mock_claude.$$
  mkdir -p "$dir"
  # Dump the received env-vars and prompt to a side file so tests can assert
  # on the environment / prompt that the parent passed in.
  cat > "$dir/claude" <<MOCK
#!/usr/bin/env bash
# Record the invocation environment + prompt for post-hoc assertions.
{
  env | grep -E '^(HANDOFF_INPUT_DATA_B64|ISSUE_ID|CLAUDE_SESSION_ID|TURN_ID|AGENT_NAME)='
  echo '--- ARGS ---'
  printf '%s\0' "\$@" | tr '\0' '\n'
  echo '--- END ---'
} > '$dir/last_invocation.txt' 2>/dev/null

printf '%s\n' '{"type":"system","subtype":"init","session_id":"mock-s"}'
printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"text","text":"mocked"}]}}'
printf '%s\n' '{"type":"result","subtype":"success","session_id":"mock-s","result":"mocked result\n- finding A\n- finding B\nCONFIDENCE: 0.72 \xe2\x80\x94 deterministic mock","is_error":false,"cost_usd":0.01,"num_turns":1}'
MOCK
  chmod +x "$dir/claude"
  export MOCK_CLAUDE_DIR="$dir"
  export MOCK_CLAUDE_BIN="$dir/claude"
  export MOCK_CLAUDE_LAST="$dir/last_invocation.txt"
}

unset_mock_claude() {
  [ -n "${MOCK_CLAUDE_DIR:-}" ] && [ -d "$MOCK_CLAUDE_DIR" ] && rm -rf "$MOCK_CLAUDE_DIR"
  unset MOCK_CLAUDE_DIR MOCK_CLAUDE_BIN CLAUDE_BIN 2>/dev/null || true
}

# Back-compat aliases (for any suite that hasn't migrated yet).
mock_claude_bin() { make_mock_claude; printf '%s' "$MOCK_CLAUDE_DIR"; }
cleanup_mock_claude() { unset_mock_claude; }

# ------------------------------------------------------------------------------
# Mocked Ollama/Haiku: route to localhost:9 (guaranteed unreachable) so the
# compact-handoff-history.py fall-through path exercises.
# ------------------------------------------------------------------------------

mock_ollama_unreachable() {
  export OLLAMA_URL="http://127.0.0.1:9"
}

# ------------------------------------------------------------------------------
# Seed a sessions row for tests that need one present.
# ------------------------------------------------------------------------------

seed_session() {
  local db="$1" issue="$2" session_id="${3:-sess-test}"
  sqlite3 "$db" "INSERT INTO sessions (issue_id, session_id, message_count, cost_usd, confidence, schema_version)
                 VALUES ('$issue','$session_id',0,0.0,0.0,1)"
}
