#!/bin/bash
# CLAUDE.md + Memory Knowledge Lookup — extracts procedural context for triage
# Usage: ./skills/claude-knowledge-lookup.sh <hostname> <alert_category> [--site nl|gr]
# Returns compact relevant knowledge from CLAUDE.md files + feedback memory files.
# Designed to be called by infra-triage.sh, k8s-triage.sh, correlated-triage.sh.
#
# Reads CLAUDE.md from local IaC repo ($IAC_REPO, set by site-config.sh).
# Reads feedback memories from local memory dirs (synced by repo-sync cron).
# Output capped at ~2000 chars to stay token-efficient.

set -uo pipefail

HOSTNAME="${1:?Usage: claude-knowledge-lookup.sh <hostname> <alert_category> [--site nl|gr]}"
ALERT_CATEGORY="${2:-general}"

# Parse --site flag
shift 2 2>/dev/null || true
while [ $# -gt 0 ]; do
  case "$1" in
    --site) TRIAGE_SITE="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Auto-detect site from hostname
if [ -z "${TRIAGE_SITE:-}" ]; then
  if echo "$HOSTNAME" | grep -qi "^grskg"; then
    TRIAGE_SITE="gr"
  else
    TRIAGE_SITE="nl"
  fi
fi

# Load site config if IAC_REPO not already set
if [ -z "${IAC_REPO:-}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  export TRIAGE_SITE
  source "$SCRIPT_DIR/site-config.sh" 2>/dev/null || true
fi

if [ -z "${IAC_REPO:-}" ] || [ ! -d "$IAC_REPO" ]; then
  echo "No IaC repo available for site $TRIAGE_SITE"
  exit 0
fi

# ─── Step 1: Route hostname to relevant CLAUDE.md files ───
CLAUDE_MDS=()

# Always include site root CLAUDE.md
[ -f "$IAC_REPO/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/CLAUDE.md")

# PVE host or guest (found in pve/ configs)
if grep -rq "hostname: $HOSTNAME" "$IAC_REPO/pve/" 2>/dev/null; then
  [ -f "$IAC_REPO/pve/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/pve/CLAUDE.md")
fi

# PVE physical host itself (hostname IS the PVE node)
if echo "$HOSTNAME" | grep -qiE "pve[0-9]"; then
  [ -f "$IAC_REPO/pve/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/pve/CLAUDE.md")
  [ -f "$IAC_REPO/native/pve/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/native/pve/CLAUDE.md")
fi

# Docker host (hostname directory exists under docker/)
if [ -d "$IAC_REPO/docker/$HOSTNAME" ]; then
  [ -f "$IAC_REPO/docker/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/docker/CLAUDE.md")
  # Service-specific CLAUDE.md (e.g., docker/nl-gpu01/ollama/CLAUDE.md)
  for svc_claude in "$IAC_REPO/docker/$HOSTNAME"/*/CLAUDE.md; do
    [ -f "$svc_claude" ] && CLAUDE_MDS+=("$svc_claude")
  done
fi

# Network device (fw/sw/rtr/ap/lte)
if echo "$HOSTNAME" | grep -qiE "(fw|sw|rtr|ap|lte)[0-9]"; then
  [ -f "$IAC_REPO/network/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/network/CLAUDE.md")
fi

# K8s node or kubernetes alert
if echo "$HOSTNAME" | grep -qiE "(k8s|ctrlr|wrkr)" || [ "$ALERT_CATEGORY" = "kubernetes" ]; then
  [ -f "$IAC_REPO/k8s/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/k8s/CLAUDE.md")
fi

# Edge/DMZ/VPS host
if echo "$HOSTNAME" | grep -qiE "(dmz|vps|edge)"; then
  [ -f "$IAC_REPO/edge/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/edge/CLAUDE.md")
fi

# Native services — check each subdir for hostname matches
if [ -d "$IAC_REPO/native" ]; then
  for native_dir in "$IAC_REPO/native"/*/; do
    [ -d "$native_dir" ] || continue
    dir_name=$(basename "$native_dir")
    # Match hostname in directory name or file contents
    if echo "$HOSTNAME" | grep -qi "$dir_name" || \
       grep -rlq "$HOSTNAME" "$native_dir" 2>/dev/null; then
      [ -f "${native_dir}CLAUDE.md" ] && CLAUDE_MDS+=("${native_dir}CLAUDE.md")
    fi
  done
fi

# Synology special case (hostname contains syno)
if echo "$HOSTNAME" | grep -qiE "syno[0-9]"; then
  [ -f "$IAC_REPO/native/synology/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/native/synology/CLAUDE.md")
fi

# CI/images (for runner/build hosts)
if echo "$HOSTNAME" | grep -qiE "(runner|build|ci)"; then
  [ -f "$IAC_REPO/ci/CLAUDE.md" ] && CLAUDE_MDS+=("$IAC_REPO/ci/CLAUDE.md")
fi

# Deduplicate
CLAUDE_MDS=($(printf '%s\n' "${CLAUDE_MDS[@]}" | sort -u))

if [ ${#CLAUDE_MDS[@]} -eq 0 ]; then
  echo "No relevant CLAUDE.md files found for $HOSTNAME"
  exit 0
fi

# ─── Step 2: Extract triage-relevant content from each CLAUDE.md ───
OUTPUT=""

for file in "${CLAUDE_MDS[@]}"; do
  [ -f "$file" ] || continue
  # Relative path for readability
  rel_path="${file#$IAC_REPO/}"
  section="### $rel_path"

  # First 3 lines (title + purpose)
  header=$(head -3 "$file" | grep -v '^$' | head -2)
  [ -n "$header" ] && section="$section
$header"

  # Lines mentioning the hostname (direct context)
  host_lines=$(grep -in "$HOSTNAME" "$file" 2>/dev/null | head -3)
  [ -n "$host_lines" ] && section="$section
Host mentions: $host_lines"

  # Warning/critical/known issue/never sections
  warnings=$(grep -iA2 -E "^#+.*(known issue|warning|critical|never|caution|important|danger)" "$file" 2>/dev/null | head -8)
  [ -n "$warnings" ] && section="$section
$warnings"

  # Alert-category-specific extraction
  cat_lines=""
  case "$ALERT_CATEGORY" in
    storage) cat_lines=$(grep -i -E "iscsi|nfs|zfs|raid|volume|disk|synology|seaweedfs|lun" "$file" 2>/dev/null | head -5) ;;
    network) cat_lines=$(grep -i -E "vlan|interface|bond|tunnel|vpn|bgp|ospf|ipsec|asa" "$file" 2>/dev/null | head -5) ;;
    kubernetes) cat_lines=$(grep -i -E "cilium|clustermesh|etcd|pod.cidr|cni|argocd|helm|pdb" "$file" 2>/dev/null | head -5) ;;
    resource) cat_lines=$(grep -i -E "cpu|memory|swap|oom|balloon|limit|quota" "$file" 2>/dev/null | head -5) ;;
    availability) cat_lines=$(grep -i -E "ha |failover|pacemaker|drbd|cluster|quorum|onboot" "$file" 2>/dev/null | head -5) ;;
    certificate) cat_lines=$(grep -i -E "cert|ssl|tls|acme|letsencrypt|openbao|pki" "$file" 2>/dev/null | head -5) ;;
  esac
  [ -n "$cat_lines" ] && section="$section
$cat_lines"

  OUTPUT="$OUTPUT
$section
"
done

# ─── Step 3: Feedback memory files (local) ───
# Memory dirs — use local paths (kept in sync by repo-sync cron)
# On OpenClaw container: /home/node/.claude-memory/
# On app-user: /home/app-user/.claude/projects/...
# Detect which host we're on
if [ -d "/home/node/.claude-memory" ]; then
  # OpenClaw container — synced memory dir
  if [ "$TRIAGE_SITE" = "gr" ]; then
    MEM_DIR="/home/node/.claude-memory/infrastructure-gr"
  else
    MEM_DIR="/home/node/.claude-memory/infrastructure-nl"
  fi
  GW_MEM_DIR="/home/node/.claude-memory/gateway"
elif [ -d "/home/app-user/.claude/projects" ]; then
  # app-user — native paths
  if [ "$TRIAGE_SITE" = "gr" ]; then
    MEM_DIR="/home/app-user/.claude/projects/-home-app-user-gitlab-infrastructure-gr-production/memory"
  else
    MEM_DIR="/home/app-user/.claude/projects/-home-app-user-gitlab-infrastructure-nl-production/memory"
  fi
  GW_MEM_DIR="/home/app-user/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory"
else
  MEM_DIR=""
  GW_MEM_DIR=""
fi

# Build search patterns from hostname components
HOST_SERVICE=$(echo "$HOSTNAME" | sed 's/^[a-z]*[0-9]*//' | sed 's/[0-9]*$//')
SEARCH_TERMS="$HOSTNAME"
case "$HOST_SERVICE" in
  pve*) SEARCH_TERMS="$SEARCH_TERMS|pve|proxmox|cluster" ;;
  fw*) SEARCH_TERMS="$SEARCH_TERMS|fw|asa|firewall|vpn" ;;
  sw*) SEARCH_TERMS="$SEARCH_TERMS|switch|vlan" ;;
  syno*) SEARCH_TERMS="$SEARCH_TERMS|synology|nas|nfs|iscsi" ;;
  gpu*) SEARCH_TERMS="$SEARCH_TERMS|gpu|ollama|cuda" ;;
  matrix*|mattermost*) SEARCH_TERMS="$SEARCH_TERMS|matrix|mattermost|bridge" ;;
  claude*|openclaw*) SEARCH_TERMS="$SEARCH_TERMS|claude|openclaw|gateway" ;;
  k8s*|ctrlr*|wrkr*) SEARCH_TERMS="$SEARCH_TERMS|k8s|kubernetes|cilium" ;;
  dmz*) SEARCH_TERMS="$SEARCH_TERMS|dmz|docker" ;;
  nms*) SEARCH_TERMS="$SEARCH_TERMS|librenms|monitoring|snmp" ;;
  syslog*) SEARCH_TERMS="$SEARCH_TERMS|syslog|logging" ;;
esac

MEMORY_OUTPUT=""
if [ -n "$MEM_DIR" ]; then
  MATCHES=$(grep -rlE "$SEARCH_TERMS" "$MEM_DIR"/feedback_*.md "$GW_MEM_DIR"/feedback_*.md 2>/dev/null | head -5)
  if [ -n "$MATCHES" ]; then
    MEMORY_OUTPUT="### Operational rules (from past sessions):"
    for f in $MATCHES; do
      NAME=$(grep '^name:' "$f" 2>/dev/null | head -1 | sed 's/^name: //')
      DESC=$(grep '^description:' "$f" 2>/dev/null | head -1 | sed 's/^description: //')
      MEMORY_OUTPUT="$MEMORY_OUTPUT
- **${NAME:-$(basename $f .md)}**: ${DESC:-no description}"
    done
  fi
fi

# ─── Step 4: Output — memories first (most critical), then CLAUDE.md context ───
# Memories contain "NEVER do X" rules and are more operationally critical than
# architectural context. Put them first so they survive truncation.
FULL_OUTPUT=""
[ -n "$MEMORY_OUTPUT" ] && FULL_OUTPUT="$MEMORY_OUTPUT
"
[ -n "$OUTPUT" ] && FULL_OUTPUT="$FULL_OUTPUT$OUTPUT"

if [ -z "$FULL_OUTPUT" ]; then
  echo "No relevant CLAUDE.md/memory knowledge found for $HOSTNAME"
  exit 0
fi

echo "$FULL_OUTPUT" | head -c 2000
if [ ${#FULL_OUTPUT} -gt 2000 ]; then
  echo ""
  echo "[truncated — ${#CLAUDE_MDS[@]} CLAUDE.md files matched]"
fi
