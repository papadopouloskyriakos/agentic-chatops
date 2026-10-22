#!/usr/bin/env bash
# audit-always-on-budget.sh — how many bytes of harness text does a session load
# before it does any work? (R1, Harness² always-on cap)
#
# Harness² hard-caps always-on text at 24,000 chars (OpenCode) / 8,000 (Codex) and
# its editor prompt says why: "ALWAYS-ON PROSE IS THE EXPENSIVE OPTION — every word
# competes with the agent's own output budget". Its ablation found skills (−5.3) and
# scripts (−3.7) carry the value; the prompt group only −1.5. This audit measures
# our always-on surface per repo and the dispatched-session prompt, so growth is
# visible and capped instead of silent.
#
# Always-on for a session in <repo>:  CLAUDE.md + .claude/rules/*.md
# Always-on for a dispatched session: the Runner Build Prompt node's static text
#                                     (jsCode minus the per-session data it splices)
#
# Usage: audit-always-on-budget.sh [--json] [--warn BYTES] [--fail BYTES] [REPO ...]
#   defaults: warn 32000, fail 48000 (env ALWAYS_ON_WARN / ALWAYS_ON_FAIL);
#   repos default to the gateway repo + the three IaC production repos.
# Exit 0 = all under the warn line, 1 = at least one over the FAIL line, 2 = usage.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY="$(cd "$HERE/.." && pwd)"
WARN="${ALWAYS_ON_WARN:-32000}"
FAIL="${ALWAYS_ON_FAIL:-48000}"
JSON=0
REPOS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --json) JSON=1 ;;
    --warn) shift; WARN="$1" ;;
    --fail) shift; FAIL="$1" ;;
    -h|--help) sed -n 2,20p "$0"; exit 0 ;;
    *) REPOS+=("$1") ;;
  esac
  shift
done
EXPLICIT=1
if [ ${#REPOS[@]} -eq 0 ]; then
  EXPLICIT=0
  REPOS=("$GATEWAY"
         /app/infrastructure/nl/production
         /app/infrastructure/gr/production
         /app/infrastructure/notrf01/production)
fi

bytes_of() { [ -f "$1" ] && wc -c < "$1" || echo 0; }

worst=0
rows=()
for repo in "${REPOS[@]}"; do
  [ -d "$repo" ] || continue
  claude=$(bytes_of "$repo/CLAUDE.md")
  rules=0; nrules=0
  if [ -d "$repo/.claude/rules" ]; then
    for f in "$repo"/.claude/rules/*.md; do
      [ -f "$f" ] || continue
      rules=$((rules + $(wc -c < "$f"))); nrules=$((nrules + 1))
    done
  fi
  total=$((claude + rules))
  state=ok
  [ "$total" -gt "$WARN" ] && state=warn
  [ "$total" -gt "$FAIL" ] && state=fail
  [ "$total" -gt "$worst" ] && worst=$total
  rows+=("$(printf '{"surface":"repo","path":"%s","claude_md":%d,"rules":%d,"rules_files":%d,"total":%d,"state":"%s"}' "$repo" "$claude" "$rules" "$nrules" "$total" "$state")")
done

# Dispatched-session prompt (default sweep only; explicit REPO args measure just those repos):
# the Build Prompt node's code is a proxy for the static
# text every dispatched session receives (the per-session splices are small).
RUNNER="$GATEWAY/workflows/claude-gateway-runner.json"
if [ "$EXPLICIT" -eq 0 ] && [ -f "$RUNNER" ]; then
  bp=$(python3 - "$RUNNER" <<'PY'
import json, sys
w = json.load(open(sys.argv[1]))
n = next((n for n in w.get("nodes", []) if n.get("name") == "Build Prompt"), None)
print(len(((n or {}).get("parameters") or {}).get("jsCode") or ""))
PY
)
  state=ok
  [ "$bp" -gt "$WARN" ] && state=warn
  [ "$bp" -gt "$FAIL" ] && state=fail
  [ "$bp" -gt "$worst" ] && worst=$bp
  rows+=("$(printf '{"surface":"build-prompt","path":"%s","claude_md":0,"rules":0,"rules_files":0,"total":%d,"state":"%s"}' "$RUNNER" "$bp" "$state")")
fi

rc=0
[ "$worst" -gt "$FAIL" ] && rc=1
if [ "$JSON" -eq 1 ]; then
  printf '{"warn":%d,"fail":%d,"worst":%d,"rows":[%s]}\n' "$WARN" "$FAIL" "$worst" "$(IFS=,; echo "${rows[*]}")"
else
  printf '%-13s %-62s %9s %9s %9s  %s\n' SURFACE PATH CLAUDE.md RULES TOTAL STATE
  for r in "${rows[@]}"; do
    python3 -c '
import json,sys
d=json.loads(sys.argv[1])
surface, path, cm, rules, total, state = d["surface"], d["path"][-62:], d["claude_md"], d["rules"], d["total"], d["state"].upper()
print(f"{surface:<13} {path:<62} {cm:>9} {rules:>9} {total:>9}  {state}")' "$r"
  done
  echo "warn>${WARN} fail>${FAIL}  (Harness² caps always-on at 24000; prefer a skill, script, subagent or hook over more prose)"
fi
exit $rc
