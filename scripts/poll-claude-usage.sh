#!/bin/bash
# poll-claude-usage.sh — Collect Claude Code CLI usage for Tier 2
# Runs as cron every 30min on nl-claude01 as app-user
#
# Reads usage data from JSONL session files in ~/.claude/projects/
# (message.model + message.usage per assistant turn).
# Inserts per-day per-model token totals into llm_usage table.
#
# Watermark: tracks byte offset per JSONL file to avoid re-processing.
# For n8n-triggered sessions, the Runner workflow also inserts per-session
# tokens. This script fills the gap for interactive CLI sessions and
# ensures all session data reaches llm_usage.

set -euo pipefail

DB=/app/cubeos/claude-context/gateway.db
WATERMARK=/app/cubeos/claude-context/.claude-jsonl-watermark.json

[ -f "$DB" ] || exit 0

python3 << 'PYEOF'
import json, glob, os, sqlite3
from datetime import datetime

DB = "/app/cubeos/claude-context/gateway.db"
WATERMARK = "/app/cubeos/claude-context/.claude-jsonl-watermark.json"
BASE = os.path.expanduser("~/.claude/projects")

# Load watermark: {filepath: bytes_read}
wm = {}
try:
    wm = json.load(open(WATERMARK))
except (json.JSONDecodeError, FileNotFoundError):
    pass

# Scan all JSONL files modified in the last 8 days
cutoff = datetime.now().timestamp() - 8 * 86400
# day -> model -> {input, output, cache_read, cache_write, turns}
buckets = {}

for jf in glob.glob(f"{BASE}/**/*.jsonl", recursive=True):
    if os.path.getmtime(jf) < cutoff:
        continue
    fsize = os.path.getsize(jf)
    prev_offset = wm.get(jf, 0)
    if fsize <= prev_offset:
        continue  # no new data

    with open(jf) as f:
        f.seek(prev_offset)
        for line in f:
            try:
                ev = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            msg = ev.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            model = msg.get("model")
            if not usage or not model:
                continue

            # Determine day from the event timestamp
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

        wm[jf] = f.tell()

if not buckets:
    # Save watermark even if nothing new
    with open(WATERMARK, "w") as f:
        json.dump(wm, f)
    exit(0)

db = sqlite3.connect(DB)
inserted = 0

for day, models in sorted(buckets.items()):
    for model, t in models.items():
        total_new = t["input"] + t["output"] + t["cache_read"] + t["cache_write"]
        if total_new == 0:
            continue

        # Check what's already in llm_usage for this day+model from JSONL polls
        # (issue_id = 'cli-session' marks JSONL-extracted rows)
        existing = db.execute(
            """SELECT COALESCE(SUM(input_tokens + output_tokens
               + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)), 0)
               FROM llm_usage WHERE tier = 2 AND model = ?
               AND DATE(recorded_at) = ? AND issue_id = 'cli-session'""",
            (model, day)
        ).fetchone()[0]

        if total_new <= existing:
            continue  # already have this data

        delta = total_new - existing
        if delta <= 0:
            continue

        # Scale components proportionally for the delta
        ratio = delta / total_new
        in_tok = round(t["input"] * ratio)
        out_tok = round(t["output"] * ratio)
        cr_tok = round(t["cache_read"] * ratio)
        cw_tok = round(t["cache_write"] * ratio)

        db.execute(
            """INSERT INTO llm_usage
               (tier, model, issue_id, input_tokens, output_tokens,
                cache_write_tokens, cache_read_tokens, cost_usd, recorded_at)
               VALUES (2, ?, 'cli-session', ?, ?, ?, ?, 0, ? || ' 00:00:00')""",
            (model, in_tok, out_tok, cw_tok, cr_tok, day)
        )
        inserted += 1

db.commit()
db.close()

# Save watermark
with open(WATERMARK, "w") as f:
    json.dump(wm, f)

if inserted > 0:
    print(f"Inserted {inserted} Tier 2 usage records from JSONL files")
PYEOF
