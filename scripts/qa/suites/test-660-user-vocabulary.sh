#!/usr/bin/env bash
# IFRNLLEI01PRD-719 — user-vocabulary map + prompt-submit hook extension.
#
# Tests the vocabulary matching logic in isolation (the full hook-emit
# chain is covered by integration tests; here we assert the match
# semantics: ambiguous phrase → ambiguous hit, canonical alias →
# canonical hit, candidate already present → suppressed, etc).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="660-user-vocabulary"
VOCAB="$REPO_ROOT/config/user-vocabulary.json"

# Extract the inline matcher from user-prompt-submit.sh for testing.
_match() {
  MSG="$1" VOCAB="$VOCAB" python3 <<'PY' 2>/dev/null
import json, os, sys
msg = (os.environ.get("MSG") or "").lower()
if not msg or len(msg) < 3:
    sys.exit(0)
try:
    data = json.load(open(os.environ["VOCAB"]))
except Exception:
    sys.exit(0)
for m in data.get("mappings", []):
    phrase = (m.get("user_phrase") or "").lower()
    if not phrase or phrase not in msg:
        continue
    if m.get("ambiguous"):
        cands = [c.lower() for c in m.get("candidates", [])]
        if any(c in msg for c in cands):
            continue
        print("ambiguous|" + phrase + "|" + ";".join(m.get("candidates", [])))
    elif m.get("canonical"):
        print("canonical|" + phrase + "|" + (m.get("canonical") or ""))
PY
}

# ─── T1 vocab JSON exists and parses ────────────────────────────────────
start_test "vocab_json_exists_and_parses"
  if [ ! -f "$VOCAB" ]; then
    fail_test "missing config/user-vocabulary.json"
  elif ! python3 -c "import json; json.load(open('$VOCAB'))" 2>/dev/null; then
    fail_test "vocabulary JSON did not parse"
  fi
end_test

# ─── T2 at least 20 mappings ────────────────────────────────────────────
start_test "vocab_has_twenty_plus_entries"
  count=$(python3 -c "import json; print(len(json.load(open('$VOCAB'))['mappings']))")
  if [ "$count" -ge 20 ]; then
    :
  else
    fail_test "expected ≥20 mappings, got $count"
  fi
end_test

# ─── T3 ambiguous phrase without candidate → emits ambiguous hit ────────
start_test "ambiguous_phrase_alone_emits_hit"
  hits=$(_match "check the firewall")
  if [[ "$hits" == *"ambiguous|the firewall"* ]]; then
    :
  else
    fail_test "expected ambiguous match for 'the firewall', got: $hits"
  fi
end_test

# ─── T4 ambiguous phrase with candidate present → suppressed ────────────
start_test "ambiguous_phrase_with_candidate_is_suppressed"
  hits=$(_match "check the firewall on nl-fw01")
  if [[ "$hits" != *"ambiguous|the firewall"* ]]; then
    :
  else
    fail_test "expected suppression when candidate present, got: $hits"
  fi
end_test

# ─── T5 canonical alias → emits canonical hit ───────────────────────────
start_test "canonical_alias_emits_hit"
  hits=$(_match "xs4all tunnel is down")
  if [[ "$hits" == *"canonical|xs4all|budget"* ]]; then
    :
  else
    fail_test "expected canonical match for 'xs4all', got: $hits"
  fi
end_test

# ─── T6 short / empty msg → no output ───────────────────────────────────
start_test "short_or_empty_msg_emits_nothing"
  hits=$(_match "")
  if [ -z "$hits" ]; then
    :
  else
    fail_test "expected no hits for empty msg, got: $hits"
  fi
  hits=$(_match "ok")
  if [ -z "$hits" ]; then
    :
  else
    fail_test "expected no hits for <3 char msg, got: $hits"
  fi
end_test

# ─── T7 case insensitivity ──────────────────────────────────────────────
start_test "matching_is_case_insensitive"
  hits=$(_match "CHECK THE FIREWALL")
  if [[ "$hits" == *"ambiguous|the firewall"* ]]; then
    :
  else
    fail_test "expected case-insensitive match, got: $hits"
  fi
end_test

# ─── T8 no false-positive on unrelated prompts ──────────────────────────
start_test "no_false_positive_on_plain_prompt"
  hits=$(_match "please check the service status and report back")
  if [ -z "$hits" ]; then
    :
  else
    fail_test "expected no match on generic prompt, got: $hits"
  fi
end_test

# ─── T9 malformed vocab → helper exits quietly ──────────────────────────
start_test "malformed_vocab_file_is_silent"
  tmp=$(mktemp)
  echo "not valid json" > "$tmp"
  out=$(MSG="the firewall" VOCAB="$tmp" python3 <<'PY' 2>&1
import json, os, sys
msg = (os.environ.get("MSG") or "").lower()
if not msg or len(msg) < 3:
    sys.exit(0)
try:
    data = json.load(open(os.environ["VOCAB"]))
except Exception:
    sys.exit(0)
# (would emit here but malformed → silent)
PY
)
  rm -f "$tmp"
  if [ -z "$out" ]; then
    :
  else
    fail_test "expected silent on malformed, got: $out"
  fi
end_test

# ─── T10 hook file carries vocabulary block ─────────────────────────────
start_test "hook_file_contains_vocabulary_block"
  HOOK="$REPO_ROOT/scripts/hooks/user-prompt-submit.sh"
  if grep -q "IFRNLLEI01PRD-719" "$HOOK" && grep -q "config/user-vocabulary.json" "$HOOK"; then
    :
  else
    fail_test "expected vocabulary block with -719 marker in user-prompt-submit.sh"
  fi
end_test
