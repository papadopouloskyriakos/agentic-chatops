# Incident Timeline

> 33 incidents recorded. Compiled 2026-04-11 14:13 UTC.

| Date | Host | Site | Alert | Root Cause | Issue | Confidence |
|------|------|------|-------|------------|-------|------------|
| 2026-04-10 | [nl-fw01](../hosts/nl-fw01.md) | NL | BGP peer down — Freedom VTI to GR (10.255.200.X) | Freedom VTI tunnel (Tunnel4) is down. Check: show  |  | 0.9 |
| 2026-04-10 | [nl-fw01](../hosts/nl-fw01.md) | NL | xs4all VTI tunnel UP but zero ESP traffic (Bytes Rx: 0) | EXPECTED BEHAVIOR. ASA tunnel source interface doe |  | 1.0 |
| 2026-04-10 | [nl-fw01](../hosts/nl-fw01.md) | NL | Cross-site corosync/NFS blackhole after BGP route change | Stale ASA connection table entries from old forwar |  | 0.9 |
| 2026-04-10 | [gr-fw01](../hosts/gr-fw01.md) | GR | BGP peer down — Freedom VTI to NL (10.255.200.X) | NL ASA Freedom VTI tunnel is down. GR ASA sees BGP |  | 0.9 |
| 2026-04-10 | [nl-fw01](../hosts/nl-fw01.md) | NL | Freedom ISP PPPoE down — full BGP failover | Freedom PPPoE died. SLA track 1 detects in ~15s. D |  | 0.9 |
| 2026-04-08 | [nl-fw01](../hosts/nl-fw01.md) | NL | Service up/down | Freedom ISP PPPoE session dropped. ASA outside_fre | IFRNLLEI01PRD-381 | 1.0 |
| 2026-04-08 | [gr-pve01](../hosts/gr-pve01.md) | GR | Devices up/down | GR devices showing down from NL LibreNMS perspecti | IFRNLLEI01PRD-381 | 0.9 |
| 2026-04-08 | [nl-pve01](../hosts/nl-pve01.md) | NL | Service up/down | Multiple NL hosts showing Service up/down during F | IFRNLLEI01PRD-381 | 0.9 |
| 2026-04-03 | [nl-pve01](../hosts/nl-pve01.md) | NL | Port status up/down. |  | IFRNLLEI01PRD-282 | 0.9 |
| 2026-04-03 | [nlprotonmail-bridge01](../hosts/nlprotonmail-bridge01.md) | NL | Device rebooted. |  | IFRNLLEI01PRD-280 | 0.9 |
| 2026-04-03 | [nl-iot02](../hosts/nl-iot02.md) | NL | Service up/down. |  | IFRNLLEI01PRD-260 | 0.9 |
| 2026-04-03 | [nlcl01iot01](../hosts/nlcl01iot01.md) | NL | Device rebooted. |  | IFRNLLEI01PRD-259 | 0.9 |
| 2026-04-03 | [nlmealie01](../hosts/nlmealie01.md) | NL | Devices up/down. |  | IFRNLLEI01PRD-232 | 0.9 |
| 2026-04-03 | [nlnetvisor01](../hosts/nlnetvisor01.md) | NL | Devices up/down. |  | IFRNLLEI01PRD-231 | 0.9 |
| 2026-04-03 | [nl-pve02](../hosts/nl-pve02.md) | NL | Service up/down. |  | IFRNLLEI01PRD-338 | 0.8 |
| 2026-04-03 | [gr2cam01](../hosts/gr2cam01.md) | GR | Device Down! Due to no ICMP response. - Critical Alert. |  | IFRGRSKG01PRD-165 | 0.8 |
| 2026-04-03 | [gr2cam01](../hosts/gr2cam01.md) | GR | Device Down! Due to no ICMP response. - Critical Alert. |  | IFRGRSKG01PRD-163 | 0.9 |
| 2026-04-03 | [gr2sw01](../hosts/gr2sw01.md) | GR | Device Down! Due to no ICMP response. - Critical Alert. |  | IFRGRSKG01PRD-161 | 0.8 |
| 2026-04-03 | [nlnc02](../hosts/nlnc02.md) | NL | Service up/down. |  | IFRNLLEI01PRD-336 | 0.9 |
| 2026-04-03 | [nl-pve01](../hosts/nl-pve01.md) | NL | Service up/down. |  | IFRNLLEI01PRD-334 | 0.9 |
| 2026-04-03 | [nlmyspeed01](../hosts/nlmyspeed01.md) | NL | Devices up/down. |  | IFRNLLEI01PRD-323 | 0.9 |
| 2026-04-03 | [nl-librespeed01](../hosts/nl-librespeed01.md) | NL | Devices up/down. |  | IFRNLLEI01PRD-322 | 0.9 |
| 2026-04-03 | [nlhpb01](../hosts/nlhpb01.md) | NL | Devices up/down. |  | IFRNLLEI01PRD-286 | 0.8 |
| 2026-04-03 | [nl-fw01](../hosts/nl-fw01.md) | NL | Service up/down | EEM watchdog timer auto-reload | SCHEDULED-ASA-NL-001 | 0.9 |
| 2026-04-03 | [nl-fw01](../hosts/nl-fw01.md) | NL | Devices up/down | EEM watchdog timer auto-reload | SCHEDULED-ASA-NL-002 | 0.9 |
| 2026-04-03 | [gr-fw01](../hosts/gr-fw01.md) | GR | Service up/down | EEM watchdog timer auto-reload | SCHEDULED-ASA-GR-001 | 0.9 |
| 2026-03-25 | [gr-pve02](../hosts/gr-pve02.md) | GR | iSCSI I/O contention | SeaweedFS 2x500GB volume zvols on ssd-pool were th | IFRGRSKG01PRD-122 | 0.9 |
| 2026-03-25 | [nl-pve01](../hosts/nl-pve01.md) | NL | Service up/down | pve01 oversubscribed: 80% RAM (75/94GB), 7 VMs (40 | IFRNLLEI01PRD-255 | 0.9 |
| 2026-03-25 | [nlcl01iot01](../hosts/nlcl01iot01.md) | NL | Devices up/down | iot01 is VMID 666 (non-standard) on pve01. Stopped | IFRNLLEI01PRD-256 | 0.9 |
| 2026-03-25 | [nlk8s-ctrl01](../hosts/nlk8s-ctrl01.md) | NL | KubePodCrashLooping | apiserver-ctrl01 crash looping (498 restarts) is  | IFRNLLEI01PRD-257 | 0.9 |
| 2026-03-25 | [my-awx-web](../hosts/my-awx-web.md) | GR | PodCrashLoopBackOff | AWX Postgres PVC (postgres-15-my-awx-postgres-15-0 | IFRGRSKG01PRD-115 | 0.9 |
| 2026-03-25 | [prometheus-monitoring-kube-prometheus-prometheus-0](../hosts/prometheus-monitoring-kube-prometheus-prometheus-0.md) | GR | PrometheusTSDBCompactionsFailing | GR iSCSI server (gr-pve02) ZFS ssd-pool: 19 zv | IFRGRSKG01PRD-113 | 0.9 |
| 2026-03-25 | [nl-pve01](../hosts/nl-pve01.md) | NL | Service up/down | PVE swap audit: pve01 had 1GB swapfile on ZFS (dea | IFRNLLEI01PRD-255 | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-232** (2026-04-09): nlmealie01 (recipe app LXC) — transient up/down. Non-critical service, self-recovers.
- **IFRNLLEI01PRD-260** (2026-04-09): nl-iot02 — IoT device service flap. Low priority, self-recovers. See IFRNLLEI01PRD-259 lesson.
- **IFRNLLEI01PRD-280** (2026-04-09): nlprotonmail-bridge01 — container restart. Docker container auto-restarts. Check docker logs if recurring >3x/day.
- **IFRNLLEI01PRD-286** (2026-04-09): nlhpb01 (HomePlugBridge) — transient up/down. Wireless bridge device, affected by interference. Self-recovers.
- **IFRNLLEI01PRD-322** (2026-04-09): nl-librespeed01 (speed test LXC) — transient up/down. Non-critical service, self-recovers.
- **IFRNLLEI01PRD-323** (2026-04-09): nlmyspeed01 (speed test LXC) — transient up/down. Non-critical service, self-recovers. Check PVE host if sustained.
- **IFRGRSKG01PRD-163** (2026-04-09): gr2cam01 ICMP down — same pattern as IFRGRSKG01PRD-161/165. GR camera goes offline during network events. Low priority unless sustained >30 min.
- **IFRGRSKG01PRD-165** (2026-04-09): Recurring gr2cam01 ICMP down alerts correlate with GR ASA reboots or VPN drops. Camera is on VLAN behind GR switch. Check GR ASA/switch status first.
- **SCHEDULED-ASA-GR-001** (2026-04-09): GR ASA EEM watchdog reboot (~6d20h cycle). GR total outage + NL VPN tunnel drop. Cross-site alerts expected. Auto-recovery in 5-10 min. See SCHEDULED-ASA-NL-001 lesson.
- **SCHEDULED-ASA-NL-002** (2026-04-09): ASA EEM watchdog reboots cause cascading device-down alerts across all site hosts. Expected and suppressed by asa-reboot-watch.sh. Auto-recovery in 5-10 min. See SCHEDULED-ASA-NL-001 lesson.
- **IFRNLLEI01PRD-338** (2026-04-09): nl-pve02 service flaps during iSCSI storage operations or kernel module reloads. This host has the longest uptime (105+ days) and is pending kernel maintenance.
- **IFRNLLEI01PRD-336** (2026-04-09): Nextcloud (nlnc02) service up/down is often caused by PHP-FPM pool exhaustion or MariaDB connection limits. Check systemctl status php-fpm and mariadb connections.
- **IFRNLLEI01PRD-282** (2026-04-09): Port status up/down on PVE hosts typically indicates network interface flap during maintenance, storage failover, or bond reconfiguration. Check interface status and bond health.
- **IFRNLLEI01PRD-334** (2026-04-09): Service up/down on PVE hosts (pve01, pve02) during cluster operations is expected. PVE services restart during HA migration, storage maintenance, or kernel updates. Correlate with maintenance window.
- **IFRNLLEI01PRD-257** (2026-04-09): KubePodCrashLooping on apiserver nodes correlates with PVE host load spikes. Self-recovers when host load drops. Check node resource pressure (kubectl top nodes) before restarting pods.
- **IFRGRSKG01PRD-161** (2026-04-09): GR devices (gr2cam01 camera, gr2sw01 switch) go offline during cross-site VPN drops or GR ASA reboots. If NL ASA also rebooting, correlate with scheduled event. If isolated, check GR power/network path.
- **IFRNLLEI01PRD-231** (2026-04-09): Single-host Devices up/down alerts (nlnetvisor01, nlmealie01, nl-librespeed01, nlmyspeed01, nlhpb01) are typically transient — LXC/VM restart or brief network blip. Check PVE host load if clustered. Self-recovers in <5 min.
- **IFRNLLEI01PRD-259** (2026-04-09): IoT devices (nlcl01iot01/02) reboot periodically — low-priority unless recurring. Protonmail bridge (nlprotonmail-bridge01) container restarts are common. These are informational alerts, not actionable.
- **SCHEDULED-ASA-NL-001** (2026-04-09): ASA EEM watchdog reboots are scheduled and expected. NL: 604800s (7d), GR: 590400s (~6d20h). Reboot times drift ~5min/cycle. All alerts during the window are suppressed by asa-reboot-watch.sh. No action needed — auto-recovery in 5-10 min.
- **IFRNLLEI01PRD-381** (2026-04-09): Freedom ISP PPPoE outages cause cascading NL+GR alerts (up/down on all NL devices + GR VPN-dependent devices). First check: show vpdn pppinterface on NL ASA. xs4all WAN takes over automatically via SLA track failover. Wait 15 min before investigating — most services self-recover.
- **IFRGRSKG01PRD-122** (2026-03-25): GR SeaweedFS volumes now on NFS/sdc (HDD), NOT iSCSI/ssd-pool. PVs: seaweedfs-volume-0-nfs, seaweedfs-volume-1-nfs. NFS export: /mnt/gr-pve02-local-ext4/seaweedfs on 10.0.188.X. Masters+filers still on iSCSI. If SeaweedFS volume pods fail, check NFS export + mount, not iSCSI.
- **IFRGRSKG01PRD-115** (2026-03-25): PERC H710P uses BBU not CacheVault. perccli /c0/cv returns not found (wrong command). Use /c0/bbu show all. BBU presence means WriteBack cache is safe. Do not assume missing CacheVault = no battery.
- **IFRNLLEI01PRD-255** (2026-03-25): NEVER use swap on ZFS (swapfile or zvol). Proxmox explicitly warns: swapoff deadlocks. pve01 proved it — swapoff hung, orphaned swap only clears on reboot. For ZFS hosts, use swap partition on physical disk outside ZFS, or no swap at all.
- **IFRGRSKG01PRD-113** (2026-03-25): GR iSCSI I/O errors trace to gr-pve02 ZFS ssd-pool: single RAID1 SSD pair, 19 zvols, sync=disabled, 61% fragmentation. TXG flush storms are the mechanism. Tunables applied: txg_timeout=2, dirty_data_max=2GB, async_write_max_active=5. No SLOG slot available.
- **IFRGRSKG01PRD-115** (2026-03-25): AWX Postgres PVC recovery: if PVC is deleted but PV has Retain policy, data is safe. Fix: clear PV claimRef (kubectl patch --type json), recreate PVC with volumeName, delete pod. Also check postgresql.conf listen_addresses and remove stale postmaster.pid.
- **IFRNLLEI01PRD-256** (2026-03-25): iot01 is VMID 666 (non-standard) on pve01. IoT cluster is 3-node Pacemaker (iot01/iot02/iotarb01) with automatic failover. Do NOT failback services — leave on current active node. SSH requires one_key + root.
- **IFRNLLEI01PRD-255** (2026-03-25): pve01 cascading failures: when pve01 load spikes (>50), expect apiserver crashes on ctrl01, iot01 VM shutdown, and service check failures across multiple hosts. Root cause is always RAM oversubscription. Check pve01 first before investigating individual alerts.

## Postmortems

- [postmortem-freedom-pppoe-20260408.md](../../docs/postmortem-freedom-pppoe-20260408.md)

*Compiled: 2026-04-11 14:13 UTC*