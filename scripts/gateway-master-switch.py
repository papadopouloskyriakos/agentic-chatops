#!/usr/bin/env python3
"""
gateway-master-switch.py — master power switch for the complete agentic system (IFRNLLEI01PRD-1823).

One switch on the orchestrator (nl-claude01) that powers the agentic platform OFF and back ON,
with a tamper-evident transition log. "Off" means NO autonomous behavior: no alert processing, no
session dispatch, no autonomous actuation of any kind. The platform SKELETON stays alive by design —
Cronicle scheduler, metric exporters, the watchdog heartbeat, and the tier-1 SMS dead-man channel
keep running so the off state is observable and a genuine host failure during the window still pages.

    gateway-master-switch.py status [--json] [--emit-metrics]
    gateway-master-switch.py off  --reason "why" [--operator who] [--hard] [--kill-sessions]
                                  [--dry-run] [--force]
    gateway-master-switch.py on   [--operator who] [--dry-run] [--force]
    gateway-master-switch.py log  [--n 10]

What OFF does (soft, default):
  1. Snapshot current armed state → ~/gateway-state/master-switch/snapshot-current.json (+ archive).
  2. Create ~/gateway.maintenance with a {"master_switch": true} marker → all maintenance-aware
     consumers suppress (8 alert receivers, chaos drills, network self-healers, watchdog checks,
     platform-controller heals, gated metric writers). A PRE-EXISTING operator maintenance file is
     preserved untouched and ownership is recorded.
  3. Remove the 14 autonomy-ARMING sentinels (autonomy_forward, platform_controller_armed, ...).
     Guard sentinels (plan_adherence_*, territory_gate, silent_cognition_guard) are NEVER touched —
     power-off must tighten, not loosen. Inverted kill-switches (gateway.tripwire_off, ...) are
     NEVER created.
  4. Disable the 9 UNGATED Cronicle actuation jobs that would otherwise keep acting (the
     2026-07-17 actuation audit: requeue-escalations, reconcile-completed-sessions.py,
     gateway-regen-artifacts-weekly, infragraph-propose-blast-radius.py, ap01-pending-mac-block,
     crowdsec-learn.sh, finalize-prompt-trials.py, scheduled-reboot-promote,
     renovate-autonomy-promote).
  5. --hard additionally deactivates the dispatch-lane n8n workflows (YouTrack Receiver, Runner,
     Matrix Bridge, Progress Poller, Session End, CI Failure Receiver, ChatDevOps CI Resume,
     Synology DSM Receiver, Teacher Runner) so even human-triggered dispatch is impossible.
     NOTE: with --hard, RegistryCriticalDark (tier-1 SMS) is EXPECTED after ~15-20 min — the
     dead-man deliberately acknowledges that the critical plane is dark.
  6. --kill-sessions TERMs in-flight dispatched claude sessions (/tmp/claude-pid-*).

What ON does: exact restore FROM THE SNAPSHOT — only the sentinels that existed, the Cronicle jobs
we disabled, the n8n workflows we deactivated. Removes the maintenance file only if the master
switch created it, and writes ~/gateway.maintenance-ended (epoch) so the 15-minute post-maintenance
cooldown engages (this also closes the long-standing AWX-clear gap).

Every transition is logged 4 ways: hash-chained master_switch_log table (migration 028, verified on
every status run), append-only JSONL at ~/logs/claude-gateway/master-switch.log, the
master_switch.prom textfile gauge set, and a Matrix m.notice to #infra-nl-prod.

Env overrides (hermetic QA): GATEWAY_HOME, MASTER_SWITCH_DB (or GATEWAY_DB), MASTER_SWITCH_STATE_DIR,
MASTER_SWITCH_LOG, MASTER_SWITCH_PROM, MASTER_SWITCH_SKIP_CRONICLE=1, MASTER_SWITCH_SKIP_N8N=1,
MASTER_SWITCH_SKIP_MATRIX=1, MASTER_SWITCH_ENV_FILE (.env path for Cronicle/Matrix creds),
MASTER_SWITCH_CLAUDE_JSON (n8n key source), MASTER_SWITCH_PID_GLOB (session pid files).
"""
import argparse
import fcntl
import json
import os
REDACTED_a7b84d63
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import ssl
from glob import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import master_switch_audit  # noqa: E402
try:
    import cronicle as cronicle_lib  # noqa: E402
except Exception:  # pragma: no cover - import failure is treated as a plane FAILURE, not a skip
    cronicle_lib = None

# ── Classification (source: 2026-07-17 sentinel-classification audit, IFRNLLEI01PRD-1823) ──────────
# Presence ARMS autonomous actuation. Master-off removes these; master-on restores the snapshot.
ARMING_SENTINELS = [
    "gateway.alert_yt_autoclose_armed",
    "gateway.autoclose_toverify_readonly",
    "gateway.autonomy_forward",
    "gateway.conservative_remediation",
    "gateway.cronicle_autoquarantine",
    "gateway.disk_autogrow_armed",
    "gateway.host_reboot_auto",
    "gateway.infragraph_autofold",
    "gateway.judge_autocalibrate_armed",
    "gateway.platform_controller_armed",
    "gateway.proactive_remediation",
    "gateway.renovate_autonomy",
    "gateway.renovate_timeout_auto",
    "gateway.sched_reboot",
]
# Presence RESTRICTS the system. NEVER touched; asserted still present after off.
GUARD_SENTINELS = [
    "gateway.plan_adherence_enforce",
    "gateway.plan_adherence_gate",
    "gateway.silent_cognition_guard",
    "gateway.territory_gate",
    # MUTATIONS=OFF shadow mode (IFRNLLEI01PRD-1824): presence = the autonomous system logs intended
    # actuations but never executes them = the tightest restriction. A guard, not an arming switch —
    # a master power-OFF must PRESERVE it (tighten, not loosen), and power-ON must not silently clear it.
    "gateway.mutations_off",
]
# Inverted semantics: presence would DISABLE a guard. NEVER created by this tool.
NEVER_CREATE = ["gateway.tripwire_off", "gateway.prompt_promotion_holdout_gate_off"]
# Data/state files that look like sentinels but are not switches. NEVER touched.
DATA_FILES = [
    "gateway.db", "gateway.mode", "gateway.foldgate-verified",
    "gateway.proactive-scan-state.json", "gateway.maintenance", "gateway.maintenance-ended",
]

# Ungated Cronicle actuation jobs (2026-07-17 actuation audit) — resolved by TITLE at runtime.
CRONICLE_DISABLE_TITLES = [
    "requeue-escalations",
    "reconcile-completed-sessions.py",
    "gateway-regen-artifacts-weekly",
    "infragraph-propose-blast-radius.py",
    "ap01-pending-mac-block",
    "crowdsec-learn.sh",
    "finalize-prompt-trials.py",
    "scheduled-reboot-promote",
    "renovate-autonomy-promote",
]

# Dispatch-lane n8n workflows deactivated by --hard — resolved by NAME at runtime.
N8N_HARD_WORKFLOW_NAMES = [
    "NL - Claude Gateway YouTrack Receiver",
    "NL - Claude Gateway Runner",
    "NL - Claude Gateway Matrix Bridge",
    "NL - Claude Gateway Progress Poller",
    "NL - Claude Gateway Session End",
    "NL - CI Failure Receiver",
    "NL - ChatDevOps CI Resume",
    "NL - Synology DSM Alert Receiver",
    "NL - Teacher Runner",
]

N8N_URL = os.environ.get("MASTER_SWITCH_N8N_URL", "https://n8n.example.net")
MATRIX_HS = os.environ.get("MATRIX_HOMESERVER", "https://matrix.example.net")
MATRIX_ROOM = os.environ.get("MATRIX_ROOM_INFRA", "!AOMuEtXGyzGFLgObKN:matrix.example.net")


def _home() -> Path:
    return Path(os.environ.get("GATEWAY_HOME", str(Path.home())))


def _db() -> str:
    return os.environ.get("MASTER_SWITCH_DB",
                          os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db"))


def _state_dir() -> Path:
    d = Path(os.environ.get("MASTER_SWITCH_STATE_DIR", str(_home() / "gateway-state" / "master-switch")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _jsonl_log() -> Path:
    p = Path(os.environ.get("MASTER_SWITCH_LOG",
                            str(_home() / "logs" / "claude-gateway" / "master-switch.log")))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _prom_path() -> str:
    return os.environ.get("MASTER_SWITCH_PROM",
                          "/var/lib/node_exporter/textfile_collector/master_switch.prom")


def _env_file() -> str:
    return os.environ.get("MASTER_SWITCH_ENV_FILE",
                          "/app/claude-gateway/.env")


def _read_env_var(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    try:
        with open(_env_file()) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{name}=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _skip(plane: str) -> bool:
    return os.environ.get(f"MASTER_SWITCH_SKIP_{plane}", "0") == "1"


# ── Sentinel plane ──────────────────────────────────────────────────────────────────────────────


def sentinels_present() -> list:
    return [s for s in ARMING_SENTINELS if (_home() / s).exists()]


def guards_present() -> list:
    return [g for g in GUARD_SENTINELS if (_home() / g).exists()]


def unknown_gateway_files() -> list:
    known = set(ARMING_SENTINELS + GUARD_SENTINELS + NEVER_CREATE + DATA_FILES)
    out = []
    for p in _home().glob("gateway.*"):
        if p.name not in known:
            out.append(p.name)
    return sorted(out)


# ── Maintenance plane ───────────────────────────────────────────────────────────────────────────


def maintenance_state() -> dict:
    """{'exists': bool, 'ours': bool, 'content': str}"""
    p = _home() / "gateway.maintenance"
    if not p.exists():
        return {"exists": False, "ours": False, "content": ""}
    try:
        content = p.read_text()
    except OSError:
        content = ""
    ours = False
    try:
        ours = bool(json.loads(content).get("master_switch"))
    except (ValueError, AttributeError):
        pass
    return {"exists": True, "ours": ours, "content": content}


def create_maintenance(reason: str, operator: str) -> str:
    """Returns 'created' | 'preexisting'."""
    st = maintenance_state()
    if st["exists"]:
        return "preexisting"
    payload = {
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reason": f"master-switch: {reason}",
        "eta_minutes": 0,
        "operator": operator,
        "master_switch": True,
    }
    (_home() / "gateway.maintenance").write_text(json.dumps(payload) + "\n")
    return "created"


def remove_maintenance_if_ours() -> str:
    """Returns 'removed' | 'kept-foreign' | 'absent'. Writes the cooldown marker on removal."""
    st = maintenance_state()
    if not st["exists"]:
        return "absent"
    if not st["ours"]:
        return "kept-foreign"
    (_home() / "gateway.maintenance").unlink()
    # Engage the 15-min post-maintenance cooldown (closes the AWX-clear gap: only
    # asa-reboot-watch.sh used to write this marker).
    (_home() / "gateway.maintenance-ended").write_text(str(int(time.time())) + "\n")
    return "removed"


# ── Cronicle plane ──────────────────────────────────────────────────────────────────────────────


def cronicle_targets() -> list:
    """[{'id','title','enabled'}] for the disable list, resolved from the live schedule.

    An explicit QA skip returns [] (plane intentionally not exercised). A LIVE import failure
    (cronicle_lib is None without the skip env) is NOT a skip — it returns the 9 titles as
    missing targets so cmd_off attempts and fails them → partial, never a silent clean off."""
    if _skip("CRONICLE"):
        return []
    if cronicle_lib is None:
        return [{"id": None, "title": t, "enabled": None, "missing": True,
                 "plane_error": "cronicle-import-failed"} for t in CRONICLE_DISABLE_TITLES]
    rows = cronicle_lib.schedule()
    by_title = {r.get("title", ""): r for r in rows}
    out = []
    for title in CRONICLE_DISABLE_TITLES:
        r = by_title.get(title)
        if r is None:
            out.append({"id": None, "title": title, "enabled": None, "missing": True})
        else:
            out.append({"id": r.get("id"), "title": title, "enabled": int(r.get("enabled", 0))})
    return out


def cronicle_set(targets: list, enabled: int) -> list:
    """set_enabled on each target id; returns results with ok flags.

    cronicle_lib.set_enabled returns the Cronicle API CODE — 0 = success, non-zero/-1 = failure.
    (A naive bool() would invert this: 0 is falsy.) login() returns '' on failure; an empty
    session makes every update fail, so we short-circuit and mark all targets failed."""
    results = []
    if not targets:
        return results
    if _skip("CRONICLE") or cronicle_lib is None:
        return [{**t, "ok": False, "error": "cronicle-plane-unavailable"} for t in targets]
    session_id = cronicle_lib.login()
    if not session_id:
        return [{**t, "ok": False, "error": "cronicle-login-failed"} for t in targets]
    for t in targets:
        if not t.get("id"):
            results.append({**t, "ok": False, "error": "not-found-in-schedule"})
            continue
        code = cronicle_lib.set_enabled(t["id"], enabled, session_id)
        results.append({**t, "ok": code == 0, "api_code": code})
    return results


# ── n8n plane ───────────────────────────────────────────────────────────────────────────────────


def _n8n_key() -> str:
    src = os.environ.get("MASTER_SWITCH_CLAUDE_JSON", "/home/app-user/.claude.json")
    try:
        with open(src) as f:
            return json.load(f)["mcpServers"]["n8n-mcp"]["env"]["N8N_API_KEY"]
    except (OSError, KeyError, ValueError):
        return ""


def _n8n_api(path: str, method: str = "GET"):
    key = _n8n_key()
    if not key:
        raise RuntimeError("n8n API key unavailable (~/.claude.json n8n-mcp env)")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(f"{N8N_URL}/api/v1/{path}", method=method,
                                 headers={"X-N8N-API-KEY": key})
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        return json.loads(resp.read().decode())


def n8n_targets() -> list:
    """[{'id','name','active'}] for the hard list."""
    if _skip("N8N"):
        return []
    data = _n8n_api("workflows?limit=100")
    by_name = {w["name"]: w for w in data.get("data", [])}
    out = []
    for name in N8N_HARD_WORKFLOW_NAMES:
        w = by_name.get(name)
        if w is None:
            out.append({"id": None, "name": name, "active": None, "missing": True})
        else:
            out.append({"id": w["id"], "name": name, "active": bool(w["active"])})
    return out


def n8n_set(targets: list, activate: bool) -> list:
    results = []
    if _skip("N8N"):
        return results
    verb = "activate" if activate else "deactivate"
    for t in targets:
        if not t.get("id"):
            results.append({**t, "ok": False, "error": "not-found"})
            continue
        try:
            resp = _n8n_api(f"workflows/{t['id']}/{verb}", method="POST")
            want = activate
            got = bool(resp.get("active", not want) is want) or bool(resp.get("active") == want)
            results.append({**t, "ok": got})
        except Exception as e:  # noqa: BLE001 - collect per-workflow failures, report partial
            results.append({**t, "ok": False, "error": str(e)[:200]})
    return results


# ── Sessions plane ──────────────────────────────────────────────────────────────────────────────


def active_sessions() -> list:
    pid_glob = os.environ.get("MASTER_SWITCH_PID_GLOB", "/tmp/claude-pid-*")
    out = []
    for f in glob(pid_glob):
        issue = re.sub(r"^.*claude-pid-", "", f)
        try:
            pid = int(Path(f).read_text().strip())
        except (OSError, ValueError):
            continue
        try:
            os.kill(pid, 0)
            out.append({"issue": issue, "pid": pid})
        except (ProcessLookupError, PermissionError):
            continue
    return out


def kill_sessions(sessions: list) -> list:
    results = []
    for s in sessions:
        try:
            os.kill(s["pid"], signal.SIGTERM)
            results.append({**s, "killed": True})
        except (ProcessLookupError, PermissionError) as e:
            results.append({**s, "killed": False, "error": str(e)})
    return results


# ── Logging planes ──────────────────────────────────────────────────────────────────────────────


def write_jsonl(entry: dict):
    with open(_jsonl_log(), "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def write_prom(state_on: int, partial: int):
    path = _prom_path()
    try:
        ok, _first, rows = master_switch_audit.verify(_db())
    except Exception:  # noqa: BLE001 - metric write must not die on a DB hiccup
        ok, rows = False, -1  # an unreadable ledger is NOT a healthy chain; never publish intact=1
    now = int(time.time())
    lines = [
        "# HELP gateway_master_switch_state 1 = agentic system ON (normal), 0 = master power-off active (IFRNLLEI01PRD-1823).",
        "# TYPE gateway_master_switch_state gauge",
        f"gateway_master_switch_state {state_on}",
        "# HELP gateway_master_switch_transitions_total Rows in the hash-chained master_switch_log ledger.",
        "# TYPE gateway_master_switch_transitions_total gauge",
        f"gateway_master_switch_transitions_total {rows}",
        "# HELP gateway_master_switch_chain_intact 1 if the master_switch_log hash chain verifies, 0 if tampered/broken.",
        "# TYPE gateway_master_switch_chain_intact gauge",
        f"gateway_master_switch_chain_intact {1 if ok else 0}",
        "# HELP gateway_master_switch_partial_last 1 if the most recent transition completed only partially.",
        "# TYPE gateway_master_switch_partial_last gauge",
        f"gateway_master_switch_partial_last {partial}",
        "# HELP gateway_master_switch_last_run_timestamp_seconds Unix ts of the last master-switch metric emit.",
        "# TYPE gateway_master_switch_last_run_timestamp_seconds gauge",
        f"gateway_master_switch_last_run_timestamp_seconds {now}",
    ]
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o644)  # node_exporter runs non-root; 0600 = silently absent metric
        os.replace(tmp, path)
    except OSError as e:
        print(f"WARN: prom write failed: {e}", file=sys.stderr)


def post_matrix(text: str):
    if _skip("MATRIX"):
        return
    tok = _read_env_var("MATRIX_CLAUDE_TOKEN") or _read_env_var("MATRIX_ACCESS_TOKEN")
    if not tok:
        print("WARN: no Matrix token; skipping notice", file=sys.stderr)
        return
    txn = f"msw{int(time.time() * 1000)}"
    body = json.dumps({"msgtype": "m.notice", "body": text}).encode()
    req = urllib.request.Request(
        f"{MATRIX_HS}/_matrix/client/v3/rooms/{MATRIX_ROOM}/send/m.room.message/{txn}",
        data=body, method="PUT",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # noqa: BLE001 - Matrix down must never fail the switch
        print(f"WARN: Matrix notice failed: {e}", file=sys.stderr)


def record_transition(action, mode, operator, reason, sentinels, cronicle, n8n, sessions,
                      maintenance_action, partial, details):
    entry = {
        "ts": int(time.time()),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action, "mode": mode, "operator": operator, "reason": reason,
        "hostname": socket.gethostname(),
        "sentinels": sentinels, "cronicle": cronicle, "n8n": n8n, "sessions": sessions,
        "maintenance_action": maintenance_action, "partial": partial, "details": details,
    }
    write_jsonl(entry)
    try:
        rowid, row_hash = master_switch_audit.append(_db(), {
            "ts": entry["ts"], "action": action, "mode": mode, "operator": operator,
            "reason": reason, "hostname": entry["hostname"],
            "sentinels_json": json.dumps(sentinels, sort_keys=True),
            "cronicle_json": json.dumps(cronicle, sort_keys=True),
            "n8n_json": json.dumps(n8n, sort_keys=True),
            "sessions_json": json.dumps(sessions, sort_keys=True),
            "maintenance_action": maintenance_action, "partial": 1 if partial else 0,
            "details_json": json.dumps(details, sort_keys=True),
        })
        entry["ledger"] = {"id": rowid, "row_hash": row_hash}
    except Exception as e:  # noqa: BLE001 - JSONL already durable; report but continue
        print(f"WARN: ledger append failed: {e}", file=sys.stderr)
    # State gauge reflects the ACTUAL recorded state (a partial 'on' keeps the snapshot 'off'),
    # not the intended action — record_transition runs after the snapshot is saved.
    write_prom(1 if current_state() == "on" else 0, 1 if partial else 0)
    icon = "\U0001F534" if action == "off" else "\U0001F7E2"
    partial_txt = " [PARTIAL — check status]" if partial else ""
    post_matrix(f"{icon} MASTER SWITCH: agentic system powered {action.upper()} "
                f"({mode}) by {operator} — {reason}{partial_txt} "
                f"[gateway-master-switch.py on {entry['hostname']}]")
    return entry


# ── Snapshot / state ────────────────────────────────────────────────────────────────────────────


def snapshot_path() -> Path:
    return _state_dir() / "snapshot-current.json"


def load_snapshot() -> dict:
    try:
        return json.loads(snapshot_path().read_text())
    except (OSError, ValueError):
        return {}


def save_snapshot(snap: dict):
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive = _state_dir() / f"snapshot-{ts}.json"
    data = json.dumps(snap, indent=2, sort_keys=True)
    archive.write_text(data)
    snapshot_path().write_text(data)


def current_state() -> str:
    """'on' | 'off' derived from the last snapshot action (default 'on')."""
    snap = load_snapshot()
    return "off" if snap.get("action") == "off" else "on"


# ── Commands ────────────────────────────────────────────────────────────────────────────────────


def cmd_off(args) -> int:
    prev = load_snapshot()
    snap_corrupt = snapshot_path().exists() and not prev
    maint = maintenance_state()
    # "effectively off" if the snapshot says so OR our own maintenance marker is present. The
    # maintenance-marker fallback covers a lost/corrupt snapshot mid-off, so the restore baseline
    # is preserved (union) rather than re-captured empty from the already-stripped world.
    prev_off = (prev.get("action") == "off") or maint["ours"]

    if snap_corrupt and not args.force:
        print("Snapshot file exists but is unparseable — refusing to overwrite the restore "
              "baseline. Inspect ~/gateway-state/master-switch/ archives, or pass --force.",
              file=sys.stderr)
        return 2
    if prev_off and not args.force:
        print("Already OFF (snapshot / master_switch maintenance marker indicate an off is in "
              "effect). Use --force to re-run the off sequence (e.g. after a partial off).")
        return 1

    plan_guards = guards_present()
    plan_cronicle = cronicle_targets()
    plan_sessions = active_sessions()

    # Restore-contract preservation: on a --force RE-off the arming set / enabled jobs / active
    # workflows have already been stripped, so re-reading the live world would record an EMPTY
    # baseline. Instead UNION the original baseline with whatever is still armed now — the
    # snapshot never shrinks across re-offs.
    cur_sentinels = sentinels_present()
    base_sentinels = sorted(set(prev.get("sentinels_present", []) if prev_off else []) | set(cur_sentinels))
    cur_cron_enabled = [t for t in plan_cronicle if t.get("enabled") == 1]

    def _union_by(key, prior, current):
        out = {x[key]: x for x in (prior if prev_off else [])}
        for x in current:
            out[x[key]] = x
        return list(out.values())

    base_cronicle = _union_by("title", prev.get("cronicle_enabled", []), cur_cron_enabled)
    # base_hard is sticky: a --force re-off of a prior --hard off stays hard even without repeating
    # the flag, so dispatch workflows manually re-activated during the window are re-deactivated.
    base_hard = bool(args.hard) or (prev_off and bool(prev.get("hard")))
    plan_n8n = n8n_targets() if base_hard else []
    cur_n8n_active = [t for t in plan_n8n if t.get("active")]
    base_n8n = _union_by("name", prev.get("n8n_active", []), cur_n8n_active)
    base_maint_pre = prev.get("maintenance_preexisting") if prev_off else maint["exists"]

    print(f"PLAN off ({'hard' if base_hard else 'soft'}"
          f"{', --force re-off (baseline preserved)' if prev_off else ''}):")
    print(f"  maintenance file : {'preexisting (left untouched)' if maint['exists'] else 'will create (master_switch marker)'}")
    print(f"  remove sentinels : {len(cur_sentinels)} now -> {cur_sentinels}  (restore baseline: {base_sentinels})")
    print(f"  keep guards      : {plan_guards}")
    print(f"  disable cronicle : {[t['title'] for t in plan_cronicle if t.get('enabled') != 0]}")
    if base_hard:
        print(f"  deactivate n8n   : {[t['name'] for t in cur_n8n_active]}")
    print(f"  active sessions  : {plan_sessions} "
          f"({'will TERM' if args.kill_sessions else 'left running (use --kill-sessions)'})")
    unknown = unknown_gateway_files()
    if unknown:
        print(f"  WARN unknown gateway.* files (unmanaged): {unknown}")
    if args.dry_run:
        print("DRY-RUN: no changes made.")
        return 0

    # Snapshot BEFORE mutating — this is the restore contract (baseline = union, never shrinks).
    snap = {
        "action": "off",
        "ts": int(time.time()),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operator": args.operator,
        "reason": args.reason,
        "hard": base_hard,
        "maintenance_preexisting": base_maint_pre,
        "sentinels_present": base_sentinels,
        "cronicle_enabled": base_cronicle,
        "n8n_active": base_n8n,
        "sessions_at_off": plan_sessions,
        "partial": False,
    }
    save_snapshot(snap)

    partial = False
    details = {}

    maintenance_action = create_maintenance(args.reason, args.operator)
    if maintenance_action == "preexisting" and not maint["ours"]:
        print("  WARN: a foreign (operator/AWX) maintenance file is already present — OFF's "
              "alert suppression is borrowed from it and will NOT be cleaned up by 'on'.",
              file=sys.stderr)
        details["maintenance_foreign"] = True

    # Remove only the arming sentinels present NOW (idempotent on a re-off).
    removed, remove_failed = [], []
    for s in cur_sentinels:
        try:
            (_home() / s).unlink()
            removed.append(s)
        except OSError as e:
            remove_failed.append({"sentinel": s, "error": str(e)})
            partial = True

    # Disable every job not already confirmed-disabled (enabled != 0). A missing/None target
    # (schedule() unreachable) is attempted and comes back not-found -> partial, so a Cronicle
    # outage can never masquerade as a clean off.
    cron_to_disable = [t for t in plan_cronicle if t.get("enabled") != 0]
    cron_results = cronicle_set(cron_to_disable, 0)
    if any(not r.get("ok") for r in cron_results):
        partial = True
        details["cronicle_failures"] = [r for r in cron_results if not r.get("ok")]

    n8n_results = []
    if args.hard:
        n8n_results = n8n_set(cur_n8n_active, activate=False)
        if any(not r.get("ok") for r in n8n_results):
            partial = True

    killed = []
    if args.kill_sessions and plan_sessions:
        killed = kill_sessions(plan_sessions)
        if any(not k.get("killed") for k in killed):
            partial = True

    # Post-verify.
    still_present = sentinels_present()
    guards_after = guards_present()
    if still_present:
        partial = True
        details["sentinels_still_present"] = still_present
    if set(guards_after) != set(plan_guards):
        partial = True
        details["GUARDS_CHANGED"] = {"before": plan_guards, "after": guards_after}
    if remove_failed:
        details["remove_failed"] = remove_failed

    # Re-save the snapshot with the observed partial flag (baseline fields unchanged) so status
    # --emit-metrics and the next transition see the true completion state.
    snap["partial"] = partial
    save_snapshot(snap)

    entry = record_transition(
        "off", "hard" if base_hard else "soft", args.operator, args.reason,
        {"removed": removed, "failed": remove_failed, "guards_kept": guards_after,
         "restore_baseline": base_sentinels},
        cron_results, n8n_results, {"active_at_off": plan_sessions, "killed": killed},
        maintenance_action, partial, details)

    print(json.dumps(entry, indent=2))
    if partial:
        print("PARTIAL OFF — some steps failed; fix the cause then re-run 'off --force' "
              "(the original restore baseline is preserved), or check 'status'.", file=sys.stderr)
        return 3
    print("Agentic system powered OFF.")
    return 0


def cmd_on(args) -> int:
    snap = load_snapshot()
    if not snap:
        print("No snapshot found — refusing to power on blind. "
              "Restore sentinels manually or create a snapshot.", file=sys.stderr)
        return 2
    if snap.get("action") != "off" and not args.force:
        print("Already ON (snapshot says the last transition was 'on'). Use --force to re-run.")
        return 1

    plan_sentinels = snap.get("sentinels_present", [])
    plan_cronicle = snap.get("cronicle_enabled", [])
    plan_n8n = snap.get("n8n_active", [])
    print("PLAN on (restore from snapshot "
          f"{snap.get('iso')} by {snap.get('operator')}):")
    print(f"  restore sentinels: {plan_sentinels}")
    print(f"  re-enable cronicle: {[t['title'] for t in plan_cronicle]}")
    print(f"  re-activate n8n  : {[t['name'] for t in plan_n8n]}")
    print(f"  maintenance file : remove if master_switch-owned "
          f"(preexisting at off: {snap.get('maintenance_preexisting')})")
    if args.dry_run:
        print("DRY-RUN: no changes made.")
        return 0

    partial = False
    details = {}

    restored, restore_failed = [], []
    for s in plan_sentinels:
        # Whitelist: only ever re-create a KNOWN arming sentinel. A tampered/corrupt snapshot
        # (or a future data/guard/inverted name that leaked in) must never be touch()ed —
        # this subsumes the NEVER_CREATE guard and blocks path traversal / arbitrary file creation.
        if s not in ARMING_SENTINELS:
            restore_failed.append({"sentinel": s, "error": "refused: not a known arming sentinel"})
            partial = True
            continue
        try:
            (_home() / s).touch()
            restored.append(s)
        except OSError as e:
            restore_failed.append({"sentinel": s, "error": str(e)})
            partial = True

    cron_results = cronicle_set(plan_cronicle, 1)
    if any(not r.get("ok") for r in cron_results):
        partial = True

    n8n_results = n8n_set(plan_n8n, activate=True)
    if any(not r.get("ok") for r in n8n_results):
        partial = True

    maintenance_action = remove_maintenance_if_ours()
    if maintenance_action == "kept-foreign" and not snap.get("maintenance_preexisting"):
        # We created it but the marker is gone -> someone replaced it; do not delete their file.
        details["maintenance_note"] = "file exists without our marker; left in place"

    # Post-verify: every known arming sentinel from the baseline must now be present.
    now_present = set(sentinels_present())
    want = {s for s in plan_sentinels if s in ARMING_SENTINELS}
    if not want.issubset(now_present):
        partial = True
        details["sentinels_missing_after_restore"] = sorted(want - now_present)

    # Only advance the recorded state to 'on' on a CLEAN restore. On a partial restore the
    # snapshot stays action='off' (baseline fields preserved) so a plain `on` retry is allowed
    # and re-reads the SAME baseline — the platform is not silently declared healthy.
    new_snap = dict(snap)
    new_snap.update({"ts": int(time.time()),
                     "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "on_operator": args.operator,
                     "action": "off" if partial else "on",
                     "partial": partial})
    save_snapshot(new_snap)

    entry = record_transition(
        "on", "hard" if snap.get("hard") else "soft", args.operator,
        f"restore of off@{snap.get('iso')} ({snap.get('reason')})",
        {"restored": restored, "failed": restore_failed},
        cron_results, n8n_results, {}, maintenance_action, partial, details)

    print(json.dumps(entry, indent=2))
    if partial:
        print("PARTIAL ON — some steps failed; state kept OFF (baseline preserved). "
              "Fix the cause and re-run 'on' (no --force needed).", file=sys.stderr)
        return 3
    print("Agentic system powered ON (exact pre-off state restored; 15-min cooldown engaged).")
    return 0


def cmd_status(args) -> int:
    state = current_state()
    snap = load_snapshot()
    maint = maintenance_state()
    present = sentinels_present()
    guards = guards_present()
    unknown = unknown_gateway_files()
    sessions = active_sessions()
    try:
        chain_ok, first_break, rows = master_switch_audit.verify(_db())
    except Exception as e:  # noqa: BLE001
        chain_ok, first_break, rows = None, None, None
        chain_err = str(e)
    else:
        chain_err = None

    inconsistencies = []
    if state == "on" and maint["ours"]:
        inconsistencies.append("state=on but a master_switch-owned maintenance file exists")
    if state == "off" and present:
        inconsistencies.append(f"state=off but arming sentinels present: {present}")
    if state == "off" and not maint["exists"]:
        inconsistencies.append("state=off but no maintenance file exists")
    missing_guards = [g for g in GUARD_SENTINELS if g not in guards]
    if missing_guards:
        inconsistencies.append(f"guard sentinels missing (pre-existing posture?): {missing_guards}")
    for nc in NEVER_CREATE:
        if (_home() / nc).exists():
            inconsistencies.append(f"inverted kill-switch present (guard disabled): {nc}")

    out = {
        "state": state,
        "last_transition": {k: snap.get(k) for k in ("action", "iso", "operator", "reason", "hard")},
        "maintenance": {"exists": maint["exists"], "master_switch_owned": maint["ours"]},
        "arming_sentinels_present": present,
        "guards_present": guards,
        "unknown_gateway_files": unknown,
        "active_sessions": sessions,
        "ledger": {"rows": rows, "chain_intact": chain_ok, "first_break_id": first_break,
                   **({"error": chain_err} if chain_err else {})},
        "inconsistencies": inconsistencies,
    }
    if args.emit_metrics:
        write_prom(1 if state == "on" else 0, 1 if snap.get("partial") else 0)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"Master switch: {state.upper()}"
              + (f"  (last: {snap.get('action')} @ {snap.get('iso')} by {snap.get('operator')})"
                 if snap else "  (no transitions recorded)"))
        print(f"  maintenance file : {'present' if maint['exists'] else 'absent'}"
              + (" [master_switch-owned]" if maint["ours"] else ""))
        print(f"  arming sentinels : {len(present)}/{len(ARMING_SENTINELS)} present")
        print(f"  guard sentinels  : {len(guards)}/{len(GUARD_SENTINELS)} present")
        print(f"  active sessions  : {len(sessions)}")
        print(f"  ledger           : rows={rows} chain_intact={chain_ok}")
        if unknown:
            print(f"  WARN unmanaged gateway.* files: {unknown}")
        for inc in inconsistencies:
            print(f"  INCONSISTENT: {inc}")
    return 0 if not inconsistencies else 4


def cmd_log(args) -> int:
    try:
        rows = master_switch_audit.tail(_db(), args.n)
    except Exception as e:  # noqa: BLE001
        print(f"ledger unavailable ({e}); falling back to JSONL", file=sys.stderr)
        rows = []
    if rows:
        for d in rows:
            print(json.dumps(d))
        return 0
    try:
        lines = _jsonl_log().read_text().strip().splitlines()
        for line in lines[-args.n:]:
            print(line)
    except OSError:
        print("(no transitions logged yet)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_off = sub.add_parser("off", help="power the agentic system OFF")
    p_off.add_argument("--reason", required=True)
    p_off.add_argument("--operator", default=os.environ.get("USER", "operator"))
    p_off.add_argument("--hard", action="store_true",
                       help="also deactivate dispatch-lane n8n workflows")
    p_off.add_argument("--kill-sessions", action="store_true",
                       help="TERM in-flight dispatched claude sessions")
    p_off.add_argument("--dry-run", action="store_true")
    p_off.add_argument("--force", action="store_true")

    p_on = sub.add_parser("on", help="power the agentic system ON (exact restore)")
    p_on.add_argument("--operator", default=os.environ.get("USER", "operator"))
    p_on.add_argument("--dry-run", action="store_true")
    p_on.add_argument("--force", action="store_true")

    p_st = sub.add_parser("status", help="show switch state + consistency checks")
    p_st.add_argument("--json", action="store_true")
    p_st.add_argument("--emit-metrics", action="store_true")

    p_log = sub.add_parser("log", help="show the transition ledger")
    p_log.add_argument("--n", type=int, default=10)

    args = ap.parse_args()

    lock_path = _state_dir() / ".lock"
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another master-switch operation is in progress; aborting.", file=sys.stderr)
            return 5
        if args.cmd == "off":
            return cmd_off(args)
        if args.cmd == "on":
            return cmd_on(args)
        if args.cmd == "status":
            return cmd_status(args)
        return cmd_log(args)


if __name__ == "__main__":
    sys.exit(main())
