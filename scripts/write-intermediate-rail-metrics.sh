#!/usr/bin/env bash
# write-intermediate-rail-metrics.sh — Prom textfile metrics for the
# intermediate-step semantic rail (IFRNLLEI01PRD-749 / G2.P0.3).
#
# Emits:
#   chatops_intermediate_rail_check_total{category, in_distribution}    counter (24h window)
#   chatops_intermediate_rail_drift_score{category}                     gauge   (out-of-dist ratio)
#   chatops_intermediate_rail_last_run_timestamp                        gauge
#
# Cron: */10 * * * *

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTDIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
DB_PATH="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
mkdir -p "$OUTDIR"

TARGET="$OUTDIR/intermediate-rail-metrics.prom"
TMP=$(mktemp "${TARGET}.XXXXXX")
trap 'rm -f "$TMP"' EXIT

DB_PATH="$DB_PATH" python3 <<'PY' > "$TMP"
import os, sqlite3, time, json
db = os.environ["DB_PATH"]
lines = []
lines.append("# HELP chatops_intermediate_rail_check_total Number of intermediate_rail_check events in the last 24h.")
lines.append("# TYPE chatops_intermediate_rail_check_total gauge")
lines.append("# HELP chatops_intermediate_rail_drift_score Out-of-distribution ratio per category over the last 24h.")
lines.append("# TYPE chatops_intermediate_rail_drift_score gauge")
lines.append("# HELP chatops_intermediate_rail_last_run_timestamp Unix seconds of the last exporter run.")
lines.append("# TYPE chatops_intermediate_rail_last_run_timestamp gauge")

if os.path.exists(db):
    try:
        conn = sqlite3.connect(db, timeout=5)
        rows = conn.execute(
            "SELECT payload_json FROM event_log "
            "WHERE event_type='intermediate_rail_check' "
            "AND emitted_at > datetime('now','-24 hours')"
        ).fetchall()
        per_cat: dict[str, dict[str, int]] = {}
        for (payload,) in rows:
            try:
                p = json.loads(payload or "{}")
            except json.JSONDecodeError:
                continue
            sigs = p.get("signals") or []
            cat = "unknown"
            for s in sigs:
                if isinstance(s, str) and s.startswith("regex:") and s.endswith((":availability", ":resource", ":storage", ":network", ":kubernetes", ":certificate", ":maintenance", ":correlated", ":security-incident")):
                    cat = s.split(":")[-1]
                    break
            in_dist = "1" if p.get("is_in_distribution") else "0"
            d = per_cat.setdefault(cat, {"in_dist": 0, "out_dist": 0})
            if p.get("is_in_distribution"):
                d["in_dist"] += 1
            else:
                d["out_dist"] += 1
        for cat, d in sorted(per_cat.items()):
            total = d["in_dist"] + d["out_dist"]
            lines.append(f'chatops_intermediate_rail_check_total{{category="{cat}",in_distribution="true"}} {d["in_dist"]}')
            lines.append(f'chatops_intermediate_rail_check_total{{category="{cat}",in_distribution="false"}} {d["out_dist"]}')
            ratio = (d["out_dist"] / total) if total else 0.0
            lines.append(f'chatops_intermediate_rail_drift_score{{category="{cat}"}} {ratio:.4f}')
        conn.close()
    except sqlite3.OperationalError:
        pass

lines.append(f"chatops_intermediate_rail_last_run_timestamp {int(time.time())}")
print("\n".join(lines))
PY

chmod 0644 "$TMP"
mv "$TMP" "$TARGET"
trap - EXIT
