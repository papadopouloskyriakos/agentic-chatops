# gr2sw01

**Site:** GR (Skagkia)

## Knowledge Base References

**gr:network/CLAUDE.md**
- | gr2sw01 | Switch | **Cisco CBS 350** (cbs_ros 3.5.x) | **cisco_s300** (override) | Remote rack switch |
- **Cisco Small Business (CBS/SG) note** — `gr-sw01` and `gr2sw01` run CBS firmware, not Catalyst IOS. Two device-side prereqs for drift-sync to succeed: (a) `ip ssh password-auth` must be enabled (default off; without it the SSH server advertises no password method and paramiko can't authenticate), (b) `write memory` to persist. Client side: netmiko `cisco_s300` driver handles the ANSI-escape-wrapped prompt + `terminal datadump` paging that CBS uses. Both switches have (a)+(b) set and are listed in the `device_driver_overrides` map in `network/scripts/{detect,auto_sync}_drift.py`. When onboarding a new CBS switch, do the device-side fix first, then add to the override map. See `feedback_cisco_small_business_cbs_ssh` memory.
- │   ├── Switch/{gr-sw01,gr-sw02,gr2sw01}

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Device Down! Due to no ICMP response. - Critical Alert. |  | Resolved via Claude session IFRGRSKG01PRD-161 | 0.8 |

## Lessons Learned

- **IFRGRSKG01PRD-161**: GR devices (gr2cam01 camera, gr2sw01 switch) go offline during cross-site VPN drops or GR ASA reboots. If NL ASA also rebooting, correlate with scheduled event. If isolated, check GR power/network path.

## Related Memory Entries

- **feedback_cisco_small_business_cbs_ssh** (feedback): Cisco CBS/SG/SF ("Small Business") switches: default SSH password-auth is DISABLED + CLI has ANSI escape codes + different paging. Need device-side `ip ssh password-auth` + netmiko `cisco_s300` driver.

*Compiled: 2026-05-06 00:48 UTC*