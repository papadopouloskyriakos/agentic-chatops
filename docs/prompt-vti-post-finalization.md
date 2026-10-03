# Resume Prompt: VTI Post-Finalization Verification & Network Troubleshooting

## Context

On 2026-04-09, a marathon VTI finalization session completed:
- Dual-WAN VTI across 4 nodes (NL ASA 6 tunnels, GR ASA 4, both VPS 4 connections each)
- E2E failover testing: 4/4 pass (DPD <60s, BGP transit, floating statics instant, ClusterMesh survived)
- Crypto-map era cleanup: ~713 config lines removed from both ASAs
- Freedom ISP recovered mid-session causing ESP routing disruption
- Proxmox corosync cluster healed (stale ASA flow from crypto-map era)
- xs4all + Freedom PAT rules added for all 11 inside zones
- VPN Mesh Stats API deployed (`/webhook/mesh-stats`)
- CrowdSec whitelists + netlink buflen + UFW fixes on 8 hosts

**Current known state (end of session):**
- 9/10 NL ASA tunnels UP (Tunnel4 vti-gr-f DOWN — Freedom→GR not establishing)
- All VPS tunnels ESTABLISHED (nl, gr, ch/no-vps, nl-freedom)
- Corosync: 5/5 nodes
- Freedom ISP: RECOVERED (default route switched back to Freedom metric 1)
- xs4all host routes for VPN peers exist on NL ASA (203.0.113.X, 198.51.100.X, 198.51.100.X via 198.51.100.X)

## Immediate Verification Tasks

### 1. Tunnel4 (vti-gr-f) — Freedom→GR not UP
NL ASA Tunnel4: `tunnel source outside_freedom`, dest 203.0.113.X. Freedom is back but this tunnel won't establish.
- Check: `show interface Tunnel4` — is Freedom interface has IP?
- Check: GR ASA has tunnel-group for 203.0.113.X (Freedom IP) — verified exists
- Try: bounce Tunnel4 (`shutdown` / `no shutdown`)
- If still down: check if GR ASA's IKE policy accepts connections from 203.0.113.X

### 2. gr-dmz01 AWX Deploy
Last AWX run failed on gr-dmz01 (unreachable during ESP SA mismatch window). 
- Retrigger AWX deploy
- Verify portfolio container running on gr-dmz01

### 3. Freedom ISP Stability Check
Freedom just recovered. Verify:
- `show interface outside_freedom` — IP assigned, line protocol up
- `show vpdn pppinterface` — PPP session stable
- `show track 1` — SLA track UP
- QoS toggle: `scripts/freedom-qos-toggle.sh` should have removed tenant QoS limits
- SMS notification: Twilio should have sent "Freedom UP" SMS

### 4. Dual-WAN NAT Completeness Audit
After-auto PAT rules were added for all zones on both Freedom and xs4all. Verify:
```
show run nat | include after-auto
```
Should show 11+ zones × 2 WANs (Freedom + xs4all) + LTE. Missing any = internet breakage on WAN failover.

### 5. GR ASA ACL Audit
The GR ASA has `deny ip any object-group nl_all_subnets` on multiple inside interfaces (dmz_servers01, inside_guest, inside_neapoli, dmz_vpn01, inside_iot, etc.). These are INTENTIONAL — they prevent inside zones from initiating connections to NL subnets. Return traffic for NL-initiated connections is allowed by stateful inspection. Do NOT remove these.

However, verify that the one deny rule I accidentally removed and restored is correctly in place:
```
show run access-list dmz_servers01_access_in | include deny.*nl_all
```

### 6. Stale Flow Check
The `clear conn all` on the NL ASA killed 6003 connections. Most re-established but some services might still be affected. Check:
- Matrix bot connectivity
- Galera replication (DMZ cross-site)
- SeaweedFS filer-sync
- LibreNMS polling to GR devices

## Key Reference

| Item | Value |
|------|-------|
| NL ASA | operator@10.0.181.X (legacy ssh-rsa, pexpect for interactive) |
| GR ASA | via grclaude01: `/tmp/netmiko-venv/bin/python3`, host 10.0.X.X |
| GR OOB | `ssh -p 2222 -i ~/.ssh/one_key app-user@203.0.113.X` |
| NO VPS | `ssh -i ~/.ssh/one_key operator@198.51.100.X` |
| CH VPS | `ssh -i ~/.ssh/one_key operator@198.51.100.X` (or ProxyJump via NO VPS) |
| VPS sudo | `REDACTED_PASSWORD` |
| swanctl | `--uri unix:///var/run/charon.vici` |
| Prometheus | `http://10.0.X.X:30090` (K8s NodePort) |
| Mesh Stats API | `GET https://n8n.example.net/webhook/mesh-stats` |
| Workflow ID | Mesh Stats: `PrcigdZNWvTj9YaL` |

## Lessons Learned (from this session)

1. **CrowdSec bans VPN peers** — IKE retransmits trigger ssh-bf. Whitelist at `/etc/crowdsec/parsers/s02-enrich/whitelist-vps.yaml`
2. **kernel-netlink buflen** — default 8KB overflows with BGP. Set 2MB. 8MB segfaults.
3. **port_nat_t = 4500** not 0 — 0 breaks VPS-to-VPS (false NAT detection)
4. **Stale ASA flows** — `clear conn` needed after VTI migration for cross-site services (corosync was blackholed)
5. **SPI mismatch** — always clear crypto on BOTH ASAs, never just one
6. **Dual-WAN PAT** — every inside zone needs PAT on BOTH outside interfaces
7. **Never mass-delete by grep** — audit each line. The cleanup missed the PAT gap.
8. **GR ASA deny ACLs are stateful** — they block new connections from DMZ→NL but allow return traffic. Don't remove them.
9. **ASA packet-tracer doesn't work on VTI interfaces** — use it on physical interfaces only
10. **Freedom recovery disrupts ESP** — when default route switches from xs4all to Freedom, ESP packets for xs4all-sourced tunnels can't route. Host routes for VPN peers on outside_xs4all fix this.
