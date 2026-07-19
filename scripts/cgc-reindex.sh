#!/bin/bash
# CGC scheduled re-index — indexes all active CubeOS/MeshSat repos
# Runs via cron every 2h + @reboot. Replaces the live watcher.
set -euo pipefail

LOCKFILE="/tmp/cgc-reindex.lock"
LOGFILE="/home/app-user/scripts/watchdog-state/cgc-reindex.log"
VENV="/home/app-user/.cgc-venv/bin/activate"
CUBEOS="/app/cubeos"

# Repos with indexable code (Go, Python, JS/TS, Vue, Kotlin)
REPOS=(meshsat meshsat-hub api hal dashboard meshsat-android)

# Prevent overlapping runs
exec 9>"$LOCKFILE"
if ! flock -n 9; then
    echo "$(date): skipped — previous reindex still running" >> "$LOGFILE"
    exit 0
fi

source "$VENV"

# Disable auto-watch during index (blocks on completion otherwise)
export ENABLE_AUTO_WATCH=false

echo "$(date): reindex started" >> "$LOGFILE"

for repo in "${REPOS[@]}"; do
    dir="$CUBEOS/$repo"
    if [ ! -d "$dir" ]; then
        echo "$(date): SKIP $repo — directory missing" >> "$LOGFILE"
        continue
    fi
    start=$(date +%s)
    if timeout 600 cgc index "$dir" >> "$LOGFILE" 2>&1; then
        elapsed=$(( $(date +%s) - start ))
        echo "$(date): OK $repo (${elapsed}s)" >> "$LOGFILE"
    else
        elapsed=$(( $(date +%s) - start ))
        echo "$(date): FAIL $repo (${elapsed}s, exit $?)" >> "$LOGFILE"
    fi
done

echo "$(date): reindex complete" >> "$LOGFILE"
