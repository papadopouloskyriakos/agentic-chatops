#!/usr/bin/env bash
# IFRNLLEI01PRD-652 — teacher-agent intelligence (quiz generator + grader + Bloom).
# All tests run fully offline via _ollama_fn injection — no GPU, no network.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="652-teacher-agent-intelligence"

# ── Bloom progression ──────────────────────────────────────────────────────

start_test "bloom_candidates_per_band"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from bloom import candidates_for, band_for, select_target_bloom
# Foundation: 0.0-0.4
assert candidates_for(0.0) == ['recall', 'recognition']
assert candidates_for(0.39) == ['recall', 'recognition']
assert band_for(0.0) == 'foundation'
# Conceptual: 0.4-0.7
assert candidates_for(0.4) == ['explanation', 'application']
assert candidates_for(0.65) == ['explanation', 'application']
assert band_for(0.5) == 'conceptual'
# Analytical: 0.7-0.9
assert candidates_for(0.7) == ['analysis', 'evaluation']
assert candidates_for(0.89) == ['analysis', 'evaluation']
# Mastery: 0.9-1.0+
assert candidates_for(0.9) == ['teaching_back']
assert candidates_for(1.0) == ['teaching_back']
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "bloom_select_rotates_by_repetition"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from bloom import select_target_bloom
# Foundation: rep=0 → recall, rep=1 → recognition, rep=2 → recall (mod 2)
assert select_target_bloom(0.2, 0) == 'recall'
assert select_target_bloom(0.2, 1) == 'recognition'
assert select_target_bloom(0.2, 2) == 'recall'
assert select_target_bloom(0.2, 3) == 'recognition'
# Conceptual: rep=0 → explanation, rep=1 → application
assert select_target_bloom(0.55, 0) == 'explanation'
assert select_target_bloom(0.55, 1) == 'application'
# Mastery band: always teaching_back
assert select_target_bloom(0.95, 0) == 'teaching_back'
assert select_target_bloom(0.95, 5) == 'teaching_back'
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "bloom_is_advance"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from bloom import is_advance, is_valid_level
assert is_advance('recall', 'recognition')
assert is_advance('recall', 'teaching_back')
assert not is_advance('teaching_back', 'recall')
assert not is_advance('recall', 'recall')
assert not is_advance('bogus', 'recall')  # invalid currents/proposeds → False
assert is_valid_level('recall')
assert not is_valid_level('wut')
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Quiz generator ─────────────────────────────────────────────────────────

start_test "quiz_generator_happy_path_all_bloom_levels"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_generator import generate, Snippet
from bloom import BLOOM_LEVELS
src = Snippet(
    source_path='docs/system-as-abstract-agent.md',
    section='§invariants',
    verbatim_text='Actions mutating external state pass a human gate unless pre-classified safe.',
)
for bl in BLOOM_LEVELS:
    def mock(prompt, bl=bl):
        return {
            'question_text': f'Explain invariant 1 at {bl} level.',
            'question_type': bl,
            'bloom_level': bl,
            'source_snippets': [{
                'source_path': src.source_path,
                'section': src.section,
                'verbatim_text': 'Actions mutating external state pass a human gate',
            }],
            'expected_answer_rubric': 'Must cite the invariant and explain why human gate matters.',
            'distractor_hints': [] if bl != 'recognition' else ['a distractor'],
        }
    q = generate('invariant-1', bl, [src], _ollama_fn=mock)
    assert q is not None, f'bloom {bl} returned None'
    assert q.bloom_level == bl
    assert q.question_type == bl
    assert len(q.source_snippets) == 1
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "quiz_generator_rejects_empty_snippets"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_generator import generate, Snippet
src = Snippet(source_path='a', section='b', verbatim_text='hello world from sources text here')
# mock returns empty source_snippets → reject 3x → None
def mock(prompt):
    return {
        'question_text': 'Q', 'question_type': 'recall', 'bloom_level': 'recall',
        'source_snippets': [],
        'expected_answer_rubric': 'r', 'distractor_hints': [],
    }
q = generate('topic', 'recall', [src], _ollama_fn=mock)
assert q is None, 'should have rejected empty snippets'
print('ok')
" 2>&1)
  assert_contains "$out" "ok"
end_test

start_test "quiz_generator_rejects_non_substring_verbatim"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_generator import generate, Snippet
src = Snippet(source_path='a', section='b', verbatim_text='real source content here')
# mock returns a snippet whose verbatim_text is NOT in the source — hallucination gate must catch.
def mock(prompt):
    return {
        'question_text': 'Q', 'question_type': 'recall', 'bloom_level': 'recall',
        'source_snippets': [{
            'source_path': 'a', 'section': 'b',
            'verbatim_text': 'fabricated content not in source whatsoever',
        }],
        'expected_answer_rubric': 'r', 'distractor_hints': [],
    }
q = generate('topic', 'recall', [src], _ollama_fn=mock)
assert q is None, 'hallucination gate should have caught fabricated snippet'
print('ok')
" 2>&1)
  assert_contains "$out" "ok"
end_test

start_test "quiz_generator_rejects_bloom_mismatch"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_generator import generate, Snippet
src = Snippet(source_path='a', section='b', verbatim_text='real source content here')
def mock(prompt):
    return {
        'question_text': 'Q',
        'question_type': 'recognition',  # mismatch with target 'recall'
        'bloom_level': 'recognition',
        'source_snippets': [{'source_path':'a','section':'b','verbatim_text':'real source content here'}],
        'expected_answer_rubric': 'r', 'distractor_hints': [],
    }
q = generate('topic', 'recall', [src], _ollama_fn=mock)
assert q is None, 'bloom mismatch should have been rejected'
print('ok')
" 2>&1)
  assert_contains "$out" "ok"
end_test

start_test "quiz_generator_ollama_returning_none_returns_none"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_generator import generate, Snippet
src = Snippet(source_path='a', section='b', verbatim_text='real source content here')
def mock(prompt):
    return None
q = generate('topic', 'recall', [src], _ollama_fn=mock)
assert q is None
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "quiz_generator_invalid_target_bloom_raises"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 1 python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_generator import generate, Snippet
src = Snippet(source_path='a', section='b', verbatim_text='x'*20)
generate('topic', 'garbage', [src], _ollama_fn=lambda p: None)
"
end_test

start_test "quiz_generator_empty_sources_raises"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 1 python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_generator import generate
generate('topic', 'recall', [], _ollama_fn=lambda p: None)
"
end_test

# ── Quiz grader ────────────────────────────────────────────────────────────

start_test "quiz_grader_happy_path"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_grader import grade
q = {
    'question_text': 'Explain invariant 1.',
    'bloom_level': 'explanation',
    'expected_answer_rubric': 'Must cite HITL gate + classify-safe carve-out.',
    'source_snippets': [{'source_path':'doc.md','section':'§inv','verbatim_text':'HITL gate unless pre-classified safe'}],
}
def mock(prompt):
    return {
        'score_0_to_1': 0.85,
        'feedback': 'The answer correctly references the HITL gate from §invariants.',
        'bloom_demonstrated': 'explanation',
        'citation_check': {'in_sources': True, 'extra_claims': []},
        'clarifying_question': None,
        'grader_confidence': 0.9,
    }
g = grade(q, 'Invariant 1 says external mutations pass a HITL gate.', _ollama_fn=mock)
assert g is not None
assert 0.83 <= g.score_0_to_1 <= 0.87
assert g.bloom_demonstrated == 'explanation'
assert g.clarifying_question is None
assert g.citation_check['in_sources'] is True
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "quiz_grader_clamps_score_to_0_1"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_grader import grade
q = {'question_text':'Q','bloom_level':'recall','expected_answer_rubric':'r','source_snippets':[]}
def mock(prompt):
    return {'score_0_to_1': 1.7, 'feedback': 'too-much', 'bloom_demonstrated': 'recall',
            'citation_check': {'in_sources': True, 'extra_claims': []},
            'clarifying_question': None, 'grader_confidence': 0.9}
g = grade(q, 'a', _ollama_fn=mock)
assert g.score_0_to_1 == 1.0, g.score_0_to_1
def mock2(prompt):
    return {'score_0_to_1': -0.3, 'feedback': 'too-low', 'bloom_demonstrated': 'recall',
            'citation_check': {'in_sources': True, 'extra_claims': []},
            'clarifying_question': None, 'grader_confidence': 0.9}
g2 = grade(q, 'a', _ollama_fn=mock2)
assert g2.score_0_to_1 == 0.0, g2.score_0_to_1
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "quiz_grader_low_confidence_forces_clarifying_question"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_grader import grade
q = {'question_text':'Q','bloom_level':'recall','expected_answer_rubric':'r','source_snippets':[]}
def mock(prompt):
    return {
        'score_0_to_1': 0.5,
        'feedback': 'Unsure.',
        'bloom_demonstrated': 'recall',
        'citation_check': {'in_sources': True, 'extra_claims': []},
        'clarifying_question': None,         # grader left it blank...
        'grader_confidence': 0.3,            # ...despite low confidence
    }
g = grade(q, 'a', _ollama_fn=mock)
assert g is not None
assert g.grader_confidence == 0.3
# Invariant #4: low confidence → grader must produce a clarifying_question
assert g.clarifying_question is not None
assert len(g.clarifying_question) > 0
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "quiz_grader_rejects_invalid_bloom_in_output"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_grader import grade
q = {'question_text':'Q','bloom_level':'recall','expected_answer_rubric':'r','source_snippets':[]}
def mock(prompt):
    return {'score_0_to_1': 0.5, 'feedback': 'ok', 'bloom_demonstrated': 'garbage',
            'citation_check': {}, 'clarifying_question': None, 'grader_confidence': 0.9}
g = grade(q, 'a', _ollama_fn=mock)
assert g is None, 'should reject invalid bloom'
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "quiz_grader_empty_feedback_rejected"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_grader import grade
q = {'question_text':'Q','bloom_level':'recall','expected_answer_rubric':'r','source_snippets':[]}
def mock(prompt):
    return {'score_0_to_1': 0.5, 'feedback': '', 'bloom_demonstrated': 'recall',
            'citation_check': {}, 'clarifying_question': None, 'grader_confidence': 0.9}
g = grade(q, 'a', _ollama_fn=mock)
assert g is None
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "quiz_grader_score_to_sm2_quality_mapping"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from sm2 import quality_from_score
# End-to-end: grader outputs score; caller maps to SM-2 quality via sm2.quality_from_score.
assert quality_from_score(0.0) == 0
assert quality_from_score(0.2) == 1
assert quality_from_score(0.4) == 2
assert quality_from_score(0.6) == 3
assert quality_from_score(0.8) == 4
assert quality_from_score(1.0) == 5
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "quiz_grader_extra_claims_preserved"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from quiz_grader import grade
q = {'question_text':'Q','bloom_level':'recall','expected_answer_rubric':'r','source_snippets':[]}
def mock(prompt):
    return {
        'score_0_to_1': 0.8,
        'feedback': 'Correct reference.',
        'bloom_demonstrated': 'recall',
        'citation_check': {'in_sources': False, 'extra_claims': ['claim A', 'claim B', 123]},
        'clarifying_question': None,
        'grader_confidence': 0.9,
    }
g = grade(q, 'a', _ollama_fn=mock)
assert g is not None
# Non-string items should be coerced to str, which they are, but 123 would become '123'
assert 'claim A' in g.citation_check['extra_claims']
assert 'claim B' in g.citation_check['extra_claims']
assert g.citation_check['in_sources'] is False
print('ok')
")
  assert_contains "$out" "ok"
end_test

end_test
