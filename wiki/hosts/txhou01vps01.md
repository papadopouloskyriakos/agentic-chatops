# txhou01vps01

**Site:** US (Houston, TX)
**Provider:** iFog GmbH (CHE-137.614.651) — same provider as chzrh01vps01
**Public IPv4:** 185.121.169.27/25
**Public IPv6:** 2a0c:9a40:2c2c:111::199c/64
**Tunnel overlay:** 10.255.X.X
**eBGP transit:** AS34927 (iFog), announces 2a0c:9a40:8e20::/48
**Onboarded:** 2026-05-06

## Role

Third edge VPS in the AS64512 anycast mesh, mirroring chzrh01vps01 + notrf01vps01. Houston was added to give the mesh a US presence (the previous 4 sites were all EU).

## Services

| Service | Bind | Notes |
|---|---|---|
| HAProxy 2.8.16 | 185.121.169.27:80, :443 + 9 IPv6 anycast (`2a0c:9a40:8e20::1`-`::9`):80, :443 | TLS termination, SNI routing for cubeos / mulecube / withelli / meshsat / omoikane / portfolio. Backends → NL/GR DMZ via VTI. |
| FRR 10.6.1 | 9 iBGP peers + 1 eBGP iFog (IPv6 only, 241k+ prefixes received) | bgpd + bfdd. Router-id 10.255.X.X. |
| strongSwan 5.9.13 | 7 swanctl conns (nl, gr, no-vps, nl-freedom, ch, no-dmz01, no-dmz02) | All ESTABLISHED. swanctl-loader.service brings up xfrm-* interfaces on boot. |
| CrowdSec 1.7.7 + crowdsec-firewall-bouncer-iptables 0.0.34 | localhost + 0.0.0.0:6060 (Prometheus) | Enrolled to operator's CrowdSec console. |
| prometheus-node-exporter 1.7.0 | :9100 | Scraped from NL Prometheus pod (instance=txhou01vps01, site=tx). |
| frr_exporter 2023-04 | :9342 | Same — site=tx, instance=tx-edge. |
| ipsec_exporter 2021-09 | :9536 | Same. |

## Mesh tunnels

7 IPsec VTI tunnels via strongSwan/swanctl + xfrm interfaces:

| Conn | Peer | xfrm | /31 (txhou) | /31 (peer) |
|---|---|---|---|---|
| nl | nlrtr01 (Cisco ISR 4321, Tunnel6) | xfrm-nl | 10.255.200.X | 10.255.200.X |
| gr | gr-fw01 (Cisco ASA, Tunnel7) | xfrm-gr | 10.255.200.X | 10.255.200.X |
| no-vps | notrf01vps01 | xfrm-no | 10.255.200.X | 10.255.200.X |
| nl-freedom | nl-fw01 (Cisco ASA, Tunnel9) | xfrm-nl-f | 10.255.200.X | 10.255.200.X |
| ch | chzrh01vps01 | xfrm-ch | 10.255.200.X | 10.255.200.X |
| no-dmz01 | notrf01dmz01 | xfrm-no-dmz01 | 10.255.200.X | 10.255.200.X |
| no-dmz02 | notrf01dmz02 | xfrm-no-dmz02 | 10.255.200.X | 10.255.200.X |

## Access

```bash
# Always use SSH ControlMaster — iFog FastNetMon null-routes per-command SSH bursts
ssh -o ControlMaster=auto -o ControlPath=/tmp/ssh-ctrl-%r@%h:%p -o ControlPersist=10m \
    -i ~/.ssh/one_key operator@txhou01vps01

# sudo password = SCANNER_SUDO_PASS in claude-gateway/.env (same as fleet)
```

## Operational gotchas

1. **Never `netplan apply` online** once eBGP is established — the 241k+ kernel routes from iFog blow systemd-networkd's netlink-enumeration timeout. Reboot to apply netplan changes. (Per `feedback_netplan_apply_post_ebgp_blows_netlink_timeout` memory.)
2. **iFog FastNetMon null-routes** SSH-handshake floods. Use ControlMaster always; don't run tight ssh loops.
3. **mesh-stats reads txhou state from peer-side swanctl** — claude01 → txhou direct queries are blocked by FastNetMon. Status comes from each peer's swanctl conn-name `txhou01`.
4. **`/48` propagation** to upstream peers takes up to 72h after iFog accepts the announcement. Outbound from txhou's iFog `/64` source works immediately; outbound from anycast `/48` is pending propagation.

## IaC + provenance

- **IaC tree:** `infrastructure/nl/production/edge/vps/txhou01vps01/` (commit `143c15e`)
- **NetBox:** site id=7 (txhou01), device id=235, eth0 interface id=806, primary IPv4 id=579 + IPv6 id=580
- **03_Lab:** `~/Q/03_Lab/US/txhou01vps01-iFog-Houston.md`
- **Memory:** `txhou01vps01_onboarding_complete_20260506.md` (project), three feedback memories on lessons-learned
- **Status page:** 5th country site, US/transit role, 7 tunnels (commits `c0eeaba` + `4719dfd`)
- **Prometheus:** Atlantis MR !292 merged — instance=txhou01vps01 / site=tx labels
