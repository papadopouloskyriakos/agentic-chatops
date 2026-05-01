#!/usr/bin/env bash
# write-trial-metrics.sh — Prometheus exporter for prompt_patch_trial
# (IFRNLLEI01PRD-645). Cron: */10 * * * *.
#
# Metrics:
#   prompt_trials_active            gauge — currently active trials
#   prompt_trials_completed_total   counter — trials promoted a winner
#   prompt_trials_aborted_total     counter — aborted (timeout or no-winner)
#   prompt_trial_winner_lift        gauge — lift of last winner vs baseline
set -uo pipefail
DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
OUT_DIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/prometheus/node-exporter}"
OUT_FILE="${OUT_DIR}/prompt_trials.prom"
TMP_FILE="${OUT_FILE}.tmp"

[ -f "$DB" ] || exit 1

if ! sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prompt_patch_trial'" | grep -q 1; then
  echo "# prompt_patch_trial not yet migrated" > "$TMP_FILE"
  mv "$TMP_FILE" "$OUT_FILE" 2>/dev/null || true
  exit 0
fi

{
  N_ACTIVE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM prompt_patch_trial WHERE status='active'")
  echo "# HELP prompt_trials_active Currently active prompt-patch A/B trials."
  echo "# TYPE prompt_trials_active gauge"
  echo "prompt_trials_active ${N_ACTIVE}"

  N_COMPLETED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM prompt_patch_trial WHERE status='completed'")
  echo "# HELP prompt_trials_completed_total All-time count of trials that promoted a winner."
  echo "# TYPE prompt_trials_completed_total counter"
  echo "prompt_trials_completed_total ${N_COMPLETED}"

  N_ABORTED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM prompt_patch_trial WHERE status LIKE 'aborted%'")
  echo "# HELP prompt_trials_aborted_total All-time count of aborted trials (timeout or no-winner)."
  echo "# TYPE prompt_trials_aborted_total counter"
  echo "prompt_trials_aborted_total ${N_ABORTED}"

  echo "# HELP prompt_trials_by_status_total Trial count by status."
  echo "# TYPE prompt_trials_by_status_total gauge"
  sqlite3 "$DB" "SELECT status, COUNT(*) FROM prompt_patch_trial GROUP BY status" | \
    while IFS='|' read -r st n; do
      [ -n "$st" ] && echo "prompt_trials_by_status_total{status=\"${st}\"} ${n}"
    done

  # Lift of the most recent completed trial.
  LIFT=$(sqlite3 "$DB" "
    SELECT ROUND(COALESCE(winner_mean,0) - COALESCE(baseline_mean,0), 4)
    FROM prompt_patch_trial
    WHERE status='completed'
    ORDER BY finalized_at DESC LIMIT 1")
  if [ -n "$LIFT" ]; then
    echo "# HELP prompt_trial_winner_lift Lift (winner_mean - baseline_mean) of the most recent winner."
    echo "# TYPE prompt_trial_winner_lift gauge"
    echo "prompt_trial_winner_lift ${LIFT}"
  fi
} > "$TMP_FILE"

mv "$TMP_FILE" "$OUT_FILE"
