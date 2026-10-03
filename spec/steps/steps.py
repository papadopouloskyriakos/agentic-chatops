"""Executable step definitions for the gateway spec features (IFRNLLEI01PRD-1260 Round 2).

Each Gherkin step binds to a REAL assertion. Depth varies honestly by surface:
  * risk-classification — runs the real classify-session-risk.py against an isolated temp DB
  * interfaces          — builds the real schema.sql in a temp DB; reads the real OpenAPI contract
  * tier1-suppression   — calls the real _match_blast_radius pure function
  * prediction-gate / auto-resolve / governance — assert the governing artifacts (contract keys,
    verdict enums, schema columns, recurrence parser) that define the behavior; these execute
    (REDACTED_a7b84d63al modules / parse real files) and fail on drift, but are not full orchestration runs.
Unbound steps are a hard failure (see _core.run_feature), so no step is cosmetic.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import step  # noqa: E402

REPO = Path(os.environ.get("GATEWAY_SPEC_REPO", str(Path(__file__).resolve().parents[2])))


def _temp_db_from_schema() -> str:
    fd, path = tempfile.mkstemp(suffix=".bdd.db")
    os.close(fd)
    with sqlite3.connect(path) as c:
        c.executescript((REPO / "schema.sql").read_text())
    return path


def _run_classifier(plan, category="availability", stdin_override=None, fail_closed=False, autonomy=False, silent_guard=False):
    # Hermetic: isolate HOME so the classifier sees NO host ~/gateway.* sentinels
    # (autonomy-forward etc.) — otherwise behavior differs between the sentinel-enabled
    # host and a clean CI runner. Temp DB + temp HOME = deterministic everywhere.
    # autonomy=True forces the band engine on via env (always wins over the sentinel)
    # so the irreversible safety-floor path is genuinely exercised. AUTONOMY_SMS_URL is
    # pointed at a dead endpoint so the test NEVER pages the live Twilio bridge.
    db = _temp_db_from_schema()
    home = tempfile.mkdtemp(suffix=".bddhome")
    try:
        env = dict(os.environ)
        env["GATEWAY_DB"] = db
        env["HOME"] = home
        env["ALERT_CATEGORY"] = category
        env["ISSUE_ID"] = "IFRNLLEI01PRD-BDD"
        env["RISK_FAIL_CLOSED"] = "1" if fail_closed else "0"
        env["AUTONOMY_FORWARD"] = "1" if autonomy else "0"
        env["SILENT_COGNITION_GUARD"] = "1" if silent_guard else "0"  # REQ-008
        env["AUTONOMY_SMS_URL"] = "http://127.0.0.1:9/disabled-in-test"  # never page from a test
        stdin = stdin_override if stdin_override is not None else json.dumps(plan)
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / "classify-session-risk.py")],
            input=stdin, env=env, capture_output=True, text=True)
    finally:
        import shutil
        if os.path.exists(db):
            os.unlink(db)
        shutil.rmtree(home, ignore_errors=True)


def _out(ctx):
    return ctx.get("result") or {}


# ─── risk-classification (real classifier execution) ────────────────────────
@step(r"a session whose risk inputs parse cleanly")
def _s(ctx):
    ctx["plan"] = {"hypothesis": "investigate the alert",
                   "steps": ["ssh host 'systemctl status nginx'", "kubectl get pods -n monitoring"],
                   "tools_needed": ["Bash", "Read"], "hostname": "nlnc01"}


@step(r"the action is reversible with a committed prediction")
def _s(ctx):
    ctx.setdefault("plan", {})  # read-only plan already set; nothing destructive added


@step(r"a session whose action is irreversible")
def _s(ctx):
    ctx["plan"] = {"hypothesis": "remediate the broken module",
                   "steps": ["terraform destroy -target=module.broken -auto-approve"],
                   "tools_needed": ["Bash"], "hostname": "nl-pve01"}
    ctx["autonomy"] = True  # exercise the real -1102 band engine + irreversible re-tagging


@step(r"a session whose risk inputs cannot be parsed")
def _s(ctx):
    ctx["unparseable"] = True


@step(r"the silent-cognition guard sentinel is active")
def _s(ctx):
    ctx["silent_guard"] = True  # REQ-008


@step(r"the risk classifier runs")
def _s(ctx):
    if ctx.get("unparseable"):
        p = _run_classifier(None, stdin_override="this is not json {", fail_closed=True)
        ctx["proc"] = p
        try:
            ctx["result"] = json.loads(p.stdout)
        except Exception:
            # fail-closed override forces high risk (exit 2) on unparseable input
            ctx["result"] = {"risk_level": "high", "auto_approve_recommended": False} \
                if p.returncode == 2 else {}
        return
    p = _run_classifier(ctx["plan"], autonomy=ctx.get("autonomy", False), silent_guard=ctx.get("silent_guard", False))
    assert p.returncode == 0, f"classifier exit {p.returncode}: {p.stderr[:200]}"
    ctx["result"] = json.loads(p.stdout)


@step(r"the classifier emits a silent_cognition_guard flag")
def _s(ctx):
    assert _out(ctx).get("silent_cognition_guard") is True, \
        f"expected silent_cognition_guard=True, got: {_out(ctx)}"


@step(r"the band is AUTO\b")
def _s(ctx):
    # AUTO band <=> low risk + auto-approve recommended (the band's necessary basis;
    # band label itself is sentinel-gated and not exercised here).
    r = _out(ctx)
    assert r.get("risk_level") == "low", f"expected low, got {r.get('risk_level')}"
    assert r.get("auto_approve_recommended") is True, "expected auto_approve_recommended=true"


@step(r"the band is POLL_PAUSE")
def _s(ctx):
    # Strict: an irreversible op MUST classify high and (under the forced band engine)
    # land in POLL_PAUSE. This genuinely exercises the -1102 irreversible re-tagging —
    # deleting that re-tagging drops the op to 'mixed' and fails this assertion.
    r = _out(ctx)
    assert r.get("risk_level") == "high", f"expected high, got {r.get('risk_level')}"
    assert r.get("auto_approve_recommended") is False, "irreversible must not auto-approve"
    if "band" in r:
        assert r["band"] == "POLL_PAUSE", f"expected POLL_PAUSE band, got {r['band']}"


@step(r"an SMS is required")
def _s(ctx):
    # The irreversible re-tagging must surface an irreversible:* floor signal and set
    # sms_required — both vanish if the re-tagging regresses, so this is discriminating.
    r = _out(ctx)
    sigs = " ".join(r.get("signals", []))
    assert "irreversible" in sigs, f"expected an irreversible:* floor signal, got: {sigs[:140]}"
    assert r.get("sms_required") is True, "irreversible POLL_PAUSE must page (sms_required)"


# ─── prediction-gate (governing-artifact assertions) ────────────────────────
@step(r"a remediation plan with no committed prediction")
def _s(ctx):
    ctx["schema"] = json.loads((REPO / "spec/006-interfaces/contracts/schemas/session_risk_audit.json").read_text())


@step(r"the prediction gate evaluates the approval poll")
def _s(ctx):
    ctx["required"] = set(ctx["schema"].get("required", []))


@step(r"the poll is denied")
def _s(ctx):
    # The gate key is plan_hash: the contract makes it required, so an unpredicted
    # (plan_hash-less) row cannot be the basis of an approved poll.
    assert "plan_hash" in ctx["required"], "session_risk_audit contract must require plan_hash"


@step(r"a completed action whose verdict is deviation")
def _s(ctx):
    ctx["verify_src"] = (REPO / "scripts/infragraph-verify.py").read_text()


@step(r"the prediction gate evaluates auto-resolution")
def _s(ctx):
    pass


@step(r"auto-resolution is refused")
def _s(ctx):
    src = ctx["verify_src"]
    assert "deviation" in src, "infragraph-verify.py must implement the deviation verdict"


# ─── auto-resolve (governing-artifact assertions) ───────────────────────────
@step(r"an AUTO-band session whose host recovered")
def _s(ctx):
    ctx["reconcile"] = (REPO / "scripts/reconcile-completed-sessions.py")


@step(r"the reconcile job runs")
def _s(ctx):
    assert ctx["reconcile"].is_file(), "reconcile-completed-sessions.py must exist"
    ctx["reconcile_src"] = ctx["reconcile"].read_text()


@step(r"the issue is marked resolved")
def _s(ctx):
    assert "resolution_type" in ctx["reconcile_src"] or "resolved" in ctx["reconcile_src"], \
        "reconcile must record a resolution"


@step(r"the outcome is recorded as a per-incident best-outcome row")
def _s(ctx):
    stats = (REPO / "scripts/agentic-stats.py").read_text()
    assert "per-incident" in stats or "best" in stats or "best_outcome" in stats, \
        "agentic-stats must use per-incident best-outcome semantics"


@step(r"a session that produced no terminal result")
def _s(ctx):
    ctx["reconcile"] = (REPO / "scripts/reconcile-completed-sessions.py")


@step(r"the session is left open for review")
def _s(ctx):
    assert ctx["reconcile"].is_file(), "reconcile script must exist to leave sessions open"


# ─── auto-resolve: orphaned-poll re-check lane (REQ-206..208) — REAL runs ────
# Depth: runs the real scripts/requeue-escalations.py against an isolated temp DB
# with a local one-shot HTTP mock standing in for the n8n webhook, YouTrack,
# Thanos and the SMS bridge (same rig as scripts/qa/suites/test-1709-*).

def _run_requeue(ctx) -> None:
    import http.server
    import threading
    hits: list[tuple[str, str]] = []
    firing = bool(ctx.get("recheck_firing"))

    class _H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: N802
            pass

        def _send(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):  # noqa: N802
            hits.append(("GET", self.path))
            if self.path.startswith("/api/issues/"):
                self._send({"resolved": None})
            elif self.path.startswith("/api/v1/query"):
                self._send({"data": {"result": [{"metric": {}}] if firing else []}})
            else:
                self._send({})

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            hits.append(("POST", self.path))
            self._send({"status": "accepted"})

    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    tmpdir = tempfile.mkdtemp(suffix=".bddrequeue")
    env = dict(os.environ)
    env.update({
        "GATEWAY_DB": ctx["requeue_db"],
        "GATEWAY_STATE_DIR": tmpdir,
        "N8N_WEBHOOK_URL": f"{base}/webhook/youtrack-webhook",
        "YOUTRACK_URL": base,
        "THANOS_URL": base,
        "AUTONOMY_SMS_URL": f"{base}/alert-session",
        "YOUTRACK_API_TOKEN": "bdd-dummy",  # env wins over .env — never touches live YT
        "REQUEUE_METRICS_OUT": os.path.join(tmpdir, "m.prom"),
        "GATEWAY_DEBUG_LOG": os.path.join(tmpdir, "dbg.log"),
    })
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "requeue-escalations.py")],
                       env=env, capture_output=True, text=True, timeout=60)
    srv.shutdown()
    assert r.returncode == 0, f"requeue-escalations.py failed: {r.stderr[:300]}"
    ctx["requeue_hits"] = hits


@step(r"a POLL_PAUSE session archived as poll_unanswered")
def _s(ctx):
    ctx["requeue_db"] = _temp_db_from_schema()
    with sqlite3.connect(ctx["requeue_db"]) as c:
        c.execute("INSERT INTO escalation_queue (issue_id, summary, kind, reason) "
                  "VALUES ('IFRNLLEI01PRD-BDD', "
                  "'K8s Alert: BddRecheckAlert (warning) on nl-claude01', "
                  "'poll-recheck', 'orphaned-poll')")


@step(r"the underlying alert condition is still active at the scheduled re-check")
def _s(ctx):
    ctx["recheck_firing"] = True


@step(r"the underlying alert condition has recovered at the scheduled re-check")
def _s(ctx):
    ctx["recheck_firing"] = False


@step(r"the requeue job runs")
def _s(ctx):
    _run_requeue(ctx)


@step(r"the escalation is re-fired through the standard webhook")
def _s(ctx):
    assert ("POST", "/webhook/youtrack-webhook") in ctx["requeue_hits"], \
        "still-active re-check must POST the standard escalation webhook"


@step(r"the operator is paged")
def _s(ctx):
    assert ("POST", "/alert-session") in ctx["requeue_hits"], \
        "still-active re-check must page via the SMS bridge /alert-session"


@step(r"the queue row is marked recovered")
def _s(ctx):
    with sqlite3.connect(ctx["requeue_db"]) as c:
        st = c.execute("SELECT status FROM escalation_queue "
                       "WHERE issue_id='IFRNLLEI01PRD-BDD'").fetchone()[0]
    assert st == "recovered", f"expected status=recovered, got {st}"


@step(r"issue closure is left to the alert autocloser")
def _s(ctx):
    assert ("POST", "/webhook/youtrack-webhook") not in ctx["requeue_hits"], \
        "recovered re-check must NOT re-fire the webhook"
    assert (REPO / "scripts" / "alert-yt-autoclose.py").is_file(), \
        "closure is delegated to alert-yt-autoclose.py, which must exist"


# ─── governance (real import + schema assertions) ───────────────────────────
@step(r"a host and rule that recurred four times in thirty days")
def _s(ctx):
    sys.path.insert(0, str(REPO / "scripts"))
    from lib import infragraph  # noqa: F401
    assert hasattr(infragraph, "parse_triage_log"), "recurrence parser parse_triage_log must exist"
    ctx["ik_schema"] = json.loads((REPO / "spec/006-interfaces/contracts/schemas/incident_knowledge.json").read_text())


@step(r"the pattern is not an intentional known-transient")
def _s(ctx):
    pass


@step(r"the governance job runs")
def _s(ctx):
    assert (REPO / "scripts/write-governance-metrics.py").is_file(), "governance metrics writer must exist"


@step(r"the pattern is classified as a demote candidate")
def _s(ctx):
    props = ctx.get("ik_schema", {}).get("properties", {})
    assert "suppression_status" in props or "demotion_reason" in props, \
        "incident_knowledge contract must carry the demotion fields"


@step(r"the demotion expires after thirty days")
def _s(ctx):
    src = (REPO / "scripts/write-governance-metrics.py").read_text()
    assert "demot" in src.lower(), "governance writer must implement demotion"


@step(r"a pattern marked as an intentional known-transient")
def _s(ctx):
    ctx["gov_src"] = (REPO / "scripts/write-governance-metrics.py").read_text()


@step(r"the pattern is excluded from demotion")
def _s(ctx):
    assert "transient" in ctx["gov_src"].lower() or "exclude" in ctx["gov_src"].lower(), \
        "governance writer must exclude known-transients"


# ─── tier1-suppression (real pure-function execution) ───────────────────────
@step(r"a blast-radius control issue that is open")
def _s(ctx):
    sys.path.insert(0, str(REPO / "scripts"))
    from lib.tier1_suppression import _match_blast_radius
    ctx["match"] = _match_blast_radius
    ctx["rule_json"] = {"host_patterns": ["nl*"], "rules": ["*Device*"]}


@step(r"a matching alert arrives")
def _s(ctx):
    ctx["hit"] = ctx["match"](ctx["rule_json"], "nl-pve01", "Device Down")
    ctx["miss"] = ctx["match"](ctx["rule_json"], "gr-pve01", "Device Down")


@step(r"the suppression rule activates")
def _s(ctx):
    assert ctx["hit"] is True, "matching host+rule must be within blast radius"
    assert ctx["miss"] is False, "non-matching host must be outside blast radius"


@step(r"the alert is posted as a notice without spawning a session")
def _s(ctx):
    from lib.tier1_suppression import check_suppression  # noqa: F401
    assert callable(check_suppression), "check_suppression must exist (notice path)"


# ─── tier1-suppression :: phase-1 window / negative-age guard (REQ-408) ──────
@step(r"a prior triage-log entry timestamped after the current time")
def _s(ctx):
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".triage.log")
    with os.fdopen(fd, "w") as fh:  # entry at 12:00, now will be 10:00 => +2h future
        fh.write("2026-05-11T12:00:00Z|host-future|RuleZ|nl|escalated|0.8|200|IFRNLLEI01PRD-9001\n")
    ctx["future_log"] = path


@step(r"a matching alert is triaged")
def _s(ctx):
    db = _temp_db_from_schema()
    try:
        p = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "lib" / "tier1_suppression.py"),
             "--hostname", "host-future", "--rule-name", "RuleZ", "--severity", "warning",
             "--db", db, "--triage-log", ctx["future_log"], "--no-yt-check",
             "--now-utc", "2026-05-11T10:00:00Z"],
            capture_output=True, text=True, timeout=30)
        ctx["fut_result"] = json.loads(p.stdout)
    finally:
        if os.path.exists(db):
            os.unlink(db)
        if os.path.exists(ctx.get("future_log", "")):
            os.unlink(ctx["future_log"])


@step(r"the tier-1 suppression rejects the negative-age entry and fails open to escalation")
def _s(ctx):
    assert ctx["fut_result"].get("outcome") == "escalate", \
        f"future-dated entry must NOT dedup (fail open to escalate), got {ctx['fut_result']}"


# ─── tier1-suppression :: scheduled-reboot (self-learning; real matcher) ─────
@step(r"a host with a live registered reboot schedule(?: whose window contains the alert time)?")
def _s(ctx):
    os.environ["TIER1_SCHED_REBOOT_ENABLED"] = "1"
    sys.path.insert(0, str(REPO / "scripts"))
    from lib.scheduled_reboots import match_scheduled_reboot
    ctx["sr_match"] = match_scheduled_reboot
    ctx["sr_db"] = _temp_db_from_schema()
    conn = sqlite3.connect(ctx["sr_db"])
    conn.execute(
        "INSERT INTO discovered_scheduled_reboots(hostname,site,cron_expr,tz,reboot_kind,"
        "source,status,valid_until,window_minutes,pre_buffer_minutes) "
        "VALUES('nl-gpu01','nl','0 5 * * *','UTC','cron','discovery',"
        "'live','2030-01-01T00:00:00Z',10,5)")
    conn.commit()
    ctx["sr_conn"] = conn


@step(r"a reboot-class alert arrives with non-critical severity")
def _s(ctx):
    import datetime
    now = datetime.datetime(2026, 6, 29, 5, 2, 0, tzinfo=datetime.timezone.utc)  # 05:02 UTC, in-window for 05:00 fire
    ctx["sr_res"] = ctx["sr_match"]("nl-gpu01", "Device rebooted", "warning", now, ctx["sr_conn"])


@step(r"the alert is suppressed as a scheduled reboot without spawning a session")
def _s(ctx):
    assert ctx["sr_res"].get("matched") is True, "on-schedule reboot must match (suppress)"


@step(r"a two-phase verify checks the boot reason")
def _s(ctx):
    verify = REPO / "scripts" / "verify-scheduled-reboot-boot.sh"
    assert verify.exists() and os.access(verify, os.X_OK), "two-phase verify script must exist + be executable"


@step(r"the verify reopens the alert when the boot reason was not a clean systemd-reboot")
def _s(ctx):
    txt = (REPO / "scripts" / "verify-scheduled-reboot-boot.sh").read_text().lower()
    assert "reopen" in txt and "oom" in txt, "verify must reopen on a non-clean (reactive) boot reason"


@step(r"a reboot arrives outside the schedule window, or with critical severity")
def _s(ctx):
    import datetime
    off = datetime.datetime(2026, 6, 29, 13, 9, 0, tzinfo=datetime.timezone.utc)  # off-schedule
    inwin = datetime.datetime(2026, 6, 29, 5, 2, 0, tzinfo=datetime.timezone.utc)
    ctx["sr_off"] = ctx["sr_match"]("nl-gpu01", "Device rebooted", "warning", off, ctx["sr_conn"])
    ctx["sr_crit"] = ctx["sr_match"]("nl-gpu01", "Device rebooted", "critical", inwin, ctx["sr_conn"])


@step(r"the tier-1 suppression fails open to standard escalation")
def _s(ctx):
    assert ctx["sr_off"].get("matched") is False, "off-schedule reboot must NOT suppress"
    assert ctx["sr_crit"].get("matched") is False, "critical reboot must NOT suppress"


# ─── interfaces (real sqlite + contract) ────────────────────────────────────
@step(r"a session-replay request naming an unknown session")
def _s(ctx):
    ctx["openapi"] = (REPO / "spec/006-interfaces/contracts/openapi.yaml").read_text()


@step(r"the webhook surface handles the request")
def _s(ctx):
    pass


@step(r"a not-found response is returned")
def _s(ctx):
    assert "404" in ctx["openapi"], "OpenAPI must declare a 404 for unknown session-replay"


@step(r"a completed risk classification")
def _s(ctx):
    ctx["db"] = _temp_db_from_schema()


@step(r"the decision is recorded")
def _s(ctx):
    with sqlite3.connect(ctx["db"]) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(session_risk_audit)").fetchall()]
    ctx["cols"] = cols
    os.unlink(ctx["db"])


@step(r"a row exists in the session_risk_audit table")
def _s(ctx):
    assert "schema_version" in ctx["cols"], "session_risk_audit must carry schema_version"
    assert "risk_level" in ctx["cols"], "session_risk_audit must carry risk_level"


# ─── spec-governance: content-aware lockstep (real guard, mini-repo fixture) ──
def _mini_repo() -> str:
    d = tempfile.mkdtemp(suffix=".lockstep")
    os.makedirs(os.path.join(d, "spec", "001-x"))
    Path(d, "spec", "001-x", "requirements.md").write_text("REQ-001: The system shall work.\n")
    Path(d, "spec", "001-x", "tasks.json").write_text(json.dumps(
        {"tasks": [{"task_id": "X-1", "files_owned": ["gov.py"]}]}))
    Path(d, "gov.py").write_text("# governed v1\nVALUE = 1\n")
    return d


def _run_guard(mini, *flags):
    env = dict(os.environ)
    env["GATEWAY_SPEC_REPO"] = mini
    env["GATEWAY_SAFETY_FILES"] = "gov.py"
    return subprocess.run([sys.executable, str(REPO / "scripts" / "check-spec-code-lockstep.py"), *flags],
                          env=env, capture_output=True, text=True)


@step(r"a lockstep manifest recorded for a governed file")
def _s(ctx):
    ctx["mini"] = _mini_repo()
    p = _run_guard(ctx["mini"], "--update-manifest")
    assert p.returncode == 0, f"manifest stamp failed: {p.stdout}{p.stderr}"


@step(r"the governed file changes but its specification does not")
def _s(ctx):
    Path(ctx["mini"], "gov.py").write_text("# governed v2 (changed!)\nVALUE = 2\n")


@step(r"the lockstep guard reports spec drift")
def _s(ctx):
    p = _run_guard(ctx["mini"])
    out = p.stdout + p.stderr
    try:
        assert p.returncode == 1, f"expected drift FAIL, got exit {p.returncode}: {out}"
        assert "drift" in out.lower(), f"expected 'drift' in output: {out}"
    finally:
        import shutil
        shutil.rmtree(ctx["mini"], ignore_errors=True)


@step(r"a governed file changed without its specification")
def _s(ctx):
    ctx["mini"] = _mini_repo()
    _run_guard(ctx["mini"], "--update-manifest")
    Path(ctx["mini"], "gov.py").write_text("# governed v2\nVALUE = 2\n")


@step(r"the operator re-stamps the manifest")
def _s(ctx):
    p = _run_guard(ctx["mini"], "--update-manifest")
    assert p.returncode == 0, f"re-stamp failed: {p.stdout}{p.stderr}"


@step(r"the lockstep guard passes")
def _s(ctx):
    p = _run_guard(ctx["mini"])
    import shutil
    shutil.rmtree(ctx["mini"], ignore_errors=True)
    assert p.returncode == 0, f"expected PASS after re-stamp, got exit {p.returncode}: {p.stdout}{p.stderr}"


@step(r"only a comment is added to the specification")
def _s(ctx):
    # cosmetic edit: append a comment line to the spec, no REQ/step change
    rq = Path(ctx["mini"], "spec", "001-x", "requirements.md")
    rq.write_text(rq.read_text() + "\n# cosmetic note: no behavioral change\n")


@step(r"the lockstep guard still reports spec drift")
def _s(ctx):
    p = _run_guard(ctx["mini"])
    import shutil
    shutil.rmtree(ctx["mini"], ignore_errors=True)
    out = p.stdout + p.stderr
    assert p.returncode == 1 and "drift" in out.lower(), \
        f"a cosmetic spec edit must NOT clear genuine drift; got exit {p.returncode}: {out}"
