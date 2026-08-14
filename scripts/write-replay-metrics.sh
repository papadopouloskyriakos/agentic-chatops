#!/usr/bin/env bash
# write-replay-metrics.sh — Prometheus textfile metrics for long-horizon replay.
#
# IFRNLLEI01PRD-748 / G1.P0.1.
#
# Emits:
#   chatops_long_horizon_replay_score{run_id, dimension}      gauge per dimension
#   chatops_long_horizon_replay_session_count{run_id}         gauge
#   chatops_long_horizon_replay_last_run_timestamp            gauge (unix s)
#
# Cron: */15 * * * *
# Reads the latest run_id from gateway.db::long_horizon_replay_results.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTDIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
DB_PATH="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
mkdir -p "$OUTDIR"

TARGET="$OUTDIR/replay-metrics.prom"
TMP=$(mktemp "${TARGET}.XXXXXX")
trap 'rm -f "$TMP"' EXIT

DB_PATH="$DB_PATH" python3 <<'PY' > "$TMP"
import os, sqlite3, time
db = os.environ["DB_PATH"]
lines = []
lines.append("# HELP chatops_long_horizon_replay_score Mean score per replay dimension across the latest run.")
lines.append("# TYPE chatops_long_horizon_replay_score gauge")
lines.append("# HELP chatops_long_horizon_replay_session_count Number of sessions scored in the latest run.")
lines.append("# TYPE chatops_long_horizon_replay_session_count gauge")
lines.append("# HELP chatops_long_horizon_replay_last_run_timestamp Unix seconds of the latest run completion.")
lines.append("# TYPE chatops_long_horizon_replay_last_run_timestamp gauge")

if os.path.exists(db):
    try:
        conn = sqlite3.connect(db, timeout=5)
        # Latest run_id (lexicographic max — run_ids are date-stamped).
        row = conn.execute(
            "SELECT run_id, MAX(replayed_at) FROM long_horizon_replay_results GROUP BY run_id ORDER BY 2 DESC LIMIT 1"
        ).fetchone()
        if row:
            run_id, replayed_at = row[0], row[1]
            for dim in ("trace_coherence", "tool_efficiency", "poll_correctness", "composite_score"):
                m = conn.execute(
                    f"SELECT AVG({dim}) FROM long_horizon_replay_results WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                val = float(m[0] or 0.0)
                lines.append(
                    f'chatops_long_horizon_replay_score{{run_id="{run_id}",dimension="{dim}"}} {val:.4f}'
                )
            cnt = conn.execute(
                "SELECT COUNT(*) FROM long_horizon_replay_results WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            lines.append(f'chatops_long_horizon_replay_session_count{{run_id="{run_id}"}} {cnt}')
        conn.close()
    except sqlite3.OperationalError:
        # table not present (migration not applied yet). Emit metric anyway so
        # the alert can detect staleness vs absence.
        pass

lines.append(f"chatops_long_horizon_replay_last_run_timestamp {int(time.time())}")
print("\n".join(lines))
PY

chmod 0644 "$TMP"
mv "$TMP" "$TARGET"
trap - EXIT
