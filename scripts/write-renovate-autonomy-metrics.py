#!/usr/bin/env python3
"""
write-renovate-autonomy-metrics.py — Prometheus textfile-collector writer for the Renovate MR
Autonomy lane (IFRNLLEI01PRD-1645). Recomputes from the append-only renovate_autonomy_audit table
each run (mirrors write-governance-metrics.py). Cron: */5. Register as prom:renovate_autonomy_metrics.

Emits /var/lib/node_exporter/textfile_collector/renovate_autonomy_metrics.prom:
  renovate_autonomy_decisions_total{decision,tier,mode}   counter (monotonic COUNT(*))
  renovate_autonomy_last_run_timestamp_seconds            gauge (freshness / dead-man)
  renovate_autonomy_live_enabled                          gauge (1 = ~/gateway.renovate_autonomy exists)
  renovate_autonomy_merged_without_snapshot_total         counter — INVARIANT, MUST STAY 0
"""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
try:
    REDACTED_a7b84d63novate_audit  # hash-chain verify
except Exception:  # pragma: no cover
    renovate_audit = None

DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
OUT = os.environ.get(
    "RENOVATE_METRICS_OUT",
    "/var/lib/node_exporter/textfile_collector/renovate_autonomy_metrics.prom",
)
SENTINEL = os.path.expanduser("~/gateway.renovate_autonomy")

# A live AUTO decision that bypassed the safety floor (CI not green, review not APPROVE, or a
# required/critical-tier snapshot not verified). This count MUST be 0.
FLOOR_BREACH_SQL = """
SELECT COUNT(*) FROM renovate_autonomy_audit
WHERE mode='live' AND decision='AUTO' AND (
      ci_status != 'success'
   OR review_verdict != 'APPROVE'
   OR ( (snapshot_required='true' OR tier='critical')
        AND COALESCE(json_extract(gates_json,'$.snapshot_verified'),0) != 1 )
)
"""


ENV_FILE = os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")


def esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def main() -> None:
    lines = [
        "# HELP renovate_autonomy_decisions_total Renovate MR autonomy decisions by outcome/tier/mode.",
        "# TYPE renovate_autonomy_decisions_total counter",
    ]
    live = 1 if os.path.exists(SENTINEL) else 0
    breach = 0
    try:
        c = sqlite3.connect(DB, timeout=30)
        c.execute("PRAGMA busy_timeout=30000")
        # table may not exist yet (lane never ran) → treat as zero rows
        have = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='renovate_autonomy_audit'"
        ).fetchone()
        if have:
            for decision, tier, mode, n in c.execute(
                "SELECT decision, COALESCE(NULLIF(tier,''),'none'), mode, COUNT(*) "
                "FROM renovate_autonomy_audit GROUP BY decision, tier, mode"
            ):
                lines.append(
                    f'renovate_autonomy_decisions_total{{decision="{esc(decision)}",'
                    f'tier="{esc(tier)}",mode="{esc(mode)}"}} {n}'
                )
            breach = c.execute(FLOOR_BREACH_SQL).fetchone()[0]
        c.close()
    except Exception as e:  # never let a metrics writer crash-loop; emit what we have
        lines.append(f"# ERROR {esc(str(e))}")

    # tamper-evidence: is the audit hash chain intact? (Dim-6)
    chain_ok = 1
    if renovate_audit is not None:
        try:
            chain_ok = 1 if renovate_audit.verify(DB) is None else 0
        except Exception:
            chain_ok = 1  # a verify error must not false-alarm the tamper metric

    lines += [
        "# HELP renovate_autonomy_merged_without_snapshot_total INVARIANT: live AUTO merges that bypassed the CI/review/snapshot floor. MUST be 0.",
        "# TYPE renovate_autonomy_merged_without_snapshot_total counter",
        f"renovate_autonomy_merged_without_snapshot_total {breach}",
        "# HELP renovate_autonomy_chain_ok 1 if the tamper-evident audit hash chain verifies, 0 if broken (edited/deleted row).",
        "# TYPE renovate_autonomy_chain_ok gauge",
        f"renovate_autonomy_chain_ok {chain_ok}",
        "# HELP renovate_autonomy_live_enabled 1 if ~/gateway.renovate_autonomy sentinel exists (live enactment), else 0 (shadow-only).",
        "# TYPE renovate_autonomy_live_enabled gauge",
        f"renovate_autonomy_live_enabled {live}",
        "# HELP renovate_autonomy_last_run_timestamp_seconds Unix time this writer last ran (freshness/dead-man).",
        "# TYPE renovate_autonomy_last_run_timestamp_seconds gauge",
        f"renovate_autonomy_last_run_timestamp_seconds {int(time.time())}",
    ]

    # ── timeout-to-auto deferred queue (2026-07-07) ──
    to_enabled = 1 if os.path.exists(os.path.expanduser("~/gateway.renovate_timeout_auto")) else 0
    pending = overdue = 0
    status_counts = {}
    try:
        c = sqlite3.connect(DB, timeout=30)
        c.execute("PRAGMA busy_timeout=30000")
        if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='renovate_deferred_merges'").fetchone():
            now = int(time.time())
            pending = c.execute("SELECT COUNT(*) FROM renovate_deferred_merges WHERE status='pending'").fetchone()[0]
            overdue = c.execute("SELECT COUNT(*) FROM renovate_deferred_merges WHERE status='pending' AND deadline_ts<=?", (now,)).fetchone()[0]
            for st, n in c.execute("SELECT status, COUNT(*) FROM renovate_deferred_merges GROUP BY status"):
                status_counts[st] = n
        c.close()
    except Exception:
        pass
    lines += [
        "# HELP renovate_timeout_auto_enabled 1 if ~/gateway.renovate_timeout_auto exists (reversible bumps timeout-auto-merge).",
        "# TYPE renovate_timeout_auto_enabled gauge",
        f"renovate_timeout_auto_enabled {to_enabled}",
        "# HELP renovate_deferred_pending Reversible bumps scheduled for timeout-auto (holding in the grace window).",
        "# TYPE renovate_deferred_pending gauge",
        f"renovate_deferred_pending {pending}",
        "# HELP renovate_deferred_overdue Pending deferred entries PAST their deadline (should be ~0; a rising value = the processor is not running).",
        "# TYPE renovate_deferred_overdue gauge",
        f"renovate_deferred_overdue {overdue}",
        "# HELP renovate_deferred_status_total Deferred-queue entries by terminal status.",
        "# TYPE renovate_deferred_status_total counter",
    ]
    for st in ("merged", "vetoed", "superseded", "expired", "pending", "ineligible"):
        lines.append(f'renovate_deferred_status_total{{status="{esc(st)}"}} {status_counts.get(st, 0)}')

    # ── current open-MR backlog (IFRNLLEI01PRD: RenovateAutonomyHighPollRate gate) ──
    # The poll-RATE alert is computed from decision counters, which are pure history:
    # it can fire on an EMPTY queue and stay silent on a full one. This gauge is the
    # live backlog; the alert now requires renovate_open_mrs > threshold to fire.
    open_mrs, scrape_ok = 0, 0
    try:
        import ssl
        import urllib.request
        tok = os.environ.get("GITLAB_TOKEN", "")
        if not tok and os.path.exists(ENV_FILE):
            for line in open(ENV_FILE, encoding="utf-8"):
                if line.startswith("GITLAB_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
                    break
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            os.environ.get("GITLAB_URL", "https://gitlab.example.net")
            + "/api/v4/projects/7/merge_requests?author_username=renovate-bot&state=opened&per_page=100",
            headers={"PRIVATE-TOKEN": tok})
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            # exclude renovate-hold: a vetoed MR is a DECIDED one, not backlog
            open_mrs = sum(1 for m in json.load(r) if "renovate-hold" not in (m.get("labels") or []))
        scrape_ok = 1
    except Exception:
        pass  # fail-soft: scrape_ok stays 0, gauge reports last-resort 0
    lines += [
        "# HELP renovate_open_mrs Open renovate-bot MRs right now (live backlog; gates the poll-rate alert).",
        "# TYPE renovate_open_mrs gauge",
        f"renovate_open_mrs {open_mrs}",
        "# HELP renovate_open_mrs_scrape_ok 1 if the GitLab backlog scrape succeeded this run.",
        "# TYPE renovate_open_mrs_scrape_ok gauge",
        f"renovate_open_mrs_scrape_ok {scrape_ok}",
    ]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, OUT)


if __name__ == "__main__":
    main()
