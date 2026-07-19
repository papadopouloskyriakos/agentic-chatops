# Daemon worktree cleanup (OMOIKANE-432)

Daily janitor for `/tmp/daemon-*` git worktrees from the
`websites/omoikane.coach/daemon` repo. Each session under the
operator's "per-session worktree" rule (P1.D) carries an `app/target/`
Rust build dir of ~4-12 GB. Over a productive week the host
accumulates 100+ GB on a 512 GB pool and trips quota-EDQUOT mid-build
(observed 2026-05-21).

## What runs

| Component | Path | Cadence |
|---|---|---|
| Script | `scripts/cleanup-daemon-worktrees.sh` | Manual `--dry-run` or via cron |
| Cron | `crontab -l \| grep cleanup-daemon` | 04:45 daily under `app-user` |
| Log | `/tmp/cleanup-daemon-worktrees.log` | Append-only |
| Syslog tag | `cleanup-daemon-worktrees` | One `summary:` line per run |

## Two-tier sweep

1. **Tier 1 — remove worktree entirely.** A worktree on a branch
   that is already merged into `main` (either fast-forward / true-merge
   per `git branch -r --merged`, or **squash-merge per GitLab MR API**
   — the dominant signal in our flow). Removed via
   `git worktree remove --force` so the worktree refs stay consistent.
2. **Tier 2 — wipe `app/target/` only.** A worktree whose branch is
   still in-flight, but whose `target/.rustc_info.json` (cargo's
   per-invocation marker) is older than `MAX_AGE_HOURS` (default 24).
   The worktree stays; only the rebuildable target dir disappears.

## Safety rails

- **Active-CWD skip.** Before touching a worktree, check every
  `/proc/[0-9]*/cwd` symlink — if any process has its CWD inside the
  worktree, skip with a `[warn]` log line. This is the cheap O(running
  processes) equivalent of `lsof +D`, which O(every file under tree)
  hangs on multi-GB target/ dirs that are mid-build.
- **`--dry-run`** prints every action without executing. Use this
  before any manual run on a host you haven't inspected.
- **Self-worktree skip.** A `self_worktree` variable resolves `$PWD`
  → repo top-level and is excluded explicitly.
- **GitLab API timeout.** The bulk-MR query has a 30 s timeout. If
  GitLab is down, `gitlab_merged_set` is empty and only Tier 1
  fast-forward + Tier 2 stale-target/ paths fire.

## Operator overrides

```bash
./scripts/cleanup-daemon-worktrees.sh --dry-run           # show plan, change nothing
./scripts/cleanup-daemon-worktrees.sh --max-age 1         # aggressive target wipe (1h)
./scripts/cleanup-daemon-worktrees.sh --root /scratch     # alt worktree root
DAEMON_CLONE=/srv/foo ./scripts/cleanup-daemon-worktrees.sh
GITLAB_TOKEN=glpat-x... ./scripts/cleanup-daemon-worktrees.sh
```

## Verification

After install:

```bash
crontab -l | grep cleanup-daemon
# Expect:
# 45 4 * * * /app/claude-gateway/scripts/cleanup-daemon-worktrees.sh >> /tmp/cleanup-daemon-worktrees.log 2>&1

./scripts/cleanup-daemon-worktrees.sh --dry-run | tail -1
# Expect a "summary:" line ending with "dry-run=1"

# Live one-shot (replace the timer fire):
./scripts/cleanup-daemon-worktrees.sh | grep summary:
# 2026-05-22 initial run: removed=60 wiped-target=0 freed-on-disk=120.10GB before=120.38GB after=0.29GB

# Daily check via journal:
journalctl --user-unit cron --since '24 hours ago' | grep cleanup-daemon
```

## Rollback

The script ONLY removes worktrees whose branches are merged-into-main
or whose target/ is stale. The work history is in `origin/main`; the
worktrees are derived artefacts. There is nothing to roll back — if a
worktree was incorrectly removed, re-create it on the same branch:

```bash
git -C /app/websites/omoikane.coach/daemon \
  worktree add /tmp/daemon-<purpose> <branch>
```

To disable the cron temporarily:

```bash
crontab -l | grep -v cleanup-daemon | crontab -
```
