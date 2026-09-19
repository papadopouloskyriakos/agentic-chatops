#!/usr/bin/env bash
# IFRNLLEI01PRD-1408 — blind-spot closures + gate-governed network/container tier.
#
# Operator risk-appetite decision 2026-06-25 (docs/risk-appetite.md):
#   - Network / firewall / BGP / AWX + Cisco conf-t + service/container stop -> GATE-GOVERNED
#     (AUTO_NOTICE when the territory gate is live; POLL_PAUSE when it is not).
#   - gh/glab deploy+delete, sed-i/tee into /etc -> HELD (never gate-relaxed).
#   - zfs rollback / zpool offline + catastrophic Cisco (write erase / no ip routing) -> floor.
#   - percona/proxysql/graylog added to the stateful denylist.
#   - flag-OFF stays byte-identical (no band keys); benign reads stay AUTO.
# Hermetic: INFRAGRAPH_DISABLED=1, temp DB, sentinels pinned via env (never the live files).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1408-blindspot-network"
CLS="$REPO_ROOT/scripts/classify-session-risk.py"
TESTDB="$(mktemp --suffix=.db)"
GATE_ON="$TESTDB.gate-on"; : > "$GATE_ON"          # territory gate LIVE
GATE_OFF="$TESTDB.gate-off"                          # territory gate ABSENT
HR_OFF="$TESTDB.hr-off"                              # host-reboot appetite off (no interference)
trap 'rm -f "$TESTDB" "$GATE_ON"' EXIT

# band <command> <gate-sentinel> [AF=1] -> prints the band (or "none")
band() {
  local cmd="$1" gate="$2" af="${3:-1}"
  printf '{"hypothesis":"remediate the alert","hostname":"nlapp01","steps":[{"command":"%s"}]}' "$cmd" | \
    env GATEWAY_DB="$TESTDB" INFRAGRAPH_DISABLED=1 AUTONOMY_FORWARD="$af" \
        TERRITORY_GATE_SENTINEL="$gate" HOST_REBOOT_AUTO_SENTINEL="$HR_OFF" \
        python3 "$CLS" --category availability --no-audit 2>/dev/null | \
    python3 -c "import json,sys;print(json.load(sys.stdin).get('band','none'))"
}

# ─── Gate-governable tier: AUTO_NOTICE when gate LIVE, POLL_PAUSE when absent ───────
for spec in \
  "conf_t|conf t" \
  "copy_run_start|copy running-config startup-config" \
  "send_config_set|conn.send_config_set(['ip access-list extended X'])" \
  "iptables|iptables -A INPUT -s 1.2.3.4 -j DROP" \
  "asa_clear_crypto|clear crypto ikev2 sa" \
  "awx_launch|curl awx.example -X POST /api/v2/job_templates/5/launch/" \
  "service_stop|service nginx stop" \
  "podman_stop|podman stop web" \
  "lxc_stop|lxc stop ct1" ; do
  name="${spec%%|*}"; cmd="${spec#*|}"
  start_test "gate_governed_${name}_auto_notice_when_live"
    assert_eq AUTO_NOTICE "$(band "$cmd" "$GATE_ON")" "$name -> AUTO_NOTICE when territory gate live"
  end_test
  start_test "gate_governed_${name}_poll_pause_when_absent"
    assert_eq POLL_PAUSE "$(band "$cmd" "$GATE_OFF")" "$name -> POLL_PAUSE when territory gate absent"
  end_test
done

# ─── HELD floor: POLL_PAUSE even with the gate LIVE ────────────────────────────────
for spec in \
  "gh_pr_merge|gh pr merge 42 --squash" \
  "glab_mr_merge|glab mr merge 7" \
  "gh_api_delete|gh api -X DELETE /repos/o/r/git/refs/heads/x" \
  "gh_release|gh release create v1.2.3" \
  "sed_i_etc|sed -i s/a/b/ /etc/resolv.conf" \
  "tee_etc|echo x | tee /etc/hosts" \
  "dd_etc|dd if=/dev/zero of=/etc/sysctl.conf" \
  "zfs_rollback|zfs rollback rpool/data@snap" \
  "zpool_offline|zpool offline rpool nvme2n1" \
  "write_erase|write erase" \
  "no_ip_routing|no ip routing" \
  "conf_t_plus_write_erase|conf t; write erase" ; do
  name="${spec%%|*}"; cmd="${spec#*|}"
  start_test "held_floor_${name}_poll_pause_even_with_gate"
    assert_eq POLL_PAUSE "$(band "$cmd" "$GATE_ON")" "$name -> POLL_PAUSE (floor, gate cannot relax)"
  end_test
done

# ─── Benign reads stay AUTO (no false-positive holds) ──────────────────────────────
start_test "benign_gh_pr_view_auto"
  assert_eq AUTO "$(band "gh pr view 42" "$GATE_ON")" "gh pr view (read) -> AUTO"
end_test
start_test "benign_kubectl_get_auto"
  assert_eq AUTO "$(band "kubectl get pods -A -o wide" "$GATE_ON")" "kubectl get (read) -> AUTO"
end_test
start_test "benign_show_run_auto"
  assert_eq AUTO "$(band "show running-config | include access-list" "$GATE_ON")" "show run (read) -> AUTO"
end_test

# ─── Flag-OFF byte-identical: no band key for any new pattern ──────────────────────
for spec in "conf_t|conf t" "gh_merge|gh pr merge 42" "zfs_rollback|zfs rollback p@s" "podman_stop|podman stop web"; do
  name="${spec%%|*}"; cmd="${spec#*|}"
  start_test "flag_off_${name}_no_band"
    assert_eq none "$(band "$cmd" "$GATE_ON" 0)" "$name with AUTONOMY_FORWARD=0 -> legacy (no band)"
  end_test
done

# ─── Stateful denylist additions held when gate absent ─────────────────────────────
for w in percona proxysql graylog; do
  start_test "stateful_deny_${w}_rollout_restart_held"
    out=$(printf '{"hypothesis":"restart","hostname":"nlapp01","steps":[{"command":"kubectl rollout restart sts/%s-0"}]}' "$w" | \
      env GATEWAY_DB="$TESTDB" INFRAGRAPH_DISABLED=1 AUTONOMY_FORWARD=1 CONSERVATIVE_REMEDIATION=1 \
          TERRITORY_GATE_SENTINEL="$GATE_OFF" HOST_REBOOT_AUTO_SENTINEL="$HR_OFF" \
          python3 "$CLS" --category availability --no-audit 2>/dev/null | \
      python3 -c "import json,sys;print(json.load(sys.stdin).get('band','none'))")
    assert_eq POLL_PAUSE "$out" "rollout-restart $w -> POLL_PAUSE (stateful deny, gate off)"
  end_test
done
