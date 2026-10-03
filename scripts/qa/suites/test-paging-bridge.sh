#!/usr/bin/env bash
# Paging bridge (2026-08-25 ntfy cutover) — static + hermetic logic contract.
# Covers: channel decision by labels.page, edge-triggered episode dedup,
# resolved-only-after-paged, SMS fail-over + hourly cap + suppression notice,
# PagingPushDown edge-trigger, heartbeat site-scoping (SMS only for own site),
# textfile metrics shape, session path still suppressed. No network, no SMS:
# ntfy target is a dead loopback port and send_sms is monkeypatched.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="paging-bridge"

PB="$REPO_ROOT/scripts/paging-bridge.py"

start_test "bridge_and_helpers_syntax_ok"
  ok=$(python3 -m py_compile "$PB" 2>/dev/null && python3 -m py_compile "$REPO_ROOT/scripts/lib/ntfy.py" 2>/dev/null && bash -n "$REPO_ROOT/scripts/lib/ntfy.sh" 2>/dev/null && echo PASS || echo FAIL)
  assert_eq "PASS" "$ok"
end_test

start_test "unit_points_at_paging_bridge"
  u="$REPO_ROOT/scripts/systemd/paging-bridge.service"
  ok=$([ -f "$u" ] && grep -q "scripts/paging-bridge.py" "$u" && grep -q "PAGING_SITE=nl" "$u" && echo OK || echo BAD)
  assert_eq "OK" "$ok"
end_test

LOGIC_OUT="$(python3 - "$PB" <<'PY'
import importlib.util, os, sys, tempfile, time, types

os.environ.update({
    "AM_TWILIO_ENV": "/nonexistent",              # no real creds
    "PAGING_DRY_RUN": "0",                         # exercise the real code paths
    "NTFY_URL": "http://127.0.0.1:9",              # dead port -> ntfy always fails
    "NTFY_TOKEN": "tk_test", "NTFY_TOPIC_TIER1": "alrt-test",
    "PAGING_SITE": "nl",
    "PAGING_SMS_FAILOVER_CAP_PER_H": "3",
    "PAGING_NTFY_DOWN_AFTER": "3",
    "PAGING_WATCHDOG_TIMEOUT_S": "900",
    "PAGING_TEXTFILE": tempfile.mktemp(prefix="paging_bridge_qa_", suffix=".prom"),
    "AUTONOMY_SESSION_SMS": "",                    # session path OFF
})
sys.path.insert(0, os.path.dirname(sys.argv[1]))
spec = importlib.util.spec_from_file_location("pb", sys.argv[1])
pb = importlib.util.module_from_spec(spec); spec.loader.exec_module(pb)

sms_log = []
pb.send_sms = lambda body: (sms_log.append(body) or (True, "qa-mock"))
res = []

def alert(name, inst, status="firing", page=None, sev="critical", tier="1"):
    labels = {"tier": tier, "severity": sev, "alertname": name, "instance": inst, "site": "nl"}
    if page: labels["page"] = page
    return {"status": status, "labels": labels,
            "annotations": {"summary": f"{name} summary"}, "startsAt": "2026-08-26T00:00:00Z"}

# 1. non-tier1 skipped entirely
r = pb.handle_alertmanager_payload({"alerts": [alert("NoTier", "h", tier="2")]})
res.append(("skip_non_tier1", r == {"pushed": 0, "sms": 0, "deduped": 0, "resolved": 0}))

# 2. ntfy fails (dead port) -> fail-over SMS; page=sms adds the ULTRA SMS too
r = pb.handle_alertmanager_payload({"alerts": [alert("Ultra", "h1", page="sms")]})
res.append(("ultra_sms_sent", r["sms"] == 1 and any("Ultra" in b and not b.startswith("[PUSH-DOWN]") for b in sms_log)))
res.append(("failover_sms_sent", any(b.startswith("[PUSH-DOWN]") and "Ultra" in b for b in sms_log)))

# 3. edge dedup: same alert again -> deduped, no new SMS
n = len(sms_log)
r = pb.handle_alertmanager_payload({"alerts": [alert("Ultra", "h1", page="sms")]})
res.append(("edge_dedup", r["deduped"] == 1 and len(sms_log) == n))

# 4. resolved: one quiet notification; a second resolved is skipped
r = pb.handle_alertmanager_payload({"alerts": [alert("Ultra", "h1", status="resolved", page="sms")]})
res.append(("resolved_once", r["resolved"] == 1))
r = pb.handle_alertmanager_payload({"alerts": [alert("Ultra", "h1", status="resolved", page="sms")]})
res.append(("resolved_skip", r["resolved"] == 0))

# 5. fail-over cap: cap=3/h; Ultra already consumed 1 -> 2 more allowed, then notice
before = len([b for b in sms_log if b.startswith("[PUSH-DOWN]")])
for i in range(4):
    pb.handle_alertmanager_payload({"alerts": [alert(f"NoLabel{i}", "h2")]})
pd = [b for b in sms_log if b.startswith("[PUSH-DOWN]")]
res.append(("failover_capped_3_plus_notice",
            len(pd) == 4 and sum("suppressed on SMS" in b for b in pd) == 1))

# 6. PagingPushDown edge-trigger: 3 consecutive probe failures -> exactly one SMS
n = len(sms_log)
for _ in range(5):
    pb._probe_ntfy()
pp = [b for b in sms_log[n:] if "PagingPushDown" in b]
res.append(("pushdown_paged_once", len(pp) == 1))

# 7. heartbeat: own site pages SMS on loss; remote site is push-only
pb.handle_heartbeat_payload({"alerts": [{"labels": {"site": "nl", "alertname": "Watchdog"}},
                                        {"labels": {"site": "no", "alertname": "Watchdog"}}]})
with pb._watchdog_lock:
    for s in ("nl", "no"):
        pb._watchdog[s]["last"] = time.time() - 2000
n = len(sms_log)
pb._watchdog_check()
lost = [b for b in sms_log[n:] if "PrometheusHeartbeatLost" in b]
res.append(("heartbeat_sms_own_site_only", len(lost) == 1 and "site=nl" in lost[0]))

# 8. metrics file shape
pb._write_metrics()
tf = os.environ["PAGING_TEXTFILE"]
try:
    blob = open(tf).read()
except FileNotFoundError:
    blob = ""
res.append(("metrics_file_shape", all(k in blob for k in (
    "paging_bridge_heartbeat_timestamp_seconds", "paging_ntfy_up",
    "paging_events_total", "paging_watchdog_last_seen_timestamp_seconds"))))
if os.path.exists(tf):
    os.unlink(tf)

# 9. session path still suppressed
r = pb.handle_session_payload({"issue_id": "QA-1"})
res.append(("session_suppressed", r["outcome"] == "suppressed"))

for name, ok in res:
    print(f"{name}={'PASS' if ok else 'FAIL'}")
PY
)"

for t in skip_non_tier1 ultra_sms_sent failover_sms_sent edge_dedup resolved_once resolved_skip \
         failover_capped_3_plus_notice pushdown_paged_once heartbeat_sms_own_site_only \
         metrics_file_shape session_suppressed; do
  start_test "logic_$t"
    assert_eq "PASS" "$(printf '%s\n' "$LOGIC_OUT" | sed -n "s/^${t}=//p")"
  end_test
done

start_test "owasp_audit_tracks_new_bridge_path"
  ok=$(grep -q "scripts/paging-bridge.py" "$REPO_ROOT/scripts/audit-owasp-agentic.py" && ! grep -q "alertmanager-twilio-bridge.py" "$REPO_ROOT/scripts/audit-owasp-agentic.py" && echo OK || echo BAD)
  assert_eq "OK" "$ok"
end_test

start_test "registry_has_paging_bridge_prom_writer"
  ok=$(python3 -c "
import json
d = json.load(open('$REPO_ROOT/config/component-registry.json'))
c = [x for x in d['components'] if x.get('name') == 'prom:paging_bridge']
print('OK' if c and c[0].get('critical') and c[0]['liveness']['ref'] == 'paging_bridge.prom' else 'BAD')")
  assert_eq "OK" "$ok"
end_test

