# prometheus-monitoring-kube-prometheus-prometheus-0

**Site:** NL (Leiden)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-03-25 | PrometheusTSDBCompactionsFailing | GR iSCSI server (gr-pve02) ZFS ssd-pool: 19 zvols on sin | ZFS tunables applied: txg_timeout=2 (was 5), dirty_data_max= | 0.9 |

## Lessons Learned

- **IFRGRSKG01PRD-113**: GR iSCSI I/O errors trace to gr-pve02 ZFS ssd-pool: single RAID1 SSD pair, 19 zvols, sync=disabled, 61% fragmentation. TXG flush storms are the mechanism. Tunables applied: txg_timeout=2, dirty_data_max=2GB, async_write_max_active=5. No SLOG slot available.

## Related Memory Entries

- **health_audit_20260629** (project): "2026-06-29 agentic-system + orchestrator health audit. System GREEN (holistic 93%, 0 fail); 1 open item nlk8s-ctrl02 saturation; HolisticHealthFailing flaps; 3 empty tables=dormant features; audit methodology."
- **orchestrator_control_plane_20260626** (project): ACTIVE build of the agentic orchestrator/control-plane epic IFRNLLEI01PRD-1421 (3 bricks). Operator overrode the A-on-all gate ("begin the orchestrator, don't stop until I'm back"). Brick 1 (component registry) DONE+deploying; Bricks 2/3 next.

*Compiled: 2026-07-03 04:30 UTC*