# Implement iBGP Transit Overlay for S2S VPN Failover

## YouTrack Issues
- IFRNLLEI01PRD-381 — Phase 1: ASA route injection + FRR RR-client fix
- IFRNLLEI01PRD-382 — Phase 2: FRR local-preference tuning
- IFRNLLEI01PRD-383 — Phase 3: ASA VTI + VPS strongSwan XFRM migration

## Background

The 4-site IPsec full mesh (NL, GR, NO, CH) and iBGP mesh (AS 65000, 6 FRR nodes + 2 ASAs) are fully operational. Currently the iBGP only carries Cilium K8s pod /32 routes — no site subnet routes. When a direct tunnel fails, there is no automatic failover. The Freedom ISP outage on 2026-04-08 proved this is a critical gap.

Both ASAs are Cisco ASA 5508-X running **ASA 9.16(4)**. Both already have `same-security-traffic permit inter-interface` and `intra-interface` enabled. Both already run `router bgp 65000` with iBGP peers (FRR LXCs on DMZ) and eBGP peers (Cilium K8s workers on AS 65001).

VPS run strongSwan 5.9.13 + FRR 10.5.3 on Ubuntu 24.04.

### Audit Findings (2026-04-09)

1. **ASA 9.16(4) BGP:** `prefix-list`, `route-map`, `network`, `next-hop-self`, `neighbor route-map out` — all confirmed supported. `network` requires matching RIB entry. Source: Cisco ASA 9.16 config guides.
2. **ASA 9.16(4) VTI:** Supported. `interface Tunnel`, `tunnel mode ipsec ipv4`, `tunnel protection ipsec profile` — confirmed. Source: Cisco ASA 9.16 VPN guide.
3. **Original Phase 3 flaw:** `0.0.0.0/0` traffic selectors in swanctl.conf WILL NOT WORK with ASA crypto-maps. ASA only narrows to one CHILD_SA per crypto-map ACL entry — remaining subnet pairs get no SA. Cisco bugs CSCue42170, CSCvh19648.
4. **FRR RR-client gap:** NL ASA (10.0.X.X) is NOT configured as `route-reflector-client` on NL-FRR01/02. Injected routes won't propagate to VPS/GR without this fix.
5. **LibreNMS self-healing:** CHECK & CLEAR S2S TUNNEL services (NL id=34, GR id=16) SSH to ASAs and run `clear crypto ipsec sa` when pings fail. Must be disabled during migration.

---

## Phase 0a: OOB SSH Path to GR Site

**Why:** VTI migration requires unbinding crypto-maps from WAN interfaces — kills the S2S VPN that provides SSH access to the GR ASA. Need an alternative path.

**GR ASA (gr-fw01) — via current VPN access before migration:**

```
! Create ACL permitting only Freedom public IP
access-list TEMP_SSH_IN extended permit tcp host 203.0.113.X host 203.0.113.X eq ssh

! NAT port 22 on public IP to grclaude01
object network TEMP_SSH_CLAUDE01
 host 10.0.X.X
 nat (inside_mgmt,outside_inalan) static interface service tcp ssh ssh

! Add to outside_inalan ACL (or create inline)
! Verify existing ACL name on outside_inalan interface first:
!   show run access-group | include outside_inalan
! Then add the permit rule to that ACL

write memory
```

**Verify OOB path:**
```bash
# From nl-claude01:
ssh -o StrictHostKeyChecking=no operator@203.0.113.X
# Should land on grclaude01 (10.0.X.X)
# Then from there:
ssh -o HostKeyAlgorithms=+ssh-rsa -o KexAlgorithms=+diffie-hellman-group14-sha1 operator@10.0.X.X
# Should reach gr-fw01
```

**Cleanup (post-migration):** Remove the NAT object, ACL entry. `write memory`.

---

## Phase 0b: Disable LibreNMS Self-Healing Scripts

**Why:** The CHECK & CLEAR S2S TUNNEL services will `clear crypto ipsec sa` on the ASAs if cross-site pings fail during migration. This would nuke all SAs mid-transition.

**Scripts on both NMS instances:**
- `check_tunnels` (Perl) — pings remote site 50x, if all fail → calls `clear_sa_simple.sh`
- `clear_sa_simple.sh` (Bash) — SSHes to ASA with sshpass, runs `clear crypto isakmp sa` + `clear crypto ipsec sa` + `clear crypto ikev2 sa`

**NL LibreNMS (nl-nms01):**
- Service ID 34, device_id 70, type "tunnels"
- Pings 10.0.X.X (GR mgmt) 50x → clears nl-fw01 SAs on failure

**GR LibreNMS (gr-nms01):**
- Service ID 16, device_id 58, type "tunnels"
- Pings 10.0.181.X (NL sw01) 50x → clears gr-fw01 SAs on failure

**Disable via LibreNMS API:**
```bash
# NL
curl -sk -X PATCH "${LIBRENMS_URL}/api/v0/services/34" \
  -H "X-Auth-Token: ${LIBRENMS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"service_disabled": 1}'

# GR
curl -sk -X PATCH "${LIBRENMS_GR_URL}/api/v0/services/16" \
  -H "X-Auth-Token: ${LIBRENMS_GR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"service_disabled": 1}'
```

**Re-enable post-migration** after rewriting `clear_sa_simple.sh` for VTI-aware SA clearing.

---

## Phase 1: Route Injection on ASAs (IFRNLLEI01PRD-381)

**Goal:** Advertise site subnets into iBGP so the FRR route-reflectors propagate them across the mesh.

### Step 1a: Fix FRR Route-Reflector Client Config

**Why:** The NL ASA (10.0.X.X) is a regular iBGP peer on NL-FRR01/02, NOT a route-reflector-client. Routes learned from the ASA won't be reflected to VPS or GR-FRR peers. Same issue likely on GR side.

**NL-FRR01 (pct exec VMID_REDACTED on nl-pve01) and NL-FRR02 (pct exec VMID_REDACTED on nl-pve03):**
```
vtysh
conf t
router bgp 65000
 address-family ipv4 unicast
  neighbor 10.0.X.X route-reflector-client
 exit-address-family
exit
exit
write memory
```

**GR-FRR01 and GR-FRR02:** Same pattern — add `neighbor <GR-ASA-IP> route-reflector-client`. Verify GR ASA peer IP first with `show bgp summary` on GR-FRR01.

### Step 1b: Verify RIB on ASAs

**Why:** The `network` command only advertises subnets that exist in the routing table.

```
! On NL ASA:
show route | include 10.0.181.X|10.0.X.X|10.0.X.X|10.0.X.X|10.0.X.X|10.0.X.X|10.0.X.X|10.0.X.X
! All should show as "C" (connected). If any missing, add: route NULL0 <network> <mask>

! On GR ASA:
show route | include 10.0.X.X|10.0.X.X|10.0.58.X|10.0.188.X|10.0.X.X|10.0.X.X|10.0.X.X|10.0.X.X|10.0.X.X
```

### Step 1c: NL ASA Route Injection

**NL ASA (nl-fw01) — SSH as `operator@10.0.181.X`:**

```
conf t

prefix-list NL_SITE_SUBNETS seq 10 permit 10.0.181.X/24
prefix-list NL_SITE_SUBNETS seq 20 permit 10.0.X.X/27
prefix-list NL_SITE_SUBNETS seq 30 permit 10.0.X.X/24
prefix-list NL_SITE_SUBNETS seq 40 permit 10.0.X.X/27
prefix-list NL_SITE_SUBNETS seq 50 permit 10.0.X.X/29
prefix-list NL_SITE_SUBNETS seq 60 permit 10.0.X.X/27
prefix-list NL_SITE_SUBNETS seq 70 permit 10.0.X.X/24
prefix-list NL_SITE_SUBNETS seq 80 permit 10.0.X.X/27

route-map BLOCK_SITE_TO_CILIUM deny 10
 match ip address prefix-list NL_SITE_SUBNETS
route-map BLOCK_SITE_TO_CILIUM permit 20

router bgp 65000
 address-family ipv4 unicast
  network 10.0.181.X mask 255.255.255.0
  network 10.0.X.X mask 255.255.255.224
  network 10.0.X.X mask 255.255.255.0
  network 10.0.X.X mask 255.255.255.224
  network 10.0.X.X mask 255.255.255.248
  network 10.0.X.X mask 255.255.255.224
  network 10.0.X.X mask 255.255.255.0
  network 10.0.X.X mask 255.255.255.224
  neighbor 10.0.X.X next-hop-self
  neighbor 10.0.X.X next-hop-self
  neighbor 10.0.X.X route-map BLOCK_SITE_TO_CILIUM out
  neighbor 10.0.X.X route-map BLOCK_SITE_TO_CILIUM out
  neighbor 10.0.X.X route-map BLOCK_SITE_TO_CILIUM out
  neighbor 10.0.X.X route-map BLOCK_SITE_TO_CILIUM out

end
write memory
```

### Step 1d: GR ASA Route Injection

**GR ASA (gr-fw01) — via stepping stone `ssh -i ~/.ssh/one_key root@gr-pve01`, then `ssh operator@10.0.X.X`:**

```
conf t

prefix-list GR_SITE_SUBNETS seq 10 permit 10.0.X.X/24
prefix-list GR_SITE_SUBNETS seq 20 permit 10.0.X.X/27
prefix-list GR_SITE_SUBNETS seq 30 permit 10.0.58.X/24
prefix-list GR_SITE_SUBNETS seq 40 permit 10.0.188.X/27
prefix-list GR_SITE_SUBNETS seq 50 permit 10.0.X.X/29
prefix-list GR_SITE_SUBNETS seq 60 permit 10.0.X.X/27
prefix-list GR_SITE_SUBNETS seq 70 permit 10.0.X.X/28
prefix-list GR_SITE_SUBNETS seq 80 permit 10.0.X.X/27
prefix-list GR_SITE_SUBNETS seq 90 permit 10.0.X.X/27

route-map BLOCK_SITE_TO_CILIUM deny 10
 match ip address prefix-list GR_SITE_SUBNETS
route-map BLOCK_SITE_TO_CILIUM permit 20

router bgp 65000
 address-family ipv4 unicast
  network 10.0.X.X mask 255.255.255.0
  network 10.0.X.X mask 255.255.255.224
  network 10.0.58.X mask 255.255.255.0
  network 10.0.188.X mask 255.255.255.224
  network 10.0.X.X mask 255.255.255.248
  network 10.0.X.X mask 255.255.255.224
  network 10.0.X.X mask 255.255.255.240
  network 10.0.X.X mask 255.255.255.224
  network 10.0.X.X mask 255.255.255.224
  neighbor 10.0.X.X next-hop-self
  neighbor 10.0.X.X next-hop-self
  neighbor 10.0.58.X route-map BLOCK_SITE_TO_CILIUM out
  neighbor 10.0.58.X route-map BLOCK_SITE_TO_CILIUM out
  neighbor 10.0.58.X route-map BLOCK_SITE_TO_CILIUM out

end
write memory
```

### Verify Phase 1

On both VPS: `sudo vtysh -c 'show bgp ipv4 unicast'` — should now show all NL + GR site subnets with multiple paths.

On NL ASA: `show bgp ipv4 unicast neighbors 10.0.X.X advertised-routes` — should NOT contain site subnets (blocked by BLOCK_SITE_TO_CILIUM).

---

## Phase 2: FRR Local-Preference Tuning (IFRNLLEI01PRD-382)

**Goal:** Direct paths preferred (LP 200) over reflected/transit paths (LP 100 default).

**NL-FRR01 and NL-FRR02:**
```
vtysh
conf t
route-map LOCAL_PREF_HIGH permit 10
 set local-preference 200
exit
router bgp 65000
 address-family ipv4 unicast
  neighbor 10.0.X.X route-map LOCAL_PREF_HIGH in
 exit-address-family
exit
exit
write memory
```

**GR-FRR01 and GR-FRR02:**
```
vtysh
conf t
route-map LOCAL_PREF_HIGH permit 10
 set local-preference 200
exit
router bgp 65000
 address-family ipv4 unicast
  neighbor <GR-ASA-IP> route-map LOCAL_PREF_HIGH in
 exit-address-family
exit
exit
write memory
```

### Verify Phase 2

On CH VPS: `sudo vtysh -c 'show bgp ipv4 unicast 10.0.X.X/27'` — should show 2 paths: one with LP 200 (best, via GR-FRR direct) and one with LP 100 (via NL-FRR reflected).

---

## Phase 3: ASA VTI + VPS XFRM Migration (IFRNLLEI01PRD-383)

**IMPORTANT:** Phase 0a (OOB SSH) and Phase 0b (disable LibreNMS scripts) MUST be completed before starting Phase 3.

### Step 3a: Create VTI Tunnels on ASAs (Additive — Crypto-Maps Stay Active)

**NL ASA (nl-fw01):**
```
conf t

! IPsec proposal for VTI
crypto ipsec ikev2 ipsec-proposal VTI-PROPOSAL
 protocol esp encryption aes-256
 protocol esp integrity sha-256

! IPsec profile
crypto ipsec profile VTI-PROFILE
 set ikev2 ipsec-proposal VTI-PROPOSAL

! VTI to GR ASA
interface Tunnel1
 nameif vti-gr
 ip address 10.255.200.0 255.255.255.254
 tunnel source interface outside_freedom
 tunnel destination 203.0.113.X
 tunnel mode ipsec ipv4
 tunnel protection ipsec profile VTI-PROFILE

! VTI to NO VPS
interface Tunnel2
 nameif vti-no
 ip address 10.255.200.2 255.255.255.254
 tunnel source interface outside_freedom
 tunnel destination 185.125.171.172
 tunnel mode ipsec ipv4
 tunnel protection ipsec profile VTI-PROFILE

! VTI to CH VPS
interface Tunnel3
 nameif vti-ch
 ip address 10.255.200.4 255.255.255.254
 tunnel source interface outside_freedom
 tunnel destination 185.44.82.32
 tunnel mode ipsec ipv4
 tunnel protection ipsec profile VTI-PROFILE

end
write memory
```

**GR ASA (gr-fw01) — via OOB SSH path:**
```
conf t

crypto ipsec ikev2 ipsec-proposal VTI-PROPOSAL
 protocol esp encryption aes-256
 protocol esp integrity sha-256

crypto ipsec profile VTI-PROFILE
 set ikev2 ipsec-proposal VTI-PROPOSAL

! VTI to NL ASA
interface Tunnel1
 nameif vti-nl
 ip address 10.255.200.1 255.255.255.254
 tunnel source interface outside_inalan
 tunnel destination 203.0.113.X
 tunnel mode ipsec ipv4
 tunnel protection ipsec profile VTI-PROFILE

! VTI to NO VPS
interface Tunnel2
 nameif vti-no
 ip address 10.255.200.6 255.255.255.254
 tunnel source interface outside_inalan
 tunnel destination 185.125.171.172
 tunnel mode ipsec ipv4
 tunnel protection ipsec profile VTI-PROFILE

! VTI to CH VPS
interface Tunnel3
 nameif vti-ch
 ip address 10.255.200.8 255.255.255.254
 tunnel source interface outside_inalan
 tunnel destination 185.44.82.32
 tunnel mode ipsec ipv4
 tunnel protection ipsec profile VTI-PROFILE

end
write memory
```

**Note:** VTI tunnel-groups and IKEv2 policies may need to be created/updated to match the existing tunnel-group configs. Verify with `show run tunnel-group` on both ASAs before applying.

### Step 3b: Unbind Crypto-Maps (Instant Rollback Available)

**NL ASA:**
```
conf t
no crypto map outside_freedom_map interface outside_freedom
no crypto map outside_xs4all_map interface outside_xs4all
end
write memory
```

**GR ASA (via OOB):**
```
conf t
no crypto map outside_inalan_map interface outside_inalan
end
write memory
```

**Rollback (if VTI fails):**
```
conf t
crypto map outside_freedom_map interface outside_freedom
crypto map outside_xs4all_map interface outside_xs4all
end
```

All crypto-map entries, ACLs, and NAT exemptions remain in the running config — rebinding reactivates them instantly.

### Step 3c: VPS strongSwan XFRM Migration

**Do NO VPS (notrf01vps01) first, then CH.**

SSH: `ssh -i ~/.ssh/one_key operator@185.125.171.172`

1. Backup current config:
```bash
sudo cp /etc/ipsec.conf /etc/ipsec.conf.bak.pre-vti
sudo cp /etc/ipsec.secrets /etc/ipsec.secrets.bak.pre-vti
```

2. Configure charon for route-based VPN:
```bash
sudo tee /etc/strongswan.d/charon/route-based.conf << 'EOF'
charon {
    install_routes = no
    install_virtual_ip = no
}
EOF
```

3. Create `/etc/swanctl/conf.d/vti.conf`:
```
connections {
    nl {
        local_addrs = 185.125.171.172
        remote_addrs = 203.0.113.X
        local { auth = psk id = 185.125.171.172 }
        remote { auth = psk id = 203.0.113.X }
        version = 2
        dpd_delay = 30s
        children {
            nl {
                local_ts = 0.0.0.0/0
                remote_ts = 0.0.0.0/0
                esp_proposals = aes256-sha256
                if_id_in = 1
                if_id_out = 1
                start_action = start
                dpd_action = restart
            }
        }
        proposals = aes256-sha256-modp2048
    }
    gr {
        local_addrs = 185.125.171.172
        remote_addrs = 203.0.113.X
        local { auth = psk id = 185.125.171.172 }
        remote { auth = psk id = 203.0.113.X }
        version = 2
        dpd_delay = 30s
        children {
            gr {
                local_ts = 0.0.0.0/0
                remote_ts = 0.0.0.0/0
                esp_proposals = aes256-sha256
                if_id_in = 2
                if_id_out = 2
                start_action = start
                dpd_action = restart
            }
        }
        proposals = aes256-sha256-modp2048
    }
    ch {
        local_addrs = 185.125.171.172
        remote_addrs = 185.44.82.32
        local { auth = psk id = 185.125.171.172 }
        remote { auth = psk id = 185.44.82.32 }
        version = 2
        dpd_delay = 30s
        children {
            ch {
                local_ts = 0.0.0.0/0
                remote_ts = 0.0.0.0/0
                esp_proposals = aes256-sha256
                if_id_in = 3
                if_id_out = 3
                start_action = start
                dpd_action = restart
            }
        }
        proposals = aes256-sha256-modp2048
    }
}
secrets {
    ike-nl { id = 203.0.113.X secret = "PSK_HERE" }
    ike-gr { id = 203.0.113.X secret = "PSK_HERE" }
    ike-ch { id = 185.44.82.32 secret = "PSK_HERE" }
}
```

**Note:** `0.0.0.0/0` TS now works because both sides are VTI/route-based. The ASA VTI also uses wildcard TS by default.

4. Create XFRM interfaces (persist via `/etc/network/interfaces.d/xfrm`):
```bash
sudo ip link add xfrm-nl type xfrm dev eth0 if_id 1
sudo ip link add xfrm-gr type xfrm dev eth0 if_id 2
sudo ip link add xfrm-ch type xfrm dev eth0 if_id 3
sudo ip addr add 10.255.200.3/31 dev xfrm-nl
sudo ip addr add 10.255.200.7/31 dev xfrm-gr
sudo ip addr add 10.255.100.5/31 dev xfrm-ch
sudo ip link set xfrm-nl up
sudo ip link set xfrm-gr up
sudo ip link set xfrm-ch up
```

5. Stop old ipsec, start swanctl:
```bash
sudo ipsec stop
sudo swanctl --load-all
```

6. UFW: allow forwarding between XFRM interfaces:
```bash
sudo ufw route allow in on xfrm-gr out on xfrm-nl
sudo ufw route allow in on xfrm-nl out on xfrm-gr
sudo ufw route allow in on xfrm-ch out on xfrm-nl
sudo ufw route allow in on xfrm-nl out on xfrm-ch
```

**Repeat for CH VPS (chzrh01vps01, 185.44.82.32) with adjusted IPs.**

### Step 3d: Update FRR BGP Peering

FRR on VPS nodes may need to peer with ASAs over the new VTI /31 addresses instead of the DMZ IPs. Or keep existing peering via FRR RRs (which are on the DMZ and still reachable via VTI). Evaluate after VTI tunnels are up.

---

## Phase 4: Post-Migration Cleanup

### 4a: Rewrite LibreNMS Self-Healing Scripts

Update `clear_sa_simple.sh` on both NMS instances to clear VTI-specific SAs:
```bash
# Instead of:
#   clear crypto isakmp sa
#   clear crypto ipsec sa
#   clear crypto ikev2 sa
# Use targeted:
#   clear crypto ipsec sa peer <PEER_IP>
# Or bounce the tunnel interface:
#   shutdown interface Tunnel1 / no shutdown interface Tunnel1
```

### 4b: Re-enable LibreNMS Services
```bash
# NL
curl -sk -X PATCH "${LIBRENMS_URL}/api/v0/services/34" \
  -H "X-Auth-Token: ${LIBRENMS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"service_disabled": 0}'

# GR
curl -sk -X PATCH "${LIBRENMS_GR_URL}/api/v0/services/16" \
  -H "X-Auth-Token: ${LIBRENMS_GR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"service_disabled": 0}'
```

### 4c: Remove Temporary OOB NAT+ACL from GR ASA

### 4d: Clean Up Orphaned Crypto-Map Config (ONLY after VTI is stable)
- Remove all `crypto map outside_freedom_map` entries (seq 1-75)
- Remove all `crypto map outside_xs4all_map` entries (seq 1-75)
- Remove 118 NAT exemptions (59 per WAN)
- Remove associated ACLs (`outside_freedom_cryptomap_*`, `outside_xs4all_cryptomap_*`)
- Same on GR ASA for `outside_inalan_map`

---

## E2E Verification

After all phases:

1. **Route check:** From CH VPS, `show bgp ipv4 unicast 10.0.X.X/27` — should show 2 paths (direct LP 200, transit LP 100)
2. **Tunnel check:** `show crypto ipsec sa` on both ASAs — VTI SAs established, traffic flowing
3. **Normal path:** From CH VPS, `traceroute 10.0.X.X` — should go direct via xfrm-gr to GR
4. **Simulate failure:** On CH VPS, `sudo swanctl --terminate --ike gr` to kill the CH→GR tunnel
5. **Wait ~90s** for BGP to converge (DPD 30s + BGP hold 90s)
6. **Failover path:** From CH VPS, `traceroute 10.0.X.X` — should now transit via xfrm-nl (NL backbone)
7. **Restore:** `sudo swanctl --initiate --ike gr` — direct path should resume within seconds
8. **Cilium check:** On K8s nodes, `kubectl get nodes` — ClusterMesh should be unaffected
9. **LibreNMS check:** CHECK & CLEAR S2S TUNNEL services healthy on both NMS instances

## Important Notes
- ASAs use legacy ssh-rsa: `ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa`
- GR ASA normally accessed via stepping stone through gr-pve01; during Phase 3, use OOB path via grclaude01
- VPS sudo password: `REDACTED_PASSWORD`
- **Rollback:** Rebind crypto-maps to WAN interfaces — instant restore, all entries still in config
- The existing `prefix-list METALLB-VIPS` on NL ASA is defined but not applied — don't remove it
- VTI tunnel-groups: verify existing IKEv2 configs (`show run tunnel-group`, `show run crypto ikev2`) before creating VTI tunnels — may need to reuse or adjust existing tunnel-group settings
- NL ASA has dual WAN — VTI `tunnel source` should use Freedom (primary). Consider adding xs4all VTI tunnels as backup after initial deployment is stable
