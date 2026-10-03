#!/bin/bash
# seed-host-agnostic-suppression.sh — idempotent seed of host-agnostic ("*") transient
# suppression knowledge rows (IFRNLLEI01PRD pipeline repair).
#
# Tier-1 Phase-2 transient suppression was pinned to a single host (nl-claude01),
# so the same flappy K8s alerts on awx/seaweedfs/other hosts (e.g. 1111/1112/1113) were
# never suppression candidates. tier1_suppression.py now matches hostname='*' rows
# (window-exempt — they're policy, not aging incidents), still gated by alert_rule
# exact-match + severity!=critical + confidence>=0.7 + a transient keyword. This seeds
# the host-agnostic rows for the well-known self-resolving alert_rules.
#
# Safe to re-run (INSERTs only when the '*' row for that alert_rule is absent).
set -uo pipefail
DB="${GATEWAY_DB:-/home/app-user/gateway-state/gateway.db}"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

seed() {
  local rule="$1" conf="$2" rc="$3"
  local exists
  exists=$(sqlite3 "$DB" "SELECT count(*) FROM incident_knowledge WHERE hostname='*' AND alert_rule='$rule';")
  if [ "${exists:-0}" -gt 0 ]; then echo "  $rule: present"; return; fi
  sqlite3 "$DB" "INSERT INTO incident_knowledge
    (alert_rule, hostname, site, root_cause, resolution, confidence, created_at, tags, project)
    VALUES ('$rule','*','','$rc',
      'Self-resolves; transient flap. Auto-resolve at Tier 1 unless critical or re-firing.',
      '$conf','$NOW','transient,flap,self-resolved,host-agnostic','chatops');"
  echo "  $rule: seeded (conf=$conf)"
}

seed "TargetDown" "0.8" "Prometheus scrape target briefly unreachable (pod restart, rollout, node blip); returns next scrape."
seed "HighPodRestartRate" "0.8" "Short-lived pod restart churn (rollout, OOM-and-recover, image pull); rate falls back under threshold."
seed "ContainerOOMKilled" "0.78" "Container hit its memory limit and restarted; recovers automatically. Escalate only if recurring on the same pod (real undersizing)."
seed "KubeClientErrors" "0.8" "Transient kube-apiserver client errors during apiserver/etcd blips; clears when the control plane settles."
echo "done."
