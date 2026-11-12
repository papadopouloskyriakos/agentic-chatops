#!/usr/bin/env bash
# audit-teacher-invariants.sh — IFRNLLEI01PRD-655 gate tier.
#
# Enforces the 6 invariants from docs/plans/teacher-agent-implementation-plan.md §8
# against the live repo + DB. Each check is self-contained and self-describing;
# any non-compliance prints FAIL with context and accumulates into the exit code.
#
# Exit 0 = all invariants hold. Exit 1 = at least one violation.
#
# Read-only. Safe to run anytime. Wired into holistic-agentic-health.sh as
# the teacher-agent section.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
fail=0

banner() {
  echo
  echo "== $* =="
}

ok()   { echo "  PASS — $*"; }
bad()  { echo "  FAIL — $*" >&2; fail=1; }
skip() { echo "  SKIP — $*"; }

echo "=== Teacher-agent invariant audit (IFRNLLEI01PRD-655) ==="
echo "repo=$REPO_ROOT"
echo "db=$DB"

# ── Invariant #1 — read-only tool allowlist ────────────────────────────────
banner "Invariant #1 — teacher-agent tool allowlist excludes mutating tools"
AGENT_MD="$REPO_ROOT/.claude/agents/teacher-agent.md"
if [ ! -f "$AGENT_MD" ]; then
  bad "$AGENT_MD not found"
else
  tools_line=$(grep -E '^tools:' "$AGENT_MD" | head -1)
  if [ -z "$tools_line" ]; then
    bad "no 'tools:' frontmatter line in $AGENT_MD"
  else
    for t in Read Grep Glob Bash ToolSearch; do
      if echo "$tools_line" | grep -q "$t"; then
        ok "read-only tool present: $t"
      else
        bad "expected read-only tool missing: $t"
      fi
    done
    for banned in Edit Write MultiEdit NotebookEdit; do
      if echo "$tools_line" | grep -q "\b$banned\b"; then
        bad "mutating tool present in allowlist: $banned"
      else
        ok "mutating tool absent: $banned"
      fi
    done
  fi
fi

# ── Invariant #2 — memory never shrinks (no DELETE on learning_* tables) ───
banner "Invariant #2 — no DELETE against learning_* tables"
delete_hits=$(grep -iE 'DELETE' \
                "$REPO_ROOT/scripts/teacher-agent.py" \
                "$REPO_ROOT/scripts/lib/matrix_teacher.py" \
                "$REPO_ROOT/scripts/lib/sm2.py" \
                "$REPO_ROOT/scripts/lib/bloom.py" \
                "$REPO_ROOT/scripts/lib/quiz_generator.py" \
                "$REPO_ROOT/scripts/lib/quiz_grader.py" 2>/dev/null \
              | grep -iE 'learning_|teacher_operator_dm')
if [ -z "$delete_hits" ]; then
  ok "no DELETE statements against learning_* / teacher_operator_dm in teacher code"
else
  bad "found DELETE statements against tracked tables:"
  echo "$delete_hits" | sed 's/^/    /' >&2
fi

# ── Invariant #3 — mastery only advances via grader (score≥0.8) ────────────
banner "Invariant #3 — mastery_score writes confined to grader path"
py_check=$(python3 - <<PY
REDACTED_a7b84d63
src = open("$REPO_ROOT/scripts/teacher-agent.py").read()
fn_starts = [(m.start(), m.group(1)) for m in re.finditer(r"^def ([a-zA-Z_]+)\b", src, re.MULTILINE)]
fn_starts.append((len(src), "__end__"))
offenders = []
for i in range(len(fn_starts) - 1):
    start, name = fn_starts[i]
    end = fn_starts[i+1][0]
    body = src[start:end]
    # "mastery_score" appears as read-access in several functions (band,
    # progress). Offenders are functions that pass it as a WRITE key into
    # _upsert_progress or issue an UPDATE against learning_progress.
    writes_dict_key = re.search(r'"mastery_score"\s*:\s*\w', body) is not None
    writes_update = "UPDATE learning_progress" in body and re.search(r'SET\s+.*mastery', body, re.IGNORECASE) is not None
    if (writes_dict_key or writes_update) and name not in ("cmd_grade", "_upsert_progress"):
        offenders.append(name)
print("OK" if not offenders else "OFFENDERS:" + ",".join(offenders))
PY
)
if [ "$py_check" = "OK" ]; then
  ok "mastery_score writes confined to cmd_grade / _upsert_progress"
else
  bad "mastery_score writes found outside grade path: $py_check"
fi

# ── Invariant #4 — low grader_confidence blocks advance ────────────────────
banner "Invariant #4 — low grader_confidence forces clarifying_question"
if ! grep -q 'clarifying_question' "$REPO_ROOT/scripts/lib/quiz_grader.py"; then
  bad "quiz_grader.py missing clarifying_question handling"
else
  # Grader lib must populate clarifying_question when grader_confidence is low.
  # The threshold is a named constant (CONFIDENCE_THRESHOLD). Accept either the
  # literal value or the named constant used in a comparison with grader_conf.
  if grep -qE 'CONFIDENCE_THRESHOLD\s*=\s*0\.6' "$REPO_ROOT/scripts/lib/quiz_grader.py" \
     && grep -qE 'grader_conf\s*<\s*CONFIDENCE_THRESHOLD' "$REPO_ROOT/scripts/lib/quiz_grader.py"; then
    ok "grader_confidence<CONFIDENCE_THRESHOLD(0.6) gate present in quiz_grader.py"
  elif grep -qE 'grader_conf(idence)?\s*<\s*0\.6' "$REPO_ROOT/scripts/lib/quiz_grader.py"; then
    ok "literal grader_confidence<0.6 gate present in quiz_grader.py"
  else
    bad "no grader_confidence<0.6 threshold gate in quiz_grader.py"
  fi
fi

# ── Invariant #5 — three-tier every decision ───────────────────────────────
banner "Invariant #5 — three-tier decision pipeline intact"
# Tier 1: deterministic renderer in teacher-agent.py (_render_lesson, _render_quiz, _render_grade)
# Tier 2: LLM (quiz_generator.generate + quiz_grader.grade)
# Tier 3: operator-typed answer (cmd_grade --answer)
missing_tiers=""
grep -q "def _render_lesson" "$REPO_ROOT/scripts/teacher-agent.py" || missing_tiers+=" T1:render_lesson"
grep -q "def _render_quiz"   "$REPO_ROOT/scripts/teacher-agent.py" || missing_tiers+=" T1:render_quiz"
grep -q "def _render_grade"  "$REPO_ROOT/scripts/teacher-agent.py" || missing_tiers+=" T1:render_grade"
grep -q "def generate"       "$REPO_ROOT/scripts/lib/quiz_generator.py" || missing_tiers+=" T2:generate"
grep -q "def grade"          "$REPO_ROOT/scripts/lib/quiz_grader.py" || missing_tiers+=" T2:grade"
grep -q "def cmd_grade"      "$REPO_ROOT/scripts/teacher-agent.py" || missing_tiers+=" T3:cmd_grade"
if [ -z "$missing_tiers" ]; then
  ok "all three tiers (T1 renderers + T2 LLM libs + T3 operator path) present"
else
  bad "missing tier entry points:$missing_tiers"
fi

# ── Invariant #6 — failure preserves state + re-entry ──────────────────────
banner "Invariant #6 — sessions row with completed_at NULL is resumable"
if [ -f "$DB" ]; then
  if sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_sessions'" | grep -q 1; then
    # No structural check beyond "table exists with completed_at column"
    has_col=$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('learning_sessions') WHERE name='completed_at'")
    if [ "$has_col" = "1" ]; then
      ok "learning_sessions.completed_at column exists (NULL = in-flight)"
      # Count abandoned rows (>24h without completion) as a yellow flag
      stale=$(sqlite3 "$DB" "SELECT COUNT(*) FROM learning_sessions WHERE completed_at IS NULL AND started_at < datetime('now','-24 hours')")
      if [ "$stale" = "0" ]; then
        ok "no stale in-flight sessions (>24h without completion)"
      else
        # Warning, not FAIL — the operator can legitimately defer an answer
        echo "  WARN — $stale in-flight learning_sessions rows older than 24h (operator abandoned or crashed mid-quiz — resumable via !learn)"
      fi
    else
      bad "learning_sessions missing completed_at column"
    fi
  else
    skip "learning_sessions table not yet migrated (migration 013)"
  fi
else
  skip "DB not found at $DB"
fi

# ── Privacy invariant (IFRNLLEI01PRD-653) — public_sharing defaults OFF ────
banner "Privacy invariant — teacher_operator_dm.public_sharing defaults OFF"
if [ -f "$DB" ]; then
  if sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='teacher_operator_dm'" | grep -q 1; then
    default=$(sqlite3 "$DB" "SELECT dflt_value FROM pragma_table_info('teacher_operator_dm') WHERE name='public_sharing'")
    if [ "$default" = "0" ]; then
      ok "public_sharing DEFAULT 0 (privacy-first)"
    else
      bad "public_sharing DEFAULT is '$default' — should be 0"
    fi
  else
    skip "teacher_operator_dm not yet migrated"
  fi
fi

echo
if [ $fail -eq 0 ]; then
  echo "=== RESULT: all invariants PASS ==="
else
  echo "=== RESULT: $fail FAIL(s) — see messages above ==="
fi
exit $fail
