#!/usr/bin/env python3
"""Deploy-drift guard (fundamentals-paydown 2026-06-26): makes the repo working-tree drift VISIBLE so it
can't silently re-accrue — the failure mode that left the live checkout 101 commits behind main with 64
untracked files in limbo. The crons run scripts directly from this working tree, so "what runs" = the
working tree, and drift between it and `origin/main` means stale running code (behind) or work at risk of
a clean/reset (uncommitted).

Emits to the textfile collector:
  repo_deploy_drift_commits_behind / _commits_ahead / _uncommitted_files / _branch_is_main / _last_run_ts.
Daily Cronicle job. READ-ONLY (git fetch/status/rev-list only — never touches the tree).
"""
import os
REDACTED_a7b84d63
import subprocess
import time

REPO = os.environ.get("GATEWAY_REPO", "/app/claude-gateway")
OUT = "/var/lib/node_exporter/textfile_collector/repo_deploy_drift.prom"


def _git(*args):
    try:
        return subprocess.run(["git", "-C", REPO, *args],
                              capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def main():
    _git("fetch", "origin", "main", "-q")  # read-only: only updates the remote-tracking ref
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    behind = _git("rev-list", "--count", "HEAD..origin/main") or "0"
    ahead = _git("rev-list", "--count", "origin/main..HEAD") or "0"
    # Cron-regenerated tracked artifacts are rewritten in place by their generator crons, so they show as
    # "modified" between periodic commits. That is expected churn, NOT work-in-limbo — count it separately
    # so the drift signal stays meaningful (real uncommitted work vs generator output).
    REGEN = ("config/interaction-graph.json", "config/component-registry.json",
             "config/orchestration-scorecard.json", "config/curriculum.json", "wiki/",
             "scripts/eval-sets/discovery.json")  # mine-failures-to-evals.py rewrites this via json.dumps
    # Collect uncommitted paths via diff/ls-files (clean one-path-per-line output) rather than parsing
    # `status -s` columns — the outer .stdout.strip() in _git() mangles the first status line's leading space.
    _mod = set(_git("diff", "--name-only").splitlines()) | set(_git("diff", "--cached", "--name-only").splitlines())
    _unt = set(_git("ls-files", "--others", "--exclude-standard").splitlines())
    paths = [p.strip() for p in (_mod | _unt) if p.strip()]
    def _is_regen(p):
        if any(p == r or p.startswith(r) for r in REGEN):
            return True
        try:  # auto-generated files tag their own header — robust vs an enumerated doc list
            with open(os.path.join(REPO, p)) as fh:
                if re.search(r"auto-?generated|do not edit|auto-refreshed", fh.read(400), re.I):
                    return True
        except Exception:
            pass
        return False
    uncommitted = sum(1 for p in paths if not _is_regen(p))
    regenerated = sum(1 for p in paths if _is_regen(p))
    is_main = 1 if branch == "main" else 0
    lines = [
        "# HELP repo_deploy_drift_commits_behind Commits the live checkout is behind origin/main (stale running code).",
        "# TYPE repo_deploy_drift_commits_behind gauge",
        f"repo_deploy_drift_commits_behind {behind}",
        "# HELP repo_deploy_drift_commits_ahead Local commits on the live checkout not on origin/main.",
        "# TYPE repo_deploy_drift_commits_ahead gauge",
        f"repo_deploy_drift_commits_ahead {ahead}",
        "# HELP repo_deploy_drift_uncommitted_files Uncommitted working-tree files that are real work (excludes cron-regenerated artifacts).",
        "# TYPE repo_deploy_drift_uncommitted_files gauge",
        f"repo_deploy_drift_uncommitted_files {uncommitted}",
        "# HELP repo_deploy_drift_regenerated_files Cron-regenerated tracked artifacts modified in place (expected churn, not drift).",
        "# TYPE repo_deploy_drift_regenerated_files gauge",
        f"repo_deploy_drift_regenerated_files {regenerated}",
        "# HELP repo_deploy_drift_branch_is_main 1 if the live checkout is on main, else 0.",
        "# TYPE repo_deploy_drift_branch_is_main gauge",
        f"repo_deploy_drift_branch_is_main {is_main}",
        "# HELP repo_deploy_drift_last_run_timestamp_seconds Unix ts of the last drift check.",
        "# TYPE repo_deploy_drift_last_run_timestamp_seconds gauge",
        f"repo_deploy_drift_last_run_timestamp_seconds {int(time.time())}",
    ]
    try:
        tmp = OUT + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, OUT)
    except Exception:
        pass
    print(f"  repo drift: branch={branch} behind={behind} ahead={ahead} uncommitted={uncommitted}")


if __name__ == "__main__":
    main()
