#!/usr/bin/env bash
# 2026-05-14 — Drift-check that ZFS Direct I/O is disabled on every NL+GR PVE host.
#
# Background: OpenZFS 2.3 changed default `direct=` from `disabled` to `standard`,
# which races with QEMU cache=none/aio=io_uring qcow2 writes — guest buffer mutation
# during ZFS DMA verify causes EIO → qcow2 maps to ENOSPC → VM paused (io-error).
# Memory: gpu01_zfs_dio_race_root_cause_20260514.md
# Feedback: feedback_zfs_dio_must_be_disabled_on_pve.md
#
# Usage: ./scripts/check-zfs-dio-disabled.sh
# Exit 0 if all PVE hosts have direct=disabled + zfs_dio_enabled=0.
# Exit 1 if any host has drifted; prints diagnostic.

set -u

SSH_KEY="${SSH_KEY:-$HOME/.ssh/one_key}"
SSH_OPTS=(-i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o LogLevel=ERROR)

# host:pool pairs to check (host with no ZFS pool can be omitted; we still check
# the runtime kernel param everywhere zfs.ko is loaded).
declare -A POOLS=(
  [nl-pve01]="rpool"
  [nl-pve02]=""        # no ZFS pool (uses different storage)
  [nl-pve03]="rpool"
  [nlpve04]="rpool"
  [gr-pve01]="rpool"
  [gr-pve02]="ssd-pool"
)

drift=0
echo "ZFS DIO drift-check — $(date -Iseconds)"
echo "================================"
for host in "${!POOLS[@]}"; do
  pool="${POOLS[$host]}"
  printf "%-15s " "$host"

  # Probe both: dataset property + runtime kernel param.
  out=$(ssh "${SSH_OPTS[@]}" root@"$host" "
    if [ -n '$pool' ]; then
      d=\$(zfs get -H -o value direct '$pool' 2>/dev/null || echo 'POOL_MISSING')
    else
      d='no-pool'
    fi
    e=\$(cat /sys/module/zfs/parameters/zfs_dio_enabled 2>/dev/null || echo 'NO_ZFS_MODULE')
    m=\$(test -f /etc/modprobe.d/zfs-dio-disable.conf && echo 'present' || echo 'MISSING')
    echo \"\$d|\$e|\$m\"
  " 2>&1)

  IFS='|' read -r direct dio_enabled modprobe <<<"$out"

  ok=1
  [ -n "$pool" ] && [ "$direct" != "disabled" ] && ok=0
  [ "$dio_enabled" != "0" ] && ok=0
  [ "$modprobe" != "present" ] && ok=0

  if [ $ok -eq 1 ]; then
    printf "OK     direct=%s zfs_dio_enabled=%s modprobe=%s\n" "$direct" "$dio_enabled" "$modprobe"
  else
    printf "DRIFT  direct=%s zfs_dio_enabled=%s modprobe=%s (pool=%s)\n" \
      "$direct" "$dio_enabled" "$modprobe" "${pool:-none}"
    drift=$((drift + 1))
  fi
done

echo
if [ $drift -gt 0 ]; then
  echo "FAIL: $drift host(s) drifted from the safe ZFS DIO config."
  echo "Re-apply with:"
  echo "  ssh root@<host> 'zfs set direct=disabled <pool>; echo 0 > /sys/module/zfs/parameters/zfs_dio_enabled'"
  echo "  ssh root@<host> 'cat > /etc/modprobe.d/zfs-dio-disable.conf << EOF"
  echo "options zfs zfs_dio_enabled=0"
  echo "EOF'"
  exit 1
fi
echo "PASS: all PVE hosts have ZFS DIO disabled."
exit 0
