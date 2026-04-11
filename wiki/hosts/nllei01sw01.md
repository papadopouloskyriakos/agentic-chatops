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

**nl:native/librenms/CLAUDE.md**
- | GR monitors NL | nl-sw01, nlsynology01, 213.144.173.77, 203.0.113.X, 203.0.113.X | ping only |

**nl:native/haha/CLAUDE.md**
- **Check switch port:** `ssh nl-sw01 "show power inline Gi1/0/17"` — if no power, run `hard_reset_tubeszb_olimex.sh`.

**gateway:CLAUDE.md**
- NL ASA has dual WAN: **Freedom** (primary, 203.0.113.X + /29 subnet, PPPoE) and **xs4all** (backup, 145.53.163.13, single IP, PPPoE). Both have full S2S tunnel parity (48 crypto-map entries incl. seq 74: K8s↔GR DMZ, seq 75: mgmt↔GR DMZ; 59 NAT exemptions each). Physical path: ASA Po1.6 (VLAN 6) → nl-sw01 Gi1/0/36 (PoE 802.3af) → TP-Link TL-PoE10R splitter (802.3af only) → Genexis XGS-PON ONT (1Gbps fiber).

## Related Memory Entries

- **Dual-WAN VPN full parity (Freedom + xs4all)** (project): Both NL WANs have full S2S tunnel coverage. Freedom PPPoE outage auto-handled via xs4all failover, QoS cron, SMS alerting, and trained triage scripts.
- **NEVER SSH to nl-sw01** (feedback): Do NOT attempt SSH to nl-sw01 (10.0.181.X) — login block-for will lock out ALL management IPs including the operator's workstation.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details

*Compiled: 2026-04-09 06:19 UTC*