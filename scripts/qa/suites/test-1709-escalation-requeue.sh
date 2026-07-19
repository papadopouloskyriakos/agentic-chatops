#!/usr/bin/env bash
# test-1709-escalation-requeue.sh — dropped-escalation requeue lane (IFRNLLEI01PRD-1709).
# Validates the escalation_queue producers/consumer end-to-end on an ISOLATED mktemp DB
# (NEVER the live gateway.db) with a local HTTP mock standing in for the n8n webhook,
# YouTrack, Thanos and the SMS bridge — no network, no live side effects.
# Covers: migration/schema presence, schema_version registry, queue-escalation.sh insert
# + dedup + issue-id validation, slot-locked fire/hold/one-per-slot, YT-resolved drop,
# session-active hold, poll-recheck recovered vs still-firing (+cap), eligible_at gating,
# max-attempts drop, and metrics file emission (world-readable).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

TMPDIR_T=$(mktemp -d)
trap 'kill $MOCK_PID 2>/dev/null; rm -rf "$TMPDIR_T"' EXIT

_mkdb() {
  local tmp="$TMPDIR_T/gw-$RANDOM.db"
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql" 2>/dev/null
  echo "$tmp"
}

# ── local mock: n8n webhook / YouTrack / Thanos / SMS on one port ────────────────
MOCK_PORT=$(( 20000 + RANDOM % 20000 ))
python3 - "$MOCK_PORT" "$TMPDIR_T/mock.log" <<'PY' &
import json, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
port, logf = int(sys.argv[1]), sys.argv[2]
class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
    def _record(self, kind):
        with open(logf, "a") as fh: fh.write(kind + " " + self.path + "\n")
    def do_GET(self):
        p = urllib.parse.unquote(self.path)
        if p.startswith("/api/issues/"):
            self._record("YT")
            resolved = VMID_REDACTED0000 if "RESOLVED" in p else None
            self._send({"resolved": resolved})
        elif p.startswith("/api/v1/query"):
            self._record("THANOS")
            firing = [{"metric": {}}] if "FiringAlert" in p else []
            self._send({"data": {"result": firing}})
        else:
            self._send({}, 404)
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._record("POST")
        self._send({"status": "accepted"})
HTTPServer(("127.0.0.1", port), H).serve_forever()
PY
MOCK_PID=$!
sleep 0.5

_requeue() {  # _requeue <db> [extra args...]
  local db="$1"; shift
  GATEWAY_DB="$db" GATEWAY_STATE_DIR="$TMPDIR_T" \
  N8N_WEBHOOK_URL="http://127.0.0.1:$MOCK_PORT/webhook/youtrack-webhook" \
  YOUTRACK_URL="http://127.0.0.1:$MOCK_PORT" \
  THANOS_URL="http://127.0.0.1:$MOCK_PORT" \
  AUTONOMY_SMS_URL="http://127.0.0.1:$MOCK_PORT/alert-session" \
  YOUTRACK_API_TOKEN="qa-dummy-token" \
  REQUEUE_METRICS_OUT="$TMPDIR_T/escalation_requeue.prom" \
  GATEWAY_DEBUG_LOG="$TMPDIR_T/dbg.log" \
  python3 "$REPO_ROOT/scripts/requeue-escalations.py" "$@"
}

start_test "schema_and_registry"
  db=$(_mkdb)
  n=$(sqlite3 "$db" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='escalation_queue'")
  assert_eq 1 "$n" "escalation_queue table in schema.sql"
  reg=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import CURRENT_SCHEMA_VERSION as C; print(C.get('escalation_queue', 0))")
  assert_eq 1 "$reg" "schema_version registry has escalation_queue=1"
end_test

start_test "queue_escalation_insert_dedup_validate"
  db=$(_mkdb)
  out=$(GATEWAY_DB="$db" GATEWAY_DEBUG_LOG="$TMPDIR_T/dbg.log" \
        bash "$REPO_ROOT/scripts/queue-escalation.sh" "IFRNLLEI01PRD-1" "disk%20full%20on%20nltest01" "gateway.lock.infra-nl" "slot-locked")
  assert_contains "$out" "QUEUED:new" "first insert"
  out=$(GATEWAY_DB="$db" GATEWAY_DEBUG_LOG="$TMPDIR_T/dbg.log" \
        bash "$REPO_ROOT/scripts/queue-escalation.sh" "IFRNLLEI01PRD-1" "disk%20full" "gateway.lock.infra-nl" "slot-locked")
  assert_contains "$out" "QUEUED:dedup" "repeat fire dedups"
  n=$(sqlite3 "$db" "SELECT COUNT(*) FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-1' AND status='pending'")
  assert_eq 1 "$n" "still one pending row"
  att=$(sqlite3 "$db" "SELECT attempts FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-1'")
  assert_eq 1 "$att" "dedup bumped attempts"
  summ=$(sqlite3 "$db" "SELECT summary FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-1'")
  assert_eq "disk full on nltest01" "$summ" "summary URI-decoded"
  out=$(GATEWAY_DB="$db" bash "$REPO_ROOT/scripts/queue-escalation.sh" 'bad;id$(reboot)' "x" "" "r" 2>&1) && rc=0 || rc=$?
  assert_ne 0 "$rc" "invalid issue_id refused (exit != 0)"
  assert_contains "$out" "REFUSED:invalid_issue_id" "refusal marker"
end_test

start_test "slot_locked_fires_when_free_and_one_per_slot"
  db=$(_mkdb)
  sqlite3 "$db" "INSERT INTO escalation_queue (issue_id, summary, kind, lock_file) VALUES
    ('IFRNLLEI01PRD-10','Alert: Devices up/down on nloas01','slot-locked','gateway.lock.infra-nl'),
    ('IFRNLLEI01PRD-11','Alert: Devices up/down on nloas03','slot-locked','gateway.lock.infra-nl')"
  rm -f "$TMPDIR_T/gateway.lock.infra-nl"
  out=$(_requeue "$db")
  assert_contains "$out" '"fired": 1' "exactly one fired for the shared slot"
  assert_contains "$out" '"held": 1' "second held (one-per-slot-per-run)"
  st=$(sqlite3 "$db" "SELECT status FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-10'")
  assert_eq "fired" "$st" "oldest row fired"
end_test

start_test "slot_locked_held_while_lock_fresh"
  db=$(_mkdb)
  sqlite3 "$db" "INSERT INTO escalation_queue (issue_id, summary, kind, lock_file) VALUES
    ('IFRNLLEI01PRD-20','Alert: x on nloas01','slot-locked','gateway.lock.infra-nl')"
  touch "$TMPDIR_T/gateway.lock.infra-nl"
  out=$(_requeue "$db")
  assert_contains "$out" '"held": 1' "held while lock fresh"
  st=$(sqlite3 "$db" "SELECT status FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-20'")
  assert_eq "pending" "$st" "stays pending"
  rm -f "$TMPDIR_T/gateway.lock.infra-nl"
end_test

start_test "resolved_issue_dropped"
  db=$(_mkdb)
  sqlite3 "$db" "INSERT INTO escalation_queue (issue_id, summary, kind, lock_file) VALUES
    ('IFRNLLEI01PRD-9RESOLVED','Alert: y on nloas02','slot-locked','gateway.lock.infra-nl')"
  out=$(_requeue "$db")
  st=$(sqlite3 "$db" "SELECT status||':'||last_note FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-9RESOLVED'")
  assert_eq "dropped:issue-resolved" "$st" "resolved YT issue dropped, never re-fired"
end_test

start_test "active_session_holds"
  db=$(_mkdb)
  sqlite3 "$db" "INSERT INTO sessions (issue_id, issue_title, session_id) VALUES ('IFRNLLEI01PRD-30','t','s30');
    INSERT INTO escalation_queue (issue_id, summary, kind, lock_file) VALUES
    ('IFRNLLEI01PRD-30','Alert: z on nloas03','slot-locked','gateway.lock.infra-nl')"
  out=$(_requeue "$db")
  st=$(sqlite3 "$db" "SELECT status FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-30'")
  assert_eq "pending" "$st" "held while a session exists for the issue"
end_test

start_test "poll_recheck_recovered_vs_still_firing"
  db=$(_mkdb)
  sqlite3 "$db" "INSERT INTO escalation_queue (issue_id, summary, kind, reason) VALUES
    ('IFRNLLEI01PRD-40','K8s Alert: QuietAlert (warning) on nl-claude01','poll-recheck','orphaned-poll'),
    ('IFRNLLEI01PRD-41','K8s Alert: FiringAlert (warning) on nl-claude01','poll-recheck','orphaned-poll')"
  out=$(_requeue "$db")
  st=$(sqlite3 "$db" "SELECT status FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-40'")
  assert_eq "recovered" "$st" "quiet alert marked recovered (no re-fire)"
  st=$(sqlite3 "$db" "SELECT status FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-41'")
  assert_eq "fired" "$st" "still-firing alert re-escalated"
  posts=$(grep -c "^POST" "$TMPDIR_T/mock.log" || true)
  assert_ge "$posts" 2 "webhook + SMS POSTs hit the mock (>=2)"
end_test

start_test "poll_recheck_cap_stands_down"
  db=$(_mkdb)
  sqlite3 "$db" "INSERT INTO session_log (issue_id, session_id, outcome, resolution_type) VALUES
    ('IFRNLLEI01PRD-50','s1','abandoned','poll_unanswered'), ('IFRNLLEI01PRD-50','s2','abandoned','poll_unanswered');
    INSERT INTO escalation_queue (issue_id, summary, kind) VALUES
    ('IFRNLLEI01PRD-50','K8s Alert: FiringAlert (warning) on nl-claude01','poll-recheck')"
  out=$(_requeue "$db")
  st=$(sqlite3 "$db" "SELECT status||':'||last_note FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-50'")
  assert_contains "$st" "dropped:recheck-cap" "cap reached -> stands down to a human"
end_test

start_test "eligible_at_future_not_processed"
  db=$(_mkdb)
  sqlite3 "$db" "INSERT INTO escalation_queue (issue_id, summary, kind, eligible_at) VALUES
    ('IFRNLLEI01PRD-60','K8s Alert: FiringAlert on nl-claude01','poll-recheck', datetime('now','+6 hours'))"
  out=$(_requeue "$db")
  assert_contains "$out" '"candidates": 0' "future eligible_at excluded"
end_test

start_test "max_attempts_drop_and_dry_run_no_writes"
  db=$(_mkdb)
  sqlite3 "$db" "INSERT INTO escalation_queue (issue_id, summary, kind, lock_file, attempts) VALUES
    ('IFRNLLEI01PRD-70','Alert: q on nloas01','slot-locked','gateway.lock.infra-nl', 3)"
  out=$(_requeue "$db")
  st=$(sqlite3 "$db" "SELECT status||':'||last_note FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-70'")
  assert_eq "dropped:max-attempts" "$st" "attempts cap drops"
  sqlite3 "$db" "INSERT INTO escalation_queue (issue_id, summary, kind, lock_file) VALUES
    ('IFRNLLEI01PRD-71','Alert: r on nloas02','slot-locked','gateway.lock.infra-nl')"
  out=$(_requeue "$db" --dry-run)
  st=$(sqlite3 "$db" "SELECT status FROM escalation_queue WHERE issue_id='IFRNLLEI01PRD-71'")
  assert_eq "pending" "$st" "dry-run changes nothing"
end_test

start_test "autocloser_parser_covers_all_live_summary_shapes"
  out=$(python3 - "$REPO_ROOT" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ac", sys.argv[1] + "/scripts/alert-yt-autoclose.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cases = [
    ("K8s Alert: KubePodNotReady (warning) in monitoring", ("prom", "KubePodNotReady")),
    ("Alert: nlnc01 - Device rebooted", ("ln", "nlnc01")),
    ("Alert: -- ALERT -- grpikvm01 -  Device Down! Due to no ICMP response.", ("ln", "grpikvm01")),
    ("Alert: Devices up/down on nloas01", ("ln", "nloas01")),
    ("Alert: Device Down! Due to no ICMP response. on nlredis01", ("ln", "nlredis01")),
    ("Alert: Service up/down on nl-iot02", ("ln", "nl-iot02")),
    ("Alert: Space on / is >= 90% and < 95% in use on nlghostfolio01", ("ln", "nlghostfolio01")),
    ("Alert: Device rebooted on nlpdu01.example.net", ("ln", "nlpdu01")),
    ("Alert: Port status up/down on nlrtr01", ("ln", "nlrtr01")),
    ("Correlated alert burst: 3 hosts affected at 04:04 UTC", ("burst", None)),
    ("[EPIC] Renovate MR Autonomy", ("unknown", None)),
    ("Alert: something odd with no host suffix", ("unknown", None)),
]
bad = [f"{s!r} -> {m.parse_issue(s)} (want {w})" for s, w in cases if m.parse_issue(s) != w]
hosts = sorted(set(m._HOST_RE.findall("burst: nloas02, nloas03.example.net and grcam01 affected")))
if hosts != ["grcam01", "nloas02", "nloas03"]:
    bad.append(f"burst host extraction: {hosts}")
print("ALL-SHAPES-OK" if not bad else "PARSE-FAIL: " + "; ".join(bad[:3]))
PY
)
  assert_contains "$out" "ALL-SHAPES-OK" "parse_issue + _HOST_RE cover every live alert-summary shape"
end_test

start_test "metrics_file_world_readable"
  assert_file_exists "$TMPDIR_T/escalation_requeue.prom" "metrics file written"
  perms=$(stat -c %a "$TMPDIR_T/escalation_requeue.prom")
  assert_eq 644 "$perms" "0644 (containerized node_exporter must be able to read it)"
  assert_contains "$(cat "$TMPDIR_T/escalation_requeue.prom")" "escalation_requeue_last_run_timestamp_seconds" "dead-man metric present"
end_test
