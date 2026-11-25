# NL boot order and DNS resolvers (nl-pve03 + nlpve04)

Applied live on 2026-11-07, 13:28-13:40 UTC. Source: the NL power-loss postmortem, operator decision D
("both parts"). YT IFRNLLEI01PRD-2992; postmortem MR !284
(`docs/postmortem-nl-power-loss-2026-11-06.md`).

## Why

On 2026-11-06 the house mains failed and both live NL PVE hosts went down. nl-pve03 died hard; nlpve04
was halted by apcupsd. When power returned, nlpve04's guests and apps started before the DNS and the
database they need. On top of that, nlpve04 itself had a single resolver: nlfreeipa01, a guest on
the other host. This change does two things:

1. **Start order** on each host: DNS/identity first, then the DB tier, then everything else.
2. **Resolvers**: every running NL guest and both NL PVE hosts get at least 2 resolvers on different
   hosts or sites.

## Part 1: start order

How PVE uses `startup:` when `pve-guests.service` runs `startall` at host boot (only `onboot: 1` guests):

- Guests start in ascending `order`. Guests with the same `order` start in ascending VMID.
- Guests **without** an `order` start after every guest that has one.
- `up=N` = wait N seconds after this guest has started before the next guest is started.
- Ordering works **per host only**. nlpve04 cannot wait for a guest on nl-pve03. That is why each
  host has its own tier-1 resolver, and why each guest lists the resolver on its own host first.

| tier | startup | nl-pve03 | nlpve04 |
|---|---|---|---|
| 1 DNS/identity | `order=1,up=60` | nlfreeipa01 (VMID_REDACTED) | nl-pihole01 (VMID_REDACTED) |
| 2 DB | `order=2,up=30` | nlcl01mariadb02 (VMID_REDACTED), nlcl01garbd01 (VMID_REDACTED), nlproxysql02 (VMID_REDACTED), nlredis03 (VMID_REDACTED) | nlcl01mariadb01 (VMID_REDACTED), nlredis02 (VMID_REDACTED) |
| 3+ | existing orders kept | nl-gpu01 (3), then 4..24, then unordered | nl-nms01 (3), then 6..99, then unordered |

The added wait before tier 3 is 60 + 4 x 30 = 180 s on nl-pve03 and 60 + 2 x 30 = 120 s on nlpve04.
Within tier 2 the VMID order still starts nlproxysql02 after both Galera members on nl-pve03, which
its old `order=14` (after the DB at 10) also did.

Conflicts resolved (the only non-DNS/DB guests that held a tier-1 or tier-2 slot):

- **nl-gpu01** (VMID_REDACTED) `order=1` -> `order=3`. It stays the first guest after the DB tier. Its old
  first place may have been deliberate: the 32 GiB GPU-passthrough VM allocates all its RAM at start, and
  tiers 1-2 are small LXCs, so that intent is kept.
- **nl-nms01** (VMID_REDACTED) `order=2` -> `order=3`. It also keeps its early slot.

All other explicit orders (4..99) already sat after tier 2 and are unchanged. No `onboot` flag was changed.
Three stopped guests with `onboot: 0` still carry a low order and never autostart: nlopenwebui01
(VMID_REDACTED, `order=2`), nlgitea01 (VMID_REDACTED, `order=2`) and nlsemaphore01 (VMID_REDACTED,
`order=3`). If one of them is ever set `onboot: 1`, move it to `order` 4 or higher first.

**Rule for new guests:** orders 1 and 2 are reserved for DNS/identity and the DB tier. Check with
`grep -H ^startup /etc/pve/nodes/<node>/{lxc,qemu-server}/*.conf`.

## Part 2: resolvers

| IP | resolver | runs on | resolves | depends on |
|---|---|---|---|---|
| 10.0.181.X | nlfreeipa01 | nl-pve03 | internal (authoritative) + recursion | itself |
| 10.0.181.X | nl-pihole01 | nlpve04 | internal + external | upstreams are **only** 10.0.181.X and 10.0.X.X (Pi-hole v6 `dns.upstreams`) |
| 10.0.X.X | grfreeipa01 | GR | internal (authoritative replica) + recursion | the NL-GR tunnel |
| 10.0.X.X | gr-pihole01 | GR | internal + external | the NL-GR tunnel |

All four answered `nl-gitlab01.example.net` and `google.com` from inside_mgmt (VLAN 10,
10.0.181.X/24) before anything was changed.

**Rule:** at least 2 resolvers, on different hosts or sites. When a guest needs fixing, the order is:

1. the NL resolver on the guest's own host (it shares fate with the guest and starts in tier 1),
2. the NL resolver on the other host,
3. grfreeipa01 (10.0.X.X), the authoritative replica.

glibc reads at most 3 `nameserver` lines. Guests that already had a compliant pair were not touched.
The existing pairs are 181.53 + 2.14 (the Pi-hole pair) and 181.130 + 2.130 (the IPA pair).

**The hypervisors are the exception: each lists the resolver on the *other* host first.** A PVE host
boots before any of its guests, so the resolver on its own host is still down while pmxcfs, corosync
and pve-guests start. Its own-host resolver only comes up once that host's tier 1 has started. With
the other host's resolver first, a host that cold-boots alone (the other host already up) gets an
answer at the first query instead of waiting out a glibc timeout per lookup. After a full-site cold
boot neither is up yet, which is why the `/etc/hosts` self-alias (postmortem cause #1) must be correct
on every node: node-name resolution must never depend on DNS.

### What changed

| target | before | after | method |
|---|---|---|---|
| nl-pve03 (host) | 181.130, 2.130 | 181.53, 181.130, 2.130 (other host first, see the hypervisor exception above) | `pvesh set /nodes/nl-pve03/dns --search example.net --dns1 10.0.181.X --dns2 10.0.181.X --dns3 10.0.X.X` |
| nlpve04 (host) | 181.130 at the incident; 181.130, 2.130 from 11:18 UTC on 2026-11-07 (the postmortem session added `dns2`) | 181.130, 181.53, 2.130 (other host first) | `pvesh set /nodes/nlpve04/dns --search example.net --dns1 10.0.181.X --dns2 10.0.181.X --dns3 10.0.X.X` |
| nlfreeipa01 (CT VMID_REDACTED) | 127.0.0.1 | 127.0.0.1, 181.53, 2.130 | NetworkManager drop-in (below) + `pct set --nameserver` |
| nlhealthops01 (CT VMID_REDACTED) | 181.53 | 181.53, 181.130, 2.130 | `pct set --nameserver` + live resolv.conf |
| nlsec01 (VM VMID_REDACTED) | 181.53 | 181.53, 181.130, 2.130 | in-guest netplan |
| nlandroidsdk01 (VM VMID_REDACTED) | 181.53 | 181.53, 181.130, 2.130 | in-guest netplan (another session started it at 13:36 UTC, during this work) |

### How to change resolvers on an NL guest

- **LXC with a PVE-managed resolv.conf** (all NL LXCs except nlfreeipa01): run
  `pct set <id> --nameserver "a b c"`. On a running CT `nameserver` is **not** hot-pluggable. It lands in
  `[pve:pending]`, and PVE rewrites `/etc/resolv.conf` only at the next CT start. For the live effect,
  rewrite `/etc/resolv.conf` in the CT with exactly what PVE will write: one `search` line, then one
  `nameserver` line per server. No restart is needed.
- **nlfreeipa01** (Rocky 9, NetworkManager active): its resolv.conf says "Generated by NetworkManager".
  It is driven by the IPA installer's `/etc/NetworkManager/conf.d/zzz-ipa.conf`, `[global-dns-domain-*]`
  `servers=`. Edit that line (comma-separated list), then run `nmcli general reload conf` and
  `nmcli general reload dns-rc` (one flag per call on NM 1.52). Also set the pct `nameserver`, so that
  PVE's write at CT start matches. Its search domain `sec.example.net` is unchanged.
- **VM with a cloud-init drive** (nlsec01, nlandroidsdk01; also nlgitlabrunner02/03,
  nlwg01, nlpaops01): **do not change the PVE cloud-init `nameserver` field.** PVE builds the
  NoCloud instance-id as `sha1(user-data . network-data)` (`/usr/share/perl5/PVE/QemuServer/Cloudinit.pm`).
  Any change therefore makes the next boot a *new instance*: SSH host keys are regenerated, `cipassword`
  is re-applied and the per-instance modules run again. Instead:
  1. Edit `/etc/netplan/50-cloud-init.yaml` in the guest. On an ordinary boot cloud-init does not re-render
     it; `/var/log/cloud-init.log` says "No network config applied. Neither a new instance nor datasource
     network update allowed", including for the boots on 2026-11-07.
  2. Run `netplan generate && networkctl reload`, **not** `netplan apply`. `apply` forces
     `networkctl reconfigure`. `reload` reconfigures only the links whose `.network` file changed, and keeps
     their addresses: a 0.2 s ping to the gateway lost 0 of 40 packets on both VMs.
  3. Check that `/run/systemd/netif/links/<ifindex>` `DNS=` shows the new list. That proves networkd holds it,
     so a systemd-resolved restart will not revert it.

  The PVE GUI therefore still shows 10.0.181.X for VMs VMID_REDACTED and VMID_REDACTED. If those VMs' cloud-init
  settings are ever changed for another reason (which regenerates the instance anyway), set `nameserver` to
  `10.0.181.X 10.0.181.X 10.0.X.X` in the same change.
- **VM without cloud-init** (k8s nodes, nlcl01file02, nlnc01, nl-iot02): use the
  `/etc/netplan/60-vlan*.yaml` `nameservers:` block, then the same generate + reload.
- **Docker inside a guest:** a running container keeps the resolver list it was started with, and picks up
  the new list at its next restart (nlhealthops01). No container was restarted.

## Before/after tables

IPs are shortened to their last two octets: 181.130 = nlfreeipa01, 181.53 = nl-pihole01,
2.130 = grfreeipa01, 2.14 = gr-pihole01. VMs show the in-guest resolvers (systemd-resolved link
DNS), and LXCs the resolv.conf that PVE writes; all 46 LXC rows were re-checked against the live resolv.conf
after the change (0 mismatches). The tables cover guests running at about 13:40 UTC on 2026-11-07.
Excluded: nltg01 and nltgsoak01 (TG-owned), stopped guests, nl-pve01 and its guests.
nlgitlabrunner02 (VM VMID_REDACTED) was running during the survey with 181.53 + 2.14 (compliant). Another
session stopped it at 13:36 UTC, so it is not in the table.

### nl-pve03 (running guests, 28)

| VMID | Guest | Type | onboot | startup before | startup after | resolvers before | resolvers after | note |
|---|---|---|---|---|---|---|---|---|
| VMID_REDACTED | nlfreeipa01 **(order+DNS)** | CT | 1 | order=1 | order=1,up=60 | 127.0.0.1 | 127.0.0.1, 181.53, 2.130 | NM `zzz-ipa.conf` owns resolv.conf; edited + `nmcli general reload conf`/`dns-rc` |
| VMID_REDACTED | nlvaultwarden01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlnpm01 | CT | 1 | order=4 | order=4 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlstsrv01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlcl01mariadb02 **(order)** | CT | 1 | order=10,up=30 | order=2,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlcl01garbd01 **(order)** | CT | 1 | order=10,up=30 | order=2,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlproxysql02 **(order)** | CT | 1 | order=14,up=10 | order=2,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nldocuseal01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlsearxng01 | CT | 1 | order=7 | order=7 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlsmtp-gpg01 | CT | 1 | order=4 | order=4 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlsmtp-dkim01 | CT | 1 | order=4 | order=4 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nloas01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nl-matrix01 | CT | 1 | order=24,up=5 | order=24,up=5 | 1.1.1.1, 8.8.8.8 | 1.1.1.1, 8.8.8.8 | public by design: dmz_servers02, internal DNS denied by nl-fw01 |
| VMID_REDACTED | nlk8s-frr01 | CT | 1 | order=16,up=10 | order=16,up=10 | 181.53 | 181.53 | NOT fixed: nl-fw01 `dmz_servers02_access_in` allows DNS only to 181.53 |
| VMID_REDACTED | nlredis03 **(order)** | CT | 1 | order=10,up=30 | order=2,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlrenovate01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlhaproxy02 | CT | 1 | order=14,up=10 | order=14,up=10 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlk8s-openbao03 | CT | 1 | order=16,up=10 | order=16,up=10 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlk8s-frr02 | CT | 1 | order=16,up=10 | order=16,up=10 | 181.53 | 181.53 | NOT fixed: nl-fw01 `dmz_servers02_access_in` allows DNS only to 181.53 |
| VMID_REDACTED | nlk8s-haproxy02 | CT | 1 | order=16,up=10 | order=16,up=10 | 181.130, 2.130 | 181.130, 2.130 |  |
| 777 | nl-iot02 | VM | 1 | order=22,up=10 | order=22,up=10 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlgitlabrunner03 | VM | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlwg01 | VM | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlk8s-node02 | VM | 1 | order=20,up=15 | order=20,up=15 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nl-gpu01 **(order)** | VM | 1 | order=1 | order=3 | 181.53, 2.14 | 181.53, 2.14 | moved out of tier 1; still the first guest after the DB tier |
| VMID_REDACTED | nlcl01file02 | VM | 1 | order=12,up=30 | order=12,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlk8s-ctrl03 | VM | 1 | order=18,up=30 | order=18,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlk8s-node03 | VM | 1 | order=20,up=15 | order=20,up=15 | 181.130, 2.130 | 181.130, 2.130 |  |

### nlpve04 (running guests, 34)

| VMID | Guest | Type | onboot | startup before | startup after | resolvers before | resolvers after | note |
|---|---|---|---|---|---|---|---|---|
| VMID_REDACTED | nlsyslogng01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nl-gitlab01 | CT | 1 | order=24,up=5 | order=24,up=5 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlnetbox01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlatlantis01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nl-pihole01 **(order)** | CT | 1 | order=2 | order=1,up=60 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlinfluxdb01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlpbs01 | CT | 1 | order=6 | order=6 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlsyncthing01 | CT | 1 | order=6 | order=6 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlcl01mariadb01 **(order)** | CT | 1 | order=20 | order=2,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlhabitica01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nllinkwarden02 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlyoutrack01 | CT | 1 | order=24,up=5 | order=24,up=5 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nltwenty01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nl-n8n01 | CT | 1 | order=24,up=5 | order=24,up=5 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlfrigate01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlhealthops01 **(DNS)** | CT | 1 | - | - | 181.53 | 181.53, 181.130, 2.130 | `pct set` (pending to next CT start) + live resolv.conf |
| VMID_REDACTED | nloas02 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlmeshcentral01 | CT | 1 | order=24,up=5 | order=24,up=5 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlredis02 **(order)** | CT | 1 | order=10,up=30 | order=2,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlk8s-openbao02 | CT | 1 | order=16,up=10 | order=16,up=10 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nl-nms01 **(order)** | CT | 1 | order=2 | order=3 | 181.130, 2.130 | 181.130, 2.130 | moved out of tier 2; still the first guest after the DB tier |
| VMID_REDACTED | nlopenobserve01 | CT | 1 | - | - | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nl-claude01 | CT | 1 | order=24,up=5 | order=24,up=5 | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nllitellm01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlinvoiceninja01 | CT | 1 | - | - | 181.53, 181.130 | 181.53, 181.130 | two NL hosts, no GR; meets the rule |
| 201101201 | nlprotonmail-bridge01 | CT | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlandroidsdk01 **(DNS)** | VM | 0 | - | - | 181.53 | 181.53, 181.130, 2.130 | started 13:36 UTC by another session; same in-guest netplan fix as nlsec01 |
| VMID_REDACTED | nlservarr01 | VM | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |
| VMID_REDACTED | nlnc01 | VM | 1 | order=22 | order=22 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlsec01 **(DNS)** | VM | 1 | order=99 | order=99 | 181.53 | 181.53, 181.130, 2.130 | in-guest netplan + `networkctl reload`; PVE cloud-init field left at 181.53 on purpose |
| VMID_REDACTED | nl-dmz01 | VM | 1 | - | - | 1.1.1.1, 8.8.8.8 | 1.1.1.1, 8.8.8.8 | public by design: dmz_servers02, internal DNS denied by nl-fw01 |
| VMID_REDACTED | nlk8s-ctrl01 | VM | 1 | order=18,up=30 | order=18,up=30 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlk8s-node04 | VM | 1 | order=20,up=15 | order=20,up=15 | 181.130, 2.130 | 181.130, 2.130 |  |
| VMID_REDACTED | nlpaops01 | VM | 1 | - | - | 181.53, 2.14 | 181.53, 2.14 |  |

## Verification (from inside each changed guest/host, 2026-11-07 13:37-13:40 UTC)

`dig @<each listed resolver> nl-gitlab01.example.net +short` and `getent hosts google.com`:

```
nlhealthops01   181.53 -> 10.0.181.X   181.130 -> 10.0.181.X   2.130 -> 10.0.181.X   google.com -> 2a00:1450:400e:811::200e
nlfreeipa01     127.0.0.1 -> 10.0.181.X   181.53 -> 10.0.181.X   2.130 -> 10.0.181.X   google.com -> 2a00:1450:400e:811::200e
nlsec01         181.53 -> 10.0.181.X   181.130 -> 10.0.181.X   2.130 -> 10.0.181.X   google.com -> 2a00:1450:400e:811::200e
nlandroidsdk01  181.53 -> 10.0.181.X   181.130 -> 10.0.181.X   2.130 -> 10.0.181.X   google.com -> 2a00:1450:400e:811::200e
nl-pve03         181.130 -> 10.0.181.X   181.53 -> 10.0.181.X   2.130 -> 10.0.181.X   google.com -> 2a00:1450:400e:811::200e
nlpve04         181.53 -> 10.0.181.X   181.130 -> 10.0.181.X   2.130 -> 10.0.181.X   google.com -> 2a00:1450:400e:811::200e
```

The short name `getent hosts nl-gitlab01` resolves through the `example.net` search domain
everywhere except nlfreeipa01. Its search domain is `sec.example.net` (unchanged), so that was
never expected to work. `ipactl status` on nlfreeipa01 after the NM reload: all 9 services RUNNING.

## Not fixed / open

1. **nlk8s-frr01 (10.0.X.X) and nlk8s-frr02 (10.0.X.X) still have one resolver.** They
   are the NL BGP route reflectors on dmz_servers02 (VLAN 21, 10.0.X.X/27).
   - On nl-fw01, `dmz_servers02_access_in` permits DNS from them only to object `nlpihole02`
     (= host 10.0.181.X, the nl-pihole01 address; the object name is misleading). It then denies
     ip to `nl_all_subnets` and `gr_all_subnets`.
   - Live test from inside both CTs: 10.0.181.X answers; 10.0.181.X, 10.0.X.X and
     10.0.X.X time out.
   - The fix needs an ASA ACL change: an operator decision, netmiko only. For example, a TCPUDP `eq domain`
     permit from each frr object to `host 10.0.181.X` (and `host 10.0.X.X`) above the denies.
     Then run `pct set VMID_REDACTED --nameserver "10.0.181.X 10.0.181.X 10.0.X.X"` (and the
     same for VMID_REDACTED) plus the live resolv.conf.
2. **nl-pihole01 has no upstream of its own.** Its only upstreams are nlfreeipa01 and
   grfreeipa01. When nl-pve03 is down *and* the NL-GR tunnel is down (as during the power-loss
   recovery, while nl-fw01 came back), it can only answer from cache.
   - Real independence would need internal zones conditionally forwarded to both IPA servers, plus a
     separate upstream for everything else.
   - A plain public upstream is the wrong fix: it would answer internal names with NXDOMAIN.
   - This is a design decision and was not changed.
3. **nl-matrix01 and nl-dmz01 use 1.1.1.1 + 8.8.8.8.** They are on dmz_servers02, where
   nl-fw01 denies internal DNS: verified from inside, no NL resolver reachable. Two independent public
   providers meet the rule, so they were left as they are.
4. **nlinvoiceninja01 has 181.53 + 181.130**: two different NL hosts, no GR. It meets the rule and
   was left.
5. **Pending PVE config:** CTs VMID_REDACTED and VMID_REDACTED show `nameserver` in `[pve:pending]` until their next
   start. The pending value equals what is live in the guest now.
6. **Side-finds:**
   - nlpve04 has no directory on nlsyslogng01 (`/mnt/logs/syslog-ng/` has nl-pve01-03 only),
     so it forwards no syslog. The 11:18 UTC resolver change had to be traced in its journal.
   - A session using the `root@pam!mcp` token swapped nlgitlabrunner02 and nlandroidsdk01 on
     nlpve04 three times on 2026-11-07 (11:08, 12:25, 13:36 UTC). Neither guest's power state was
     touched by this change.

## Rollback

Backups, all named `*.bak-20261107`:

- `/root/resolv.conf.bak-20261107` on nl-pve03 and nlpve04.
- In nlfreeipa01: `/root/zzz-ipa.conf.bak-20261107` and `/root/resolv.conf.bak-20261107`.
- In nlhealthops01: `/root/resolv.conf.bak-20261107`.
- In nlsec01 and nlandroidsdk01: `/root/50-cloud-init.yaml.bak-20261107`.

```
# start order (old values)
# on nl-pve03:
pct set VMID_REDACTED --startup order=1
pct set VMID_REDACTED --startup order=10,up=30
pct set VMID_REDACTED --startup order=10,up=30
pct set VMID_REDACTED --startup order=14,up=10
pct set VMID_REDACTED --startup order=10,up=30
qm set VMID_REDACTED --startup order=1
# on nlpve04:
pct set VMID_REDACTED --startup order=2
pct set VMID_REDACTED --startup order=20
pct set VMID_REDACTED --startup order=10,up=30
pct set VMID_REDACTED --startup order=2

# hosts (on each): cp -p /root/resolv.conf.bak-20261107 /etc/resolv.conf
# CTs:
pct set VMID_REDACTED --nameserver 10.0.181.X
pct set VMID_REDACTED --nameserver 127.0.0.1
# then restore the in-CT backups; nlfreeipa01 also needs:
#   nmcli general reload conf; nmcli general reload dns-rc
# VMs:
#   sudo cp -p /root/50-cloud-init.yaml.bak-20261107 /etc/netplan/50-cloud-init.yaml
#   sudo netplan generate && sudo networkctl reload
```
