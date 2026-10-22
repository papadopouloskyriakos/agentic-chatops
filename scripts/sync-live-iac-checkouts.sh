#!/bin/bash
# sync-live-iac-checkouts.sh
#
# Keeps the LIVE IaC working checkouts on nl-claude01 pinned to the default
# branch (main) and current. Prevents the "stranded on a stale feature branch"
# drift class: on 2026-07-08 the NL IaC checkout was found parked on a local-only
# 'agora-dashboard' branch 182 commits behind main — so every read/edit of the
# live tree hit ~2-week-stale IaC until someone noticed. IaC edits are supposed to
# go via a worktree/MR, never as direct commits on the live checkout, so the live
# checkout should ALWAYS be a clean `main`.
#
# Policy (safe by construction — never clobbers uncommitted work):
#   - clean + on a non-main branch with NO commits ahead of origin/main  -> auto-heal (checkout main + ff)
#   - clean + on main but behind origin/main                             -> auto-ff
#   - clean + on a non-main branch WITH ahead-commits                    -> METRIC ONLY (could be real WIP; human decides)
#   - dirty (uncommitted changes)                                        -> METRIC ONLY (someone is mid-edit)
# Emits Prometheus metrics for the "drifted / dirty / stashed" states so a
# persistent drift can never again go unnoticed for weeks (alerted via
# holistic-agentic-health + a PrometheusRule on iac_checkout_*).
set -uo pipefail

CHECKOUTS=(
  "/app/infrastructure/nl/production"
  "/app/infrastructure/gr/production"
)
PROM="${IAC_CHECKOUT_PROM:-/var/lib/node_exporter/textfile_collector/iac_checkout_drift.prom}"
DEF="${IAC_DEFAULT_BRANCH:-main}"
DRYRUN="${DRYRUN:-0}"
now="$(date +%s)"
log(){ logger -t iac-checkout-sync "$*" 2>/dev/null; [ "${VERBOSE:-0}" = 1 ] && echo "[iac-sync] $*"; return 0; }

out=""
add(){ out+="$1"$'\n'; }
add "# HELP iac_checkout_on_default_branch Live IaC checkout is on the default branch (1) or drifted (0)."
add "# TYPE iac_checkout_on_default_branch gauge"
add "# HELP iac_checkout_behind_commits Commits the live IaC checkout is behind origin/<default>."
add "# TYPE iac_checkout_behind_commits gauge"
add "# HELP iac_checkout_ahead_commits Un-pushed commits on the current branch (blocks auto-heal when >0)."
add "# TYPE iac_checkout_ahead_commits gauge"
add "# HELP iac_checkout_dirty Uncommitted files in the live IaC checkout (0=clean)."
add "# TYPE iac_checkout_dirty gauge"
add "# HELP iac_checkout_stashes Stash entries in the live IaC checkout."
add "# TYPE iac_checkout_stashes gauge"
add "# HELP iac_checkout_healed Whether this run auto-healed the checkout to the default branch."
add "# TYPE iac_checkout_healed gauge"

for repo in "${CHECKOUTS[@]}"; do
  [ -d "$repo/.git" ] || continue
  lbl="$(basename "$(dirname "$repo")")/$(basename "$repo")"
  git -C "$repo" fetch origin "$DEF" --quiet 2>/dev/null || true
  br="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  dirty="$(git -C "$repo" status --porcelain 2>/dev/null | grep -vE '^\?\? \.claude/' | wc -l | tr -d ' ')"
  stashes="$(git -C "$repo" stash list 2>/dev/null | wc -l | tr -d ' ')"
  behind="$(git -C "$repo" rev-list --count "HEAD..origin/$DEF" 2>/dev/null || echo 0)"
  ahead="$(git -C "$repo" rev-list --count "origin/$DEF..HEAD" 2>/dev/null || echo 0)"
  on_def=0; [ "$br" = "$DEF" ] && on_def=1
  healed=0
  if [ "$dirty" = 0 ] && [ "${ahead:-0}" = 0 ] && { [ "$on_def" = 0 ] || [ "${behind:-0}" -gt 0 ]; } && [ "$DRYRUN" = 0 ]; then
    if git -C "$repo" checkout "$DEF" --quiet 2>/dev/null && git -C "$repo" merge --ff-only "origin/$DEF" --quiet 2>/dev/null; then
      healed=1; on_def=1; br="$DEF"
      behind="$(git -C "$repo" rev-list --count "HEAD..origin/$DEF" 2>/dev/null || echo 0)"
      log "healed $lbl -> $DEF"
    fi
  elif [ "$on_def" = 0 ] || [ "$dirty" != 0 ]; then
    log "drift $lbl: branch=$br dirty=$dirty ahead=$ahead behind=$behind stashes=$stashes (no auto-heal — needs human)"
  fi
  add "iac_checkout_on_default_branch{repo=\"$lbl\",branch=\"$br\"} $on_def"
  add "iac_checkout_behind_commits{repo=\"$lbl\"} ${behind:-0}"
  add "iac_checkout_ahead_commits{repo=\"$lbl\"} ${ahead:-0}"
  add "iac_checkout_dirty{repo=\"$lbl\"} $dirty"
  add "iac_checkout_stashes{repo=\"$lbl\"} $stashes"
  add "iac_checkout_healed{repo=\"$lbl\"} $healed"
  [ "${VERBOSE:-0}" = 1 ] && echo "[iac-sync] $lbl: branch=$br on_def=$on_def dirty=$dirty ahead=$ahead behind=$behind stashes=$stashes healed=$healed"
done

add "# HELP iac_checkout_sync_last_run_timestamp Unix time of last run."
add "# TYPE iac_checkout_sync_last_run_timestamp gauge"
add "iac_checkout_sync_last_run_timestamp $now"

mkdir -p "$(dirname "$PROM")" 2>/dev/null || true
printf '%s' "$out" > "${PROM}.tmp" 2>/dev/null && mv "${PROM}.tmp" "$PROM" 2>/dev/null && chmod 0644 "$PROM" 2>/dev/null || true
exit 0
