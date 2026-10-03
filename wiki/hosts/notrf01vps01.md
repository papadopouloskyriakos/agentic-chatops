# notrf01vps01

**Site:** NO (Sandefjord / Trondheim)
**Provider:** Terrahost / Gigahost (AS56655)
**Public IPv4:** 198.51.100.X
**Public IPv6:** 2a03:94e0:ffff:185:125:171:0:172/118
**Tunnel overlay:** 10.255.X.X
**eBGP transit:** AS56655 (Terrahost) — 2 IPv6 sessions (upstream 1 + 2), announces 2a0c:9a40:8e20::/48
**Onboarded:** original member (pre-2026)

## Role

Second edge VPS. Co-located with the active/active SaaS dmz pair (notrf01dmz01 + notrf01dmz02) at the same Gigahost facility — same IPsec mesh peer, same provider class.

## Services

| Service | Bind |
|---|---|
| HAProxy 2.8.16 | 198.51.100.X:80, :443 + 9 IPv6 anycast (`2a0c:9a40:8e20::1`-`::9`):80, :443 |
| FRR 10.5.0 | 8 iBGP peers + 2 eBGP Terrahost sessions |
| strongSwan 5.9.13 | 6 swanctl conns (nl, gr, ch, nl-freedom, no-dmz01, no-dmz02) |
| CrowdSec 1.7.6 + bouncer-iptables 0.0.34 | localhost + 0.0.0.0:6060 |
| prometheus-node-exporter / frr_exporter / ipsec_exporter | :9100 / :9342 / :9536 |

## Mesh tunnels

| Conn | Peer | xfrm | /31 (notrf01vps01) |
|---|---|---|---|
| nl | nlrtr01 (Cisco ISR 4321 Tunnel2) | xfrm-nl | 10.255.200.X |
| gr | gr-fw01 (ASA Tunnel2) | xfrm-gr | 10.255.200.X |
| ch | chzrh01vps01 | xfrm-ch | 10.255.200.X |
| nl-freedom | nl-fw01 (ASA Tunnel5) | xfrm-nl-f | 10.255.200.X |
| no-dmz01 | notrf01dmz01 | xfrm-no-dmz01 | 10.255.200.X |
| no-dmz02 | notrf01dmz02 | xfrm-no-dmz02 | 10.255.200.X |
| txhou01 | txhou01vps01 | xfrm-txhou | 10.255.200.X (added 2026-05-06) |

## Access

```bash
ssh -i ~/.ssh/one_key operator@notrf01vps01
# sudo password = SCANNER_SUDO_PASS in claude-gateway/.env
```

## Operational gotchas

1. **Never `netplan apply` online once eBGP is established** — same constraint as chzrh01vps01 (Terrahost transit also delivers full IPv6 table; 241k+ kernel routes blow netlink-enumeration).
2. **VPS interface name is `mainif`, NOT `eth0`** — Terrahost provisioning convention. swanctl xfrm interfaces are anchored to `mainif`. Don't copy chzrh's templates verbatim — must rename.
3. **NL xs4all `start_action=none` quirk** — historically the xs4all path on this VPS used `start_action=none` instead of `start`. Per the txhou onboarding plan, that quirk is NOT propagated to new VPSes. Existing config retains the original behavior.

## IaC + provenance

- IaC tree: `infrastructure/nl/production/edge/vps/notrf01vps01/`
