# nllte01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nllte01 | C819G-LTE | IOS 15.6 | 10.0.X.X | NAPALM | LTE failover gateway |
- Available devices: nl-sw01, nlrtr01, nl-fw01, nllte01, nlap01-04.
- | nllte01 | 10.0.X.X | IOS | C819G-LTE | password (operator) |

**nl:network/CLAUDE.md**
- | nllte01 | C819G-LTE-MNA | IOS 15.6 | 10.0.X.X | LTE failover gateway | NAPALM |
- │   ├── Router/             # nlrtr01, nllte01
- - **LTE Failover**: Cellular0 on nllte01, NAT to 10.0.X.X/30.
- | HIGH | **No VTY access-class** | `line vty 0 4` has no `access-class` — any IP can attempt SSH. nllte01 has `access-class 23 in`. |
- **nllte01 (C819G-LTE, IOS 15.6) — LTE Failover Gateway:**

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-21 | Sensor over limit - Check Device Health Settings | recurred 6x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **agentic_state_orange_verified_20260628** (project): "2026-06-28 verified the post-benchmark 'orange' issue tier against live sources — ALL items dissolved under verification (3 agent fabrications + false_auto_resolve/demotion gap audited to 0 misfires); no code fixes warranted. MRs !123/!124 shipped + reusable Cronicle-API pattern."
- **ASA syslog timestamps are in the ASA local clock (CEST), not UTC** (feedback): Avoid 2h labelling errors when copying ASA log lines into customer/vendor emails — ASA timestamp = clock timezone setting, not UTC
- **Cisco IaC — device is the source of truth, don't file-edit ahead** (feedback): Cisco configs under infrastructure/nl/production/network/configs/ (NL) and .../gr/production/network/oxidized/ (GR) are captured by a GitLab CI drift-sync job (`auto_detect_and_sync_drift`, schedule `*/30`) that netmiko-SSHes each device, normalises the output, and pushes to main as "GitLab CI Auto-Sync". Apply changes to the live device first, then let the job sync them to git. Don't open human MRs that edit the file before the live change exists. (Oxidized was decoupled from gitops 2025-11-23 — still runs on both oxidized01/02 hosts as an independent local-filesystem backup tier, but no longer pushes to GitLab. See docs/runbooks/oxidized-role.md per IFRNLLEI01PRD-701.)
- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details

*Compiled: 2026-07-03 04:30 UTC*