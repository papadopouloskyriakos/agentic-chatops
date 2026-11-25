#!/usr/bin/env bash
# check-hostname-abbreviations.sh — detect BARE (non-site-prefixed) hostnames.
#
# WHY: hosts in this estate share role-names across sites — nl-pve01 AND gr-pve01,
# nl-fw01 AND gr-fw01, etc. Abbreviating to "pve01"/"fw01" collapses two physically
# distinct machines into one ambiguous token. That is a CONFIRMED operational landmine: it
# caused a real wrong-host reasoning failure (memory feedback_verify_belief_not_rationalize_observation).
# The [P0] CLAUDE.md rule mandates FULL site-prefixed hostnames everywhere. This guard enforces it
# in agent-authored content (memory, CLAUDE.md, .claude/rules, docs) so it can't silently creep back.
#
# Usage:
#   scripts/check-hostname-abbreviations.sh [path ...]      # scan paths (default: the standard set)
#   scripts/check-hostname-abbreviations.sh --count <path>  # just the count
# Exit 0 = clean, 1 = bare hostnames found (for hooks/CI).
set -uo pipefail

SITES='nl|gr|gr2|defra01|txhou01|notrf01|chzrh01|gr-|nl-'
# collision-prone role tokens that MUST carry a site prefix. Keep in sync with the live
# inventory: scripts/check-hostname-abbreviations.sh --roles regenerates the suggested list.
ROLES='pve0[1-9]|file0[1-9]|iot[0-9]|iotarb0[1-9]|ctrlr0[1-9]|node0[1-9]|fw0[1-9]|sw0[1-9]|nms0[1-9]|syno0[1-9]|gpu0[1-9]|claude0[1-9]|dmz0[1-9]|pihole0[1-9]|freeipa0[1-9]|npm0[1-9]|syslogng0[1-9]|sec0[1-9]|gitlab0[1-9]|haproxy0[1-9]|openbao0[1-9]|frr0[1-9]|matrix0[1-9]|mattermost0[1-9]|nc0[1-9]|nc[0-9]|k8s-ctrlr0[1-9]|k8s-node0[1-9]'

# Allowlist: lines that legitimately contain the bare token (e.g. the rule's own negative examples).
ALLOW_RE='short hostname|use the short|not pve01|not nllei|not grskg|negative example|abbreviation|do not use|never use|collision|bare hostname|check-hostname-abbreviations'

scan_one() {
  local f="$1"
  # files that exist SOLELY to teach this rule contain bare tokens as deliberate bad-examples
  case "$f" in
    *feedback_full_hostnames.md|*feedback_never_truncate_hostnames.md|*check-hostname-abbreviations*) return 0;;
  esac
  # Flag a STANDALONE role token (not adjacent to alnum/hyphen) — but first strip regions that are
  # NOT prose hostname references: inline-code `...`, wiki-links [[...]], markdown links [t](u),
  # and *.md filename slugs. This isolates real bare hostnames in prose from identifiers/filenames.
  local infence=0
  grep -n '' "$f" 2>/dev/null | while IFS=: read -r ln rest; do
    t="${rest#"${rest%%[![:space:]]*}"}"                                      # strip leading whitespace
    case "$t" in '```'*|'~~~'*) infence=$((1 - infence)); continue;; esac      # skip fenced code blocks (incl. indented)
    [ "$infence" = 1 ] && continue
    clean=$(printf '%s' "$rest" | sed -E 's/`[^`]*`//g; s/\[\[[^]]*\]\]//g; s/\[[^]]*\]\([^)]*\)//g; s/[A-Za-z0-9_./-]+\.md//g')
    printf '%s' "$clean" | grep -qiE "$ALLOW_RE" && continue
    # exclude _ adjacency too (filename slugs / param names like include_syno01, pve01_memory_pressure)
    printf '%s' "$clean" | grep -oP "(?<![a-z0-9_-])(?:${ROLES})(?![a-z0-9_-])" 2>/dev/null | while read -r tok; do
      printf '%s:%s:%s\n' "$f" "$ln" "$tok"
    done
  done
}

DEFAULT_PATHS=(
  "$HOME/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory"
  "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/CLAUDE.md"
  "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.claude/rules"
  "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docs"
)

[ "${1:-}" = "--count" ] && { shift; CNT=1; }
PATHS=("$@"); [ ${#PATHS[@]} -eq 0 ] && PATHS=("${DEFAULT_PATHS[@]}")

total=0; files=0
for p in "${PATHS[@]}"; do
  [ -e "$p" ] || continue
  while IFS= read -r -d '' f; do
    hits=$(scan_one "$f")
    if [ -n "$hits" ]; then
      files=$((files+1)); n=$(printf '%s\n' "$hits" | grep -c .); total=$((total+n))
      [ "${CNT:-0}" = 1 ] || printf '%s\n' "$hits"
    fi
  done < <(find "$p" -type f \( -name '*.md' -o -name '*.markdown' \) -print0 2>/dev/null)
done
echo "  >> ${total} bare-hostname occurrence(s) in ${files} file(s)" >&2
[ "$total" -eq 0 ]
