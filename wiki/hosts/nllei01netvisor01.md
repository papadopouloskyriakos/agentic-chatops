# nlnetvisor01

**Site:** NL (Leiden)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Devices up/down. |  | Resolved via Claude session IFRNLLEI01PRD-231 | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-231**: Single-host Devices up/down alerts (nlnetvisor01, nlmealie01, nl-librespeed01, nlmyspeed01, nlhpb01) are typically transient — LXC/VM restart or brief network blip. Check PVE host load if clustered. Self-recovers in <5 min.

*Compiled: 2026-05-06 00:48 UTC*