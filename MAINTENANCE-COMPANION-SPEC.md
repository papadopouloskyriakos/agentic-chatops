# Maintenance Companion — Implementation Spec

## Context

Copy-paste this entire file as the initial prompt for a new Claude Code session in the IaC repo (`~/gitlab/infrastructure/nl/production`). Read CLAUDE.md in that repo first for full infrastructure context.

The claude-gateway repo (`~/gitlab/n8n/claude-gateway`) has the n8n workflows, OpenClaw skills, and triage scripts. Read its CLAUDE.md too.

## Problem

Updating core infrastructure (Proxmox nodes, ASA firewall, core switch) causes alert storms. A single PVE node reboot triggers 80+ LibreNMS alerts → 80+ Matrix messages → OpenClaw triage attempts → 80+ YouTrack issues → escalation to Claude Code — all for a planned maintenance event.

There is no way to:
1. Tell the system "I'm about to reboot pve01" and have it suppress alerts intelligently
2. Monitor recovery progress during maintenance in real-time
3. Differentiate expected downtime (planned reboot) from unexpected failures (a guest that didn't come back)
4. Orchestrate rolling updates across multiple hosts (e.g., 5 PVE nodes one by one)

## What to Build

An active **maintenance companion** that runs as a Claude Code session, manages the full lifecycle of a maintenance event through conversation in Matrix.

### Flow Example — PVE Node Update

```
User:    @claude I'm updating pve01, expect reboot in 5 min
Claude:  Setting 2h maintenance window on pve01 + 83 guests (75 LXC, 8 QEMU).
         Alerts suppressed. I'll monitor recovery and report back.

[pve01 reboots]

Claude:  pve01 is back (uptime: 2min). Monitoring guest recovery...
         Running: 71/83 | Starting: 10 | Stopped: 2

Claude:  81/83 guests up. 2 remaining:
         - nlvpngw02: stopped (onboot: 0 — expected, not auto-start)
         - nlopenwebrx01: stopped (onboot: 1 — UNEXPECTED)
         Shall I investigate openwebrx01?

User:    ignore it
Claude:  OK. Clearing maintenance window on pve01 + 83 guests.
         Final: 81/83 healthy, 1 expected-stopped, 1 acknowledged-stopped.
         Ready for pve02?
```

### Flow Example — ASA Firewall Upgrade

```
User:    @claude firmware upgrade on the ASA, full network outage ~10 min
Claude:  This affects ALL 137 monitored devices. Setting maintenance on everything.
         I'll verify after reboot: WAN links, BGP peering, VPN tunnels, K8s connectivity, NFS mounts.

[ASA reboots]

Claude:  ASA is back. Post-reboot checklist:
         ✅ WAN XS4ALL — PPPoE up, public IP confirmed
         ✅ WAN Freedom — PPPoE up
         ✅ BGP 65000↔65001 — 6 Cilium peers established
         ⚠️  VPN GR site — IKE SA not established (tunnel DOWN)
         ✅ VPN NO site — tunnel up
         ✅ NAT — outbound verified
         ✅ K8s — 7/7 nodes reachable
         ✅ Synology NFS — mounts responsive

         GR VPN needs attention. Want me to check the GR side?
```

### Flow Example — Core Switch IOS-XE Upgrade

```
User:    @claude upgrading nl-sw01, all ports will bounce
Claude:  Setting maintenance on nl-sw01 + all 30 connected devices.
         Port-channels: Po1 (ASA), Po2 (syno), Po3 (pve01), Po5 (syno), Po6 (syno), Po7 (pve03).
         Expected impact: brief outage on all VLANs during reload.
         I'll verify port-channel recovery and VLAN connectivity after.

[switch reloads]

Claude:  Switch is back. Checking port-channels:
         ✅ Po1 (ASA) — 4/4 members up, trunk VLANs passing
         ✅ Po3 (pve01) — 2/2 members up, 20Gbps
         ⚠️  Po7 (pve03) — 1/2 members up (Te1/0/12 down)
         ✅ Po2, Po5, Po6 (Synology) — all up

         Te1/0/12 may need SFP reseat. Want me to check error counters?
```

## Architecture

### Components to Build

1. **`/maintenance` slash command** (`.claude/commands/maintenance.md` in IaC repo)
   - Entry point for interactive sessions
   - Instructions for Claude Code on how to handle maintenance events

2. **`scripts/maintenance-companion.sh`** (claude-gateway repo)
   - Shell script callable by Claude Code via SSH
   - Subcommands:
     - `start <hostname> <duration>` — set LibreNMS maintenance on device + dependents
     - `status` — list active maintenance windows
     - `check <hostname>` — poll device + dependents for recovery status
     - `end <hostname>` — clear maintenance, run health check, report failures
     - `deps <hostname>` — list all devices that depend on this host

3. **Dependency map** — built from existing IaC data, not hardcoded:
   - PVE hosts → guests: parse `pve/<host>/lxc/*.conf` and `pve/<host>/qemu/*.conf`
   - Switch → connected devices: parse port descriptions or use LibreNMS neighbor data
   - Firewall → everything: when ASA goes down, ALL monitored devices are affected
   - Synology → NFS/iSCSI consumers: K8s nodes (VLAN 88), Nextcloud, Docker hosts

4. **OpenClaw SOUL.md addition** — detect maintenance-related messages, escalate to Claude immediately:
   ```
   When user mentions: "updating", "rebooting", "upgrading", "firmware", "maintenance",
   "patching" for infrastructure devices → escalate to Claude Code immediately with context:
   "Maintenance event: <device> - <what user said>"
   ```

5. **Recovery monitoring** — Claude Code runs a polling loop:
   - SSH to PVE host: `pct list` / `qm list` for guest status
   - LibreNMS API: `GET /api/v0/devices/<hostname>` for device status
   - kubectl: `get nodes` for K8s node recovery
   - Ping: basic reachability for network devices
   - Post progress updates to Matrix every 30-60s

### LibreNMS API Reference

```bash
# Set maintenance window
POST /api/v0/devices/:hostname/maintenance
Body: {"title": "Planned update", "duration": "2:00", "notes": "User-initiated via maintenance companion"}

# Check maintenance status
GET /api/v0/devices/:hostname/maintenance

# Get device status (for recovery check)
GET /api/v0/devices/:hostname

# List all devices (for dependency mapping)
GET /api/v0/devices

# Acknowledge alert (for stragglers)
PUT /api/v0/alerts/:id
Body: {"state": 2, "note": "Maintenance window"}
```

API key: in `.env` as `LIBRENMS_API_KEY`
Base URL: `https://nl-nms01.example.net` (self-signed cert, use `-k` / `verify=False`)

### Dependency Map Sources

| Dependency Type | Source | How to Parse |
|----------------|--------|-------------|
| PVE host → LXC guests | `pve/<host>/lxc/*.conf` | Extract `hostname:` from each .conf |
| PVE host → QEMU guests | `pve/<host>/qemu/*.conf` | Extract `name:` from each .conf |
| Switch → all | Hardcode: when `nl-sw01` goes down, set maintenance on ALL devices | Everything is behind the switch |
| Firewall → all | Hardcode: when `nl-fw01` goes down, set maintenance on ALL devices | Everything routes through ASA |
| Synology → K8s | Parse NFS exports + iSCSI targets from synology CLAUDE.md | K8s nodes on VLAN 88 |
| K8s control plane → cluster | If ctrlr node goes down, K8s may degrade | Monitor `kubectl get nodes` |

### Post-Reboot Verification Checklists

**PVE node:**
- [ ] PVE host SSH reachable
- [ ] PVE web UI responding (port 8006)
- [ ] All `onboot: 1` guests running (`pct list` / `qm list`)
- [ ] Flag `onboot: 0` guests as expected-stopped
- [ ] K8s nodes on this host: `kubectl get nodes` shows Ready
- [ ] Ceph/ZFS healthy (if applicable)

**ASA firewall:**
- [ ] SSH reachable
- [ ] WAN interfaces up: `show interface ip brief` (PPPoE on Po1.2, Po1.6)
- [ ] BGP established: `show bgp summary` (6 Cilium peers on VLAN 85)
- [ ] VPN tunnels: `show crypto ikev2 sa` (GR, NO, CH sites)
- [ ] NAT working: curl test from inside
- [ ] DHCP serving: `show dhcpd binding` (7 scopes)

**Core switch:**
- [ ] SSH reachable
- [ ] All port-channels up: `show etherchannel summary`
- [ ] Spanning-tree converged: `show spanning-tree summary`
- [ ] All VLANs present: `show vlan brief`
- [ ] Error counters: `show interfaces counters errors`

**Synology NAS:**
- [ ] SSH reachable
- [ ] RAID status: `/proc/mdstat` (all [UU...])
- [ ] Volumes mounted: `df -h /volume1 /volume2`
- [ ] NFS exports active: `showmount -e localhost`
- [ ] iSCSI targets (syno01): check sessions active
- [ ] K8s PVCs: `kubectl get pvc -A` (all Bound)

### Infrastructure Reference

| Host | Role | PVE Guests | Impact of Reboot |
|------|------|-----------|------------------|
| nl-pve01 | Primary PVE (i9-12900H, 96GB) | 75 LXC + 8 QEMU (incl. K8s ctrl01, node01, node02) | K8s loses 1 control plane + 2 workers |
| nl-pve02 | Secondary PVE (**VM on nl-nas01**, Ryzen, 16GB) | 7 LXC (incl. K8s ctrl02) | K8s loses 1 control plane. **syno01 reboot kills pve02 too.** |
| nl-pve03 | Tertiary PVE (i9-14900K, 128GB) | 34 LXC + 14 QEMU (incl. K8s ctrl03, node03, node04) | K8s loses 1 control plane + 2 workers |
| nl-fw01 | Core firewall (ASA 5508-X) | — | ALL network connectivity lost |
| nl-sw01 | Core switch (Catalyst 3850) | — | ALL wired connectivity lost |
| nl-nas01 | Primary NAS (DS1621+) | **nl-pve02 VM** + K8s iSCSI LUNs | K8s iSCSI PVCs go read-only, NFS hangs, **pve02 + 7 guests die** |
| nl-nas02 | Secondary NAS (DS1513+) | — | Frigate/Viseron NFS mounts hang |

### K8s Rolling Update Considerations

When updating PVE nodes that host K8s VMs:
- **Never reboot pve01 and pve03 simultaneously** — would lose 2/3 control plane nodes (etcd quorum lost)
- **Safe order:** pve02 first (only ctrl02, 4GB, least critical) → pve01 → pve03
- **Between reboots:** Verify `kubectl get nodes` shows all nodes Ready, pods rescheduled
- **etcd quorum:** Need 2/3 members healthy at all times. Losing 2 = cluster down.

### Tone

Active, concise, proactive. Report progress without being asked. Flag unexpected issues clearly. Don't ask for confirmation on read-only checks — just do them. DO ask before clearing maintenance windows or making changes.

### Definition of Done

- [ ] `/maintenance` slash command works in the IaC repo
- [ ] `scripts/maintenance-companion.sh` handles start/status/check/end/deps
- [ ] Dependency map built from IaC repo configs (not hardcoded hostnames)
- [ ] LibreNMS maintenance windows set/cleared via API
- [ ] Recovery monitoring loop posts progress to Matrix
- [ ] Post-reboot checklists run automatically per device type
- [ ] OpenClaw SOUL.md updated to detect and escalate maintenance conversations
- [ ] Tested with a real PVE node reboot (start with pve02 — least guests, least risk)
