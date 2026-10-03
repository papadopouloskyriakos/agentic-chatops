#!/bin/bash
# Backfill session_transcripts from Claude Code CLI JSONL files.
# IFRNLLEI01PRD-646: Tier 1 — nightly cron that drains the CLI JSONL backlog.
#
# CLI JSONL lives in ~/.claude/projects/*/*.jsonl (different format from the
# gateway /tmp/claude-run-<ISSUE>.jsonl, but archive-session-transcript.py
# handles both). Each JSONL filename is a UUID — we tag it as cli-<uuid>
# in session_transcripts.issue_id.
#
# Usage:
#   backfill-cli-transcripts.sh [--limit N] [--embed|--no-embed]
#                               [--oldest-first|--newest-first]
#                               [--no-watermark] [--no-toolcalls]
#
# Defaults (cron-safe):
#   --limit 50    --embed    --newest-first    watermark on    toolcalls on
#
# Cron line (nl-claude01):
#   30 4 * * * /app/claude-gateway/scripts/backfill-cli-transcripts.sh \
#     --embed --oldest-first --limit 50 \
#     >> /home/app-user/logs/claude-gateway/cli-transcript-backfill.log 2>&1

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARCHIVE_SCRIPT="$SCRIPT_DIR/archive-session-transcript.py"
PARSE_TOOLS_SCRIPT="$SCRIPT_DIR/parse-tool-calls.py"
CLI_BASE="$HOME/.claude/projects"
WATERMARK_FILE="$HOME/gitlab/products/cubeos/claude-context/.cli-transcript-watermark.json"

LIMIT=50
EMBED=1
ORDER="newest"
USE_WATERMARK=1
RUN_TOOLCALLS=1

while [ $# -gt 0 ]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --limit=*) LIMIT="${1#*=}"; shift ;;
    --embed) EMBED=1; shift ;;
    --no-embed) EMBED=0; shift ;;
    --oldest-first) ORDER="oldest"; shift ;;
    --newest-first) ORDER="newest"; shift ;;
    --no-watermark) USE_WATERMARK=0; shift ;;
    --no-toolcalls) RUN_TOOLCALLS=0; shift ;;
    [0-9]*) LIMIT="$1"; shift ;;  # back-compat: bare number
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [ ! -f "$ARCHIVE_SCRIPT" ]; then
  echo "ERROR: archive-session-transcript.py not found at $ARCHIVE_SCRIPT" >&2
  exit 1
fi

EMBED_FLAG=""
if [ "$EMBED" = "1" ]; then EMBED_FLAG="--embed"; else EMBED_FLAG="--no-embed"; fi

# Sort key: newest-first = %T@ desc, oldest-first = %T@ asc.
# Using python sort avoids find/sort coreutils quirks on odd filenames.
SORT_DIR="reverse=True"
if [ "$ORDER" = "oldest" ]; then SORT_DIR="reverse=False"; fi

echo "=== backfill-cli-transcripts.sh ==="
echo "  started:    $(date -u +%FT%TZ)"
echo "  limit:      $LIMIT"
echo "  embed:      $EMBED"
echo "  order:      $ORDER"
echo "  watermark:  $USE_WATERMARK"
echo "  toolcalls:  $RUN_TOOLCALLS"

# Pick candidate JSONLs via python (handles watermark + sort uniformly).
mapfile -t JSONLS < <(python3 - "$CLI_BASE" "$WATERMARK_FILE" "$LIMIT" "$USE_WATERMARK" "$ORDER" <<'PYEOF'
import json, os, sys
base, wm_path, limit, use_wm, order = sys.argv[1:6]
limit = int(limit)
use_wm = use_wm == "1"

wm = {}
if use_wm:
    try:
        wm = json.load(open(wm_path))
    except (FileNotFoundError, json.JSONDecodeError):
        wm = {}

candidates = []
for root, _, files in os.walk(base):
    for fn in files:
        if not fn.endswith(".jsonl"):
            continue
        p = os.path.join(root, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_size < 10240:   # skip tiny files (< 10 KB) like the old -size +10k
            continue
        prev = wm.get(p, {})
        if use_wm and prev:
            if prev.get("size") == st.st_size and abs(prev.get("mtime", 0) - st.st_mtime) < 1.0:
                continue   # unchanged since last run
        candidates.append((st.st_mtime, p))

candidates.sort(reverse=(order == "newest"))
for _, p in candidates[:limit]:
    print(p)
PYEOF
)

TOTAL=${#JSONLS[@]}
if [ "$TOTAL" = "0" ]; then
  echo "  no files to process (watermark caught up)"
  exit 0
fi

echo "  candidates: $TOTAL"
echo ""

PROCESSED=0
TOTAL_CHUNKS=0
TOOLCALL_TOTAL=0

for jsonl in "${JSONLS[@]}"; do
  uuid=$(basename "$jsonl" .jsonl)
  issue_id="cli-${uuid}"
  size=$(stat -c %s "$jsonl" 2>/dev/null || echo 0)
  size_h=$(numfmt --to=iec-i --suffix=B "$size" 2>/dev/null || echo "${size}B")

  echo "--- $uuid ($size_h) ---"
  # archive-session-transcript.py supports --source, so no /tmp symlink needed.
  archive_out=$(python3 "$ARCHIVE_SCRIPT" "$issue_id" \
    --session-id "$uuid" --source "$jsonl" $EMBED_FLAG 2>&1) || archive_out="$archive_out
[archive] exit non-zero (continuing)"
  echo "$archive_out"
  chunks=$(echo "$archive_out" | grep -oP 'Inserted \K\d+' | head -n1 || echo 0)
  chunks=${chunks:-0}
  TOTAL_CHUNKS=$((TOTAL_CHUNKS + chunks))

  # Tier 3: chain parse-tool-calls.py for the same file.
  if [ "$RUN_TOOLCALLS" = "1" ] && [ -f "$PARSE_TOOLS_SCRIPT" ]; then
    tc_out=$(python3 "$PARSE_TOOLS_SCRIPT" "$jsonl" --issue "$issue_id" --session "$uuid" 2>&1) || tc_out="$tc_out
[toolcalls] exit non-zero (continuing)"
    echo "$tc_out"
    tc=$(echo "$tc_out" | grep -oP '\[done\].* \K\d+(?= calls inserted)' | head -n1 || echo 0)
    tc=${tc:-0}
    TOOLCALL_TOTAL=$((TOOLCALL_TOTAL + tc))
  fi

  PROCESSED=$((PROCESSED + 1))
done

# Update watermark with the files we just processed.
if [ "$USE_WATERMARK" = "1" ]; then
  python3 - "$WATERMARK_FILE" "${JSONLS[@]}" <<'PYEOF'
import json, os, sys
wm_path = sys.argv[1]
files = sys.argv[2:]
try:
    wm = json.load(open(wm_path))
except (FileNotFoundError, json.JSONDecodeError):
    wm = {}
now_iso = os.popen("date -u +%FT%TZ").read().strip()
for p in files:
    try:
        st = os.stat(p)
    except OSError:
        continue
    wm[p] = {"size": st.st_size, "mtime": st.st_mtime, "last_run": now_iso}
# Prune entries for files that no longer exist (session rotation).
wm = {k: v for k, v in wm.items() if os.path.exists(k)}
os.makedirs(os.path.dirname(wm_path), exist_ok=True)
with open(wm_path, "w") as f:
    json.dump(wm, f, indent=2)
PYEOF
fi

# Tier 2: run the knowledge extractor over any new chunk_index=-1 summaries
# produced by archive-session-transcript.py above. Idempotent; safe per file.
EXTRACT_SCRIPT="$SCRIPT_DIR/extract-cli-knowledge.py"
EXTRACTED=0
if [ -f "$EXTRACT_SCRIPT" ] && [ "$PROCESSED" -gt 0 ]; then
  echo ""
  echo "=== extract-cli-knowledge (Tier 2) ==="
  extract_out=$(python3 "$EXTRACT_SCRIPT" --limit "$LIMIT" 2>&1) || extract_out="$extract_out
[extract] exit non-zero (continuing)"
  echo "$extract_out"
  EXTRACTED=$(echo "$extract_out" | grep -oP 'inserted=\K\d+' | head -n1 || echo 0)
  EXTRACTED=${EXTRACTED:-0}
fi

echo ""
echo "=== summary ==="
echo "  files processed:      $PROCESSED / $TOTAL"
echo "  transcript chunks:    $TOTAL_CHUNKS"
echo "  tool-call rows:       $TOOLCALL_TOTAL"
echo "  knowledge extracted:  $EXTRACTED"
echo "  finished:             $(date -u +%FT%TZ)"
