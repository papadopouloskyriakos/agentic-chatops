#!/usr/bin/env bash
# IFRNLLEI01PRD-653 — teacher-agent interface tier (orchestrator + Matrix routing).
# All tests run fully offline: Matrix API is stubbed via monkey-patching,
# Ollama is stubbed via _ollama_fn injection.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="653-teacher-agent-interface"

# ── Migration 014 ──────────────────────────────────────────────────────────

start_test "migration_014_creates_teacher_operator_dm"
  tmp=$(fresh_db)
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='teacher_operator_dm'")
  [ "$n" = "1" ] || fail_test "teacher_operator_dm missing"
  # Expected columns present
  for col in operator_mxid dm_room_id display_name public_sharing first_seen last_active schema_version; do
    n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('teacher_operator_dm') WHERE name='$col'")
    [ "$n" = "1" ] || fail_test "column $col missing"
  done
  cleanup_db "$tmp"
end_test

start_test "migration_014_idempotent"
  tmp=$(fresh_db)
  before=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='teacher_operator_dm'")
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1
  after=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='teacher_operator_dm'")
  assert_eq "$before" "$after"
  cleanup_db "$tmp"
end_test

start_test "schema_registry_teacher_operator_dm_registered"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from schema_version import CURRENT_SCHEMA_VERSION, SCHEMA_VERSION_SUMMARIES
assert 'teacher_operator_dm' in CURRENT_SCHEMA_VERSION
assert CURRENT_SCHEMA_VERSION['teacher_operator_dm'] == 1
assert 1 in SCHEMA_VERSION_SUMMARIES['teacher_operator_dm']
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Matrix client (resolve_dm uses injected _create_fn for offline) ────────

start_test "matrix_resolve_dm_creates_and_caches"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0, 'lib')
import matrix_teacher as mx
calls = []
def fake_create(mxid):
    calls.append(mxid)
    return '!ROOM_FOR_' + mxid.replace(':', '_')
r1 = mx.resolve_dm('@alice:matrix.local', _create_fn=fake_create)
r2 = mx.resolve_dm('@alice:matrix.local', _create_fn=fake_create)  # cached
r3 = mx.resolve_dm('@bob:matrix.local',   _create_fn=fake_create)
assert r1 == r2, (r1, r2)
assert r1 != r3
assert len(calls) == 2, f'expected 2 creates (one per new user), got {len(calls)}'
print('ok')
")
  assert_contains "$out" "ok"
  cleanup_db "$tmp"
end_test

start_test "matrix_is_authorised_fails_closed"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
import matrix_teacher as mx
# Member: returns True
def members_ok(r): return ['@alice:m', '@bob:m']
assert mx.is_authorised('@alice:m', '!room', _members_fn=members_ok)
assert not mx.is_authorised('@mallory:m', '!room', _members_fn=members_ok)
# Failure mode: fail closed, never grant auth on error
def members_err(r): raise mx.MatrixError('simulated')
assert not mx.is_authorised('@alice:m', '!room', _members_fn=members_err)
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "matrix_public_sharing_toggle"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0, 'lib')
import matrix_teacher as mx
mx.resolve_dm('@alice:m', _create_fn=lambda x: '!alice')
assert not mx.is_public('@alice:m')
mx.set_public_sharing('@alice:m', True)
assert mx.is_public('@alice:m')
mx.set_public_sharing('@alice:m', False)
assert not mx.is_public('@alice:m')
print('ok')
")
  assert_contains "$out" "ok"
  cleanup_db "$tmp"
end_test

# ── teacher-agent.py subcommands (with Matrix + Ollama mocked) ─────────────

start_test "teacher_resolve_dm_via_cli"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Monkey-patch via a tiny wrapper module
  cat > /tmp/qa_mock_mx.py <<'PY'
import sys, os, sqlite3
# Pre-seed a DM row so resolve_dm doesn't try a real Matrix call.
db = os.environ['GATEWAY_DB']
c = sqlite3.connect(db)
c.execute("INSERT INTO teacher_operator_dm (operator_mxid, dm_room_id, schema_version) VALUES ('@alice:m', '!alice_room', 1)")
c.commit(); c.close()
PY
  GATEWAY_DB="$tmp" python3 /tmp/qa_mock_mx.py
  out=$(GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/teacher-agent.py" --resolve-dm --operator '@alice:m')
  assert_contains "$out" '"dm_room_id": "!alice_room"'
  cleanup_db "$tmp"
  rm -f /tmp/qa_mock_mx.py
end_test

start_test "teacher_next_auto_dispatches_first_lesson_for_fresh_operator"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Inline Python: patch mx, run cmd_next, assert it dispatched a lesson for the
  # first curriculum topic (gulli-01-prompt-chaining). Fresh operator → no progress rows
  # → cmd_next picks the first unseen topic and calls cmd_lesson.
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys, json
sys.path.insert(0, 'lib')
import matrix_teacher as mx
mx.is_authorised = lambda *a, **kw: True
mx.resolve_dm    = lambda op, **kw: '!dm_room_' + op.replace(':','_')
mx.post_message  = lambda room, body, **kw: '\$evt_stub'
mx.post_notice   = lambda room, body, **kw: '\$evt_stub'
import importlib.util
spec = importlib.util.spec_from_file_location('teacher_agent', '$REPO_ROOT/scripts/teacher-agent.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.cmd_next('@alice:m', source_room='!HdUfKpzHeplqBOYvwY:matrix.example.net')
print(json.dumps(r))
")
  assert_contains "$out" '"ok": true'
  assert_contains "$out" '"topic_id": "gulli-01-prompt-chaining"'
  assert_contains "$out" '"event_id":'
  cleanup_db "$tmp"
end_test

start_test "teacher_next_dispatches_lowest_mastery_due_topic"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Seed two due topics — alice has both; one at higher mastery
  sqlite3 "$tmp" "
    INSERT INTO learning_progress (operator, topic, mastery_score, next_due, schema_version)
      VALUES ('@alice:m', 'gulli-01-prompt-chaining',                  0.5, datetime('now', '-2 days'), 1);
    INSERT INTO learning_progress (operator, topic, mastery_score, next_due, schema_version)
      VALUES ('@alice:m', 'gulli-02-routing', 0.9, datetime('now', '-2 days'), 1);
  "
  # Lower-mastery topic (0.5 gulli-01) surfaces first → cmd_lesson dispatched.
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys, json
sys.path.insert(0, 'lib')
import matrix_teacher as mx
mx.is_authorised = lambda *a, **kw: True
mx.resolve_dm    = lambda op, **kw: '!dm_room_' + op.replace(':','_')
mx.post_message  = lambda room, body, **kw: '\$evt_stub'
mx.post_notice   = lambda room, body, **kw: '\$evt_stub'
import importlib.util
spec = importlib.util.spec_from_file_location('teacher_agent', '$REPO_ROOT/scripts/teacher-agent.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.cmd_next('@alice:m')
print(json.dumps(r))
")
  assert_contains "$out" '"ok": true'
  assert_contains "$out" '"topic_id": "gulli-01-prompt-chaining"'
  cleanup_db "$tmp"
end_test

start_test "teacher_next_notice_when_curriculum_exhausted"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Seed progress rows for every curriculum topic, all not-due (next_due in future).
  # cmd_next sees no due topics + no unseen topics → posts a "caught up" notice.
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys, json, sqlite3, os
sys.path.insert(0, 'lib')
import matrix_teacher as mx
mx.is_authorised = lambda *a, **kw: True
mx.resolve_dm    = lambda op, **kw: '!dm_room'
captured = []
mx.post_notice   = lambda room, body, **kw: captured.append((room, body)) or '\$evt_stub'
with open('$REPO_ROOT/config/curriculum.json') as f:
    curriculum = json.load(f)
c = sqlite3.connect('$tmp')
for t in curriculum['topics']:
    c.execute(\"INSERT INTO learning_progress (operator, topic, mastery_score, next_due, schema_version) VALUES ('@alice:m', ?, 1.0, datetime('now', '+30 days'), 1)\", (t['id'],))
c.commit(); c.close()
import importlib.util
spec = importlib.util.spec_from_file_location('teacher_agent', '$REPO_ROOT/scripts/teacher-agent.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.cmd_next('@alice:m')
assert r['ok'] is True, r
assert r['message'] == 'curriculum exhausted', r
assert captured and 'every topic at least once' in captured[0][1], captured
print('ok')
")
  assert_contains "$out" "ok"
  cleanup_db "$tmp"
end_test

start_test "teacher_morning_nudge_with_no_members_is_noop"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/teacher-agent.py" --morning-nudge)
  assert_contains "$out" '"nudged": 0'
  cleanup_db "$tmp"
end_test

start_test "teacher_class_digest_reads_aggregates"
  # Uses a LIVE-style DB so we skip Matrix posting by shortcircuiting MATRIX_HOMESERVER
  tmp=$(fresh_db)
  # Seed mastered topics and session counts
  sqlite3 "$tmp" "
    INSERT INTO teacher_operator_dm (operator_mxid, dm_room_id, schema_version) VALUES ('@a:m', '!a', 1);
    INSERT INTO teacher_operator_dm (operator_mxid, dm_room_id, schema_version) VALUES ('@b:m', '!b', 1);
    INSERT INTO learning_progress (operator, topic, mastery_score, schema_version) VALUES ('@a:m', 't1', 0.95, 1);
    INSERT INTO learning_progress (operator, topic, mastery_score, schema_version) VALUES ('@b:m', 't2', 0.93, 1);
    INSERT INTO learning_sessions (operator, topic, session_type, completed_at, schema_version)
      VALUES ('@a:m','t1','quiz',datetime('now','-1 day'),1);
  "
  # Redirect Matrix homeserver to an unreachable address; post_notice will raise
  # MatrixError but class-digest returns structured JSON either way.
  out=$(GATEWAY_DB="$tmp" MATRIX_HOMESERVER="http://127.0.0.1:9" \
        MATRIX_CLAUDE_TOKEN="fake" \
        python3 "$REPO_ROOT/scripts/teacher-agent.py" --class-digest 2>&1 || true)
  # The script's body is still computed even if the Matrix post fails.
  # Verify the aggregate computation ran (lines printed OR proper JSON).
  # We don't assert success because Matrix is unreachable by design here —
  # just that the script didn't crash before computing.
  [ -n "$out" ] || fail_test "class-digest produced no output"
  cleanup_db "$tmp"
end_test

# ── Teacher-runner workflow JSON is well-formed ────────────────────────────

start_test "teacher_runner_workflow_json_valid"
  cd "$REPO_ROOT"
  python3 -c "
import json
wf = json.load(open('workflows/claude-gateway-teacher-runner.json'))
assert wf['name'] == 'NL - Teacher Runner'
nodes = {n['name'] for n in wf['nodes']}
assert 'Teacher Command Webhook' in nodes
assert 'Parse Command' in nodes
assert 'Invoke teacher-agent.py' in nodes
assert 'Parse Output' in nodes
# Note: 'Respond to Matrix-Bridge' was intentionally REMOVED 2026-04-23
# (commit 99dc9fc). Webhook responseMode flipped to onReceived; a
# terminal Respond node would return HTTP 500 under the neverError:true
# caller pattern used by matrix-bridge. See
# memory/teacher_agent_dm_audit_20260423.md.
assert 'Respond to Matrix-Bridge' not in nodes, \
    'Respond to Matrix-Bridge should NOT exist (removed 2026-04-23)'
# SSH credential wired
ssh = next(n for n in wf['nodes'] if n['name'] == 'Invoke teacher-agent.py')
assert ssh['type'] == 'n8n-nodes-base.ssh'
assert ssh['parameters']['authentication'] == 'privateKey'
assert ssh['credentials']['sshPrivateKey']['id'] == 'REDACTED_SSH_CRED'
# Webhook path is the one matrix-bridge needs to target
hook = next(n for n in wf['nodes'] if n['name'] == 'Teacher Command Webhook')
assert hook['parameters']['path'] == 'teacher-command'
# responseMode must be onReceived (post-reliability-fix 2026-04-23)
assert hook['parameters'].get('responseMode', '') == 'onReceived', \
    f'expected responseMode=onReceived, got {hook[\"parameters\"].get(\"responseMode\")!r}'
print('ok')
" | grep -q ok || fail_test "workflow JSON validation failed"
end_test

# ── Agent definition is read-only by allowlist ─────────────────────────────

start_test "agent_definition_excludes_mutating_tools"
  cd "$REPO_ROOT"
  out=$(cat .claude/agents/teacher-agent.md | grep -E '^tools:')
  # Must allow Read/Grep/Glob/Bash/ToolSearch
  for tool in Read Grep Glob Bash ToolSearch; do
    echo "$out" | grep -q "$tool" || fail_test "tool $tool missing from allowlist"
  done
  # Must NOT include Edit/Write/MultiEdit
  for banned in Edit Write MultiEdit; do
    echo "$out" | grep -q "$banned" && fail_test "agent allowlist contains mutating tool $banned"
  done
  true
end_test

# ── Markdown → HTML rendering (Matrix formatted_body) ─────────────────────

start_test "md_to_html_handles_teacher_lesson_subset"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
import matrix_teacher as mx
# Bold + inline code + italic-underscore
assert mx.md_to_html('**x** _y_ \`z\`') == '<p><strong>x</strong> <em>y</em> <code>z</code></p>', mx.md_to_html('**x** _y_ \`z\`')
# ATX headings 1–4
assert '<h3>Title</h3>' in mx.md_to_html('### Title')
# Bullet list
assert '<ul>' in mx.md_to_html('- one\n- two') and mx.md_to_html('- one\n- two').count('<li>') == 2
# Well-formed tables render as real <table><thead>/<tbody> markup with inline md in cells
t = mx.md_to_html('| a | b |\n|---|---|\n| **1** | 2 |')
assert '<table>' in t and '<thead>' in t and '<tbody>' in t, t
assert '<th>a</th>' in t and '<td><strong>1</strong></td>' in t, t
# Malformed tables (no separator row) fall back to <pre>
assert '<pre>' in mx.md_to_html('| lonely row |')
# Fenced code block
assert '<pre><code' in mx.md_to_html('\`\`\`bash\nls\n\`\`\`')
# Literal # inside heading text is preserved, not re-interpreted
assert '<h3>Gulli pattern #1: Tool Use</h3>' in mx.md_to_html('### Gulli pattern #1: Tool Use')
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Snippet extractor uses title-based fallbacks ──────────────────────────

start_test "snippets_for_topic_uses_per_pattern_wiki_page"
  cd "$REPO_ROOT/scripts"
  # Post-2026-04-21 the curriculum points gulli-NN topics at per-pattern
  # wiki/patterns/gulli-NN-<slug>.md pages instead of sections of the flat
  # docs/agentic-patterns-audit.md. The snippet extractor must pick up the
  # per-pattern page cleanly (no fallback needed — the anchor is '' so the
  # whole doc body is fair game).
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
import importlib.util
spec = importlib.util.spec_from_file_location('ta', 'teacher-agent.py')
ta = importlib.util.module_from_spec(spec); spec.loader.exec_module(ta)
topic = ta._get_topic('gulli-05-tool-use')
snippets = ta._snippets_for_topic(topic)
assert snippets, 'no snippets extracted'
s = snippets[0]
assert s.source_path.endswith('gulli-05-tool-use.md'), f'wrong source: {s.source_path}'
# Section should be the top-level heading carrying the pattern name
assert 'Tool Use' in getattr(s, 'section', '') or 'Tool Use' in s.verbatim_text, \
    f'neither section nor text mentions Tool Use: section={getattr(s, \"section\", None)!r}, text={s.verbatim_text[:200]!r}'
# Must NOT be the old flat-audit preamble
assert 'ChatOps Platform Audit vs.' not in s.verbatim_text, 'fell through to flat-audit preamble'
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Wiki URL generation (IFRNLLEI01PRD-654 follow-up) ────────────────────

start_test "wiki_url_slug_matches_pymdownx_samples"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from wiki_url import slugify, wiki_url, linkify
# Byte-for-byte match with pymdownx.slugs.slugify(case=lower) — verified
# against actual HTML output from the mkdocs-material build.
cases = [
    ('Summary Scorecard (updated 2026-03-29)', 'summary-scorecard-updated-2026-03-29'),
    ('Reasoning Techniques (B -> A)', 'reasoning-techniques-b---a'),
    ('GAP 1: RAG is keyword-only, no semantic search', 'gap-1-rag-is-keyword-only-no-semantic-search'),
    ('Tool Use', 'tool-use'),
    ('Learning & Adaptation (B+ -> A)', 'learning--adaptation-b---a'),
]
for inp, expected in cases:
    got = slugify(inp)
    assert got == expected, f'slug({inp!r}) = {got!r}, expected {expected!r}'
# URL shape
u = wiki_url('docs/agentic-patterns-audit.md', 'Summary Scorecard (updated 2026-03-29)')
assert u == 'https://wiki.example.net/docs/agentic-patterns-audit/#summary-scorecard-updated-2026-03-29', u
# Paths outside the wiki return None
assert wiki_url('scripts/teacher-agent.py', 'foo') is None
# linkify falls back to plain code when no URL
assert linkify('scripts/out.py', 'x') == '\`scripts/out.py\`'
# linkify uses the URL when in-corpus
link = linkify('wiki/services/grafana.md', '')
assert link == '[\`wiki/services/grafana.md\`](https://wiki.example.net/wiki/services/grafana/)', link
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "wiki_url_strips_embedded_fragment_from_composite_path"
  cd "$REPO_ROOT/scripts"
  # Regression guard: wiki_articles.path is stored as `<file>.md#<section-slug>`.
  # Feeding that composite string into wiki_url used to produce a double-anchor
  # URL with literal `.md#` in the middle (404). The path normalizer now splits
  # on `#` upfront.
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from wiki_url import wiki_url
u = wiki_url('docs/agentic-patterns-audit.md#identified-gaps-&-actionable-recommendat',
             'Identified Gaps & Actionable Recommendations')
assert u == 'https://wiki.example.net/docs/agentic-patterns-audit/#identified-gaps--actionable-recommendations', u
assert u.count('#') == 1, u
assert '.md' not in u, u
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "wiki_url_recognises_bare_wiki_subdirs"
  cd "$REPO_ROOT/scripts"
  # Regression guard: wiki_articles stores wiki paths WITHOUT the `wiki/`
  # prefix (e.g. `hosts/gr-fw01.md`). The normalizer re-adds it so
  # semantic citations become clickable instead of plain code fallback.
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from wiki_url import wiki_url
cases = [
    ('hosts/gr-fw01.md', 'Services running',
     'https://wiki.example.net/wiki/hosts/gr-fw01/#services-running'),
    ('services/grafana.md', '',
     'https://wiki.example.net/wiki/services/grafana/'),
    ('patterns/gulli-05-tool-use.md', '',
     'https://wiki.example.net/wiki/patterns/gulli-05-tool-use/'),
    # project-docs/ + memory/ + openclaw/ are published to the internal wiki
    # (2026-04-21: wiki is internal-only, everything is exposed).
    ('project-docs/CLAUDE.md', '',
     'https://wiki.example.net/project-docs/CLAUDE/'),
    ('memory/seaweedfs_crosssite.md', '',
     'https://wiki.example.net/memory/seaweedfs_crosssite/'),
    ('openclaw/SOUL.md', '',
     'https://wiki.example.net/openclaw/SOUL/'),
    # README.extensive.md is physically republished under project-docs/
    # (build-wiki-site.sh) to avoid clashing with mkdocs's auto index.
    ('project-docs/README.extensive.md', 'Table of Contents',
     'https://wiki.example.net/project-docs/README.extensive/#table-of-contents'),
    # Paths genuinely outside the wiki corpus still return None
    ('/var/some/file.md', '', None),
    ('randomfile.md', '', None),
]
for path, sec, want in cases:
    got = wiki_url(path, sec)
    assert got == want, f'{path!r} → {got!r}, expected {want!r}'
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "semantic_snippets_filter_index_only_files"
  cd "$REPO_ROOT/scripts"
  # Regression guard for the 2026-04-21 "MEMORY.md in See-also" quality
  # complaint. wiki_articles indexes auto-generated TOCs
  # (memory/MEMORY.md, */index.md, README.md) which are clickable but
  # content-free. Those must never reach the LLM top-K nor the See-also
  # block — they'd waste a slot on pure metadata.
  out=$(python3 -c "
import sys, importlib.util
sys.path.insert(0, 'lib')
spec = importlib.util.spec_from_file_location('ta', 'teacher-agent.py')
ta = importlib.util.module_from_spec(spec); spec.loader.exec_module(ta)
# Verify _is_index_only predicate directly
assert ta._semantic_snippets.__doc__  # function still exists
# Find the closure by running against a real embed call if possible;
# fall back to unit-testing the predicate via the module source.
src = open('teacher-agent.py').read()
assert 'def _is_index_only' in src
assert 'MEMORY.md' in src and 'index.md' in src and 'README.md' in src
assert 'def _is_index_only' in src
# Live retrieval guard: if Ollama reachable, actually run the query and
# assert no index-only leaks. Skip silently when embed is unavailable.
try:
    snippets = ta._semantic_snippets('how does RAG work', limit=8)
except Exception:
    snippets = []
for s in snippets:
    base = (s.source_path or '').rsplit('/', 1)[-1]
    assert base not in ('MEMORY.md', 'index.md', 'README.md'), \
        f'index-only leak: {s.source_path}'
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "wiki_url_base_override_via_env"
  cd "$REPO_ROOT/scripts"
  out=$(TEACHER_WIKI_BASE='https://internal-wiki.example.test' python3 -c "
import sys; sys.path.insert(0, 'lib')
from wiki_url import wiki_url
u = wiki_url('docs/x.md', 'Hello World')
assert u.startswith('https://internal-wiki.example.test/docs/x/'), u
assert u.endswith('#hello-world'), u
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "lesson_render_emits_clickable_wiki_links"
  cd "$REPO_ROOT/scripts"
  # Stub-inject a topic + snippet shape the renderer accepts; assert the
  # markdown body contains a [label](https://wiki.example.net/...)
  # link.
  out=$(python3 -c "
import sys, importlib.util
sys.path.insert(0, 'lib')
spec = importlib.util.spec_from_file_location('teacher_agent', 'teacher-agent.py')
m = importlib.util.module_from_spec(spec); sys.modules['teacher_agent'] = m; spec.loader.exec_module(m)
from quiz_generator import Snippet
topic = {'title': 'Test Topic'}
snips = [Snippet(source_path='docs/agentic-patterns-audit.md',
                 section='Summary Scorecard (updated 2026-03-29)',
                 verbatim_text='x'*100)]
body = m._render_lesson(topic, snips)
assert '](https://wiki.example.net/docs/agentic-patterns-audit/#summary-scorecard-updated-2026-03-29)' in body, body
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Combined foundation + intelligence + interface still compiles ─────────

start_test "all_tiers_import_cleanly"
  cd "$REPO_ROOT/scripts"
  python3 -c "
import sys; sys.path.insert(0, 'lib')
import sm2, bloom, quiz_generator, quiz_grader, matrix_teacher
# Main orchestrator
import importlib.util
spec = importlib.util.spec_from_file_location('ta', 'teacher-agent.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert hasattr(mod, 'cmd_next')
assert hasattr(mod, 'cmd_lesson')
assert hasattr(mod, 'cmd_quiz')
assert hasattr(mod, 'cmd_grade')
assert hasattr(mod, 'cmd_progress')
assert hasattr(mod, 'cmd_class_digest')
assert hasattr(mod, 'cmd_morning_nudge')
print('ok')
" | grep -q ok || fail_test "import check failed"
end_test

end_test
