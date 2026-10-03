#!/usr/bin/env bash
# queue-escalation.sh <issue_id> <summary_uriencoded> <lock_file> <reason>
#
# Called by the Runner's "Queue Dropped Escalation" SSH node (the TRUE branch of
# "Is Locked?") so an accepted escalation that loses the slot race is QUEUED for
# scripts/requeue-escalations.py instead of silently discarded (the 2026-06-30
# nl-pve01 power-cycle burst dropped ~30 accepted escalations this way).
#
# Summary arrives encodeURIComponent()-encoded from the n8n expression so shell
# metacharacters can't break quoting; decoded + parameter-bound here in Python.
# Dedup: one pending slot-locked row per issue_id (repeat fires bump attempts).
set -euo pipefail

ISSUE_ID="${1:?issue_id required}"
SUMMARY_ENC="${2:-}"
LOCK_FILE="${3:-}"
REASON="${4:-slot-locked}"
DB="${GATEWAY_DB:-/home/app-user/gateway-state/gateway.db}"
DBG_LOG="${GATEWAY_DEBUG_LOG:-/home/app-user/logs/claude-gateway/pipeline-debug.log}"

if ! echo "$ISSUE_ID" | grep -qE '^[A-Z0-9]+-[0-9]+$'; then
  echo "REFUSED:invalid_issue_id:$ISSUE_ID"
  exit 1
fi

ISSUE_ID="$ISSUE_ID" SUMMARY_ENC="$SUMMARY_ENC" LOCK_FILE="$LOCK_FILE" REASON="$REASON" \
DB="$DB" DBG_LOG="$DBG_LOG" python3 - <<'PYEOF'
import json, os, sqlite3, time, urllib.parse

issue = os.environ["ISSUE_ID"]
summary = urllib.parse.unquote(os.environ.get("SUMMARY_ENC", ""))[:500]
lock_file = os.environ.get("LOCK_FILE", "")[:100]
reason = os.environ.get("REASON", "slot-locked")[:100]

conn = sqlite3.connect(os.environ["DB"], timeout=30)
conn.execute("PRAGMA busy_timeout=30000")
row = conn.execute(
    "SELECT id, attempts FROM escalation_queue "
    "WHERE issue_id=? AND kind='slot-locked' AND status='pending'", (issue,)).fetchone()
if row:
    conn.execute(
        "UPDATE escalation_queue SET attempts=attempts+1, "
        "last_note='repeat fire while queued', updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (row[0],))
    action = f"QUEUED:dedup:{issue}"
else:
    conn.execute(
        "INSERT INTO escalation_queue (issue_id, summary, kind, reason, lock_file) "
        "VALUES (?, ?, 'slot-locked', ?, ?)", (issue, summary, reason, lock_file))
    action = f"QUEUED:new:{issue}"
conn.commit()
conn.close()

try:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "script": "queue-escalation.sh", "pid": os.getpid(),
           "event": "escalation_queued", "issue_id": issue,
           "detail": f"kind=slot-locked lock_file={lock_file} reason={reason}"}
    os.makedirs(os.path.dirname(os.environ["DBG_LOG"]), exist_ok=True)
    with open(os.environ["DBG_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
except OSError:
    pass

print(action)
PYEOF
