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
DB="${GATEWAY_DB:-$HOME/gateway-state/gateway.db}"  # cutover 2026-05-17; old cubeos path is a stale snapshot
OUT_DIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
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

  # --- Starved-trial dead-man (IFRNLLEI01PRD-1664/1666) ---------------------------------
  # The ~2.5-month-dark trial pipeline was invisible because nothing tracked whether
  # assignments actually JOIN to judgments. arm_samples is the JOINABLE count the
  # finalizer's Welch t-test uses; if assignments>0 but arm_samples=0, the issue_id join
  # is broken (empty/quoted ids). malformed_issue_ids MUST be 0.
  echo "# HELP prompt_trial_arm_samples Joinable (assignment JOIN judgment) samples per active trial arm."
  echo "# TYPE prompt_trial_arm_samples gauge"
  sqlite3 "$DB" "SELECT sta.trial_id, sta.variant_idx, COUNT(*) FROM session_trial_assignment sta JOIN session_judgment sj ON sj.issue_id=sta.issue_id WHERE sta.trial_id IN (SELECT id FROM prompt_patch_trial WHERE status='active') GROUP BY sta.trial_id, sta.variant_idx" | \
    while IFS='|' read -r tid v n; do [ -n "$tid" ] && echo "prompt_trial_arm_samples{trial_id=\"${tid}\",variant=\"${v}\"} ${n}"; done

  echo "# HELP prompt_trial_assignments Total assignment rows per active trial (assignments>0 with 0 joinable samples => broken issue_id join)."
  echo "# TYPE prompt_trial_assignments gauge"
  sqlite3 "$DB" "SELECT trial_id, COUNT(*) FROM session_trial_assignment WHERE trial_id IN (SELECT id FROM prompt_patch_trial WHERE status='active') GROUP BY trial_id" | \
    while IFS='|' read -r tid n; do [ -n "$tid" ] && echo "prompt_trial_assignments{trial_id=\"${tid}\"} ${n}"; done

  MALFORMED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_trial_assignment WHERE issue_id='' OR issue_id LIKE '%\"%'")
  echo "# HELP prompt_trial_malformed_issue_ids Assignment rows with an empty or quote-wrapped issue_id (cannot join judgment). MUST be 0."
  echo "# TYPE prompt_trial_malformed_issue_ids gauge"
  echo "prompt_trial_malformed_issue_ids ${MALFORMED:-0}"

  echo "# HELP prompt_trial_newest_assignment_age_seconds Age of the newest assignment per active trial (no-intake / starvation detector)."
  echo "# TYPE prompt_trial_newest_assignment_age_seconds gauge"
  sqlite3 "$DB" "SELECT trial_id, CAST((julianday('now')-julianday(MAX(assigned_at)))*86400 AS INT) FROM session_trial_assignment WHERE trial_id IN (SELECT id FROM prompt_patch_trial WHERE status='active') GROUP BY trial_id" | \
    while IFS='|' read -r tid age; do [ -n "$tid" ] && echo "prompt_trial_newest_assignment_age_seconds{trial_id=\"${tid}\"} ${age}"; done
} > "$TMP_FILE"

mv "$TMP_FILE" "$OUT_FILE"
