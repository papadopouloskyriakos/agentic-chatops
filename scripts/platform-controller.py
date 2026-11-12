#!/usr/bin/env python3
"""Plane-A platform controller — the agentic platform's k8s-style self-healing operator
(IFRNLLEI01PRD-1421 extension, 2026-06-26).

SCOPE: keep the agentic PLATFORM alive and kicking — its OWN operational components. It NEVER touches
the platform's mission (it will not resize a VM, reboot a host, or auto-resolve an incident — that
stays in the autonomy-forward / fail-closed-prediction lane). It only does idempotent, reversible,
low-blast-radius platform ops — the exact class k8s auto-does to a crash-looping pod. Relieves the
human of ADMINISTERING the platform; SMS only when a heal won't take or it is itself down.

Consolidates gateway-watchdog.sh (one operator, not two): reconciles three heal classes —
  1. n8n CRITICAL workflows inactive          -> reactivate (the watchdog's core job, all-monitored)
  2. failed SAFE-LIST gateway Cronicle jobs    -> re-run (covers the bricks + metric-writers)
  3. Cronicle scheduler down                   -> restart the service
...monitors ALL n8n workflows + Cronicle jobs (state -> metrics + OpenObserve), and emits its OWN
dead-man heartbeat (folds in the watchdog's IFRNLLEI01PRD-1152 guarantee).

GUARDRAILS (k8s-style): per-target heal cap/hour -> CrashLoopBackOff -> ESCALATE (the
platform_controller_escalations metric -> a tier-1 alert -> SMS). Never thrashes.

GATED, ships dark: ~/gateway.platform_controller_armed ABSENT (default) = ANALYSIS-ONLY (flags what it
WOULD heal via a metric + audit log, takes NO action); PRESENT = heals. Kill: rm the sentinel.

Does NOT: auto-re-run agora/non-safe-list jobs or n8n executions (idempotency unknown -> escalate);
override the active-state of NON-critical n8n workflows (that is operator intent).
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import cronicle as cron_api  # noqa: E402
import obs_log  # noqa: E402
try:
    import mutation_mode  # noqa: E402 - MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824)
except Exception:  # noqa: BLE001 - absent lib must not crash the controller
    mutation_mode = None

REPO = Path(__file__).resolve().parent.parent
PROM_DIR = Path("/var/lib/node_exporter/textfile_collector")
OUT = PROM_DIR / "platform_controller.prom"
SENTINEL = Path.home() / "gateway.platform_controller_armed"
STATE = Path.home() / "gateway-state" / "platform-controller-heals.json"
AUDIT = Path.home() / "logs" / "claude-gateway" / "platform-controller.log"
HEAL_CAP_PER_HOUR = int(os.environ.get("PLATFORM_HEAL_CAP", "3"))
HEAL_BACKOFF_BASE = int(os.environ.get("PLATFORM_BACKOFF_BASE", "120"))   # s, first cool-down between heals
HEAL_BACKOFF_MAX = int(os.environ.get("PLATFORM_BACKOFF_MAX", "1800"))    # s, 30-min cap (CrashLoopBackOff)
HEAL_ESCALATE_AFTER = int(os.environ.get("PLATFORM_ESCALATE_AFTER", str(HEAL_CAP_PER_HOUR)))  # consec heals -> escalate
MAINTENANCE = Path.home() / "gateway.maintenance"
WATCHDOG = Path(__file__).resolve().parent / "gateway-watchdog.sh"
_HOST = socket.gethostname().split(".")[0]

N8N = "https://n8n.example.net/api/v1"
# Critical n8n workflows that MUST be active (the platform pipeline). Reactivated if found inactive.
CRITICAL_WF = {
    "qadF2WcaBsIR7SWG": "Claude Runner", "uRRkYbRfWuPXrv3b": "Progress Poller",
    "QGKnHGkw4casiWIU": "Matrix Bridge", "e3e2SFPKc1DLsisi": "YouTrack Receiver",
    "Ids38SbH48q4JdLN": "LibreNMS Receiver", "CqrN7hNiJsATcJGE": "Prometheus Receiver",
    "HI9UkcxNDxx6MEFD": "LibreNMS Receiver GR", "bdAYIiLh5vVyMDW7": "Prometheus Receiver GR",
}
# Idempotent gateway jobs safe to auto-re-run (regenerators: metric-writers + the orchestrator bricks).
SAFE_RERUN_HINTS = ("-metrics.", "registry-seed", "registry-check", "registry-curate",
                    "interaction-graph", "orchestration-benchmark", "ship-cronicle-logs",
                    "write-cronicle-metrics", "infragraph-eval", "infragraph-verify")


def _audit(msg):
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT, "a") as f:
            f.write(f"{int(time.time())} {msg}\n")
    except Exception:
        pass


def _state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(s):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s))
    except Exception:
        pass


def _n8n_key():
    REDACTED_a7b84d63
    for p in (REPO / "scripts" / "holistic-agentic-health.sh",):
        try:
            m = re.search(r'N8N_KEY="(eyJ[A-Za-z0-9._-]+)"', p.read_text())
            if m:
                return m.group(1)
        except Exception:
            pass
    return ""


def _n8n(path, key, method="GET"):
    req = urllib.request.Request(f"{N8N}{path}", headers={"X-N8N-API-KEY": key}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=15))


def _cronicle_down():
    try:
        for line in (PROM_DIR / "cronicle_metrics.prom").read_text().splitlines():
            if line.startswith("cronicle_scheduler_up "):
                return line.split()[1] == "0"
    except Exception:
        pass
    return False


class Reconciler:
    def __init__(self):
        self.armed = SENTINEL.exists()
        self.now = int(time.time())
        self.state = _state()
        self.candidates, self.healed, self.escalations, self.backoffs = [], 0, [], []
        self.wf_active = {}
        self.monitored = {"n8n_total": 0, "n8n_inactive_critical": 0, "cronicle_failed": 0, "n8n_healthy": 0}

    def _heal_decision(self, target):
        """k8s CrashLoopBackOff: 'heal' | 'backoff' (cooling down) | 'escalate' (gave up). Exponential
        backoff between heals of the SAME target; the count resets on a clean run (reset_recovered),
        so a target that recovers and later fails again starts the backoff fresh (was a flat 3/hr cap)."""
        hist = [t for t in self.state.get(target, []) if t > self.now - 3 * HEAL_BACKOFF_MAX]
        n = len(hist)
        if n >= HEAL_ESCALATE_AFTER:
            return "escalate"
        if n == 0:
            return "heal"
        backoff = min(HEAL_BACKOFF_BASE * (2 ** (n - 1)), HEAL_BACKOFF_MAX)
        return "backoff" if (self.now - hist[-1]) < backoff else "heal"

    def _capped(self, target):  # back-compat: True = won't heal this cycle (escalating or cooling down)
        return self._heal_decision(target) != "heal"

    def reset_recovered(self):
        """Clean-run reset: a target no longer flagged a candidate has recovered -> drop its heal
        history so a later failure restarts the backoff fresh (k8s resets CrashLoopBackOff on recovery)."""
        for t in list(self.state.keys()):
            if t not in self.candidates:
                del self.state[t]

    def _act(self, target, kind, fn):
        """Apply a heal: exponential backoff -> CrashLoopBackOff -> escalate. Gated, audited, logged."""
        self.candidates.append(target)
        decision = self._heal_decision(target)
        if decision == "escalate":
            self.escalations.append(target)
            _audit(f"ESCALATE {target} ({kind}): {HEAL_ESCALATE_AFTER}+ heals w/o recovery -> human needed")
            obs_log.event("orchestrator", source="platform-controller", action="escalate",
                          target=target, kind=kind, level="error")
            return
        if decision == "backoff":
            self.backoffs.append(target)
            _audit(f"BACKOFF {target} ({kind}): exponential cool-down, not healing this cycle")
            return
        if mutation_mode and mutation_mode.is_shadow():
            _audit(f"SHADOW (MUTATIONS=OFF, log-only) would heal {kind} {target}")
            mutation_mode.log_wouldve("platform-heal", rationale=f"would apply heal {kind}",
                                      target=target, kind=kind)
            return
        if not self.armed:
            _audit(f"CANDIDATE (analysis-only) {kind} {target}")
            return
        ok = False
        try:
            ok = fn()
        except Exception as e:
            _audit(f"heal EXC {target}: {e}")
        self.state.setdefault(target, []).append(self.now)
        if ok:
            self.healed += 1
            _audit(f"HEALED {target} ({kind})")
            obs_log.event("orchestrator", source="platform-controller", action="healed",
                          target=target, kind=kind, level="warn")
        else:
            _audit(f"heal FAILED {target} ({kind})")
            obs_log.event("orchestrator", source="platform-controller", action="heal_failed",
                          target=target, kind=kind, level="error")

    def reconcile_n8n(self):
        key = _n8n_key()
        if not key:
            return
        try:
            wfs = _n8n("/workflows?limit=250", key).get("data", [])
        except Exception:
            return
        self.monitored["n8n_total"] = len(wfs)
        self.monitored["n8n_healthy"] = 1  # the API answered -> n8n reachable
        for wf in wfs:
            wid = wf.get("id")
            if wid in CRITICAL_WF:
                active = bool(wf.get("active"))
                self.wf_active[CRITICAL_WF[wid]] = 1 if active else 0
                if not active:
                    self.monitored["n8n_inactive_critical"] += 1
                    self._act(f"n8n:{CRITICAL_WF[wid]}", "reactivate-workflow",
                              lambda wid=wid: _n8n(f"/workflows/{wid}/activate", key, "POST").get("active") is True)

    def reconcile_cronicle_jobs(self):
        stats = cron_api.event_failure_stats()
        sched = {e["id"]: e for e in cron_api.schedule()}
        sid = ""
        for eid, s in stats.items():
            if s["last_code"] in (0, "0", None):
                continue
            ev = sched.get(eid, {})
            if ev.get("category") != "gateway":
                continue  # never auto-rerun agora / non-gateway
            cmd = (ev.get("params") or {}).get("script", "")
            title = ev.get("title", "")
            if not any((h in cmd or h in title) for h in SAFE_RERUN_HINTS):
                continue  # only idempotent regenerators (matched by title or embedded path)
            self.monitored["cronicle_failed"] += 1
            if not sid and self.armed and not self._capped(f"job:{s['title']}"):
                sid = cron_api.login()
            self._act(f"job:{s['title']}", "rerun-cronicle-job",
                      lambda eid=eid, sid=sid: cron_api.run_now(eid, sid) == 0)

    def reconcile_cronicle_service(self):
        if _cronicle_down():
            self._act("cronicle-service", "restart-scheduler",
                      lambda: subprocess.run(["sudo", "systemctl", "restart", "cronicle"],
                                             capture_output=True, timeout=60).returncode == 0)

    def reconcile_watchdog_heals(self):
        """Run gateway-watchdog.sh's proven heals as a library (n8n-restart, Bridge bounce, zombie +
        stale-lock cleanup). ALWAYS-ON — these were never gated; the controller is now their single
        scheduler (the watchdog's standalone Cronicle job is retired). This is the one entry point."""
        if not WATCHDOG.exists():
            return
        try:
            subprocess.run(["bash", str(WATCHDOG), "--heals-only"], capture_output=True, timeout=180)
        except Exception as e:
            _audit(f"watchdog-heals invocation failed: {e}")

    def emit(self, heartbeat_only=False):
        m = self.monitored
        now = int(time.time())
        # The dead-man metrics ALWAYS emit (incl. during maintenance) so the heartbeat never goes stale.
        lines = [
            "# HELP platform_controller_last_run_timestamp_seconds Heartbeat (dead-man).",
            "# TYPE platform_controller_last_run_timestamp_seconds gauge",
            f"platform_controller_last_run_timestamp_seconds {now}",
            "# HELP gateway_watchdog_heartbeat_timestamp_seconds Dead-man heartbeat (consolidated from gateway-watchdog.sh; IFRNLLEI01PRD-1152).",
            "# TYPE gateway_watchdog_heartbeat_timestamp_seconds gauge",
            f'gateway_watchdog_heartbeat_timestamp_seconds{{host="{_HOST}"}} {now}',
            "# HELP platform_controller_armed Sentinel present (1) or analysis-only (0)",
            "# TYPE platform_controller_armed gauge",
            f"platform_controller_armed {1 if self.armed else 0}",
        ]
        if not heartbeat_only:
            lines += [
                "# HELP platform_controller_candidates Unhealthy platform targets detected",
                "# TYPE platform_controller_candidates gauge",
                f"platform_controller_candidates {len(self.candidates)}",
                "# HELP platform_controller_healed_total Targets healed this run",
                "# TYPE platform_controller_healed_total gauge",
                f"platform_controller_healed_total {self.healed}",
                "# HELP platform_controller_escalations Targets that hit the heal cap (need a human -> SMS)",
                "# TYPE platform_controller_escalations gauge",
                f"platform_controller_escalations {len(self.escalations)}",
                "# HELP platform_controller_backoffs Targets in exponential cool-down (not healed this run)",
                "# TYPE platform_controller_backoffs gauge",
                f"platform_controller_backoffs {len(self.backoffs)}",
                "# HELP platform_controller_n8n_workflows_total n8n workflows monitored",
                "# TYPE platform_controller_n8n_workflows_total gauge",
                f"platform_controller_n8n_workflows_total {m['n8n_total']}",
                "# HELP gateway_n8n_healthy 1 if n8n API reachable on the last run, else 0.",
                "# TYPE gateway_n8n_healthy gauge",
                f"gateway_n8n_healthy {m.get('n8n_healthy', 0)}",
                "# HELP gateway_workflow_active 1 if a critical n8n workflow is active, 0 if inactive.",
                "# TYPE gateway_workflow_active gauge",
            ]
            for w, v in sorted(self.wf_active.items()):
                lines.append(f'gateway_workflow_active{{workflow="{w}"}} {v}')
        try:
            tmp = str(OUT) + ".tmp"
            with open(tmp, "w") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, OUT)
        except Exception:
            pass


def main():
    # Maintenance mode: suppress all heals (don't fight a planned change) but KEEP the dead-man alive.
    if MAINTENANCE.exists():
        Reconciler().emit(heartbeat_only=True)
        print("  maintenance mode — heals suppressed, heartbeat emitted")
        return
    r = Reconciler()
    r.reconcile_cronicle_service()
    r.reconcile_cronicle_jobs()
    r.reconcile_n8n()
    r.reconcile_watchdog_heals()
    r.reset_recovered()  # clean-run reset: drop backoff history for targets that recovered this cycle
    _save(r.state)
    r.emit()
    print(f"  armed={r.armed} candidates={len(r.candidates)} healed={r.healed} "
          f"escalations={len(r.escalations)} monitored={r.monitored}")


if __name__ == "__main__":
    main()
