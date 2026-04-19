# gr2sw01

**Site:** GR (Skagkia)

## Knowledge Base References

**gr:network/CLAUDE.md**
- | gr2sw01 | Switch | — | Remote rack switch |
- │   │   └── gr2sw01

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Device Down! Due to no ICMP response. - Critical Alert. |  | Resolved via Claude session IFRGRSKG01PRD-161 | 0.8 |

## Lessons Learned

- **IFRGRSKG01PRD-161**: GR devices (gr2cam01 camera, gr2sw01 switch) go offline during cross-site VPN drops or GR ASA reboots. If NL ASA also rebooting, correlate with scheduled event. If isolated, check GR power/network path.

*Compiled: 2026-04-11 14:13 UTC*