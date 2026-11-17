#!/bin/bash
# poll-openclaw-usage.sh — Collect OpenClaw Tier 1 usage from the container's
# Claude CLI JSONL session files. Mirror of poll-claude-usage.sh but
# remote-reads via SSH + docker exec.
#
# Why remote? The JSONL files live inside the openclaw container on
# nl-openclaw01:/home/node/.claude/projects/. We don't NFS/sshfs them.
# Instead, this script SSHes in, lists files via stat, then `docker exec
# tail -c +OFFSET` to read only new bytes per cron tick.
#
# Reads usage data: message.model + message.usage per assistant turn.
# Inserts per-day per-model token totals into llm_usage table with tier=1.
#
# Watermark: /app/cubeos/claude-context/.openclaw-jsonl-watermark.json
# Maps {filepath: bytes_read} to avoid re-processing.
#
# Cost: $0 (Max-subscription OAuth) — recorded as cost_usd=0.
# IFRNLLEI01PRD-746 (2026-04-28): replaces poll-openai-usage.sh after Tier 1
# migrated from gpt-5.1 to claude-sonnet-4-6 via OAuth.

set -euo pipefail

DB=/app/cubeos/claude-context/gateway.db
WATERMARK=/app/cubeos/claude-context/.openclaw-jsonl-watermark.json
OPENCLAW_HOST=nl-openclaw01
OPENCLAW_CONTAINER=openclaw-openclaw-gateway-1
PROJECTS_BASE=/home/node/.claude/projects

[ -f "$DB" ] || exit 0

# Ensure llm_usage table exists (idempotent — same schema as poll-claude-usage.sh)
sqlite3 "$DB" "CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tier INTEGER NOT NULL,
  model TEXT NOT NULL,
  issue_id TEXT DEFAULT '',
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cache_write_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);" 2>/dev/null

# List JSONL files with size + mtime via SSH + docker exec
LISTING=$(ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no \
  -i /home/app-user/.ssh/one_key root@$OPENCLAW_HOST \
  "docker exec -u node $OPENCLAW_CONTAINER find $PROJECTS_BASE -name '*.jsonl' -mtime -8 -exec stat -c '%n %s %Y' {} +" 2>/dev/null || echo "")

if [ -z "$LISTING" ]; then
  echo "$(date -Iseconds) [poll-openclaw-usage] no JSONL files found or SSH failed" >&2
  exit 0
fi

# Pass listing + watermark + DB path into Python for processing.
# NOTE: heredoc-with-pipe doesn't work (heredoc claims stdin), so we pass
# LISTING via an exported env var that Python reads from os.environ.
export LISTING
python3 << 'PYEOF'
import json, os, subprocess, sqlite3
from datetime import datetime

DB = "/app/cubeos/claude-context/gateway.db"
WATERMARK = "/app/cubeos/claude-context/.openclaw-jsonl-watermark.json"
HOST = "nl-openclaw01"
CONTAINER = "openclaw-openclaw-gateway-1"
SSH_KEY = "/home/app-user/.ssh/one_key"

# Load watermark: {filepath: bytes_read}
wm = {}
try:
    wm = json.load(open(WATERMARK))
except (json.JSONDecodeError, FileNotFoundError):
    pass

# day -> model -> {input, output, cache_read, cache_write, turns}
buckets = {}

listing = os.environ.get("LISTING", "")
for line in listing.splitlines():
    parts = line.strip().rsplit(" ", 2)
    if len(parts) != 3:
        continue
    jf, fsize_s, _mtime_s = parts
    try:
        fsize = int(fsize_s)
    except ValueError:
        continue
    prev_offset = wm.get(jf, 0)
    if fsize <= prev_offset:
        continue  # no new data

    # Read new bytes via docker exec (tail -c +OFFSET — 1-indexed)
    cmd = ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
           "-i", SSH_KEY, f"root@{HOST}",
           "docker", "exec", "-u", "node", CONTAINER,
           "tail", "-c", f"+{prev_offset + 1}", jf]
    try:
        new_bytes = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except subprocess.TimeoutExpired:
        continue
    if not new_bytes:
        continue

    for ln in new_bytes.splitlines():
        try:
            ev = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        model = msg.get("model")
        if not usage or not model:
            continue
        ts = ev.get("timestamp")
        if ts:
            try:
                day = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except (ValueError, AttributeError):
                day = datetime.now().strftime("%Y-%m-%d")
        else:
            day = datetime.now().strftime("%Y-%m-%d")
        b = buckets.setdefault(day, {}).setdefault(model, {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "turns": 0
        })
        b["input"] += usage.get("input_tokens", 0)
        b["output"] += usage.get("output_tokens", 0)
        b["cache_read"] += usage.get("cache_read_input_tokens", 0)
        b["cache_write"] += usage.get("cache_creation_input_tokens", 0)
        b["turns"] += 1
    wm[jf] = fsize

# Write rows: tier=1, issue_id='openclaw-cli', cost_usd=0 (Max sub)
# Schema versioning: writers in the 9 audited tables stamp schema_version=1
# (per scripts/lib/schema_version.py registry). llm_usage is NOT in that
# audited set, so we skip the column.
con = sqlite3.connect(DB)
inserted = 0
for day, models in buckets.items():
    for model, b in models.items():
        if not (b["input"] or b["output"] or b["cache_read"] or b["cache_write"]):
            continue
        con.execute(
            """INSERT INTO llm_usage
               (tier, model, issue_id, input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens, cost_usd, recorded_at)
               VALUES (1, ?, 'openclaw-cli', ?, ?, ?, ?, 0, ?)""",
            (model, b["input"], b["output"], b["cache_read"], b["cache_write"],
             day + " 00:00:00")
        )
        inserted += 1
con.commit()
con.close()

# Persist watermark
os.makedirs(os.path.dirname(WATERMARK), exist_ok=True)
with open(WATERMARK + ".tmp", "w") as f:
    json.dump(wm, f, indent=2, sort_keys=True)
os.replace(WATERMARK + ".tmp", WATERMARK)

print(f"[poll-openclaw-usage] inserted {inserted} llm_usage rows; watermark covers {len(wm)} files")
PYEOF
