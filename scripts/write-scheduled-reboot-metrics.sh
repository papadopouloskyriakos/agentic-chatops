#!/bin/bash
# write-scheduled-reboot-metrics.sh — Prometheus metrics for the scheduled-reboot
# suppression (self-learning). Runs every 5 min (Cronicle) on nl-claude01.
#
# Emits: registry row counts by status, plus the two-phase verify accumulators
# (verified / misclassified / unreachable) read from the verify script's state
# file. Atomic tmp+mv to the node_exporter textfile collector.
DB=/app/cubeos/claude-context/gateway.db
OUT=/var/lib/node_exporter/textfile_collector/scheduled_reboot_metrics.prom
TMPOUT="${OUT}.tmp"
COUNTERS=/home/app-user/gateway-state/scheduled-reboot-verify-counters.json
[ -f "$DB" ] || exit 0
mkdir -p "$(dirname "$OUT")" 2>/dev/null
> "$TMPOUT"

echo "# HELP scheduled_reboot_registry_entries Scheduled-reboot registry rows by status" >> "$TMPOUT"
echo "# TYPE scheduled_reboot_registry_entries gauge" >> "$TMPOUT"
for s in observing live disabled; do
  c=$(sqlite3 "$DB" "SELECT COUNT(*) FROM discovered_scheduled_reboots WHERE status='$s';" 2>/dev/null || echo 0)
  echo "scheduled_reboot_registry_entries{status=\"$s\"} $c" >> "$TMPOUT"
done

echo "# HELP scheduled_reboot_verified_total Two-phase verifies that confirmed a clean scheduled reboot" >> "$TMPOUT"
echo "# TYPE scheduled_reboot_verified_total counter" >> "$TMPOUT"
echo "# HELP scheduled_reboot_misclassified_total Two-phase verifies that REOPENED (boot was not a clean scheduled reboot)" >> "$TMPOUT"
echo "# TYPE scheduled_reboot_misclassified_total counter" >> "$TMPOUT"
echo "# HELP scheduled_reboot_verify_unreachable_total Two-phase verifies where the host could not be SSH-checked" >> "$TMPOUT"
echo "# TYPE scheduled_reboot_verify_unreachable_total counter" >> "$TMPOUT"
python3 - "$COUNTERS" "$TMPOUT" <<'PY' 2>/dev/null || true
import json, sys
path, out = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(path))
except Exception:
    d = {}
def w(name, val):
    with open(out, "a") as fh:
        fh.write(f"{name} {int(val or 0)}\n")
w("scheduled_reboot_verified_total", d.get("verified", 0))
w("scheduled_reboot_misclassified_total", d.get("misclassified", 0))
w("scheduled_reboot_verify_unreachable_total", d.get("verify_unreachable", 0))
PY

echo "# HELP scheduled_reboot_metrics_last_run_timestamp_seconds Last write-scheduled-reboot-metrics run" >> "$TMPOUT"
echo "# TYPE scheduled_reboot_metrics_last_run_timestamp_seconds gauge" >> "$TMPOUT"
echo "scheduled_reboot_metrics_last_run_timestamp_seconds $(date +%s)" >> "$TMPOUT"

mv -f "$TMPOUT" "$OUT"
