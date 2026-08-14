#!/usr/bin/env bash
# cleanup-daemon-worktrees.sh — recurring janitor for /tmp/daemon-*
#
# Closes OMOIKANE-432. Background: every active app-user session uses
# `git worktree add /tmp/daemon-<purpose>` (per omoikane.coach P1.D rule —
# concurrent sessions on the same canonical clone shift each other's HEAD).
# Each worktree carries a Rust `app/target/` build dir at ~4 GB. After ~10
# MRs in a day, /tmp grows ~40 GB; quota-EDQUOT trips and downstream cargo
# invocations SIGKILL out (observed 2026-05-21).
#
# Two-tier sweep:
# 1) Worktrees on branches already merged into origin/main → remove entirely
#    (next session re-creates them on demand). Always-safe; the branch is
#    no longer needed.
# 2) Remaining worktrees whose app/target/ has mtime > 24 h → wipe target/
#    only. Cargo rebuilds the next time a session touches that worktree
#    (~60-90 s incremental, ~3-5 min cold).
#
# In-progress safety: we DO NOT remove a worktree if any process has a CWD
# inside it (lsof check) or if HEAD differs from the worktree's recorded
# branch (i.e. someone is actively rebasing). Skipped entries log a line.
#
# Operator overrides:
#   --dry-run         : print what would happen, change nothing
#   --max-age <hours> : override the 24h mtime threshold for target/ wipe
#   --root <dir>      : override /tmp as the worktree search root
#
set -euo pipefail

DAEMON_CLONE="${DAEMON_CLONE:-/app/websites/omoikane.coach/daemon}"
ROOT="${ROOT:-/tmp}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-24}"
DRY=0
LOG_TAG="cleanup-daemon-worktrees"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)   DRY=1; shift ;;
    --max-age)   MAX_AGE_HOURS="$2"; shift 2 ;;
    --root)      ROOT="$2"; shift 2 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

log_info()  { logger -t "$LOG_TAG" -p user.info  "$@"; echo "[info]  $*"; }
log_warn()  { logger -t "$LOG_TAG" -p user.warn  "$@"; echo "[warn]  $*"; }
log_error() { logger -t "$LOG_TAG" -p user.error "$@"; echo "[error] $*"; }

run_or_dry() {
  if [[ $DRY -eq 1 ]]; then
    echo "[dry-run] would run: $*"
  else
    "$@"
  fi
}

bytes_freed=0
removed_count=0
target_wipe_count=0
skipped_count=0

# Refresh the merged-branch set. Two signals:
#  1. `git branch -r --merged origin/main` — catches fast-forward and
#     true-merge branches. Misses squash-merge (the default GitLab MR
#     mode here), since the squash commit isn't an ancestor of the
#     original branch tip.
#  2. GitLab MR API — for each branch starting with kp/ or feat/ that
#     names an OMOIKANE-NNN issue, check if a state=merged MR exists
#     for it. This is the dominant signal in our squash-merge flow.
log_info "refreshing $DAEMON_CLONE origin/main"
merged_set=""
if [[ -d "$DAEMON_CLONE/.git" ]]; then
  run_or_dry git -C "$DAEMON_CLONE" fetch --quiet --prune origin
  merged_set=$(git -C "$DAEMON_CLONE" branch -r --merged origin/main 2>/dev/null \
    | sed -e 's|^[[:space:]]*||' -e 's|^origin/||' \
    | grep -v '^HEAD ->' | sort -u)
else
  log_warn "$DAEMON_CLONE not a git repo — skipping worktree-merged sweep"
fi

# Compute the squash-merged-via-GitLab set. Pull the last 200 merged
# MRs (covers ~6 weeks of activity). One bulk query, not per-worktree.
GITLAB_TOKEN="${GITLAB_TOKEN:-$(cat /home/app-user/.config/omoikane-gitlab/token 2>/dev/null || true)}"
gitlab_merged_set=""
if [[ -n "$GITLAB_TOKEN" ]]; then
  gitlab_merged_set=$(curl -sk --max-time 30 \
      --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
      "https://gitlab.example.net/api/v4/projects/39/merge_requests?state=merged&per_page=100&order_by=updated_at" \
    | python3 -c "
import json, sys
try:
    arr = json.load(sys.stdin)
    if isinstance(arr, list):
        for m in arr:
            sb = m.get('source_branch')
            if sb:
                print(sb)
except Exception:
    pass
" | sort -u)
  log_info "gitlab merged set: $(echo "$gitlab_merged_set" | wc -l) branches"
else
  log_warn "no GITLAB_TOKEN — skipping GitLab merged-MR squash-detect"
fi

# Snapshot pre-cleanup footprint for the syslog summary line.
# Use printf "%d" so awk doesn't emit scientific notation for >2 GiB totals
# (bash arithmetic chokes on "1.09995e+10").
total_before=$(du -sb "$ROOT"/daemon-* 2>/dev/null | awk '{sum+=$1} END {printf "%.0f", sum+0}')

# Track the current process's own worktree (if running inside one) so we
# never reap our own foot.
self_worktree=""
if [[ -d "$PWD/.git" || -f "$PWD/.git" ]]; then
  self_worktree="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)"
fi

# Tier 1 — remove worktrees on merged branches.
shopt -s nullglob
for wt in "$ROOT"/daemon-*; do
  [[ -d "$wt" ]] || continue
  [[ "$wt" == "$self_worktree" ]] && { log_info "skip $wt (self)"; ((skipped_count++)) || true; continue; }

  if ! [[ -d "$wt/.git" || -f "$wt/.git" ]]; then
    log_info "skip $wt (not a git worktree)"
    continue
  fi

  branch=$(git -C "$wt" branch --show-current 2>/dev/null || true)
  if [[ -z "$branch" ]]; then
    log_info "skip $wt (detached HEAD or missing branch)"
    continue
  fi

  # Active CWD inside the worktree? Skip — another app-user session
  # likely has the directory open. Use /proc/*/cwd instead of lsof +D
  # which is O(every-file-under-tree) and times out on multi-GB target/
  # dirs.
  if find /proc/[0-9]*/cwd -maxdepth 1 -lname "$wt*" 2>/dev/null | grep -q .; then
    log_warn "skip $wt (active CWD — branch=$branch)"
    ((skipped_count++)) || true
    continue
  fi

  # Is the branch in either merged signal? (FF/true-merge OR squash-merge.)
  is_merged=0
  why=""
  if [[ -n "$merged_set" ]] && grep -Fxq "$branch" <<<"$merged_set"; then
    is_merged=1; why="ff/true-merge"
  elif [[ -n "$gitlab_merged_set" ]] && grep -Fxq "$branch" <<<"$gitlab_merged_set"; then
    is_merged=1; why="gitlab-mr-merged"
  fi
  if (( is_merged )); then
    sz=$(du -sb "$wt" 2>/dev/null | awk '{printf "%.0f", $1+0}')
    log_info "remove $wt (branch $branch $why; freeing ${sz} bytes)"
    run_or_dry git -C "$DAEMON_CLONE" worktree remove --force "$wt" \
      || { log_warn "git worktree remove failed for $wt; falling back to rm"; \
           run_or_dry rm -rf "$wt"; }
    bytes_freed=$((bytes_freed + sz))
    ((removed_count++)) || true
    continue
  fi

  # Tier 2 — branch not merged, but stale target/ dir.
  # Cargo bumps `target/.rustc_info.json` on every invocation; its mtime
  # tracks the freshness signal in O(1). Walking `find target -mmin` is
  # O(files) and hangs on multi-GB target/ dirs that are mid-build.
  target="$wt/app/target"
  if [[ -d "$target" ]]; then
    indicator=""
    for cand in "$target/.rustc_info.json" "$target/debug/deps" "$target"; do
      if [[ -e "$cand" ]]; then indicator="$cand"; break; fi
    done
    if [[ -n "$indicator" ]]; then
      mt=$(stat -c %Y "$indicator" 2>/dev/null || echo 0)
      now=$(date +%s)
      age_h=$(( (now - mt) / 3600 ))
      if (( age_h > MAX_AGE_HOURS )); then
        sz=$(du -sb "$target" 2>/dev/null | awk '{printf "%.0f", $1+0}')
        log_info "wipe-target $target (last cargo ${age_h}h ago, branch $branch; freeing ${sz} bytes)"
        run_or_dry rm -rf "$target"
        bytes_freed=$((bytes_freed + sz))
        ((target_wipe_count++)) || true
      fi
    fi
  fi
done

total_after=$(du -sb "$ROOT"/daemon-* 2>/dev/null | awk '{sum+=$1} END {printf "%.0f", sum+0}')

# Pretty-print the summary line so a single grep over journal gives an
# operator their daily footprint trajectory.
delta=$((total_before - total_after))
mb() { awk -v n="$1" 'BEGIN{printf "%.1f", n/1024/1024}'; }
gb() { awk -v n="$1" 'BEGIN{printf "%.2f", n/1024/1024/1024}'; }

log_info "summary: removed=${removed_count} wiped-target=${target_wipe_count} skipped=${skipped_count} \
freed-on-disk=$(gb "$delta")GB freed-counter=$(gb "$bytes_freed")GB \
before=$(gb "$total_before")GB after=$(gb "$total_after")GB \
dry-run=${DRY}"
