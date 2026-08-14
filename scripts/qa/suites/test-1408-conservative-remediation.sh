#!/usr/bin/env bash
# IFRNLLEI01PRD-1408 — conservative-remediation carve-out + the closed safety floor.
# Covers: every conservative situation -> AUTO; each destructive sibling -> POLL_PAUSE;
# co-occurrence (carve cannot un-protect an irreversible); stateful denylist; docker
# volume-prune hole; P0 -> AUTO_NOTICE; guest reboot stays HITL; flag-off byte-parity.
# Hermetic: INFRAGRAPH_DISABLED=1, temp GATEWAY_DB, both sentinels via env.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"
export QA_SUITE_NAME="1408-conservative-remediation"
CLS="$REPO_ROOT/scripts/classify-session-risk.py"
TESTDB="$(mktemp --suffix=.db)"
# Pin the territory gate OFF (a path that does not exist) so these stateful-FLOOR tests
# are isolated from the LIVE ~/gateway.territory_gate — the gate-ON relaxation is covered
# by test-1408-territory-gate. Likewise pin the host-reboot appetite OFF for the floor.
export TERRITORY_GATE_SENTINEL="$TESTDB.noterritory"
export HOST_REBOOT_AUTO_SENTINEL="$TESTDB.nohostreboot"
trap 'rm -f "$TESTDB"' EXIT

# cls_band <category> <hostname> <command> [CR_FLAG=1]
cls_band() {
  local cat="$1" host="$2" cmd="$3" cr="${4:-1}"
  python3 -c "import json,sys;print(json.dumps({'hypothesis':'fix','hostname':sys.argv[1],'steps':[{'command':sys.argv[2]}]}))" "$host" "$cmd" \
  | env GATEWAY_DB="$TESTDB" INFRAGRAPH_DISABLED=1 AUTONOMY_FORWARD=1 CONSERVATIVE_REMEDIATION="$cr" \
    python3 "$CLS" --category "$cat" --no-audit 2>/dev/null \
  | python3 -c "import json,sys;print(json.load(sys.stdin).get('band'))"
}
want() {  # want <expected-band> <name> <category> <host> <command> [CR]
  start_test "$2"
    assert_eq "$1" "$(cls_band "$3" "$4" "$5" "${6:-1}")" "$2"
  end_test
}

# ── conservative situations -> AUTO ──────────────────────────────────────────
want AUTO disk_image_prune       resource     nl-gpu01 "docker image prune -af"
# `systemctl restart n8n` targets the gateway's OWN control plane — the
# _SELF_PROTECTED_RESTART_RE veto (1408 follow-up) keeps it POLL_PAUSE by design
# (the platform-controller owns those restarts, not the mission lane). A
# non-platform service on the same host still carves to AUTO.
want POLL_PAUSE service_restart_self_protected availability nl-n8n01 "systemctl restart n8n"
want AUTO service_restart        availability nlweb01 "systemctl restart nginx"
want AUTO pod_rollout_restart    resource     nlk8s01 "kubectl rollout restart deploy/api"
want AUTO scale_up               resource     nlk8s01 "kubectl scale deploy/api --replicas=3"
want AUTO pod_delete_reschedule  resource     nlk8s01 "kubectl delete pod web-xyz"
want AUTO fstrim                 resource     nl-gpu01 "fstrim -av /"
want AUTO cert_renew             certificate  nlweb01 "certbot renew"
want AUTO stale_lock_rm          generic      nlapp01 "rm -f /var/run/app.pid"
want AUTO journal_vacuum         resource     nlapp01 "journalctl --vacuum-size=500M"

# ── destructive siblings / irreversible -> POLL_PAUSE ────────────────────────
want POLL_PAUSE service_disable      availability nl-n8n01 "systemctl disable n8n"
want POLL_PAUSE etcd_stateful_deny   resource     nlk8s01 "kubectl rollout restart sts/etcd"
want POLL_PAUSE postgres_stateful    resource     nlk8s01 "kubectl rollout restart deploy/postgres-primary"
want POLL_PAUSE delete_pvc           resource     nlk8s01 "kubectl delete pvc data-0"
want POLL_PAUSE docker_volume_prune  resource     nl-gpu01 "docker volume prune -f"
want POLL_PAUSE scale_to_zero        resource     nlk8s01 "kubectl scale deploy/api --replicas=0"
want POLL_PAUSE mkfs_irreversible    resource     nl-gpu01 "mkfs.ext4 /dev/sdb1"
want POLL_PAUSE certbot_revoke       certificate  nlweb01 "certbot revoke --cert-name x"

# ── co-occurrence: carve must NOT un-protect an irreversible ─────────────────
want POLL_PAUSE cooccur_rollout_and_deletepvc resource nlk8s01 \
  "kubectl rollout restart deploy/api; kubectl delete pvc data-0"

# ── guest reboot = reversible power-cycle -> AUTO; host reboot stays HITL ─────
want AUTO       guest_reboot_nonp0   resource nlvm99   "qm reboot 101"
want AUTO       guest_reboot_pct     resource nlapp01  "pct reboot 105"
want POLL_PAUSE host_reboot          resource nlapp01  "reboot"
want POLL_PAUSE guest_plus_destroy   resource nlvm99   "qm reboot 101; qm destroy 102"
want POLL_PAUSE guest_plus_hostreboot resource nlvm99  "qm reboot 101
reboot"
want POLL_PAUSE qm_reset_hard        resource nlvm99   "qm reset 101"
want POLL_PAUSE guest_reboot_stateful resource nlk8s01 "qm reboot 101 # etcd member vm"
want POLL_PAUSE guest_multi_semicolon resource nlk8s01 "qm reboot 101; qm reboot 102; qm reboot 103"
want POLL_PAUSE guest_reboot_loop     resource nlk8s01 'for i in 101 102 103; do qm reboot $i; done'
want POLL_PAUSE guest_reboot_bare     resource nl-gpu01 "qm reboot"
want AUTO       guest_reboot_2space   resource nl-gpu01 "qm  reboot 101"

# host reboot hidden in a non-command step field (description/action/hint) must NOT be
# superseded — the executing session reads those fields too (adversarial CRITICAL-1).
start_test "host_reboot_in_step_description"
  band=$(python3 -c "import json;print(json.dumps({'hypothesis':'fix','hostname':'nl-gpu01','steps':[{'command':'qm reboot 101','description':'then reboot the host for the kernel update'}]}))" \
    | env GATEWAY_DB="$TESTDB" INFRAGRAPH_DISABLED=1 AUTONOMY_FORWARD=1 CONSERVATIVE_REMEDIATION=1 \
      python3 "$CLS" --category resource --no-audit 2>/dev/null \
    | python3 -c "import json,sys;print(json.load(sys.stdin).get('band'))")
  assert_eq POLL_PAUSE "$band" "host_reboot_in_step_description"
end_test

# guest reboot where the HYPOTHESIS prose says "reboot" must still reach AUTO (the word
# in prose is not a host-reboot command) — the regression this fix targets.
start_test "guest_reboot_prose_says_reboot"
  band=$(python3 -c "import json;print(json.dumps({'hypothesis':'VM frozen — reboot the guest to recover','hostname':'nl-gpu01','steps':[{'command':'qm reboot VMID_REDACTED'}]}))" \
    | env GATEWAY_DB="$TESTDB" INFRAGRAPH_DISABLED=1 AUTONOMY_FORWARD=1 CONSERVATIVE_REMEDIATION=1 \
      python3 "$CLS" --category resource --no-audit 2>/dev/null \
    | python3 -c "import json,sys;print(json.load(sys.stdin).get('band'))")
  assert_eq AUTO "$band" "guest_reboot_prose_says_reboot"
end_test

# ── P0 host conservative -> AUTO_NOTICE (parallel SMS) ───────────────────────
want AUTO_NOTICE p0_service_restart  availability nl-pve03 "systemctl restart chronyd"

# ── ADVERSARIAL: destructive sibling on a SEPARATE line / via flags / stateful ──
want POLL_PAUSE adv_restart_disable_newline availability nl-n8n01 "systemctl restart n8n
systemctl disable n8n"
want POLL_PAUSE adv_restart_disable_semicolon availability nl-n8n01 "systemctl restart n8n; systemctl disable n8n"
want POLL_PAUSE adv_restart_then_rmrf      availability nl-n8n01 "systemctl restart n8n; rm -rf /data"
want POLL_PAUSE adv_rollout_mongodb        resource nlk8s01 "kubectl rollout restart deploy/mongodb"
want POLL_PAUSE adv_rollout_elasticsearch  resource nlk8s01 "kubectl rollout restart deploy/elasticsearch"
want POLL_PAUSE adv_rollout_vault_sts      resource nlk8s01 "kubectl rollout restart sts/vault"
want POLL_PAUSE adv_rollout_kafka          resource nlk8s01 "kubectl rollout restart deploy/kafka-broker"
want POLL_PAUSE adv_scale_consul           resource nlk8s01 "kubectl scale sts/consul --replicas=1"
want POLL_PAUSE adv_rm_rf_lock             generic  nlapp01 "rm -rf /var/lib/data.lock"
want POLL_PAUSE adv_delete_pod_selector    resource nlk8s01 "kubectl delete pod --selector app=broken"
want POLL_PAUSE adv_delete_pod_fieldsel    resource nlk8s01 "kubectl delete pod --field-selector status.phase=Failed"
want POLL_PAUSE adv_delete_deploy          resource nlk8s01 "kubectl delete deployment api"
want POLL_PAUSE adv_delete_pod_then_pvc    resource nlk8s01 "kubectl delete pod x
kubectl delete pvc data-0"

# ── flag-off byte-parity: sentinel OFF => restart stays POLL_PAUSE (legacy) ──
want POLL_PAUSE flagoff_restart_legacy availability nl-n8n01 "systemctl restart n8n" 0
# prune was always LOW->AUTO; carve-off must not change that
want AUTO flagoff_prune_still_auto    resource nl-gpu01 "docker image prune -af" 0
