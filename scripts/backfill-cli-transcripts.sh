#!/bin/bash
# Backfill session_transcripts from Claude Code CLI JSONL files.
# CLI JSONL lives in ~/.claude/projects/*/*.jsonl (different format from
# gateway /tmp/claude-run-<ISSUE>.jsonl, but archive-session-transcript.py
# now handles both formats).
#
# Usage:
#   backfill-cli-transcripts.sh [--limit N] [--embed]
#
# Each JSONL filename is a UUID session ID. We use "cli-<uuid>" as issue_id
# to distinguish from gateway sessions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARCHIVE_SCRIPT="$SCRIPT_DIR/archive-session-transcript.py"
CLI_BASE="$HOME/.claude/projects"
LIMIT="${1:-5}"
EMBED_FLAG=""

# Parse args
for arg in "$@"; do
  case "$arg" in
    --embed) EMBED_FLAG="--embed" ;;
    --limit) : ;;  # next arg is the number
    [0-9]*) LIMIT="$arg" ;;
  esac
done

if [ ! -f "$ARCHIVE_SCRIPT" ]; then
  echo "ERROR: archive-session-transcript.py not found at $ARCHIVE_SCRIPT"
  exit 1
fi

# Find JSONL files, sorted by modification time (newest first), skip tiny files
PROCESSED=0
TOTAL_CHUNKS=0

for jsonl in $(find "$CLI_BASE" -name '*.jsonl' -size +10k -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -"$LIMIT" | awk '{print $2}'); do
  uuid=$(basename "$jsonl" .jsonl)
  issue_id="cli-${uuid}"

  # Create a symlink in /tmp so archive-session-transcript.py can find it
  tmp_path="/tmp/claude-run-${issue_id}.jsonl"
  if [ -f "$tmp_path" ]; then
    rm -f "$tmp_path"
  fi
  ln -sf "$jsonl" "$tmp_path"

  echo "--- Processing $uuid ($(du -h "$jsonl" | cut -f1)) ---"
  output=$(python3 "$ARCHIVE_SCRIPT" "$issue_id" --session-id "$uuid" $EMBED_FLAG 2>&1) || true
  echo "$output"

  # Extract chunk count
  chunks=$(echo "$output" | grep -oP 'Inserted \K\d+' || echo 0)
  TOTAL_CHUNKS=$((TOTAL_CHUNKS + chunks))
  PROCESSED=$((PROCESSED + 1))

  # Clean up symlink
  rm -f "$tmp_path"
done

echo ""
echo "Backfill complete: processed $PROCESSED files, inserted $TOTAL_CHUNKS total chunks"
