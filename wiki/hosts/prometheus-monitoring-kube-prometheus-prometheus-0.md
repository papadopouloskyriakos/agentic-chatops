# prometheus-monitoring-kube-prometheus-prometheus-0

**Site:** NL (Leiden)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-03-25 | PrometheusTSDBCompactionsFailing | GR iSCSI server (gr-pve02) ZFS ssd-pool: 19 zvols on sin | ZFS tunables applied: txg_timeout=2 (was 5), dirty_data_max= | 0.9 |

## Lessons Learned

- **IFRGRSKG01PRD-113**: GR iSCSI I/O errors trace to gr-pve02 ZFS ssd-pool: single RAID1 SSD pair, 19 zvols, sync=disabled, 61% fragmentation. TXG flush storms are the mechanism. Tunables applied: txg_timeout=2, dirty_data_max=2GB, async_write_max_active=5. No SLOG slot available.

*Compiled: 2026-04-11 14:13 UTC*