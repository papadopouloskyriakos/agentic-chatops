#!/usr/bin/env bash
# gr-watches-nl (IFRNLLEI01PRD-2992) — hermetic logic + checker->bridge contract.
# Covers: degraded rule (critical / >=2 / info ignored), page only after 5 consecutive
# degraded runs, no re-page within the hour, hourly re-notify on a NEW episode key,
# recovery only after 3 healthy runs and only for a paged episode, observer-isolated
# runs frozen, time-boxed mute, bridge-down + bridge-lost-episode direct fallback,
# and the payload fed into the REAL paging-bridge.py handler: push on page, no SMS
# label, SMS only through the fail-over when ntfy fails. No network, no SMS:
# probes, clock, bridge POST and every send are injected or monkeypatched.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="gr-watches-nl"

GW="$REPO_ROOT/scripts/gr-watches-nl.py"
PB="$REPO_ROOT/scripts/paging-bridge.py"

start_test "script_syntax_ok"
  ok=$(python3 -m py_compile "$GW" 2>/dev/null && echo PASS || echo FAIL)
  assert_eq "PASS" "$ok"
end_test

start_test "units_shape"
  s="$REPO_ROOT/scripts/systemd/gr-watches-nl.service"
  t="$REPO_ROOT/scripts/systemd/gr-watches-nl.timer"
  ok=$([ -f "$s" ] && [ -f "$t" ] \
       && grep -q "ExecStart=/usr/bin/python3 /home/app-user/scripts/gr-watches-nl.py --once" "$s" \
       && grep -q "^User=app-user" "$s" && grep -q "^StateDirectory=gr-watches-nl" "$s" \
       && grep -q "GRWATCH_BRIDGE_URL=http://127.0.0.1:9106" "$s" \
       && grep -q "^OnCalendar=\*-\*-\* \*:\*:00" "$t" && echo OK || echo BAD)
  assert_eq "OK" "$ok"
end_test

start_test "runbook_exists"
  assert_file_exists "$REPO_ROOT/docs/runbooks/gr-watches-nl.md"
end_test

LOGIC_OUT="$(python3 - "$GW" "$PB" <<'PY'
import importlib.util, json, os, sys, tempfile

for k in ("GRWATCH_DEGRADED_AFTER", "GRWATCH_RECOVER_AFTER", "GRWATCH_RENOTIFY_S"):
    os.environ.pop(k, None)
def load(name, path, extra_env=None):
    if extra_env:
        os.environ.update(extra_env)
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

gw = load("gw", sys.argv[1])
res = []

def R(name, role, ok, info="x"):
    return {"name": name, "role": role, "ok": ok, "info": info}

HEALTHY = [R("TG intake", "critical", True), R("NL Prometheus+Alertmanager", "critical", True),
           R("nl-claude01", "critical", True), R("n8n", "normal", True),
           R("Home Assistant", "normal", True), R("Nextcloud", "normal", True),
           R("public edge", "info", True)]
def with_fail(*names, edge_ok=True):
    out = []
    for r in HEALTHY:
        r = dict(r)
        if r["name"] in names:
            r["ok"] = False; r["info"] = "timeout"
        if r["role"] == "info":
            r["ok"] = edge_ok
        out.append(r)
    return out

# 1. degraded rule
res.append(("rule_one_normal_not_degraded", gw.evaluate(with_fail("n8n"))[0] is False))
res.append(("rule_two_normal_degraded", gw.evaluate(with_fail("n8n", "Nextcloud"))[0] is True))
res.append(("rule_one_critical_degraded", gw.evaluate(with_fail("TG intake"))[0] is True))
res.append(("rule_info_ignored", gw.evaluate(with_fail(edge_ok=False))[0] is False))

class Sim:
    def __init__(self):
        self.t = 1_800_000_000.0
        self.results = HEALTHY
        self.posts = []
        self.direct = []
        self.observer = True
        self.post_status = "ok"
        self.bridge = None          # optional real-bridge handler
        d = tempfile.mkdtemp(prefix="grwatch-qa-")
        self.mute = os.path.join(d, "mute.json")
        self.w = gw.Watcher([], os.path.join(d, "state.json"), mute_path=self.mute,
                            probe_fn=lambda ts: self.results, post_fn=self.post,
                            direct_fn=self.direct_push, observer_fn=lambda: self.observer,
                            now_fn=lambda: self.t)
    def post(self, path, payload):
        self.posts.append(payload)
        if self.post_status != "ok":
            return self.post_status, {}
        if self.bridge:
            return "ok", self.bridge(payload)
        a = payload["alerts"][0]
        return "ok", ({"pushed": 1, "sms": 0, "deduped": 0, "resolved": 0} if a["status"] == "firing"
                      else {"pushed": 0, "sms": 0, "deduped": 0, "resolved": 1})
    def direct_push(self, title, body, prio, tags):
        self.direct.append((title, prio)); return True
    def run(self, n=1, step=60):
        rcs = []
        for _ in range(n):
            rcs.append(self.w.run_once()); self.t += step
        return rcs
    def firing(self):
        return [p for p in self.posts if p["alerts"][0]["status"] == "firing"]
    def resolved(self):
        return [p for p in self.posts if p["alerts"][0]["status"] == "resolved"]

# 2. page only on the 5th consecutive degraded run
s = Sim(); s.results = with_fail("TG intake")
s.run(4)
res.append(("no_page_before_5_runs", len(s.posts) == 0))
s.run(1)
res.append(("page_on_5th_run", len(s.firing()) == 1))
lab = s.firing()[0]["alerts"][0]["labels"]
res.append(("labels_tier1_critical_no_page_label",
            lab["tier"] == "1" and lab["severity"] == "critical" and "page" not in lab
            and lab["alertname"] == "NLSiteDegraded" and lab["site"] == "nl"))
first_inst = lab["instance"]

# 3. still degraded inside the hour -> no further page; at +1h -> re-notify on a NEW key
s.run(50)
res.append(("no_repage_within_hour", len(s.firing()) == 1))
s.run(10)
f = s.firing()
res.append(("renotify_after_hour_new_key",
            len(f) == 2 and f[1]["alerts"][0]["labels"]["instance"] != first_inst
            and f[1]["alerts"][0]["labels"]["instance"].endswith("#2")
            and "STILL" in f[1]["alerts"][0]["annotations"]["summary"]))
last_inst = f[1]["alerts"][0]["labels"]["instance"]

# 4. recovery: 2 healthy runs -> nothing; 3rd -> ONE resolved for the LAST key
s.results = HEALTHY
s.run(2)
res.append(("no_recovery_before_3_healthy", len(s.resolved()) == 0))
s.run(1)
r = s.resolved()
res.append(("one_recovery_last_key", len(r) == 1 and r[0]["alerts"][0]["labels"]["instance"] == last_inst))
s.run(5)
res.append(("no_second_recovery", len(s.resolved()) == 1 and s.w.load()["episode"] is None))

# 5. a flap (healthy run between degraded runs) does not end the episode or re-page
s2 = Sim(); s2.results = with_fail("n8n", "Nextcloud"); s2.run(5)
s2.results = HEALTHY; s2.run(1)
s2.results = with_fail("n8n", "Nextcloud"); s2.run(3)
res.append(("flap_keeps_one_episode", len(s2.firing()) == 1 and len(s2.resolved()) == 0))

# 6. degraded shorter than the threshold -> never pages, never recovers
s3 = Sim(); s3.results = with_fail("TG intake"); s3.run(4)
s3.results = HEALTHY; s3.run(5)
res.append(("short_blip_silent", len(s3.posts) == 0))

# 7. observer isolated -> runs skipped, counters frozen
s4 = Sim(); s4.results = with_fail("TG intake"); s4.run(3)
s4.observer = False; s4.run(10)
st = s4.w.load()
res.append(("observer_isolated_frozen", len(s4.posts) == 0 and st["cd"] == 3))
s4.observer = True; s4.run(2)
res.append(("observer_back_resumes", len(s4.firing()) == 1))

# 8. mute holds the page; it fires once the mute expires (recovery is never muted)
s5 = Sim()
with open(s5.mute, "w") as fh:
    json.dump({"until": s5.t + 600}, fh)
s5.results = with_fail("TG intake"); s5.run(8)
held = len(s5.posts) == 0
s5.run(4)
res.append(("mute_holds_then_pages", held and len(s5.firing()) == 1))

# 9. bridge not listening -> direct ntfy fallback, episode marked paged (no retry storm)
s6 = Sim(); s6.post_status = "refused"; s6.results = with_fail("TG intake"); s6.run(5)
res.append(("bridge_down_direct_fallback", len(s6.direct) == 1 and s6.direct[0][1] == 5))
s6.run(5)
res.append(("bridge_down_no_retry_storm", len(s6.direct) == 1))
# timeout -> assumed delivered, no direct duplicate
s6b = Sim(); s6b.post_status = "timeout"; s6b.results = with_fail("TG intake"); s6b.run(7)
res.append(("bridge_timeout_no_duplicate", len(s6b.direct) == 0 and s6b.w.load()["episode"]["paged"]))

# 10. bridge lost the episode (restart) -> recovery via direct push, quiet priority
s7 = Sim(); s7.results = with_fail("TG intake"); s7.run(5)
s7.bridge = lambda p: {"pushed": 0, "sms": 0, "deduped": 0, "resolved": 0}
s7.results = HEALTHY; s7.run(3)
res.append(("recovery_fallback_when_bridge_forgot", len(s7.direct) == 1 and s7.direct[0][1] == 3
            and s7.w.load()["episode"] is None))

# 11. contract with the REAL bridge handler (sends monkeypatched): push, no SMS while
#     ntfy is up; SMS only via the capped fail-over when ntfy fails; one resolved push.
pb = load("pb", sys.argv[2], {"AM_TWILIO_ENV": "/nonexistent", "PAGING_DRY_RUN": "0",
                              "NTFY_URL": "http://127.0.0.1:9", "NTFY_TOKEN": "tk_test",
                              "PAGING_SITE": "gr", "PAGING_SMS_FAILOVER_CAP_PER_H": "3",
                              "PAGING_TEXTFILE": tempfile.mktemp(suffix=".prom")})
pushes, sms = [], []
ntfy_up = {"v": True}
pb.send_push = lambda title, message, priority=5, tags="", click="", **kw: (
    pushes.append((title, priority)) or (ntfy_up["v"], "qa"))
pb.send_sms = lambda body: (sms.append(body) or (True, "qa"))
s8 = Sim(); s8.bridge = pb.handle_alertmanager_payload
s8.results = with_fail("TG intake", "NL Prometheus+Alertmanager"); s8.run(5)
res.append(("bridge_contract_push_no_sms", len(pushes) == 1 and pushes[0][1] == 5 and not sms
            and pushes[0][0] == "[nl] NLSiteDegraded"))
ntfy_up["v"] = False
s8.run(60)
res.append(("bridge_contract_failover_sms_on_renotify",
            len(pushes) == 2 and len(sms) == 1 and sms[0].startswith("[PUSH-DOWN] [FIRING] NLSiteDegraded")))
ntfy_up["v"] = True
s8.results = HEALTHY; s8.run(3)
res.append(("bridge_contract_one_resolved_push",
            len(pushes) == 3 and pushes[2][0].endswith("resolved") and len(sms) == 1
            and not s8.direct))

# 12. message content: failing checks named, NL time, rule, partition hint
s9 = Sim(); s9.results = with_fail(*[r["name"] for r in HEALTHY if r["role"] != "info"], edge_ok=True)
s9.run(5)
a = s9.firing()[0]["alerts"][0]
d = a["annotations"]["description"]
res.append(("message_names_checks_and_hint",
            "FAIL TG intake [critical]" in d and "since " in d and "partition" in d
            and "Rule:" in d and a["startsAt"].endswith("Z")))
s10 = Sim(); s10.results = with_fail("TG intake", edge_ok=False); s10.run(5)
res.append(("message_site_loss_hint",
            "DOWN too" in s10.firing()[0]["alerts"][0]["annotations"]["description"]))

# 13. duration parser + mute cap
res.append(("parse_duration", gw.parse_duration("90m") == 5400 and gw.parse_duration("2h") == 7200))

for name, ok in res:
    print(f"{name}={'PASS' if ok else 'FAIL'}")
PY
)"

for t in rule_one_normal_not_degraded rule_two_normal_degraded rule_one_critical_degraded rule_info_ignored \
         no_page_before_5_runs page_on_5th_run labels_tier1_critical_no_page_label \
         no_repage_within_hour renotify_after_hour_new_key no_recovery_before_3_healthy \
         one_recovery_last_key no_second_recovery flap_keeps_one_episode short_blip_silent \
         observer_isolated_frozen observer_back_resumes mute_holds_then_pages \
         bridge_down_direct_fallback bridge_down_no_retry_storm bridge_timeout_no_duplicate \
         recovery_fallback_when_bridge_forgot bridge_contract_push_no_sms \
         bridge_contract_failover_sms_on_renotify bridge_contract_one_resolved_push \
         message_names_checks_and_hint message_site_loss_hint parse_duration; do
  start_test "logic_$t"
    assert_eq "PASS" "$(printf '%s\n' "$LOGIC_OUT" | sed -n "s/^${t}=//p")"
  end_test
done
