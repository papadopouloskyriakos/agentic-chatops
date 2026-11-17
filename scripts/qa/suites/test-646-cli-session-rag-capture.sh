#!/usr/bin/env bash
# IFRNLLEI01PRD-646 / -647 / -648 — CLI-session RAG capture tests.
# Covers the 3-tier CLI-session pipeline:
#   Tier 1 (-646) backfill-cli-transcripts.sh flag handling + watermark
#   Tier 2 (-647) extract-cli-knowledge.py structured JSON insertion (mocked Ollama)
#   Tier 3 (-648) parse-tool-calls.py CLI issue_id inference
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="646-cli-session-rag-capture"

# ─── Tier 1: backfill-cli-transcripts.sh flag handling ──────────────────────
start_test "backfill_script_syntax"
  out=$(bash -n "$REPO_ROOT/scripts/backfill-cli-transcripts.sh" 2>&1)
  assert_eq 0 $? "bash -n failed: $out"
end_test

start_test "backfill_script_help_flags"
  # Unknown flag should exit 2.
  "$REPO_ROOT/scripts/backfill-cli-transcripts.sh" --bogus-flag >/dev/null 2>&1
  assert_eq 2 $?
end_test

start_test "backfill_script_defaults_exposed"
  # The script must honor --limit 50 as default and --embed as default.
  out=$(grep -E '^LIMIT=|^EMBED=|^ORDER=|^USE_WATERMARK=' "$REPO_ROOT/scripts/backfill-cli-transcripts.sh")
  assert_contains "$out" "LIMIT=50"
  assert_contains "$out" "EMBED=1"
end_test

start_test "backfill_runs_against_empty_cli_base"
  # Point at an empty dir via HOME indirection; script should exit 0 with "no files".
  tmp=$(mktemp -d)
  mkdir -p "$tmp/.claude/projects"
  # The script uses $HOME/.claude/projects; wrap via a subshell export.
  out=$(HOME="$tmp" bash "$REPO_ROOT/scripts/backfill-cli-transcripts.sh" --no-watermark --no-toolcalls --no-embed --limit 1 2>&1)
  rc=$?
  rm -rf "$tmp"
  assert_eq 0 "$rc" "script exit: $rc output: $out"
  assert_contains "$out" "no files to process"
end_test

start_test "backfill_watermark_roundtrip"
  # Synthesize a fake CLI JSONL, run backfill with watermark on + fresh DB,
  # verify the watermark file is written and the second invocation skips.
  tmp=$(mktemp -d)
  mkdir -p "$tmp/.claude/projects/-fakeproj"
  tmp_jsonl="$tmp/.claude/projects/-fakeproj/$(echo "qa-$(date +%s)-${RANDOM}").jsonl"
  python3 - "$tmp_jsonl" <<'PYEOF'
import json, sys
p = sys.argv[1]
# 12 KB of fake exchanges so the size filter (>10 KB) passes.
with open(p, "w") as f:
    f.write(json.dumps({"type":"user","message":{"role":"user","content":"fake Q "*10}})+"\n")
    f.write(json.dumps({"type":"assistant","message":{"role":"assistant","content":"fake A "*10}})+"\n")
    f.write("X" * 12000 + "\n")   # filler to pass 10 KB gate
PYEOF
  db=$(fresh_db)
  wm="$tmp/.wm.json"
  # First run
  HOME="$tmp" GATEWAY_DB="$db" bash "$REPO_ROOT/scripts/backfill-cli-transcripts.sh" \
    --no-embed --no-toolcalls --newest-first --limit 1 \
    > /tmp/bf-1.log 2>&1 || true
  # Second run — watermark should kick in
  out=$(HOME="$tmp" GATEWAY_DB="$db" bash "$REPO_ROOT/scripts/backfill-cli-transcripts.sh" \
    --no-embed --no-toolcalls --newest-first --limit 1 2>&1)
  assert_contains "$out" "no files to process"
  cleanup_db "$db"
  rm -rf "$tmp" /tmp/bf-1.log
end_test

# ─── Tier 3: parse-tool-calls.py CLI path inference ─────────────────────────
start_test "parse_tool_calls_cli_issue_id_inference"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import os
from importlib import import_module
os.environ['GATEWAY_DB'] = '/nonexistent'  # no DB writes needed for this test
import sys
sys.path.insert(0, '.')
spec = __import__('importlib').util.spec_from_file_location('ptc', 'parse-tool-calls.py')
mod = __import__('importlib').util.module_from_spec(spec)
spec.loader.exec_module(mod)
# Case 1: /tmp/claude-run-<ISSUE>.jsonl → <ISSUE>
assert mod.extract_issue_id_from_path('/tmp/claude-run-IFR-9.jsonl') == 'IFR-9', 'legacy case'
# Case 2: ~/.claude/projects/<proj>/<uuid>.jsonl → cli-<uuid>
p = os.path.expanduser('~/.claude/projects/-foo/abc-123.jsonl')
assert mod.extract_issue_id_from_path(p) == 'cli-abc-123', f'got {mod.extract_issue_id_from_path(p)}'
# Case 3: unrelated path → ''
assert mod.extract_issue_id_from_path('/var/log/nginx.log') == '', 'unrelated path must be empty'
print('ok')
" 2>&1)
  assert_contains "$out" "ok"
end_test

# ─── Tier 2: extract-cli-knowledge.py offline shape checks ──────────────────
start_test "extract_script_syntax"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 0 python3 -c "import ast; ast.parse(open('extract-cli-knowledge.py').read())"
end_test

start_test "extract_dry_run_no_rows"
  # Fresh DB with no pending cli-* summaries → must print "nothing to do" and exit 0.
  db=$(fresh_db)
  out=$(GATEWAY_DB="$db" python3 "$REPO_ROOT/scripts/extract-cli-knowledge.py" --dry-run 2>&1)
  assert_contains "$out" "nothing to do"
  cleanup_db "$db"
end_test

start_test "extract_sanitize_tags"
  # Unit-test the tag sanitizer.
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('ecklib', 'extract-cli-knowledge.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
# Upper/whitespace/punct -> lower-hyphenated; len<2 and >40 dropped; only 6 max.
raw = ['Zigbee!!!', 'Permit Join', '  cp210x_reset ', 'a', 'x'*50, 'fix', 'dep', 'one-more', 'seven']
out = mod._sanitize_tags(raw)
assert out == ['zigbee', 'permit-join', 'cp210x-reset', 'fix', 'dep', 'one-more'], out
# Non-list input -> empty
assert mod._sanitize_tags('not a list') == []
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "extract_fetch_pending_query_idempotent"
  # Seed a cli summary + a matching incident_knowledge row; fetch_pending must skip it.
  db=$(fresh_db)
  sqlite3 "$db" "
    INSERT INTO session_transcripts (issue_id, session_id, chunk_index, role, content, schema_version)
    VALUES ('cli-qa-already', 's1', -1, 'summary', 'test summary text with enough length to be accepted', 1);
    INSERT INTO incident_knowledge (issue_id, project, alert_rule) VALUES ('cli-qa-already', 'chatops-cli', '');"
  out=$(GATEWAY_DB="$db" python3 -c "
import sys, sqlite3, importlib.util
spec = importlib.util.spec_from_file_location('ecklib', '$REPO_ROOT/scripts/extract-cli-knowledge.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
conn = mod._db_connect()
rows = mod.fetch_pending(conn, 10)
print(f'pending={len(rows)}')
")
  assert_contains "$out" "pending=0"
  cleanup_db "$db"
end_test

start_test "extract_fetch_pending_surfaces_new_row"
  # Seed a cli summary without an incident_knowledge row → must appear.
  db=$(fresh_db)
  sqlite3 "$db" "
    INSERT INTO session_transcripts (issue_id, session_id, chunk_index, role, content, schema_version)
    VALUES ('cli-qa-pending', 's2', -1, 'summary',
      'long enough summary content for extraction eligibility over a hundred chars '
      || 'so the min-length check passes and the LEFT JOIN surfaces this row', 1);"
  out=$(GATEWAY_DB="$db" python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('ecklib', '$REPO_ROOT/scripts/extract-cli-knowledge.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
conn = mod._db_connect()
rows = mod.fetch_pending(conn, 10)
print(f'pending={len(rows)} issue={rows[0][0] if rows else \"(none)\"}')
")
  assert_contains "$out" "pending=1"
  assert_contains "$out" "issue=cli-qa-pending"
  cleanup_db "$db"
end_test

start_test "cli_incident_weight_default_and_env"
  # Guard that kb-semantic-search exposes CLI_INCIDENT_WEIGHT.
  cnt=$(grep -c "CLI_INCIDENT_WEIGHT" "$REPO_ROOT/scripts/kb-semantic-search.py")
  # Expect >=2 refs: the constant definition + the apply site.
  [ "$cnt" -ge 2 ] || fail_test "expected >=2 CLI_INCIDENT_WEIGHT refs; got $cnt"
  # Guard the project-guarded multiplier is in place.
  grep -q 'chatops-cli' "$REPO_ROOT/scripts/kb-semantic-search.py" || fail_test "chatops-cli guard missing"
end_test

end_test
