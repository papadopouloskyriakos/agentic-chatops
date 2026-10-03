#!/usr/bin/env bash
# test-1160-scheduled-reboot-matcher.sh — self-learning scheduled-reboot suppression.
# Validates the safety floor of the Tier 1 phase-SR matcher end-to-end on an
# ISOLATED mktemp DB (NEVER the live gateway.db — the governance_chain lesson).
# Covers: env kill-switch, critical gate, reboot-class allowlist, observe-before-live,
# kill_switch, valid_until expiry, malformed cron (fail-open), strict time-window
# (on vs off schedule), DST correctness, promotion threshold, and the CLI integration.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

_mkdb() {  # echo a fresh temp DB with the full schema (incl. discovered_scheduled_reboots)
  local tmp; tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql" 2>/dev/null
  echo "$tmp"
}

# _match <db> <host> <rule> <sev> <now_utc_iso>  -> prints "matched" or "nomatch"
_match() (
  cd "$REPO_ROOT/scripts" && TIER1_SCHED_REBOOT_ENABLED=1 python3 - "$@" <<'PY'
import sys, sqlite3, datetime
import lib.scheduled_reboots as sr
dbpath, host, rule, sev, nowt = sys.argv[1:6]
db = sqlite3.connect(dbpath)
now = datetime.datetime.fromisoformat(nowt.replace("Z", "+00:00"))
r = sr.match_scheduled_reboot(host, rule, sev, now, db)
print("matched" if r.get("matched") else "nomatch")
PY
)

start_test "migration_022_table_and_indexes_exist"
  tmp=$(_mkdb)
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='discovered_scheduled_reboots'")
  assert_eq 1 "$n" "table exists"
  idx=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name='discovered_scheduled_reboots'")
  assert_ge 5 "$idx" "5 indexes (match partial, status, valid_until, host, unique)"
  rm -f "$tmp"
end_test

start_test "schema_version_registers_table"
  v=$(cd "$REPO_ROOT/scripts" && python3 -c "import lib.schema_version as s; print(s.current('discovered_scheduled_reboots'))" 2>/dev/null)
  assert_eq 1 "$v" "schema_version.current() = 1"
end_test

start_test "matcher_onschedule_summer_suppresses"
  # cron 07:00 Europe/Amsterdam = 05:00 UTC (CEST). window=[04:55,05:10]. now=05:02Z in-window.
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,site,cron_expr,tz,reboot_kind,source,status,valid_until,window_minutes,pre_buffer_minutes) VALUES('nl-gpu01','nl','0 7 * * *','Europe/Amsterdam','cron','discovery','live','2030-01-01T00:00:00Z',10,5);"
  assert_eq "matched" "$(_match "$tmp" nl-gpu01 'Device rebooted' warning 2026-06-29T05:02:00Z)" "07:00 Amsterdam reboot @ 05:02Z summer → suppress"
  rm -f "$tmp"
end_test

start_test "matcher_offschedule_escalates"
  # same host, now=13:09Z (the documented self-heal time) — outside both fire windows.
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,site,cron_expr,tz,reboot_kind,status,valid_until) VALUES('nl-gpu01','nl','0 7 * * *','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z');"
  assert_eq "nomatch" "$(_match "$tmp" nl-gpu01 'Device rebooted' warning 2026-06-29T13:09:00Z)" "13:09Z off-schedule → escalate"
  rm -f "$tmp"
end_test

start_test "matcher_dst_winter_correct_utc"
  # winter CET (UTC+1): 07:00 local = 06:00 UTC. window=[05:55,06:10]. now=06:02Z in-window.
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,site,cron_expr,tz,reboot_kind,status,valid_until) VALUES('h','nl','0 7 * * *','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z');"
  assert_eq "matched" "$(_match "$tmp" h 'Device rebooted' warning 2026-01-15T06:02:00Z)" "winter 07:00 local = 06:00Z (DST-correct)"
  rm -f "$tmp"
end_test

start_test "matcher_observing_never_suppresses"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until) VALUES('h','0 7 * * *','Europe/Amsterdam','cron','observing','2030-01-01T00:00:00Z');"
  assert_eq "nomatch" "$(_match "$tmp" h 'Device rebooted' warning 2026-06-29T05:02:00Z)" "observing row never suppresses (observe-before-live)"
  rm -f "$tmp"
end_test

start_test "matcher_killswitch_never_suppresses"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until,kill_switch) VALUES('h','0 7 * * *','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z',1);"
  assert_eq "nomatch" "$(_match "$tmp" h 'Device rebooted' warning 2026-06-29T05:02:00Z)" "kill_switch=1 → escalate"
  rm -f "$tmp"
end_test

start_test "matcher_expired_validuntil_never_suppresses"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until) VALUES('h','0 7 * * *','Europe/Amsterdam','cron','live','2020-01-01T00:00:00Z');"
  assert_eq "nomatch" "$(_match "$tmp" h 'Device rebooted' warning 2026-06-29T05:02:00Z)" "expired valid_until → escalate"
  rm -f "$tmp"
end_test

start_test "matcher_malformed_cron_fails_open"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until) VALUES('h','garbage !!','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z');"
  assert_eq "nomatch" "$(_match "$tmp" h 'Device rebooted' warning 2026-06-29T05:02:00Z)" "malformed cron → escalate (no crash)"
  rm -f "$tmp"
end_test

start_test "matcher_nonreboot_rule_skipped"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until) VALUES('h','0 7 * * *','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z');"
  assert_eq "nomatch" "$(_match "$tmp" h 'CPU high' warning 2026-06-29T05:02:00Z)" "non-reboot rule → GUARD1 skip"
  rm -f "$tmp"
end_test

start_test "matcher_critical_never_suppresses"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until) VALUES('h','0 7 * * *','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z');"
  assert_eq "nomatch" "$(_match "$tmp" h 'Device rebooted' critical 2026-06-29T05:02:00Z)" "severity=critical → always investigate"
  rm -f "$tmp"
end_test

start_test "matcher_env_killswitch_off"
  # TIER1_SCHED_REBOOT_ENABLED unset AND no sentinel file -> no match (dark).
  # HOME is isolated to a temp dir so a real ~/gateway.sched_reboot can't leak in.
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until) VALUES('h','0 7 * * *','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z');"
  r=$(cd "$REPO_ROOT/scripts" && HOME="$(mktemp -d)" python3 - "$tmp" <<'PY'
import sys, sqlite3, datetime
import lib.scheduled_reboots as sr
db=sqlite3.connect(sys.argv[1])
now=datetime.datetime.fromisoformat("2026-06-29T05:02:00+00:00")
print("matched" if sr.match_scheduled_reboot('h','Device rebooted','warning',now,db).get('matched') else "nomatch")
PY
)
  assert_eq "nomatch" "$r" "no env + no sentinel -> dark (no match)"
  rm -f "$tmp"
end_test

start_test "promote_eligible_threshold"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,observed_count,valid_until) VALUES('a','0 7 * * *','Europe/Amsterdam','cron','observing',2,'2030-01-01T00:00:00Z'),('b','0 8 * * *','Europe/Amsterdam','cron','observing',1,'2030-01-01T00:00:00Z');"
  n=$(cd "$REPO_ROOT/scripts" && python3 - "$tmp" <<'PY'
import sys, sqlite3
import lib.scheduled_reboots as sr
db=sqlite3.connect(sys.argv[1])
print(sr.promote_eligible(db))
print(db.execute("SELECT hostname FROM discovered_scheduled_reboots WHERE status='live'").fetchall())
PY
)
  assert_contains "$n" "1" "1 row promoted (the observed_count=2 one)"
  assert_contains "$n" "[('a',)]" "only host 'a' went live; 'b' (count=1) stays observing"
  rm -f "$tmp"
end_test

start_test "upsert_observing_inserts_once_and_dedupes"
  tmp=$(_mkdb)
  r=$(cd "$REPO_ROOT/scripts" && python3 - "$tmp" <<'PY'
import sys, sqlite3
import lib.scheduled_reboots as sr
db = sqlite3.connect(sys.argv[1])
sr.upsert_observing(db, 'h', '0 7 * * *', 'cron', tz='Europe/Amsterdam', source='discovery', rationale='x')
sr.upsert_observing(db, 'h', '0 7 * * *', 'cron', tz='Europe/Amsterdam', source='discovery', rationale='x')  # idempotent
row = db.execute("SELECT COUNT(*), status, substr(valid_until,1,4) FROM discovered_scheduled_reboots").fetchone()
print(f"{row[0]} {row[1]} {row[2]}")
PY
)
  assert_contains "$r" "1 observing 2026" "upsert: 1 row (deduped), status observing, valid_until set"
  rm -f "$tmp"
end_test

start_test "cli_integration_onschedule_suppresses"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until) VALUES('nl-gpu01','0 7 * * *','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z');"
  out=$(cd "$REPO_ROOT/scripts" && TIER1_SCHED_REBOOT_ENABLED=1 python3 lib/tier1_suppression.py --hostname nl-gpu01 --rule-name "Device rebooted" --severity warning --db "$tmp" --triage-log /dev/null --no-yt-check --now-utc 2026-06-29T05:02:00Z 2>/dev/null)
  oc=$(echo "$out" | python3 -c 'import sys,json;print(json.load(sys.stdin)["outcome"])' 2>/dev/null)
  assert_eq "resolved-scheduled-reboot" "$oc" "CLI: on-schedule reboot suppressed via phase SR"
  rm -f "$tmp"
end_test

start_test "cli_integration_offschedule_escalates"
  tmp=$(_mkdb)
  sqlite3 "$tmp" "INSERT INTO discovered_scheduled_reboots(hostname,cron_expr,tz,reboot_kind,status,valid_until) VALUES('nl-gpu01','0 7 * * *','Europe/Amsterdam','cron','live','2030-01-01T00:00:00Z');"
  out=$(cd "$REPO_ROOT/scripts" && TIER1_SCHED_REBOOT_ENABLED=1 python3 lib/tier1_suppression.py --hostname nl-gpu01 --rule-name "Device rebooted" --severity warning --db "$tmp" --triage-log /dev/null --no-yt-check --now-utc 2026-06-29T13:09:00Z 2>/dev/null)
  oc=$(echo "$out" | python3 -c 'import sys,json;print(json.load(sys.stdin)["outcome"])' 2>/dev/null)
  assert_eq "escalate" "$oc" "CLI: off-schedule (13:09Z) escalates through all phases"
  rm -f "$tmp"
end_test

start_test "cli_phase1_future_dated_entry_escalates"
  # IFRNLLEI01PRD-1706: a future-dated (negative-age) triage.log entry must NOT dedup — the phase-1
  # window is [now-window, now]; without the upper bound a future timestamp gave age<0 and wrongly
  # suppressed the alert. Entry at 12:00Z, now 10:00Z (+2h future) -> must fail open to escalate.
  tmp=$(_mkdb); flog=$(mktemp --suffix=.triage.log)
  printf '2026-05-11T12:00:00Z|host-fut|RuleZ|nl|escalated|0.8|200|IFRNLLEI01PRD-9001\n' > "$flog"
  out=$(cd "$REPO_ROOT/scripts" && python3 lib/tier1_suppression.py --hostname host-fut --rule-name "RuleZ" --severity warning --db "$tmp" --triage-log "$flog" --no-yt-check --now-utc 2026-05-11T10:00:00Z 2>/dev/null)
  oc=$(echo "$out" | python3 -c 'import sys,json;print(json.load(sys.stdin)["outcome"])' 2>/dev/null)
  assert_eq "escalate" "$oc" "CLI: future-dated triage.log entry rejected, alert escalates (no negative-age dedup)"
  rm -f "$tmp" "$flog"
end_test
