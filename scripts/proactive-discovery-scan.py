#!/usr/bin/env python3
"""proactive-discovery-scan.py — cc-cc-native SELF-INITIATED discovery (Loop Engineering D1).

Queries Thanos for conditions DEGRADING but not yet alerting ("amber zone") — the paper's
"what's degrading that hasn't alerted yet" — and routes them by REVERSIBILITY, because for
an operator who has structurally left the loop a review post nobody reads is just un-actioned
work + false comfort (see memory loop_engineering_benchmark + the D8/D10 discussion).

Routing (the operator graduates this deliberately via a sentinel):
  • ~/gateway.proactive_remediation ABSENT (default): SURFACE-ONLY — findings go to a weekly
    Matrix digest for review. Nothing auto-acts.
  • ~/gateway.proactive_remediation PRESENT: actionable findings are DISPATCHED into the
    existing cc-cc triage→Runner→autonomy-forward path (run-triage.sh) — which already routes
    REVERSIBLE/bounded/predicted actions to the AUTO band (auto-remediate) and
    IRREVERSIBLE/high-blast-radius ones to POLL_PAUSE + SMS. This script adds NO risk logic;
    the proven gate decides. Kill instantly: `rm ~/gateway.proactive_remediation`.

Dedup via a state file so the same condition is dispatched/surfaced once, not daily.

Usage: proactive-discovery-scan.py [--dry-run] [--force-post]
"""
import json, os, ssl, subprocess, sys, time, urllib.parse, urllib.request


def _load_env(path="~/gitlab/n8n/claude-gateway/.env"):
    """Load KEY=VALUE pairs from .env into os.environ (cron-safe; never overrides existing)."""
    try:
        with open(os.path.expanduser(path)) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


_load_env()

PROM = os.environ.get("PROM_URL", "https://nl-thanos.example.net")
STATE = os.path.expanduser(os.environ.get("PROACTIVE_STATE", "~/gateway.proactive-scan-state.json"))
METRIC_OUT = os.environ.get("PROACTIVE_METRIC", "/var/lib/node_exporter/textfile_collector/proactive_discovery.prom")
RUN_TRIAGE = os.path.expanduser("~/gitlab/n8n/claude-gateway/scripts/run-triage.sh")
REMEDIATION_SENTINEL = os.path.expanduser("~/gateway.proactive_remediation")
NL_ROOM = "!AOMuEtXGyzGFLgObKN:matrix.example.net"
MATRIX_URL = os.environ.get("MATRIX_HOMESERVER", "https://matrix.example.net")
DIGEST_INTERVAL_S = 7 * 86400

DRY_RUN = "--dry-run" in sys.argv
FORCE_POST = "--force-post" in sys.argv
REMEDIATION = os.path.exists(REMEDIATION_SENTINEL)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
try:
    import mutation_mode  # MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824)
except Exception:  # noqa: BLE001
    mutation_mode = None

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def promq(expr):
    url = PROM + "/api/v1/query?query=" + urllib.parse.quote(expr)
    try:
        with urllib.request.urlopen(url, timeout=20, context=_ctx) as r:
            return json.load(r).get("data", {}).get("result", [])
    except Exception as e:
        print(f"[warn] query failed ({expr[:40]}...): {e}", file=sys.stderr)
        return []


def _inst(m):
    return m.get("instance", m.get("namespace", m.get("cluster", "?")))


VPS_PREFIXES = ("notrf01", "chzrh01", "txhou01", "defra01")


def _dispatchable(host):
    """infra-triage can only identify NAMED NL/GR estate hosts. IP-based instances (k8s nodes,
    e.g. 192.168.85.x) and VPS/DMZ hosts aren't identifiable by it, so dispatching them just
    creates thin, un-resolving issues — those stay DIGEST-ONLY (k8s nodes have their own
    alert→k8s-triage path; VPS degradation is surfaced for the operator)."""
    if not host or host[0].isdigit():          # empty or an IP (k8s node etc.)
        return False
    if host.startswith(VPS_PREFIXES):           # out-of-scope VPS/DMZ
        return False
    return host.startswith(("nl", "gr"))


def collect():
    """Run the amber-zone checks. Finding fields: sev, key, text, actionable, host, rule.
    `actionable` findings have a clear bounded remediation target; the rest are informational
    (they'll fire their own path, or need a human) and go to the digest only."""
    out = []

    # 1. Pending alerts — about to fire on the operator's own thresholds. Informational: each
    #    will trigger its OWN triage when it crosses, so we don't double-dispatch here.
    for x in promq('ALERTS{alertstate="pending"}'):
        m = x["metric"]; name = m.get("alertname", "?")
        out.append({"sev": m.get("severity", "warning"), "key": f"pending:{name}:{_inst(m)}",
                    "text": f"about-to-fire: {name} ({_inst(m)})", "actionable": False})

    # 2. Filesystems in the amber band (80–93%). ACTIONABLE — disk pressure has bounded,
    #    usually-reversible remediations (prune images, rotate/clear logs, fstrim, expand).
    fs = ('((node_filesystem_size_bytes-node_filesystem_avail_bytes)/node_filesystem_size_bytes > 0.80) '
          'and ((node_filesystem_size_bytes-node_filesystem_avail_bytes)/node_filesystem_size_bytes < 0.93)')
    for x in promq(fs):
        m = x["metric"]; pct = round(float(x["value"][1]) * 100, 1); mnt = m.get("mountpoint", "")
        host = _inst(m).split(":")[0]
        out.append({"sev": "critical" if pct >= 90 else "warning", "key": f"disk:{_inst(m)}:{mnt}",
                    "text": f"disk {pct}% on {_inst(m)}:{mnt} (approaching full)",
                    "actionable": True, "host": host, "rule": "ProactiveDiskPressure",
                    "dispatch": _dispatchable(host)})

    # 3. Memory pressure amber band (10–18% available). ACTIONABLE — bounded remediations.
    mem = ('(node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes < 0.18) '
           'and (node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes > 0.10)')
    for x in promq(mem):
        m = x["metric"]; pct = round(float(x["value"][1]) * 100, 1)
        host = _inst(m).split(":")[0]
        out.append({"sev": "warning", "key": f"mem:{_inst(m)}",
                    "text": f"memory {pct}% available on {_inst(m)} (pressure building)",
                    "actionable": True, "host": host, "rule": "ProactiveMemoryPressure",
                    "dispatch": _dispatchable(host)})

    # 4. TLS certs expiring within 21 days. Informational (renewal is often host/PKI-specific) —
    #    surfaced in the digest; the human or a renewal job acts.
    cert = '(probe_ssl_earliest_cert_expiry - time() < 21*86400) and (probe_ssl_earliest_cert_expiry - time() > 0)'
    for x in promq(cert):
        m = x["metric"]; days = round(float(x["value"][1]) / 86400, 1); tgt = m.get("instance", m.get("target", "?"))
        out.append({"sev": "critical" if days < 7 else "warning", "key": f"cert:{tgt}",
                    "text": f"TLS cert expires in {days}d: {tgt}", "actionable": False})

    # de-dup identical keys (Thanos returns per-cluster dupes), keep highest severity
    by_key, rank = {}, {"critical": 2, "warning": 1}
    for f in out:
        k = f["key"]
        if k not in by_key or rank.get(f["sev"], 0) > rank.get(by_key[k]["sev"], 0):
            by_key[k] = f
    return list(by_key.values())


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"keys": [], "last_digest_ts": 0}


def save_state(state):
    try:
        with open(STATE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"[warn] state write failed: {e}", file=sys.stderr)


def dispatch_remediation(f):
    """Hand an actionable finding to the EXISTING cc-cc triage→Runner→autonomy-forward path.
    Background (non-blocking); the gate routes reversible→AUTO, irreversible→POLL_PAUSE+SMS."""
    host, rule, sev = f.get("host"), f.get("rule", "ProactiveDiscovery"), f.get("sev", "warning")
    if not host:
        return False
    logf = os.path.expanduser(f"~/logs/claude-gateway/proactive-dispatch.log")
    try:
        os.makedirs(os.path.dirname(logf), exist_ok=True)
        with open(logf, "a") as lg:
            lg.write(f"[{time.strftime('%FT%TZ', time.gmtime())}] dispatch infra {host} {rule} {sev}\n")
            subprocess.Popen(["bash", RUN_TRIAGE, "infra", host, rule, sev],
                             stdout=lg, stderr=lg, stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception as e:
        print(f"[warn] dispatch failed for {host}: {e}", file=sys.stderr)
        return False


def post_digest(findings, new, dispatched):
    tok = os.environ.get("MATRIX_CLAUDE_TOKEN", "")
    if not tok:
        try:
            tok = open(os.path.expanduser("~/.matrix-claude-token")).read().strip()
        except Exception:
            tok = ""
    if not tok:
        print("[warn] no Matrix token — cannot post digest", file=sys.stderr)
        return False
    room = os.environ.get("MATRIX_ROOM_INFRA", NL_ROOM)
    crit = sum(1 for f in findings if f["sev"] == "critical")
    mode = "auto-remediating reversible / SMS-gating irreversible" if REMEDIATION else "surface-only (remediation OFF)"
    lines = [f"🔭 Weekly proactive-discovery digest — {len(findings)} pre-alert condition(s) "
             f"({crit} critical), {len(new)} new. Mode: {mode}."]
    for f in findings:
        flags = []
        if f in new: flags.append("NEW")
        if f in dispatched: flags.append("→dispatched")
        elif f.get("actionable") and not f.get("dispatch"): flags.append("digest-only (k8s/VPS — own path)")
        elif f.get("actionable") and not REMEDIATION: flags.append("actionable (remediation OFF)")
        suffix = (" [" + ", ".join(flags) + "]") if flags else ""
        lines.append(f"• [{f['sev']}] {f['text']}{suffix}")
    if dispatched:
        lines.append(f"— {len(dispatched)} dispatched to the autonomy-forward gate (it decides auto vs SMS).")
    lines.append("— enable/kill auto-remediation: touch/rm ~/gateway.proactive_remediation")
    txn = f"proactive-digest-{int(time.time())}"
    payload = json.dumps({"msgtype": "m.notice", "body": "\n".join(lines)}).encode()
    url = f"{MATRIX_URL}/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/send/m.room.message/{txn}"
    req = urllib.request.Request(url, data=payload, method="PUT",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15, context=_ctx)
        return True
    except Exception as e:
        print(f"[warn] digest post failed: {e}", file=sys.stderr)
        return False


def write_metric(findings, dispatched_n):
    crit = sum(1 for f in findings if f["sev"] == "critical")
    lines = [
        "# HELP proactive_discovery_findings Pre-alert (amber-zone) conditions surfaced by the discovery scan.",
        "# TYPE proactive_discovery_findings gauge",
        f'proactive_discovery_findings{{severity="critical"}} {crit}',
        f'proactive_discovery_findings{{severity="warning"}} {len(findings)-crit}',
        "# HELP proactive_discovery_dispatched Findings dispatched to the autonomy-forward path this run.",
        "# TYPE proactive_discovery_dispatched gauge",
        f"proactive_discovery_dispatched {dispatched_n}",
        "# HELP proactive_discovery_remediation_enabled 1 if the proactive_remediation sentinel is present.",
        "# TYPE proactive_discovery_remediation_enabled gauge",
        f"proactive_discovery_remediation_enabled {1 if REMEDIATION else 0}",
        "# HELP proactive_discovery_last_run_timestamp_seconds Unix time of last discovery scan.",
        "# TYPE proactive_discovery_last_run_timestamp_seconds gauge",
        f"proactive_discovery_last_run_timestamp_seconds {int(time.time())}",
        "",
    ]
    try:
        os.makedirs(os.path.dirname(METRIC_OUT), exist_ok=True)
        with open(METRIC_OUT, "w") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[warn] metric write failed: {e}", file=sys.stderr)


def main():
    findings = collect()
    findings.sort(key=lambda f: (f["sev"] != "critical", f["key"]))
    cur_keys = sorted(f["key"] for f in findings)
    state = load_state()
    seen = set(state.get("keys", []))
    new = [f for f in findings if f["key"] not in seen]

    print(f"=== Proactive Discovery Scan {time.strftime('%FT%TZ', time.gmtime())} ===")
    print(f"  findings={len(findings)} new={len(new)} "
          f"remediation={'ON' if REMEDIATION else 'OFF (surface-only)'} (Thanos: {PROM})")
    for f in findings:
        tags = (" *NEW*" if f in new else "") + (" [actionable]" if f.get("actionable") else "")
        print(f"  [{f['sev']}] {f['text']}{tags}")

    # 1. Dispatch actionable NEW findings into the autonomy-forward path (reversible→AUTO, irreversible→SMS).
    dispatched = []
    for f in new:
        if not f.get("dispatch"):  # actionable-but-not-infra-triageable (k8s/VPS) stays digest-only
            continue
        if mutation_mode and mutation_mode.is_shadow():
            mutation_mode.log_wouldve("proactive-dispatch", rationale="would dispatch a remediation session",
                                      host=f.get("host"), rule=f.get("rule"), sev=f.get("sev"))
            print(f"  → SHADOW (MUTATIONS=OFF): would dispatch {f.get('host')} {f.get('rule')} — logged, not run")
        elif REMEDIATION and not DRY_RUN:
            if dispatch_remediation(f):
                dispatched.append(f)
                print(f"  → dispatched: infra {f['host']} {f['rule']} {f['sev']} (gate decides auto/SMS)")
        else:
            why = "dry-run" if DRY_RUN else "remediation OFF — touch ~/gateway.proactive_remediation to enable"
            print(f"  → WOULD dispatch: infra {f.get('host')} {f.get('rule')} [{why}]")

    if DRY_RUN:
        print("  (--dry-run: no dispatch, no post, no state write)")
        return

    write_metric(findings, len(dispatched))

    # 2. Weekly digest (the realistic D10 — a periodic sample the operator will read, not daily spam).
    digest_due = bool(findings) and (FORCE_POST or (time.time() - state.get("last_digest_ts", 0) > DIGEST_INTERVAL_S))
    digest_ok = True
    if digest_due:
        digest_ok = post_digest(findings, new, dispatched)
        print(f"  weekly digest posted ({len(new)} new, {len(dispatched)} dispatched)"
              if digest_ok else "  digest post FAILED")
    else:
        print("  digest not due (weekly) — silent")

    # State: dispatch-dedup keys advance every run (the act/surface decision was made);
    # last_digest_ts only on a successful digest. A failed dispatch finding stays "new" only
    # if dispatch itself raised — handled inside dispatch_remediation (returns False, not added).
    state["keys"] = cur_keys
    if digest_due and digest_ok:
        state["last_digest_ts"] = int(time.time())
    save_state(state)


if __name__ == "__main__":
    main()
