# chzrh01vps01

**Site:** CH (Zürich)
**Provider:** iFog GmbH (CHE-137.614.651)
**Public IPv4:** 198.51.100.X/26
**Public IPv6:** 2a0c:9a40:2511:101::1917/64
**Tunnel overlay:** 10.255.X.X
**eBGP transit:** AS34927 (iFog) + AS47498 (FogIXP RS1+RS2 at FogIXP), announces 2a0c:9a40:8e20::/48
**Onboarded:** original member (pre-2026)

## Role

First edge VPS in the AS64512 anycast mesh. The most-peered VPS — sits at FogIXP and has the lowest-latency path to most major IPv6 networks.

## Services

| Service | Bind |
|---|---|
| HAProxy 2.8.16 | 198.51.100.X:80, :443 + 9 IPv6 anycast (`2a0c:9a40:8e20::1`-`::9`):80, :443 |
| FRR 10.5.1 | 8 iBGP peers + eBGP iFog (1) + FogIXP RS1+RS2 (2) |
| strongSwan 5.9.13 | 6 swanctl conns (nl, gr, no-vps, nl-freedom, no-dmz01, no-dmz02) |
| CrowdSec 1.7.6 + bouncer-iptables 0.0.34 | localhost + 0.0.0.0:6060 |
| prometheus-node-exporter 1.7.0 / frr_exporter 2023-04 / ipsec_exporter 2021-09 | :9100 / :9342 / :9536 |

## Mesh tunnels

| Conn | Peer | xfrm | /31 (chzrh) |
|---|---|---|---|
| nl | nlrtr01 (Cisco ISR 4321 Tunnel3) | xfrm-nl | 10.255.200.X |
| gr | gr-fw01 (ASA Tunnel3) | xfrm-gr | 10.255.200.X |
| no-vps | notrf01vps01 | xfrm-no | 10.255.200.X |
| nl-freedom | nl-fw01 (ASA Tunnel6) | xfrm-nl-f | 10.255.200.X |
| no-dmz01 | notrf01dmz01 | xfrm-no-dmz01 | 10.255.200.X |
| no-dmz02 | notrf01dmz02 | xfrm-no-dmz02 | 10.255.200.X |
| txhou01 | txhou01vps01 | xfrm-txhou | 10.255.200.X (added 2026-05-06) |

## Access

```bash
ssh -i ~/.ssh/one_key operator@chzrh01vps01
# sudo password = SCANNER_SUDO_PASS in claude-gateway/.env
```

## Operational gotchas

1. **Never `netplan apply` online once eBGP is established** — 241k+ kernel routes from iFog blow the netlink-enumeration timeout. Reboot to apply netplan changes.
2. **swanctl-loader.service has a charon-not-ready boot race** — fixed via `Restart=on-failure` in the unit. Without it, exit code 2 silently leaves tunnels down.
3. **charon restart does NOT reload swanctl connections.** After any charon restart or VPS reboot, verify `swanctl --list-sas` shows all conns. If not: `sudo swanctl --load-all`.

## IaC + provenance

- IaC tree: `infrastructure/nl/production/edge/vps/chzrh01vps01/`
- NetBox: device id=196, site id=5
