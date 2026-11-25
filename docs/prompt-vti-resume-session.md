# Resume Prompt: VTI Migration Finalization & E2E Testing

## Context

On 2026-04-09, a major VTI migration was completed (IFRNLLEI01PRD-381/382/383). Crypto-map based S2S VPN on both Cisco ASA 5508-X firewalls was replaced with route-based VTI tunnels. VPS strongSwan migrated from ipsec.conf to swanctl.conf with XFRM interfaces. BGP transit overlay is live with 17 site subnets injected into iBGP.

**Current state:** VTI tunnels UP on all 3 NL tunnels + all 3 GR tunnels. Cross-site connectivity (NL↔GR) verified at 50ms. VPS→NL/GR mgmt pings working. PVE cluster quorate. Freedom ISP still down (irrelevant — VTI works over xs4all).

## Immediate Tasks (Priority Order)

### 1. Matrix Backend — TCP Unreachable from VPS

**Symptom:** HAProxy on NO VPS (198.51.100.X) reports `nl-matrix` backend DOWN. TCP 443 to 10.0.X.X (Matrix server on NL DMZ) times out from VPS.

**What works:** ICMP ping works (34ms). Other DMZ services on same subnet work (.10:9443 has 23KB flowing, .12:443 has 5.7KB).

**What we know:**
- VPS source IP is 10.255.200.X (XFRM interface IP on xfrm-nl)
- NL ASA `show conn` shows the TCP connection: `TCP vti-no 10.255.200.X:42348 dmz_servers02 10.0.X.X:443, flags SaAB` — SYN forwarded, awaiting SYN-ACK
- NL ASA packet-tracer from vti-no to 10.0.X.X:443 shows Action: allow
- The SYN reaches the Matrix server but the SYN-ACK doesn't return
- Other services on the SAME DMZ subnet work fine from VPS

**Investigation path:**
1. SSH to the Matrix server (10.0.X.X) and check:
   - `ip route` — does it have a route for 10.255.200.X/24? (its default gw is the NL ASA 10.0.X.X, which should route via VTI)
   - `iptables -L -n` — any firewall rules blocking 10.255.200.x?
   - `ss -tlnp | grep 443` — is the service listening?
   - `tcpdump -i any host 10.255.200.X and port 443 -c 10` — are SYNs arriving? Are SYN-ACKs being sent?
2. If the Matrix server IS sending SYN-ACKs, the issue is the return path through the ASA
3. If the Matrix server is NOT sending SYN-ACKs, it's a local firewall/service issue on .11

### 2. Inter-VPS Tunnel (NO↔CH)

**Symptom:** `NO_PROPOSAL_CHOSEN` when CH VPS tries to initiate `no-vps` connection to NO VPS.

**Investigation:**
- Compare ESP proposals between NO VPS `ch` child and CH VPS `no-vps` child in their swanctl.conf
- Both should use `esp_proposals = aes256-sha256` and `proposals = aes256-sha256-modp2048`
- Check if the issue is IKE proposal or ESP proposal mismatch
- The NO→CH direction works (NO VPS `ch` connection ESTABLISHED) — only CH→NO fails

### 3. LibreNMS Self-Healing Scripts

**Status:** Both disabled (NL service_id=34, GR service_id=16).

**Task:** Rewrite `/usr/lib/nagios/plugins/clear_sa_simple.sh` on both NMS instances:
- Old: `clear crypto isakmp sa` + `clear crypto ipsec sa` + `clear crypto ikev2 sa` (nukes ALL SAs)
- New: targeted VTI SA clear — `clear crypto ipsec sa peer <PEER_IP>` or bounce tunnel interface
- Then re-enable services via LibreNMS API: `curl -sk -X PATCH "${URL}/api/v0/services/${ID}" -H "X-Auth-Token: ${KEY}" -d '{"service_disabled": 0}'`

### 4. XFRM Persistence Testing

**Task:** Reboot each VPS and verify `swanctl-loader.service` correctly:
1. Creates XFRM interfaces with correct device name (NO: `mainif`, CH: `eth0`)
2. Adds IP addresses
3. Loads swanctl connections
4. VTI tunnels re-establish automatically

### 5. E2E Failover Testing

**Task:** Verify the BGP transit overlay actually provides failover:

1. **Test 1 — Direct tunnel failure:**
   - From NO VPS: `sudo swanctl --terminate --ike gr --uri unix:///var/run/charon.vici`
   - Wait 90s for BGP to converge (DPD 30s + hold 90s)
   - Verify NO VPS can still reach GR subnets (via NL transit: NO→xfrm-nl→NL ASA→vti-gr→GR)
   - Restore: `sudo swanctl --initiate --child gr --uri unix:///var/run/charon.vici`

2. **Test 2 — ASA-to-ASA tunnel failure:**
   - On NL ASA: `clear crypto ikev2 sa 203.0.113.X` (kills NL↔GR VTI)
   - Verify NL hosts can still reach GR via VPS transit (NL→vti-no→NO VPS→xfrm-gr→GR)
   - Wait for auto-recovery via DPD restart

3. **Test 3 — Full site isolation:**
   - Shut down NL ASA Tunnel1 (vti-gr): `interface Tunnel1` → `shutdown`
   - Verify all cross-site traffic routes via VPS transit
   - Restore: `no shutdown`

4. **Test 4 — Cilium ClusterMesh:**
   - During any failover test, verify `kubectl get nodes` on both clusters
   - Check Cilium ClusterMesh status: `cilium clustermesh status`

### 6. Orphaned Config Cleanup (ONLY after all tests pass)

- Remove unbound crypto-map entries from both ASAs (56 on NL, ~40 on GR)
- Remove 118 NAT exemptions (59 per WAN)
- Remove associated ACLs (`outside_freedom_cryptomap_*`, etc.)
- Remove OOB NAT (port 2222 on GR ASA) — or keep as permanent OOB
- `write memory` on both ASAs

## Key Reference

| Item | Value |
|------|-------|
| NL ASA | operator@10.0.181.X (legacy ssh-rsa) |
| GR ASA | via grclaude01 Netmiko: `/tmp/netmiko-venv/bin/python3`, host 10.0.X.X |
| GR OOB | `ssh -p 2222 -i ~/.ssh/one_key app-user@203.0.113.X` → grclaude01 |
| NO VPS | `ssh -i ~/.ssh/one_key operator@198.51.100.X` (mainif, not eth0) |
| CH VPS | `ssh -i ~/.ssh/one_key operator@198.51.100.X` (eth0) |
| VPS sudo | `REDACTED_PASSWORD` |
| swanctl | `swanctl --uri unix:///var/run/charon.vici` (always pass --uri) |
| Critical fix | `port_nat_t = 0` in `/etc/strongswan.conf` — NAT-T breaks ASA VTI |
| Rollback | Rebind crypto-maps: `crypto map outside_freedom_map interface outside_freedom` etc. |
| Memory | `memory/vti_migration_20260409.md` |
| Postmortem | `docs/postmortem-freedom-pppoe-20260408.md` |
| Plan | `docs/prompt-bgp-transit-overlay.md` |
| YT Issues | IFRNLLEI01PRD-381, 382, 383 |
| LibreNMS disabled | NL service_id=34, GR service_id=16 |
