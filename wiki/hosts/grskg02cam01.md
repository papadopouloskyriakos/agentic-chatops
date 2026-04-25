# gr2cam01

**Site:** GR (Skagkia)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Device Down! Due to no ICMP response. - Critical Alert. |  | Resolved via Claude session IFRGRSKG01PRD-165 | 0.8 |
| 2026-04-03 | Device Down! Due to no ICMP response. - Critical Alert. |  | Resolved via Claude session IFRGRSKG01PRD-163 | 0.9 |

## Lessons Learned

- **IFRGRSKG01PRD-163**: gr2cam01 ICMP down — same pattern as IFRGRSKG01PRD-161/165. GR camera goes offline during network events. Low priority unless sustained >30 min.
- **IFRGRSKG01PRD-165**: Recurring gr2cam01 ICMP down alerts correlate with GR ASA reboots or VPN drops. Camera is on VLAN behind GR switch. Check GR ASA/switch status first.

*Compiled: 2026-04-11 14:13 UTC*