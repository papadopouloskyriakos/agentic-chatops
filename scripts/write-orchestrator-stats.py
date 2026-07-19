#!/usr/bin/env python3
"""Deeper control-plane metrics for the Grafana orchestrator overview (2026-06-26). Emits the stats that
were NOT already in Prometheus — per-table DB row counts, the autonomy-forward decision-band split, and the
auto-approve ratio — so the realtime dashboard has a complete picture. READ-ONLY (mode=ro). Cron */15.
"""
import os
import sqlite3
import time

DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
OUT = "/var/lib/node_exporter/textfile_collector/orchestrator_stats.prom"
TABLES = ["session_log", "session_risk_audit", "incident_knowledge", "otel_spans", "event_log",
          "agent_diary", "session_transcripts", "wiki_articles", "llm_usage", "circuit_breakers"]


def main():
    lines = []
    ntables = 0
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
        ntables = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        lines += ["# HELP gateway_db_table_rows Row count per gateway DB table.",
                  "# TYPE gateway_db_table_rows gauge"]
        for t in TABLES:
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                lines.append(f'gateway_db_table_rows{{table="{t}"}} {n}')
            except Exception:
                pass
        lines += ["# HELP gateway_db_tables_total Tables in the gateway DB.",
                  "# TYPE gateway_db_tables_total gauge", f"gateway_db_tables_total {ntables}"]
        lines += ["# HELP gateway_decisions_by_band Autonomy-forward decisions by band.",
                  "# TYPE gateway_decisions_by_band gauge"]
        for band, n in c.execute("SELECT COALESCE(band,'unknown'), COUNT(*) FROM session_risk_audit GROUP BY band"):
            safe = str(band).replace('"', '').replace('\\', '')
            lines.append(f'gateway_decisions_by_band{{band="{safe}"}} {n}')
        row = c.execute("SELECT SUM(auto_approved), COUNT(*) FROM session_risk_audit").fetchone()
        aa, tot = (row[0] or 0), (row[1] or 1)
        lines += ["# HELP gateway_auto_approve_ratio Fraction of autonomy-forward decisions auto-approved.",
                  "# TYPE gateway_auto_approve_ratio gauge", f"gateway_auto_approve_ratio {round(aa / tot, 4)}"]
        c.close()
    except Exception as e:
        lines.append(f"# orchestrator-stats error: {e}")
    lines += ["# HELP gateway_orchestrator_stats_last_run_timestamp_seconds Last run.",
              "# TYPE gateway_orchestrator_stats_last_run_timestamp_seconds gauge",
              f"gateway_orchestrator_stats_last_run_timestamp_seconds {int(time.time())}"]
    try:
        tmp = OUT + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, OUT)
    except Exception:
        pass
    print(f"  orchestrator stats: {ntables} tables + decision bands + auto-approve ratio emitted")


if __name__ == "__main__":
    main()
