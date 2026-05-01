#!/bin/bash
# OpenClaw Repo Sync — keeps all Git repos and Claude memory on nl-openclaw01 current
# Runs via cron on nl-openclaw01 every 30 minutes.
# Clones missing repos, pulls existing ones, syncs Claude memory feedback files.
#
# Repos mirror the directory structure on nl-claude01 (app-user).
# Memory feedback files are rsynced to /root/.claude-memory/ for local access.

set -uo pipefail

GITLAB_URL="https://gitlab.example.net"
GITLAB_TOKEN="REDACTED_ad791391tG86MQp1OjEH.01.0w1tny590"
CLONE_URL="https://gitlab-ci-token:${GITLAB_TOKEN}@gitlab.example.net"
BASE_DIR="/root/gitlab"
LOG="/tmp/openclaw-repo-sync.log"

exec >> "$LOG" 2>&1
echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ) repo-sync start ---"

# All repos that should exist (mirrors app-user)
declare -A REPOS=(
  ["infrastructure/nl/production"]="infrastructure/nl/production"
  ["infrastructure/gr/production"]="infrastructure/gr/production"
  ["infrastructure/common"]="infrastructure/common/production"
  ["n8n/claude-gateway"]="n8n/claude-gateway"
  ["n8n/doorbell"]="n8n/doorbell"
  ["products/cubeos/api"]="products/cubeos/api"
  ["products/cubeos/coreapps"]="products/cubeos/coreapps"
  ["products/cubeos/dashboard"]="products/cubeos/dashboard"
  ["products/cubeos/demo"]="products/cubeos/demo"
  ["products/cubeos/docs"]="products/cubeos/docs"
  ["products/cubeos/docsindex"]="products/cubeos/docsindex"
  ["products/cubeos/dot-github"]="products/cubeos/dot-github"
  ["products/cubeos/hal"]="products/cubeos/hal"
  ["products/cubeos/meshsat"]="products/cubeos/meshsat"
  ["products/cubeos/meshsat-android"]="products/cubeos/meshsat-android"
  ["products/cubeos/meshsat-hub"]="products/cubeos/meshsat-hub"
  ["products/cubeos/meshsat-website"]="products/cubeos/meshsat-website"
  ["products/cubeos/releases"]="products/cubeos/releases"
  ["products/cubeos/website"]="products/cubeos/website"
  ["rfc/hemb"]="rfc/hemb"
  ["rfc/ipougrs"]="rfc/ipougrs"
  ["websites/mulecube.com/www"]="websites/mulecube.com/www"
  ["websites/papadopoulos.tech/kyriakos"]="websites/papadopoulos.tech/kyriakos"
)

CLONED=0
PULLED=0
FAILED=0

for local_path in "${!REPOS[@]}"; do
  remote_path="${REPOS[$local_path]}"
  repo_dir="$BASE_DIR/$local_path"

  if [ -d "$repo_dir/.git" ]; then
    # Existing repo — pull
    if git -C "$repo_dir" pull --ff-only origin main >/dev/null 2>&1; then
      PULLED=$((PULLED + 1))
    else
      # Try with default branch detection
      default_branch=$(git -C "$repo_dir" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
      if [ -n "$default_branch" ] && git -C "$repo_dir" pull --ff-only origin "$default_branch" >/dev/null 2>&1; then
        PULLED=$((PULLED + 1))
      else
        echo "WARN: pull failed for $local_path"
        FAILED=$((FAILED + 1))
      fi
    fi
  else
    # Missing repo — clone
    mkdir -p "$(dirname "$repo_dir")"
    if git clone --depth 1 "${CLONE_URL}/${remote_path}.git" "$repo_dir" >/dev/null 2>&1; then
      echo "CLONED: $local_path"
      CLONED=$((CLONED + 1))
    else
      echo "WARN: clone failed for $remote_path"
      FAILED=$((FAILED + 1))
    fi
  fi
done

# ─── Sync Claude memory feedback files from app-user ───
# These are read by claude-knowledge-lookup.sh for operational rules.
# Uses SSH+tar (rsync not available on openclaw01).
MEMORY_DIR="/root/.claude-memory"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -i /root/.ssh/one_key"

mkdir -p "$MEMORY_DIR/infrastructure-nl" "$MEMORY_DIR/infrastructure-gr" "$MEMORY_DIR/gateway"

# Tar feedback files on app-user, pipe to local extract
# NL infra memories
ssh $SSH_OPTS app-user@nl-claude01 \
  "cd /home/app-user/.claude/projects/-home-app-user-gitlab-infrastructure-nl-production/memory && tar cf - feedback_*.md 2>/dev/null" \
  | tar xf - -C "$MEMORY_DIR/infrastructure-nl/" 2>/dev/null && true

# GR infra memories
ssh $SSH_OPTS app-user@nl-claude01 \
  "cd /home/app-user/.claude/projects/-home-app-user-gitlab-infrastructure-gr-production/memory && tar cf - feedback_*.md 2>/dev/null" \
  | tar xf - -C "$MEMORY_DIR/infrastructure-gr/" 2>/dev/null && true

# Gateway memories
ssh $SSH_OPTS app-user@nl-claude01 \
  "cd /home/app-user/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory && tar cf - feedback_*.md 2>/dev/null" \
  | tar xf - -C "$MEMORY_DIR/gateway/" 2>/dev/null && true

MEM_COUNT=$(find "$MEMORY_DIR" -name 'feedback_*.md' 2>/dev/null | wc -l)

# ─── Sync gateway.db read-only copy (for local semantic search) ───
# The triage scripts use kb-semantic-search.py which needs gateway.db.
# Write operations still go to app-user via SSH; this is a read replica.
DB_DIR="/root/.claude-data"
mkdir -p "$DB_DIR"
scp -o StrictHostKeyChecking=no -o ConnectTimeout=10 -i /root/.ssh/one_key \
  app-user@nl-claude01:/app/cubeos/claude-context/gateway.db \
  "$DB_DIR/gateway.db" 2>/dev/null && DB_SYNCED="yes" || DB_SYNCED="no"

echo "repos: pulled=$PULLED cloned=$CLONED failed=$FAILED | memories: $MEM_COUNT feedback files | db_synced: $DB_SYNCED"
echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ) repo-sync done ---"
