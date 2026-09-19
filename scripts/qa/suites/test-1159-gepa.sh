#!/usr/bin/env bash
# IFRNLLEI01PRD-1159 — GEPA reflective prompt-variant generator (claude -p based).
# GENERATE-ONLY: the Welch t-test stays the promotion gate. DORMANT by default
# (PROMPT_GEPA_ENABLED=0 => hand-authored pool, byte-identical legacy). CI-safe.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1159-gepa"

GEN="$REPO_ROOT/scripts/lib/gepa_generator.py"
PT="$REPO_ROOT/scripts/prompt-patch-trial.py"
FIN="$REPO_ROOT/scripts/finalize-prompt-trials.py"

start_test "gepa_generator_py_syntax"
  assert_eq "OK" "$(python3 -c "import ast;ast.parse(open('$GEN').read());print('OK')" 2>/dev/null || echo FAIL)"
end_test

start_test "dormant_by_default_flag_off"
  # ENABLED must default off; evolve_candidates returns None when off => caller
  # falls back to the hand-authored pool (byte-identical legacy).
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import os; os.environ.pop('PROMPT_GEPA_ENABLED',None)
import importlib; from lib import gepa_generator as g; importlib.reload(g)
print(g.ENABLED, g.evolve_candidates('investigation_quality','seed instr',3))")
  assert_eq "False None" "$out"
end_test

start_test "flag_off_candidates_are_hand_authored_3"
  out=$(cd "$REPO_ROOT/scripts" && PROMPT_GEPA_ENABLED=0 python3 -c "
import importlib.util as u
s=u.spec_from_file_location('ppt','prompt-patch-trial.py'); m=u.module_from_spec(s); s.loader.exec_module(m)
c=m.candidates_for_dim('investigation_quality')
print(len(c), all(x.category!='gepa' for x in c))")
  assert_eq "3 True" "$out"
end_test

start_test "fails_safe_when_claude_unavailable"
  # force-enable, stub the CLI call to None (CLI missing/timeout/error) =>
  # evolve_candidates returns None so the caller falls back to hand-authored.
  out=$(cd "$REPO_ROOT/scripts" && PROMPT_GEPA_ENABLED=1 python3 -c "
import importlib; from lib import gepa_generator as g; importlib.reload(g)
g._run_claude = lambda prompt: None
print(g.ENABLED, g.evolve_candidates('investigation_quality','seed instruction text',3))")
  assert_eq "True None" "$out"
end_test

start_test "extract_array_parses_good_rejects_garbage"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
from lib import gepa_generator as g
good='[{\"label\":\"a\",\"instruction\":\"x\"},{\"label\":\"b\",\"instruction\":\"y\"}]'
print(len(g._extract_array(good) or []), g._extract_array('not json at all'))")
  assert_eq "2 None" "$out"
end_test

start_test "dedupe_drops_near_identical"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
from lib import gepa_generator as g
# 'a' and 'b' differ only by case + whitespace => same normalized key => dedupe to 1
items=[{'label':'a','instruction':'Be concise'},{'label':'b','instruction':'be  CONCISE'},{'label':'c','instruction':'Add worked examples'}]
print(len(g._dedupe(items)))")
  assert_eq "2" "$out"
end_test

start_test "generate_only_reflection_prompt_has_no_promote_language"
  # The text SENT to claude must not instruct promotion/applying — generate-only.
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
from lib import gepa_generator as g
p=g._reflection_prompt('investigation_quality','seed line',3).lower()
print(any(w in p for w in ('promote','auto-apply','bypass','deploy this','make it live')))")
  assert_eq "False" "$out"
end_test

start_test "welch_gate_preserved_in_finalize"
  # the SOLE promotion gate (Welch t-test) must remain in finalize-prompt-trials.py
  assert_eq "yes" "$(grep -qiE "welch|t_test|t-test|p_value" "$FIN" && echo yes || echo no)"
end_test
