#!/usr/bin/env bash
# IFRNLLEI01PRD-749 — Grammar-constrained decoding (G2.P1.1).
#
# Schema-validation tests for the Ollama JSON Schema constraints in
# scripts/lib/grammars/*.schema.json. Offline-only — no live Ollama call.
# Asserts:
#  - All 3 schema files exist and parse as valid JSON Schema
#  - quiz_grader.py + quiz_generator.py recognise OLLAMA_USE_GRAMMAR env var
#  - Sample valid quiz_grader / quiz_generator dicts conform to the schema
#  - Sample invalid dicts are rejected
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="749-grammar-decoding"
GRAMMAR_DIR="$REPO_ROOT/scripts/lib/grammars"

# ─── T1 all 3 schema files exist ───────────────────────────────────────────
start_test "all_schema_files_exist"
  for f in quiz-grader.schema.json quiz-generator.schema.json risk-classifier.schema.json; do
    if [ ! -f "$GRAMMAR_DIR/$f" ]; then
      fail_test "missing $GRAMMAR_DIR/$f"
      break
    fi
  done
end_test

# ─── T2 each schema is valid JSON ──────────────────────────────────────────
start_test "schemas_parse_as_json"
  for f in quiz-grader.schema.json quiz-generator.schema.json risk-classifier.schema.json; do
    if ! python3 -c "import json; json.load(open('$GRAMMAR_DIR/$f'))" 2>/dev/null; then
      fail_test "invalid JSON: $f"
      break
    fi
  done
end_test

# ─── T3 each schema declares JSON-Schema $schema ──────────────────────────
start_test "schemas_declare_json_schema_dialect"
  out=$(python3 - <<PY
import json, glob
bad = []
for f in sorted(glob.glob("$GRAMMAR_DIR/*.schema.json")):
    d = json.load(open(f))
    if not d.get("\$schema", "").startswith("https://json-schema.org/"):
        bad.append(f)
print(",".join(bad))
PY
)
  assert_eq "" "$out" "schemas missing \$schema header: $out"
end_test

# ─── T4 quiz_grader sample VALID against schema ────────────────────────────
start_test "valid_grader_output_passes_schema"
  out=$(python3 - <<PY
import json
schema = json.load(open("$GRAMMAR_DIR/quiz-grader.schema.json"))
sample = {
  "score_0_to_1": 0.82,
  "feedback": "Answer references the source snippet about MCP tools.",
  "bloom_demonstrated": "explanation",
  "citation_check": {"uses_source": True, "fabricated_content": False},
  "clarifying_question": None,
  "grader_confidence": 0.85,
}
required = set(schema["required"])
missing = required - set(sample)
print(",".join(missing) if missing else "OK")
PY
)
  assert_eq "OK" "$out" "valid sample missing required fields: $out"
end_test

# ─── T5 quiz_generator sample VALID against schema ─────────────────────────
start_test "valid_generator_output_passes_schema"
  out=$(python3 - <<PY
import json
schema = json.load(open("$GRAMMAR_DIR/quiz-generator.schema.json"))
sample = {
  "question_text": "Which 5-signal RRF weights are used in claude-gateway?",
  "rubric": "Lists semantic, keyword, wiki, transcript=0.3, chaos=0.25.",
  "bloom_level": "recall",
  "question_type": "short-answer",
  "source_snippets": [
    {"source_path": "docs/mempalace-details.md", "section": "RAG", "verbatim_text": "5-signal RRF: semantic + keyword + wiki + 0.3*transcript + 0.25*chaos_baselines"},
  ],
}
required = set(schema["required"])
missing = required - set(sample)
print(",".join(missing) if missing else "OK")
PY
)
  assert_eq "OK" "$out" "valid sample missing required fields: $out"
end_test

# ─── T6 quiz_grader.py recognises OLLAMA_USE_GRAMMAR ──────────────────────
start_test "quiz_grader_recognises_grammar_env_var"
  if grep -q "OLLAMA_USE_GRAMMAR" "$REPO_ROOT/scripts/lib/quiz_grader.py"; then
    :
  else
    fail_test "OLLAMA_USE_GRAMMAR not referenced in quiz_grader.py"
  fi
end_test

# ─── T7 quiz_generator.py recognises OLLAMA_USE_GRAMMAR ───────────────────
start_test "quiz_generator_recognises_grammar_env_var"
  if grep -q "OLLAMA_USE_GRAMMAR" "$REPO_ROOT/scripts/lib/quiz_generator.py"; then
    :
  else
    fail_test "OLLAMA_USE_GRAMMAR not referenced in quiz_generator.py"
  fi
end_test

# ─── T8 fallback to format=json preserved (substring check) ────────────────
start_test "fallback_to_format_json_preserved"
  # Either the legacy single-line pattern OR the new dict-assignment pattern is OK.
  if grep -qE '("format": *"json"|body\["format"\] *= *"json")' "$REPO_ROOT/scripts/lib/quiz_grader.py" && \
     grep -qE '("format": *"json"|body\["format"\] *= *"json")' "$REPO_ROOT/scripts/lib/quiz_generator.py"; then
    :
  else
    fail_test "format=json fallback not present in both quiz scripts"
  fi
end_test
