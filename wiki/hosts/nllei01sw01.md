# nl-sw01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-sw01 | Catalyst 3850 | IOS-XE 16.12 | 10.0.181.X | NAPALM | Core L2 switch, 7 port-channels |
- ssh nl-sw01 "show interface Gi1/0/24 status"
- ssh nl-sw01 "show interface Gi1/0/24 | include admin|line protocol"
- python3 /home/app-user/scripts/network-check.py nl-sw01 "show interface Gi1/0/24 status"
- python3 /home/app-user/scripts/network-check.py nl-sw01 "show interface Gi1/0/24"

**nl:network/CLAUDE.md**
- | nl-sw01 | Catalyst 3850-12X48U | IOS-XE 16.12 | 10.0.181.X | Core L2 switch, 7 port-channels, 13+ VLANs | NAPALM |
- │   ├── Switch/             # nl-sw01
- **nl-sw01 (Catalyst 3850-12X48U, IOS-XE 16.12):**

**nl:native/haha/CLAUDE.md**
- **Check switch port:** `ssh nl-sw01 "show power inline Gi1/0/17"` — if no power, run `hard_reset_tubeszb_olimex.sh`.

## Related Memory Entries

- **Autonomous chaos-port-shutdown primitive + Freedom-ONT drill** (project): scripts/chaos-port-shutdown.py runs the full Freedom-ONT drill unattended — shut sw01 port, observe, PoE-recycle restore, write chaos_experiments row. First unattended run 2026-04-23 08:00 CEST. Replaces the manual operator-nudge flow.
- **Dual-WAN VPN full parity (Freedom + xs4all)** (project): Both NL WANs have full S2S tunnel coverage. Freedom PPPoE outage auto-handled via xs4all failover, QoS cron, SMS alerting, and trained triage scripts.
- **Cisco IaC — device is the source of truth, don't file-edit ahead** (feedback): Cisco configs under infrastructure/nl/production/network/configs/ (NL) and .../gr/production/network/oxidized/ (GR) are captured by a GitLab CI drift-sync job (`auto_detect_and_sync_drift`, schedule `*/30`) that netmiko-SSHes each device, normalises the output, and pushes to main as "GitLab CI Auto-Sync". Apply changes to the live device first, then let the job sync them to git. Don't open human MRs that edit the file before the live change exists. (Oxidized was decoupled from gitops 2025-11-23 — still runs on both oxidized01/02 hosts as an independent local-filesystem backup tier, but no longer pushes to GitLab. See docs/runbooks/oxidized-role.md per IFRNLLEI01PRD-701.)
- **lib/devices.py expects CISCO_PASSWORD; nl-claude01 has CISCO_ASA_PASSWORD** (feedback): For ad-hoc netmiko queries against NL Cisco gear, alias CISCO_ASA_PASSWORD into CISCO_PASSWORD before calling lib.devices helpers
- **Never reuse an existing channel-group number when adding a new LACP bundle** (feedback): P0 rule — always `show etherchannel summary` first; reusing an existing Po number modifies the existing bundle's config AND absorbs new members into it, which can cut the production path that the existing bundle carries.
- **NEVER SSH to nl-sw01** (feedback): Do NOT attempt SSH to nl-sw01 (10.0.181.X) — login block-for will lock out ALL management IPs including the operator's workstation.
- **freedom-ont-drill-trigger installer — manual, one-shot** (reference): Who schedules the Freedom-ONT failover drill, and why it's manual-by-design rather than cron/AWX-driven
- **Freedom ONT (Genexis XGS-PON) requires forced PoE re-detect after long down** (feedback): Plain `no shutdown` on sw01 Gi1/0/36 after a long Freedom-down window is not enough — the ONT loses PON training and needs `power inline never` → `power inline auto` + `shut`/`no shut` to cold-boot cleanly. 2026-04-22 recovery exercise.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.

*Compiled: 2026-05-06 00:48 UTC*