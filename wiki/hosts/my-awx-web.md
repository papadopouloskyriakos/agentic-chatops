# my-awx-web

**Site:** NL (Leiden)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-03-25 | PodCrashLoopBackOff | AWX Postgres PVC (postgres-15-my-awx-postgres-15-0) was dele | Fix: cleared PV claimRef (Released→Available), recreated PVC | 0.9 |

## Lessons Learned

- **IFRGRSKG01PRD-115**: PERC H710P uses BBU not CacheVault. perccli /c0/cv returns not found (wrong command). Use /c0/bbu show all. BBU presence means WriteBack cache is safe. Do not assume missing CacheVault = no battery.
- **IFRGRSKG01PRD-115**: AWX Postgres PVC recovery: if PVC is deleted but PV has Retain policy, data is safe. Fix: clear PV claimRef (kubectl patch --type json), recreate PVC with volumeName, delete pod. Also check postgresql.conf listen_addresses and remove stale postmaster.pid.

## Related Memory Entries

- **yt_triage_alert_remediation_20260625** (project): 2026-06-25 YouTrack triage (8 issues closed with evidence) + the IFRNLLEI01PRD-1408 commit-label mislabel finding + active-alert remediation (in progress).

*Compiled: 2026-07-03 04:30 UTC*