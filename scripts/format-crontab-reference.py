#!/usr/bin/env python3
"""Auto-regenerate docs/crontab-reference.md from the live app-user crontab.

Keeps the human-readable reference in sync so "what cron runs X?" queries hit a
fresh doc rather than a stale snapshot.

Usage:
  crontab -l | python3 scripts/format-crontab-reference.py > docs/crontab-reference.md
  # or:
  python3 scripts/format-crontab-reference.py           # reads live crontab

Intended cron: 20 4 * * *  (daily, just after index-memories runs at 15 4)
"""
import os
REDACTED_a7b84d63
import subprocess
import sys
from datetime import datetime

# Map known scripts → purpose (extend as needed)
PURPOSES = {
    "kb-latency-probe.py": "Prometheus RAG latency metrics (p50/p95/p99, embedded-vector count, migration-trigger distance, rerank service health)",
    "faiss-index-sync.py": "Mirror SQLite embeddings to FAISS HNSW index at /var/claude-gateway/vector-indexes/. Daily cron schedule for FAISS index sync. Ready-to-cut-over zero-downtime migration path.",
    "kb-semantic-search.py": "Backfill any new incident_knowledge rows missing embeddings",
    "index-memories.py": "Daily re-index of memory/, CLAUDE.md, docs/*.md into wiki_articles. Prevents silent-regrow of memory-embedding gap.",
    "wiki-compile.py": "Daily wiki compilation with contradiction detection",
    "chaos-calendar.sh": "Daily chaos engineering exercise selection (CMM L3)",
    "weekly-eval-cron.sh": "Weekly hard retrieval eval (50 q judge-scored) + kb_hard_eval_* Prometheus metrics",
    "format-crontab-reference.py": "This script — keeps docs/crontab-reference.md fresh",
    "teacher-agent.py": "Teacher agent (IFRNLLEI01PRD-654) — morning-nudge (daily 08:30 UTC) pings operators about due topics; class-digest (Sun 16:00 UTC) posts weekly aggregate to #learning",
    "write-learning-metrics.sh": "Prometheus exporter for teacher-agent (IFRNLLEI01PRD-654): topics_total/mastered/due, weekly_sessions, quiz_accuracy_7d, longest_streak, bloom_distribution, cron freshness timestamps",
    "build-wiki-site.sh": "Wiki rebuild (IFRNLLEI01PRD-654 follow-up) — triggered by claude-gateway-wiki-build.path on changes to docs/, wiki/, config/curriculum.json, README.extensive.md. Not cron-driven anymore.",
    "close-stale-learning-sessions.py": "Daily cleanup (IFRNLLEI01PRD-655 follow-up) — closes quiz/chat rows in learning_sessions with completed_at IS NULL and started_at >7d ago. Keeps the Prometheus 7d-window metrics accurate and the session log uncluttered.",
    "check-asa-binding-drift.py": "ASA config-drift check — verifies `access-group vti_access_in` bindings, 2 outside_budget identity NAT rules, SLA monitors 1+2, track 1+2, and `timeout floating-conn 0:00:30` on nl-fw01 + gr-fw01. Emits asa_binding_drift_total + asa_nat_rule_present{} + asa_sla_monitor_present{} + asa_track_object_present{} + asa_floating_conn_seconds{}. Extended 2026-04-22 [IFRNLLEI01PRD-668].",
    "budget-pppoe-health.sh": "Budget PPPoE health on nlrtr01 (IFRNLLEI01PRD-670). Emits budget_pppoe_up + budget_pppoe_dual_wan_down (1 on Budget+Freedom both DOWN) + budget_pppoe_info{ip}. SMS via Twilio on entering dual-fail state.",
    "vti-budget-recovery.sh": "Budget-side VTI auto-recovery on nlrtr01 (IFRNLLEI01PRD-670). Mirror of vti-freedom-recovery.sh: when Dialer1 UP + Tunnel<N> UP + BGP to peer not-Established → clear crypto ipsec sa peer. One peer per run, 10-min cooldown.",
    "bgp-mesh-watchdog.sh": "Cross-device iBGP mesh watchdog (IFRNLLEI01PRD-671). Polls show-bgp-summary on 9 BGP speakers (rtr01, fw01, GR-fw01, 4× FRR, 2× VPS). Emits bgp_session_state{local_host,neighbor} 0|1 + bgp_mesh_established_count + bgp_mesh_missing_count. 52-session topology hardcoded as source of truth.",
    "vps-route-health.sh": "VPS BGP-route regression detector (IFRNLLEI01PRD-672). Verifies both VPSs use a `proto bgp` entry for 10.0.X.X/27 (post-2026-04-21 swanctl-loader change). Emits vps_dmz_route_bgp{vps}. Matrix notice on regression to mainif.",
}


def parse_crontab():
    # Prefer explicit stdin (pipe) if non-empty; fall back to live crontab
    stdin_data = ""
    if not sys.stdin.isatty():
        try:
            stdin_data = sys.stdin.read()
        except Exception:
            stdin_data = ""
    if stdin_data.strip():
        out = stdin_data
    else:
        try:
            out = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            print("crontab -l failed", file=sys.stderr)
            sys.exit(1)
    rows = []
    for line in out.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Match: <5 cron fields> <command>
        m = re.match(r"^(\S+\s+\S+\s+\S+\s+\S+\s+\S+)\s+(.+)$", line)
        if not m:
            continue
        schedule, cmd = m.group(1), m.group(2)
        # Try to identify which script — strip /path/to/ and take basename
        script_match = re.search(r"(/\S+\.(?:sh|py))", cmd)
        script = os.path.basename(script_match.group(1)) if script_match else cmd.split()[0]
        purpose = PURPOSES.get(script, "(purpose not catalogued — update format-crontab-reference.py)")
        rows.append((schedule, script, purpose, cmd))
    return rows


def render(rows):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Crontab Reference — app-user@nl-claude01",
        "",
        f"Auto-generated by `scripts/format-crontab-reference.py` on {now}.",
        "Live `crontab -l` is the source of truth — this doc mirrors it.",
        "",
        "## Active cron entries",
        "",
        "| Schedule | Script | Purpose |",
        "|---|---|---|",
    ]
    for schedule, script, purpose, _cmd in rows:
        lines.append(f"| `{schedule}` | `{script}` | {purpose} |")
    lines.extend([
        "",
        "## Eval cadence",
        "",
        "**Hard retrieval + KG eval** via `weekly-eval-cron.sh` on Monday 05:00 UTC.",
        "Emits `kb_hard_eval_hit_rate`, `kb_hard_eval_coverage_rate`, `kb_hard_eval_kg_coverage`, ",
        "`kb_hard_eval_latency_p50_seconds`, `kb_hard_eval_latency_p95_seconds`, and ",
        "`kb_hard_eval_last_run_timestamp_seconds` into the node-exporter textfile collector.",
        "",
        "The 18-query RAGAS golden set (`ragas-eval.py run-golden`) is still manual.",
        "",
        "## Budget enforcement",
        "",
        "**Session cost warning threshold: EUR 5 (five euros, equivalent to $5 USD) per session.** ",
        "**Daily plan-only cap: EUR 25 (twenty-five euros, $25 USD) per day.** ",
        "When a session's accumulated cost crosses the EUR 5 session warning threshold, the ",
        "Runner workflow posts a Matrix heads-up. When the cumulative daily cost crosses the ",
        "EUR 25 plan-only cap, the Runner flips subsequent sessions into plan-only mode ",
        "(no exec tools) until midnight UTC rollover. The EUR 5 session warning and EUR 25 ",
        "daily plan-only cap are the two budget levers.",
        "",
        "## FAISS specifics",
        "",
        "FAISS index sync cron: **`*/15 * * * *`**. Script: `scripts/faiss-index-sync.py`. ",
        "Output: `/var/claude-gateway/vector-indexes/*.faiss` with HNSW_Flat (M=32, efConstruction=128, efSearch=64).",
        "Migration trigger: embedded vectors > 25,000 OR end-to-end p95 > 5s.",
        "",
        "## Dead-man routines",
        "",
        "- `0 10 * * *` chaos-calendar.sh — failure to run indicates cron or script break",
        "- `*/5 * * * *` kb-latency-probe — `kb_rerank_service_up` gauge surfaces rerank container health",
        "- `*/15 * * * *` faiss-index-sync — `/tmp/faiss-sync.log` shows last successful run",
        "- `dmz-cleanup` — `05:45 UTC` on both DMZ hosts (Ansible-managed, not in this crontab)",
        "",
        f"Last regenerated: {now}",
    ])
    return "\n".join(lines) + "\n"


def main():
    rows = parse_crontab()
    print(render(rows), end="")


if __name__ == "__main__":
    main()
