#!/usr/bin/env python3
"""registry-curate.py — apply the BASELINE component classification to the manifest.

Brick 1 (IFRNLLEI01PRD-1421): registry-seed.py discovers components; this encodes the
human judgment of which are EXPECTED-dark (dormant by design -> known_dark, excluded from
alerting) and which MUST be fresh (critical -> a dark one fails the check + pages). Kept as
re-runnable code (not hand-edits) so the classification survives a from-scratch re-seed.
Idempotent. Run after registry-seed.py.

Policy:
  known_dark — inactive n8n workflows (intentionally off), retired/empty tables, event-driven
               outputs (chaos), and naturally-sparse low-use tables (teacher).
  critical   — the self-audit tier, the dead-man's-switch, the registry itself, and the core
               live pipeline (Runner + Poller). A critical component going dark is a real
               incident, so these page via RegistryCriticalDark.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "config" / "component-registry.json"

# Exact-name critical set (must be fresh; verified currently-fresh so marking won't false-fire).
CRITICAL = {
    "prom:holistic_health", "prom:self_audit", "prom:handoff_depth", "prom:registry_check",
    # prom:gateway_watchdog RETIRED 2026-06-26 — the watchdog was consolidated into platform-controller.py;
    # the dead-man heartbeat now lives in platform_controller.prom (= prom:platform_controller, critical).
    "prom:session_metrics", "prom:agent_metrics",
    "n8n:NL - Claude Gateway Runner", "n8n:NL - Claude Gateway Progress Poller",
    # The orchestrator monitors its OWN bricks (completes who-watches-the-watcher):
    "prom:interaction_graph", "prom:orchestration_benchmark",
    # The scheduler that now runs all 172 migrated crons (its death = nothing runs):
    "prom:cronicle_metrics",
    # The Plane-A self-healing operator — if the platform's healer goes dark, nothing self-heals:
    "prom:platform_controller",
    # The agora escalator's own dead-man (finops-agora B2b, 2026-07-04): the escalator pages agora
    # RED via the Twilio bridge, so if ITS cron dies nothing pages — unless the registry watches its
    # heartbeat. health_notify.py emits agora_escalator.prom every run; marking it critical makes
    # RegistryCriticalDark (tier-1) fire when the alerter itself goes dark.
    "prom:agora_escalator",
    # The Renovate MR-autonomy lane's own liveness writer (2026-07-06). This */5 writer emits the lane's
    # decisions_total / chain_ok / live_enabled / merged_without_snapshot invariants; if it dies the
    # autonomous-MERGE lane runs unobserved (exactly the dark-component class this registry exists to
    # close), so mark it critical → RegistryCriticalDark (tier-1) pages when the dead-man goes stale.
    "prom:renovate_autonomy_metrics",
    # MUTATIONS=OFF shadow-mode liveness writer (IFRNLLEI01PRD-1824). This */5 job emits
    # gateway_mutations_shadow_active — the single signal telling the orchestrator whether the
    # autonomous system is actuating or in log-only mode. If the writer dies we lose that visibility
    # (can't tell if MUTATIONS is ON or OFF), so mark it critical → RegistryCriticalDark (tier-1).
    "prom:mutation_mode",
    # Whole-system master power switch liveness writer (IFRNLLEI01PRD-1823). This */5 job emits
    # gateway_master_switch_state / chain_intact / partial_last — the canonical dead-man for the
    # master switch. It is the ONE liveness owner for the master-switch subsystem (the cronicle-job
    # and the ledger table stay non-critical: the table is written only on rare transitions, so a
    # write-recency liveness would false-dark). If this writer dies, the orchestrator is blind to
    # whether the entire agentic system is ON or OFF → mark critical → RegistryCriticalDark (tier-1).
    "prom:master_switch",
}
# Per-component liveness tuning (merged onto the auto liveness on re-seed). The orchestration
# benchmark runs WEEKLY, so its .prom is legitimately up to ~8d old between runs.
LIVENESS_OVERRIDE = {
    "prom:orchestration_benchmark": {"max_stale_seconds": 700000},
    # agora escalator runs DAILY (health_notify 07:05); the 90000s (25h) prom default leaves only
    # ~1h margin, so give a daily-cadence margin (~27.7h) to avoid a false dark on a slightly-late run.
    "prom:agora_escalator": {"max_stale_seconds": 100000},
    # mutation-mode metrics run */5; the 90000s (25h) prom default would let a dead shadow-state
    # writer go unnoticed for a day. Tighten to 30min (6 missed runs) so RegistryCriticalDark fires fast.
    "prom:mutation_mode": {"max_stale_seconds": 1800},
    # master-switch metrics run */5; tighten the 90000s (25h) prom default to 30min (6 missed runs)
    # so RegistryCriticalDark fires fast on a dead whole-system power-state writer.
    "prom:master_switch": {"max_stale_seconds": 1800},
}
# Retired / intentionally-empty tables (dark-component audit 2026-06-25 classified these).
KNOWN_DARK_TABLES = {
    "table:a2a_task_log", "table:credential_usage_log", "table:execution_log",
    "table:features", "table:work_units", "table:chaos_findings",
    "table:learning_progress", "table:learning_sessions", "table:session_feedback",
    "table:handoff_log", "table:teacher_operator_dm",
}
# Event-driven / on-demand prom outputs (no fixed cadence -> not "dark" when idle).
KNOWN_DARK_PROMS = {"prom:chaos_exercise", "prom:chaos_test",
                    "prom:gateway_watchdog"}  # retired 2026-06-26: consolidated into platform-controller


def main() -> int:
    dry = "--dry-run" in sys.argv
    doc = json.loads(MANIFEST.read_text())
    comps = doc["components"]
    nc = nk = 0
    for c in comps:
        name, typ = c["name"], c["type"]
        # critical (authoritative — also CLEARS the flag when a component is retired from the set,
        # so a removed-and-now-absent component doesn't linger as a false critical-dark)
        should_crit = name in CRITICAL
        if should_crit and not c.get("critical"):
            c["critical"] = True; nc += 1
        elif c.get("critical") and not should_crit:
            c["critical"] = False
        # per-component liveness tuning (e.g. the weekly benchmark)
        if name in LIVENESS_OVERRIDE:
            c["liveness_override"] = LIVENESS_OVERRIDE[name]
            if isinstance(c.get("liveness"), dict):
                c["liveness"].update(LIVENESS_OVERRIDE[name])
        # known_dark: inactive workflows + retired tables + event-driven proms
        kd = (
            (typ == "n8n-workflow" and c.get("observed_active") is False)
            or name in KNOWN_DARK_TABLES
            or name in KNOWN_DARK_PROMS
        )
        if kd and not c.get("known_dark"):
            c["known_dark"] = True; nk += 1
            c.setdefault("notes", "baseline-curate: dormant/retired/event-driven by design")
    print(f"  marked critical: +{nc} (total {sum(1 for c in comps if c.get('critical'))})")
    print(f"  marked known_dark: +{nk} (total {sum(1 for c in comps if c.get('known_dark'))})")
    if dry:
        print("  (--dry-run: not writing)"); return 0
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"  wrote {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
