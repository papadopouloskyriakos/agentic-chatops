# Operational Rules

> Auto-compiled from 236 feedback memory files on 2026-07-03 04:30 UTC.
> These are hard-won lessons from real incidents. Violating them has caused outages.

## Configuration Safety

### Always ask before making changes

NEVER make changes to config files without asking the user first. Present findings and proposed fixes, then wait for explicit approval before editing anything.

**Why:** User was furious when config files were edited without permission during an audit task. The audit was requested as analysis — not as a license to change things. Some "fixes" were wrong because the user had context that wasn't visible in the code (e.g., devices were decommissioned, a "wrong" MQTT topic was intentionally wrong to avoid a side effect).

**How to apply:** When doing analysis/audit tasks, ALWAYS present findings as a report and ask "Want me to fix X?" before touching any file. Even when the user says "fix these", confirm the exact changes first if there's any ambiguity. This applies especially to production configs (HA, IoT, infrastructure).

*Source: `memory/feedback_ask_before_changing.md`*

### NEVER modify OOB/lifeline systems without explicit approval

NEVER install packages, run system upgrades, or modify configuration on OOB/lifeline systems (PiKVM, LTE gateway, PDU) without explicit step-by-step user approval.

**Why:** On 2026-03-21, `pacman -S --overwrite '*'` on grpikvm01 corrupted libgcc_s.so.1, then `pikvm-update` failed mid-upgrade leaving the system unbootable. The PiKVM was the ONLY remote access path to the GR site with no remote hands available. The system is now bricked.

**How to apply:**
- OOB systems are untouchable infrastructure — their stability is more important than being up-to-date
- Never use `--overwrite '*'` or `--force` on any package manager
- Never run full OS upgrades on remote systems without a tested rollback plan
- If packages need installing, install ONLY the specific package, resolve conflicts manually, and get explicit user approval for each step
- If a package conflict arises, STOP and ask the user — do not try to force through it
- The user explicitly asked for the upgrade, but I should have flagged the risks of upgrading a remote OOB appliance with no fallback access

*Source: `memory/feedback_never_modify_oob.md`*

### When mirroring a working production config, mirror it verbatim — don't reinterpret

**Rule:** when the operator says "mirror the config of X," read X's config files in detail and copy the exact structure. Do NOT replace working blocks with what "the docs say is equivalent." The original config encodes troubleshooting lessons that are invisible until they break.

**Why:** during the defra Matrix+MAS deploy on 2026-04-27, the operator said "mirror the config of nl-matrix01." I read it superficially, then wrote my own using `experimental_features.msc3861:` for MAS delegation in Synapse — which the upstream docs document as a valid option. NL's actual config used the newer `matrix_authentication_service:` block (with a comment: "replaces deprecated experimental_features.msc3861"). My choice produced a Synapse that loaded MAS structurally but didn't advertise the right `unstable_features` in `/_matrix/client/versions`, and Element Web rejected the homeserver as "misconfigured." Cost: ~30 minutes of debugging + 3 reload cycles to discover something the original config had already solved.

Other examples from the same deploy where verbatim-mirroring saved time:
- `.well-known/matrix/client` JSON must include BOTH `m.authentication` AND `org.matrix.msc2965.authentication` keys with identical content. NL had both. I had only the msc-prefixed one. Element checks both depending on version.
- nginx must redirect `/.well-known/openid-configuration` to MAS subdomain (NL had this; I missed it).
- nginx synapse proxy needs `proxy_buffering off`, `proxy_read_timeout 600s`, and `Upgrade` headers for sliding sync. NL had them; I had a minimal proxy that worked for non-streaming requests but would have broken on long-polling / sync.

**How to apply:**
- When an operator points at an existing config as the reference, read every config file in full before rewriting.
- For each setting, ask "is this present in the reference? If so, why?" Copy unless there's a specific reason to deviate (e.g., different domain, federation off vs on).
- Note the deltas explicitly in your output ("dropping bridges, dropping captcha, dropping rtc_foci because we don't run those features here") so the operator can sanity-check.
- Use the operator's existing IaC repo for the source, not just CLAUDE.md descriptions — the actual yaml/conf files are the ground truth.
- If the docs say "X is equivalent to Y," default to whichever the existing config uses, not whichever the docs prefer. Equivalence claims often hide subtle differences in version-advertising or compatibility.

*Source: `memory/feedback_mirror_working_configs_verbatim.md`*

## ASA / VPN / Network

### ASA 9.16 BGP limitations — why FRR sidecars exist + why ASAs don't peer with remote RRs

ASA 9.16 has two related BGP limitations that make it **unsuitable** as a direct iBGP peer of a remote-site route reflector. These aren't bugs — they're intentional design choices — but they shape how the network must be laid out.

**Why:** discovered 2026-04-23 while trying to extend the YT-200 community-policy fix into a full-symmetry cross-cluster RR-client mesh (planned GR-ASA ↔ NL-FRR01/02 + NL-fw01 ↔ GR-FRR01/02). Both ASA-side session pairs refused to establish. The 2 rtr01 ↔ GR-FRR01/02 sessions established fine because rtr01 is IOS-XE, not ASA.

**How to apply:** when designing iBGP HA in this network, let the FRR sidecars (`nlk8s-frr{01,02}` cluster 1.1.1.1, `grk8s-frr{01,02}` cluster 2.2.2.2) do all the RR work. Each ASA peers ONLY with its 2 local FRRs. Cross-cluster route propagation rides the existing FRR-to-FRR mesh. Do not try to make ASAs peer with remote RRs — it's architecturally wrong AND hardware-blocked.

## The two ASA 9.16 constraints

1. **No `neighbor <X> update-source <interface>` on BGP neighbors.** Help output of `neighbor 10.0.X.X ?` at `config-router-af` prompt literally doesn't list `update-source`. ASA picks the egress-interface IP for TCP source based on the routed path. For a remote peer reachable via VTI, source becomes the VTI /31 IP — which doesn't match any stable inside/DMZ address the remote side would configure as its neighbor.

2. **To-the-box traffic is dropped across interfaces unless `management-access <nameif>` explicitly permits it.** TCP destined for ASA's `dmz_servers02` IP (e.g. 10.0.X.X on NL-fw01) arriving via Tunnel4 (Freedom VTI) gets dropped because the destination IP doesn't belong to the arrival interface. `management-access` is a single-interface-global knob — can't coexist with the existing `management-access inside_mgmt` without breaking it.

Combined result: a remote FRR trying to peer with NL-fw01 at 10.0.X.X cannot reach it, AND NL-fw01 can't initiate outbound with a source IP the remote FRR would accept. Session stays Idle/Connect forever.

## Why FRR sidecars are the answer (and already solve this)

- Each site has 2 FRR RRs — RFC 4456 redundancy already covers single-RR failure.
- NL-FRRs ↔ GR-FRRs peer cross-cluster; routes propagate via RR-to-RR mesh without any edge device reflecting.
- ASAs peer with local FRRs as non-clients → get everything via reflection, including cross-cluster origins.
- VPSs peer with both clusters' FRRs as clients → origin traffic flows through the sidecar fabric.
- rtr01 (IOS-XE, no ASA limits) is additionally an RR for its direct VPS xfrm peers and GR ASA — minor bonus, not required.

The "both local FRRs dead simultaneously" scenario isn't an iBGP design target — it's a catastrophic cluster event. The right mitigation is **failure-domain separation** of the 2 FRRs per site (different Proxmox hosts, different power, different racks), not another layer of iBGP peerings.

## rtr01 ↔ GR-FRR01/02 sessions — kept because they work

2026-04-23 deploy did successfully establish:
- `rtr01 neighbor 10.0.X.X update-source Port-channel4.2` ↔ `grk8s-frr01 neighbor 10.0.X.X update-source 10.0.X.X`
- symmetric for `-frr02` / `10.0.X.X`

rtr01's Port-channel4.2 is 10.0.X.X, matches GR-FRRs' configured peer IP. Sessions Established, 38 prefixes each. Community-policy route-map `XCLUSTER_RR_IN` (LP 50 for CL-VPS-ORIGIN, LP 100 default) applied inbound. Net +2 iBGP sessions, mesh went 43/43 → **45/45**.

These are architecturally an optional bonus — the FRR sidecars already handle the canonical HA paths. The rtr01 pair adds another client-of-both-clusters pattern similar to the VPSs, valuable because rtr01 is topologically at the NL edge.

## What NOT to do

- Don't try to add ASA ↔ remote-FRR peerings. ASA 9.16 blocks it. A different firmware or device would be needed.
- Don't set up ASA-as-RR (adds deviation without HA benefit). Original YT-200 attempt at "nl-fw01 as partial RR" was architecturally regressive.
- Don't add redundant ASA ↔ remote-ASA peerings beyond the existing VTI-direct ones (nl-fw01 ↔ GR-ASA Freedom, rtr01 ↔ GR-ASA budget). They already exist for fast VTI convergence; more would be noise.

## Real HA improvement worth doing

Audit the 2 FRRs per site for failure-domain separation. If NL-FRR01 and NL-FRR02 are both on the same Proxmox host, losing that host loses the entire NL RR service. Same for GR. Move one to a different host/rack. That's the CCIE-shaped HA work, not more iBGP sessions.

*Source: `memory/asa_9_16_bgp_limitations.md`*

### ASA 9.16 PPPoE/VPDN show commands — which exist, which don't

On `nl-fw01` (ASA 9.16(4)) the following commands **do not exist** and will return `% Incomplete command` or `% Invalid input detected`:

- `show pppoe client`
- `show pppoe statistics`
- `show pppoe session packet`
- `show vpdn` (bare, with no sub-keyword)
- `show vpdn session`
- `show vpdn tunnel`
- `show logging | tail N` (`tail` filter not available; use `last N` or just inspect end of buffer)

What **does** work for PPPoE diagnosis on this platform:

| Need | Command |
|------|---------|
| PPPoE config | `show running-config vpdn`, `show running-config interface Port-channel1.6` |
| VPDN group dump | `show vpdn group Freedom` (group name required) |
| Sub-if state | `show interface Port-channel1.6` (line protocol + IP address line says it all) |
| Live IP assignment | `show ip address` — if `Port-channel1.6` is missing from the **Current** table while present in **System**, PPPoE never completed |
| Tracked-route SLA | `show track 1`, `show running-config sla monitor 1`, `show running-config \| include ^route outside_freedom` |
| Routing | `show route` — confirm `S* 0.0.0.0/0 [5/0] via 10.0.X.X, outside_budget` is the active default (failover is doing its job) |
| BRAS reachability **via the other WAN** | `ping outside_budget 198.51.100.X size 64 repeat 4` (do not ping via outside_freedom — it has no IP) |
| VTI tunnel state | `show interface stats` — Tunnel4–9 sourced from `outside_freedom` will all show `down, line protocol is down` with `IP address: 0.0.0.0` |

Caught 2026-05-11 on a netmiko sweep against `nl-fw01`. Saves ~5 min of dead-command guessing on the next PPPoE incident.

Also: the `lib/devices.py` helper reads `CISCO_PASSWORD`, but the gateway shell exports `CISCO_ASA_PASSWORD` — remap before invoking (parallel to the dhcpd binding case in `feedback_asa_show_dhcpd_cli_gotchas.md`).

*Source: `memory/feedback_asa_9_16_pppoe_show_commands.md`*

### ASA crypto-map delete+recreate pattern

Never modify Cisco ASA crypto-map entries in-place when changing the peer list. Always fully delete (`no crypto map <name> <seq> ...` for all 3 lines: match, peer, proposal) then re-create.

**Why:** In-place `set peer` changes update the running config but leave stale internal IKEv2 Traffic Selector (TS) matching tables. The ASA will reject CREATE_CHILD_SA requests with TS_UNACCEPTABLE even though `show run` looks correct. Discovered during the Freedom ISP outage (2026-04-08) when GR ASA entries 37/38 had 203.0.113.X added as secondary peer — `show run` showed the peer correctly but IKEv2 TS narrowing kept rejecting the traffic selectors. Only a full delete+recreate fixed it.

**How to apply:** Any time you add, remove, or reorder peers on an existing crypto-map entry:
```
no crypto map <name> <seq> match address <acl>
no crypto map <name> <seq> set peer <peers>
no crypto map <name> <seq> set ikev2 ipsec-proposal <proposal>
crypto map <name> <seq> match address <acl>
crypto map <name> <seq> set peer <new_peers>
crypto map <name> <seq> set ikev2 ipsec-proposal <proposal>
```

*Source: `memory/feedback_asa_cryptomap_delete_recreate.md`*

### ASA floating-conn for route changes

Use `timeout floating-conn 0:00:30` on Cisco ASA to handle stale connection entries after routing changes. This is the Cisco-native solution (Cisco doc 113592). **Configured and saved on both ASAs (2026-04-11).**

**Why:** Corosync cluster split 2026-04-11. ASA conn table pinned UDP flows to pre-VTI interface. Initial instinct was to write a cron script, but user correctly pushed back — the ASA has a native feature for this. Always research vendor documentation before building workaround scripts.

**How to apply:**
1. Prefer Cisco-native features over external scripts for ASA behavior
2. `timeout floating-conn 0:00:30` is now active on both nl-fw01 and gr-fw01
3. Null0 blackhole routes (AD 255) added for remote-site subnets on both ASAs — prevents cleartext leakage
4. `sysopt connection preserve-vpn-flows` confirmed DISABLED on both ASAs
5. Use **netmiko** (not expect) for Cisco ASA automation — netmiko venv at `/tmp/netmiko-venv/` on grclaude01
6. GR ASA reachable from grclaude01 at **10.0.X.X** (not 10.0.X.X)

*Source: `memory/feedback_asa_clear_conn_after_vti.md`*

### ASA show dhcpd CLI gotchas

On Cisco ASA (verified on nl-fw01, ASA 9.16(4) 2026-05-10):

1. **Neither `show dhcpd binding <intf>` nor `show dhcpd state <intf>` exists.**
   - `show dhcpd binding inside_mgmt` → `ERROR: % Invalid Hostname` (ASA parses the trailing token as an IP/hostname).
   - `show dhcpd state inside_mgmt` → `% Invalid input detected at '^' marker.`
   - Correct form: `show dhcpd binding` (full table, all pools) + `show dhcpd state` (per-interface enable/disable list). Filter to a specific subnet client-side.

2. **Client Identifier format prepends the DHCP hwtype byte.** Ethernet client-id `012c.cf67.7b96.82` is 7 bytes = `01` (hwtype = Ethernet) + 6-byte MAC. Strip the leading `01` → MAC `2c:cf:67:7b:96:82`. A handful of clients send the raw MAC with no `01` prefix (sent client-id as ASCII string or a non-standard option), and those appear as 12-char `xxxx.xxxx.xxxx`.

**Why:** Caught while pulling VLAN-10 leases via netmiko. First guess (`show dhcpd binding inside_mgmt`) burned a connection round-trip; cross-referencing reservations to the binding table needed the prefix-strip rule.

**How to apply:** When asked for ASA DHCP state for a single interface, do `show dhcpd binding` once then grep by subnet, and decode client-id by dropping the leading 2 hex chars when the field is 14 chars long. Lease default on this ASA is 3600s.

**Project-specific aside:** `network/scripts/lib/devices.py` looks for `CISCO_PASSWORD`, but the gateway shell exports `CISCO_ASA_PASSWORD`. Remap with `CISCO_PASSWORD="$CISCO_ASA_PASSWORD"` before invoking any script that imports the lib.

*Source: `memory/feedback_asa_show_dhcpd_cli_gotchas.md`*

### ASA syslog timestamps are in the ASA local clock (CEST), not UTC

When pasting `%ASA-*` syslog lines into ISP / vendor / YouTrack timelines, never assume the timestamp is UTC. `nl-fw01` has:

```
clock timezone CET 1
clock summer-time CEST recurring last Sun Mar 2:00 last Sun Oct 3:00
```

So every line in `show logging` and in remote syslog (`/mnt/logs/syslog-ng/.../nl-fw01-*.log`) is in CET (Nov–Mar) or CEST (Mar–Oct). Subtract 2h in summer (or 1h in winter) before writing "(UTC)".

**Why:** Caught 2026-05-11 auditing a drafted Freedom Internet support email about the 2026-05-08 PPPoE outage — operator wrote `Outage start (UTC) : 2026-05-08 09:46:36` based on the `May 8 09:46:36` syslog timestamp, but that timestamp was already CEST. Real UTC was `07:46:36 UTC` (09:46:36 CEST). Freedom's NOC would have searched the wrong 2-hour window of BRAS session logs.

**How to apply:** For any ASA-sourced timestamp going into an outside-facing message, label it as CEST/CET and provide the UTC explicitly with the offset applied. Cross-check with `show track <N>` — the relative-time `last change` reading should match the syslog event after offset is applied (e.g., outage at 07:46 UTC = `last change 3d05h` shown at 12:56 UTC three days later).

Parallel trap: `nlrtr01`, `nl-sw01`, `nllte01` all run the same clock-timezone CET pattern (IOS-XE / IOS), so their logs are also CEST in summer.

*Source: `memory/feedback_asa_syslog_timezone_cest_not_utc.md`*

### GR ASA SSH requires stepstone via gr-pve01

GR ASA (gr-fw01) SSH access requires a stepstone connection through gr-pve01. Direct SSH from NL (nl-claude01) gets connection reset.

**Why:** The GR ASA likely has SSH ACLs restricting management access to local GR subnets only (10.0.X.X/24), not cross-site NL subnets.

**How to apply:** When SSHing to gr-fw01, use: `ssh -i ~/.ssh/one_key root@gr-pve01` then `ssh operator@10.0.X.X` from there. Or use ProxyJump: `ssh -J root@gr-pve01 operator@gr-fw01` (with appropriate legacy SSH flags for the ASA hop).

*Source: `memory/feedback_gr_asa_ssh_stepstone.md`*

### GR ASA access — direct via grclaude01 netmiko (not OOB public IP)

When talking to **gr-fw01** (GR ASA) for diagnosis or read-only inspection, SSH directly to `app-user@grclaude01` over the VPN and invoke netmiko from the pre-built venv at `/tmp/netmiko-venv/`. Do NOT route through the OOB public IP `203.0.113.X:2222`.

**Why:** The OOB path is the disaster-recovery fallback — intended for when VPN is down, not routine work. Routine queries should stay on the inside VPN path: it is faster, doesn't consume public-IP round trips, and doesn't hit the rate-limits on the NAT translated OOB port. The `scripts/lib/asa_ssh.py::ssh_gr_asa_command()` helper ships with the OOB path baked in because it's used by cron jobs that must survive VPN outages — for interactive diagnosis, bypass the helper.

**How to apply:**

```bash
# One-shot query, password passed via env:
ssh -i ~/.ssh/one_key app-user@grclaude01 \
  "CISCO_ASA_PASSWORD='<pw>' /tmp/netmiko-venv/bin/python3 - <<'PY'
from netmiko import ConnectHandler
import os
pw = os.environ['CISCO_ASA_PASSWORD']
dev = {'device_type':'cisco_asa','host':'10.0.X.X',
       'username':'operator','password':pw,'secret':pw}
n = ConnectHandler(**dev); n.enable()
for c in ['terminal pager 0','show bgp summary',...]:
    print(f'### {c}'); print(n.send_command(c, read_timeout=15))
n.disconnect()
PY"
```

- ASA host: `10.0.X.X` (inside interface from grclaude01 LAN)
- Netmiko venv: `/tmp/netmiko-venv/bin/python3` on grclaude01
- User: `operator`; enable uses same password (`secret=pw`)
- Password lives in `CISCO_ASA_PASSWORD` env var, read from `~/gitlab/n8n/claude-gateway/.env` by existing scripts
- `terminal pager 0` first, always — ASA paginates by default and will stall netmiko
- Use `read_timeout >= 15` for `show run` or any BGP query that scans the full table

NL ASA (`nl-fw01`) does not need a stepstone — SSH directly from NL hosts with the `ssh-rsa` legacy kex flags, or use `ssh_nl_asa_command()` in the same lib.

Reserve the OOB path (`ssh -p 2222 app-user@203.0.113.X` or `ssh_gr_asa_command`) only for: (a) cron jobs that must run during VPN outages, or (b) manual recovery when VPN is actually down.

*Source: `memory/feedback_asa_netmiko_via_grclaude01.md`*

### IPsec changes must be additive — never replace without asking

When adding ISP redundancy to VPS IPsec tunnels, the change must be ADDITIVE — add the new ISP as a backup path alongside the existing primary. NEVER replace the current working tunnel with the new ISP path.

**Why:** During the Freedom PPPoE outage (2026-04-08), VPS tunnels were incorrectly migrated FROM Freedom TO xs4all instead of adding xs4all as backup. This left VPS with no NL tunnels when xs4all also had issues, and required reverting when Freedom recovered. The user explicitly stated they wanted both ISPs active simultaneously.

**How to apply:** Use `auto=start` for the primary ISP and `auto=route` (trap-based, activates on traffic when primary fails via DPD) for backup ISPs. This gives seamless failover without replacing the working path.

*Source: `memory/feedback_ipsec_additive_changes.md`*

### IPsec tunnel naming — ISP-specific suffixes

VPS IPsec connection names MUST include the ISP suffix for NL-bound tunnels: `nl-{destination}-{isp}` (e.g., `nl-dmz-freedom`, `nl-dmz-xs4all`). This makes it unambiguous which ISP each tunnel uses, especially as new ISPs may be added.

**Why:** User explicitly requested this during the dual-WAN VPN parity work. Generic names like `nl-dmz` don't scale when multiple ISPs serve the same destination.

**How to apply:** When creating or modifying VPS strongSwan connections that target NL ASA, always suffix with the ISP name. GR-direct tunnels (single ISP) don't need a suffix. Backbone failover paths include both ISP and path: `gr-dmz-via-nl-freedom`.

*Source: `memory/feedback_ipsec_isp_naming.md`*

### NEVER SSH to nl-sw01

nl-sw01 SSH: login block-for fixed (2026-04-09). Now 10s block after 5 failures (was 100s after 2).

**Why:** Original `login block-for 100 attempts 2 within 100` was extremely aggressive — 2 wrong passwords locked out the entire management subnet for 100s. Claude triggered this twice (2026-04-08 and 2026-04-09), locking out the operator.

**How to apply:** SSH to nl-sw01 is now safe, but use correct parameters:
- Ciphers: `aes128-ctr,aes256-ctr` (NOT CBC — switch doesn't offer CBC)
- HostKeyAlgorithms: `+ssh-rsa`
- KexAlgorithms: `diffie-hellman-group14-sha1`
- User: `operator`, Password: same as ASA
- IOS XE 16.12.12, Catalyst 3850 (WS-C3850-12X48U)
- `ip ssh authentication-retries 2` — only 2 password attempts per connection, so get it right

**Programmatic access (2026-04-22, IFRNLLEI01PRD-705).** Four netmiko helpers
in `scripts/lib/ios_ssh.py`: `ssh_nl-sw01_config`, `ssh_nl-sw01_command`,
`nl-sw01_port_shutdown(iface)`, `nl-sw01_port_noshut(iface, force_poe_cycle=False)`.
Used by `scripts/chaos-port-shutdown.py` for the autonomous monthly
Freedom-ONT drill. Shared `CISCO_ASA_PASSWORD` credential. Single-try
semantics to avoid the 5-attempt block-for lockout.

*Source: `memory/feedback_never_ssh_sw01.md`*

### feedback_asa_shun_vti

ASA `threat-detection scanning-threat shun` auto-shuns any IP that breaches the per-host burst threshold. nl-fw01's config:

```
threat-detection rate scanning-threat rate-interval 600 average-rate 5 burst-rate 10
threat-detection rate scanning-threat rate-interval 3600 average-rate 4 burst-rate 8
threat-detection scanning-threat shun except object-group whitelist_shun_nlgr_all_subnets
```

**10 pps burst is the ASA default** — trivially exceeded by normal inter-site transit traffic during failover/migration events. Any trusted internal router/VTI endpoint MUST be explicitly whitelisted or it WILL be shunned.

## Whitelist object-group hierarchy

`whitelist_shun_nlgr_all_subnets` is composed of three sub-groups — ALL infrastructure IPs (routers, firewalls, VTI transit /30s, VPS loopbacks, K8s pods, tenant subnets) need to be in one of these three:

| Sub-group | Covers | Add to this sub-group when |
|---|---|---|
| `gr_all_subnets` | GR private networks + VPN pools + GR NFS | new GR subnet lands |
| `nl_all_subnets` | NL mgmt/corosync/cctv/rooms/k8s/strongswan/dmz + **10.0.X.X/30** (rtr01↔nl-fw01 budget transit, added 2026-04-22) | new NL subnet or transit lands |
| `ALL_VPS_OVERLAY` | `10.255.X.X/24` + `10.255.X.X/24` + `10.255.200.X/24` + VPS public IPs | new overlay/VTI subnet lands |

## Historical incidents

| Date | Missing from whitelist | Symptom | Fix |
|---|---|---|---|
| 2026-04-12 | `10.255.200.X/24` (VTI mesh) | IKE re-negotiation during chaos test → VTI endpoints shunned → VPN silently dead while interfaces showed up/up | Added to `ALL_VPS_OVERLAY` |
| 2026-04-22 | `10.0.X.X/30` (rtr01↔nl-fw01 budget transit, new from 2026-04-21 migration) | Budget failover traffic + corosync retransmissions + NAT churn during Freedom-shut test → rtr01 (10.0.X.X) burst hit 10 pps → shunned → Budget path dead for 19 min (Freedom was also down) | Added to `nl_all_subnets` |

## Diagnostic pattern

If a VTI/transit endpoint is up/up + IKE READY + BGP route present but traffic doesn't flow:

```
show shun                                           # look for infrastructure IPs
show shun statistics                                # per-interface count
show logging | include 733101|733102|401002|401004  # trigger + shun-add events
```

Look for `%ASA-4-733101: Host X.X.X.X is attacking. Current burst rate is ≥ max configured rate`. Clear with `clear shun`.

**CRITICAL:** `clear shun` is a temporary unblock. If the IP isn't in the whitelist, it WILL be shunned again on the next traffic spike. Always add to the appropriate sub-group + `write memory`.

## Running checklist for migrations / new infrastructure

Any IaC MR that:
- adds a new internal subnet (transit /30, VTI /31, loopback, service VLAN)
- adds a new routing device (edge router, FRR instance, VPS)
- adds a new VPN pool

…MUST also patch `whitelist_shun_nlgr_all_subnets` via one of its three sub-groups. Add a grep CI check in nl/production: any new `nat (X,outside_*) source static …` rule or new `object network NET_…` with an IP in 10.0.0.0/8 / 172.16.0.0/12 / 10.0.X.X/16 ranges must have a corresponding whitelist entry.

## How to apply (runbook)

1. Identify the sub-group (gr/nl/overlay) based on subnet semantics.
2. `configure terminal → object-group network <sub-group> → network-object <subnet> <mask> → exit → write memory`.
3. Propagate to GR ASA (mirror change required — same config on gr-fw01 if the IP is bilateral).
4. Verify: `show run object-group id whitelist_shun_nlgr_all_subnets` and each sub-group.
5. No runtime clear needed — but `clear shun` is required to release any already-shunned IP.

*Source: `memory/feedback_asa_shun_vti.md`*

### feedback_dual_wan_nat_parity

When configuring dual-WAN on ASA, EVERY inside zone needs dynamic PAT on BOTH outside interfaces.

**Why:** The NL ASA had dynamic PAT only for `outside_freedom`. When Freedom went down, all inside zones lost internet because traffic routed via `outside_xs4all` had no PAT. When Freedom came back, `inside_mgmt` still had no Freedom PAT (only rooms had it). This broke the operator's laptop twice in one session.

**How to apply:** When adding a new inside zone or outside interface, always add PAT for ALL outside interfaces. Check with `show run nat | include dynamic` and verify every zone×interface combination exists. The `after-auto source dynamic any interface` pattern works for catch-all PAT.

*Source: `memory/feedback_dual_wan_nat_parity.md`*

### strongSwan needs libstrongswan-standard-plugins for socket support

When installing strongSwan with `--no-install-recommends`, you must explicitly include `libstrongswan-standard-plugins` or charon comes up with no socket implementation and IKE silently fails.

**Why:** On Ubuntu 24.04 noble, `strongswan` (the metapackage) declares `libstrongswan-standard-plugins` as a Recommends. With `apt install --no-install-recommends`, the plugin is omitted. charon-systemd / charon then starts but `ipsec listplugins` shows only:
```
charon:
    NONCE_GEN
    libcharon-sa-managers
    libcharon-receiver
    kernel-ipsec
    kernel-net
```
— no `socket-default`, no AES, no SHA. Charon writes `[NET] no socket implementation registered, sending failed` to journalctl when an SA tries to dial out. The IPsec tunnel's strongswan-side just keeps retransmitting the IKE_SA_INIT to nowhere.

Caught 2026-05-05 on the notrf01dmz01/02 onboarding. Symptom: tunnels stayed CONNECTING for minutes with no peer response visible in charon logs even though the peer was reachable; ss -ulnp showed nothing listening on UDP 500/4500.

**How to apply:**
- When provisioning a new IPsec edge host, install the FULL set of strongSwan packages explicitly:
  ```
  apt install --no-install-recommends \
    strongswan strongswan-swanctl strongswan-pki \
    libstrongswan libstrongswan-standard-plugins \
    libcharon-extauth-plugins libcharon-extra-plugins \
    charon-systemd
  ```
- Quick verify post-install: `ipsec listplugins | grep -E "socket|aes"` — should show `socket-default` + `aes`. If not, install `libstrongswan-standard-plugins` and `systemctl restart strongswan-starter`.
- Check `ss -ulnp | grep -E ':(500|4500)'` — charon should be listening there.

*Source: `memory/feedback_libstrongswan_standard_plugins_recommends.md`*

## Kubernetes

### FRR route reflectors are independent LXCs, NOT K8s pods or CRDs

**Rule.** The 4 route-reflector FRR instances (`nlk8s-frr01`, `nlk8s-frr02`, `grk8s-frr01`, `grk8s-frr02`) and the 2 VPS FRRs (`notrf01vps01`, `chzrh01vps01`) are **Linux LXC containers and VMs**, not Kubernetes resources. The hostname contains `k8s-` because they peer with the K8s data plane as Cilium eBGP partners, NOT because they're themselves inside a cluster.

- FRR service: `systemctl status frr` on the LXC
- Config file: `/etc/frr/frr.conf` — plain text, editable via SSH, applied via `vtysh` or `service frr reload`
- OS: Debian 12 (confirmed 2026-04-21 on nlk8s-frr01)

**Why this matters:** The strict K8s GitOps rule (`feedback_k8s_strict_gitops.md`) does NOT apply to FRR config changes. FRR changes are NOT subject to Atlantis MR. They are operator-driven and manually applied (with git-commit-for-audit where applicable, but no Atlantis plan/apply cycle).

**Correction history.** On 2026-04-21 I claimed an iBGP fix "requires K8s FRR CRD change (Atlantis MR)". Operator corrected: "the NL-FRR side is a K8s FRR CRD change — wrong; the none of the frr are pods; all of them are independent from k8s cluster LXCs." Re-verified via `ssh root@10.0.X.X "hostname; cat /etc/os-release"` → `nlk8s-frr01 / Debian GNU/Linux 12 (bookworm) / frr active / /etc/frr/frr.conf exists`.

**How to apply.** For FRR config changes:
1. SSH to the FRR LXC/VM directly as `root` (or `operator` with sudo on VPSs).
2. Edit `/etc/frr/frr.conf` OR use `vtysh -c "config t / ..."` for live changes.
3. `vtysh -c "write memory"` persists to `/etc/frr/frr.conf`.
4. Commit to the IaC repo for audit if the config is mirrored there, but apply is direct.

*Source: `memory/feedback_frr_not_k8s.md`*

### K8s Strict GitOps Requirement

Every Kubernetes configuration change MUST follow this exact procedure:
1. Feature branch from main
2. Edit `.tf` files only (use OpenTofu MCP for correct argument names)
3. `tofu fmt -recursive k8s/`
4. Commit, push, create GitLab MR
5. Atlantis auto-runs `tofu plan` on the MR
6. Review plan, then comment `atlantis apply`
7. Verify cluster health after apply
8. Merge MR only after verification passes
9. Sync local repo

**Why:** This is how the user has operated K8s for months. No exceptions. kubectl apply, helm install, or direct API changes cause drift that OpenTofu will overwrite on next apply. The user has been burned by drift before.

**How to apply:** When any task involves K8s changes — whether it's a new service, a config update, scaling, or even a simple label change — always use the OpenTofu + Atlantis MR flow. Never use kubectl for write operations. Never push .tf changes directly to main. If Claude Code or OpenClaw is asked to make a K8s change, follow the procedure exactly.

*Source: `memory/feedback_k8s_strict_gitops.md`*

### feedback-no-balloon-on-k8s-control-plane

## The rule

Any PVE VM that runs **etcd / kube-apiserver / kube-scheduler / kube-controller-manager / kubelet on a control-plane node** MUST have its balloon device disabled. Set `balloon: 0` in the VM config and reboot to apply.

This rule extends to databases generally — Postgres, MariaDB, Redis with persistence, anything that does synchronous fsyncs to disk under load. Page cache eviction during balloon inflation turns ms-scale fsyncs into seconds-scale fsyncs.

## Why

etcd backs k8s state and uses fsync after every Raft commit. With healthy page cache, fsync is < 10 ms. With page cache evicted by balloon-induced memory pressure, fsync becomes disk-bound (10-100× slower). The apiserver does **synchronous** `KV/Range` reads against etcd as part of every `/healthz` and `/readyz` invocation, with default 5 s timeout. When etcd is slow, apiserver returns HTTP 500. Kubelet's liveness probe sees the 500, sends SIGTERM, restarts the apiserver pod. Cycle repeats every ~24 min until the underlying memory pressure clears.

The kicker: this is a **silent partial degradation** as far as `etcdctl endpoint health` is concerned. The health-probe commit is so small it fits in any remaining cache. So you see:

```
$ etcdctl endpoint health --cluster
✓ all 3 peers healthy, 10-22 ms commit times
```

…while the apiserver's actual workload is timing out at 5 s on the same etcd. Don't trust endpoint-health as a proxy for "this etcd is good for the apiserver." Check endpoint-status commit-latency instead:

```
$ etcdctl endpoint status --cluster -w table | grep "<affected_node>"
| ... | commit-latency 288 ms |       ← outlier among peers at 70-80 ms
```

## How to spot the trap

| Symptom | Check |
|---|---|
| One control-plane node's apiserver restartCount much higher than peers' | `kubectl get pods -l component=kube-apiserver -o wide` |
| Apiserver logs flooded with `etcd-client retrying ... DeadlineExceeded` | `kubectl logs ... | grep -c DeadlineExceeded` |
| VM kernel `free -h` shows much less RAM than configured | ssh in, run `free -h`; compare to `qm config <vmid> | grep memory` |
| etcd commit latency on affected node 3-10x peer latency | `etcdctl endpoint status --cluster -w table` |
| `cat /proc/pressure/io` inside VM avg300 > 15 % | sustained IO pressure → balloon-or-disk-starvation symptom |

## Apply (per VM)

```bash
# On the PVE host that owns the VM:
qm set <vmid> --balloon 0
qm reboot <vmid>   # MANDATORY — see [[feedback_pve_balloon_zero_needs_reboot]]
qm status <vmid> --verbose | grep -E "^(balloon|mem|maxmem)"
# Expected: only maxmem + mem (no balloon line) — device entirely removed
```

## Fleet audit one-liner

```bash
for H in nl-pve01 nl-pve02 nl-pve03 nlpve04 gr-pve01 gr-pve02; do
  ssh root@$H 'for v in $(qm list 2>/dev/null | awk "NR>1 {print \$1}"); do
    b=$(qm config $v 2>/dev/null | awk -F: "/^balloon:/{print \$2+0}")
    n=$(qm config $v 2>/dev/null | awk -F: "/^name:/{print \$2}" | tr -d " ")
    m=$(qm config $v 2>/dev/null | awk -F: "/^memory:/{print \$2+0}")
    if [ -n "$b" ] && [ "$b" != "0" ] && [ "$b" != "$m" ] && echo "$n" | grep -qE "k8s-ctrlr|etcd|mariadb|postgres|redis"; then
      echo "  $(hostname):$v $n balloon=$b memory=$m"
    fi
  done'
done
```
…will flag any VM whose name suggests it runs a stateful / fsync-sensitive workload AND has an active balloon device (balloon != 0 AND balloon != memory).

## Caught 2026-05-15

nlk8s-ctrl01 had `balloon: 4096` while peers nlk8s-ctrl03 had `balloon: 0`. 1665 apiserver restarts over ~27 days. Single config-line fix + reboot dropped that to 0. See [[apiserver_nlk8s-ctrl01_balloon_chronic_restart_fixed_20260515]] for the full incident narrative.

## Cross-references

- [[apiserver_nlk8s-ctrl01_balloon_chronic_restart_fixed_20260515]] — the incident this rule comes from
- [[feedback_pve_balloon_zero_needs_reboot]] — the gotcha when applying this fix (balloon: 0 is [PENDING], not live)
- [[n8n_oom_outage_20260511]] — sibling story about nl-pve01 host pressure cascading into k8s apiserver issues (same family of failure)
- [[feedback_no_zramswap_on_pve_hosts]] — sibling Proxmox rule

*Source: `memory/feedback_no_balloon_on_k8s_control_plane.md`*

### feedback_gitops_autonomous

**Execute git operations (branch, commit, push, open MR) autonomously — do not ask "should I commit/open the MR?" each time.** Operator wants momentum and does not want to be a per-step gate on routine gitops.

**Why:** asked 2026-06-29 whether to commit the scheduled-reboot feature; answer was "(a) fix/execute all gitops automatically; do not ask me each time." Repeated confirmation questions on routine gitops add friction without value.

**How to apply:**
- Proceed with branch → surgical stage → commit → push → **MR → and merge it to main** without the confirmation question. (Clarified 2026-29: "fix/execute all gitops automatically == also the MR, just do them" — merging a CI-green MR is included, not held for a confirm.)
- STILL be **surgical**: this repo's working tree is frequently dirty with *pre-existing* changes (wiki/, docs/, config/ regen artifacts, other WIP). Before committing, stage only the in-scope files and **verify `git diff --cached` shows only my changes** — never sweep unrelated pre-existing modifications into a feature commit. If a file I edited also has pre-existing hunks, use `git add -p` (or restore + re-apply only my hunk) to stage just mine.
- STILL follow conventions: branch off `main` (don't push direct), MR not direct-push, `feature/` or `fix/` branch prefix, workflow names prefixed `"NL - "`, `Co-Authored-By: Claude <noreply@anthropic.com>` trailer on commits, `🤖 Generated with Claude Code` on PR bodies.
- **Boundary:** this covers *routine* gitops (commit/MR/push of in-scope work + trivial git hygiene). Genuinely destructive or outward-facing-beyond-git actions (force-push, deleting branches/resources, deploying to prod infra, pushing secrets) still get explicit confirmation.

Relates: [[scheduled_reboot_suppression_build_20260629]], [[feedback_dont_disturb_foreign_repo_working_tree]].

*Source: `memory/feedback_gitops_autonomous.md`*

## Deployment & Sync

### Audit-before-sync pattern — prefer this over ignore_unreachable

Rule: when a sync/deploy playbook touches multiple hosts and one flaky
host shouldn't block delivery to the others, **do not add
`ignore_unreachable: true`** to the sync playbook. That path makes
failures silent and hid the BGP ECMP bug for 3 days on 2026-04-14 to
2026-04-17.

Preferred pattern — **"audit before sync"**:
- Separate playbook: `check_<thing>_<condition>.yml`
- Same inventory group as the sync it protects
- Runs as its OWN AWX job template on a schedule that fires **at least
  30 minutes before** the corresponding sync schedule
- FAILS RED (non-zero exit) if any host is near-expiry / unreachable /
  misconfigured
- Has a Matrix / email / whatever-notification on error only
- Gives the operator a real, actionable heads-up window

Why this is better than `ignore_unreachable` + banner:
- The sync stays strict — a red sync job is still a strong attention
  signal when things are genuinely broken.
- The audit is designed to fail, so its red state is unambiguous: "one
  of your hosts needs attention" rather than "is this cert sync actually
  working or silently skipping".
- Audit and sync have different risk profiles: audit can be rerun
  cheaply, sync shouldn't be rerun casually (writes state).
- Decouples observability (audit) from the delivery path (sync). If the
  audit breaks, sync still works; if sync breaks, audit still alerts.

Why: user explicit preference on 2026-04-17 when the AWX session
proposed adding `ignore_unreachable: true` to `sync_cert_to_proxmox.yml`
as a graceful-degradation measure. User declined and asked for an
AWX-only safety net instead. Result: playbook
`ansible/playbooks/cert-manager/check_cert_expiry.yml` (commit 04d5dbd),
AWX template "Cert Expiry Audit - Proxmox" id 74, daily 05:30 UTC
(52 min before the 06:22 UTC sync), Matrix-on-error notification.

How to apply:
- Any time a playbook author proposes `ignore_unreachable: true`,
  `ignore_errors: yes`, or `failed_when: false` as fault tolerance for a
  sync/deploy: stop and propose an audit-before-sync instead.
- Exception: `ignore_unreachable: true` is acceptable on purely
  informational plays (e.g. the "Banner - unreachable hosts" summary in
  sync_certs_to_edge.yml commit 328c6f7) where the goal is explicitly to
  surface state without blocking delivery to the reachable hosts.
- Audit schedule: fire ~30-60 min before the corresponding sync runs, so
  an operator who wakes to a pager has time to act before the sync does
  its thing.

Reference: `cert_sync_banner_20260417.md`, `bgp_ecmp_fix_20260417.md`,
`incident_multilayer_20260417.md`.

*Source: `memory/feedback_audit_before_sync_pattern.md`*

### Cloudflare edge serves stale HTML during Hugo deploy verification — always bust the cache

After pushing a deploy to `kyriakos.papadopoulos.tech` (or any HAProxy-fronted Hugo site behind Cloudflare), **the first plain `curl` against the live URL will likely return the previous build** because Cloudflare's edge cache hasn't seen its TTL expire — even though the origin already serves the new build.

This produced a false-negative during the 2026-05-06 chaos red-link verification: a deploy probe with `curl ... "https://kyriakos.papadopoulos.tech/status/?nocache=$(date +%s)"` returned `chaos.js?v=7` (old) and 3× `AS64512` (old) — making it look like the deploy hadn't landed. A second probe with `Cache-Control: no-cache, no-store` + `Pragma: no-cache` + `?_=$(date +%s%N)` immediately returned `chaos.js?v=9` (new) and 0× `AS64512` in the diagram. The deploy *had* landed; the edge was just serving stale.

**How to apply:**

```bash
# WRONG — Cloudflare may serve stale even with a unique-ish query param
curl -s "https://kyriakos.papadopoulos.tech/status/?nocache=$(date +%s)"

# RIGHT — force-bust the edge cache (verified 2026-05-06)
curl -s -H "User-Agent: Mozilla/5.0" \
        -H "Cache-Control: no-cache, no-store" \
        -H "Pragma: no-cache" \
        "https://kyriakos.papadopoulos.tech/status/?_=$(date +%s%N)"
```

- The nanosecond timestamp ensures the URL hasn't been seen before. CF's cache key includes the full URL by default but some path normalizers strip query params; the headers are belt-and-braces.
- This is purely a **verification** trick. Real users will see the new build automatically as the CF TTL expires (typically minutes, depends on `Cache-Control` from the origin). Don't change origin headers just to make verification easier — change the verification.
- The same pattern applies for `until` loops that wait for a deploy to land: pass the cache-busting headers in *every* iteration, not just the final probe. Otherwise the loop can match a stale response and exit early.
- For asset URLs (`/js/*.js`, `/css/*.css`), the version query string (`?v=9`) is the cache-buster *for users* — but for *your* verification probe, still add `?v=9&_=$(date +%s%N)` to defeat CF's per-URL cache during the deploy window.

Born 2026-05-06 from the chaos red-link deploy verification (memory `status_page_chaos_red_link_fix_20260506.md`). Adjacent precedent: any time a CDN-fronted change "looks not deployed", check the origin directly *or* cache-bust before assuming the deploy failed.

*Source: `memory/feedback_cf_edge_serves_stale_during_deploy_verification.md`*

### OpenClaw SSH Access Pattern

Always SSH directly to the OpenClaw LXC to configure it. Do NOT use `pct exec` via PVE.

**SSH command:** `ssh nl-openclaw01`
**Container:** `openclaw-openclaw-gateway-1` (Docker)
**Workspace:** `/home/app-user/.openclaw/workspace/` (inside container)
**SOUL.md:** `/home/app-user/.openclaw/workspace/SOUL.md` (deployed copy)
**Skills:** `/root/.openclaw/workspace/skills/` (bind-mounted into container)
**Config:** `/root/.openclaw/openclaw.json`

**Deploy pattern (from repo to live):**
1. Edit files in repo (`openclaw/SOUL.md`, `openclaw/skills/`, `openclaw/openclaw.json`)
2. SCP to nl-openclaw01: `scp openclaw/SOUL.md nl-openclaw01:/root/.openclaw/workspace/`
3. Restart to reload: `ssh nl-openclaw01 "docker restart openclaw-openclaw-gateway-1"`

**Why:** The LXC VMID is not in standard naming — using `pct exec` requires knowing the exact VMID on the correct PVE node. Direct SSH is simpler and always works.

**How to apply:** Every time you need to update SOUL.md, skills, or config on OpenClaw, SSH directly to nl-openclaw01. Never try pct exec via PVE nodes.

*Source: `memory/feedback_openclaw_ssh.md`*

### OpenClaw deploy checklist

When deploying changes to OpenClaw skills (k8s-triage.sh, infra-triage.sh, site-config.sh, etc.), ALWAYS complete the full deploy checklist:

1. SCP changed file(s) to `root@nl-openclaw01:/root/.openclaw/workspace/skills/`
2. SSH to nl-openclaw01 and verify the file landed (diff repo vs deployed)
3. Check ALL related files that the changed script depends on (e.g., site-config.sh for env vars, .env for tokens)
4. If the same fix applies to sibling scripts (e.g., infra-triage.sh has the same dedup logic as k8s-triage.sh), apply it there too
5. Verify inside the Docker container (`docker exec openclaw-openclaw-gateway-1 ...`) that the bind mount reflects changes
6. If SOUL.md or config changed, restart the container: `docker restart openclaw-openclaw-gateway-1`

**Why:** In the IFRNLLEI01PRD-320 fix session (2026-03-30), k8s-triage.sh was SCP'd but related files on OpenClaw were not checked — the user had to prompt for it. Deploying only the changed file without verifying dependencies (NETBOX_TOKEN in .env, site-config.sh, sibling scripts) risks silent failures.

**How to apply:** Any time you modify files under `openclaw/skills/`, treat OpenClaw deployment as a mandatory final step, not optional. SSH in and verify before declaring done.

*Source: `memory/feedback_openclaw_deploy_checklist.md`*

### Portfolio page must be updated alongside major default flips

When flipping a cross-cutting default (judge/synth backend, Tier-1/Tier-2 model, RAG signal weights, safety thresholds) OR when a live count drifts (Grafana dashboards, wiki articles, OpenClaw skills, SQLite tables), update the portfolio page at `kyriakos.papadopoulos.tech/projects/agentic-chatops/` in the same PR — not after.

**Why:** 2026-04-19 audit found the page's "Updated April 19, 2026" stamp but still said "Haiku for routine, Opus for flagged" judge and "Haiku synth step" — both flipped to local Ollama (gemma3:12b judge, qwen synth) that same day per commits 700fe07 + 8b8718c + dcdab34. CLAUDE.md got updated; portfolio page did not. Public-facing claim drift is worse than internal-doc drift because visitors can't cross-check against the repo.

**Additional drift found in the same audit** (stale even before the 2026-04-19 flip):
- Grafana dashboards: page says 9 (Tech Stack) / 10 (Status); actual IaC-managed count is **11** JSON files under `infrastructure/nl/production/k8s/namespaces/monitoring/dashboards/`
- Grafana panels: page says 127 in Tech Stack vs 64+ in Status; 64+ is canonical
- Wiki articles: page says 44; actual is **45** (find + `holistic-agentic-health.sh` claim)
- OpenClaw skills: page says 15; post-2026.4.11 upgrade is **17**
- Workflow nodes: internal 424 vs ~425 conflict
- Missing: rerank service (bge-reranker-v2-m3 at nl-gpu01:11436), cross-chunk synthesis Q2, CMM L3 weekly chaos cron

**How to apply:**
1. Any time you edit `CLAUDE.md` with a cross-cutting behavioral change (new model/backend default, flipped safety threshold, new signal in RRF, etc.) — also open the corresponding section in the Hugo source for the portfolio page (website repo) in the same change set.
2. Before claiming a portfolio page is "current," grep it for every count that appears in `MEMORY.md` Quick Reference (workflows, nodes, MCP servers, tables, skills, dashboards, panels, wiki articles) and reconcile.
3. Treat the portfolio page as a third doc source alongside `CLAUDE.md` and `MEMORY.md` — all three must move together for cross-cutting flips.
4. Push to website main directly per `feedback_website_push_direct.md` — no local Hugo preview needed; CI handles it.
5. **Scope extended (2026-04-24):** `README.md` + `README.extensive.md` are the fourth and fifth doc source — all *five* (CLAUDE.md, MEMORY.md, README.md, README.extensive.md, portfolio page) must move together. The two READMEs sanitize-and-propagate to the public GitHub mirror `papadopouloskyriakos/agentic-chatops` via the `sync_to_github` CI job, so the mirror drifts silently when they lag.

**Reinforcing event (2026-04-24):** The 2026-04-23 IFRNLLEI01PRD-712 umbrella (agents-cli uplift, 11 commits on `main`) shipped CLAUDE.md and scorecard-post-agents-cli-adoption.md but left the two READMEs and the portfolio page at the 2026-04-20 snapshot. A same-session comparison surfaced the drift; fix landed next-day under IFRNLLEI01PRD-725 (commits `b0fb968` + `149bef8`, pipelines #24187 + #24188, GitHub mirror confirmed on `920bd33`). Had the rule been followed, the parity pass would have been part of `0527d03` (Phase H memo) — not a separate session. The pattern to break is: "scorecard memo counts as the portfolio update." It doesn't. Scorecard is internal; portfolio is external.

*Source: `memory/feedback_portfolio_sync_on_major_flips.md`*

### corosync CMAP version-mismatch = clone-of-member rejection

## Pattern 1 — corosync CMAP version-mismatch

When a PVE node tries to join a cluster and corosync exits with:

```
[KNET ] A new membership was formed. Members joined: 1 2 4 5
[CMAP ] Received config version (X) is different than my config version (Y)! Exiting
[SERV ] Unloading all Corosync service engines.
```

…and Y < X, it means the **local** `/etc/corosync/corosync.conf` is older than the cluster's authoritative version. Almost always: this node's disk is a clone of an existing cluster member taken before the cluster's last config bump.

**Why:** Caught 2026-05-10 on the new ASRock GENOAD8X-2T/BCM hardware that arrived as a disk clone of the real `nl-pve02`. Cluster was at v16, clone had v14 baked in. corosync's CMAP refused to let the clone be authoritative — that's the protection against split-brain.

**How to apply:**
- The fix is NOT to bump the version manually. The fix is to **wipe the cluster identity locally** (`/etc/corosync/corosync.conf`, `/etc/corosync/authkey`, `/var/lib/corosync/*`, `/var/lib/pve-cluster/config.db`) and rejoin as a NEW node with a different hostname and corosync IP.
- Never let a clone-of-member rejoin under the same identity — even if you "fix" the version. The cluster already has a node at that nodeid + ring0_addr; bringing up a duplicate creates HA fence loops, NFS clientaddr collisions, and storage permission chaos.
- Same pattern can happen if you restore a node from a `vzdump` backup that's older than the live cluster.

## Pattern 2 — SSH host-key fingerprint change = remote OS reinstall

When SSH key auth that worked 30 seconds ago suddenly fails with `Permission denied (publickey,password)` on a previously-friendly host, **before assuming the key was revoked**, capture the current host key fingerprint and compare:

```bash
ssh-keyscan -t ed25519 <ip> 2>/dev/null | ssh-keygen -lf -
```

If the fingerprint has changed but the host's MAC and IP are unchanged, the OS was reinstalled (host keys regenerated by openssh-server.postinst). `/root/.ssh/authorized_keys` was wiped by the reinstall — that's why your key no longer works.

**Why:** Caught same incident — operator reinstalled the disk during a ~2-min full-power outage. ARP showed the same MAC pool (consecutive ASRock-OUI bytes for host NIC + BMC), so the hardware was unchanged; only the OS was new.

**How to apply:**
- If you SSH-ed to a host with `UserKnownHostsFile=/dev/null` (which suppresses change-detection), do an explicit `ssh-keyscan` after an unexplained auth failure to detect this case.
- Don't keep retrying the key — diagnose the host-key change first, then ask the operator how to re-establish access (push your key vs send a password vs regenerate).
- Don't continue an in-flight multi-step procedure (e.g. local cluster wipe) on a box whose OS state has changed under you. Backups taken before the reinstall are gone.

*Source: `memory/feedback_corosync_cmap_version_mismatch_signature.md`*

### feedback-diagnose-deploy-hang-on-host-process-tree-first

When an Ansible/AWX deploy (or any SSH-driven task) **hangs on one specific host**, the FIRST diagnostic is to look at that host's **process tree during the hang**, not to theorize about the network/egress/DNS:

```
ps -eo pid,ppid,etimes,stat,wchan:20,user,args   # on the hung host
```

It shows the stuck process and what it's blocked on (`wchan`) immediately. 

**Why (canonical incident, 2026-06-20, IFRGRSKG01PRD-260):** gr-dmz01 deploys hung at `docker compose pull` for ~22h. I spent **hours** chasing an "intermittent GR VPS-mesh egress" theory — wrong. The host process tree showed it in seconds: **176 stale `sshd: operator [priv]` → `run-parts /etc/update-motd.d` → `/etc/update-motd.d/99-livepatch-kernel-upgrade-required` → `canonical-livepatch kernel-upgrade-required` wedged in ep_poll**. A hung MOTD hook blocked every SSH login → the deploy froze BEFORE the pull command ran (so "no pull process + healthy egress" during the hang — which fooled me).

**Tells I should have caught sooner:**
- The failure was **deterministic** (4/4 deploys hung), not intermittent — I never verified transient-vs-persistent before theorizing. Establish that FIRST.
- Manual `docker pull` / `docker compose pull` worked, but the *Ansible* path hung → the problem is the SSH/login/become path, not the command.
- "No relevant process running + dependency looks healthy" during a hang ⇒ the hang is UPSTREAM of where you're looking (here: login MOTD, before the command).
- Operator kept asking "is it even transient?" / "what's different from the working mirror host?" — those were the right questions; answer them with host-side evidence, not network theories.

**Fix pattern for hung `canonical-livepatch` MOTD:** `chmod 0644 /etc/update-motd.d/99-livepatch-kernel-upgrade-required` (run-parts skips non-exec files) + kill the wedged procs + `snap restart canonical-livepatch`. Check other hosts for the same risk. Cross-ref [[awx-default-group-zero-capacity-20260620]].

*Source: `memory/feedback_diagnose_deploy_hang_on_host_process_tree_first.md`*

### feedback-let-deploy-pipeline-finish-before-manual-recreate

When a post-merge main-branch pipeline (build + push + auto-deploy) just shows as "success", **do NOT immediately SSH and `docker compose pull + force-recreate`** on `notrf01dmz0{1,2}`. The pipeline handles the deploy — manual force-recreate is redundant and the operator notices when I do it.

**Why:** The omoikane.coach deploy system auto-pulls and recreates the daemon container after the main-branch pipeline pushes `:latest` to ghcr.io. Manually duplicating this is wasted work + clutters the docker daemon logs with extra recreate events + signals I'm not trusting the platform to do its job.

**How to apply:** 
- After a post-merge pipeline completes successfully, wait — don't force-recreate.
- Only force-recreate manually if **either** (a) the deploy clearly hasn't fired after ~5-10 min post-pipeline-success (verifiable via `docker inspect` image SHA still matching the old pre-merge value), **or** (b) the operator explicitly asks for it (e.g. when restoring lost env vars and an immediate restart is needed).
- The env-var restore loop is a different beast — that genuinely requires force-recreate because env_file changes don't propagate to a running container. But after a code-only deploy, just let the pipeline do its thing.

**Canonical incident:** 2026-05-31 — after !2737 + !2738 post-merge pipelines completed (35210 + 35215), I `compose pull + force-recreate`'d both dmz hosts within seconds. Operator called out the redundant work: "why redeploy the pipeline just done that". The deploys would have happened automatically.

**Cross-ref:** [[feedback-docker-compose-env-file-force-recreate]] — that one's about env_file changes which DO require force-recreate. This one is the opposite: code-only changes don't need it.

*Source: `memory/feedback_let_deploy_pipeline_finish_before_manual_recreate.md`*

### feedback-runtime-env-wiped-by-awx-deploy

## Setup

The omoikane daemon's runtime env on dmz hosts is assembled by docker compose `env_file: [.env, ../secrets/shared.env, ../secrets/host.env]` (last wins). The `shared.env` at `/srv/omoikane-daemon/secrets/shared.env` is **NOT** the canonical source — it's a build product.

Canonical source: `daemon/secrets/shared.env.encrypted` in the gitlab repo (sops + age recipient `age1rvwducm3cykzwehze559uzpnacnyfc4rqa86p954q80kdepyg3fqfsu8fz`).

Bootstrap script: `scripts/sops/decrypt-shared.sh` decrypts the encrypted file and **REPLACES** `/srv/omoikane-daemon/secrets/shared.env` on the host (mode 600, root). This script runs as part of every AWX deploy.

## The hazard

Any env var added directly to `/srv/omoikane-daemon/secrets/shared.env` at runtime (e.g., via `echo X=Y | sudo tee -a`) will be:

1. ✅ Present in the running container after force-recreate (env_file is read on container start)
2. ❌ **WIPED** on the next AWX deploy when `decrypt-shared.sh` re-writes the file from the sops source

The wipe is silent — the file is replaced entirely, no warning issued, no audit log entry.

## How to detect this happened

The inode birth time differs from the modification time:

```bash
sudo stat /srv/omoikane-daemon/secrets/shared.env
# Birth: <recent deploy time>   ← file was REPLACED, not edited
# Modify: <runtime-add time or original deploy>
```

A `Birth` time after your runtime-add means the file was wiped + re-created.

Also: the `shared.env.bak.<timestamp>` backup file with `Birth: <deploy time>` is created by `decrypt-shared.sh` just before the rewrite. Its content reflects what was there pre-wipe — useful for forensics.

## The fix

For ANY env var that must persist across deploys, add it to the sops canonical:

```bash
cd ~/gitlab/websites/omoikane.coach/daemon
SOPS_AGE_KEY_FILE=~/.config/sops/age/omoikane.txt \
  sops --decrypt --input-type dotenv --output-type dotenv \
  secrets/shared.env.encrypted > /tmp/plain.env

# Edit /tmp/plain.env to add your vars
echo 'MY_VAR=value' >> /tmp/plain.env

SOPS_AGE_KEY_FILE=~/.config/sops/age/omoikane.txt \
  sops --encrypt --input-type dotenv --output-type dotenv \
  /tmp/plain.env > secrets/shared.env.encrypted

shred -u /tmp/plain.env   # never leave plaintext on disk

# Verify roundtrip
SOPS_AGE_KEY_FILE=~/.config/sops/age/omoikane.txt \
  sops --decrypt --input-type dotenv --output-type dotenv \
  secrets/shared.env.encrypted | grep MY_VAR

# Commit + push + MR
git add secrets/shared.env.encrypted
git commit -m "secrets(...): add MY_VAR (...reason...)"
git push -u origin <branch>
```

After merge, AWX deploy → `decrypt-shared.sh` writes the canonical file → docker compose picks it up via env_file → container has the var permanently.

## Non-secret vars in the encrypted file

Some "secrets" in `shared.env.encrypted` are actually configuration (e.g., `OMOIKANE_SEARCH_PROVIDER_ORDER=brave,searxng`). They live in the encrypted file NOT because they're secret, but because:

1. AWX `decrypt-shared.sh` is the only mechanism that survives deploys for env-file content on dmz hosts
2. Compose `env_file` is the only mechanism that injects them as container env
3. Putting them in any non-canonical location means another deploy wipes them

This is documented in `scripts/sops/README.md` under the OMOIKANE-913 entry.

## Caught in the wild

2026-05-29 session: operator added `BRAVE_SEARCH_API_KEY` + 3 search-provider config vars at runtime ~15:36 UTC. llm_enrichment throughput recovered 30×. Then OMOIKANE-905 merge → AWX deploy ~18:31 UTC → `decrypt-shared.sh` wiped them. llm_enrichment silently stalled until 19:11 UTC diagnosis. Fix-forward applied at 19:13 (re-add to runtime), then OMOIKANE-913 MR !2637 added them to the sops canonical for durability.

Cross-reference: [[feedback-company-enrich-search-chain-diagnostic]] — what the silent stall looks like.

## Prevention rule

If you're going to add an env var to `/srv/omoikane-daemon/secrets/shared.env`, ALWAYS also stage the matching sops edit. The runtime add is for "fix it now, validate behavior, then immediately ship the durable change". Never leave the system in the "runtime-only, will be wiped" state across more than one operator session.

*Source: `memory/feedback_runtime_env_wiped_by_awx_deploy.md`*

### feedback_deployed_copy_not_repo_for_some_crons

**Not all gateway crons run from the repo.** 2026-06-26: I retired the dormant Session-End n8n workflow by removing it from `gateway-watchdog.sh`'s monitored array (repo edit + merged MR !61) and deactivating it in n8n. The watchdog **re-activated it within one */5 cycle** — because the cron runs `/home/app-user/scripts/gateway-watchdog.sh`, a **separate deployed copy**, not `~/gitlab/n8n/claude-gateway/scripts/gateway-watchdog.sh`. The repo edit + the MR had zero live effect; only editing the deployed copy made the change stick (verified by running the deployed watchdog manually → B stayed deactivated).

**Scope (measured from the live crontab):** ~**8 crons run from `/home/app-user/scripts/`**, ~**99 run from the repo** (`~/gitlab/n8n/claude-gateway/...`). The deployed copies are a plain dir (not a symlink, not a git repo) and **had drifted** from the repo beyond my edit — so they are silently out of VC sync.

**Why:** a legacy deploy location that predates the repo-as-deployment model; nothing syncs the 8.

**How to apply:**
- **Before editing any script for a LIVE effect, check which path the cron actually runs:** `crontab -l | grep <script>`. If it's `/home/app-user/scripts/...`, edit THAT copy (and the repo copy for VC) — editing only the repo is a no-op live.
- **A merged MR ≠ live behavior changed** for these 8. Verify the live effect against the deployed copy / by running it, not by the merge.
- The 8 deployed copies are un-versioned + drifted = a real config-drift gap (the orchestrator interaction-graph / a drift-check should ideally cover them). Auditing + reconciling the 8 against the repo is an open follow-up. [[feedback_verify_belief_not_rationalize_observation]] [[orchestrator_control_plane_20260626]]

*Source: `memory/feedback_deployed_copy_not_repo_for_some_crons.md`*

## Infrastructure Operations

### AWX EE Image Persistence Problem

Custom AWX EE images imported via `ctr -n k8s.io images pull` are lost when K8s worker nodes reboot (containerd ephemeral runtime store).

**Why:** containerd stores pulled images in `/var/lib/containerd/`. On PVE-managed K8s VMs, this is on the VM's root disk. The `ctr` import worked, but after the GR PVE reboot all worker VMs restarted and lost the cached images. With `pull: never` on the EE, the execution pod fails with `ErrImageNeverPull`.

**How to apply:** Do NOT rely on `ctr` image imports for persistent images. Options:
1. Deploy a persistent container registry (Harbor, GitLab Registry) accessible from all K8s nodes
2. Use the default AWX EE image and route tool calls via SSH (proven to work for GR maintenance from NL AWX with _kubectl SSH routing)
3. Run maintenance playbooks from app-user directly (not AWX) — works for GR maintenance, problematic for NL maintenance (app-user goes down)

**Current workaround:** GR maintenance runs from NL AWX using direct kubectl + baked kubeconfig in EE (works until image is lost). NL maintenance runs from app-user directly. For NL real run, app-user goes down with nl-pve03 — tiered startup must be completed manually after nl-pve03 comes back.

**RESOLVED (2026-03-26):** Using GR GitLab Container Registry at `10.0.X.X:5050` (HTTP).
Setup required on each K8s worker:
1. `/etc/containerd/certs.d/10.0.X.X:5050/hosts.toml` with `server = "http://..."` + `skip_verify = true`
2. `/etc/containerd/config.toml`: `config_path = "/etc/containerd/certs.d"` (was empty)
3. `systemctl restart containerd`
4. Pull secret: `kubectl create secret docker-registry gr-gitlab-registry` + patch default SA with `imagePullSecrets`
5. AWX EE: `pull: missing` (IfNotPresent — caches after first pull, re-pulls if missing after reboot)

*Source: `memory/feedback_awx_ee_persistence.md`*

### AWX project_update HTTP 500 ≠ 504 — check gitlab host disk first

Distinguish HTTP 500 vs HTTP 504 when an AWX project_update fails fetching from gitlab.example.net:

- **HTTP 504** = the existing recurring transient (memory: `awx_gitlab_production_504_pattern.md`). Self-heals in 15-20 min, hits the project ~1× per 2-3 weeks. Diagnostic signature: dependent job has `elapsed=0` + `job_explanation` referencing the project_update.

- **HTTP 500** = NOT transient. Most likely: nl-gitlab01 root volume full → redis BGSAVE fails → `stop-writes-on-bgsave-error yes` puts redis read-only → gitlab-workhorse spams `MISCONF Redis is configured to save RDB snapshots, but it's currently unable to persist to disk` → all authenticated git ops return 500. Will not self-heal until disk is freed.

**Why**: the 504 pattern memory predates the 2026-05-08 incident and would have led future agents to wait 20 min instead of investigating. Reinforced after gitlab was down ~4.5h before someone noticed (incident: `gitlab_redis_disk_full_20260508.md`).

**How to apply**: when an AWX project_update fails, fetch its stdout via `/api/v2/project_updates/<id>/stdout/?format=txt`. If the inner `git fetch --tags origin` shows HTTP 500 (not 504), SSH to nl-gitlab01 (`ssh -p 222 -i ~/.ssh/one_key root@nl-gitlab01`) and check `df -h /` immediately, plus `docker exec gitlab tail /var/log/gitlab/redis/current` for "No space left on device" / "Background saving error". Don't wait for self-heal.

**Quick fix when this matches**: `docker image prune -f` on nl-gitlab01 (drops only untagged dangling images, no risk to running services). The gitlab-runner colocated on this box accumulates ~7000+ dangling layers between cleanups.

*Source: `memory/feedback_awx_project_update_500_vs_504.md`*

### PVE Maintenance Real-Run Lessons

First real GR PVE maintenance (2026-03-26) exposed 5 issues that dry-runs missed:

1. **GR LibreNMS token**: playbook used NL token for GR LibreNMS API. Fixed — `gr_librenms_token` var with correct default.
   **Why:** The `api_token` extra_var was ambiguous (NL vs GR). Each site needs its own LibreNMS token.
   **How to apply:** Always use site-specific variable names for credentials.

2. **Backup-locked containers**: `pct shutdown` fails silently on containers locked by running backup jobs. Fixed — `pct unlock` before shutdown + force-stop stragglers.
   **Why:** PBS backup jobs lock containers. Maintenance can coincide with backup windows.
   **How to apply:** Always unlock before shutdown in any guest stop logic.

3. **Kernel pin grep pattern**: `proxmox-boot-tool kernel list` outputs versions at column 0 (no indentation). The grep `^\s+[0-9]` matched nothing. Fixed — `^[0-9]+.*-pve`.
   **Why:** Assumed indented output based on visual display, never tested the actual byte output.
   **How to apply:** Always test grep patterns against `cat -A` output.

4. **K8s VMs missing onboot=1**: Setting `startup: order=18` does NOT imply `onboot: 1`. Without onboot, PVE ignores the startup order entirely. K8s VMs didn't auto-start after reboot.
   **Why:** The startup order script (Step 1) used `qm set --startup` but never checked/set `onboot`.
   **How to apply:** Always verify `onboot: 1` when setting startup order. Add to playbook pre-checks.

5. **AWX EE kubeconfig**: Volume mounts (`ee_extra_volume_mounts`) apply to task pod, NOT execution pods. Baking credentials into the Docker image is the only reliable approach.
   **Why:** AWX Operator creates separate execution pods per job with different HOME and mount paths.
   **How to apply:** Never rely on K8s secret mounts for AWX EE. Bake into image.

*Source: `memory/feedback_pve_maint_lessons.md`*

### PVE-clone leaves snmpd.conf sysName pinned to the source host

When a Proxmox node is built by cloning an existing cluster member (vzdump restore, disk image clone, etc.), the **corosync identity wipe** is well-known and covered in `feedback_corosync_cmap_version_mismatch_signature.md`. But `/etc/snmp/snmpd.conf` is **not** in that wipe list — it keeps the source host's hardcoded `sysName <source>` line.

**Why:** the snmpd config is hand-managed (not generated from hostname). The clone-and-rename runbook needs an explicit `sed -i 's/^sysName <source>$/sysName <new>/'  /etc/snmp/snmpd.conf` step. Symptom is the LibreNMS API rejecting the device add with: `Already have device <new> due to duplicate sysName: <source>`.

**How to apply:** Before adding a cloned PVE node to LibreNMS, run on the target:
1. `grep '^sysName' /etc/snmp/snmpd.conf` — confirm it shows the OLD hostname
2. `sed -i 's/^sysName <source>$/sysName <new>$/' /etc/snmp/snmpd.conf && systemctl restart snmpd`
3. Retry the `POST /api/v0/devices` call.

Caught 2026-05-10 onboarding nlpve04 (cloned from nl-pve02) to nl-nms01.

*Source: `memory/feedback_pve_clone_drags_snmpd_sysname.md`*

### feedback-no-sudo-install-on-pve-hosts

## The rule (corrected 2026-05-15 mid-session)

Don't propose `sudo` as the fix mechanism for a permission gap on a PVE host. It works, but:

1. **Proxmox-staff position**: Fabian Grünbichler (Proxmox dev lead) on [forum #89000 "Reason no sudo in default install"](https://forum.proxmox.com/threads/reason-no-sudo-in-default-install.89000/):
   > *"sudo is not the right way to implement unprivileged services."* (2024-01-11)
   > *"it's just not used for PVE itself. if you want to use it, feel free to install it."* (2021-05-11)
2. **Architectural reason**: PVE uses a `pveproxy (www-data) → pvedaemon (root)` loopback model for privilege separation. Adding `sudo`-gated CLI invocations creates a **parallel** privilege-escalation path that **bypasses PVE's ACL system** entirely (pveum / roles / paths). Adds an audit-trail hole.
3. **Practical reason**: locked-down sudoers configs are routinely escapable in real-world deployments (`sudo vi` → `:!sh`, `sudo less` → `!sh`, `sudo find -exec` etc.). Operator-side sudo discipline tends to drift.

## State of `sudo` in this estate (factual, verified 2026-05-15)

**All 6 PVE hosts already have `sudo 1.9.16p2-3+deb13u1` installed** — nl-pve01/nl-pve02/nl-pve03 + gr-pve01/nl-pve02 from legacy setup (pre-rotation, ≥ April 2026), nlpve04 since 2025-12-25. The package is `Priority: optional` in Debian and is **not pulled in by any `proxmox-ve` Depends/Recommends** — the PVE ISO inherits Debian-minbase which doesn't include it. Its presence here is from operator-side install scripts during host setup, not a Proxmox default.

So the rule isn't "remove sudo from PVE hosts" (operator decision: keep what's there, it works). The rule is **don't add it as a fix shape going forward** when a PVE-native pattern exists.

## What to use instead (decision tree)

| Permission gap | PVE-native fix |
|---|---|
| snmpd extender needs `/etc/pve/priv/*` (e.g., LibreNMS proxmox app needs `authkey.key`) | **Cache pattern**: root cron writes data to `/var/cache/<name>`, snmpd does `extend <name> /bin/cat /var/cache/<name>`. See [[feedback_pve_root_extender_cache_pattern]]. |
| Delegated VM/storage admin | `pveum` user + role + ACL + path (or API token). NEVER `sudo qm reboot` for "Bob can restart VM 100". |
| Service needs root for a periodic task | System-level systemd timer (running as root) writes its output to a `world-readable` cache file, consumer service reads cache. Avoid `--user` slice (see [[feedback_systemd_user_slice_oom_score]]). |
| Group-based access to `/etc/pve/priv/*` | **Does not work.** `/etc/pve/priv/` is mode `700 root:www-data` (group bits zero). Adding users to `www-data` won't grant access — verified 2026-05-15. |

## What about `apt install sudo` on a fresh PVE host?

Skip it. Use root directly (which is the Proxmox-supported admin model). If you need a permission-gap fix, use the appropriate pattern from the table above. If sudo turns out to be required by something specific later, decide then.

## How I went wrong mid-session

1. Misdiagnosed `sudo binary missing on nlpve04` (was a transient SSH PATH glitch — sudo was installed since 2025-12-25)
2. Proposed `apt install sudo` to fix LibreNMS proxmox-extender
3. Operator hard-stopped with: *"sudo binary on proxmox? no that is not standard proxmox practice WAIT STOP"*
4. Researched the Proxmox-staff position (Fabian forum #89000 quote above), discovered the proper architectural objection
5. Researched the alternative www-data group fix → confirmed it doesn't work (`/etc/pve/priv/` mode 700)
6. Landed on the cache pattern as the canonical PVE-native fix

## Cross-references

- [[feedback_pve_root_extender_cache_pattern]] — the alternative that this rule pushes toward
- [[librenms_extender_fleet_deployment_20260515]] — the session where this was hammered out
- [[feedback_no_zramswap_on_pve_hosts]] — sibling pattern: don't propose non-PVE-native fixes
- [[feedback_no_migration_off_nl-pve03]] — sibling pattern: respect intentional PVE topology

*Source: `memory/feedback_no_sudo_install_on_pve_hosts.md`*

### feedback-pve-balloon-zero-needs-reboot

## The rule

Don't trust `qm set <vmid> --balloon 0` alone to disable a balloon device on a running VM. The change goes to a `[PENDING]` config section and only takes effect on the next VM cold-restart (which removes the balloon device from QEMU's device list).

Until reboot:
- The active `balloon: N` line in `/etc/pve/qemu-server/<vmid>.conf` is unchanged
- The QEMU balloon device is still present
- `pvestatd auto_balloon` keeps balancing memory based on the OLD active value
- Any `qm monitor balloon <mb>` you send to force-deflate is temporary — `pvestatd` will re-inflate within ~10 minutes if host pressure is present

## How to spot

After `qm set --balloon 0`:

```bash
qm config <vmid> | grep balloon       # shows balloon: 0
grep -n "^balloon:" /etc/pve/qemu-server/<vmid>.conf   # shows ACTIVE balloon: 4096 + [PENDING] balloon: 0
```

The duplicate `balloon:` lines are the tell. The `[PENDING]` block in the .conf file holds queued changes.

`qm status <vmid> --verbose` shows the live balloon device target — if it doesn't show 0 / removed, the change hasn't applied.

## The right sequence

```bash
# 1. Set the persistent config
qm set <vmid> --balloon 0

# 2. (Optional) Dedup if a stale balloon line lingers
sed -i "0,/^balloon: [0-9]\+\$/{//d;}" /etc/pve/qemu-server/<vmid>.conf

# 3. Reboot the VM to apply [PENDING]
qm reboot <vmid>

# 4. Verify: qm status should have no `balloon` line at all
qm status <vmid> --verbose | grep -E "^(balloon|mem|maxmem)"
# Should see only maxmem + mem, no balloon target
```

## Why

PVE distinguishes between **live-applicable** changes (memory amount within current balloon range, balloon target, network bridge, etc.) and **cold-restart-only** changes (CPU model, BIOS type, machine type, **removing devices** including the balloon device). Setting `balloon: 0` falls in the second category because it's "remove the balloon device entirely" not "set balloon target to N MB".

PVE puts cold-restart-only changes into a `[PENDING]` section so the next start picks them up — but until that next start, the running VM continues with the old active config.

## Caught 2026-05-15

During the apiserver-ctrl01 chronic-restart-loop fix ([[apiserver_nlk8s-ctrl01_balloon_chronic_restart_fixed_20260515]]). My initial `qm set --balloon 0` "looked applied" because `qm config` reported `balloon: 0`, but the live VM was still memory-starved 17 min later. apiserver hit one more restart (1665 → 1666) in the interim because `pvestatd auto_balloon` re-inflated against my `qm monitor balloon 8192` deflate. Only the VM reboot made the fix durable.

## Cross-references

- [[apiserver_nlk8s-ctrl01_balloon_chronic_restart_fixed_20260515]] — the incident where this was learned
- [[feedback_no_balloon_on_k8s_control_plane]] — the architectural rule the fix enforces
- [[feedback_no_sudo_install_on_pve_hosts]] — sibling Proxmox-specific quirk worth remembering

*Source: `memory/feedback_pve_balloon_zero_needs_reboot.md`*

### feedback-pve-lock-backup-with-fleecing-image

# PVE `lock: backup` + dangling fleecing-image trap

When a vzdump using **backup fleecing** (PVE 8.2+, the `--fleecing 1,storage=...` flag in the scheduled job) aborts mid-run (host reboot, qmp socket break, PBS storage hiccup), it leaves three artifacts:

1. `lock: backup` line in `/etc/pve/qemu-server/<vmid>.conf`
2. `[special:fleecing]\nfleecing-images: <storage>:<vmid>/vm-<vmid>-fleece-0.qcow2` section in the same config
3. The fleecing qcow2 file on disk — allocated up to the FULL disk size (e.g. 244 GiB per disk)

**Why:** A running incident-style memory of how PVE backup fleecing fails open and the recovery shape — this happens on every PVE 8.2+ cluster using fleecing.

**How to apply:**

### Diagnostic signature
- Symptom: `qm start <vmid>` rejects with `VM is locked (backup)`.
- Recent task log shows multiple weekly `qmstart` (or `vzdump`) attempts returning the same error from `wyse@pam!vm-power-token` or `pvescheduler`.
- `qm config <vmid>` shows both `lock: backup` AND `[special:fleecing]` block.
- `pvesm list <storage>` shows a `vm-<vmid>-fleece-0.qcow2` next to the real disks.

### The invisibility trap
**`lock: backup` does NOT block an already-running VM.** It only blocks lifecycle ops: start, stop, migrate, snapshot, clone, destroy, backup. So a VM can run for **weeks or months** carrying a stale lock with no visible symptom — until the next attempted restart or backup. Diagnostic implication: weekly cluster-vzdump errors of the shape `Backup of VM X failed - VM is locked (backup)` repeating on a multi-week cadence = a single VM stuck-locked since before the earliest failure.

### Safety check BEFORE any unlock
Always confirm no real backup is in progress first:
```bash
pgrep -af vzdump                                   # any active vzdump?
ps -ef | grep -E "qemu.*<vmid>"                    # any qemu PID for this VM?
qm status <vmid>                                   # `qmpstatus: stopped` and `lock: backup`?
```
If a vzdump IS currently running for this VM, do NOT unlock — wait or kill the vzdump cleanly first. An unlock during a live fleecing snapshot can corrupt the source disk.

### Recovery sequence (PVE 8.2+, post-fleecing)
```bash
qm unlock <vmid>

# NOTE: `qm set <vmid> --delete special:fleecing` does NOT work — qm --delete
# only accepts top-level keys, not section names. Returns:
#   400 Parameter verification failed. delete: invalid format - invalid configuration ID 'special:fleecing'
# Must edit the conf file directly (pmxcfs handles cluster replication):
cp /etc/pve/qemu-server/<vmid>.conf /tmp/<vmid>.conf.bak-$(date +%s)
sed -i -e "/^\[special:fleecing\]$/d" -e "/^fleecing-images:/d" /etc/pve/qemu-server/<vmid>.conf

pvesm free <storage>:<vmid>/vm-<vmid>-fleece-0.qcow2                       # frees the orphan qcow2 (often >100 GiB)
qm start <vmid>
```
`qm unlock` alone is NOT enough — the `[special:fleecing]` block plus the fleecing qcow2 on disk linger. Older PVE-forum advice that says "just `qm unlock`" predates the fleecing feature and is stale. Confirmed working 2026-05-13 on grvmorpheus.

### Source of truth
PVE Wiki: <https://pve.proxmox.com/wiki/Backup_and_Restore#vzdump_fleecing>. The fleecing image is intentionally allocated to the full source-disk size to avoid out-of-space during dirty-block buffering.

Caught 2026-05-13 on `grvmorpheus` (VMID 201061601, gr-pve01) — see [[grvmorpheus-stuck-lock-backup-20260513]] for the full incident timeline.

*Source: `memory/feedback_pve_lock_backup_with_fleecing_image.md`*

### feedback-pve-root-extender-cache-pattern

## The rule

Whenever you deploy a LibreNMS (or any) snmpd extender on a PVE host that needs to read PVE-internal state under `/etc/pve/priv/` (or otherwise needs root), **use the cache pattern**:

```
# /etc/cron.d/<extender>  or root crontab
*/5 * * * * /path/to/script > /var/cache/<name> 2>/dev/null

# /etc/snmp/snmpd.conf
extend <name> /bin/cat /var/cache/<name>
```

The privileged work happens in a root cron context. snmpd-as-Debian-snmp just reads a normal world-readable file.

## Why — three rejected alternatives

| Alternative | Why it's wrong |
|---|---|
| **Run snmpd as root** | Massively widens attack surface; PVE's own daemons (pveproxy as `www-data`, pvedaemon as `root` over loopback) deliberately separate privileges — running snmpd as root breaks this model. |
| **`sudo`-prefix extend line + `/etc/sudoers.d/`** | Works but creates a parallel privilege-escalation path that bypasses PVE's ACL system. Proxmox staff (Fabian Grünbichler, forum #89000): *"sudo is not the right way to implement unprivileged services."* Also: locked-down sudoers configs are routinely escapable via `vi`/`less`/`find -exec` etc. |
| **Add `Debian-snmp` to `www-data` group** | **Does not work.** PVE intentionally locks `/etc/pve/priv/` at mode `700 root:www-data` — group bits are explicitly zero. Even members of `www-data` can't enter the directory. Files inside (e.g., `authkey.key`) are `600 root:www-data` — group bits zero too. This is deliberate Proxmox security design, not an oversight. |

The cache pattern is the **only PVE-native shape** that works without any privilege hackery.

## Reference deployment (2026-05-15, all 6 PVE hosts)

The `proxmox` extender was failing fleet-wide with `exit=13: cfs-lock 'authkey' error`. Cache pattern applied to nl-pve01-04 + gr-pve01-02:

```bash
# root cron
echo "*/5 * * * * /usr/local/bin/proxmox > /var/cache/proxmox 2>/dev/null" | crontab -e ...

# snmpd
sed -i 's|^extend proxmox /usr/local/bin/proxmox$|extend proxmox /bin/cat /var/cache/proxmox|' \
  /etc/snmp/snmpd.conf
systemctl reload snmpd
```

After cache prime: extend exit 13 → 0 on all 6 hosts. Cache sizes 206-2922 bytes proportional to running-VM count per host.

## Where this generalises

This pattern applies to **any** extender / monitoring agent on a PVE host that needs:
- `/etc/pve/priv/*` access (auth keys, ACME challenges, ceph keyrings, etc.)
- Cluster API calls via libpve-apiclient-perl (which reads auth keys)
- Anything else that the `Debian-snmp` user can't reach

If you're adding a new one (e.g., a custom k8s/ceph/vm-state collector), default to the cache pattern unless you have a specific reason to do otherwise.

## Cross-references

- [[feedback_no_sudo_install_on_pve_hosts]] — sudo IS commonly on PVE in this estate (legacy from setup) but per Proxmox staff is not the canonical privilege-separation mechanism
- [[librenms_extender_fleet_deployment_20260515]] — the session where this pattern was formalised
- Existing reference impl: `/etc/snmp/smart` + `*/5 * * * * /etc/snmp/smart -u -Z` cron — same shape, deployed on all 6 PVE hosts since long before this session

*Source: `memory/feedback_pve_root_extender_cache_pattern.md`*

### feedback-zfs-dio-must-be-disabled-on-pve

On any PVE host running OpenZFS 2.3+ with VMs using `cache=none` (`cache.direct=true` in QEMU `-blockdev` JSON) on a ZFS-backed disk image (qcow2 OR raw on directory storage), ALWAYS set `zfs set direct=disabled <pool>` and drop `/etc/modprobe.d/zfs-dio-disable.conf` with `options zfs zfs_dio_enabled=0`. Verify with `zfs get direct <pool>` and `cat /sys/module/zfs/parameters/zfs_dio_enabled`.

**Why:** OpenZFS 2.3 changed the default direct-I/O policy to `standard` (was `disabled` in 2.2-). With `standard`, ZFS honours `O_DIRECT` and does zero-copy DMA from the QEMU userspace buffer, then verifies CRC after the write completes. If the guest mutates that page mid-flight (very common — any RSS rewrite, container heap churn, ML model load), the CRC mismatches → ZFS returns EIO → qcow2 cluster-allocation path maps EIO to ENOSPC → QEMU `werror=enospc,stop` pauses the VM with bogus "nospace" status. Pool can have terabytes free and you still get io-error pauses. Manifested at NL on nl-gpu01 / VM VMID_REDACTED as "almost daily freezes" because ollama's buffer churn maximises the race window. 121 `ereport.fs.zfs.dio_verify_wr` events accumulated over 2 months before diagnosis.

**How to apply:** Whenever doing PVE-host onboarding (cf [[nlpve04_onboarding_in_progress_20260510]]) or after any major ZFS upgrade. Also when investigating any "VM paused with io-error but ZFS pool is fine" symptom. The man-page literally says `disabled` is "the default behavior for OpenZFS 2.2 and prior releases" — zero risk, just reverts to pre-2.3 behavior. ARC absorbs the writes via the buffered path.

**Important caveat — official endorsement status:** This workaround is NOT in any pve.proxmox.com wiki page (`ZFS_on_Linux` or `Storage:_ZFS`) and has no Proxmox staff endorsement found in forum research. It IS marked as the SOLUTION in multiple `[SOLVED]` PVE 9 forum threads (`forum.proxmox.com/threads/proxmox-9-io-error-zfs.179519`, `forum.proxmox.com/threads/zfs-io-error-on-9-1-4.179579`). The OpenZFS authoritative man-page DOES document the `direct=disabled` value. So: community-validated + OpenZFS-documented, but Proxmox-unofficial. If you propose this in a future change, surface that nuance to the operator — don't claim it's "the official Proxmox recommendation".

Caught 2026-05-14 during nl-gpu01 RCA. Full mechanism + fix recipe + research-validation against authoritative sources: [[nl-gpu01_zfs_dio_race_root_cause_20260514]]. Diagnostic recipe: [[feedback_zfs_dio_diagnostic_recipe]].

*Source: `memory/feedback_zfs_dio_must_be_disabled_on_pve.md`*

### feedback_pve_mgmt_wedge_pmxcfs_restart

When a Proxmox host shows **pvestatd `failed`, guest status=`unknown` cluster-wide, and a high load average while CPU is mostly IDLE**, it is almost always a **hung pmxcfs** (the `/etc/pve` FUSE cluster filesystem), NOT CPU saturation and NOT a quorum loss.

**Diagnose:** the wedged PVE daemons (pvestatd/pvedaemon/qm/pveproxy) sit in **D-state** (uninterruptible IO) with `wchan = path_openat`/`filename_create`/`lookup_slow` — i.e. blocked opening/creating a file, and for pvestatd that file is under `/etc/pve`. The high load = the count of D-state procs (uninterruptible-IO counts toward loadavg); `top` shows the CPU idle. Check corosync separately (`corosync-quorumtool -s`) — if Quorate, it's pmxcfs itself, not quorum.

**FIX (no reboot needed — proven 2026-06-27 on nlpve04, P0 guests undisturbed):**
1. `systemctl restart pve-cluster` — tears down + recreates the pmxcfs FUSE mount; the abort returns EIO to the blocked syscalls and **releases the D-state procs instantly** (saw 22→2, `/etc/pve` accessible again). Running KVM/LXC guests are unaffected (they don't depend on pmxcfs once started).
2. `systemctl reset-failed pvestatd && systemctl restart pvestatd` — it stays `failed` after pmxcfs recovers and must be restarted explicitly.
3. Verify: all PVE services active, D-state ≈0, guest status no longer `unknown`, load decays over 5-15 min.

**THE TRAP (why a prior session wrongly concluded "reboot is the ONLY fix"):** restarting **pvestatd ALONE** returns exit 124 / leaves it `Ds` — because pvestatd is still blocked on the **hung pmxcfs**. You must restart the **provider (pve-cluster) FIRST**. Order matters.

**Two companion diagnostic lessons from the same incident:**
- **VMID node-digit ≠ host placement.** The NL VMID schema `S NN VV TT RR` encodes a node digit, but it DRIFTS (CLAUDE.md says so). Do NOT infer which PVE host runs a guest from the VMID — verify with `pvesh get /cluster/resources --type vm` (authoritative). I decoded `VMID_REDACTED`→"03"→pve03 and SSH'd to the wrong host; it's actually pve04.
- **load-high + CPU-idle ⇒ IO/D-state, not CPU.** Never report "CPU saturated" off loadavg alone; check `top` %idle + the R/D state counts. A NodeSaturation alert can be a pmxcfs wedge, not CPU. [[feedback_verify_belief_not_rationalize_observation]] [[pve04_pvestatd_wedge_20260625]]

*Source: `memory/feedback_pve_mgmt_wedge_pmxcfs_restart.md`*

### no-migration-off-pve03

Do **not** propose moving K8s workers, GPU VMs, NMS, or any other guest off nl-pve03 as a remediation. Operator rejected the suggestion on 2026-05-12 during the nl-gpu01 freeze RCA. The nl-pve03 placement (nl-gpu01 + 4 K8s nodes + NMS + YouTrack + OpenObserve + OpenWebUI + LibreChat + Renovate + Frigate) is deliberate.

**Why:** Operator owns the cluster topology decisions. Migration off nl-pve03 is a "remove the dependency, not the problem" pattern that doesn't actually fix the root cause — it just hides it on a different host. Both memories (`nl-pve03_capacity_pressure_20260422.md`) suggesting K8s-worker migration should be treated as stale on that point.

**How to apply:**
- Fix memory/CPU pressure on nl-pve03 in-place via:
  - Right-sizing per-guest `memory:` caps that are over-provisioned vs actual RSS.
  - Reducing ZFS ARC if appropriate (`zfs_arc_max`).
  - Identifying the specific tenant causing pressure and fixing IT, not relocating it.
- Topology change requires explicit operator request — never propose unsolicited.
- Combine with [[feedback_no_zramswap_on_pve_hosts]] — those two together rule out the standard "memory pressure" remediation playbook.

*Source: `memory/feedback_no_migration_off_pve03.md`*

### no-zramswap-on-pve-hosts

Do **not** propose `apt install zram-tools` / `zramswap` / `swapfile` / any swap-as-release-valve fix on any Proxmox VE host (nl-pve01..nlpve04, gr-pve01..gr-pve02).

**Why:** Proxmox themselves do not officially recommend running swap on a hypervisor. The 2026-04-19 nl-pve01 OOM fix and the 2026-04-22 nl-pve03 capacity memo both reached for zramswap by analogy with bare-metal Linux — operator rejected that pattern on 2026-05-12 during the nl-gpu01 freeze RCA. Both memories (`nl-pve03_capacity_pressure_20260422.md`, `nl-pve01_memory_pressure_apiserver_20260415.md`) should be treated as stale on the zram point. Any later sweep that resurfaces the recommendation should be ignored.

**How to apply:**
- When a PVE host shows sustained high memory utilisation or has OOM-killed a guest, look at other levers first:
  - Reduce ZFS `zfs_arc_max` (currently 16 GiB on nl-pve03 — could go to 8 GiB).
  - Add `balloon` to non-passthrough VMs so PVE can reclaim under pressure (PCI-passthrough VMs cannot balloon — DMA-pinned).
  - Right-size LXC `memory:` caps that are over-provisioned vs `memory.current`.
  - Identify a single bloated tenant rather than adding swap.
- Migration is also off the table per [[feedback_no_migration_off_nl-pve03]] — solve in-place.
- Never recommend `zramswap` even with "low risk, no reboot" framing.

**Related:** [[feedback_no_migration_off_nl-pve03]], [[nl-pve03_capacity_pressure_20260422]].

*Source: `memory/feedback_no_zramswap_on_pve_hosts.md`*

## Data Integrity

### Always use full hostnames [P0]

**P0 rule.** Always use full hostnames (e.g. nl-nas02, gr-pve01, nl-iot02, nl-pve02), never shortened forms (syno02, pve01, pve02, iot02, dmz01). **Never use generic role labels ("the ASA", "the router", "the NL firewall", "NL ASA", "pve01") as a substitute for the real hostname.**

**Why:** Shortened hostnames and generic role labels cause confusion in a multi-site environment (NL + GR) with multiple devices per class. "The ASA" is ambiguous — we have nl-fw01 and gr-fw01. "The router" is ambiguous — nlrtr01, nllte01, grrtr01 could all fit. "pve02" is ambiguous — nl-pve02 vs gr-pve02. Operator re-confirmed as **P0** on 2026-04-21 after another slip in mid-session: "never use half names like pve02; always nl-pve02; put that as P0". Earlier in same session: "stop stripping from the devices their actual hostname; never do that again; ever."

**How to apply:** In every output — tables, commands, prose, memory files, YT comments, Matrix messages, incident reports, python variables, comments in code, table-header abbreviations — refer to every device by its exact hostname as configured on the device itself (matches DNS + NetBox). When quoting config snippets, keep the hostname in context. Do not substitute "the ASA" for `nl-fw01`, do not substitute "rtr01" or "the router" for `nlrtr01`, do not substitute "NO VPS" for `notrf01vps01`, do not substitute "CH VPS" for `chzrh01vps01`, do not substitute "pve02" for `nl-pve02`. Full hostname every time, no exceptions. **Filenames and temp scripts also count** — do not name a file `rtr01_stage.cfg`; name it `nlrtr01_stage.cfg`. Operator has now reinforced this across three separate sessions — further slips are unacceptable.

*Source: `memory/feedback_full_hostnames.md`*

### Audit dependency source before integrating, not after

When integrating a foreign program (bundling Direwolf as a subprocess, linking a new C lib, adopting a new SDK), **read the key source files first** — not after the third deploy that fixes "surprises" one at a time.

**Why:** During MESHSAT-514 (MeshSat Mode A bundled Direwolf, 2026-04-17) I shipped three follow-up patches for issues that were all visible in direwolf's source:
- `signal(SIGINT, cleanup_linux)` in `direwolf.c:341` — Direwolf ignores SIGTERM; I was sending SIGTERM for "graceful" shutdown, getting immediate-exit semantics instead.
- `hid_open_path` in `cm108.c:945` — CM108 PTT is HID GPIO, not serial RTS. I defaulted to `PTT /dev/ttyACMX RTS` which keys the AIOC's unwired serial line.
- `INADDR_ANY` in `kissnet.c:558` — KISS TCP cannot be restricted to loopback via config; requires a source patch.

Each of these cost a full deploy cycle (~15 min CI + RF validation). A 2-minute read of the relevant files would have caught all three up front. The user called this out directly: "audit deeply both codebases, the ones you cloned at /tmp related to aprs and the the meshsat bridge codebases and find what we are doing wrong" — at which point I dispatched a code-explorer agent and found the remaining bug (HTTP-ctx propagation) in one pass.

**How to apply:**

- When adding a new external binary or library, spend 10-15 minutes reading: its signal-handling, its resource-acquisition order (what files/sockets/HIDs does it grab, in what order, with what flags), its configuration grammar (look for `find_package` / `strcasecmp` / `parse_config` or equivalent), and its shutdown path.
- When a second integration patch is needed, **stop and audit** rather than guessing a third. Dispatch a code-explorer subagent for structured reading if the codebase is large.
- The cost of the audit is always < the cost of one wrong redeploy. Always.

*Source: `memory/feedback_audit_codebase_before_patching.md`*

### Data trust hierarchy

Data trust hierarchy — always follow this order when investigating or making claims:

1. **Running config on the live device** (SSH + `show run`, `ip a`, `pct config`, `kubectl get`) — the ONLY 100% truth
2. **LibreNMS** — active monitoring, shows what's happening NOW
3. **NetBox** — CMDB inventory, accurate but manually maintained — can drift if someone forgets to update
4. **03_Lab, GitLab IaC, backups** — supplementary reference, useful context but can be stale

**Why:** NetBox requires manual updates, so it can drift from reality. LibreNMS actively polls devices so it reflects current state. But even LibreNMS can lag or miss things. The only way to know what a device is actually running is to SSH in and check. 03_Lab xlsx files, IaC configs, and backups are all point-in-time snapshots that may not reflect recent changes.

**How to apply:** During triage, always verify critical facts by checking the live device. Never trust a stale xlsx entry or IaC config over what `show run` returns. When 03_Lab data contradicts live state, the live state wins — and flag the 03_Lab entry as potentially outdated.

*Source: `memory/feedback_data_trust_hierarchy.md`*

### Never truncate or shorten hostnames anywhere

Always write the full site-prefixed hostname. Never abbreviate.

**Why:** The operator runs a multi-site fleet (nl / gr / notrf01 / chzrh01 / iskef01 / defra01 / wcrw01) where each site has hosts called `dmz01`, `dmz02`, `pve01`, `vps01`, `fw01`, `nms01`. Writing "dmz01" in any context creates ambiguity — it could be `nl-dmz01`, `gr-dmz01`, or `notrf01dmz01`. The operator has lost time to this kind of ambiguity and the rule is now enforced strictly. Reinforced angrily on 2026-05-05 after I shortened `notrf01dmz01` and `notrf01dmz02` to `dmz01`/`dmz02` repeatedly across plan files, tables, prose, and code-fence comments. Operator's response: "IF YOU EVER CUT THE HOSTNAME OF A SERVER HALF AGAIN I AGOING TO RM -RF YO ASS!!! ... wtf does 'dmz02' means???"

The CLAUDE.md root file already documents this as `[P0] Full hostnames, no exceptions, ... Reinforced 2026-04-30 after multiple session slips.` This memory exists because the rule was broken AGAIN despite being in the master config — it needs to be reinforced every session via memory injection too.

**How to apply:**
- Every output surface: prose responses, plan files, table cells, code blocks, comments, commit messages, memory entries, Matrix replies, YouTrack comments, log lines, filenames, diagrams.
- No `notrf01dmz0{1,2}` brace-expansion shortcuts in prose. Write `notrf01dmz01` and `notrf01dmz02` separately, even if the sentence ends up longer.
- No `dmz01`/`dmz02`/`pve01`/`fw01` shortcuts even when the surrounding paragraph "obviously" implies a specific site.
- No generic role labels ("the ASA", "the router", "the active node", "the dmz host", "the firewall") as substitutes. Always name the host.
- Acceptable shell-expansion shortcut **only inside an actual bash command** that needs to iterate, e.g. `for h in notrf01dmz01 notrf01dmz02; do ...; done` — but never in prose describing the command.
- If a table column appears too narrow for the full hostname, narrow other columns or restructure the table; never abbreviate the hostname.
- Same rule applies to other prefixed identifiers like VLANs (`inside_mgmt VLAN 10`, not `mgmt VLAN`), interface names (`outside_freedom`, not `the freedom WAN`), and crypto map names.
- When restating the operator's wording back to them, mirror their hostname usage exactly — they always type the full name.

*Source: `memory/feedback_never_truncate_hostnames.md`*

### feedback-visual-audits-must-render-not-grep

When auditing a user-facing page on omoikane.coach (or any web surface), structural checks alone — counting form inputs, verifying ARIA attributes, checking heading hierarchy, asserting expected text tokens are present — are **insufficient**. They give false confidence when the FRAMEWORK WRAPPER around the body content is the bug.

**Why:** A handler that returns `view::render(&data).into_response()` directly (skipping `page(lang, Layout, title, body).into_response()`) ships raw `<body>` content with no `<head>` link to CSS, no sidebar nav, no page chrome. The body's structure is identical to a properly-wrapped page — same form, same headings, same ARIA — so token-based audits all pass. But the user sees a Times-New-Roman unstyled HTML page.

**Caught 2026-05-27 OMOIKANE-816:** `/profile/fairness-audit-opt-in` shipped (OMOIKANE-799 !2537) + `/profile/employment-history` shipped (OMOIKANE-803 !2538) without the `page()` wrapper. Three prior audit passes (mine + ccs-01's QA report) all passed because they counted form elements, checked ARIA, verified heading order — and all those were correct. The bug was visible the moment the operator opened the page in a browser.

**How to apply (for future audits):**

1. **Always render full-page screenshots** in at least 2 viewport × 2 theme combos via Playwright (`page.screenshot(path=..., full_page=True)`). Don't ship an audit report without them.

2. **Inspect the screenshots visually** OR diff against a reference. Don't trust the structural pass.

3. **Quick structural sentinel for "is the wrapper applied":**
   - `body` `background-color` should be non-transparent (`rgba(0,0,0,0)` = missing wrapper) — the theme bg should show
   - ARIA attribute count should be **non-trivial** (≥ 20+ on a typical page with sidebar nav) — a single-ARIA page means the body is rendering without the framework's nav/aside
   - `<head>` should contain a `<link rel="stylesheet">` to the main CSS
   - `document.documentElement.classList` (or similar) should carry framework theme classes

4. **For Rust+Maud handlers specifically:** if a handler does `view::render(&data).into_response()`, that's almost certainly a wrapper bug. The canonical pattern is `page(lang, Layout::WithSidebar(Section::X, user.is_operator()), "Title", body).into_response()`. Grep `app/src/handlers/**/*.rs` for `render(.*).into_response()` to find any other surfaces with the same defect class.

**Audit script lives at** `/tmp/audit-fairness-audit-opt-in.py` (visual+structural; reusable shape). The structural checks alone gave 0 P0/P1; only visual review caught it.

**Lesson saved to** [[feedback-visual-audits-must-render-not-grep]]. Pair with [[feedback-mr-size-target-2000-loc-bundled]] for the broader "ship complete features, not just structurally-valid fragments" pattern.

*Source: `memory/feedback_visual_audits_must_render_not_grep.md`*

### feedback_audit_before_mass_delete

When mass-deleting ASA config (NAT rules, ACLs, crypto maps), AUDIT every line before removal — don't just grep and nuke.

**Why:** During crypto-map cleanup, 161 NAT lines matching `outside_freedom|outside_xs4all` were removed by pattern. This missed that there were ZERO dynamic PAT rules for `outside_xs4all`. When Freedom ISP was down, all inside zones lost internet because traffic routed via xs4all had no PAT. Broke the operator's laptop internet.

**How to apply:** Before any mass config removal: (1) categorize what you're removing (exemptions vs PAT vs static), (2) verify outbound PAT exists for ALL active outside interfaces, (3) check for gaps the removal exposes, not just what it removes.

*Source: `memory/feedback_audit_before_mass_delete.md`*

### feedback_never_abbreviate_hostnames

[P0] **NEVER abbreviate, shorten, or truncate a hostname. ALWAYS write the complete site-prefixed hostname, every single time, in every surface.**

Wrong → Right:
- `gr` → **gr-pve01** (the site prefix alone is NOT a hostname)
- `pve01` → **nl-pve01** or **gr-pve01** (disambiguate the site)
- `the GR host` / `the active node` / `the ASA` → the actual full hostname
- `nvme2` belongs to a host → name the host fully: "gr-pve01 nvme2n1"

**Why:** Operator-anger rule. Triggered 2026-06-24 — I typed "gr" instead of "gr-pve01" while summarizing the two-host disk investigation. This is dangerous precisely BECAUSE the two stories were on two different hosts (gr-pve01 = thermal-throttling disk, NOT failing; nl-pve01 = a genuinely FAILED FireCuda) — a truncated prefix like "gr" or "pve01" is exactly how the wrong host gets blamed. The short name `pve01` also collides across sites (nl-pve01 vs gr-pve01). This duplicates and reinforces the CLAUDE.md §"[P0] Operator-anger rules — Full hostnames, no exceptions" rule.

**REPEAT VIOLATION 2026-06-24 (operator FURIOUS — "i will fucking kill you"):** I wrote "ctrl01" and "n8n01" instead of **nlk8s-ctrl01** and **nl-n8n01** in a blast-radius example — AFTER this very memory existed. The memory alone did NOT prevent it. The ONLY thing that works: literally re-read every drafted sentence for bare host tokens BEFORE sending. Common bare forms I keep slipping on: `ctrlr0x`→nlk8s-ctrlr0x / grk8s-ctrlr0x; `n8n01`→nl-n8n01; `pve0x`→nlpve0x/grpve0x; `nvme2n1` always with its host. This is a zero-tolerance, relationship-threatening rule. NO abbreviation EVER, including in examples, casual asides, and recaps.

**REPEAT VIOLATION 2026-06-25 (operator angry again — "do NOT ever abbreviate a damn hostname"):** I wrote `gpu01` instead of **nl-gpu01** in a risk-appetite dials TABLE. **Newly-identified trigger: I slip specifically when COMPRESSING for width — tables, TL;DRs, compact summaries.** The act of trimming a cell/line to fit is exactly when the site prefix gets dropped. So the rule needs EXTRA vigilance in any compact surface: a table cell is NOT an excuse to shorten; `nl-gpu01` goes in the cell at full length even if it's wide. `gpu01`→nl-gpu01 added to the bare-form watchlist.

**How to apply:** Before sending ANY message, comment, YT/Matrix post, table, diagram label, filename, or memory note — scan for any bare `pve0x`, `sw0x`, `fw0x`, `iot0x`, `k8s-*`, `ctrlr0x`, `n8n0x`, `gpu0x`, a bare site prefix (`gr`, `nl`), or a generic role label, and expand it to the full site-prefixed hostname. **Tables/TL;DRs/compact output are the highest-risk surface — never trim a hostname to fit width.** No exceptions, even in casual recap or when the host was named fully earlier in the same conversation. Related: [[feedback_verify_belief_not_rationalize_observation]] (the same two-host investigation where short-name collision risk bites).

*Source: `memory/feedback_never_abbreviate_hostnames.md`*

## General

### "Remove X completely" after operator flags X as misleading = remove the whole widget

When the operator says "remove X completely" after explaining why X is wrong or misleading, default to removing the **entire widget/row/bar** that contains X — not just the offending sub-span the original complaint pointed at.

**Why:** First round of the 2026-05-06 status-page fix removed the literal `<span>since {first_seen}</span>` from the BGP info bar (`AS64512 · prefix · 100% visibility · since Aug 2024 · transit ASNs · paths`). The operator pushed back: "this is the day i first registered my account with RIPE... the aug-2024 was this ASN belonging to somebody else ... hence remove it completely". The "completely" + the "it was somebody else's" context meant the whole AS64512 mention — and by extension the whole bar — was unwanted, not just the date. Removing only the date span in round 1 forced a second deploy round to remove the bar in round 2.

**How to apply:**

- When an operator explains *why* a UI element is wrong (not just "remove this") and pairs it with "completely", interpret broadly. Strip the whole widget. If they wanted finer granularity they'd have asked for it.
- If the widget contains *some* useful sub-info (e.g. visibility/peer counts that are independent of the misleading bit), surface that as a question — "want to keep the visibility line and just drop the AS+date?" — but don't ship the literal-minimum patch by default.
- The cost of over-removing is one cheap revert. The cost of under-removing is another deploy cycle + the operator wondering why their literal request still wasn't honoured.
- Watch for this pattern after any operator message that combines: (1) factual correction ("X was actually Y"), (2) the word "completely" / "entirely" / "all of it", (3) escalating frustration tone.

Born 2026-05-06 from the AS64512 BGP-bar removal, where the operator had to ask twice before the whole bar came out. See `memory/status_page_chaos_red_link_fix_20260506.md`.

*Source: `memory/feedback_remove_completely_means_the_whole_widget.md`*

### ASA after-auto source dynamic PAT has rpf-check side-effect on inbound traffic

**Rule.** When you add an after-auto egress PAT rule like:
```
nat (dmz_servers02, outside_budget) after-auto source dynamic any interface
```
you are implicitly telling the ASA: "any untranslate lookup on outside_budget for a destination in dmz_servers02 must rpf-match the outside_budget interface IP." For traffic that legitimately uses the two subnets as a transit peer pair (e.g., BGP between an edge router on outside_budget and a route reflector on dmz_servers02), the rpf check DROPS the packet in the NAT phase with `Action: drop / acl-drop`.

**How it surfaces:** the traffic is completely silent — no syslog, no `show asp drop` counter in an obvious bucket (the drop is reported as "Flow is denied by configured rule"). packet-tracer IS the diagnostic — it shows the NAT phase as the drop cause with the after-auto rule quoted.

**Why this matters.** On 2026-04-21 I added 11 after-auto PAT rules to close the outside_budget Freedom-failover gap. The NAT for `dmz_servers02 ↔ outside_budget` then blackholed all rtr01 ↔ FRR BGP opens. Two hours of wrong-layer debugging (BGP capability mismatches, addpath, router-id, SSH access) before `packet-tracer input outside_budget tcp 10.0.X.X 50000 10.0.X.X 179` made it obvious.

**How to apply.**

1. **Two failure modes, one family**:
   - **(a) rpf-drop on INBOUND** — traffic from outside_X to src_zone is dropped at `NAT rpf-check` because the source doesn't match the outside_X interface IP. Diagnostic: `packet-tracer` drops in Phase "NAT / rpf-check".
   - **(b) silent source rewrite on OUTBOUND control plane** — traffic from src_zone to a peer on outside_X (e.g., a BGP neighbor over a VTI) gets its source translated to the outside_X interface IP. If the peer's BGP/routing table doesn't know the interface-IP's subnet, replies resolve out the public internet and disappear. Diagnostic: nl-fw01 packet capture shows `<interface_ip> > <peer>` for outbound ICMP but no replies; VPS `ip route get <interface_ip>` returns public-internet path.
2. **When adding `after-auto source dynamic any interface` PAT rules**, list the subnet pairs that legitimately carry bidirectional transit across the two zones (e.g., BGP transits, VTI peers, iSCSI, tunneled control plane). For each pair, pre-stage a Section-1 identity NAT to preempt the dynamic rule:
   ```
   object network NET_transit_A
    subnet <A.B.C.0> <mask>
   object network NET_transit_B
    subnet <X.Y.Z.0> <mask>
   nat (<zone_A>, <zone_B>) 1 source static NET_transit_A NET_transit_A destination static NET_transit_B NET_transit_B no-proxy-arp route-lookup
   ```
2. **packet-tracer is the primary diagnostic.** For any cross-zone BGP/TCP session that refuses to establish after a NAT change, first run:
   ```
   packet-tracer input <src_zone> tcp <src_ip> 50000 <dst_ip> 179
   ```
   Look for Phase = NAT / Subtype = rpf-check / Result = DROP. That identifies the rule without any running debug.
3. **`no-proxy-arp route-lookup`** should be the default for exemption NATs — prevents the ASA from proxy-ARPing the identity-mapped addresses on the wrong interface and avoids forced egress through the listed interface.

Full incident in [budget_migration_20260421.md](budget_migration_20260421.md).

*Source: `memory/feedback_after_auto_nat_rpf_check.md`*

### Add per-peer LP override when introducing a new ISP edge (rtr01-style), not just blanket FRR_TRANSIT_IN

**Rule.** After introducing a new ISP edge device that peers iBGP with remote endpoints via its own VTI tunnels, audit the core firewall's BGP tie-break for any prefix reachable by BOTH edges. If both paths end up at the same LP, the ASA picks by router-ID and the reply comes back on the other edge → asymmetric → stateful drop.

**Why.**
- 2026-04-22: After yesterday's xs4all→budget migration moved 3 VTIs from nl-fw01 to nlrtr01, VPS loopbacks (10.255.X.X/24, 10.255.X.X/24) became unreachable from NL because:
  - nl-fw01 learned the VPS loopback via 3 BGP paths (FRR01 reflecting with Freedom NH, FRR02 reflecting with Budget NH, rtr01 reflecting with Budget NH)
  - All 3 were LP 100 (blanket `FRR_TRANSIT_IN` route-map on all three peers)
  - Tie-break picked rtr01 → Budget path out
  - NO VPS replied via its default Freedom FRR peering → reply came in on nl-fw01's vti-no-f (Freedom) → asymmetric → rpf-violated + nat-rpf-failed drops → Prometheus scrapes timed out → `TargetDown` fired
- Without this fix, any K8s-originated traffic (Prometheus, service scrapes, pod-to-VPS) is silently broken even though the BGP session is Established.

**Fix pattern (ASA 9.16):**

```cisco
! 1) Define what the "asymmetric-risk" prefixes are
prefix-list VPS_LOOPBACKS seq 10 permit 10.255.X.X/24
prefix-list VPS_LOOPBACKS seq 20 permit 10.255.X.X/24

! 2) New dedicated inbound route-map for the FRR that reflects the Freedom-NH variant
route-map FREEDOM_FRR_IN permit 5
 match ip address prefix-list VPS_LOOPBACKS
 set local-preference 200
!
route-map FREEDOM_FRR_IN permit 10
 set local-preference 100

! 3) Apply the new route-map ONLY to the Freedom-reflecting FRR peer (e.g. FRR01)
router bgp 65000
 address-family ipv4 unicast
  neighbor 10.0.X.X route-map FREEDOM_FRR_IN in
! Leave FRR02 and rtr01 on the baseline FRR_TRANSIT_IN (LP 100)

! 4) Soft-refresh and clear stale conns
clear bgp 10.0.X.X soft in
clear conn address 10.255.X.X
clear conn address 10.255.X.X
write memory
```

**Why not `match ip next-hop`.** ASA 9.16 logs `WARNING: used as BGP inbound route-map, nexthop match not supported`. The clause silently ignores the next-hop match and ends up setting LP on ALL matching prefixes regardless of NH — same tie, no fix. Use per-peer route-map scoping instead.

**Identity NAT prerequisite.** The ASA `after-auto source dynamic any interface` PAT on the new edge interface (`outside_budget` in this case) will also PAT transit traffic to the new-edge IP (10.0.X.X) — see `feedback_after_auto_nat_rpf_check.md`. BEFORE the BGP fix, also stage Section-1 identity NAT for the transit-prefix pairs:

```cisco
object network NET_vps_ch
 subnet 10.255.X.X 255.255.255.0
object network NET_vps_no
 subnet 10.255.X.X 255.255.255.0

nat (inside_k8s,outside_budget) 1 source static any any destination static NET_vps_ch NET_vps_ch no-proxy-arp route-lookup
nat (inside_k8s,outside_budget) 2 source static any any destination static NET_vps_no NET_vps_no no-proxy-arp route-lookup
nat (inside_mgmt,outside_budget) 1 source static any any destination static NET_vps_ch NET_vps_ch no-proxy-arp route-lookup
nat (inside_mgmt,outside_budget) 2 source static any any destination static NET_vps_no NET_vps_no no-proxy-arp route-lookup
```

**How to apply going forward.**
- When rolling a new edge router with direct iBGP to remotes, for every destination prefix reachable via both the new edge AND the existing path: check `show bgp ipv4 unicast <prefix>` on the core ASA — if all paths show the same LP, add a per-peer LP-override.
- Keep the prefix-list scope narrow (specific subnets, not whole /16s) so failover still works when the Freedom path drops.
- Audit via `scripts/check-asa-binding-drift.py` — consider adding an `EXPECTED_ROUTEMAP_APPLIED` assertion for `FREEDOM_FRR_IN` on 10.0.X.X.
- Symptom to watch for: `TargetDown` (Prometheus) or service-health flaps immediately after a migration where tunnels appear UP and BGP appears Established but payloads don't flow. Check `show asp drop | include rpf|nat-rpf-failed` on the ASA and `show conn address <dst>` to confirm asymmetric.

*Source: `memory/feedback_bgp_asymmetric_lp_after_new_edge.md`*

### Adding IPsec peer to a Cisco edge — also add to inbound ACL on the WAN interface

When adding a new IPsec peer to a Cisco edge router (or ASA) that has an inbound ACL on its WAN interface, you MUST add the new peer's source IP to the ACL — otherwise IKE_SA_INIT packets are dropped silently and strongSwan just retries forever with no useful error.

**Why:** `nlrtr01` has `ip access-group OUTSIDE_BUDGET_IN in` on `Dialer1` (the xs4all PPPoE WAN). The ACL has explicit allow lines for each known peer (`203.0.113.X`, `198.51.100.X`, `198.51.100.X`) covering: ESP (proto 50), `udp eq isakmp` (500), `udp eq non500-isakmp` (4500). Final line is `deny ip any any log` so anything else is dropped.

When I added VTI Tunnel4/5 on rtr01 for `notrf01dmz01` (193.200.238.138) and `notrf01dmz02` (193.200.238.139) without touching the ACL, the dmz hosts' nl-xs4all tunnel showed CONNECTING with retransmits in their charon log; rtr01 showed no IKEv2 SA attempt and Tunnel4/Tunnel5 with `line protocol is down`. The clue was the ACL hit counter on existing entries staying static while the dmz hosts retried — meaning packets weren't reaching IKE.

**How to apply:**
- Whenever you add a new IPsec peer to an ASA / IOS-XE router with an inbound ACL on the WAN, add SIX ACL entries before re-attempting:
  ```
  ip access-list extended <ACL_NAME>
   N0 permit esp host <new-peer-ip> any
   N1 permit udp host <new-peer-ip> eq isakmp any
   N2 permit udp host <new-peer-ip> eq non500-isakmp any
  ```
  (and the symmetric inverses if the device originates connections too)
- Use sequence numbers strategically — insert before the trailing `deny ip any any` to avoid editing-order drift.
- Verify via `show access-list <NAME> | i <new-peer-ip>` — entries should be there with hit counters that grow once IKE retries.
- Symptoms when missing: dmz-side IKE retransmits without peer response, rtr01-side `show crypto ikev2 sa` shows no entry for the new tunnel, `show interface TunnelN` reports `line protocol is down` even though the underlying tunnel config looks correct.
- Generalises to: any Cisco edge with an explicit-allowlist inbound ACL. Always re-read the ACL after adding crypto config; the two layers are decoupled.

*Source: `memory/feedback_cisco_acl_silent_block_for_new_peers.md`*

### After restoring a backend, probe every static-site consumer for staleness

When restoring a backend service that feeds a static-site generator (Hugo, Jekyll, Astro, Eleventy, Next static export, etc.) at build time, **HTTP 200 on the backend is not "the page is fixed."** The user-visible page is the static HTML, which was baked during the outage with whatever fallback the build pipeline chose. It will keep serving the fallback until the next rebuild.

**Why:** 2026-05-11 — n8n OOM-killed for 4h. I restarted n8n, confirmed all 3 portfolio webhooks returned 200, declared the incident resolved. Operator pushed back: "both pages live stats widgets are offline." They were right. Three kyriakos CI pipelines during the outage (29159/29200/29219) had fetched failed → baked `<span>Mesh health data unavailable</span>` + `<span>Usage stats unavailable</span>` directly into the static HTML. The next scheduled rebuild would be 1h away; manual trigger (pipeline 29252) was needed.

**How to apply** — when a backend outage involves a consumer that's a static-site generator:

1. **Probe the static HTML, not just the backend.** `curl -sk https://<site>/<path> | grep -iE 'fallback|unavailable|loading\.\.\.'` — if you see these tokens *in the source HTML* (not just in JS string literals), the page was rebuilt during the outage with bad data.
2. **Find the build pipeline.** Look for `.gitlab-ci.yml` / `.github/workflows/*.yml` / Cloudflare Pages / Vercel / Netlify config. Search for `curl|fetch|wget|getJSON` against the backend's URL.
3. **Inspect the failure semantics.** Most pipelines write empty/error JSON on fetch failure and continue the build. That's the trap.
4. **Trigger a fresh build after the backend recovers.** GitLab: `POST /projects/<id>/pipeline?ref=main`. GitHub: `workflow_dispatch`. Vercel/Netlify/CF Pages: manual deploy from dashboard or `gh-pages` push.
5. **Verify with Playwright (or curl + grep) against the live URL.** DOM locators for the fallback class should resolve to 0 elements. Specific data should appear.
6. **Save BEFORE + AFTER screenshots** — Playwright `await page.screenshot({path: 'reports/...png'})` makes the visual proof reproducible.

**Spec to ship in your verification toolkit** — example at `visual-audit/tests/live-widgets-verify.spec.js`. Pattern:
```js
const fallback = page.locator('.fallback-class');
await expect(fallback, 'fallback should NOT be rendered').toHaveCount(0);
const widget = page.locator('#real-widget');
await expect(widget).toBeVisible();
const num = await page.locator('.stat-num').first().textContent();
expect(num).toMatch(/[1-9]/); // not empty, not zero-only
```

**Anti-pattern: grepping the raw HTML for fallback strings.** Shortcodes often have the fallback HTML as a *string literal inside the JS source* that ships with every render — false positive. Use DOM-aware assertions (Playwright locators) instead.

**Anti-pattern: declaring "resolved" the moment the backend service is `active`.** Look downstream first.

*Source: `memory/feedback_static_site_consumer_staleness.md`*

### Allowlist lookup miss must hard-error, never silently empty-pass

When a backend builds a kill/target list by iterating user input through an allowlist dict, **lookup misses must hard-error** — never silently skip:

```python
# BUG: silent miss -> empty tunnel_infos -> "active" response with tunnels_killed=[].
tunnel_infos = []
for tk in tunnel_keys:
    info = CHAOS_TUNNELS.get(tk)
    if info:
        tunnel_infos.append({...})
# ... 50 lines later, history saved with tunnels=[], subprocess fired, sys.exit(1) in background ...

# FIX: defensive check immediately after the loop.
if chaos_type in ("tunnel", "combined") and tunnel_keys and not tunnel_infos:
    print(json.dumps({
        "error": "None of the requested tunnels are in CHAOS_TUNNELS. ...",
        "submitted": [list(t) for t in tunnel_keys],
        "available": [list(k) for k in CHAOS_TUNNELS.keys()],
    }))
    sys.exit(1)
```

**Why:** `_cmd_start_locked` in `scripts/chaos-test.py` accepted `tunnel_keys = [("NO-DMZ01 ↔ NL", "freedom"), ("NO-DMZ02 ↔ CH", "vps")]` from the operator's 2026-05-06 19:13 click, looped through `CHAOS_TUNNELS.get()`, both missed, `tunnel_infos = []`, then code happily proceeded to:
- write state with `tunnels_killed=[]`
- save history with `tunnels=[]`
- print `{status: "active", tunnels_killed: []}` to the frontend
- fork subprocess to execute kills, where `_execute_tunnel_chaos` finally exited 1 in the background

The frontend received `status=active` with `tunnels_killed=[]`, took the `if (res.tunnels_killed.length)` branch as falsy, and never overwrote its pre-call optimistic state. Net effect was a 600s "active" run with no real kills. The only signal of failure was a single `Tunnel kill FAILED (SystemExit): 1` line buried in `~/chaos-state/execute-kills.log`.

**How to apply:**

- Right after any allowlist-iteration that builds a target list, add an explicit `if not target_list: error_out()` check. Two adjacent lines, not a layered guard 50 lines downstream.
- The error JSON should include both what was *submitted* and what's *available* — diagnostics for the next operator (or future-you) reading the response.
- Reading sys.exit(1) in a background subprocess log is not a substitute. The synchronous-response path must surface the failure.
- Frontend mirror: when consuming an allowlisted resource, pair `if (res.list && res.list.length)` with `else { showError(...); }` — never let an empty list silently coexist with a `status=active` from the same response.

Born from chaos-test.py 2026-05-06 (memory `status_page_chaos_red_link_fix_20260506.md`). Adjacent precedent: same shape as `feedback_classify_pipeline_failures_by_step.md` — silent partial success on multi-item operations is the most expensive class of bug because nothing in monitoring catches it.

*Source: `memory/feedback_no_silent_pass_when_allowlist_lookup_misses.md`*

### Always monitor pipelines after a push

After every `git push`, check the resulting CI/CD pipeline and stay on it
until it finishes — success or failure. A green push is not a green build.

**Why:** The operator asked for this on 2026-04-20 immediately after a
2-repo push (gateway + portfolio). Unmonitored pipelines mean regressions
ship silently — especially for cross-cutting commits like the 3-tier CLI
capture (13 files, new scripts, new QA suite). If CI fails after the
operator has moved on, the gap between failure and discovery is hours.

**How to apply:**

- After each `git push`, immediately query the pipeline for the just-pushed
  commit SHA. Don't assume it'll pass because local tests / QA passed.
- Use the GitLab API via `GITLAB_TOKEN` in `.env` (or `GITLAB_TOKEN` /
  `GL_TOKEN` in the environment). `gh` works for github mirror only —
  GitLab is the primary.
- Preferred endpoints:
  - `GET /api/v4/projects/<id>/pipelines?ref=<branch>&sha=<sha>` — find the pipeline for a specific push
  - `GET /api/v4/projects/<id>/pipelines/<pid>` — current status
  - `GET /api/v4/projects/<id>/pipelines/<pid>/jobs` — per-job state; drill into failures via `/jobs/<jid>/trace`
- Project IDs live in `CLAUDE.md`: claude-gateway=30, portfolio=websites/papadopoulos.tech/kyriakos.
- **One-shot status checks, not blocking until-loops.** The operator has
  interrupted long monitor loops repeatedly (2026-04-20 session: 3×).
  Pattern: check once at push+~30s, report the current state, and let the
  operator decide if they want more polling. Use `run_in_background` or
  an explicit one-shot `curl`. Do NOT run `until status in {success,
  failed, canceled, skipped}; do sleep; done` — the operator finds the
  cadence obstructive and will interrupt.
- On failure: pull the failing job's trace, summarize the failure, and
  offer the fix. Don't just announce the failure — resolve it.
- Parallel multi-repo pushes (like the one that triggered this memory)
  need multi-pipeline tracking — both pipelines, both repos, both reported.
- If no CI is wired for a repo/branch (some content-only pushes trigger
  nothing), say so explicitly instead of going silent.
- Retries and manual-gate jobs: note them, don't block on them unless
  they're a required step.

**Signal of the rule working:** every push ends with a one-line status
like "gateway !1234 ✓ (5 jobs, 2m18s) / portfolio !567 ✓ (3 jobs, 47s)"
or the operator sees the failure within minutes instead of hours.

Memory created 2026-04-20 in response to the feedback after pushing
7cda6d1 (gateway) + efdf162 (portfolio).

*Source: `memory/feedback_monitor_pipelines_on_push.md`*

### Always set per-request num_ctx when using Ollama on nl-gpu01

`nl-gpu01` has global `OLLAMA_CONTEXT_LENGTH=65536` configured in `/srv/ollama/docker-compose.yml`. Ollama allocates a KV cache for the FULL 64k context on every model load, regardless of actual prompt size.

**Symptom:** A 1B-parameter model (llama3.2:1b) takes 23 GB memory with 22% CPU / 78% GPU split and runs at 10-25 tokens/sec instead of 200+ tok/s. A 7B model (qwen2.5:7b) can spill similarly.

**Why:** KV cache size scales with context length × model hidden dim. At 64k context with q8_0 quantization, even a tiny model's KV cache exceeds reasonable sizes. Ollama splits across CPU+GPU when VRAM is insufficient.

**How to apply:** In every `/api/generate` or `/api/embed` call, set `options.num_ctx` to the smallest value that covers your prompt + num_predict:

```json
{
  "model": "llama3.2:1b",
  "prompt": "...",
  "options": {"num_predict": 180, "num_ctx": 1024}
}
```

Rule of thumb:
- Short classification (yes/no): num_ctx=2048
- Rewriting / summarization: num_ctx=2048-4096
- Long-doc map-reduce chunks: num_ctx=4096-8192
- Only use the default (64k) for genuinely long-context tasks

Confirmed improvement 2026-04-17: RAG pipeline end-to-end p50 4.80s → 1.43s (−70%) after adding per-request num_ctx in `kb-semantic-search.py` rewrite + rerank paths.

Verify with `docker exec ollama ollama ps` — the `PROCESSOR` column should read `100% GPU`, not `X% CPU/Y% GPU`.

*Source: `memory/feedback_ollama_num_ctx_vram.md`*

### Anchor literal markers in LLM output to start-of-line

When extracting a literal marker like `[POLL]`, `[AUTO-RESOLVE]`, `CONFIDENCE:`, `TRIAGE_JSON:` from free-form LLM output:

1. **Anchor the marker to start-of-line** (`^MARKER` with the `m` flag).
2. **Prefer the LAST match**, not the first — use `result.matchAll(re)` then take the tail.

**Why:** the same string also lives in the prompt that *taught* the model to emit it. When the model quotes the prompt instructions back at the operator (which it does whenever asked to explain its own behavior), the unanchored regex matches the quoted mid-sentence mention and rebuilds the wrong structure. This was the exact failure mode of `Prepare Result.parsePoll` in 2026-04-25 commit `9f680fc`: poll #0 (IFRNLLEI01PRD-734) and poll #15 (-723) rendered nonsense questions sourced from quoted text like *"...the gateway ONLY processes [POLL] blocks for interactive approval..."* — the prompt's own pollInstructions sentence.

**How to apply:**
- Any new parser of `[MARKER]`-style LLM signals: regex `/^\[MARKER\]\s*(.+?)\s*$/gm` + `[...result.matchAll(re)].pop()`.
- Add a regression test that includes the marker quoted inside surrounding prose, not just the clean happy-path example.
- Same rule covers `CONFIDENCE:`, `[AUTO-RESOLVE]`, `TRIAGE_JSON:`, `REVIEW_JSON:`, `PROMPT_TRIAL_INSTRUCTIONS:` and any other parsed-by-gateway literal — audit each parser when refactoring.

*Source: `memory/feedback_anchor_llm_output_markers.md`*

### Atlantis apply command format and architecture

Atlantis apply command must include the project flag: `atlantis apply -p k8s`

**Why:** Both NL and GR IaC repos have a single project named `k8s`. Without `-p k8s`, Atlantis ignores the apply comment.

**How to apply:** When posting apply comments to GitLab MRs for IaC repos, always use `atlantis apply -p k8s`. Same for plan: `atlantis plan -p k8s`.

NL and GR have **separate GitLab instances and separate Atlantis servers**. They can run plans and applies concurrently — there is no shared state or lock between sites.

*Source: `memory/feedback_atlantis_apply.md`*

### Atlantis — do NOT spam plan/apply commands

Post `atlantis plan` or `atlantis apply` ONCE on a GitLab MR and WAIT for the response. Do NOT:
- Poll in a loop checking for results
- Re-trigger the same command if it hasn't responded yet
- Post `atlantis unlock` + `atlantis plan` + `atlantis apply` in rapid succession

**Why:** Atlantis processes one command at a time per workspace. Re-triggering creates lock conflicts ("workspace currently locked by apply"), duplicate plan runs, and floods the MR with redundant comments. kube-prometheus-stack plans take 1-3 minutes for the Helm diff.

**How to apply:** Post the command once, then tell the user to check the MR when it's done. If the user asks to check, do ONE API call to read the latest note — don't loop.

*Source: `memory/feedback_atlantis_no_spam.md`*

### Canary cron during dispatch-chain cutover, retire once real traffic confirms steady state

# Canary cron pattern — cutover-only, then retire

When you rewire an alert/dispatch path — e.g. moving the "Post Triage Instruction" SSH command from a Matrix-mention dispatch to a direct shell wrapper — a canary cron that fires synthetic input and asserts the expected output lifts your migration confidence. The receiver-canary lifted cc-cc-migration confidence 0.78 → 0.93 on 2026-04-29. **But it is a cutover instrument, not a permanent monitor.**

**Why retire after cutover:** real alert volume on this system is roughly hourly. A broken dispatch chain manifests as the next real alert failing to land — same minutes-to-hours signal the canary provides, but without producing synthetic artifacts. Keeping the canary running indefinitely turns the verifier into the noise it was meant to detect: 50 `CanaryAlert_*` YT issues piled up in 25h on 2026-04-30 before being ripped out.

**How to apply (during cutover):**

1. Pick the simplest input shape that exercises the full chain end-to-end (e.g. a Prometheus `firing` payload, not a synthetic SQL row insert).
2. The canary script must do BOTH halves: fire the input, then assert the expected output landed within a deadline. One-sided canaries that just fire are useless.
3. Emit Prometheus textfile metrics (`*_last_run_status`, `*_last_run_timestamp_seconds`) so two alerts can be derived: a **Failing alert** (output didn't land) and a **Stale alert** (the cron itself stopped — without this, the failing alert can never fire because the metric never updates).
4. Add a counterpart **wiring health check** to `holistic-agentic-health.sh` that verifies the structural prerequisite (e.g. `grep -q "run-triage\.sh" workflows/*receiver*.json`). The canary tests behavior; the health check tests structure. **The wiring health check stays — it has no per-run side-effect; the canary goes.**

**How to apply (retirement gate):**

- After ≥24h of continuous real alert traffic post-cutover, retire the canary: disable cron, delete script, drop the two Prometheus alerts, bulk-close any synthetic artifacts. Keep the wiring health check.
- If the design forces synthetic artifacts (YT issues, tickets, pages) in production queues, build the cleanup path into the canary itself from day 1 — auto-resolve after PASS, suppress at receiver via a `_canary: true` label, or route to a dedicated queue. Never rely on "operator filters by name" — see [feedback_canary_must_clean_its_own_artifacts.md](feedback_canary_must_clean_its_own_artifacts.md).

History: `scripts/receiver-canary.sh` + `agentic-health.yml:ReceiverCanaryFailing,ReceiverCanaryStale` were retired 2026-04-30 (cc-cc cutover proven steady; real alert volume exercises the chain). `holistic-agentic-health.sh §38 cc-cc-receiver-wiring` retained as the durable structural check.

*Source: `memory/feedback_canary_for_dispatch_chain_changes.md`*

### Canary verification mechanisms must clean their own artifacts

When designing a canary / synthetic-traffic monitor that verifies a production dispatch chain end-to-end, the verification side-effects must auto-clean. Three viable shapes — pick one at design time:

1. Auto-resolve: after the canary asserts the artifact exists (PASS), it closes/resolves the artifact in the same run.
2. Suppress at receiver: the dispatcher recognises a `_canary: true` label and emits a metric instead of creating the artifact (loses "full chain" verification).
3. Separate queue: synthetic traffic routed to a dedicated project/queue, never mixed with real traffic.

**Never rely on "operator filters them out by name."** That works for a week and then becomes the noise it was meant to detect.

**Why:** 2026-04-30, operator hit `scripts/receiver-canary.sh` cron `*/30 * * * *` (installed alongside cc-cc migration 2026-04-29 commit 484f5da). 50 `CanaryAlert_*` YT issues piled up in the IFRNLLEI01PRD project in 25 hours, none auto-resolved. The script's own header documented the design as "synthetic issues are tagged with prefix 'CanaryAlert_' so the operator can filter them out of YT searches; they auto-stay-open with no triage activity." That assumption broke at production volume — operator opened the project board and said "wtf are all these canaryalert."

**How to apply:**
- Reviewing or building a canary cron / synthetic-input → expected-output verifier? Check the artifact lifecycle BEFORE shipping. If artifacts persist, demand a cleanup path.
- Pair this with `feedback_canary_for_dispatch_chain_changes.md` (which says "install a canary after every dispatch-chain rewire") — that rule still stands, this rule adds: design the cleanup at the same time.
- Default to Option 1 (auto-resolve after PASS) — preserves the strongest verification (real artifact gets created and immediately closed) without leaving residue.

*Source: `memory/feedback_canary_must_clean_its_own_artifacts.md`*

### Canonical-label helpers must use site-priority fallback, not blind reverse

When a function normalizes a bidirectional pair label by looking it up in a static map, the fallback for a miss must be a *deterministic priority ordering*, not a blind reverse.

```js
// BUG: works only when the legacy table has both directions listed.
function tunnelLabel(src, tgt) {
  var fwd = src + ' ↔ ' + tgt;
  if (TUNNEL_WAN[fwd]) return fwd;
  return tgt + ' ↔ ' + src;   // ← guaranteed REVERSAL when neither direction is in the table
}

// FIX: explicit priority list mirrors the *backend's* canonical key order.
var SITE_ORDER = ['NL','GR','NO','CH','TX','NO-DMZ01','NO-DMZ02'];
function tunnelLabel(src, tgt) {
  var fwd = src + ' ↔ ' + tgt;  if (TUNNEL_WAN[fwd]) return fwd;
  var rev = tgt + ' ↔ ' + src;  if (TUNNEL_WAN[rev]) return rev;
  var sIdx = SITE_ORDER.indexOf(src); if (sIdx<0) sIdx = 999;
  var tIdx = SITE_ORDER.indexOf(tgt); if (tIdx<0) tIdx = 999;
  return sIdx <= tIdx ? fwd : rev;
}
```

**Why:** The original code's "if not in table, return reverse" logic was a clever shortcut that works ONLY because the legacy 4-site `TUNNEL_WAN` listed both directions explicitly. The instant TX (2026-05-06) and NO-DMZ01/02 (2026-05-05) joined the mesh, no entries were added to `TUNNEL_WAN`, and the function silently returned `"NO-DMZ01 ↔ NL"` instead of `"NL ↔ NO-DMZ01"`. The backend's `CHAOS_TUNNELS` dict (keyed on canonical NL-first) silently missed the lookup, the chaos run produced no kills, the dashboard never went red. **Cost: a 600s "active" run with zero observable effect. No error surfaced.**

**How to apply:**

- For any "canonical label" helper that normalizes bidirectional pairs (`A ↔ B`), pair the lookup-table fast path with an explicit priority array fallback.
- Mirror the priority order from the *authoritative* dataset (the backend's dict keys, the IaC's site list, etc.) — not whichever order felt natural while writing the JS.
- Default missing entities to a high priority index (`999`) so unknown→known produces a deterministic order that surfaces the unknown end first or last consistently.
- Tests: include cases where neither direction is in the lookup table. Adding an entity to the table should never change the function's output for legacy pairs.

Born from `chaos.js:tunnelLabel()` 2026-05-06 (memory `status_page_chaos_red_link_fix_20260506.md`). Adjacent precedent: any time `vpn-mesh-stats.py` adds a new tunnel label to `mesh-stats`, audit any frontend helper that consumes it for the same shape of bug.

*Source: `memory/feedback_canonical_label_helpers_need_site_priority_fallback.md`*

### Capture state on exception raise, not in the except handler

**Rule:** if you raise an exception from inside a `with lock_ctx:` block and the `except` block needs to describe the protected state, capture that state *at raise time* and attach it to the exception. Do not re-read the file / DB / resource from the `except` block.

**Why:** Python's `with` statement guarantees `__exit__` runs **before** the `except` clause that catches the raise. For `marker_lock()` or any `flock()` / `threading.Lock` / connection-checkout context, that means the lock is already **released** by the time the caller's except is executing. Another writer can modify (or clear) the protected state in that microsecond window. Your except will then read inconsistent / cleared state and report confusing defaults.

**How to apply:** the `try` / `except` / `raise` pattern is already correct — just move the state capture into the exception constructor.

```python
# WRONG — races with other writers releasing the lock after raise
class CollisionError(RuntimeError): pass

def write_marker(...):
    with marker_lock():
        if not allowed():
            raise CollisionError("marker owned by another drill")
        ...

try:
    write_marker(...)
except CollisionError:
    existing = load_state()   # ← racy: lock is released, other writer may have cleared
    print(f"marker owned by {existing.get('scenario', 'unknown')}")

# RIGHT — capture at raise time, while we still hold the lock
class CollisionError(RuntimeError):
    def __init__(self, msg, existing=None):
        super().__init__(msg)
        self.existing = existing or {}

def write_marker(...):
    with marker_lock():
        existing = load_state()   # safe: we hold the lock
        if not allowed(existing):
            raise CollisionError("marker owned by another drill", existing=existing)
        ...

try:
    write_marker(...)
except CollisionError as e:
    print(f"marker owned by {e.existing.get('scenario', 'unknown')}")   # never races
```

**Real-incident evidence:** observed live 2026-04-24 20:05:02 + 20:15:23 UTC in `#infra-nl-prod` — two identical ABORT posts all showing `scenario=unknown, experiment_id=n/a, expires=unknown`, because the except block was calling `load_state()` from outside the `with marker_lock():` scope. Fixed in `scripts/lib/chaos_marker.py` + `scripts/chaos-test.py` via commit `f4f2cd4`.

**Unit-test pattern that would have caught it:** don't just assert "the exception carries attrs". Also assert race-safety: delete the protected file AFTER the raise but BEFORE reading the attribute. If your tests only run the happy-path re-read, production will find the race for you.

**Affects:** any `with chaos_marker.marker_lock():` site; any `with DB_CONN.cursor()` where the cursor releases the row lock on commit/rollback; any `with threading.Lock():` where the except handler accesses state the lock was protecting.

*Source: `memory/feedback_capture_state_on_exception_raise.md`*

### Chatwoot FORCE_SSL=true breaks internal HTTP — set X-Forwarded-Proto: https

**Rule:** When making internal HTTP calls to a Chatwoot rails service that has `FORCE_SSL=true` set, ALWAYS send the `X-Forwarded-Proto: https` header. Without it, every request gets 301'd to HTTPS and the n8n HTTP node throws `SSL routines:tls_get_more_records:packet length too long` (because port 3000 isn't speaking TLS).

**Why:**
- `FORCE_SSL=true` in Chatwoot's compose env (the default for production) sets Rails `config.force_ssl = true`, which redirects all plain HTTP requests to HTTPS at the application layer.
- This is correct for traffic that comes through HAProxy (which terminates TLS externally), because HAProxy passes the original protocol via headers.
- But internal docker-network traffic (n8n container → chatwoot-rails:3000) is plain HTTP and has no SSL termination layer in front of it — Rails 301s it, the HTTP client follows the redirect, and SSL handshake fails on port 3000.
- The standard Rails-behind-a-proxy fix: send `X-Forwarded-Proto: https` so Rails treats the request as already-SSL-terminated upstream and does NOT 301.

**How to apply:**
- All n8n HTTP nodes pointing to `http://agriops-chatwoot-rails:3000/...` (or any internal Chatwoot endpoint) MUST include the header `X-Forwarded-Proto: https`.
- In n8n workflow JSON (httpRequest node):
  ```json
  "headerParameters": {
    "parameters": [
      { "name": "Content-Type", "value": "application/json" },
      { "name": "X-Forwarded-Proto", "value": "https" }
    ]
  }
  ```
- When patching multiple HTTP nodes via API, filter by **credential id** (e.g. Chatwoot httpHeaderAuth credential id), NOT by URL substring — many nodes use `={{ $json.chatwootUrl }}` expression URLs that don't contain the literal hostname.
- Diagnostic: on a failure, `wget -O - --timeout=5 -S http://agriops-chatwoot-rails:3000/<path>` from inside the n8n container shows `HTTP/1.1 301 Moved Permanently → Location: https://...`. Adding `--header="X-Forwarded-Proto: https"` makes it return `HTTP/1.1 200 OK`.

**Memory ties:**
- Project: `agentic-agriops-project.md` — Lane 2 e2e wiring section
- Related: `feedback_chatwoot_sidekiq_separate_network.md` (companion fix for the same wiring path)

*Source: `memory/feedback_chatwoot_force_ssl_xforwarded_proto.md`*

### Chatwoot sidekiq is on a separate docker network from rails — webhooks need explicit network attach

**Rule:** Whenever you wire a Chatwoot instance to send outbound webhooks to a sibling service on a different docker network, attach the `agriops-chatwoot-sidekiq` (or equivalent sidekiq container) to that network — NOT just `agriops-chatwoot-rails`.

**Why:**
- Chatwoot's `WebhookJob` (the ActiveJob that POSTs payloads) runs in the sidekiq worker container, not rails.
- Default Chatwoot compose ships sidekiq on `chatwoot-internal` network ONLY (so it can talk to postgres + redis), and rails on BOTH `chatwoot-internal` AND the public/api network.
- We hit this on agri 2026-04-27: every outbound webhook to `http://agriops-n8n:5678/webhook/chatwoot-conversation-created` failed in sidekiq with "Timed out connecting to server" — bare wget from sidekiq returned "bad address agriops-n8n:5678" while the same wget from rails returned `{"status":"ok"}` immediately.
- The error is misleading because Chatwoot's WebhookJob wrapper formats it as `Invalid webhook URL <url> : Timed out connecting to server`, which sounds like a URL validation failure, not a network-routing failure.

**How to apply:**
- For any `*` Chatwoot deploy that sends webhooks to non-database sibling services:
  ```yaml
  sidekiq:
    networks:
      - agentic-agriops          # NEW — needed for outbound webhooks
      - agriops-chatwoot-internal # existing — postgres + redis
  ```
- Live attach without restart: `docker network connect agentic-agriops agriops-chatwoot-sidekiq` (cgroup updated in place; existing connections preserved).
- Verify with: `docker exec agriops-chatwoot-sidekiq wget -qO- --timeout=5 http://<target-service>:<port>/<healthz>`. Should return 200 immediately.
- Diagnostic ladder when webhooks fail:
  1. Check `docker logs agriops-chatwoot-sidekiq --since 5m | grep -E 'WebhookJob|Invalid webhook URL'` for the sidekiq log line.
  2. Compare which networks each container is on: `docker inspect <container> --format '{{range $net,$cfg := .NetworkSettings.Networks}}{{$net}} {{end}}'`.
  3. Test reachability from sidekiq specifically (NOT from rails — they're on different networks).

**Memory ties:**
- Project: `agentic-agriops-project.md` — Lane 2 e2e wiring section
- Related: `feedback_chatwoot_force_ssl_xforwarded_proto.md` (companion fix for the same wiring path)

*Source: `memory/feedback_chatwoot_sidekiq_separate_network.md`*

### Check upstream capabilities before designing a shim

Before designing a translation shim, proxy, or adapter for a third-party service, **search the upstream's source + CHANGELOG.md for native support of the target capability.** A custom shim is high effort, ongoing maintenance burden, and usually unnecessary.

**Why:** During the 2026-04-28 OpenClaw GPT-5.1 → Sonnet migration, the initial design was an OpenAI-compatible HTTP shim on `nl-claude01:11437` translating chat-completions requests into `claude -p` subprocesses (~150 LOC FastAPI + systemd unit). The Plan agent validated this design end-to-end. The operator pushed back: "openclaw latest versions support anthropic oauth, hence why using claude -p together with openclaw? openclaw changes are minimal imho." Investigation of `/srv/openclaw/extensions/anthropic/cli-*.ts` + `CHANGELOG.md` found OpenClaw 2026.4.11 already had:

- `extensions/anthropic/cli-auth-seam.ts`, `cli-backend.ts`, `cli-shared.ts`, `cli-migration.ts` — Claude-CLI reuse path.
- `openclaw onboard --auth-choice claude-cli` documented flag (`docs/start/wizard.md:75` calls Claude CLI the **preferred local Anthropic path**).
- CHANGELOG entries 117/137/282/665/941: OAuth wired through `service_tier` / `/fast`, stream wrappers handle 401s, env-vars sanitized so spawned `claude` runs inherit the Max subscription.

Result: 0 new code, 1 config edit (`openclaw configure --section model`), 1 container restart. Migration done in an hour vs. ~1 day for the shim path.

**How to apply:** When the recommended-design draft proposes building an adapter/shim/proxy that translates protocol A to protocol B for a third-party service, before committing to the design:

1. Clone or SSH-read the third-party source.
2. `grep -rni 'oauth|auth-choice|target_protocol_keyword' CHANGELOG.md docs/`.
3. Check `--help` of relevant CLI subcommands for hidden auth/transport options.
4. If native support exists, use it — even if the public docs are sparse. The CHANGELOG is the source of truth for "what the latest version actually does."

The cost of this check is ~10 minutes. The cost of NOT checking is sometimes a week of redundant work.

*Source: `memory/feedback_check_upstream_capabilities_first.md`*

### Cisco IaC — device is the source of truth, don't file-edit ahead

**One-line summary:** ASA `show run` suppresses default values — when comparing running config to git IaC, a MISSING line in git means the ASA default is in effect; do NOT add explicit lines for default-valued settings. The GitLab CI `auto_detect_and_sync_drift` job runs every 30 min and normalizes `show run` into git, so apply device changes FIRST and let the job push them. Don't open a human MR ahead of the device change.

Cisco configs in `infrastructure/nl/production/network/configs/`
(NL) and `infrastructure/gr/production/network/oxidized/` (GR) are
**device-following**, not device-driving:

- `auto_detect_and_sync_drift` job runs on schedule id=1 (`*/30 * * * *`)
  on main branch (both NL + GR, as of IFRNLLEI01PRD-700)
- Job invokes `network/scripts/detect_drift.py` → if drift, invokes
  `network/scripts/auto_sync_drift.py`. Both SSH directly to each device
  via netmiko. Oxidized still exists on nloxidized01 +
  groxidized02 but runs as a decoupled local-filesystem backup
  tier only (GitLab-push cron was commented out 2025-11-23). See
  `docs/runbooks/oxidized-role.md` for the layered-defence rationale.
- The script fetches `show running-config`, normalises, writes the
  file verbatim, and commits direct to main with message
  `Auto-sync device configurations to GitLab`
- Firewall configs pass through the layer-1 whitelist guardrail
  (IFRNLLEI01PRD-699) before commit — refuses to sync any RFC1918 NAT
  change that introduces a subnet not in `whitelist_shun_nlgr_all_subnets`
- Pre-deploy drift gate only blocks when device and main disagree on
  lines that the MR isn't capturing

**Preferred workflow (Cisco config change):**
1. Apply the config change to the **live device** first
   (`configure terminal ...`, `write memory`)
2. Wait up to 30 min for auto-sync to capture and commit it to main
3. Done — no human MR required

**If you insist on a human MR:**
- Pull the live `show running-config` at commit time and use it **verbatim**
  as the new file content. Don't hand-edit a single line and expect it to
  merge cleanly; the auto-sync will fight you.
- **ASA specifically suppresses default values in `show run` output.**
  Example: `maximum-paths ibgp 1` is the ASA default — setting it to 1 removes
  the explicit line from `show run`, so the correct IaC representation is
  "no line at all", not `maximum-paths ibgp 1`. Don't explicitly write default
  values.
- Never expect your file edit to stick through a race with auto-sync. Rebase
  immediately before merge, re-copy live dump on conflict, verify
  cryptochecksum matches.

**Cryptochecksum as ground truth:** The last config line is
`Cryptochecksum:<hash>`. The ASA computes this hash over its full running
config. If your git file and live device have the same cryptochecksum,
they are bit-for-bit identical. It is the authoritative match test.

**Why this matters (reference):** 2026-04-17 MR !249. I opened an MR to
codify `maximum-paths ibgp 4→1` as an explicit line. Auto-sync at 11:04 UTC
had already done the correct thing (removed the line entirely because the
new value equals ASA default). My MR created a merge conflict and had
the wrong IaC representation. Closed as redundant.

**Also applies to:** switches (nl-sw01), routers (nlrtr01,
nllte01), APs (nlap01-04). All managed by the same Netmiko /
NAPALM / hier_config / auto_sync_drift pipeline.

*Source: `memory/feedback_cisco_iac_device_is_truth.md`*

### Classify CI failure clusters by JOB, not by pipeline status

When investigating a cluster of "failed pipelines" in GitLab CI, ALWAYS filter by the failing JOB name (not pipeline status alone). A pipeline status of `failed` only tells you that *some* job in it failed — different jobs in different pipelines may have wholly unrelated root causes.

**Why:** On 2026-04-25, a 26-pipeline cluster on 2026-04-21 in `infrastructure/nl/production` was initially diagnosed as "18 K8s drift failures suggesting GitHub release-CDN outage" based on pipeline-status filtering. Pulling the actual job-level data revealed:
- `sync_pve_drift`: 26/26 failed (1h timeout deleting LXCs from inventory blink)
- `detect_pve_lxc_drift`: 26/26 failed (same timeout)
- `detect_pve_qemu_drift`: 24/26 failed
- `detect_k8s_drift`: only 4/26 failed (2 legit drift exit-2, 2 OpenBao auth)

The cluster was 96% PVE drift, not K8s drift. Building a hardening plan for "GitHub release-CDN reliability" would have addressed the wrong system.

**How to apply:** For any GitLab pipeline failure cluster investigation, run something like:
```bash
for PID in $FAILED_PIPELINE_IDS; do
  curl -sk -H "PRIVATE-TOKEN: $TOK" "$BASE/projects/$PROJ/pipelines/$PID/jobs?per_page=50" \
    | jq -r '.[] | select(.status=="failed") | .name'
done | sort | uniq -c | sort -rn
```
Then pull traces only for the dominant job(s). The pipeline-status view is a leaky abstraction over the per-job state — never assume cluster homogeneity from it.

Related: `parsepoll_fix_20260425.md` for similar "same-shape symptom, different root cause" patterns.

*Source: `memory/feedback_classify_ci_clusters_by_job.md`*

### Classify pipeline failures by step before assuming common cause

When N runs of the same CI job fail, do NOT assume they share a root cause. Pull the full trace for each, identify the failing step, and group by mode. Operator caught me three times in one day claiming "fix is one line" off the most-recent failure when the actual distribution was different.

**Why:** On 2026-05-01 the claude-gateway `sync_to_github` job failed 7 times since 2026-04-30. I anchored on the latest trace's `fatal: couldn't find remote ref refs/pipelines/<id>` and proposed `GIT_STRATEGY: none`. Real distribution was:
- 6/7 failed at step 4 (verification grep — gitignore-vs-cp-a interaction)
- 1/7 failed at get_sources (refs/pipelines transient)

Fixing only the 1-of-7 case would have left 6/7 still broken. The audit-by-step revealed the structural cause that was actually responsible for the reproducible failures.

**How to apply:** For each failed run, fetch `/api/v4/projects/X/jobs/<id>/trace` and grep the section_start/section_end markers + the last lines. Tabulate. If the modes differ, fix each independently — and don't promise "one line" until you know the distribution.

```bash
for jid in <list>; do
  trace=$(curl -sk -H "PRIVATE-TOKEN: $TOK" ".../jobs/$jid/trace" | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g')
  # extract last error + which section it landed in
  echo "$jid: $(echo "$trace" | grep -E 'fatal|ERROR|FAILED' | tail -2)"
done | sort -k2 | uniq -c -f1
```

Also caught related: "Pipeline went red in 1-of-N attempts" is NOT necessarily transient. It could be a deterministic failure that only manifests under specific conditions (e.g. single-job pipelines, specific commit content). Reproduce before declaring transience.

*Source: `memory/feedback_classify_pipeline_failures_by_step.md`*

### Create Matrix bot users via mas-cli inside the MAS container, NOT via Synapse admin endpoints

**Rule:** when a Matrix homeserver runs MAS (Matrix Authentication Service) in front of Synapse, do NOT try to create users via Synapse's old `/_synapse/admin/v1/register` HMAC-signed endpoint — it's correctly blocked at the reverse proxy because Synapse no longer owns auth. Instead, use **`mas-cli manage`** inside the MAS container.

**Why:** Synapse's `/_synapse/admin/*` admin namespace pre-dates MAS. With MAS, Synapse delegates ALL auth to MAS, including admin auth. Calling Synapse admin endpoints with a token (even the `MAS_SYNAPSE_ADMIN_TOKEN` that MAS uses for its own Synapse calls) returns 404 from outside the docker network — nginx is configured to only forward `/_matrix/*` paths, not `/_synapse/admin/*`. Even if you bypass nginx and hit Synapse directly, MAS may reject the request because the token isn't a MAS-issued user token.

**The right flow — three commands inside `agriops-matrix-mas` container:**

```bash
# 1. Register the user (--yes for non-interactive, --no-admin unless you want admin)
docker exec agriops-matrix-mas mas-cli -c /data/config.yaml manage register-user \
    --yes --no-admin \
    --password "<strong-random-pw>" \
    --display-name "Claude Agri Bot" \
    claude-agri

# 2. Issue a long-lived compatibility token for the user (suitable for n8n credentials)
docker exec agriops-matrix-mas mas-cli -c /data/config.yaml manage issue-compatibility-token \
    claude-agri AGRI_N8N_BOT
# Returns: mct_... access token + device_id you specified

# 3. (If you ever need to rotate password later)
docker exec agriops-matrix-mas mas-cli -c /data/config.yaml manage set-password \
    claude-agri "<new-pw>"
```

**The `-c /data/config.yaml` flag is mandatory.** Without it, mas-cli errors with `missing field 'matrix'` because it can't find the homeserver-name binding. The container's default ENTRYPOINT is `/usr/local/bin/mas-cli` and CMD is `["server", "--config", "/data/config.yaml"]` — the implicit config path applies only to `server` mode, not subcommands.

**The compatibility token (`mct_...`) is what you use as the bot's Bearer token everywhere:**
- n8n credential: `httpHeaderAuth` with `Authorization: Bearer mct_...`
- `claude -p` Matrix MCP servers
- `curl -H "Authorization: Bearer mct_..."` against `/_matrix/client/v3/*`

It does NOT expire and is NOT a refresh token. Treat it as a long-lived credential. If you generate via `--yes-i-want-to-grant-synapse-admin-privileges` it has admin power; without that flag it's a normal user token.

**Verification — `whoami`:**

```bash
curl -sS -H "Authorization: Bearer mct_..." \
    https://matrix.meshsat.org/_matrix/client/v3/account/whoami
```

Should return `{user_id, device_id, is_guest: false}`.

**Bot room-joining:** new bots have `joined_rooms: []`. Operator invites the bot via `/invite @bot:server` from their own Matrix client, then bot accepts via:

```bash
curl -X POST -H "Authorization: Bearer mct_..." \
    "https://matrix.meshsat.org/_matrix/client/v3/rooms/<urlencoded_room_id>/join" \
    -H "Content-Type: application/json" -d '{}'
```

**How to apply:**
- For any new agri bot account (Lane 2 support-triage bot, Lane 3 agronomy-advisor bot when those land), follow the same 3-command flow inside `agriops-matrix-mas`.
- For NL too (when/if NL adopts MAS — currently still legacy Synapse auth).
- Save the password to `agentic_agri_service_tokens.md` (operator-authorised storage policy) alongside the access token.

**When this rule kicks in:** any time the user-creation flow says "registration is closed" in the MAS web UI. Registration via the WEB UI is tied to MAS's user-facing flows; CLI bypasses those policy checks.

**Cross-references:**
- `agentic_agri_service_tokens.md` — `@claude-agri` creds saved 2026-04-27 (mct_mOcmBsU...)
- `agentic-agriops-project.md` — Day 6 Matrix unblock entry

*Source: `memory/feedback_mas_user_creation_via_cli.md`*

### Cron PATH excludes /usr/local/bin — always export PATH in cron scripts

Default cron `PATH=/usr/bin:/bin` excludes `/usr/local/bin`. Any third-party CLI tool installed there (Go binaries from go install, custom builds, npm-global wrappers, anything outside the package manager's standard paths) will fail under cron with bash exit 127 — `command not found`.

If the script redirects stderr to `/dev/null` or to a file with `2>&1` and uses `|| true`, the failure is COMPLETELY SILENT. The tool never runs. Output files are never written. Subsequent steps see missing-file errors with no obvious cause.

**Why:** Bit me 2026-05-04 on `/opt/scans/weekly-scan.sh`. Both daily security scanners had nuclei + testssl silently failing in cron for ~5 weeks (Mar 29 → May 4). Daily email reports said "Nuclei findings: 0" / "TLS issues: 0" reading as clean scans, but were actually "tool didn't run." 13 of 21 scanner tools live in /usr/local/bin (Go-installed: nuclei, naabu, ffuf, httpx, katana, dalfox, subfinder, dnsx; Perl/Python: testssl, nikto, wapiti, sslyze; etc.).

**How to apply:**

1. **Always `export PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin` near the top of any script that will run from cron** (or systemd timers without explicit `Environment=PATH=`).
2. **Never redirect tool stderr to `/dev/null`** — capture to a dated debug file so silent failures leave breadcrumbs. e.g. `tool ... 2>"$DEBUG_DIR/tool-stderr-${DATE}.log"`.
3. **Reproduce cron's exact env** when debugging:
   ```bash
   sudo env -i HOME=/root PATH=/usr/bin:/bin SHELL=/bin/sh \
     LOGNAME=root USER=root which <tool>
   ```
   If "No such file or directory" → cron PATH issue.
4. **Pre-create expected output files** with `:` or `touch` before invoking the tool, so downstream `wc -l`/`cat` don't error if the tool aborts early.
5. **Check `/etc/cron.d/<entry>` for explicit `PATH=` line** — some entries override the default. If present, that's the authoritative path.

The pattern `cmd 2>/dev/null || true` is a code smell in cron scripts. Replace with `cmd 2>"$STDERR_FILE" || log "cmd failed (stderr: $STDERR_FILE)"`.

*Source: `memory/feedback_cron_path_excludes_usr_local_bin.md`*

### Diagnose multi-replica services per-pod, not via the load-balanced service

When a service runs as multiple replicas behind one cluster service (e.g. SeaweedFS filer with 2 pods, multi-master DB, Loki distributors) and the symptom is **intermittent / probabilistic** (writes "succeed" but reads sometimes 404, replication "works" but only N% of the time), one of the replicas may have diverged. The cluster-IP / service URL hides this because every probe round-robins to a different pod.

**Why:** clients (and you, when debugging) connect to `svc/foo:port` and Cilium/kube-proxy picks an endpoint. If pod-A has full state and pod-B is missing 20% of recent writes, every probe is a coin flip on pod identity. Without inspecting each pod independently, you'll see "sometimes works, sometimes doesn't" and chase ghosts in the cross-cluster wiring or the application protocol.

**How to apply:** when symptoms are intermittent on a multi-replica service:

1. List the pods: `kubectl get pods -l app.kubernetes.io/component=foo -o wide`.
2. For each pod, port-forward directly to the pod (not the service): `kubectl port-forward pod/foo-0 LOCAL:REMOTE` and same for pod/foo-1.
3. Read the same resource from each pod independently. Tabulate: pod, resource, observed state.
4. If one pod is missing data, the issue is intra-cluster replication (peer-follow, raft sync, gossip) — not cross-cluster wiring. Look at the diverged pod's "follow peer" / replication-consumer logs.

**Caught by operator pushback 2026-05-05** ("are you trying to extrapolate how the sync behavior patterns are acting instead of studying the actual configuration on both k8s sites?"). Diagnostic was chasing `kubectl logs deploy/filer-sync` showing healthy progression and assuming the cross-site path was good; the actual break was that GR's filer-1 had been unable to subscribe to filer-0 since 2026-03-24 due to a separate stale-checkpoint problem. Reading per-pod bucket listings on GR (filer-0 had 4 entries, filer-1 had 2) revealed the real issue in one query.

**Companion check:** when a service has internal peer-replication (filer meta_aggregator, etcd raft, postgres logical replication, etc.), include `kubectl logs <pod-N>` for each replica in the diagnostic sweep — not just the deployment-level aggregate. The retry-loop for "can't follow peer" is silent in `kubectl logs deploy/...` if it only tails one pod.

*Source: `memory/feedback_per_pod_state_for_multi_replica_diagnosis.md`*

### Don't append dated content to CLAUDE.md — use the allocation table at its bottom

Rule: **if a documentation entry has a date in its headline, it almost certainly does not belong in CLAUDE.md.**

**Why:** CLAUDE.md hit 52.6 KB on 2026-05-06 (over the 40 KB Claude-performance threshold) because incident bullets accreted in the `Conventions` section across 2026-04-19 → 2026-05-06. Each individual bullet looked harmless in the moment (parsePoll fix, NVIDIA DLI cross-audit, scanner cron PATH fix, SeaweedFS recovery, status-page chaos red-link, agentic-platform sweeps, OpenAI SDK adoption batch, teacher-agent tiers, etc.). They compounded. Refactor on 2026-05-06 redistributed 27.7 KB to three already-referenced files with no information loss — every incident already had a memory/* or runbook home; the bullets were duplicates.

**How to apply** — when adding new documentation to claude-gateway, route by content shape:

| Content shape | Destination |
|---|---|
| Incident summary (post-mortem, multi-bug fix, dated narrative) | `memory/<descriptive_name>_<YYYYMMDD>.md` (+ index in `memory/MEMORY.md`) |
| Systemic platform feature (uses `## <Feature> (implemented YYYY-MM-DD)` pattern) | `.claude/rules/platform-features.md` |
| Host-specific operational note (per-host pressure, fragility, oddity) | `.claude/rules/infrastructure.md` |
| Workflow-editing convention or n8n gotcha | `.claude/rules/workflows.md` |
| OpenClaw / OOB / fallback-mode operational detail | `.claude/rules/openclaw.md` |
| CI/CD pipeline rule | `.claude/rules/ci-cd.md` |
| **Stable** architectural orientation (URLs, hostnames, top-level diagrams) | CLAUDE.md |
| Runbook / runnable recovery procedure | `docs/runbooks/<topic>.md` |

The same table now lives at the bottom of CLAUDE.md under "Where to add new content (so CLAUDE.md doesn't regrow)" — re-read it before adding anything.

**Companion rule:** if you DO need to mention a dated incident from CLAUDE.md (because it's load-bearing context for future sessions), use a 1-line summary + a pointer to the memory file. Never inline the multi-paragraph narrative.

**Detection:** `wc -c CLAUDE.md` should stay ≤ 35,000. If it crosses 40,000, refactor immediately — performance impact is real.

*Source: `memory/feedback_no_dated_content_in_claudemd.md`*

### Don't estimate time/duration; group work by logical cohesion, not time-bound buckets

**Rule:** never produce time-duration estimates ("~3 hours", "1-2 weeks", "Day 8", "ETA 9-12 weeks for full parity"). I do not have calibrated reasoning about how long things take. Group remaining work by **logical cohesion** — features that only make sense built together — not by time buckets.

**Why:** Operator pushback 2026-04-27 during the agentic-agriops rollout. I had:
- Labelled focused 1-3 hour sessions as "Day 1" through "Day 8", implying 8 calendar days when only 2-3 hours of actual time had passed across the conversation
- Estimated "Full Parity in 9-12 weeks" with no calibrated basis
- Estimated specific tasks as "1-2 hours" / "30 min" repeatedly when I have no record of how long any task actually takes

The cumulative effect: unreliable forecasting that the operator has to mentally discount. They specifically said: *"you are not good at that part (calculating time/duration)"*.

**What logical-cohesion grouping looks like:** instead of "Day 9 = Runner v2 + Poller + parsePoll start", say "**Phase B finish** = Runner v2 + Poller + full Matrix Bridge + Receiver — the dev-flow chain that only works as a unit". The unit cohesion is "things that have to land together to be useful".

**Examples for agentic-agriops remaining work:**

| Bad framing (time-based) | Good framing (logical cohesion) |
|---|---|
| Day 9 = Runner v2 + Poller (~3 hours) | **Phase B Lane 1 finish** — Runner async + Poller + full Matrix Bridge + Receiver |
| Days 10-12 = Lane 2 build (~3 days) | **Lane 2 customer support pipeline** — support-triage agent + 2 workflows + Chatwoot widget + Greek register calibration |
| Days 13-15 = Lane 3 v0 (~3 days) | **Lane 3 KB-only agronomy advisor** — agent + workflow + KB seed content |
| Days 16-19 = Lane 3 v1 (~4 days) | **Lane 3 customer-DB tooling** — postgres MCP + read-only role + per-tenant routing |
| Days 20-26 = Lane 3 v2 (~7 days) | **Lane 3 government-source ingest** — gov.gr + OPEKEPE + EU CAP scrapers + RAG pipeline |
| Days 27-30 = Eval + benchmark (~4 days) | **First honest scorecard measurement** — 50+ scenarios + RAGAS v2 + industry benchmark |
| Days 31-35 = Polish (~5 days) | **Parity capstone (optional)** — red-team + OTel + NIST telemetry + prompt patcher A/B |

**How to apply:**

1. When proposing future work, name it by what-it-builds (the logical unit), never by when-it-finishes.
2. When a unit is too big to fit one session, split it by what's INTERNALLY cohesive (e.g. "judge data-flow plug" + "Matrix-bridge slice" can each ship independently and provide value), not by arbitrary time slices.
3. When operator asks "how much is left", answer in **count of logical units remaining** + their dependencies, not weeks/days.
4. When recording shipped work in memory, use the unit name (e.g. "Phase B Lane 1 finish") not "Day N".
5. Existing "Day 1-8" labels in agentic-agriops-project.md memory are historical artifacts — don't rewrite them, but also don't extend the pattern.
6. Tracking progress within a session: TaskCreate units named by the deliverable, no time annotations.

**When this rule kicks in:** any time I'm tempted to write "~3 hours", "next session", "Day N", "by week X", or "ETA". All of those should become "this unit" or "the next unit" or omitted entirely.

**Cross-references:**
- `agentic-agriops-project.md` — where I created the bad pattern
- `feedback_no_jargon.md` — operator-vocabulary discipline (related: don't use SRE-jargon timelines)
- `feedback_single_operator.md` — operator does the work; my job is to help them, not project-manage

*Source: `memory/feedback_no_time_estimates_group_by_logical_units.md`*

### Explicit stop conditions when sweeping list-shaped LLM output

Don't write a parser that does "take everything from the marker line to end-of-string and split on `\n`." That's how `Prepare Result.parsePoll` swept *"Awaiting approval to proceed. Reply 'approved' to execute."*, *"My recommendation is Plan A..."*, and *"Then file a follow-up task..."* into Matrix poll options across ~17/70 polls (2026-04-25 commit `9f680fc`).

**Why:** LLMs commonly add post-list prose: a closing safety net, a recommendation, a caveat, a footnote. None of it is part of the structured payload, but a greedy parser can't tell. The Matrix poll renderer dutifully turned each absorbed line into a clickable option that did nothing on click.

**How to apply** when sweeping a list out of free-form LLM text:
- Sweep with **explicit stop conditions**: blank line, `CONFIDENCE:`, `[AUTO-RESOLVE...]`, heading (`^#{1,6}\s`), or any line starting with prose lead-ins like `Awaiting approval`, `Reply approved`, `My recommendation`, `Then file`, `Note:`, `Notes:`, `Caveat:`, `Also[, ]`.
- Strip both `[-*+]\s+` bullet markers AND `\d+[.)]\s+` numbered-list prefixes before deciding whether a line is "an option" or "prose."
- A blank line ends the block iff at least one option has been collected (tolerates a leading blank between marker and first bullet).
- Add a regression test for each prose form actually observed in production. The patterns above are the empirical bug list, not a guess.

*Source: `memory/feedback_explicit_stop_conditions_when_sweeping_llm_lists.md`*

### Freedom ONT (Genexis XGS-PON) requires forced PoE re-detect after long down

**Rule.** After Freedom has been shut for more than a few minutes, bringing
`nl-sw01 Gi1/0/36` back up with plain `no shutdown` is NOT sufficient
to restore the link. The Genexis XGS-PON ONT loses its PON training during
the power-off window and does not re-negotiate on its own when PoE is
restored.

**Symptom.** After `no shutdown`:
```
GigabitEthernet1/0/36 is down, line protocol is down (notconnect)
```
…even with `show power inline Gi1/0/36` reporting `Oper: on`, Class 3 PD
detected, 15.4 W drawn. The PoE is delivering but no Ethernet link comes
back from the splitter/ONT side.

**Why.** The TL-PoE10R splitter re-delivers power to the ONT, but the
ONT's PON-side fibre training with Freedom's OLT is a separate handshake
that the ONT only retries under certain reset conditions. A plain
`no shutdown` keeps the PoE output continuous (no power dip) — the ONT's
firmware sees the same power rail and doesn't re-initialise the PON
state machine.

**Fix (2026-04-22 exercise, confirmed working).**
```
nl-sw01# configure terminal
nl-sw01(config)# interface Gi1/0/36
nl-sw01(config-if)# power inline never
nl-sw01(config-if)# power inline auto
nl-sw01(config-if)# shutdown
nl-sw01(config-if)# no shutdown
nl-sw01(config-if)# end
```
The `power inline never` cuts PoE completely (ONT goes dark). `power inline
auto` re-enables PD detection. The `shut`/`no shut` then forces a fresh
PoE re-detect + Ethernet link training. ONT cold-boots cleanly, fibre
trains with the OLT, PPPoE negotiates in ~60–90 s.

**Alternative (not tested — use only if CLI not available).** Physically
unplug the PoE cable from the splitter for ~5 s, then reconnect. Same
effect.

**Expected link behaviour.** The port will flap during ONT boot:
`up → down → up` over ~30 s as the ONT asserts Ethernet before PON sync,
loses it, and re-asserts once sync completes. The last `up` is the one
that matches PPPoE negotiation on nl-fw01.

**Timing from the 2026-04-22 exercise.**

| Step | Elapsed |
|---|---|
| First `no shutdown` (did NOT work) | T0 |
| `power inline never/auto` + `shut`/`no shut` cycle | T0 + 5 min |
| Ethernet link stable `up (connected)` | + 2 s (after 2 flaps) |
| nl-fw01 `outside_freedom` IP assigned (PPPoE UP) | + 90 s |
| Freedom VTIs Tunnel4/5/6 `up`, BGP Established | + 120 s |
| mesh-stats `Nominal — 9/9 tunnels` | + 120 s |

**When to apply.** Any planned Freedom maintenance that shuts nl-sw01
Gi1/0/36 for more than ~5 min should plan the recovery as:
1. `power inline never` (explicit ONT de-power)
2. Wait 5 s
3. `power inline auto`
4. `shutdown` (clean interface)
5. `no shutdown` (link up → ONT boot → PPPoE)

For a brief shut (< 1 min) a plain `no shut` will usually work because
the ONT holds PON state that briefly. Beyond that window, use the full
recycle pattern.

**Related.** Update `docs/failover-simulation-freedom-ont-20260422.md`
post-test section with this gotcha. The `freedom-ont-shutdown` chaos
scenario in `experiments/catalog.yaml` must include this in its
recovery runbook reference before it's automated end-to-end.

*Source: `memory/freedom_ont_poe_recycle_gotcha_20260422.md`*

### GIT_STRATEGY=empty + manual clone bypasses refs/pipelines fragility

If a GitLab Runner job fails get_sources with `fatal: couldn't find remote ref refs/pipelines/<id>` and the job doesn't depend on the runner's git checkout (e.g. it's going to `rm -rf .git` or `cp -a` anyway), bypass the runner's get_sources via `GIT_STRATEGY: empty`.

**Why:** GitLab Runner v18.6.1's default `GIT_STRATEGY: fetch` issues a single `git fetch` command with a refspec list including `refs/pipelines/<id>`. If any refspec fails, the whole fetch aborts — even if the alternative refs (`refs/heads/main`) would have resolved fine. The `refs/pipelines/<id>` refs are created by GitLab when the pipeline starts and pruned when it ends; under transient Gitaly conditions they can be unavailable to the runner.

`GIT_STRATEGY: empty` short-circuits the runner's get_sources to `RmDir($CI_PROJECT_DIR) + MkDir($CI_PROJECT_DIR)` — no git operation. Verified in `gitlab-runner` source: `shells/abstract.go:740-744`, `case common.GitEmpty:`.

**How to apply:**

```yaml
my_job:
  variables:
    GIT_STRATEGY: empty
  before_script:
    - apt-get update -qq && apt-get install -y -qq git curl jq >/dev/null 2>&1
    - git clone "$CI_REPOSITORY_URL" .
    - git -c advice.detachedHead=false checkout "$CI_COMMIT_SHA"
    # ... rest of original setup
```

`$CI_REPOSITORY_URL` includes embedded `gitlab-ci-token` credentials so the clone works without extra auth. The clone always has the SHA reachable from the branch tip (newer commits since pipeline creation are uncommon and would only matter if the pipeline raced with another push).

**Trade-off:** ~5-15s extra per job for the full clone vs the runner's incremental fetch. Usually negligible. Don't blanket-apply this to every job — only the ones that don't depend on the runner's prepared git tree.

Caught 2026-05-01 in claude-gateway sync_to_github after pipeline 25538's runner failed at `fatal: couldn't find remote ref refs/pipelines/25538`. Fix landed in commit 63be431; verified with 4-pipeline stress test.

**Related:**

- `feedback_resource_group_interruptible_deadlock.md` — separate fix on the same job.
- `feedback_classify_pipeline_failures_by_step.md` — got to this fix only after grouping the 7 failures by their actual step (6 of them were the gitignore class, only 1 was the refs/pipelines class).

*Source: `memory/feedback_git_strategy_empty_bypass.md`*

### Grep for hardcoded host paths after migrating between deploy targets

# Grep for hardcoded paths after host migration

When a script moves between deploy targets — e.g. `/home/app-user/.ssh/one_key` (openclaw container) → `/home/app-user/.ssh/one_key` (nl-claude01) — patching the central config file is necessary but not sufficient. Grep the FULL repo for the old path string before declaring portability done.

**Why:** During the cc-cc migration (2026-04-29) I patched `openclaw/skills/site-config.sh` with `${TRIAGE_SSH_KEY:-...}` env-var fallbacks and assumed the triage scripts that source it would inherit. They mostly did, except `openclaw/skills/security-triage/security-triage.sh` which had its own `SSH_KEY="/home/app-user/.ssh/one_key"` constant on line 62 (defined locally, ignoring the sourced env). The synthetic-alert verification surfaced it as `Permission denied (publickey)` — the wrapper dispatch worked, the script ran to completion (exit 0), but the SSH-into-scanner step silently failed and the triage report had `(scanner unreachable?)`. A real alert would have produced an unhelpful triage that LOOKED successful.

**How to apply:**

1. Before declaring a host migration done, grep the whole repo for the old environment's path patterns:
   ```
   grep -rn "/home/node/" scripts/ openclaw/skills/ workflows/
   grep -rn "/root/.openclaw" scripts/ openclaw/skills/
   ```
2. For every hit that's NOT inside a fallback chain (like `${VAR:-/home/app-user/.ssh/...}`), patch it with an env-var fallback or a runtime probe (`[ -r ... ] && SSH_KEY=...`).
3. Don't trust `source site-config.sh` to fix all of them — local script constants set after the source override the sourced value, which is the exact bug that bit us on security-triage.sh.
4. After patching, **re-run the actual end-to-end path** (synthetic alert in this case) and look for `Permission denied`, `No such file`, `not found`, exit-code-0-with-warnings — not just exit-zero overall.

Patch pattern actually used:

```bash
# Host-portable: openclaw container default → app-user repo path → env override
SSH_KEY="${TRIAGE_SSH_KEY:-/home/app-user/.ssh/one_key}"
[ ! -r "$SSH_KEY" ] && [ -r "/home/app-user/.ssh/one_key" ] && SSH_KEY="/home/app-user/.ssh/one_key"
```

This works on BOTH hosts without an env var being set, AND honors `TRIAGE_SSH_KEY` when it is.

*Source: `memory/feedback_grep_hardcoded_paths_after_host_migration.md`*

### Grep for parser-pattern duplication BEFORE declaring a fix complete

When you fix a parser bug — especially in n8n workflow Code nodes — search the entire repo for the buggy regex/pattern signature before declaring done.

**Why:** Workflow Code nodes have no shared library. The 2026-04-25 parsePoll fix landed clean in `Prepare Result` (Runner) on the first commit (`9f680fc`), but the **identical buggy regex** was also duplicated in `Prepare Bridge Response` of the matrix-bridge workflow. The bridge bug was only caught when the second-round deep-sweep ran `grep -lE "\\\\\\\[POLL\\\\\\\]\\\\s\*\(\.\+\?\)" workflows/*.json` — turned up matrix-bridge as STILL BUGGY. Required a follow-up commit (`eec74a9`).

**How to apply:**
- Right after writing a fix for parser code in a workflow node, run `grep -rn` across `workflows/`, `scripts/`, and `openclaw/` for the buggy regex literal AND the function name (`parsePoll`, `parseConfidence`, etc.).
- Treat any other hit as an unfixed instance until proven otherwise. Audit each.
- Before committing, also re-run `validate-n8n-code-nodes.sh` against every workflow that mentions the function — not just the one you edited.
- Add a regression test that drives the *real* parser from each workflow JSON (not a Python re-implementation), so future test runs catch any duplicated parser drifting.

This rule is broader than just polls — it applies to any parser pattern you find duplicated across workflow Code nodes (credential redaction, confidence extraction, JSON validators, etc.).

*Source: `memory/feedback_grep_for_parser_duplication.md`*

### HAProxy allowlist is the safety net — deploy compose + frontend in one shot

When deploying a service that will sit behind an HAProxy `silent-drop if !<service>_allowed` allowlist gate, deploy the whole stack in one shot — `docker compose up -d` AND the live HAProxy backend AND the live frontend ACL block AND the live allowlist file AND the reload — not "internal-only first, validate, then flip HAProxy."

**Why:** The allowlist already restricts the service to operator IPs (NL ASA Freedom + NL ASA XS4ALL + GR ASA Inalan + Ilias + loopback for agentic-agriops). Splitting deploy into two steps gives no extra safety; it just creates two ways to fail (compose works but HAProxy doesn't, or vice versa) and forces awkward `curl --resolve` testing. The deployment pattern existing tenants on the host already use is "compose + HAProxy + reload, all together."

**How to apply:**
- For services WITH an allowlist gate (`youtrack`, `n8n`, `grafana` in agentic-agriops, plus the existing tenant pattern): single deploy step, full chain live.
- For services on a public surface with NO allowlist (`chatwoot`/`support.meshsat.org`, `gatus`/`status.meshsat.org`): same single-step deploy — CrowdSec is the gate, no extra "validate internal first" stage.
- "Internal-only first" is the right pattern ONLY for services that must never be publicly reachable: Ollama, Prometheus, Alertmanager, Loki, internal Postgres/Redis. These bind to the docker network or `127.0.0.1` permanently and never get an HAProxy frontend.

*Source: `memory/feedback_allowlist_is_the_safety_net.md`*

### HAProxy backend ssl/verify required when target serves nginx-with-TLS

When a HAProxy edge VPS forwards to a backend that terminates TLS at the application layer (nginx-in-Hugo-container, Authentik, or any cert-mounted app), the `server` line MUST include `ssl verify required ca-file /etc/ssl/certs/ca-certificates.crt`. Plain-HTTP backend connections to a TLS-terminating target return 400 → HAProxy passes through → client sees REFUSED_STREAM via HTTP/2 or "Empty reply from server" via HTTP/1.1.

**Why:** Caught 2026-05-06 during omoikane SaaS migration to notrf01dmz01+02. The migration spec said `server no-dmz01 10.255.X.X:8456 check`. The Hugo containers there mount `/srv/certs/*.pem` and bind nginx with TLS. Without `ssl` on the HAProxy server line, every request returned 400 from nginx, and clients got 000.

**How to apply:** Match the pattern of cubeos/mulecube/withelli/meshsat backends already in the same haproxy.cfg — those have `ssl verify required ca-file /etc/ssl/certs/ca-certificates.crt check inter 10s fall 3 rise 2`. New SaaS deploys terminating TLS at the container layer should mirror this. Plain-HTTP backends (Rust daemon on `:8459`, Authentik on `:9000`) don't need the `ssl` flag.

**Quick check before adding a new backend:** `curl -sk https://<dmz-host>:<port>/` (HTTPS) vs `curl -s http://<dmz-host>:<port>/` (HTTP). If HTTPS works and HTTP returns 400, the backend is TLS-terminated → use `ssl verify required ...`.

*Source: `memory/feedback_haproxy_backend_tls_required_for_hugo_nginx_targets.md`*

### HAProxy has a 64-words-per-line limit — use multi-line ACL pattern for host lists

**Rule:** when an HAProxy line contains a chain of `|| { hdr(host) -i X }` clauses, refactor into multi-line `acl is_known_host hdr(host) -i X` (one per host) plus a single `<directive> ... is_known_host` reference. Same logical effect — different syntax — and avoids the 64-word-per-line limit.

**Why:** caught 2026-04-27 on defra HAProxy when adding the monitoring stack. The `http-request deny deny_status 404 unless { hdr(host) -i agri.meshsat.org } || ... || { hdr(host) -i status.meshsat.org }` line had grown to 12 hosts (the original 4 ERP tenants + 7 agentic services + 1 demo tenant + 2 monitoring). HAProxy 2.8.16 hit the limit and aborted with:

```
[ALERT] config : parsing [/etc/haproxy/haproxy.cfg:114]: too many words, truncating after word 64, position 440: <}>.
[ALERT] config : Fatal errors found in configuration.
```

Each `|| { hdr(host) -i X }` is ~5 words. At 12 hosts that's ~60 words plus the `http-request deny deny_status 404 unless` prefix → over 64. The reload failed; backup-restore needed.

The operator's existing `is_authenticated_site` ACL on the same file was already using the multi-line pattern correctly:
```haproxy
    acl is_authenticated_site hdr(host) -i agri.meshsat.org
    acl is_authenticated_site hdr(host) -i komotini-agri.meshsat.org
    acl is_authenticated_site hdr(host) -i straytrack.meshsat.org
    acl is_authenticated_site hdr(host) -i nigrita-agri.meshsat.org
```

Applying the same shape to the 404-fallback fixed it cleanly.

**How to apply:**
- When you see a `|| { ... }` chain growing past 8-10 entries, refactor proactively.
- Replace the inline chain with one ACL per line:
  ```haproxy
  acl my_acl hdr(host) -i agri.meshsat.org
  acl my_acl hdr(host) -i ...
  ...
  http-request <action> ... unless my_acl
  ```
  HAProxy treats multiple `acl <same_name>` lines as logical OR within that ACL.
- The same approach works for any kind of pattern matching, not just `hdr(host)`. Stick with `acl name <fetch> <pattern>` per line.

**Other 64-word traps to watch:** the `crowdsec_whitelist` `-f /etc/haproxy/acl/X.txt -f /etc/haproxy/acl/Y.txt ...` chain. At ~3 words per `-f` entry, you can fit ~20 file references before hitting 64. Past that, refactor with multiple `acl crowdsec_whitelist src -f X.txt` lines (one per file).

*Source: `memory/feedback_haproxy_64_word_line_limit.md`*

### HAProxy named defaults — split http_defaults + tcp_defaults when mixing modes

**Rule:** when haproxy.cfg has both HTTP and TCP frontends/backends, split `defaults` into two named blocks (`defaults http_defaults` + `defaults tcp_defaults`) and tag each frontend/backend with `from http_defaults` or `from tcp_defaults`. Don't try to silence warnings on a single TCP backend with `no option …` — `option forwardfor` specifically rejects negation in HAProxy 2.x.

**Why:** HAProxy emits an ignored-with-warning per HTTP-only option per TCP backend at startup. The `crowdsec-spoa` backend on defra produced 2 warnings every reload (`option http-buffer-request`, `option forwardfor`). The accepted CrowdSec SPOE doc-pattern just shrugs and tells you to ignore them, but the noise pollutes haproxy validation output and masks real warnings during config edits.

**The wrong fix that bites you:**
```haproxy
backend crowdsec-spoa
    mode tcp
    no option http-buffer-request   # OK, accepted
    no option forwardfor            # ALERT — fatal config error in 2.8+
```
HAProxy 2.8.16 (Ubuntu 24.04 default): `'negation/default is not supported for option 'forwardfor'`. Reload fails. The running config keeps serving (good), but you cannot reload until you back this out.

**The right fix — named defaults:**
```haproxy
defaults http_defaults
    log     global
    mode    http
    option  httplog
    option  forwardfor
    option  http-server-close
    option  http-buffer-request
    timeout connect 5s
    timeout client  30m
    timeout server  300s
    ...

defaults tcp_defaults
    log     global
    mode    tcp
    option  dontlognull
    timeout connect 5s
    timeout client  30m
    timeout server  300s

frontend https_in from http_defaults
    bind *:443 ssl crt /etc/haproxy/certs/
    ...

backend agriops_youtrack from http_defaults
    server yt 127.0.0.1:8181 check ...

backend crowdsec-spoa from tcp_defaults
    server spoa 127.0.0.1:9000
```
Each frontend/backend pulls timeouts/options from the appropriate named defaults. Zero warnings.

**How to apply:**
1. Backup `haproxy.cfg` with a timestamped name before any structural edit.
2. Stage the new file at `/tmp/haproxy.cfg.refactored`, validate with `sudo haproxy -c -f /tmp/haproxy.cfg.refactored` BEFORE replacing the live one.
3. Swap, reload, then re-validate the live file (`haproxy -c -f /etc/haproxy/haproxy.cfg`) — confirms no surprise drift between staged and live.
4. Smoke-curl every hostname to confirm no service fell off.

**When this rule kicks in:** any haproxy.cfg with `mode tcp` on at least one frontend or backend. Single-mode (all HTTP or all TCP) configs don't need the split.

**Caught:** 2026-04-27 on `defra01agri01` while deploying `kb.meshsat.org`. Operator asked to fix the 2 warnings; quick `no option …` attempt broke reload (fatal on `forwardfor`); reverted; refactored to named defaults — clean validation, all 8 hostnames respond.

**Cross-references:**
- `feedback_haproxy_64_word_line_limit.md` — the other defra HAProxy 2.x gotcha
- `feedback_allowlist_is_the_safety_net.md` — the deploy pattern this fits inside

*Source: `memory/feedback_haproxy_named_defaults_for_mixed_modes.md`*

### Heredoc-with-pipe in Python is a silent no-op

In bash, `echo "$DATA" | python3 << 'EOF' ... EOF` does **NOT** pipe `$DATA` to Python's stdin. The heredoc redirection (`<<`) claims stdin first; the pipe input is discarded silently. Inside the Python heredoc, `sys.stdin.read()` returns an empty string and `for line in sys.stdin` iterates zero times.

**Why:** Caught 2026-04-28 in `scripts/poll-openclaw-usage.sh` v1. Initial version:
```bash
LISTING=$(ssh ... 'find ... -exec stat ... +')
echo "$LISTING" | python3 << 'PYEOF'
for line in sys.stdin:  # always 0 iterations
    ...
PYEOF
```
Result: "inserted 0 llm_usage rows; watermark covers 0 files" despite 15 valid JSONL files in the listing. Lost 15 minutes debugging Python parsing logic before noticing the shell wiring.

**How to apply:**

Three correct patterns:

1. **Short code** — use `python3 -c '...'`:
   ```bash
   echo "$DATA" | python3 -c 'import sys; ...'
   ```

2. **Longer scripts via env var** — export then read from `os.environ`:
   ```bash
   export DATA
   python3 << 'PYEOF'
   import os
   data = os.environ.get('DATA', '')
   for line in data.splitlines():
       ...
   PYEOF
   ```

3. **Longer scripts via `python3 - <<EOF` with file redirect** — uses `-` to read script from stdin AND `<<<` here-string for data:
   ```bash
   python3 - "$DATA" << 'PYEOF'
   import sys
   data = sys.argv[1]
   ...
   PYEOF
   ```

The first two are clearer. Avoid `echo X | python3 << 'EOF'` entirely — the failure is silent and will pass syntax checks.

*Source: `memory/feedback_no_heredoc_with_pipe_in_python.md`*

### Hook output format — silent allow, plain text deny

Claude Code hooks (PreToolUse, PostToolUse, UserPromptSubmit, SessionStart, SessionEnd, Stop, PreCompact) expect:
- **Exit 0 (allow / fire-and-forget):** No stdout output. Silent exit. Any stdout is parsed as JSON and triggers "Hook JSON output validation failed" if schema doesn't match.
- **Exit 2 (deny or reject_content — PreToolUse only):** Plain text on stdout shown as error message to the model. NOT JSON — just a human-readable string.

**Why:** The unified-guard.sh hook was outputting `{"decision": "allow"}` on every allowed Bash/Edit/Write command. Claude Code tried to parse this as its internal hook response schema, failed, and logged "JSON validation failed" on every tool call. This caused hundreds of spurious errors in sub-agent contexts.

**How to apply:** When writing any hook script, never output anything to stdout on the allow path. Only output on the deny path (exit 2), and use plain text, not JSON.

**3-behavior taxonomy (IFRNLLEI01PRD-639, 2026-04-20):** still honours the exit-code contract. `allow` = silent exit 0. `deny` and `reject_content` both = exit 2 with stdout prose, but the PROSE differentiates — deny messages lead with "Blocked: ..." (irrecoverable, don't retry), reject_content with "Rejected: ..." (recoverable, includes a retry hint). The taxonomy lives in `event_log.payload_json.behavior` for Grafana audit — Claude Code only sees the string. An audit invariant in `scripts/audit-risk-decisions.sh` rejects any `reject_content` row with an empty message.

**Wired hooks (2026-04-20):**
- `unified-guard.sh` — PreToolUse (Bash/Edit/Write) — 3-behavior taxonomy
- `audit-bash.sh` + `protect-files.sh` — legacy companions, same taxonomy (retained for sites that wire them standalone; never emit JSON)
- `snapshot-pre-tool.sh` — PreToolUse — writes `session_state_snapshot` row BEFORE mutating tools (Bash/Edit/Write/Task), skips read-only tools (Read/Grep/Glob/LS/ToolSearch)
- `session-start.sh` — SessionStart — seeds turn 0, emits `agent_updated`
- `post-tool-use.sh` — PostToolUse — emits `tool_ended`, bumps `tool_count`/`tool_errors`
- `user-prompt-submit.sh` — UserPromptSubmit — advances turn, emits `message_output_created`, detects `[POLL]` responses → `mcp_approval_response`
- `session-end.sh` — SessionEnd — `on_final_output` equivalent: finalises last open turn, flips agent back to operator
- `mempal-session-save.sh` — Stop — transcript auto-save every 15 msgs
- `mempal-precompact.sh` — PreCompact — emergency transcript save

All telemetry-emitting hooks (post/start/session-end) swallow their own errors so a telemetry hiccup never kills the caller. They all exit 0 silently — never write JSON to stdout.

*Source: `memory/feedback_hook_output_format.md`*

### Hugo {{ $data | jsonify | safeJS }} doesn't escape </script> and raw m.field concat parses as HTML

Two coupled traps in any Hugo shortcode that (a) injects a JSON blob into an inline `<script>` and (b) string-concatenates fields from that blob into `innerHTML`:

1. **`{{ $stats | jsonify | safeJS }}` does NOT escape `</script>`.** Hugo's `jsonify` emits literal `<`, `>`, `/` inside string values; `safeJS` opts out of any downstream sanitisation. The moment any webhook string field contains `</script>` the inline script terminates and the widget breaks (and an attacker who controls the upstream gets script execution). Defence: wrap with `JSON.parse({{ $stats | jsonify | safeJS }})` — `JSON.parse` of a JSON literal is identical at runtime but stops the `</` injection because the JSON string is a JS string literal, not the script body itself. Or post-process the jsonify output with a tag-aware escape.

2. **Raw concatenation of string fields into innerHTML.** `'<span>'+m.model+'</span>'` parses `<synthetic>` as an unknown HTML tag — the surrounding span auto-closes and the model name **renders blank** on the live page. The webhook actually shipped a model literally named `<synthetic>` (test-traffic leak from `/webhook/agentic-stats` `ncUp08mWsdrtBwMA`), and the Tier 2 last row on the live agentic-chatops page rendered with no model name. Same trap inside `title="…— '+m.model+'"` (breaks on any `"` in the string).

**Why:** the operator's pattern of "n8n webhook → Hugo data file → inline-script widget" is widespread (agentic-stats, lab-stats, mesh-stats shortcodes). Every one of them is reachable by whatever writer feeds the webhook. Two layers of defence: escape JSON for script context AND escape strings for HTML context.

**How to apply:** any time you touch `layouts/shortcodes/*-stats.html` or write a new one:
- Wrap the data with `JSON.parse(...)`.
- Add a small `function esc(s){return String(s).replace(/[<>&"']/g, c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));}` helper and pass every external string through it before concat.
- Or build with `document.createElement` + `.textContent` instead of `innerHTML`.
- For chart `title` attributes, escape `"` separately.

**Canonical example (validated by Playwright 2026-05-11):** see `kyriakos:layouts/shortcodes/agentic-stats.html` post-commit `729f0bb`. Pattern: `<script id="agentic-stats-data" type="application/json">{{ $stats | jsonify | safeJS }}</script>` + `data = JSON.parse(document.getElementById('agentic-stats-data').textContent)` inside the renderer, with `try/catch` falling back to the "stats unavailable" card. **Sibling shortcodes (`lab-stats.html`, `lab-data.html`, `mesh-health.html`) likely still have these gaps — copy the pattern when you next touch them.**

*Source: `memory/feedback_hugo_shortcode_safejs_injection.md`*

### JUDGE_BACKEND defaults to local (gemma3:12b)

Judge and synth defaults moved to local Ollama on 2026-04-19 to eliminate ~$5-10/month Haiku spend. The operator explicitly doesn't have that budget.

**Why:** calibration (60-query dual-score) = 85% agreement with Haiku. Local is +5pp looser (6 false positives vs 3 false negatives across 60 cases). Acceptable for steady-state work; below the 95% threshold where absolute numbers are fully interchangeable.

**How to apply:**

- **Default (do nothing):** `JUDGE_BACKEND=local`, `SYNTH_BACKEND=qwen`. Works for 100% of the categories operator actually runs week-to-week: architecture, multi-hop, corroboration, cost, negation, timeboxed, synthesis, recency, monitoring, etc.
- **Explicitly flip to Haiku** (`JUDGE_BACKEND=haiku` / `SYNTH_BACKEND=haiku`) when:
  1. Benchmarking KG traversal / policy / meta / specific-incident queries — those categories show 20-33% disagreement and Haiku is the more reliable judge.
  2. Re-establishing calibration reference after a rubric or prompt change.
  3. Investigating a suspected scoring drift (is local getting looser over time?).
- **Max-effort escalations** (confidence<0.7, duration>5min, thumbs-down sessions) still use Opus automatically in `llm-judge.sh`. Don't disable that — local can't match Opus on the hardest judgments.
- **When comparing hit rates across 2026-04-19**: stamp the judge source on any chart or number. The +5pp calibration gap means a 0.90 → 0.96 change post-flip could be zero real improvement. Real pipeline wins need to exceed +5pp or be confirmed under a single judge era.

**Files that respect `JUDGE_BACKEND`:** `scripts/run-hard-eval.py`, `scripts/ragas-eval.py`, `scripts/llm-judge.sh`. `scripts/kb-semantic-search.py` uses `SYNTH_BACKEND` (same local/haiku logic, different env name because it's a different task).

**Calibration cadence:** `scripts/judge-calibration.py` — annual or on-change. One-off ~$0.06 Haiku cost per run. Writes dated `docs/judge-calibration-YYYY-MM-DD.{md,json}`.

*Source: `memory/feedback_judge_backend_local_default.md`*

### LibreNMS REST API exposes no ifSpeed override endpoint

**Rule.** When you need to override `ifSpeed` on a LibreNMS port (e.g. asymmetric DSL where Cisco `BW = min(DS, US)` produces a wrong polled value), do NOT spend time looking for a REST API endpoint — there isn't one. The full route list at `GET /api/v0/` on a LibreNMS instance confirms: the only port-write routes are `update_port_description` and `update_device_port_notes`. PATCH on `/ports/{id}`, `update_port_field`, attribute-write — none exist.

**Why:** LibreNMS's WebUI form (`includes/html/forms/update-ifspeed.inc.php`) writes to two places — `ports.ifSpeed` (column) and `devices_attribs[ifSpeed:<ifName>]` (the poller checks this attribute on each cycle and applies as override). Neither is reachable from `/api/v0/...`. Caught 2026-05-09 mid-Freedom-outage when the operator (correctly) said "use the API to configure the interface" and I had already wandered into PHP source + MariaDB schema before realising the REST surface didn't expose this.

**How to apply.** When asked to override port ifSpeed on LibreNMS:
1. Confirm via `curl -sk -H "X-Auth-Token: $LIBRENMS_API_KEY" "$LIBRENMS_URL/api/v0/" | grep -iE "port|ifspeed|attrib|field"` that no write route exists. Reading the API root listing first is cheaper than diving into source code.
2. Surface the gap to the operator immediately and offer the three non-REST paths:
   - WebUI form endpoint: authenticated POST to `/ajax_form.php` with `type=update-ifspeed`, `port_id=<id>`, `speed=<bps>`. Same path the WebUI sidebar's "Set port speed manually" uses; produces a clean `eventlog` entry tagged `Port speed set manually: <speed>`.
   - `lnms` CLI on the LibreNMS host (e.g. `nl-nms01:/usr/bin/lnms`).
   - Direct DB write — UPDATE `ports.ifSpeed` AND INSERT/UPDATE `devices_attribs` row keyed `ifSpeed:<ifName>`.
3. Do NOT lead with "I'll dive into the source" — that's the wrong order when an API endpoint is the natural ask. Confirm the API gap first, then ask which fallback the operator is comfortable with.

*Source: `memory/feedback_librenms_api_no_ifspeed_override.md`*

### LibreNMS check_cororings hard-codes expected cluster size in every service

The Nagios plugin `/usr/lib/nagios/plugins/check_cororings` SSHes to the target, parses `corosync-cfgtool -s`, and counts `nodeid: N: (connected|localhost)` lines. The `--rings N` flag is **misleadingly named**: it actually asserts cluster **member count**, not network ring count. Mismatch → CRITICAL.

The 6-member NL+GR PVE cluster is monitored from 4 NL vantage points (nl-pve01..nlpve04) + 2 GR vantage points (gr-pve01/02) = 6 services, each with `--rings 6`. Operator wants to keep this hard-coded pattern (the change-detection value is worth the touch cost — agreed 2026-05-10).

**How to apply when adding or removing a PVE node:**

1. New cluster member count = `N`.
2. PATCH every `cororings` service's `service_param` from `--rings <old>` to `--rings <new>`:
   ```
   curl -sk -X PATCH -H "X-Auth-Token: $KEY" -H "Content-Type: application/json" \
     -d '{"service_param":"check_cororings --host <hostname> --rings <new>"}' \
     "$URL/api/v0/services/<svc_id>"
   ```
3. For an ADD: also `POST /api/v0/devices` (NL side) and `POST /api/v0/services/<new-hostname>` with type=cororings.
4. Force re-poll: `ssh root@<nms> 'sudo -u librenms /opt/librenms/check-services.php'`.
5. Verify all 6 services return status=0 OK.

NL svc_ids (as of 2026-05-10): nl-pve01=10, nl-pve02=9, nl-pve03=16, nlpve04=40. GR svc_ids: gr-pve01=12, gr-pve02=13.

Caught 2026-05-10 after onboarding nlpve04 — 5 services were stuck CRITICAL ("Expected 5 connected nodes but found 6") and 1 new service was needed for nlpve04.

*Source: `memory/feedback_librenms_cororings_hardcoded_per_node.md`*

### LibreNMS port-utilisation alarm false-fires on asymmetric DSL/VDSL2

Cisco IOS-XE on ISR4321/NIM-VAB-A reports a single `BW` per VDSL interface = `min(downstream_sync, upstream_sync)`. On asymmetric VDSL2 (e.g. Profile 17a giving ~111 Mbps DS / ~33 Mbps US) `BW = 33,031 Kbit/sec`. LibreNMS pulls this into `ifSpeed`, and `Port utilisation over threshold` (rule_id=6 on nl-nms01, query `((max(InOctets_rate, OutOctets_rate)*8) / ifSpeed) * 100 >= 90`) divides actual rate (which can hit DS sync = ~111 Mbps inbound) by the LOWER (US) sync = 33 Mbps, producing readings >100% even at 50% real utilisation.

Cisco's `show interfaces` `txload`/`rxload` use the same `BW` field, so they ALSO mislead on asymmetric lines (`rxload 255/255` while real DS utilisation is ~46%).

**Why:** Caught on 2026-05-09 during the Freedom-ISP outage when alarm 64 (rule 6) on nlrtr01:Et0/1/0.6 (port_id 123127) was re-firing every 300s. Live `show controllers vdsl 0/1/0` confirmed DS Channel0 Speed 111,214 kbps / US Channel0 Speed 33,031 kbps and Cisco `BW 33031 Kbit/sec`. Real downstream utilisation was 46%, real upstream 64% — nowhere near saturation. The alarm was a direction-mismatch artefact, not real saturation. Re-notification interval = 300s with `count: -1` → unlimited noise for the duration of the outage.

**How to apply:**
1. Whenever a LibreNMS port-utilisation alert fires on a VDSL/ADSL/G.fast/asymmetric-line edge router, run `show controllers vdsl <slot>` on the device first — note `Speed (kbps)` for DS Channel0 and US Channel0 (or `show controllers efm-grp` / equivalent for non-VDSL DSL).
2. If they differ materially (>2x), the LibreNMS `ifSpeed` is the lower of the two and the alarm is a direction-mismatch on the higher-bandwidth direction.
3. Fix: PATCH the LibreNMS port to override `ifSpeed` to the downstream sync rate (the larger of the two), or add a per-port exception to rule 6.
4. Cisco `rxload`/`txload` from `show interfaces` are similarly suspect — don't quote them as evidence of saturation on asymmetric lines.
5. Operator-configured shaper drops on the upstream policy-map (e.g. `BUDGET_UL_PARENT_NORMAL cir 30000000`) ARE real symptoms but live in a different alarm dimension (port discards / drop-rate), not utilisation %.

*Source: `memory/feedback_libre_nms_asymmetric_dsl_ifspeed.md`*

### Log10-of-tokens as flex-grow inside a stacked bar segment misrepresents proportions by orders of magnitude

Setting `flex-grow=Math.round(Math.log10(tokens)*10)` on per-model segments inside a stacked bar makes the visual ratio between segments collapse to the log ratio of their values, not the actual ratio. On the agentic-chatops Token Usage chart, a 1.0B-token Opus segment vs a 3.1M Qwen segment in the same day got flex-grow `90` vs `65` (1.4× visual) for a real 300× ratio. Opus = 99.6% of May 9 tokens but visually appeared as ~30% of the stack. The chart's day-total label correctly read "1.0B" while the stack composition silently lied.

**Why:** the operator's chart relies on a stacked-bar visual contract — "the size of this segment IS its share of the day." Log-scaling the segments breaks that contract while looking superficially-similar. The same pattern would mislead anywhere segments represent additive composition (cost breakdown, tool-call mix, traffic by source).

**How to apply:**
- For stacked-composition bars: `flex-grow = (segment.value / day.total) * 100` — proportional. Small segments may need a `min-height` clamp to stay visible.
- Log-scale is fine for **comparing days** (different x-axis bars), not for slicing **within** a bar.
- If most segments are tiny relative to a single dominant one, prefer a Pareto-style "top-3 + 'other' aggregated" rather than log-scaling everything to make them all visible.
- When clamping a small segment to a min visual size, surface that fact (e.g. striped fill or `min-height` clamp ≤ 1px) so the reader doesn't read clamped pixels as composition signal.

**Canonical fix (validated by Playwright 2026-05-11, `kyriakos:729f0bb`):** `var grow = Math.max(Math.round((num(m.tokens) / stackTotal) * 1000), 1);` where `stackTotal = segs.reduce(sum)`. ×1000 (not ×100) gives sub-percent resolution between segments. The `min` of 1 keeps zero-token segments out (combine with an upstream `filter(m => m.tokens > 0)` so hairlines don't leak — see `feedback_hugo_shortcode_safejs_injection.md` companion rules).

*Source: `memory/feedback_log10_flex_grow_misrepresents_proportions.md`*

### Match defense-in-depth layers to the actual threat model — don't reflex-apply patterns from a different deployment shape

**Rule:** before recommending a multi-layer defense pattern (constrained tools API, parameterised query wrappers, RBAC matrices), check whether the threat model actually has the attack surface those layers address. If a single guardrail (e.g., a read-only DB role + tenant container isolation) already eliminates a class of risk, layering more defenses on top is overengineering — it adds maintenance cost without adding security.

**Example (2026-04-27 agentic-agriops):** I proposed a hand-written FastAPI "safe SQL wrapper" exposing 5-10 parameterised functions to prevent the agronomy-advisor LLM from constructing destructive or cross-tenant queries. Operator pushed back with three concrete counter-arguments:
- (a) DROP TABLE class — solved by a read-only Postgres role; the LLM literally cannot run DDL/DML
- (b) Cross-row PII leakage — solved by the existing human-in-the-loop Matrix poll (operator approves bot output before it reaches the customer) + confidence markers + optional judge step. The constrained-tools approach has the SAME risk shape (wrong arg = wrong fetch).
- (c) Cross-tenant joins — physically impossible; each tenant has its own Postgres container on its own docker network. The LLM doesn't have credentials or network reach to other tenants.

All three were correct. The constrained-tools API only adds value in shapes where these don't already hold (multi-tenant single-DB, regulated PII compliance, or unattended/no-poll bots). Our shape: small operator, one-DB-per-tenant, human-in-loop on every output. The simpler **postgres MCP + read-only role + statement_timeout + audit log** is sufficient.

**How to apply:**
- When recommending defense-in-depth, list each layer and what specific risk it mitigates.
- For each risk, ask "does an existing isolation/role/gate already eliminate this?" If yes, don't add another layer for that risk.
- Surface the explicit threat model (multi-tenant? regulated? human-in-loop?) before reaching for patterns from FAANG-style compliance docs.
- Engage seriously when the operator pushes back with concrete counter-arguments — they know their deployment shape better than abstract security patterns.
- If the simpler approach genuinely has gaps the constrained one wouldn't, list them explicitly so the operator can decide. Don't just collapse to "use the constrained one."

*Source: `memory/feedback_match_defense_to_threat_model.md`*

### Max-sub 5-hour rolling rate-limit is account-level (not per-token)

Anthropic Claude Max plans (`rateLimitTier: default_claude_max_20x` etc.) have a **5-hour rolling rate-limit window** that is **shared across ALL OAuth tokens for the same Max account**. NOT per-token. NOT per-model. Running heavy work on one host depletes the pool for every other host signed into the same account.

The plan-level monthly quota (visible at `claude.ai/settings/usage`) is a separate metric — it shows monthly burn relative to plan-included quota and tells you nothing about the 5-hour window state.

**Why (corrected from initial mis-diagnosis 2026-04-28):**

During the 2026-04-28 OpenClaw → Sonnet cutover, OpenClaw's first real Tier 1 turn hit "You're out of extra usage" on every fallback rung. Initial diagnosis was "per-token burst window" — wrong. Verification by running 2 concurrent claude-CLI calls from the openclaw01 token at recovery time → both succeeded, ruling out per-token concurrency or per-token burst.

Real cause: the operator session driving the cutover work was running on `claude-opus-4-7[1m]` (Opus 4.7, 1M context). Each turn was a 1.9M cache-read + 406k cache-write + tiny in/out. Over 5h the session burned **2.3M tokens** for that one model. That depleted the Max account's 5-hour rolling pool. OpenClaw's first real 1040-char turn (with 17k-token workspace cache-write) couldn't fit in what was left. After ~5 min the rolling window advanced enough to free budget, recovery succeeded.

**How to apply:**

- When debugging OAuth-Sonnet billing rejections on a multi-host Max deployment, query `gateway.db.llm_usage` for the last 5 hours grouped by model:
  ```sql
  SELECT model, SUM(input_tokens+output_tokens+cache_read_tokens+cache_write_tokens)/1000.0 AS ktok
  FROM llm_usage WHERE recorded_at >= datetime('now','-5 hours') GROUP BY model;
  ```
  If any model's 5h total approaches the published Max-tier limits (Max 20x: roughly 100k-500k tokens per 5h depending on Anthropic's current calibration), that's your culprit.
- The plan-level monthly quota number (`claude.ai/settings/usage`) is NOT the right metric. Operator looking at "1% used Sonnet only" is reading a 30-day window; the 5-hour window can be at 100% even when the monthly is at 1%.
- Heavy 1M-context (Opus 4.7 1M, Sonnet 4.6 1M) sessions are the highest-burn. Each turn writes the full context as cache (100k+ tokens). Avoid running these in parallel with production OpenClaw / Tier 1 traffic on the same Max account.
- Mitigation in flight: wait ~5 min for the rolling window to advance, then retry. Permanent: spread heavy interactive work across separate Max accounts, OR retain a non-OAuth fallback (paid API key) for production-critical agents.
- Symptom: OpenClaw `model-fallback/decision: reason=billing detail="You're out of extra usage..."` on every chain rung. Matrix sees "Something went wrong while processing your request. Please try again, or use /new to start a fresh session." from the agent.
- Mis-diagnosis check: if a concurrent test from the SAME token succeeds (both calls return cleanly), the issue is NOT per-token — look for account-level pool depletion across ALL active OAuth tokens.

*Source: `memory/feedback_max_sub_per_token_burst_limit.md`*

### MeshSat Android UX feedback

User tested MeshSat Android v1.0.1 on real phone (2026-03-16). Key feedback:

1. **Maps show grey square** — WebView/Leaflet maps never load tiles, just grey. Must fix.
2. **SMS permissions too invasive** — App requests default SMS app role + RECEIVE_MMS/WAP_PUSH which triggers scary Android security warnings. User wants SMS to work with minimal permissions.
3. **Dark/light theme** — App should support both, default to dark. Maps should also respect theme.
4. **GUI simpler than expected** — Backend is complete but UI doesn't surface everything yet.

**Why:** First impression matters. Invasive permissions scare users away before they try the app.

**How to apply:** Fix maps first (visible bug). Reduce SMS permissions to minimum (SEND_SMS + RECEIVE_SMS only, drop default SMS app requirement). Add theme toggle. Don't request permissions the core flow doesn't need.

*Source: `memory/feedback_meshsat_android_ux.md`*

### NFS exports managed by Pacemaker have no /etc/exports

When the file-server cluster (nlcl01file01/nlcl01file02 on this stack) shows an `ocf:heartbeat:exportfs` resource in `crm status`, exports come from the resource-agent invocation, **not** from `/etc/exports` or `/etc/exports.d/*`. `cat /etc/exports` is empty.

**Never run `exportfs -r` (or `-rv`) on these hosts.** It re-syncs to the empty /etc/exports and unexports all currently exported paths. nlnc01/nlnc02 active mounts will continue working (clients cached the FH) but new mounts and grace recovery will fail until the export is re-added.

**Why:** Caught 2026-04-30 during the HAHA stale-fh incident. Tried `exportfs -rv` to refresh the kernel fh cache — got `exportfs: No file systems exported!`, and `exportfs -v` afterward was empty. Recovered with `pcs resource restart exportfs`, which the agent implements as `exportfs -u` then `exportfs -o <opts> <client>:<path>`. That re-export call is what actually rebuilds the nfsd fh cache for the fsid — and it was the action that fixed the underlying stale-fh issue, so the workflow ended up correct, but only by accident.

**How to apply:** Whenever you need to refresh an NFS export's fh cache or re-read its options on a Pacemaker-managed file server:
- `pcs resource restart exportfs` (or whatever the resource name is — check `crm_mon -1 -r`).
- This is also the right tool to clear server-side stale-fh emission for a specific export. Brief blip is invisible to clients holding live mounts.
- If you ever DO need to use raw `exportfs` for diagnostic purposes, never use `-r`. Use `exportfs -v` (read-only listing) or `exportfs -o <opts> <client>:<path>` (explicit add).

*Source: `memory/feedback_pacemaker_managed_exports_no_etc_exports.md`*

### NFSv4 stale-fh diagnostic ladder

When a Pacemaker `ocf:heartbeat:Filesystem` for an NFS mount fails with `mount.nfs4: Stale file handle`, walk this ladder before changing anything. Each step is read-only.

**Why:** The 2026-04-30 HAHA outage was diagnosed in ~25 minutes by walking this exact sequence. Skipping steps tempts you to restart NFSd on the server (disruptive to all clients) when the actual fault was kernel state on two specific clients.

**How to apply:** Run on every NFS-stale-fh incident. The first step that yields a unique difference between failing and working clients narrows the search; do not run remediations until the difference is confirmed.

1. **Identify failing vs working clients on the same export.** If others work, the export and server are fine — focus on the failing client(s).
2. **Test mount across NFSv4 minor versions** (`-o nfsvers=4.0`, `4.1`, `4.2`) and at the **parent path**. If all fail identically, it is not a path/version issue.
3. **Check server-side active client list and recovery DB.** `ls /proc/fs/nfsd/clients/` for live sessions; `python3 + sqlite3` against `/var/lib/nfs/nfsdcld/main.sqlite` (no `sqlite3` CLI on file servers — use Python). Failing clients absent from both = they never reach client-id confirmation.
4. **Check client-side cached state.** `/proc/fs/nfsfs/servers`, `/proc/fs/nfsfs/volumes`, `nfsstat -m`. Empty means the kernel module either has no state, or holds opaque client-identity state that doesn't show up in /proc.
5. **Verify ARP and routing match.** `ip neigh show <NFS-VIP>` — STALE is not broken (lazy refresh), but the MAC must match the active server's NIC. `ip route get <NFS-VIP>` — source must be the storage-VLAN IP.
6. **Look at server kernel logs** during a mount attempt. `dmesg -T | grep -i nfsd`. Silence is meaningful: it means the server isn't logging the stale-fh response; the rejection happens at the dispatcher before nfsd-internal logging.
7. **Look at client kernel history.** `dmesg -T | grep -E 'NFS|state recovery|stale'`. `state recovery failed for open file ... error = -13` (EACCES) is the smoking gun for "post-failover poisoned client identity." The kernel will not self-heal across umount in this state — only a reboot or `nfs.ko` reload (rarely possible if anything else is using NFS) will clear it.
8. **Check failure-handler scripts** referenced by the cluster's alert config. The handler may be wrong-IP / wrong-trigger and never fired (HAHA's `clear_arp_nfs.sh` had both faults).

**Remediation order, only after the ladder narrows the cause:**
- Cleanest: `pcs resource cleanup` on the failed resource — lets Pacemaker retry without any state change.
- If kernel-state is the cause and the client is idle: reboot **one** failing node (preserve quorum). Never both in parallel.
- Last resort, only if the server itself is at fault: brief `systemctl restart nfs-server` on the active NFS node (~90s grace period blips all clients).

*Source: `memory/feedback_nfsv4_stale_fh_diagnostic_ladder.md`*

### Narrate long-running work

During a multi-step task (PDF extraction + chunking + wiki compile + embed) I ran 4-5 background jobs and wait loops with no user-facing narration. The operator called it out as "very slow and telling me nothing."

**Why:** the operator is watching the stream; tool calls and background tasks aren't surfaced to them, so silence reads as "stuck" or "lost the plot." Even a crisp 1-line update between steps ("splitter done, triggering wiki rebuild") turns a 5-min silent block into a legible live log.

**How to apply:**
- After each tool call that completes non-trivial work (file write, script run, long query), output one short sentence on what happened and what's next.
- Before a long/blocking/polling operation, say so ("embed step will take ~2-3 min").
- If a step fails or gets slower than expected (e.g. timeout), say so immediately — don't silently retry with a different method.
- Don't batch a 5-step plan into 5 silent tool calls followed by a summary. Stream it.
- This is separate from the "no trailing summaries" rule — mid-flight narration is wanted, end-of-turn recap is not.

*Source: `memory/feedback_narrate_long_running.md`*

### Never call subnets by their third octet as a "VLAN" [P0]

**P0 rule.** Never refer to a subnet as a "VLAN" by its third IP octet. The third octet is **not** the VLAN tag; calling `10.0.181.X/24` "VLAN 181" is misleading and wrong.

**Mapping (NL site):**

| Subnet | VLAN tag | VLAN name |
|---|---|---|
| 10.0.181.X/24 | **VLAN 10** | inside_mgmt |
| 10.0.X.X/28 | VLAN 12 | CCTV |
| 10.0.X.X/27 | (storage) | storage |

(Other tags exist; consult CLAUDE.md or NetBox for the full table.)

**Correct phrasings:**
- "the inside_mgmt VLAN" ✓
- "VLAN 10 (inside_mgmt)" ✓
- "the 10.0.181.X/24 subnet" ✓
- "the management LAN" ✓ (when context unambiguous)

**Wrong phrasings (do not use):**
- "VLAN 181" ✗ — 181 is the subnet third octet, not a VLAN tag
- "VLAN 88" ✗ — 88 is a subnet third octet
- "VLAN 183" ✗ — 183 is a subnet third octet (the actual VLAN is 12)

**Why:** The VLAN tag is what's configured on switches and in 802.1Q frames. The third octet is just an IP address feature. Conflating them propagates wrong assumptions into config diffs, ACLs, troubleshooting docs. Operator reinforced 2026-04-30 after I called the inside_mgmt VLAN "VLAN 181" in a status report.

**How to apply:** Every time I'm about to write "VLAN <N>" check whether N is the actual 802.1Q tag (from CLAUDE.md or NetBox) or just the subnet third octet. If it's the third octet, use the subnet form (`192.168.X.0/24`) or the VLAN name (`inside_mgmt`) instead.

*Source: `memory/feedback_vlan_naming_third_octet_misleading.md`*

### Never combine `interruptible: true` with `resource_group` on the same GitLab CI job

Do not mix `interruptible: true` and `resource_group` on the same CI job. Pick one based on the actual need:
- **`resource_group` alone** if you need serialization (only one instance running at a time). Every queued pipeline runs to completion in order.
- **`interruptible: true` alone** if you need supersession (newer push cancels older). Older job dies when newer one arrives.
- **NEVER both.** They deadlock.

**Why:** Reproduced 2026-05-01 16:13 in claude-gateway. Configured both on `sync_to_github`. Pushed 4 commits in 8 seconds. `workflow.auto_cancel.on_new_commit: interruptible` triggered cancellation of pipeline 25559's still-running job. GitLab transitioned the job to `canceling` state. **`canceling` holds the resource_group lock** until the runner fully tears down its container. Runner was mid-clone with a slow network operation; teardown stalled. Lock stayed held for 12+ min. Pipeline 25560 sat in `waiting_for_resource` indefinitely. Job-level cancel API, pipeline-level cancel API, and `/jobs/<id>/erase` all returned `canceling` without unblocking.

The only way out (without admin Rails console) is `DELETE /api/v4/projects/X/pipelines/<stuck-id>` (admin scope) — works because it nukes the pipeline+job atomically, releasing the lock. Or rename the resource_group to bypass the orphan; old lock will eventually be reaped by `build_timeout` (1h default).

**How to apply:** Before adding `interruptible: true` to any job, check if it has `resource_group` set (or vice versa). If yes, document why you're picking one and not the other in a YAML comment so the next operator doesn't re-add the missing flag thinking it's an oversight.

For sync_to_github specifically: chose `resource_group` alone. Trade-off accepted: a burst of N pushes = N sequential syncs (~3 min each), no auto-cancel of intermediate pushes. Acceptable because real push cadence is low and each sync force-pushes the entire tree (later sync makes earlier sync's output redundant anyway).

*Source: `memory/feedback_resource_group_interruptible_deadlock.md`*

### Never embed Python in a heredoc inside `bash -c '...'`

Never embed a multi-line Python script in a heredoc that lives inside
`bash -c '...'` (e.g. `setsid bash -c '... python3 - <<PYEOF ... PYEOF ...'`).

**Why:** Python idioms like `session_end_payload['outcome']` contain literal
`'foo'` substrings. The OUTER `bash -c '...'` argument is single-quoted, and
every `'` inside the heredoc body is interpreted by THAT outer parser as the
end of the bash-c argument — bash then sees the bare token (`outcome`),
and with `set -u` aborts the block. `<<'PYEOF'`, `<<\PYEOF`, `<<"PYEOF"` do
NOT help because the breakage happens before the heredoc is parsed by the
inner shell.

**Symptom:** silent `NameError: name 'X' is not defined` from Python at
runtime, even though the heredoc body looks syntactically clean and runs
fine when extracted to a file. (2026-04-28: AGRI runner-claude-async.sh's
auto-resolve post-processing path crashed with `name 'outcome' is not
defined`, ate Matrix m.notice delivery, operator never saw answers in
agri-webapp-dev for ~30 minutes.)

**How to apply:**
- Always put non-trivial Python in its own `.py` file under the project's
  scripts dir.
- Have bash invoke `python3 /full/path/to/script.py "$VAR" "$OTHER"` and
  pass any inputs via argv or env, not heredoc.
- For one-liners that genuinely fit in a heredoc, only do it OUTSIDE
  `bash -c '...'` (i.e. at the top level of a script), where there's no
  outer single-quoting to collide with.
- If the surrounding bash is `bash -c "..."` (double-quoted), the same trap
  doesn't apply for `'foo'`, but `$VAR` and backticks expand — different
  hazard. Still prefer extracted .py files.

*Source: `memory/feedback_no_python_heredocs_in_bash_c.md`*

### Never install tools on the Proxmox hosts — use the site oversight agent

**Rule.** Never `apt install`, `pip install`, or otherwise add tooling to the Proxmox hosts (nl-pve01/02/03, gr-pve01/02). They run workloads, not automation.

**Why.** PVE hosts are already complex (Debian + PVE subscription repos + kernel + ZFS + ceph + cluster services). Adding random python/automation tooling accretes surface area, complicates upgrades, and risks PVE-subscription signature drift. The site oversight agents (`nl-claude01` at 10.0.181.X, `grclaude01` at 10.0.X.X) exist exactly for that purpose — they have netmiko, pexpect, paramiko, ansible, kubectl, and all automation libraries pre-installed and maintained.

**How to apply.**

When you need to reach a Cisco ASA or any site-local device from Claude Code:

- For NL ASAs / NL devices: run python/netmiko/pexpect directly from `nl-claude01` (the host Claude Code is running on).
- For GR ASA / GR devices: SSH to `grclaude01` first, then run the automation from there. Pattern:

```bash
ssh -i ~/.ssh/one_key app-user@grclaude01 "bash -s" <<'EOF'
python3 <<'PYEOF'
import pexpect
c = pexpect.spawn("ssh -o ... operator@10.0.X.X", ...)
# ...
PYEOF
EOF
```

Use the PVE host ONLY for legitimate PVE-level queries: `pvecm status`, `qm list`, `pct config`, etc. Never as a Python/automation host.

**Incident that produced this memory (2026-04-22).** During a live failover test, I needed to reach the GR ASA via the GR stepstone (normally `gr-pve01`). The stepstone didn't have `python3-pexpect`. I ran `apt-get install -y python3-pexpect` on `gr-pve01` — the wrong move. The operator corrected: use grclaude01 for automation, keep gr-pve01 clean. The installed package was left in place (not worth risking a removal on a running PVE host mid-failover) but no further tooling additions.

*Source: `memory/feedback_never_install_tools_on_proxmox.md`*

### Never reuse an existing channel-group number when adding a new LACP bundle

**P0 rule.** Before creating a new LACP bundle on a Cisco switch, run `show etherchannel summary` and pick an unused `channel-group` number. Never assume Po1 (or any specific number) is free.

**Why:** On 2026-04-21 I planned to bundle nl-sw01 Gi1/0/34 + Gi1/0/32 into a new Po1 for the nlrtr01 uplink. nl-sw01's Po1 was **already the production 4-link LACP to nl-fw01 (Gi1/0/21/23/25/27)** — the entire trunk that carries every internal VLAN to the firewall. My `interface Port-channel1 / switchport trunk allowed vlan 2 / switchport trunk native vlan 10` commands rewrote the firewall's trunk config. `channel-group 1 mode active` on Gi1/0/34 added it as a 5th member of the firewall bundle. This caused:

- ~several hours of management-network L2 outage (nl-fw01 untagged VLAN 10 ingress dropped because nl-fw01 Po1.10 expects tagged)
- Asymmetric L2 making triage non-obvious (nl-fw01 → LAN worked; LAN → nl-fw01 silent drop)
- nl-fw01 power cycle during triage
- Partial recovery that missed `switchport trunk native vlan 10` until discovered via live `show interfaces Po1 trunk`
- NAT rules for `outside_budget` never created (follow-up item)

**How to apply:**

1. **Before any `interface Port-channel<N>` or `channel-group <N> mode <mode>` command, run `show etherchannel summary` on the target switch.** The output lists Po numbers in use.
2. **Pick a number that does NOT appear.** On nl-sw01 today Po1 was the firewall bundle; Po3 and Po7 also exist. Safe new numbers start from Po4 onward — verify.
3. **When migrating an unused port into a new bundle, prefer `default interface` to strip old config**, then `channel-group <NEW_N> mode active` — never reuse the neighboring device's bundle number.
4. **After any channel-group config push, diff running-config against pre-change snapshot** (`show etherchannel summary`, `show interfaces trunk`). Don't rely on spot checks.
5. **Asymmetric L2 = trunk/native-VLAN mismatch.** It's one of the few failure modes that populates ARP on only one side. When in doubt, check `show interfaces <port-channel> trunk` for unexpected `Native vlan` value.

Related lesson on packet-tracer: it simulates policy, not the wire. A clean `Action: allow` doesn't prove the frame arrived. Cross-check with `show arp <interface>` and physical port counters.

*Source: `memory/feedback_never_reuse_channel_group_number.md`*

### Never use emojis anywhere

NEVER use emojis. This is a hard, repeatedly-stated operator rule.

**Why:** Operator stated multiple times («ommit all the emojis; ALWAYS AVOID EMOJIS», then later «and NEVER user emojis»). Treats emojis as visual noise / unprofessional / inconsistent across renderers. The system prompt also already says "Only use emojis if the user explicitly requests it" — and they have explicitly forbidden them.

**How to apply:**
- **Text output to user**: never. Not even one. Not even in summaries. Not even tables. Not for status indicators. Use plain text or words.
- **Code / templates / UI strings**: never. Use Bootstrap Icons (`<i class="bi bi-paperclip">`), Material icons (`:material-paperclip:` in MkDocs), or plain text labels. Same for placeholders.
- **Plan files / wireframes / ASCII art**: never. Use bracketed text instead: `[paperclip]` not paperclip-emoji, `[arrow up]` not arrow-up-emoji. Or use the literal Bootstrap class name in brackets: `[bi-paperclip]`.
- **Commit messages**: never. No conventional-commit emoji prefixes either.
- **Telegram/Slack/Matrix posts**: never.
- **In any agent SYSTEM_PROMPT we author**: include an explicit «No emojis ever» line.

**Substitutes (when status/severity needs to be visually distinct):**
- Coloured Bootstrap text classes: `text-danger`, `text-warning`, `text-success`
- Bootstrap badges: `<span class="badge bg-danger">Κρίσιμο</span>`
- Bootstrap Icons (a11y-friendly): `bi-x-circle text-danger`, `bi-check-circle text-success`, `bi-exclamation-triangle text-warning`
- ASCII bracket labels: `[OK]`, `[FAIL]`, `[WARN]`, `[INFO]`
- Plain Greek words: «Επιτυχία», «Σφάλμα», «Προσοχή»

**Self-check before sending any message:** scan output for any U+1F300–U+1F9FF, U+2600–U+27BF, dingbats, mathematical alphanumerics-as-icons, etc. If found, rewrite. Includes "innocent" ones like check-marks, arrows, hearts, fire, sparkles, etc.

**Exception:** none. The operator said NEVER. There is no «but for this special case…».

*Source: `memory/feedback_never_use_emojis.md`*

### No ops/SRE jargon in user-facing text

**Rule.** Don't use ops/SRE jargon in messages to the operator without defining it inline. Plain words are always acceptable; shortcuts like "P0", "SLO", "MTTR", "RCA", "MTBF", "TOIL", "pager-ready", "shift-left" are NOT.

**Why:** On 2026-04-21 the operator asked "what the fuck is P0?" after I'd used the term three times in one reply. The shorthand conveyed nothing and created friction. The operator manages the infrastructure alone; technical shortcuts that assume Google-SRE vocabulary don't add signal, they just obscure.

**How to apply:**

- In conversation and in answers, say **"never-violate rule"** instead of "P0", **"highest priority"** instead of "P0/priority zero", **"time to recover"** instead of "MTTR", **"cause-of-failure writeup"** instead of "RCA/post-mortem" (unless the operator used the term first — mirror their vocabulary in that case).
- Inside memory files, docs, commit messages, or code where precision matters and the reader self-selected (e.g. I'm reading my own memory), compact jargon is fine.
- If the operator uses a term first, mirror it — don't translate back to plain words.
- When in doubt: plain words. Plain words never cost anything; jargon costs comprehension.

*Source: `memory/feedback_no_jargon.md`*

### No public IPs for internal BGP services

NEVER use public IP addresses to reach services that should be reachable within the iBGP mesh. If a path doesn't work, fix the BGP/routing, don't bypass it with public addresses.

**Why:** The entire network is iBGP-meshed with VTI tunnels. Routing internal monitoring traffic over public internet defeats the purpose of the VPN mesh and introduces unnecessary external dependencies.

**How to apply:** When internal overlay IPs (10.255.x.x) are unreachable from a segment, the fix is always to extend BGP peering to that segment (e.g., Cilium BGP for K8s), never to fall back to public IPs or create out-of-band workarounds.

*Source: `memory/feedback_no_public_ips_internal_bgp.md`*

### OCF docker start/stop timeout must match real container boot time

**Rule:** When adding an `ocf:heartbeat:docker` resource to a Pacemaker group, set start/stop timeouts to **at least 2× the container's typical first-boot time, with a 60s+ floor for any non-trivial app**.

**Why this matters:**
On 2026-04-30, chaos test C9 (`docker kill nodered`) escalated from a sidecar-restart event to a **node fence + reboot of nlcl01iot01**. Root cause: `p_docker_nodered` had `start timeout=90s`. Node-RED's first-after-kill boot took >90 s (loading flows, plugins, etc.). Pacemaker's start operation timed out → counted as start failure → migration-threshold=2 reached after a second retry → group can't migrate cleanly → escalation to fence the failed node. Kept the cluster correct but rebooted nlcl01iot01 unnecessarily for ~2 min.

Fixed live with:
```
pcs resource update p_docker_nodered     op start interval=0s timeout=180s op stop interval=0s timeout=180s
pcs resource update p_docker_mosquitto   op start interval=0s timeout=120s op stop interval=0s timeout=120s
pcs resource update p_docker_zigbee2mqtt op start interval=0s timeout=120s op stop interval=0s timeout=120s
pcs resource update p_docker_esphome     op start interval=0s timeout=120s op stop interval=0s timeout=120s
```

p_docker_home-assistant was already at 120s (set higher because HA is slow-booting). Remaining sidecars were left at the OCF default 90s and that was the bug.

**How to apply:**
- For new Pacemaker docker resources: don't accept the OCF default. Set `op start timeout` to ≥ 120 s minimum (180 s for Node-RED-style apps that load lots of state from disk on first boot).
- After a chaos kill that triggers Pacemaker recovery, watch the journal for `Resource agent did not complete within Xs` errors — that's the marker for an undersized timeout.
- Stop timeout should mirror start timeout — `docker stop --time=N` waits for graceful SIGTERM exit before SIGKILL, and slow apps need the same headroom.
- Trade-off: longer timeouts mean slower recovery on actual failure (wait the full timeout before declaring failed). Pick the shortest value that survives p99 boot time.

*Source: `memory/feedback_ocf_docker_start_timeout_for_slow_boot.md`*

### Ollama "model failed to load" — check host RAM + OOM-killer FIRST, not GPU VRAM

When Ollama (or n8n's `@n8n/n8n-nodes-langchain.lmOllama` / `chainLlm` node) returns:

> `model failed to load, this may be due to resource limitations or an internal error, check ollama server logs for details`

the diagnostic instinct is to check GPU VRAM with `nvidia-smi` first. **Don't.** In the majority of observed cases on the NL fleet, the cause is **host-side RAM exhaustion + kernel OOM-killer**, not GPU VRAM. Reason: cold-loading a 7 GB Q4 quantised model briefly holds ~9–10 GB of host anon RSS during file-map + KV cache + working buffers, before layers get pinned to the GPU. If the host is already memory-pressed, the kernel kills the loader process before it gets to the GPU-pinning phase, and Ollama returns the generic "model failed to load" — which says nothing about *who* killed *what*.

### Diagnostic ladder

1. **`journalctl --since '1 hour ago' | grep 'Out of memory.*ollama'`** — the smoking gun. If you see `Out of memory: Killed process N (ollama) total-vm:~17GB anon-rss:~9GB`, it is 100% host-RAM, not GPU.
2. **`free -h`** + **`cat /proc/swaps`** + **`uptime`** — confirm host pressure (low available RAM, swap near full, high load avg).
3. **Reproduce via curl**: `curl http://<ollama>:11434/api/generate -d '{"model":"<name>","prompt":"ping","stream":false}'`. If this also fails with the same message, the issue is server-side and not n8n.
4. **Ollama listing** (`/api/ps` for resident, `/api/tags` for cached on-disk) — confirms the model is *available* (so it's not a missing-model issue), just can't load.
5. **Only AFTER** the above show host RAM is fine, check `nvidia-smi` for VRAM/process attribution.

### Why this is non-obvious

- The error message points the operator at "ollama server logs" but if Ollama isn't running under a known systemd unit (e.g., on `nl-gpu01` it's launched as a bare `/bin/ollama serve` under root), `journalctl -u ollama` returns nothing — you must `journalctl --since … | grep` the kernel ring instead.
- Ollama's own logs go to a pipe FD (`readlink /proc/$pid/fd/1` shows `pipe:[NNNNNNN]`), so they're effectively dropped unless someone captured them.
- GPU VRAM may show plenty of free space (e.g., 7+ GB) and still be unable to load — because the host RAM exhaustion happens BEFORE GPU allocation.
- A successful prior run can complete in 1–2 s (model warm in resident worker), then the worker gets OOM-killed during an idle period, and the next cold-load fails — making failures look intermittent and confusing.

### Why

Observed 2026-05-04 on nl-gpu01: workflow `RSS2Postiz with Images and Hashtags v7` (`dCCyqbu2lrWTxAxh`) failing with "model failed to load" for `gemma3:12b`. GPU VRAM had 7.6 GB free (would have fit). Host had 8.6 GB available with swap 99% full and load avg 65; **25 `Out of memory: Killed process … (ollama)` events in the prior hour**. Workflow had 5 successful runs at 21:30–22:10 UTC (warm worker, 1.6–2.2 s each), then started erroring at 22:20 once the warm worker was OOM-killed and every cold-load failed. Linked open issue: YT-733 ("gemma3:12b num_gpu 49 Modelfile pinning") — pinning the Modelfile is a partial mitigation but doesn't solve host-RAM exhaustion.

### How to apply

When triaging "Ollama failed" / "n8n LLM Chain failed" / "Basic LLM Chain → Ollama Model timeout":
- Step 1 is `journalctl --since '1 hour ago' | grep -c 'Out of memory'` on the Ollama host. If non-zero, host RAM is the cause and `nvidia-smi` is a distraction.
- Step 2 is decide between freeing host RAM (kill/restart heavy non-critical services), switching the workflow to a smaller model (e.g., `qwen2.5:7b` — documented fallback in CLAUDE.md), or growing host RAM/swap.

*Source: `memory/feedback_ollama_model_failed_to_load_check_host_ram_first.md`*

### Ollama runs in Docker on nl-gpu01

Ollama on `nl-gpu01` runs as a Docker container with data volume at `/srv/ollama`. There is no native `ollama` binary on the host.

**Why:** Docker deployment for easier lifecycle management + GPU passthrough.

**How to apply:**
- Do NOT run `ollama pull <model>` directly over SSH — it will fail with `ollama: command not found`.
- Find the container: `ssh ... root@nl-gpu01 'docker ps --format "{{.Names}}" | grep -i ollama'`
- Use docker exec: `ssh ... root@nl-gpu01 'docker exec <container_name> ollama pull <model>'`
- Same pattern for `ollama list`, `ollama rm`, etc.
- The HTTP API (`http://nl-gpu01:11434`) is unaffected — it's published from the container.
- Models are persisted in the `/srv/ollama` volume mount.

*Source: `memory/feedback_ollama_docker_gpu01.md`*

### OpenAI model instruction pattern for OpenClaw (HISTORICAL — Tier 1 migrated to Sonnet 2026-04-28)

**STATUS (2026-04-28):** No longer in production effect. Tier 1 OpenClaw runs `claude-cli/claude-sonnet-4-6` via Max-sub OAuth. Sonnet handles auto-trigger patterns + multi-step sequential exec calls reliably. The pattern below is preserved as reference for any future OpenAI re-introduction (e.g. as a billing-fallback). Safe-by-default: don't remove SOUL.md's literal `exec` tool naming — it's still clearer for Sonnet and a no-op cost.

---

OpenAI models (OpenClaw — was GPT-5.1, migrated from GPT-4o on 2026-04-07, then to Sonnet on 2026-04-28) don't reliably follow auto-trigger patterns like "when you see X, do Y via exec" in the system prompt (SOUL.md). Multi-step sequential exec calls are also unreliable. (GPT-5.1 was supposed to have "stricter system-message enforcement" but pre-migration testing did not see strong improvement vs GPT-4o.)

**What works:**
- Single wrapper scripts that do everything in one exec call
- n8n posting explicit instruction messages: `@openclaw use the exec tool to run: ./script args`
- Matrix mention pills in `formatted_body` (required when `requireMention: true`)
- `requireMention: true` for rooms where automated messages should be ignored

**What doesn't work:**
- Auto-trigger patterns in SOUL.md (e.g., "when you see [LibreNMS] ALERT, run these 5 steps")
- Multi-step exec sequences (GPT-4o runs 1-2 then stops or summarizes)
- Relying on `historyLimit` context — established suggestion patterns in history cause GPT-4o to continue suggesting instead of executing
- `m.notice` alone to prevent OpenClaw from responding — OpenClaw processes ALL message types

**Pattern (2026-03-13):**
1. Alert posted as `m.notice` (informational, ignored by OpenClaw)
2. Triage instruction posted as `m.text` with @openclaw mention pill (triggers exec)
3. Room has `requireMention: true` so only mention-containing messages are processed

*Source: `memory/feedback_gpt4o_instruction_pattern.md`*

### PPPoE Discovery failure is never an MTU/MSS issue

If `show interface Port-channel1.6` shows `IP address unassigned` and `outside_freedom` never receives a PADO after `shutdown / no shutdown` on the PPPoE sub-interface, **do not** propose MTU changes or MSS clamping (e.g. Freedom's `1500 - 4 - 8 - 40 = 1448` recipe from `helpdesk.freedom.nl/algemene-instellingen-eigen-modem`). Those recipes are for a working session whose TCP throughput is broken by large-packet fragmentation. They cannot fix Discovery.

**Why:** PPPoE Discovery (PADI → PADO → PADR → PADS) runs as raw L2 Ethernet frames (~30–80 bytes) with no IP layer. MSS clamping mutates TCP-SYN MSS option values inside IP packets — those don't exist yet at Discovery time. MTU only matters once LCP has negotiated MRU and a PPP frame can carry user data.

**How to apply:** When PPPoE won't come up, the diagnostic tree is:
1. L1/L2 — ONT port (`show interface Gi1/0/36` on `nl-sw01`) line-protocol up + power inline on + ONT registered.
2. L2 PPPoE — fire fresh PADI by `shutdown` / `no shutdown` on the PPPoE-client sub-interface (`Port-channel1.6` on nl-fw01); look for `%PPP-*` and `%PPPoE-*` in `show logging`. If silence, it is BRAS-side.
3. **Verify the BRAS itself is alive from a different WAN** (`ping outside_budget <BRAS_IP>`). If BRAS responds from the failover but our PADI gets no PADO, the issue is session-state for our circuit, not BRAS reachability. Tell the ISP "clear stale session for our line", not "BRAS down".
4. Only after a session is up and large packets / TCP throughput is broken do MTU/MSS recipes apply.

Caught 2026-05-11 auditing the 2026-05-08 Freedom XGS-PON outage email — operator asked whether Freedom's `MSS 1448` helpdesk note was relevant. It wasn't: PADI was getting no PADO, and from the Budget WAN the BRAS itself (`198.51.100.X`) pinged 4/4 at 10 ms.

*Source: `memory/feedback_pppoe_discovery_failure_not_mss_clamping.md`*

### Re-read CLAUDE.md before concluding when finding contradicts it

When a live-system probe contradicts a CLAUDE.md claim about architecture, the answer is almost always "I'm looking at the wrong device" — not "the doc is outdated."

**Why:** Reinforced 2026-05-05 during the notrf01dmz01/02 onboarding. CLAUDE.md said "Budget path (formerly xs4all; renamed 2026-04-21) terminates on dedicated edge router `nlrtr01` (ISR 4321)" — explicit, in plain English, with the device name and model. I queried `nl-fw01` for xs4all VTIs, found none, concluded "the existing fleet has zero xs4all VTIs for ANY peer; CLAUDE.md is outdated." Then I deferred work that should have been routine. The operator's correction was angry and immediate: "wtf is that? use netmiko and ssh to nlrtr01 and audit the running config." Of course there were xs4all VTIs — they were on the dedicated edge router I hadn't looked at, exactly where CLAUDE.md said they were.

**How to apply:**
- When a probe yields "X doesn't exist" or "Y is missing," and the user's CLAUDE.md says it should, re-read that section of CLAUDE.md word-for-word before stating the conclusion. Do not paraphrase.
- Pay attention to device names mentioned in CLAUDE.md prose — they're load-bearing. "Terminates on dedicated edge router `nlrtr01`" means rtr01 is a SEPARATE device from the ASA, with its own role, its own SSH endpoint, its own running config.
- If the prose mentions a transit subnet (`10.0.X.X/30`), interfaces (`outside_budget`), or a model number (ISR 4321), use those as breadcrumbs — they prove the device exists and tell you where to look.
- When in doubt about whether the doc is outdated, ASK the operator with a specific question ("CLAUDE.md says rtr01 terminates xs4all — should I verify there before concluding xs4all isn't wired?") instead of stating a sweeping conclusion that might be wrong.
- Do NOT preemptively log "deferred" tasks for things that turn out to be already-built and just on a device I didn't check.

*Source: `memory/feedback_reread_claudemd_when_finding_contradicts.md`*

### Right-size Bash tool timeouts to expected work, not worst-case

**Rule:** the `timeout` parameter on Bash tool calls should reflect the realistic upper bound for the operation, not a defensive worst-case multiplier. Each operation class gets its own budget:

| Operation class | Realistic budget |
|---|---|
| Read-only inventory / status check | 30s |
| `docker compose up -d` + healthcheck wait | 60-90s |
| HAProxy edit + validate + reload + verify | 30-60s |
| Image pull (first time, ~2 GB) | 120-180s |
| App migration / first-boot init (Chatwoot, YouTrack, etc.) | 300-600s — and run in BACKGROUND with a separate poll loop, not as a single SSH foreground call |

**Why:** an interactive operator watching a 5-minute SSH command sit on the screen has reason to interrupt — they reasonably assume something is wrong. Padded timeouts hide real hangs (the SSH session that should take 20s but actually hangs at 4 min looks the same as one set to 5 min "just in case"). Tight timeouts surface real failures fast.

**How to apply:**
- Default: pick the realistic 95th-percentile and add ~50% headroom. Don't multiply by 5x.
- For long migrations / asset compilation steps: do NOT block the SSH foreground for 5+ min. Kick off as `nohup ... &` background, return immediately, then poll for completion in a separate, short-budget SSH loop.
- The `until <check>; do sleep N; done` polling pattern is the right tool when waiting for an out-of-band process (migration write completion, container health, DNS propagation).
- For routine compose-up + HAProxy wire scripts: 60-90s. If they don't finish, the assumption should be "something's wrong" not "be patient."

*Source: `memory/feedback_right_size_timeouts.md`*

### SQLite writers on gateway.db need busy_timeout

gateway.db at `~/gitlab/products/cubeos/claude-context/gateway.db` has many concurrent writers: agentic runner, session-end, poller, wiki-compile (via kb-semantic-search `wiki-embed` + `index-memories`), metric scrapers (`write-*-metrics.sh` *every 5min*), and every operator-triggered tool that logs a row. A Python `sqlite3.connect(...)` with no `busy_timeout` fails instantly (`OperationalError: database is locked`) the moment any other writer holds the WAL write-lock for more than a few ms.

**Why:** this bit us on 2026-04-23 — teacher-agent's `cmd_chat` ran Ollama synthesis (109s), then tried to UPDATE the audit row and crashed on lock contention, so the user-visible Matrix reply was never posted even though the answer had been computed. The broken pattern was: expensive LLM call → final DB write → user-facing effect. The crash happened between step 2 and step 3, so step 3 was silently skipped. Commit `feb2bae` fixed it by (a) adding `timeout=30 + PRAGMA busy_timeout=30000` in `_db()` and (b) reordering so Matrix post precedes the final UPDATE.

**How to apply:**
- **Always** open gateway.db connections with `sqlite3.connect(path, timeout=30.0)` and immediately run `PRAGMA busy_timeout=30000` (plus `journal_mode=WAL` if not already set). 30s covers every realistic contention window this system sees; shorter values (default 5s or the 200ms we saw in an earlier n8n sqlite mutex incident) are too aggressive.
- **Order side effects** so that the user-visible effect (Matrix post, YT comment, webhook response) happens BEFORE the final DB write. If the write still fails after `busy_timeout`, catch `sqlite3.OperationalError` and continue — audit rows are recoverable via `close-stale-*.py` crons or manual SQL; a lost user reply is not.
- **When reviewing new writers**, grep for `sqlite3.connect(` in the new code and verify every hit has a `timeout=` kwarg. Shell-side `sqlite3 gateway.db "..."` invocations get the CLI's default 0-timeout behaviour and will fail under contention too — use `sqlite3 -cmd "PRAGMA busy_timeout=30000"` when writing from bash cron scripts that run during peak hours.
- **Reference pattern already in the codebase**: `scripts/lib/handoff_depth.py` uses `isolation_level=None` + `PRAGMA busy_timeout=10000` (documented in CLAUDE.md). `scripts/lib/prompt_patch_trial.py` and the adoption-batch libs (IFRNLLEI01PRD-635..643) follow the same shape. New writers should match.

*Source: `memory/feedback_sqlite_busy_timeout.md`*

### Security scan report — known-noise filter for our topology

When auditing weekly-scan reports, treat the following as **known noise** and do not propose action unless the underlying topology has changed.

**Why:** Re-deriving each of these from first principles burns 15-30 min per scan review. The signal/noise ratio of these reports is low; pre-filtering recovers it.

**How to apply:** Before opening the scan report, mentally subtract these. Then look at what's left.

### nmap NSE — always noise on our stack

| Finding | Why it's noise |
|---|---|
| `CVE-2007-6750` Slowloris "LIKELY VULNERABLE" | nmap heuristic that any nginx/OpenResty trips. Our edge is nginx/OpenResty everywhere; `client_header_timeout` + `worker_connections` mitigate the actual attack. |
| `CVE-2011-3192` Apache Range DoS "VULNERABLE" | Wrong product. We run nginx, not Apache httpd. nmap's check is banner-loose and false-positives on any server that handles `Range:` gracefully. |
| `http-csrf` / `http-stored-xss` / `http-dombased-xss` "Couldn't find" | These are clean signals (no finding); they show in the report only because nmap NSE prints status, not because anything is wrong. |

### Banner mis-identifications

- `203.0.113.X:2022` reports as `FortiSSH (protocol 2.0)`. **It is not Fortinet.** It's NAT'd to `nlsftpgo01`; nmap is confusing SFTPGo's Go-based SSH banner. Verify SFTPGo version when in doubt.

### testssl baseline-acceptable findings

The following 3-finding cluster is the OpenVPN-AS default self-signed cert at `nloas01` (203.0.113.X NAT). It's behind `WHITELIST_OAS`. Cosmetic only.
- `Serial NOT ok: length should be >= 64 bits entropy (is: 4 bytes)`
- `Chain of trust NOT ok (self signed CA in chain)`
- `Neither CRL nor OCSP URI provided`

If you want it gone from the baseline: install LE cert on `nloas01`. Otherwise: accept.

### testssl wording you must read carefully

- `BREACH (CVE-2013-3587) potentially NOT ok, "gzip" HTTP compression detected. - only supplied "/" tested` — this means *"compression detected; the actual attack requires CSRF-token-in-body reflection that I (testssl) cannot verify with one GET."* Do **not** treat this as "verified vulnerable." On our topology (Hugo static + allowlisted admin endpoints) it's not exploitable. Walk the BREACH preconditions per host before recommending action.

### What to DO check on every scan report

- New port appearing on a previously-filtered IP → real signal.
- Open port on a host that should be allowlist-only → check ACL (config drift).
- Nuclei finding count of 0: plausible for our patched surface, **but** confirm the scanner's cron PATH includes `/usr/local/bin` (`export PATH` in `weekly-scan.sh`) — silent-fail precedent on `nlsec01` 2026-05-04 (memory `scanner_nuclei_silently_broken_20260504`). The fix should be mirrored on `grsec01`; verify if you can reach the host.
- Cert expiry creeping inside 14 days on any LE-fronted host.

*Source: `memory/feedback_security_scan_report_noise_filter.md`*

### Single Operator Context

Dominicus is a solo operator managing enterprise-grade infrastructure (310 objects: 113 physical devices + 197 VMs, 421 IPs, 39 VLANs, 653 interfaces across 6 sites (NL, GR x2, CH, NO + Slurp'it), 3 PVE clusters, 12 K8s nodes, full HA Nextcloud, Cisco/ASA network stack, BGP AS64512). No ops team.

**Why:** Every friction point in the chatops pipeline directly costs his time. There is no one else to pick up the slack. When something breaks at 3 AM, the system needs to handle it autonomously up to the approval gate.

**How to apply:**
- Always optimize for minimum human interaction — one tap, not typing
- Auto-close related issues, auto-acknowledge alerts, auto-link children
- Never ask the human for information the system can look up itself (issue IDs, hostnames, IPs)
- Make progress visible (timestamps, progress updates) so he can glance and know if it's working
- Every new feature should reduce his workload, not add configuration burden
- When documenting architecture, be thorough — the docs ARE the team's knowledge base since there is no team

*Source: `memory/feedback_single_operator.md`*

### Status-page detail goes in the graph, not the banner text

On the portfolio `/status/` page (and similar status surfaces), do **not** put failure detail into the banner text. The banner stays one concise line. If something specific is broken, make the specific graph element show it — e.g. paint the one failing D3 VPN link red, give the one failing DMZ container a red fill, etc.

**Why:** 2026-04-19 — attempted to name a failure in the banner text (`Degraded — ... | BGP 31/35 + 4 expected standby + 4 unexpected idle | ClusterMesh ready — CH↔GR direct tunnel down`). User hard-rejected: the banner became a paragraph, unreadable at a glance, and the graph below (the actual visualization) still didn't depict the specific problem. The correct fix was to mark the one broken tunnel with `status=impaired` + `bgp_down=true` in the API, then colour the one D3 line red in `mesh-graph.js`. Banner reverted to its original one-liner.

**How to apply:**
- When a status API reveals a real failure, the *detail* (which peer, which tunnel, which container) goes into the structured API response for the visualization to consume. The compound banner gets at most one extra word, never a clause.
- For new failure categories: add a distinct status value (`up` / `standby` / `down` / `impaired` / etc.) so the visualization has a hook for colour/shape. Don't conflate states.
- Cross-check: if the graph is already compressed to a single colour per category, a new colour for a new failure mode is the right lever, not more banner text.
- Same principle on any future status/health surface (alerts page, chaos page, service-health page): the graph is the source of signal; the banner is the summary.

*Source: `memory/feedback_status_detail_in_graph_not_text.md`*

### Stuck Helm release — use OpenTofu -replace via Atlantis

When a Helm release managed by OpenTofu gets stuck in `pending-upgrade`, `pending-rollback`, or `failed` state (e.g. after timeout, killed apply, or rollback failure), the proper GitOps fix is:

```
atlantis plan -p k8s -- -replace=module.monitoring.helm_release.monitoring
atlantis apply -p k8s
```

This passes OpenTofu's `-replace` flag (successor to deprecated `terraform taint`) through Atlantis. It destroys the stuck release (clears all Helm secrets) and creates a fresh install.

**Why:** Multiple failed approaches tried first: `initDatasources=true` (creates broken init container), `kubectl patch` on Helm secrets (violates GitOps), `helm rollback` CLI (violates GitOps), killing Atlantis processes (leaves zombie locks). The `-replace` flag is the ONLY approach that respects the K8s CLAUDE.md ("never kubectl apply/delete managed resources", "never tofu apply locally").

**How to apply:**
- Use when `atlantis apply` fails with "Error upgrading chart", "another operation in progress", or "context deadline exceeded"
- Resource address format: `module.<module_name>.helm_release.<resource_name>` (check error message for exact path)
- Expect brief downtime — the entire release is uninstalled then reinstalled
- After success, the Helm release resets to v1 with clean state
- `atomic=true` + `cleanup_on_fail=true` + `timeout=300` prevent future stuck states

**Real example (2026-04-11):** kube-prometheus-stack stuck at v41 with 41 Helm secrets, 10 orphaned ReplicaSets, stuck pod in Init:1/2. `-replace` fixed it in 80 seconds (25s destroy + 55s create). MR !243 merged.

*Source: `memory/feedback_helm_replace_via_atlantis.md`*

### Substring grep for keywords needs explicit negation filter

`grep -iE "VULNERABLE|NOT ok"` matches "not vulnerable (OK)" because case-insensitive substring grep treats "vulnerable" as a hit anywhere it appears — including inside "not vulnerable". Same trap with `ERROR` matching "no error", `FAILED` matching "not failed", `BAD` matching "not bad", `EXPIRED` matching "not expired".

**Why:** Bit me 2026-05-04 on testssl output parsing. The script's grep for TLS issues had `grep -iE "VULNERABLE|NOT ok"`. Once testssl actually started producing output (after fixing a separate PATH bug), the email reported "44 TLS issues" but 42 were lines like `Heartbleed (CVE-2014-0160) not vulnerable (OK)`. Only 2 were real findings.

**How to apply:** When grepping tool output for severity keywords:

1. **Always pair the keyword grep with a negation filter:**
   ```bash
   grep -iE "VULNERABLE|NOT ok" file | grep -viE "not vulnerable|not.*ok"
   ```
2. **Or use PCRE negative lookbehind** (`-P`):
   ```bash
   grep -iP "(?<!not )VULNERABLE"
   ```
3. **Or use word boundaries** when the tool capitalizes findings deliberately:
   ```bash
   grep -E "\bVULNERABLE\b"   # case-sensitive — only match all-caps marker
   ```

The bug is latent until the tool actually runs successfully. If the tool was previously silently broken (returning 0 lines or error messages), the bad grep produced "0 findings" by accident — fixing the tool exposes the bad grep.

**Process lesson:** When fixing a silent tool failure, scan downstream parsing/filter logic for patterns that would have masked false positives during the broken period. The downstream bug almost certainly exists; the broken tool was just hiding it.

*Source: `memory/feedback_substring_grep_negation_filter.md`*

### Try admin API operations before claiming "no admin access"

Before listing anything as "I don't have admin access to do this," verify what the existing token CAN do via the REST API. SSH-to-server access and admin-API-token access are different surfaces; missing one doesn't mean missing the other.

**Why:** On 2026-05-01 I called out a stuck `canceling` pipeline (25559) as "irreducible — needs admin Rails console." Operator pushed back. The token at `.env:GITLAB_TOKEN` was already `is_admin=True` (root user, id=1) with scopes `[sudo, admin_mode, api, ...]` — verified via `GET /api/v4/personal_access_tokens/self`. **`DELETE /api/v4/projects/<id>/pipelines/<stuck-id>` worked** (HTTP 204), atomically removed the stuck pipeline + freed its resource_group lock. The "irreducible" framing was a self-imposed limit.

**How to apply:** When tempted to write "I don't have admin access" or "this needs operator-side action":

1. Check actual token scopes: `curl -H "PRIVATE-TOKEN: $TOK" /api/v4/personal_access_tokens/self`.
2. Try the relevant admin endpoint(s) end-to-end. Ones that exist on GitLab 18.x:
   - `DELETE /projects/<id>/pipelines/<id>` (atomic kill)
   - `POST /projects/<id>/housekeeping` (queue Gitaly GC)
   - `POST /admin/ci/variables`
   - `GET /admin/users`, `/admin/users/<id>` 
   - `GET /features` (feature-flag state)
   - `GET /application/settings`
3. If the operation fails with 401/403, then admit the limit. If it returns 200/204, you had access.

**Anti-pattern to avoid:** "I don't have SSH to server X" → conflated with "I have no admin reach into the GitLab instance." These are different. The admin REST API often covers what SSH would, including pipeline management, housekeeping, user/feature flag queries, project deletion, etc.

Related: `feedback_youtrack_mcp_state_bug.md` is the same shape — MCP failed but raw REST worked. Don't trust a single tool's failure as a permission verdict.

*Source: `memory/feedback_admin_api_first_then_say_cant.md`*

### Use SSH ControlMaster/ControlPersist for any externally-routed VM with DDoS auto-mitigation (defra01agri01 + similar)

**Rule:** for any host hosted on an external VM provider with DDoS auto-mitigation in front of it (ifog uses FastNetMon, others use Voxility / Path / Cloudflare Magic Transit / etc.), put a `Host` block in `~/.ssh/config` with `ControlMaster auto` + `ControlPersist 30m` BEFORE running automation that issues many separate ssh commands.

**Why:** ifog null-routed defra01agri01's public IP **twice on 2026-04-27** based on FastNetMon flagging "traffic pattern (bandwidth, pps, flows, etc.)". Each Bash-tool `ssh -i ~/.ssh/one_key operator@defra01agri01 'cmd'` is a brand-new TCP + SSH handshake + auth + channel-open + close cycle. Across Day 1+2+3 setup that totalled ~100+ short-lived flows from 203.0.113.X → 118.91.186.185 in a 12-hour window. FastNetMon's heuristics treat that as elevated PPS/flow rate from a single source = candidate for null-route. Auto-mitigation engaged twice, with no operator-side cause and no OS-side crash (host uptime was continuous: 8d during incident #1 and 9d during incident #2). ifog manually lifted both routes.

**The fix — `~/.ssh/config` block:**

```sshconfig
Host defra01agri01
    User operator
    IdentityFile ~/.ssh/one_key
    ControlMaster auto
    ControlPath ~/.ssh/cm/%r@%h:%p
    ControlPersist 30m
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

`mkdir -p ~/.ssh/cm` first. `chmod 600 ~/.ssh/config`.

After that:
- First `ssh defra01agri01 cmd` opens the master (one full handshake)
- Every subsequent `ssh defra01agri01 cmd` reuses the master — no new TCP, no new auth, no new flow visible at ifog's edge
- `ssh -O check defra01agri01` confirms the master is alive
- Master persists 30 min of idle, then cleans up
- ServerAliveInterval=60, CountMax=3 = stalled tunnels close gracefully without the runtime hanging

**Verification snippet:**

```bash
ssh defra01agri01 'echo first'              # opens master
ssh -O check defra01agri01                   # confirms 'Master running (pid=...)'
ssh defra01agri01 'echo second'              # reuses, no new handshake
```

Run `tcpdump -ni any host 118.91.186.185 and port 22` from the source side during a multi-command run; with multiplexing you'll see one SYN, with naive ssh you'll see one per command.

**How to apply:**
- Whenever I'm working on **defra01agri01**, **any VPS at notrf01vps01 / chzrh01vps01** (also externally-hosted with auto-mitigation), or **any new ifog/Hetzner/OVH/etc.** target, the `~/.ssh/config` block goes in BEFORE the automation begins.
- For NL/GR internal hosts (nl* / gr* / behind our own firewalls) this is nice-to-have for speed but not load-bearing — internal mitigation is operator-controlled, not auto.
- For one-off interactive sessions from a terminal, multiplexing is also a quality-of-life win (no auth prompt repeated).

**When this rule kicks in:** any externally-hosted target where you don't control the upstream DDoS detector. If you don't know whether the provider uses one, assume yes — most do, silently.

**Cross-references:**
- `feedback_defra01agri01_ssh_pattern.md` — the operator+one_key+sudo-i SSH pattern (this rule LAYERS ON TOP — same auth, but multiplexed)
- `agentic-agriops-project.md` — both 2026-04-27 outage entries should be updated to credit the FastNetMon root cause once verified

*Source: `memory/feedback_ssh_multiplex_for_ddos_safety.md`*

### Use real n8n execution data (not synthetic fixtures) for parser regression testing

When fixing a parser that processes Claude's free-form output, use the n8n executions API to pull *real* historical inputs and replay them — don't rely on synthesized fixtures alone.

**Why:** During the 2026-04-25 parsePoll fix, three round-trip iterations each found new bugs that synthesized fixtures didn't catch:

- **Round 1** caught Bug 1+2+3 with synthesized fixtures matching the obvious failure modes (operator's reported poll #0).
- **Round 2** added a `mass_buggy_replay.py` that pulled the actual `result` string for the 14 most recent suspicious executions via `GET /api/v1/executions/<eid>?includeData=true`. Found Bug 6 — v2's blank-line break silently broke MESHSAT-664-shape polls (Markdown loose-list spacing) which I'd never have written as a synthetic test.
- **Round 3** paginated 250 executions across 4 pages. Found Bug 7 — nested sub-bullets in MESHSAT-623 (`- **Plan A**\n  - sub-bullet`). Also found Bug 8 — Markdown HR.

Synthetic fixtures encode *what you think Claude does*. Real execution data shows *what Claude actually does* — including formatting variants you'd never invent.

**How to apply:**
- For any n8n Code-node parser fix, walk historical executions with cursor pagination:
  ```
  GET /api/v1/executions?workflowId=<id>&limit=100[&cursor=<next>]
  ```
- For each, fetch full data with `?includeData=true` and pull the upstream node's output (the `result` field).
- Drive the live patched parser through `node` with `new Function('$', '$input', 'Buffer', 'require', code)` (the same wrapper n8n uses internally).
- Classify each result as PASS / GOOD-FAIL (correctly rejected a known-bug shape) / BAD-FAIL (regressed a previously-clean shape).
- Until BAD-FAIL = 0 across the widest history you can fetch, you haven't proven the fix.

**Bonus:** the `Runner` workflow has `saveDataSuccessExecution: 'all'`. The Bridge has `saveDataErrorExecution: 'all'` only — but that's enough to detect regressions (any failed run after deploy is recorded).

*Source: `memory/feedback_use_real_execution_data_for_regression.md`*

### VPS SSH access pattern

VPS SSH: `ssh -i ~/.ssh/one_key operator@198.51.100.X` (NO) or `operator@198.51.100.X` (CH). Root login not available.

**Why:** Discovered during 2026-04-10 tunnel outage. `root@` and `app-user@` both fail. Only `operator` with one_key works.

**How to apply:** All VPS operations (strongSwan, HAProxy, XFRM, swanctl) need `echo '<pw>' | sudo -S <cmd>` pattern. Sudo password same as ASA/scanner password in .env. `swanctl` without sudo fails with "Permission denied" on charon.vici socket.

*Source: `memory/feedback_vps_ssh_access.md`*

### When K8s pod TCP probes hang at 10s — check CiliumNetworkPolicy egress first

**Rule:** Before blaming routing, firewalls, or HTTP-protocol mismatches when a K8s pod times out connecting to an external endpoint, check the CiliumNetworkPolicy on its namespace + endpoint label.

**Why:** I spent ~30 min on 2026-04-30 chasing wrong diagnoses for Gatus probe timeouts to nlcl01file01/02:9101 — first claimed it was K8s pod-network routing (wrong: Prometheus from the same pod CIDR scrapes nlcl01file01:9101 fine), then HTTP/1.0-vs-1.1 protocol mismatch (wrong: ThreadingHTTPServer + protocol_version="HTTP/1.1" didn't fix it), then head-of-line blocking on single-thread server (wrong again). The actual cause was a CNP egress allowlist:

```yaml
- toEntities: [world]
  toPorts: [443, 80, 6443, 8404]
```

Port 9101 wasn't in the list. Cilium dropped at egress.

**Diagnostic in 2 minutes:**
1. `kubectl get cnp -n <ns>` — does the pod have a CNP applied?
2. If yes, read the egress block, look for the destination port.
3. Spawn a labeled curl pod in the same namespace (matching `endpointSelector.matchLabels`) and try the same destination. If it times out / 000s with the same label and works without, the policy is the cause.

```bash
# template — adjust labels for the policy in question
kubectl run probe --rm -i --image=curlimages/curl -n <ns> \
  --labels='app.kubernetes.io/name=<gatus|whatever>' \
  --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"c","image":"curlimages/curl","command":["sleep","60"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}' \
  --command -- sleep 60
```

**Fix:** add the port to the CNP egress allowlist. For external destinations the world entity covers them; for in-cluster, `cluster` is already typically open.

**Common gotchas:**
- `cilium monitor -t drop` shows the drops but only if you're on the right node + at the right time.
- TCP traffic through a CNP-blocked egress can either drop silently (Gatus saw 10s timeout) or RST immediately (curl saw `code=000 t=0`) depending on Cilium config.
- Diagnostic curl from `default` namespace (no policy) WILL succeed and is misleading — the policy is namespace-scoped.

*Source: `memory/feedback_cilium_egress_policy_check_first.md`*

### When asked for a prompt, scope it strictly to what was asked

When the operator says "give me a prompt for X", deliver a prompt scoped to X. Don't bundle:

- Adjacent findings from earlier in the conversation that the operator never asked to act on
- "While we're at it" cleanup
- Cluster-wide sweeps when one host was named
- Multi-step playbooks when one step was asked for

**Why:** Caught 2026-05-07 — operator asked for a "targeted and short prompt to audit how OAS gzip can be disabled" (closing a single testssl BREACH finding). I delivered a prompt covering: 6-host inventory, 9-column inventory table, cert replacement (Finding B from earlier in the chat that the operator never asked to act on), open-questions section, cluster-role discovery. Operator pushed back: "i asked for a targeted and short prompt... you went so far to ask replacing certificates." The cert work was a Finding B I'd raised — once I said it, I treated it as scope, but it wasn't. Operator feedback memories already cover this shape (`feedback_match_defense_to_threat_model.md`, `feedback_no_time_estimates_group_by_logical_units.md`); add the prompt-writing variant explicitly.

**How to apply:**

1. Re-read the request literally. If it says "a prompt to do X", the deliverable is one prompt about X.
2. If earlier in the conversation I surfaced findings B, C, D — those exist for the operator to act on or not. They are NOT my scope unless the current message names them.
3. One host named → one host in the prompt. One finding named → one finding in the prompt. The receiving Claude session will not infer cluster-wide scope from a single-host SSH target — that's correct behaviour.
4. Length test: if the prompt is over ~25 lines for a single read-only investigation, I have probably bundled too much. Cut.
5. The operator's vocabulary "targeted" / "short" / "minimal" maps to: one task, one host (unless explicitly multi), no adjacent cleanup, no follow-on roadmap baked in. Same shape as `feedback_single_operator.md`.

A useful sanity-check before sending a prompt: read it back as if I were the receiving Claude session — does the *task* clause name the same scope as what the operator literally asked for? If the task clause is broader, I scope-crept.

*Source: `memory/feedback_prompt_scope_match_the_question.md`*

### When fixing cron-env gaps, pair PATH + .env-sourcing

When you patch a cron-driven script for an environment-shaped failure (an `.env`-var unset, or a binary-not-found, or a `which()` returning None), audit the OTHER dimension before commit. Both dimensions fail silently under cron, both look like "the alert is broken" rather than "the script is broken," and they tend to surface months apart on different labels of the same alert.

**Why:** `IFRNLLEI01PRD-827` (2026-04-23, commit `088ef45`) patched the `.env`-sourcing half of `scripts/write-skill-metrics.sh` + `scripts/audit-skill-requires.sh` after `SkillPrereqMissing` false-fired on `env:GITLAB_TOKEN`. The PATH half was not touched. Twelve days later (2026-05-05) the same alert false-fired on `bin:kubectl` for k8s-diagnostician + drift-check, triggering five chatops loops in 12h before the second half of the same fix was identified. Same shape hit `weekly-scan.sh` on 2026-05-04 (`scanner_nuclei_silently_broken_20260504`). The general lesson: a cron-env fix is rarely complete in one dimension — the missing PATH and the missing .env-var live next to each other.

**How to apply:** before committing a fix to a cron-driven script, run all three of these:
1. `grep -n 'set -a\|\. .*\.env' <script>` — does it source `.env`? If it has any `os.environ.get(...)` or references env vars at runtime, it must.
2. `grep -n 'export PATH\|PATH=' <script>` — does it set PATH? If it calls (directly or via `which()`/`shutil.which()`) any binary outside `/usr/bin` or `/bin`, it must export PATH explicitly.
3. Simulate cron: `env -i HOME=$HOME LOGNAME=$USER USER=$USER SHELL=/bin/bash PATH=/usr/bin:/bin bash <script>` — watch for missing bins / unset vars in the output. This is what the cron daemon actually inherits.

If any of (1)-(3) flags a gap, fix it in the same commit as the original patch. The alternative is "the same alert false-fires on a different label N weeks later" — which is the literal pattern this rule was born from.

*Source: `memory/feedback_pair_cron_env_fixes_path_and_dotenv.md`*

### When operator asks for "API", confirm API surface first — don't dive into source/DB until gap is proven

**Rule.** When the operator names a tool with a documented API and asks "use the API to do X", the first investigative step is `GET /api/v0/` (or the equivalent route listing) and grep for the relevant verb. If the route exists, use it. If it doesn't, surface the API gap explicitly and ask which fallback (CLI / form endpoint / DB write) the operator is comfortable with.

**Why:** Caught 2026-05-09 mid-Freedom-outage on a LibreNMS ifSpeed override. Operator picked Option A (override port ifSpeed), then watched me SSH into nl-nms01, grep PHP source, query MariaDB schema, and inspect existing `devices_attribs` rows — all to discover information that the API root listing would have surfaced in one curl. Operator's reaction: "what the fuck are you even doing? why checking the php code and why are you even checking the database tables? use the API to configure the interface in librenms". Fair. The right sequence was: hit the API, confirm the gap, then surface it.

This generalises: the same trap exists with any well-instrumented system — n8n REST, GitLab API, AWX API, Proxmox API, NetBox API. When the operator says "use the API", the first cost is one curl to the route table; the second cost is asking "this isn't there, want me to use X instead?" — both far cheaper than reading source.

**How to apply:**
1. Read the API root listing: `curl -sk -H "<auth>" "<base>/api/v0/" | python3 -c "import sys,json; r=json.load(sys.stdin); [print(k,'=',v) for k,v in r.items() if 'KEYWORD' in k.lower()]"`.
2. If the route exists → use it. End.
3. If the route doesn't exist → tell the operator immediately, list the route table snippet that proves it, and offer 2-3 non-API alternatives (CLI / form / DB / WebUI).
4. Never silently fall back from REST to source-diving without acknowledging the gap.

*Source: `memory/feedback_api_first_then_say_cant_no_php_diving.md`*

### Wrap `nohup … &` SSH-launched processes in systemd-run --user --scope

**Rule.** Any time an automation SSHes into a host to launch a backgrounded process (`nohup cmd &`), wrap the launch with `systemd-run --user --scope --quiet --slice=app.slice --unit=<name>` so the child is placed under `user@UID.service/app.slice/<unit>.scope`, NOT under the SSH session scope.

**Why.**

- systemd-logind tracks each SSH session in a `session-NNNN.scope` cgroup under `user-UID.slice`.
- When the SSH connection closes, sshd dies but logind only finalises the scope once its cgroup is empty.
- A `nohup cmd &` child stays in the session scope because backgrounding doesn't change cgroup membership.
- logind sets `State=closing` on the scope and waits — forever.
- Symptom: `loginctl list-sessions` / `uptime` report phantom users; `systemctl list-units session-*.scope --state=closing` fills with zombies; 202+ leaked processes per ~100 leaks; uptime load average misleading.
- On 2026-04-22 the operator found 101 abandoned session scopes on nl-claude01, all traced to Runner + Matrix Bridge n8n workflows using the `nohup claude …` pattern. Pattern documented in CLAUDE.md as "Background launch + progress polling".

**Fix pattern** (substitute for `nohup cmd …`):

```bash
# BAD — child inherits SSH session cgroup, leaks on disconnect:
nohup timeout 300 /home/app-user/.local/bin/claude … > "$LOG" 2>&1 &
PID=$!

# GOOD — child lives in user@UID.service/app.slice, outside session scope:
nohup systemd-run --user --scope --quiet --slice=app.slice \
  --unit="claude-$$-$(date +%s%N)" \
  timeout 300 /home/app-user/.local/bin/claude … > "$LOG" 2>&1 &
PID=$!
```

The `$!` still captures the actual process PID (systemd-run exec's into the command), so existing PID-based health-check code (`kill -0 $PID`) still works unchanged.

**Prereqs on the target host.**

- User must have `Linger=yes` enabled (`loginctl enable-linger <user>`) so their systemd `user@UID.service` persists between SSH sessions.
- systemd ≥ 229 for `--user --scope`.

**Verification** (`ssh user@host 'cgroup=$(cat /proc/$$/cgroup); echo "$cgroup"'` before and after):

- Before fix: `0::/user.slice/user-1000.slice/session-NNN.scope`
- After fix: `0::/user.slice/user-1000.slice/user@1000.service/app.slice/<unit>.scope`

**Reaping existing leaks.**

- Cosmetic, low-risk: `systemctl restart systemd-logind` — reaps all `State=closing` session scopes without disturbing SSH or services.
- Per-scope: `systemctl stop session-NNN.scope` (may be blocked by guard hooks on protected hosts).

**Applied to.**

- `workflows/claude-gateway-runner.json` (8 launch sites, 2026-04-22)
- `workflows/claude-gateway-matrix-bridge.json` (8 launch sites, 2026-04-22)

**How to apply going forward.**

- Any new n8n workflow launching a long-running process via SSH must use this pattern. Validators don't currently catch the leak pattern — adding `grep -q "nohup.*claude.*&$"` to `scripts/validate-n8n-code-nodes.sh` is a reasonable follow-up.
- AWX / Ansible equivalents (if they also launch via SSH + nohup) should apply the same wrapper.

*Source: `memory/feedback_systemd_run_for_ssh_launchers.md`*

### YouTrack MCP state-update bug — use direct REST instead

**The bug.** Both `mcp__youtrack__update_issue_state` and `mcp__youtrack__update_custom_fields` (with `{"State": "<state>"}` payload) fail with `"Unknown workflow restriction"` and `"This may be due to workflow restrictions, permissions, or state machine guard conditions."` even when:

- The user has full permission (verified — `mcp__youtrack__add_comment` works on the same issues; the issue's state field is `StateIssueCustomField` not `StateMachineIssueCustomField` so there are no guard conditions).
- The target state is a valid bundle value for the project (verified by reading a recently-closed sibling issue's customFields).
- The token (`perm-Q2xhdWRl...`) belongs to user "Claude" who already commented + created the issue.

The MCP's `diagnose_workflow_restrictions` itself reports `available_transitions: []` even though the same token successfully drives the same transition via raw REST.

**Why:** Looks like the MCP wrapper's state-update implementation doesn't include the `$type: "StateBundleElement"` discriminator on the value object — YouTrack's schema requires it for state changes via the customFields-array shape.

**The fix (direct REST workaround).** Use the YT REST API directly:

```bash
YT_TOKEN="$(grep -oE 'perm-[A-Za-z0-9./=_-]+' /home/app-user/.claude.json | head -1)"
curl -sk -X POST \
  -H "Authorization: Bearer $YT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  "https://youtrack.example.net/api/issues/IFRNLLEI01PRD-XYZ?fields=customFields(name,value(name))" \
  -d '{"customFields":[{"name":"State","$type":"StateIssueCustomField","value":{"name":"Done","$type":"StateBundleElement"}}]}'
```

HTTP 200 + the response body shows the new state value. Works for all states in the bundle: Submitted, Open, In Progress, To be discussed, Reopened, Can't Reproduce, Duplicate, Fixed, Won't fix, Done (and any others added later).

**Verified:** transitioned IFRNLLEI01PRD-747..-751 to Done on 2026-04-29 with this approach after the MCP rejected all 5.

**Why memory not patch:** the MCP is a third-party container (`tonyzorin/youtrack-mcp:latest`). Operator can either upstream a fix or pin a fork. Until then, every Claude session should fall back to the REST workaround when state transitions fail.

## How to apply

When `mcp__youtrack__update_issue_state` or `update_custom_fields(state=...)` returns `"Unknown workflow restriction"`:

1. Confirm the failure isn't a real permission issue (`mcp__youtrack__add_comment` succeeds on the same issue → MCP bug, not perms).
2. Pull the YT token: `python3 -c "import json,re;print(re.search(r'perm-[A-Za-z0-9./=_-]+', json.dumps(json.load(open(\"/home/app-user/.claude.json\")))).group(0))"`.
3. POST to `/api/issues/{idReadable}` with the customFields-array shape including the `$type` discriminator on both the field and the value.

Do not block on this — there is a working path.

*Source: `memory/feedback_youtrack_mcp_state_bug.md`*

### YouTrack state transitions use command API

YouTrack MCP `update_issue_state` fails with "Unknown workflow restriction" for state transitions (Open→Done, In Progress→Done, etc.). The MCP tool can't handle workflow-restricted state machines.

**Working approach:** Use the YouTrack command API directly:
```bash
curl -s -X POST "https://youtrack.example.net/api/commands" \
  -H "Authorization: Bearer ${YT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"query": "State Done", "issues": [{"idReadable": "ISSUE-ID"}]}'
```
Empty `{}` response = success. Token is **`YT_TOKEN`** from `.env` — NOT `YOUTRACK_TOKEN` (which is undefined and silently yields `Authorization: Bearer ` → HTTP 401 "Invalid token"). Always verify with a GET (`curl -w "HTTP=%{http_code}\n"`) before calling `/api/commands` so auth failures don't look like command successes. There are also `YOUTRACK_API_TOKEN` and `YOUTRACK_URL` in `.env` for reference.

**Why:** YT MCP's update_issue_state uses direct field API which doesn't respect workflow state machine transitions. The command API (`/api/commands`) executes commands as if typed in the YT UI, which properly handles workflow rules.

**How to apply:** For any YT state change, use curl to `/api/commands` instead of the MCP tool. MCP tools still work for: `add_comment`, `get_issue`, `search_issues`, `get_custom_fields`.

*Source: `memory/feedback_yt_command_api.md`*

### chaos catalog drift per topology change

Every time the mesh adds a new ASA/router/VPS or moves a tunnel termination, `experiments/catalog.yaml` needs at minimum:
- A `targets:` entry for the new device (`type`, `site`, `capabilities`, `access`)
- One mirror experiment per chaosable interface on that device (`tunnel-{site}-{peer}-{wan}` for each VTI)

**Why:** Catalog is the source of truth for `chaos_catalog.py` validation + Chaos Toolkit / Azure Chaos Studio export. Pre-2026-04-21 catalog was ASA-only. When `nlrtr01` took over budget WAN, no one updated the catalog. Drift sat hidden for 15 days. My 2026-05-06 TX additions (referencing rtr01) tripped the validator.

**How to apply:** When onboarding a new tunnel-terminating device, run `python3 scripts/chaos_catalog.py validate` after the IaC changes — if it fails, the catalog is the missing piece. Then add the target + experiments before merging. The validator is the canary; trust it.

**Worked example:** I added 3 mirror budget-side experiments (`tunnel-nl-{gr,no,ch}-budget`) in commit `c078291` to fix the rtr01 drift caught during the txhou onboarding. Took ~15 minutes; should have happened on 2026-04-21.

*Source: `memory/feedback_chaos_catalog_drift_per_topology_change.md`*

### chaos test density can drift kernel state

**Rule:** When running chaos engineering on hot production clusters, do not run multiple disruptive operations against the same kernel-level subsystem within minutes of each other.

**Why:** On 2026-04-30 I ran Phase 2 NFS auto-flush verification (10:44-10:47, three back-to-back exportfs cycles + manual cycles) followed by T1 HA restart (11:03). At 11:48 — ~45 minutes after the dense phase, with no operator activity — the nlcl01file02 nfsd kernel fh-cache spontaneously re-poisoned, taking HA down for ~2 min until the manual `pcs resource restart exportfs` recovery. The chaos batch was the trigger; the manifestation was lagged.

This pattern (delayed manifestation of a kernel-state drift) is hard to reproduce on demand. The 11:48 incident wasn't reproducible during the formal C1 chaos test that followed, despite trying the same stress-cycle. The kernel had already settled by then. So:

1. Once a kernel subsystem is stressed (NFS fh-cache, OCFS2 dlm, DRBD replication, etc.), give it 15-30 min of normal-load idle time before stressing it again.
2. Verify ground-truth (mounts work, exports refresh cleanly, monitors pass) before queuing the next chaos test.
3. The outage you cause may not look like the chaos test you ran — symptoms can be lagged and morphed.

**How to apply:**
- For chaos catalogs of 5+ tests touching the same subsystem, plan for 30+ min of test execution time, not just the per-test recovery.
- For chaos against shared production: prefer a dedicated test cluster mirror, or run chaos during a maintenance window with operator on-call.
- If a chaos test causes an unexpected real outage (not the simulated one), STOP the catalog and diagnose before continuing.

*Source: `memory/feedback_chaos_test_density_kernel_drift.md`*

### check other sessions before claiming account exhaustion

Before diagnosing any failure as "the account/quota/billing is exhausted," verify the negative: if other sessions on the same account are still working concurrently, exhaustion is not the cause. Per-token, per-credential, per-call-pattern, or per-model limits exist and look identical to account exhaustion in error wording.

**Why:** 2026-04-29 — operator caught me proposing fixes for "Max account quota depletion" while we were actively chatting on the same Max account. Their words: "how. the. fuck. are. we. still. chatting. here?" The answer was that OpenClaw's separate OAuth token had its own 5-minute burst window that didn't affect nl-claude01's session. I should have recognized that the moment they pushed back the first time. Three rounds of bad theory + one harmful migration (setup-token, 100% failure rate, profile auto-disabled for 5–24h, had to roll back) before I admitted it.

**How to apply:**
- The error wording from upstream APIs ("out of usage", "extra usage", "quota exceeded") is generic. Don't infer the *cause* from the *message*.
- Always ask: "is anything else on the same account still working?" If yes, the cause is narrower than account-level.
- Identical `errorHash` / `error_id` across multiple retries = same upstream payload = batch-level not per-request — but still doesn't tell you whether the bucket is account, token, or session level.
- Before applying a "fix" that changes the failing path, prove the proposed alternative path actually works on this account with a single small probe call. Do not migrate first and test second.

*Source: `memory/feedback_check_other_sessions_before_account_exhaustion_theory.md`*

### clippy-local-must-match-ci-workspace-all-targets

Before pushing any omoikane.coach/daemon MR, run the **CI-matching** clippy invocation:

```bash
cd app && cargo clippy --workspace --all-targets --locked -- -D warnings
```

NOT `cargo clippy --bin omoikane-daemon --tests --locked -- -D warnings` — that's a strict subset.

**Why:** OMOIKANE-914 (2026-05-29) shipped with `count() as i64` in `foreign_company_enrichment_worker.rs` line 518. My pre-push gate (`--bin --tests`) passed; CI's `clippy_gate` passed too because both compile only the daemon bin's own crate. But CI's `migration_smoke` job runs `cargo test --no-run --bin omoikane-daemon --locked` which goes through the FULL rustc invocation with all `[lints.clippy]` denies — including `cast_possible_wrap` — and rejected the `usize → i64` cast. Pipeline 34661 burned ~5min to surface this.

The CI invocation `scripts/ci-clippy-gate.sh` literally does `cargo clippy --workspace --all-targets --locked -- -D warnings`. That's the contract; match it locally.

**How to apply:** When working in any per-session daemon worktree, before `git push`:

1. `cd /tmp/daemon-<purpose>/app && cargo clippy --workspace --all-targets --locked -- -D warnings`
2. Exit code 0 = green. Exit non-zero = read the error and fix BEFORE push.
3. ~4-5 min wall-clock cold; cached after first run.

If `--workspace --all-targets` errors but `--bin --tests` doesn't, the failure is almost always one of:
- `cast_possible_wrap` / `cast_sign_loss` (silent `as` casts) — fix with `i64::try_from(x).unwrap_or(i64::MAX)` (project convention; mirrors `discover_esco_tags_worker.rs:348`, `salary_aggregate_worker.rs:172`, `cross_eu_resolver_worker.rs:298-299`)
- Workspace-sibling crates (mcp/, temporal-worker/) — those compile under `--workspace` but not under `--bin omoikane-daemon`

Related: [[feedback-no-shared-main-worktree]] (per-session worktrees), [[feedback-mr-description-in-initial-post]] (open MR with description in initial POST).

*Source: `memory/feedback_clippy_local_must_match_ci_workspace_all_targets.md`*

### count-incidents-not-events-when-measuring-auto-resolve

When designing or reviewing any "auto-resolution %", "noise rate", "MTTR", or "MTTA" metric in the agentic platform, the unit of analysis must be the **incident** (one unique `issue_id` / one unique root cause), not the alert **event** (one row in triage.log or one webhook firing).

**Why:** Sustained outages (Freedom PPPoE down, GR poller stall, nl-gpu01 io-error) generate dozens of repeat alerts against the SAME issue_id. Event-based counting treats each repeat as a separate "the system failed to resolve" — inflating the denominator and tanking the headline rate. On 2026-05-12 the agentic-stats outcomes block read 6.76% (event-based) vs 27.3% (incident-based, best-outcome) on the same 7d window — a 4.7× distortion.

**Industry references that say the same thing:**
- Google SRE Book, Ch 6 "Monitoring Distributed Systems" — alerts are correlated at the cause, not the symptom; metrics are per-incident.
- Datadog SRE Maturity Model 2024 — auto-resolution rate measured per incident; >90% event-based is flagged as a gaming signal.
- PagerDuty MTTR/MTTA definitions — per-incident, with parent-child folding via Event Intelligence.
- Prometheus Alertmanager `inhibit_rules` syntax — exists specifically to fold downstream-event noise into one incident.

**How to apply:**
- When writing a new metric in `agentic-stats.py` / `lab-stats.py` / `mesh-stats.py`: dedupe events by `issue_id` and rank outcomes per issue (best-of: resolved > dedup > escalated).
- When reading a metric: if the denominator is event-count and you have a sustained-outage week in the window, mentally divide by 3-5×.
- If asked "are we auto-resolving?", quote both numbers (event-based and incident-based) until the metric is fixed, and lead with the incident-based one.
- One-number alternative the SRE textbook prefers: `pages_per_oncall_shift` (Google's "toil per oncall hour"). Lower is better; not gameable by suppression tricks.

Caught 2026-05-12 investigating the agentic-stats auto-resolve regression. See `[[auto_resolve_regression_diagnosis_20260512]]` for the full case study.

*Source: `memory/feedback_count_incidents_not_events.md`*

### dataclass(frozen=True) + importlib.util fails on Python 3.11 — use NamedTuple

**The bug.** Building `scripts/lib/jailbreak_detector.py` (G1 / IFRNLLEI01PRD-748, 2026-04-29) the original code used:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Detection:
    category: str
    pattern: str
    span: tuple[int, int]
```

The library compiled fine. The QA suite (test-jailbreak-corpus.sh) loaded it via:

```python
spec = importlib.util.spec_from_file_location("jbd", "$LIB")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
```

Loading failed at the `@dataclass(frozen=True)` line:

```
AttributeError: 'NoneType' object has no attribute '__dict__'. Did you mean: '__dir__'?
  File "/usr/lib/python3.11/dataclasses.py", line 712, in _is_type
    ns = sys.modules.get(cls.__module__).__dict__
```

`_is_type` is part of the dataclass-decorator machinery introduced for `KW_ONLY` and `ClassVar` resolution. It calls `sys.modules.get(cls.__module__).__dict__` to inspect the namespace where the class was defined — but `importlib.util.spec_from_file_location` does NOT register the module in `sys.modules`. So `sys.modules.get("jbd")` returns `None` → `None.__dict__` → AttributeError.

**The fix.** Replace `@dataclass(frozen=True)` with `typing.NamedTuple`:

```python
from typing import NamedTuple

class Detection(NamedTuple):
    category: str
    pattern: str
    span: tuple[int, int]
```

NamedTuple is immutable, fields are typed, attribute access works the same way. No `_is_type` path, no `sys.modules` dependency. Drop-in replacement for read-only typed records.

**Why dataclasses do this.** Python 3.10 added forward-reference resolution to dataclasses; Python 3.11 hardened it. The check fires for any field annotation that needs evaluation (str, tuple[…], etc.). It only matters when the *module containing the dataclass* isn't in `sys.modules`.

**Two alternative fixes** (less clean):

1. Register the module before exec_module:
   ```python
   import sys
   spec = importlib.util.spec_from_file_location("jbd", path)
   m = importlib.util.module_from_spec(spec)
   sys.modules[spec.name] = m   # <-- add
   spec.loader.exec_module(m)
   ```
   This works but every test caller has to remember the line. Easy to forget.

2. Avoid `frozen=True`:
   ```python
   @dataclass
   class Detection:
       ...
   ```
   `_is_type` isn't called for non-frozen dataclasses. But you lose immutability + hashability.

**Detection signal.** If you load a Python module via `importlib.util.spec_from_file_location` (common in test runners that need to load files outside the package layout) and you see `AttributeError: 'NoneType' object has no attribute '__dict__'` originating from `dataclasses.py` line 712 (or nearby), this is the issue. Switch to `NamedTuple` and move on.

## How to apply

For any new pure-data record that:
- needs to be immutable + typed
- might be loaded via `importlib.util` from a test or external loader
- doesn't need methods, default factories, `__post_init__`, or any other dataclass-specific feature

… reach for `typing.NamedTuple` first. Reserve `@dataclass(frozen=True)` for cases where you need defaults, `field(default_factory=...)`, or post-init validation — and only when the module is reliably imported via the normal path.

*Source: `memory/feedback_dataclass_importlib_quirk.md`*

### defra01agri01 SSH pattern — operator + one_key + sudo -i ONLY

**Rule (operator-locked 2026-04-27):** All SSH sessions to `defra01agri01` MUST use exactly this pattern. No exceptions, no fallbacks, no probing.

```bash
ssh -i ~/.ssh/one_key operator@defra01agri01 [...]
# inside the session, for root work:
sudo -i [<command>]
```

**Concretely — the Bash tool invocations look like:**

- `ssh -i ~/.ssh/one_key -o BatchMode=yes -o ConnectTimeout=10 operator@defra01agri01 'bash -s' << 'EOF' ... EOF`
- For privileged ops inside the session: `sudo -i <cmd>` (NOT `sudo -n`, NOT plain `sudo`, NOT `su`)

**Why:**
- Operator's stated requirement on 2026-04-27 after a session where they audited sshd logs and found unrelated `dedi` (and one `root`) failed-auth attempts from the same NL ASA Freedom WAN egress (`203.0.113.X`). To eliminate ambiguity, the only authorised SSH identity for Claude→defra is `operator` via `one_key`. Any other username (`dedi`, `root`, `app-user`, etc.) is forbidden.
- Sudo on defra is configured passwordless for `operator`; `sudo -i` invokes a login root shell with proper environment (`/root` PATH, login dotfiles).

**How to apply:**
- ALWAYS specify `operator@defra01agri01` explicitly. Never rely on default user resolution. Never use `ssh defra01agri01` bare.
- ALWAYS use `-i ~/.ssh/one_key`. Never offer other keys. (`BatchMode=yes` is recommended too, since password auth is forbidden.)
- For privileged ops inside the session, prefer `sudo -i <cmd>` over `sudo -n <cmd>` per operator preference.
- Do NOT SSH as `root` directly. Do NOT use other users.
- This rule is specific to defra01agri01 — other hosts retain their own conventions (e.g., `~/.ssh/config` aliases for `nl-openclaw01` use `User root`, which is correct for those hosts).

**Memory ties:**
- Project: `agentic-agriops-project.md`, `defra01agri01_mirror_target.md`
- YT issue: `IFRNLLEI01PRD-742`

*Source: `memory/feedback_defra01agri01_ssh_pattern.md`*

### docker-reclaimable-misleading

The `Reclaimable` column in `docker system df` (and its `--format json` equivalent) is **not a real free-space measure**. Docker counts every image that isn't pinned to a *currently running* container as "reclaimable", even when stopped containers still reference it. On a healthy host the value drifts upward forever — every new `docker pull` adds to the total without freeing anything — but actually running `docker image prune -af` won't free those bytes without also tearing down the dependent containers.

**Why:** Caught 2026-05-12 by operator question after I wired the Gpu01DockerImagesReclaimableHigh alert on nl-gpu01 (MR !294). On nl-gpu01 at the time: `Reclaimable` read 97.6 GiB but only 124 MiB (`python:3.11-slim`, one truly orphan image) was actually prunable. The threshold at 100 GiB would have fired on the next pull of any moderately-sized image — pure noise, no actionable signal. Swapped for `Gpu01DockerDanglingImagesHigh` in MR !295.

**How to apply:**
- For alerting on Docker bloat, use **`docker images -f dangling=true`** instead. Those are truly orphan layers (no tag, no container ref) — safe to remove with `docker image prune -f` (no `-a` needed). Baseline on a healthy GPU/CI host: < 1 GiB.
- For Grafana visibility, keep emitting `docker_reclaimable_bytes` as a *diagnostic* metric — it shows total image storage trend over time, which is useful context. Just don't wire an alert on it.
- Don't post-hoc rationalize a misleading metric. If a metric drifts upward indefinitely on a healthy host, it's the wrong metric — change it, don't paper over with a higher threshold.
- See [[nl-gpu01_freeze_qcow2_io_error_20260512]] for the full context.

*Source: `memory/feedback_docker_reclaimable_misleading.md`*

### dockerfile is the right place for runtime writes to root-owned paths

When a containerized service runs as a non-root user (`USER node` or similar) and you need to ensure something exists in a root-owned location (`/usr/local/bin/*`, `/usr/local/lib/node_modules/*`, system-wide configs), **do it at image build time via Dockerfile `RUN`**, not at container start time via entrypoint script.

**Why:** 2026-04-29, OpenClaw upgrade, ~30 min wasted. The patch-matrix-timeout.sh entrypoint had logic to install claude CLI: `if [ ! -x /usr/local/bin/claude ]; then npm install -g @anthropic-ai/claude-code; fi`. The script *appeared* to run (logged "[patch] Installing..."), but the install silently failed because the entrypoint runs as the container's `USER` (uid 1000), not root, and `/usr/local/lib/node_modules` is root-owned 755 — non-root users get permission denied. The npm install errored out (truncated output hid this), the script `exec`d the gateway, and claude was missing.

Manual `docker exec -u root /patch-matrix-timeout.sh true` worked, confirming root-vs-node was the issue.

**How to apply:**
- Anything that writes to `/usr/local`, `/usr/lib`, `/usr/bin`, `/etc`: Dockerfile `RUN`. Period.
- Entrypoint scripts can only safely write to volumes the user owns or paths owned by the container user.
- For OAuth/session credentials, mount from a host directory `chown`'d to the container user's UID (1000:1000), and copy in entrypoint to the `~/<user>` path with chmod 600.
- If something needs to be runtime-determined (like fetching latest deps), ensure it runs before `USER` is set, OR run the entrypoint as root and `gosu`/`su -c` to drop privileges before exec'ing the main process.
- Test the persistence by running `docker compose up -d --force-recreate` and verifying everything works without manual intervention. If you need to docker-exec anything to fix it after recreate, you don't have persistence yet.

*Source: `memory/feedback_dockerfile_for_runtime_writes_to_root_paths.md`*

### don't infer account quota state from error messages

When the Claude CLI / Claude Code API returns HTTP 402 with "You're out of extra usage. Add more at claude.ai/settings/usage and keep going.", do NOT diagnose this as "the account is depleted" or "Max quota exhausted" without verifying.

**Why:** 2026-04-29 — operator pushed back on exactly this framing during an OpenClaw triage incident: "i can see my usage on the claude.ai settings; if it was 100% how can we chat right now and also on another session; you logic is flawed." They were right. The 402 was hitting only large-call burst patterns; the operator's interactive session worked simultaneously, and claude.ai/settings showed sub-100% usage. The error wording was misleading me.

**How to apply:**
- The 402 message is generic. Anthropic doesn't expose which dimension of which limit was hit (tokens-per-5h, requests-per-5h, extras-pool, etc.).
- claude.ai/settings/usage is what the operator can actually see. It's authoritative.
- If you must speculate about cause, label it as speculation and ask the operator to check the usage page.
- Reproduce the failing call exactly before claiming it's quota — small calls slipping through doesn't mean the auth is fine, and large calls failing doesn't mean the account is empty. Both can coexist if the throttle is size- or burst-keyed.
- Identical `errorHash` across multiple model fallbacks tells you the upstream is returning the same payload regardless of model, which is consistent with billing-class blocks but doesn't tell you whether they're transient or permanent.

*Source: `memory/feedback_dont_infer_quota_state_from_error_message.md`*

### don-t-pad-auto-resolve-numerator-with-dedup-only-writes

When tempted to improve the agentic-stats auto-resolve headline by writing additional `dedup` rows to `triage.log` from the receiver's repeat-alert branch (or any equivalent "the system avoided work" event), **don't**. This was explicitly proposed and rejected on 2026-05-12 as "Layer A2".

**Why:** "We auto-resolved an incident" and "the receiver deduplicated an event" are not the same statement. Padding the numerator with the second kind makes the metric say "92% auto-resolved" when the underlying reality is "27% of incidents resolved + 65% of events deduplicated". A reviewer looking at the headline can't distinguish. Industry SRE maturity models (Datadog 2024, PagerDuty Operational Maturity) call out exactly this pattern as a gaming signal — >90% headline auto-resolve is typically achievable only by counting dedup events as resolutions or by over-aggressively suppressing real failures.

**How to apply:**
- If the goal is "make the metric honest", switch the denominator to unique-issue counting (see `[[feedback_count_incidents_not_events]]`).
- If the goal is "reduce alert noise so fewer events arrive in the first place", fix the upstream brittleness — Alertmanager `inhibit_rules`, persistent dedup state, parent-incident fold. The numerator goes up because the work was genuinely avoided, not because of accounting.
- Acceptable: writing `dedup` rows only when Tier 1 *actively* matched a parent incident via `tier1_suppression.py` (the Phase 1 path). Not acceptable: writing `dedup` rows just because the n8n receiver's 60s `__alert_dedup_<alertKey>` matched.

Caught 2026-05-12 during the auto-resolve regression diagnosis. The 4-layer remediation plan explicitly orders A1 (incident-based metric) and D (parent-incident fold) ahead of any numerator-padding approach. See `[[auto_resolve_regression_diagnosis_20260512]]`.

*Source: `memory/feedback_no_dedup_writes_to_pad_numerator.md`*

### feedback-adapter-knobs-must-be-env-driven

Every adapter tunable — per-adapter timeout, max-pages, items-per-run, retry count, inter-request delay, kill-switch / disable flag, alternate-endpoint URL — MUST be exposed as an env var with a sane default. Tuning these values should NEVER require: write Rust → push MR → wait pipeline → wait docker build → wait auto-deploy → force-recreate. The full cycle is ~16 min minimum (pipeline 5 + docker 10 + deploy 2) which means tuning under fire is impossible.

**Why:** caught 2026-05-30 23:39 UTC when xe.gr deployed AWS WAF between the operator's earlier "plain HTTP works" probe and the Phase 4 deploy. xe_gr started failing every fan-out with HTTP 405 + "Human Verification" — and the operator's response was "shouldn't all these be dynamic variables configured in an .env file instead of pushing a new MR every time you want to tune a value?". Three independent knobs that needed touching in fast succession (TIMEOUT_XE_GR_SECS 120 → 5; XE_GR_MAX_DETAILS 25 → 50; INTER_DETAIL_MS 1500 → 800; then DISABLED=true to silence) — each as a code-path change would have been 3 MRs.

**How to apply:**

1. When writing a new adapter, surface EVERY magic number as an env var:
   ```rust
   const DEFAULT_X: u64 = 30;
   fn x() -> u64 {
       std::env::var("OMOIKANE_<ADAPTER>_X")
           .ok().and_then(|s| s.trim().parse::<u64>().ok())
           .unwrap_or(DEFAULT_X).clamp(<lo>, <hi>)
   }
   ```
2. Every adapter MUST expose a `..._DISABLED` env-flag with a `disabled()` early-return at the top of `search()`. Default false; operator flips when upstream goes down (WAF, paywall, server-error, etc.) — no code change needed.
3. Naming pattern (locked): `OMOIKANE_<KIND>_<KNOB>` where `<KIND>` matches `SourceKind::as_str().to_uppercase()`. Examples:
   - `OMOIKANE_XE_GR_DISABLED`
   - `OMOIKANE_XE_GR_MAX_DETAILS_PER_RUN`
   - `OMOIKANE_XE_GR_TIMEOUT_MS`
   - `OMOIKANE_XE_GR_INTER_DETAIL_MS`
   - `OMOIKANE_RANDSTAD_GR_MAX_PAGES`
   - `OMOIKANE_WELCOME_TO_NL_MAX_PAGES`
4. Per-adapter timeout already exists via `OMOIKANE_DISCOVER_ADAPTER_TIMEOUT_<KIND>_SECS` (`handlers::discover::kind_specific_timeout`). Keep this pattern.
5. Document every adapter knob in `docs/runbooks/adapter-tunables.md` as a single table (KIND × KNOB × DEFAULT × CLAMP × MEANING). Operator reads this when tuning under fire; never grep the source.
6. Drift-lock test per adapter: `omoikane_<NNNN>_<adapter>_exposes_all_knobs_as_env` asserting source contains the expected `std::env::var("OMOIKANE_<KIND>_<KNOB>")` strings.

**Anti-patterns:**
- `const TIMEOUT_SECS: u64 = 30;` used directly in `search()` without an env override.
- `const MAX_DETAILS: usize = 25;` used directly without an env override.
- Hardcoded URLs (`const SITEMAP_URL = "..."`) — sometimes legit but flag for review; URLs can also be env-overridden when sites move endpoints.

**Exemptions** (don't promote to env):
- Schema column names, JSON field names, regex patterns for HTML parsing — these are interface contracts, not tunables.
- HTTP method (`POST` vs `GET`) — interface contract.
- The `SourceKind` enum string — drift-locked.

**Where to land the next tuning-pressure MR:** `docs/runbooks/adapter-tunables.md` + each adapter file's knob fn. Bundle ALL adapters into one MR, not one per adapter; this is the "comprehensive env-driven refactor" the operator asked for on 2026-05-30. Mirror of `OMOIKANE-940` env-override pattern but applied to per-adapter internals.

*Source: `memory/feedback_adapter_knobs_must_be_env_driven.md`*

### feedback-always-code-in-foreground

**Rule:** When the operator hands me a coding task (Rust + SQL + Maud + Python + JS — anything that gets committed and shipped), I code it myself in the foreground. I do not delegate the implementation to a general-purpose subagent.

**Why:**
1. The operator wants real-time visibility into edits + commits + push (this session: explicit "why you coding in the background" after I launched a subagent for MR-5).
2. The operator wants me to own implementation decisions (substrate-reuse choices, naming, error handling shape, test coverage) personally rather than reviewing a subagent's interpretation after the fact.
3. Subagents drift from the project's conventions (the OMOIKANE-1113 Phase 2a launch revealed this risk would have been hidden behind a finished commit instead of caught mid-edit).
4. Token cost difference is minor relative to the trust + correctness cost.

**How to apply:**

- For Rust / SQL / Maud / Python / JS that gets committed: edit + commit + push in the foreground. Use Read/Edit/Write/Bash directly. Report progress in conversation text between edits so the operator sees the cadence.
- For multi-MR sequences: still ship each MR in the foreground. Use ScheduleWakeup for between-MR pacing (CI completion, deploy probes) but do the actual coding myself.
- **Subagents remain OK for:**
  - Read-only exploration (Explore agent) — e.g. mapping a codebase before drafting a plan.
  - Independent code review (code-reviewer agent) — bias-free second opinion.
  - Visual verification (Playwright / screenshot subagent) — orthogonal to my code path.
  - YouTrack / GitLab API bulk operations (e.g. filing 23 child issues) — mechanical work that I'd otherwise burn token cost on.
- **Subagents NOT OK for:** writing Rust modules, writing SQL migrations, writing Maud views, writing Python tests, writing the actual deliverable code. That's foreground only.

**Canonical incident:** 2026-06-02 session, OMOIKANE-1096 Phase 2a (MR-5 / OMOIKANE-1113). I launched a general-purpose subagent for the signal_ledger + 4 channel adapters + Art. 17 fan-out implementation (~6000 LOC). Operator called out: "why you coding in the background? always code in the foreground". Stopped the subagent, took the work in foreground.

Cross-ref: [[feedback-let-deploy-pipeline-finish-before-manual-recreate]] — same kind of operator visibility concern (don't act invisibly when the operator wants to see the cadence).

*Source: `memory/feedback_always_code_in_foreground.md`*

### feedback-always-netmiko-for-cisco

**ALWAYS use netmiko for Cisco. Never sshpass, expect, or raw `ssh`/paramiko command-channel.** Operator instruction, 2026-06-19, emphatic ("once and for all").

**Why:** non-netmiko approaches silently fail and waste cycles —
- Raw `ssh user@asa "show ..."` / `sshpass`: the ASA authenticates ("User X logged in") then **closes the command channel immediately** — it only services interactive sessions, so you get empty output.
- `expect`: **not installed** on nl-claude01 (`/usr/bin/expect` missing → "No such file or directory").
- netmiko (`device_type='cisco_asa'` / `'cisco_ios'`) handles login + `enable` + `terminal pager 0` + prompt detection correctly. It's the documented path (infrastructure.md references a `/tmp/netmiko-venv/` on grclaude01).

**How to apply** — ConnectHandler pattern (creds: `CISCO_ASA_PASSWORD` in `claude-gateway/.env`; user `operator`; legacy KEX/host-key algs needed):
```python
from netmiko import ConnectHandler
dev = {"device_type": "cisco_asa", "host": "10.0.181.X", "username": "operator",
       "password": PW, "secret": PW,   # enable secret = same login pw unless noted
       # legacy crypto for ASA 9.16: modern clients disable ssh-rsa + dh-group14-sha1
       "conn_timeout": 15}
c = ConnectHandler(**dev); c.enable()
print(c.send_command("show running-config interface"))
```
- **NL ASA** `nl-fw01` = 10.0.181.X (direct from nl-claude01 mgmt LAN).
- **GR ASA** `gr-fw01` mgmt = **`10.0.X.X`** (GR `inside_mgmt` VLAN 2; = the DNS A record). NOT 10.0.X.X (that was a wrong/stale value in infrastructure.md). Its SSH is filtered cross-site, so reach it **with ONE jump**: SSH to a GR host on the 10.0.X.X/24 subnet (`grclaude01` 10.0.X.X — has netmiko at `/tmp/netmiko-venv/bin/python3`; or `gr-pve01` 10.0.X.X) and run netmiko **locally there** against 10.0.X.X. Do NOT double-hop / port-forward from nl-claude01 (paramiko fails the SSH-banner read over the second hop). One jump is enough; both GR hosts have direct access to the ASA.
- IOS devices (nlrtr01 ISR4321, switches) → `device_type='cisco_ios'`.
- If netmiko isn't importable in the base python, create/use a venv (`pip install netmiko`) — do NOT fall back to expect/sshpass.

This is for **read-only `show`** evidence-gathering and config audits; any config change still goes through the normal change/approval flow.

*Source: `memory/feedback_always_netmiko_for_cisco.md`*

### feedback-anti-slop-means-empty-chip-is-valid

The omoikane.coach gate's chip strip renders `—` for any dimension whose underlying score is genuinely unknown. This is anti-slop — the alternative ("default to Mid" / "default to 50%") would mislead the user about whether the system actually has a basis for the number.

**Why:** Operator pushed on TNO-gate posting 2026-05-22: "why no seniority shape?" — implication being it should show *something*. My initial reflex was to ship more fallbacks (OMOIKANE-490 snippet-seniority detector; OMOIKANE-491 LLM extraction at posting_create; OMOIKANE-496 lazy extraction on gate render). The fallbacks landed real improvements (geography 0% → 100%, compensation `—` → 100%), but the seniority `—` remained — because the TNO body genuinely carries **zero** seniority signal. Both the title-keyword detector and the snippet-keyword detector returned None, AND the LLM extractor (a third independent attempt) wrote `seniority: null` to structured_json. Three independent signals all said "honestly no idea." Same outcome for value-alignment and growth-axes for any user whose `user_goals.growth_axes = {}` and whose coaching session hasn't populated `CoachingValue/Motivator/Quality` facts.

**How to apply:**
- When a chip shows `—`, the first instinct should NOT be "ship more fallbacks." First check whether the underlying signal is genuinely absent at all three levels: structured_json field, deterministic Phase 2 chain (title/snippet/known-city scan), RAG cache row.
- If all three say "no data" → the `—` is right. The fix is operator-side: add the data (declare growth axes, complete a coaching session, paste a posting that actually carries the signal).
- Consider a UX improvement: explanatory tooltip on `—` chips ("Add growth axes in /goals to unlock this score"). This converts "looks broken" into "user knows what to do." Operator-approved scope before shipping.
- Don't ever default seniority to "Mid", value-alignment to 50%, or growth-axes to anything. `seniority::detect_seniority` doc literally says this: "When there's no clear signal we return None rather than defaulting to Mid."

Related: [[feedback-never-block-request-on-external-llm]] (the LLM extractor is one of the three signals; even when blocking would have been worse UX, it was the right architectural call to let it run asynchronously).

*Source: `memory/feedback_anti_slop_means_empty_chip_is_valid.md`*

### feedback-autonomous-claude-p-loop-dispatch

## Pattern

For autonomous claude-code dispatch of loop-shaped work (extraction, iteration over a bounded set of units), use:

1. **Isolated worktree** off `origin/main` so the dispatch doesn't touch the operator's active branch:
   ```bash
   git worktree add /tmp/loop-wt-<name> --detach origin/main
   ```

2. **Extract just the PROMPT block** from the wrapper md file (the part inside triple-backticks under `## PROMPT`). Don't send the whole wrapper — the cheat-sheet section confuses the dispatched model.

3. **Background dispatch with stream-json**:
   ```bash
   export YT_TOKEN=...
   export GITLAB_TOKEN=...
   ( cd /tmp/loop-wt-<name> && \
     nohup claude --dangerously-skip-permissions -p "$(cat /tmp/<name>-prompt.txt)" \
       --output-format stream-json --verbose \
       > /tmp/loop-<name>.jsonl 2>&1 & )
   ```

4. **Optional safety-net driver** at `daemon/scripts/extraction-loop-driver.sh` — waits for the one-shot to exit, then re-invokes via `claude -r <session_id> -p "continue ..."` until DONE.

## Surprise: opus 4.7 self-iterates without `/loop`

When a PROMPT body describes a bounded loop (e.g., "process chapters 1-21, one per cycle"), opus 4.7 with `--dangerously-skip-permissions` will:

- Process **multiple cycles within a single response** without needing to be poked
- Decide for itself when to commit, push, and continue to the next unit
- Explicitly skip `ScheduleWakeup` polling for the same reason ("staying in-session is more efficient")

Observed 2026-05-19 (OMOIKANE-248 + -249, dispatch under MR !2010 + !2012, driver preserved under MR !2017):

| Dispatch | Units | One-shot covered | Driver did | JSONL size |
|---|---|---|---|---|
| Ousterhout extraction | 21 chapters / 36 rows | ~16 chapters | 5 more chapters | 1.17 MB |
| Drysdale extraction | 35 items / 35 rows | **all 35 in one response** | nothing | 1.53 MB |

For bounded extraction-shaped loops with ≤35 deterministic per-cycle units, the driver is often unnecessary. Keep it as the safety net for when context fills.

## Caveat: `yt-close-from-mr.sh` grammar

The model writing a MR description tends to use `Refs: OMOIKANE-NNN`. The `daemon/scripts/yt-close-from-mr.sh` helper requires `Closes/Resolves/Fixes OMOIKANE-NNN` shape to auto-close after merge. Either:

- (a) Add to loop prompts: "MR description first line MUST be `Closes OMOIKANE-NNN`"
- (b) Plan to close YT manually via `/api/commands` POST after merge

Without (a), the close step is manual. The driver script's MR (!2017) used grammar `Closes OMOIKANE-247` correctly because I wrote that MR myself — the issue is specifically with model-authored MR descriptions during autonomous dispatch.

## How to apply

When dispatching a new autonomous loop in future sessions:

1. Pre-set env vars (`YT_TOKEN`, `GITLAB_TOKEN`, `~/.config/omoikane-matrix/access-token`) before nohup
2. Each loop gets its own `/tmp/` worktree to avoid touching operator branches
3. JSONL stream is the monitoring contract — `jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="text") | .text'` extracts model text
4. Driver wrapper at `daemon/scripts/extraction-loop-driver.sh` is the safety net; add a new case branch per new loop type (the `get_last_n()` shape is loop-specific)
5. Process detection via `readlink /proc/<pid>/cwd` is how the driver knows when the one-shot is done

## Cross-references

- `daemon/scripts/extract-ousterhout-invariants.md` + `extract-drysdale-invariants.md` — the loop PROMPT files (under !2012)
- `daemon/scripts/extraction-loop-driver.sh` — the wrapper (under !2017)
- 2026-05-19 dispatches: !2014 (Ousterhout, merged `c8735d669212`) + !2015 (Drysdale, merged `3653fb6e7c2d`)
- The general "loops survive a model swap if they're mechanized as checks, not prose" thesis: [[feedback-omoikane-p1c-env-var-tunables]] (the Karpathy-shape conversation that started this whole arc)

*Source: `memory/feedback_autonomous_claude_p_loop_dispatch.md`*

### feedback-cache-only-request-path-pattern

When a request handler does serial HTTP fan-out (KvK + LLM + 3rd
party APIs) to enrich a view, refactor to **cache-only on the
request path + background tokio::spawn**.

**Why:** Caught 2026-05-28/29 across two independent handler
chains:

- `/postings/discover`: 90s → 1.3s ([[omoikane-discover-perf-chain-20260528]])
- `/company-info/:kind/:id` modal: 10-15s → sub-1s ([[omoikane-modal-perf-chain-20260529]])

Both started with "budget" approaches (45s → 10s → 2s) that
incrementally lowered the blocking ceiling. Each "budget cut"
deploy still hit the operator's complaint because cold-cache
requests blocked the full budget AND shipped partial / skeletal
content. The architecturally correct fix was to **never block the
request on a live HTTP round-trip at all**.

**Recipe:**

```rust
async fn build_view(state, …) -> ViewData {
    let cached = load_cache_row(...).await;  // single DB query

    let blocking = env("OMOIKANE_<HANDLER>_BLOCKING") in (true|1|yes|on);
    if !blocking {
        // === Default: cache-only path ===
        let mut data = ViewData::default();
        if let Some(c) = &cached {
            // Hydrate regardless of staleness; live refresh updates
            // cache for next view.
            data.field_a = c.field_a.clone();
            data.field_b = c.field_b.clone();
            ...
        }

        // DB-only enrichments (each < 50ms; keep blocking)
        data.identifiers = sqlx::query(...).fetch...().await?;
        data.badges = badges::load(...).await?;

        // Pure derivations
        data.derived = derive(&data.cached_field);

        // Spawn live refresh; cache will be warm for next view.
        let state_bg = state.clone();
        tokio::spawn(async move {
            refresh_live_enrichments(state_bg, ...).await;
        });

        return data;
    }

    // === Legacy blocking path (kill-switch ON only) ===
    // Original code unchanged — emergency rollback target.
    ...
}
```

**Key invariants:**

- **Default = spawned.** Operator opts INTO blocking via env.
- **Cache-only handles stale gracefully** — render anyway; freshness
  comes from background refresh tick.
- **First-ever view** of an entity (no cache row) renders a skeleton
  with DB-only enrichments. Re-view ~5-15s later = full content.
- **Background helper writes back to the same cache table.** No
  schema change required.
- **All HTTP that's NOT essential for the immediate render
  goes into the background.** Even sub-second HTTPs add up.

**When NOT to use:**

- If freshness is a correctness invariant (financial transactions,
  pricing, auth) — cache staleness is unacceptable.
- If the HTTP call is the entire point of the request (image
  proxying, raw API passthrough).

**Symptoms that the pattern is overdue:**

- Operator reports "X seconds" where X > 1 on cold cache.
- Handler has 3+ awaited HTTP calls under a `tokio::time::timeout`.
- Most successful renders use cached data; live HTTP enrichments
  silently fail under partial-budget pressure.
- Lowering the timeout budget twice didn't fix it.

Canonical incidents:
- [[omoikane-discover-perf-chain-20260528]]: discover handler
- [[omoikane-modal-perf-chain-20260529]]: company-info modal

Sister: [[feedback-instrument-before-the-third-perf-mr]] for
choosing WHICH path to refactor.

*Source: `memory/feedback_cache_only_request_path_pattern.md`*

### feedback-check-working-case-before-writing-refresh-code

# Feedback: check the working case before writing refresh code

**Rule:** When a UI bug looks like "X stays stuck on stale value but Y renders correctly", trace the code path Y takes through the refresh function first. The pattern that makes Y work is almost always the right shape to extend for X — usually you're missing one selector, not a whole new code block.

**Why:** I hit this exact trap 2026-05-13. `nl-dmz01` rendered `?/?` grey and never updated, while `gr-dmz01` rendered `24/24` orange correctly. Instead of reading `updateData()` to see what makes gr-dmz01 work, I added an 18-line block at the wrong indent level that called a non-existent function `nColor` (I had skimmed the existing code and hallucinated the name from `nStroke`). The `ReferenceError` killed `updateData()` mid-execution, broke EVERY auto-refresh on the page, and pushed straight to main. Operator caught it the next time they loaded the page. The actual fix was a 5-line block inside the existing refresh pattern (next to `nodeEl.select('circle').attr('stroke', nStroke); glowEl.attr('fill', nStroke); linkLbl.text(...)`) that added `text.mg-nsub` to the refresh — the one selector the existing pattern was missing.

**How to apply:**
1. Find the canonical refresh function (here `updateData()` at `kyriakos/static/js/mesh-graph.js:1120`).
2. **Read it end-to-end** before adding code — don't grep for the broken case, grep for the *working* case.
3. Identify which selectors/attributes the existing pattern already covers.
4. Add only the missing selector to the existing block — same scope, same line of code in style.
5. Never reference a helper function name unless you've grep-confirmed it exists in the same closure (`function nColor` returned 0 matches; the real name was `nStroke`).
6. Run Playwright with `await page.evaluate(() => window.__meshGraph.update(api))` to force-fire the refresh function *before* committing — this would have surfaced the `ReferenceError` in 5 seconds.

**Related signals to watch for:**
- A `_compound_status()` / `updateData()` / `refreshXYZ()` function that's silent on the symptom selector → add to that, don't fork.
- "Only X is broken" usually = "X has one attribute the existing refresh doesn't cover", not "X needs its own refresh path".

Caught: 2026-05-13 during the [[dmz-container-count-zero-baked-20260513]] fix chain. Bad commit `kyriakos:f3dacee` (ReferenceError), corrected `kyriakos:7a9cc2a`.

*Source: `memory/feedback_check_working_case_before_writing_refresh_code.md`*

### feedback-clippy-strict-flags-for-omoikane-daemon

## The rule

When working in `/app/websites/omoikane.coach/daemon`, the pre-push clippy command is **literally one command, no flag invention**:

```bash
bash scripts/ci-clippy-gate.sh
```

That is the EXACT command CI runs in `clippy_gate`. Verified by reading `.gitlab-ci.yml` (`clippy_gate: ... script: - cd ..; bash scripts/ci-clippy-gate.sh`).

## Why the hand-rolled flag list is wrong

The script itself just runs `cargo clippy --workspace --all-targets --locked -- -D warnings`. The actual deny list — `cast_precision_loss`, `cast_possible_truncation`, `cast_sign_loss`, `cast_possible_wrap`, `cast_lossless`, `as_conversions`, `explicit_iter_loop`, `explicit_into_iter_loop`, `unwrap_used`, `expect_used`, `panic`, `unreachable`, `unimplemented`, `todo`, `indexing_slicing`, `integer_division`, `missing_panics_doc`, `missing_errors_doc`, `redundant_pub_crate`, and ~50 more — lives in **`app/Cargo.toml [lints.clippy]`**.

That means:

- `cargo clippy --workspace --all-targets --locked -- -D warnings` (what most other Rust projects expect) reads the lints from Cargo.toml AND passes if all deny-level lints are clean.
- Adding `-D clippy::as_conversions -D clippy::cast_lossless` to the CLI is **redundant + incomplete** — those lints are already denied via Cargo.toml, and only adding TWO of the ~50 strict CI lints to the CLI gives false confidence.

**Pre-push command IS `bash scripts/ci-clippy-gate.sh`. Period.**

## What CI denies that surprises people

Real failures from MR-8b !2788 pipeline 35548 (compile-blocking on numerical code):

- `clippy::cast_precision_loss` — `usize as f64` is a deny (because >2^53 usize values lose precision). Triggers on rank counters, batch sizes, any `i64 as f64` math.
- `clippy::cast_possible_truncation` — `f64 as usize` triggers.
- `clippy::cast_possible_wrap` — `usize as i64` triggers.
- `clippy::cast_sign_loss` — `i64 as u64` triggers.
- `clippy::as_conversions` — meta-lint covering all `as` keyword casts.
- `clippy::cast_lossless` — use `T::from(x)` when infallible.
- `clippy::explicit_iter_loop` — `for x in vec.iter()` → `for x in &vec`.
- `clippy::explicit_into_iter_loop` — same shape for `.into_iter()`.
- `clippy::unwrap_used` / `expect_used` / `panic` / `unreachable` / `unimplemented` / `todo` — all deny in production code (test code allowed).
- `clippy::indexing_slicing` — `v[i]` → use `.get(i)`.
- `clippy::integer_division` — `a / b` for integers → use `div_ceil` or document the truncation.
- `clippy::missing_panics_doc` / `missing_errors_doc` — public fns must document panics/errors.

## Two correct approaches when writing math code

1. **Just run the script before pushing** (1 line):
   ```bash
   bash scripts/ci-clippy-gate.sh
   ```

2. **For pure-numerical files, add the per-file allow block** mirroring `drift_canary.rs` + `non_inferiority_test.rs` + `calibration_optimiser.rs` (the peer files that ALREADY have this pattern — read them, copy them):
   ```rust
   #![allow(
       clippy::cast_precision_loss,
       clippy::cast_possible_truncation,
       clippy::cast_sign_loss,
       clippy::cast_possible_wrap,
       clippy::as_conversions,
       clippy::explicit_iter_loop
   )]
   ```
   Document WHY in a comment above (`sample sizes far below 2^53` etc).

## Canonical incidents

- 2026-06-02 OMOIKANE-1117 MR-8b !2788 pipeline 35548 — `benjamini_hochberg.rs` + `fairness_audit_disaggregated.rs` failed `clippy_gate` on 24 + ~15 cast lints. Wasted ~9min CI cycle. Operator called it out: "you are doing the same damn mistake with every damn CI."
- 2026-06-02 OMOIKANE-755 !2771 pipeline 35409 — `platt_fitter.rs` failed `clippy_gate`. ~5min wasted.
- Earlier OMOIKANE-1068 dashboard `cast_possible_truncation` (same family).

**This is now the 4th+ time.** The fix is to **read this memory** at the start of any omoikane.coach/daemon Rust work AND to write the per-file allow block at file creation time (NOT after a failed CI run).

## Cross-refs

- [[feedback-clippy-local-must-match-ci-workspace-all-targets]] — covers the `--workspace --all-targets` invocation pattern (different angle: target breadth, not lint breadth).
- Peer files with the canonical allow block: `app/src/methodology_registry/drift_canary.rs`, `non_inferiority_test.rs`, `calibration_optimiser.rs`, `conformal_predictor.rs`, `advisory_theta_lane.rs`.

*Source: `memory/feedback_clippy_strict_flags_for_omoikane_daemon.md`*

### feedback-company-enrich-search-chain-diagnostic

When `company_info_prewarm_worker` shows `llm_enrichment` stalled at near-zero throughput despite candidates with `llm_enrichment_json IS NULL`, the **wrong** instinct is "Brave Search is rate-limiting" — that was the historical pre-2026-05-24 baseline, not the current state.

**Why:** OMOIKANE-491 backfill burned the Brave Lite-tier 20k-mo quota; on 2026-05-24 the default search provider was flipped from `brave` to `searxng` (`app/src/badges/company_enrich_llm.rs:177-187`). Most deployments since then carry `SEARXNG_URL=...` but **no** `BRAVE_SEARCH_API_KEY`, so:

1. Primary = SearXNG sidecar fans out to Google/Bing/DDG.
2. Under prewarm concurrency (N≥4), upstream engines CAPTCHA-wall the sidecar → log line `WARN search: provider failed provider="searxng" error_kind="all_engines_blocked" error="all backend engines blocked (CAPTCHA / rate-limit / timeout)"`.
3. Secondary = Brave is "skipped (not configured)" → `DEBUG search: provider skipped (not configured) provider="brave"`.
4. `search_company()` returns `Ok(Vec::new())` → `enrich()` returns `Ok(None)` → no `llm_enrichment_fetched_at` write → row re-picked next tick → loop, no progress.

**How to apply:** Before diagnosing this class of bug, in this order:

1. `docker exec omoikane-daemon printenv | grep -iE 'BRAVE|SEARXNG|SEARCH_PRIMARY'` — confirm which providers are even configured.
2. `docker logs --since 30m omoikane-daemon | grep -oE 'error_kind="[a-z_]+"' | sort | uniq -c` — tally the actual error kinds. `all_engines_blocked` (SearXNG) vs `429` (Brave) are completely different failures.
3. Look at the `provider="..."` field in each WARN line — that tells you which leg of the chain actually fired, not which one you assumed.

**Fix (resolved 2026-05-29 by OMOIKANE-902 operational config):** Two env vars need to be set, NOT one. Two distinct code paths use different env vars:

- `OMOIKANE_SEARCH_PROVIDER_ORDER=brave,searxng` → unified OMOIKANE-601 module (`crate::search::companies::run`). Read at `app/src/search/mod.rs:295-316` `order_providers()`. This is the main LLM-enrichment search path used by `company_info_prewarm_worker`.
- `OMOIKANE_COMPANY_INFO_SEARCH_PRIMARY=brave` → legacy `company_enrich_llm::search_via_active_provider` chain (at lines 183-204). Used by `company_info_prewarm_worker::discover_website_via_search` for ~63 bucket-A companies with no Brandfetch/OpenKvK website hint.

Both env vars MUST be set together on the dmz hosts in `/srv/omoikane-daemon/secrets/shared.env` along with `BRAVE_SEARCH_API_KEY=...`. After editing, deploy via `docker compose up -d --force-recreate app` (NOT `restart` — see [[feedback-docker-compose-env-file-force-recreate]]).

**Live verification recipe:** `docker logs --since 5m omoikane-daemon | grep -E 'provider=.*label="company:bare"' | head -5` should show `provider="brave"` lines WITHOUT preceding `provider="searxng".*all_engines_blocked` lines. If you see SearXNG firing first, the env var wasn't set or wasn't picked up.

**My earlier "doc-vs-impl drift" guess was wrong** — I read the `default_chain()` function body but missed that `ProviderChain::new()` wraps it in `order_providers()` which DOES honour the env var. Always read the constructor chain end-to-end before concluding a function doesn't read what its doc-comment claims.

Related: [[omoikane-898-prewarm-llm-freshness-gate]] exposed this latent bottleneck at N=8. Pre-898 the prewarm was sequential + had no freshness gate, so each candidate was re-attempted infrequently — the silent no-op was hidden by lower attempt-rate.

**Caught 2026-05-29** mid-session when llm_enrichment stuck at 1/5min despite 45 NULL candidates. Post-fix: ~6 writes/min sustained (30× improvement). Operator-provided Brave key showed 50 QPS rate limit (above the documented 20 QPS Lite tier — likely Pro tier).

*Source: `memory/feedback_company_enrich_search_chain_diagnostic.md`*

### feedback-docker-compose-env-file-force-recreate

`docker compose restart <service>` does NOT pick up changes to files
referenced in `env_file:`. The restarted container keeps its original
runtime env from container creation. You must use:

```
docker compose up -d --force-recreate <service>
```

…to make the daemon read the updated `shared.env` / `.env`.

**Why:** `env_file` is materialised into the container's env at
`docker create` time. `restart` is a `SIGTERM` + start of the SAME
container, so the env stays frozen at creation. `up -d --force-recreate`
tears down + creates a new container with fresh env.

**How to apply:** Whenever you change a file referenced by `env_file:`
on a deployed compose project:

1. `git pull` (or scp the new env file)
2. `docker compose up -d --force-recreate <service>` — NOT `restart`
3. Verify in-container env actually reflects the change:
   `docker compose exec <service> printenv | grep KEY_NAME`

This bites you on every "added a new env var" change. The wrong
sequence (compose restart) silently gives you the old env, then the
next action depending on the new var (provider sync, secret decrypt,
API call) fails confusingly.

**Caught 2026-05-29** on omoikane.coach daemon:
`/srv/omoikane-daemon/secrets/shared.env` had FERNET_KEY and
LITELLM_MASTER_KEY but `/srv/omoikane-daemon/app/.env` did not. SSH
hot-fix appended them, but `docker compose restart` didn't reload —
took a second pass with `--force-recreate` to fix. Cascaded into
OMOIKANE-879 (boot reconciler) because the env-file drift had been
hiding for an unknown duration.

Related: [[omoikane-879-litellm-self-healing-20260529]].

*Source: `memory/feedback_docker_compose_env_file_force_recreate.md`*

### feedback-docker-compose-restart-policy

When deploying or auditing a docker-compose stack on any PVE LXC, ensure **every** service has an explicit `restart: unless-stopped` (or `restart: always`). Sidecars often get the policy and the main service often doesn't — particularly when starting from an upstream project's example compose.

**Why:** Caught 2026-05-18 on `nllitellm01`. The litellm proxy was deployed Feb 2025 from upstream `berriai/litellm`'s example docker-compose.yml, which had `restart: always` on the `db` and `prometheus` sidecars but **no policy at all on the `litellm` service itself**. When the operator did a routine `docker compose down` on 2025-02-15 22:10 UTC, db + prometheus came back at the next host reboot via their restart policies; litellm did not. It stayed dead for **15 months** completely unused, only surfacing now because the operator wanted to wire Codestral into laptop Claude Code. See [[litellm01-codestral-proxy-20260518]] for the full incident.

This is a class-of-bug, not a one-off — any time you adopt an upstream example compose, the author may have written restart policies on the bits they considered "infrastructure" (db, cache) but not on the main app, assuming the operator would run it foreground. We don't run anything foreground in production.

**How to apply:**
- When pulling an upstream `docker-compose.yml` example, audit every `services:` block for an explicit `restart:` line BEFORE first `docker compose up -d`. If any are missing, add `restart: unless-stopped`.
- When triaging a "service X mysteriously not running" report on any LXC, check `docker inspect <container> --format '{{.HostConfig.RestartPolicy.Name}}'` — if it returns `no`, that's why it didn't come back at the last host reboot. Confirm with the host's `uptime` and `docker ps -a --format '{{.Names}} {{.Status}}'`.
- Default to `restart: unless-stopped` (not `restart: always`) so that an operator-issued `docker compose stop` is respected across reboots — useful during planned outages.
- Same audit applies to any host running docker-compose, not just PVE LXCs.
- The upstream LiteLLM example still has this bug as of 2026-05; ours is now fixed but if anyone clones the same example for another deployment (or another service from a similar upstream pattern), they'll hit it.

*Source: `memory/feedback_docker_compose_restart_policy.md`*

### feedback-freeipa-named-no-manual-ops

In any FreeIPA setup (`nlfreeipa01`, `grfreeipa01`, future replicas), do **NOT** operate `named` directly:

- No `rndc flush`, `rndc flushname`, `rndc reload`.
- No `systemctl start|stop|restart|reload named*`.
- No editing `/etc/named.conf`, `/etc/named/*.conf`, or `/var/named/*`.
- No `nsupdate` to mutate IPA-managed zones.

**Why:** FreeIPA stores DNS zones in LDAP and reads them via `bind-dyndb-ldap`. Manual `rndc` operations or config edits bypass the LDAP source of truth, drift named's in-memory state vs LDAP, and break the next `ipa dns*` op or replica re-sync. Operator was explicit 2026-05-16 after I cleared a stale-NS cached SERVFAIL on `nlfreeipa01` via `rndc flushname extreme-agri.gr` — the flush *worked* but is the wrong shape.

**How to apply:**

- **DNS zone / record changes** → `ipa dnszone-*`, `ipa dnsrecord-*`, `ipa dnsconfig-*`, `ipa dnsforwardzone-*`.
- **Service lifecycle** (start / stop / restart) → `ipactl start|stop|restart [named]`. This orchestrates LDAP / krb5 / kdc / etc. dependencies in the correct order; bare `systemctl` skips that ordering.
- **Health check** → `ipactl status`.
- **Read-only diagnostic is fine** → `dig`, `ipa dns-show-*`, `rndc status` (no mutation), `klist -kt /etc/named.keytab`, `named-checkconf -z` (dry-parse), `journalctl -u named`, `rndc dumpdb -cache` (read-only dump).
- **Cache flushing inside FreeIPA-managed `named`** has *no* documented `ipa`-API equivalent. **ASK the operator** for the approved procedure (probably `ipactl restart named` if anything; `rndc flushname` is off-limits even though it works one-shot).
- **If the cache issue is DOWNSTREAM of FreeIPA** (Pi-hole, client resolvers, etc.), those are not FreeIPA-managed — flush them directly.

Same "go through the API, not the storage" shape as [[seaweedfs_filer_sync_stale_checkpoint_20260505]] and [[apiserver_ctrl01_balloon_chronic_restart_fixed_20260515]] (PVE `qm set --balloon 0` is `[PENDING]` until a reboot routes through the orchestrated path).

*Source: `memory/feedback_freeipa_named_no_manual_ops.md`*

### feedback-goal-rationale-prom-histogram-empty

**Status: RESOLVED** 2026-05-25 15:25Z via MR !2449 (closes OMOIKANE-696 follow-up, written in the same epic OMOIKANE-693).

## What was the issue

After MR !2425 (OMOIKANE-696) merged + deployed, `curl http://localhost:8459/metrics | grep omoikane_goal_rationale` returned **zero matches** — no HELP, no TYPE, no buckets. The operator's /goals SLO panel would have read "no data" between every daemon restart and first user click. Visually indistinguishable from a broken metric.

## Root cause

The Rust `metrics-exporter-prometheus` crate (v0.23) **does NOT emit HELP/TYPE/series for a histogram until at least one sample is recorded.** `describe_histogram!()` only registers the description string; the series shape never appears on `/metrics` until something calls `histogram!(...).record(...)`.

Verified by inspection: `omoikane_ingestion_batch_duration_seconds` (sister histogram) DID appear on `/metrics` because the ingestion worker had fired post-restart. `omoikane_goal_rationale_duration_seconds` did NOT appear because no /goals click had triggered the rationale-generation path.

**This is a Prometheus-exporter idiom, not a code bug** — but it's UX-bad enough that operators see fresh dashboards reading "no data" and assume something is broken.

## Fix (MR !2449)

Added at end of `app/src/metrics.rs::register_descriptions()`:

```rust
histogram!(
    "omoikane_goal_rationale_duration_seconds",
    "surface" => "boot",
    "dim"     => "init",
    "outcome" => "boot",
).record(0.0_f64);
```

Plus runbook update in `docs/runbooks/rationale-latency.md` — all PromQL examples filter `outcome!="boot"` alongside the existing `outcome!="cache_hit"` filter.

New unit test: `goal_rationale_boot_emit_is_idempotent_and_chainable` (51/51 metrics::tests PASS).

## Live verification (2026-05-25 15:25:52Z)

Container restart 15:24:42Z image sha256:c11df72d. `/metrics` now carries 11 series lines:

```
# HELP omoikane_goal_rationale_duration_seconds Per-dim /goals rationale LLM dispatch wall-clock duration. ...
# TYPE omoikane_goal_rationale_duration_seconds summary
omoikane_goal_rationale_duration_seconds{surface="boot",dim="init",outcome="boot",quantile="0"} 0
... (6 more quantiles)
omoikane_goal_rationale_duration_seconds_sum{surface="boot",dim="init",outcome="boot"} 0
omoikane_goal_rationale_duration_seconds_count{surface="boot",dim="init",outcome="boot"} 1
```

## Lesson for future Rust + Prometheus work

When adding a `metrics::histogram!()` that's emitted along a rare codepath (anything user-triggered, like a modal handler), **pair the `describe_histogram!` with a 0.0s sentinel `.record()` at startup** so the series appears on `/metrics` without waiting for first user interaction. Use a sentinel label like `outcome="boot"` or `surface="boot"` and document the filter in the runbook.

Same caveat applies to counters with rarely-fired labels (`metrics-exporter-prometheus` may show the counter at 0 but not all label combinations — `cache_hit` / `discarded` / `empty_response` outcomes never appear until they actually happen).

## Related

- Parent epic: [[omoikane-693-goals-excellence-epic-20260525]]
- Predecessor MR: !2425 (OMOIKANE-696 latency budget + Prometheus instrumentation)
- Resolution MR: !2449 (OMOIKANE-696 follow-up boot-emit)

*Source: `memory/feedback_goal_rationale_prom_histogram_empty.md`*

### feedback-html-scraper-first-match-fragile

When scraping HTML in an n8n Code node, never trust "first `<img>`" / "first `<a>`" / "first `<meta>`" — source pages get search widgets, header banners, ad slots, JS-template literals (`src="'+e.thumb+'"`), schema.org JSON-LD blocks, etc, added upstream over time, and your regex will silently start matching them instead of the article body.

**Why:** the failure mode is silent. The regex matches *something* and returns a value (often empty string between mismatched quote types). The downstream filter (`item.json.imageUrl !== null`) treats empty/garbage as a present-but-falsy value, zeroes the item array, all downstream nodes no-op, n8n reports `status: success`. No alert ever fires. The only way to notice is operator-side ("why hasn't this posted in 9 days?").

**How to apply:** every HTML-scrape regex in this estate's n8n workflows MUST:

1. Whitelist the expected value shape in the capture group itself:
   - For images on withelli.com: `src=["'](\/images\/posts\/[^"']+|https:\/\/withelli\.com\/[^"']+)["']`
   - For canonical article URLs: `href=["'](https:\/\/<host>\/posts\/[^"']+)["']`
2. Prefer parsing `<meta property="og:image" …>` / `<meta property="og:url" …>` from `<head>` over scraping body — Hugo, Jekyll, Next.js, Astro all emit these and they're version-stable.
3. If you DO use a generic-first-match regex, pair it with a sanity check at the end: `if (!url || !url.startsWith('http')) throw new Error('image extraction returned suspicious URL: ' + url)` — converts silent halt into a loud error that surfaces in n8n's execution list.

**Canonical incident:** [[autoposter-silent-halt-search-widget-20260527]] — RSS2Postiz workflow silently stopped publishing for 9 days after withelli.com added a search widget whose JS-template `<img src="'+e.thumb+'">` was emitted before the article image. Same regex would have caught the issue at fix-time if it had whitelisted `/images/posts/…` in the capture group.

*Source: `memory/feedback_html_scraper_first_match_fragile.md`*

### feedback-instrument-before-the-third-perf-mr

After two perf MRs that don't fully close a latency gap, the **next**
MR must be observability, not another guess at a fix.

**Why:** Caught 2026-05-28 on the omoikane discover chain. I shipped 3
back-to-back perf MRs (-820 Tantivy, -824 fanout-spawn, -826 parallelize)
that each took the avg from 90-120s → 27.5s → 5.5s → 4.65s. Each landed
based on educated reading of the handler code. After -826, I was about
to ship a 4th guess (-826 parallelization didn't help on the test query
because the per-row scoring loop was a no-op — user's profile_nodes was
empty). The operator pushed me to instrument first.

OMOIKANE-827 added per-phase `omoikane_discover_phase_duration_ms{phase}`
around every `.await`. **One** real measurement showed `cache_lookup` =
1859 ms = 76% of post-Tantivy time. -830 was a one-line gate
(`if !cache_hit && ...`) and brought the avg to ~1.3s — the actual goal.

**How to apply:**

- If 2 perf MRs in a row don't drop p50 by ≥50% of the remaining gap,
  the next MR is instrumentation. No exceptions.
- Wrap every `.await` (and any obvious sync-CPU block) on the request
  path with `Instant::now()` + a Prom histogram labelled by phase.
- Boot-emit a 0.0 sample per phase (per
  [[feedback-goal-rationale-prom-histogram-empty]]) so the panel is
  populated from second 0.
- Use `record(0.0)` boot-emit + `count` to detect whether a phase
  actually ran (count=1 means boot-only, count=N+1 means N real runs).
- After one real request post-deploy, the phase with the largest sum is
  the bottleneck — the next perf MR is targeted at exactly that.
- ~12 phase labels with low-cardinality static strings is fine. Don't
  label by query / user / tenant — cardinality will explode and break
  Prometheus.

**Cost:** observability MRs are usually <150 LOC and ship clean (no
behavioural change). The cost of one extra MR is dwarfed by the cost
of shipping 2-3 wrong-guess perf MRs.

**Symptoms that the instrumentation MR is overdue:**

- Two consecutive perf MRs each "moved the needle a bit" but neither
  hit the target.
- The reasoning for the next MR is *"the X loop must be slow because
  N is big"* — without a measurement.
- The handler has >5 awaits between the entry point and the response.
- You can list 3+ "likely suspects" with no way to choose between them.

Canonical incidents:
- [[omoikane-discover-perf-chain-20260528]] — full 6-MR chain with the
  pivot.
- [[omoikane-820-tantivy-discover-index-20260527]] — MR #1 in the chain,
  context.

*Source: `memory/feedback_instrument_before_the_third_perf_mr.md`*

### feedback-litellm-self-heal-on-boot

When a daemon stores API keys at rest in its own DB AND ALSO pushes those
keys to a separate registration system (LiteLLM `/model/new`, a gateway
router, a secret-manager scope), boot-time reconciliation is mandatory.

**Why:** The save-handler-pushes-to-registration pattern is racy whenever
the registration system requires env config (a master key, a base URL)
that may not be set at save-time. The operator's mental model is
"I saved the key, the daemon has it" — but if the env was unset when
Save ran, the daemon stored the key without registering it. Restart
later doesn't fix it. Next dispatch returns a confusing error
("Invalid model name", "401 unauthorized", "scope not found") that the
operator can't trace to the missing env.

This actually happened on 2026-05-29 (OMOIKANE-879): operator saved a
DeepSeek API key BEFORE `LITELLM_MASTER_KEY` was wired into
`docker-compose.yml`'s `env_file`. The save-handler's `litellm_sync_model`
call silently skipped on the missing env var. After the operator added the
env to compose + force-recreated, the key was still not registered with
LiteLLM. Every dispatch returned `400 Invalid model name passed in model`.

**How to apply:** For any daemon-stores-key-then-pushes-to-X pattern:

1. **Boot reconciler** as `tokio::spawn` fire-and-forget — walk every
   stored credential, push each to the registration system. Idempotent
   because the registration system already handles "already exists".

2. **Dispatch auto-retry** — match the specific failure-signature
   (NOT a broad catch-all that would amplify storms), then re-push +
   retry exactly once.

3. **Operator-facing health page** — surface which env vars are present
   (boolean, no leak) + per-credential last-sync state.

4. **Per-credential outcome columns** in the storage table:
   `last_<system>_sync_at` + `last_<system>_sync_outcome` +
   `last_<system>_sync_<artifact>`. So `/admin/<system>/health` can show
   "stored 2 days ago, never registered with downstream" in red.

5. **Dashboard-locked outcome strings**: `ok`, `failed`,
   `skipped_no_master_key`, `skipped_no_credential`, `skipped_decrypt_failed`,
   etc. Drift-lock the literals via source-text greps so a future rename
   doesn't silently break Grafana.

Save the outcome via a Prometheus counter with an `outcome` label so
alerting can fire on `outcome="failed"` or `outcome="skipped_no_*"`.

Related incident: [[omoikane-879-litellm-self-healing-20260529]].
Related pattern: [[feedback-docker-compose-env-file-force-recreate]] —
the env-file drift that triggered this incident.

*Source: `memory/feedback_litellm_self_heal_on_boot.md`*

### feedback-mesh-graph-cache-buster

# mesh-graph.js cache-buster must move when JS behaviour changes

**Rule:** Any behavioural change to
`websites/papadopoulos.tech/kyriakos/static/js/mesh-graph.js` must be paired
with a bump of the cache-buster suffix in
`websites/papadopoulos.tech/kyriakos/layouts/shortcodes/mesh-health.html`:

```html
<script src="/js/mesh-graph.js?v=N"></script>   →   ?v=N+1
```

**Why:** Browsers cache `/js/mesh-graph.js?v=N` by full URL. After a Hugo
rebuild + dmz redeploy, the file at that URL has new content, but cached
clients keep using the old response until the URL changes. Without bumping
`?v=`:

- Incognito / first-visit users see the new behaviour
- Returning operators see the OLD behaviour and conclude "nothing changed"

This bit us 2026-05-16: after the first layout patch deployed, the operator
loaded the page in their normal browser, saw no change, and reported
"nothing changed". The deploy was actually fine — the deployed JS had the
patch — but their browser had `?v=39` cached. Bumping to `?v=40` made the
patch visible.

**How to apply:** in the same commit as the mesh-graph.js change, edit
mesh-health.html and bump the version number. Don't rely on operators to
hard-refresh.

**Doesn't apply to:** pure CSS changes, Hugo template changes, data file
changes — only when JS behaviour at the `/js/mesh-graph.js` URL changes.

Same rule applies to other versioned JS includes in the same template:
`chaos.js`, `service-health.js`, `auto-refresh.js`. Check the script tag in
`mesh-health.html` for the file you're editing.

See also: [[status-diagram-upstream-render-gaps-20260516]].

*Source: `memory/feedback_mesh_graph_cache_buster.md`*

### feedback-mesh-graph-updatedata-key-shape

# updateData(fullData) must accept BOTH camelCase + snake_case keys

**Rule:** Any code added to `mesh-graph.js`'s `function updateData(fullData) { ... }` that reads new keys from `fullData` must accept both:

- **camelCase** — Hugo template `layouts/shortcodes/mesh-health.html:56` builds `__meshData` as:
  ```
  $graphData := dict "sites" $stats.sites "bgp" $stats.public_bgp
                     "dmzNodes" $stats.dmz_nodes "latencyMatrix" $stats.latency_matrix ...
  ```
  Used only at IIFE startup for the initial render.

- **snake_case** — `auto-refresh.js` polls `/api/mesh-stats` every 30 s and calls:
  ```js
  fetch(MESH_URL).then(r => r.json()).then(fullData => {
    window.__meshGraph.update(fullData);
  });
  ```
  `fullData` is the **raw n8n payload**, keys are `public_bgp`, `dmz_nodes`, `latency_matrix`, etc.

The existing `updateData` body has been adjusted over time to accept snake_case (`fullData.dmz_nodes`, `fullData.latency_matrix || fullData.latencyMatrix`). Anything new must do the same. Pattern:

```js
var newBgp = (fullData && (fullData.public_bgp || fullData.bgp)) || {};
var newDmz = fullData.dmz_nodes || fullData.dmzNodes || [];
var newLatency = fullData.latency_matrix || fullData.latencyMatrix || {};
```

**Why this matters:** the initial render works fine (camelCase). The bug only manifests **30 s later**, when auto-refresh fires the first tick. Page-load screenshots and short Playwright tests miss it entirely.

**Caught 2026-05-17** on the v=42 deploy of the BGP-layer visibility batch. updateData() read `fullData.bgp` only → first auto-refresh tick saw `undefined.upstreams || []` → flagged every Layer-2 node `withdrawn=true` → both iFog and Terrahost flipped to red WITHDRAWN. Operator hit the bug within minutes of deploy; my Playwright test had captured at t=3s and missed it. Fixed in v=43 (commit `221231c`).

**Mandatory test:** the regression test `visual-audit/tests/status-autorefresh-regression.spec.js` explicitly calls `window.__meshGraph.update(rawApiPayload)` with the actual `/api/mesh-stats` response. Any future updateData refactor that introduces a key-shape mismatch fails this test before it ships. Same pattern: load page → capture state → fetch raw API → call update() → re-capture → assert nothing degraded.

**Don't trust** a page-load screenshot for `updateData()` correctness. The function only runs on auto-refresh, so the first page load doesn't exercise it.

See also: [[feedback-mesh-graph-cache-buster]], [[status-diagram-upstream-render-gaps-20260516]].

*Source: `memory/feedback_mesh_graph_updatedata_key_shape.md`*

### feedback-migration-filename-hhmmss

When creating a new SQL migration in `omoikane.coach/daemon/app/migrations/`, the filename MUST use the actual current HHMMSS timestamp, not a zero-suffixed placeholder.

**Why:** Operator-stated rule (2026-05-26). The migrations directory is the ordered audit trail of schema changes; `000000` and `000100` suffixes look like manual placeholders and break the chronological grep. Multiple migrations in the same session must each get distinct HHMMSS values so the ordering is deterministic.

**How to apply:** Before writing a migration file, derive the timestamp from `date +%Y%m%d%H%M%S` (or equivalent). Pattern: `YYYYMMDDHHMMSS_short_slug.sql`. Example: `20260526011152_methodology_seed_gate_a_salary.sql`.

**Forbidden patterns** (caught 2026-05-26):
- `YYYYMMDD000000_*.sql` — midnight placeholder
- `YYYYMMDD000100_*.sql` — sequential placeholder
- Reusing the same HHMMSS across two migrations in the same day
- `YYYYMMDD120000_*.sql` if the actual creation time was 03:47

**Correct pattern:** snapshot the system time when creating the file. Bash one-liner: `printf '%s_%s.sql\n' "$(date -u +%Y%m%d%H%M%S)" 'my_slug'`.

**Triage when CI fails on a duplicate or out-of-order migration:** rename via `git mv old.sql new.sql` where new.sql carries the correct HHMMSS, then re-run `cargo sqlx migrate run --dry-run` locally.

**Important exception — historical-leniency for already-merged migrations:** Once a migration with a bad timestamp is merged to `main`, it MUST keep its existing filename forever. Renaming a deployed migration is a schema-history rewrite that breaks production sqlx state (sqlx tracks migrations by filename). Caught 2026-05-26 on `20260526000000_methodology_seed_gate_a_remote_mode.sql` — I tried to rename via `git mv` after the operator flagged the bad timestamp, but the migration had already merged. Resolution: leave the bad filename, apply the HHMMSS rule strictly to new migrations only, document the historical artefact in a follow-up cleanup ticket if it matters. Rule of thumb: HHMMSS strictness applies pre-merge; post-merge migrations are immutable.

*Source: `memory/feedback_migration_filename_hhmmss.md`*

### feedback-migration-filename-must-use-real-hhmmss

When creating a new SQL migration file under `app/migrations/` (or any other migration directory in this org), the filename's HHMMSS suffix MUST be the real wall-clock time from `date -u +%Y%m%d%H%M%S`, NOT a round-zero placeholder like `_160000` (16:00:00 exact) or `_000000`.

**Why:** Migrations are ordered lexicographically by filename. Round-zero suffixes look like placeholders rather than genuine timestamps, can collide with future migrations on the same calendar day if anyone else also picks `_HH0000`, and signal sloppy authoring. The operator's standing rule (reinforced 2026-05-26 after my `20260526160000_methodology_gr_datasets_eurostat_fix.sql` PR): "always use HHMMSS not only 0000 in migrations."

**How to apply:**

Always derive the migration filename from a real timestamp:

```bash
TS=$(date -u +%Y%m%d%H%M%S)
touch "app/migrations/${TS}_some_descriptive_name.sql"
```

NOT this:
```bash
# BAD — round-zero suffix:
touch "app/migrations/20260526160000_foo.sql"
touch "app/migrations/20260526000000_bar.sql"  # also bad
```

This convention applies to:
- `app/migrations/*.sql` in omoikane.coach/daemon
- Any other Rust+sqlx project where migration ordering is filename-based
- Any project where the schema-migration filename includes a timestamp suffix

If you catch yourself writing `_000000` or `_HH0000` patterns, regenerate the filename from `date -u +%H%M%S` immediately.

*Source: `memory/feedback_migration_filename_must_use_real_hhmmss.md`*

### feedback-minimum-mr-size-1500-loc

Operator rule received 2026-05-29 via ccs-01 Matrix broadcast:

> minimum MR size is 1500 LOC; never smaller unless nothing else to code

**Why:** Operator preference for fewer, larger, bundled MRs over
many small ones. Surfaced after several days of the modal/perf chain
that shipped 11 MRs (820 / 824 / 825 / 826 / 827 / 830 / 833 / 842 /
844 / 848 / 849) each of which was 1-200 LOC. Plus -851 (12 LOC) for
the FromRow drift bug.

This is in tension with prior guidance I read into the codebase
("ship the smallest possible diff"), but the operator's explicit
broadcast wins.

**How to apply:**

- Before opening an MR, ask: *is the topic substantially complete,
  or are there obvious follow-ups in the same surface that should
  ride along?*
  - YES → bundle them.
  - NO → ship.
- A 12-LOC fix like OMOIKANE-851 (FromRow SELECT mismatch) should
  also include:
  - Audit of every other `query_as::<_, T>` site for similar
    drift on the SAME struct
  - The test that locks the SELECT shape to the struct
  - The `tracing::warn` replacement for `unwrap_or(None)` so the
    next drift becomes loud
  - Any UX gap in the surrounding admin surface
  - That gets it to 1500 LOC, no problem.
- The perf chain (820/824/826) should have been ONE MR with all
  three layers + the instrumentation (-827). The follow-up modal
  chain (833/842/844/848/849) likewise.

**When NOT to apply:**

- Operator explicitly asked for the smallest possible diff on a
  high-risk surface (rare).
- Hot-fix on a production incident where speed > size — but in
  that case ship the hot-fix AND open a follow-up that bundles the
  hardening.
- Cosmetic regression on a freshly-deployed MR (842 after 833) —
  here the smaller fix is the right call to avoid extending the
  surface area while operator is staring at a broken modal.

**Phrasing to use in PR descriptions:**

- "This MR closes OMOIKANE-X (the headline) plus drift-locks Y and
  Z that would otherwise come back as flaky tests in 2 weeks."

**Signal that I'm under-bundling:**

- Multiple consecutive MRs touching the same handler / view /
  module in a 1-day window — should have been one.
- Hot-fix MR that requires a follow-up MR for the test that locks
  the same surface — should have been one.

Canonical broadcast: ccs-01 Matrix message 2026-05-29 cancelling
small-MR push for OMOIKANE-855.

*Source: `memory/feedback_minimum_mr_size_1500_loc.md`*

### feedback-minimum-scoped-css-diff

When scoping a CSS rule to fix one property's behaviour, scope ONLY
that property. Don't scope the entire ruleset.

**Why:** Caught 2026-05-28 on OMOIKANE-833 → -842. Bug 2 was the modal
not closing because `.ci-modal { display: flex }` was unconditional
and overrode the UA `dialog:not([open]) { display: none }`. The fix
should have been one property:

    dialog.ci-modal[open] { display: flex; }
    dialog.ci-modal:not([open]) { display: none; }

I scoped the **entire** ruleset to `dialog.ci-modal[open]`:

    dialog.ci-modal[open] {
      border: ...;     /* unnecessary scoping */
      background: ...; /* unnecessary scoping */
      color: ...;      /* unnecessary scoping */
      ...
      display: flex;   /* this was the ONLY property that needed scoping */
    }

That bumped specificity from `.ci-modal` (0,1,0) to
`dialog.ci-modal[open]` (0,2,1) for EVERY property. The dark-mode
override 150 lines below was still `.ci-modal { background: #14141a }`
at (0,1,0) — it lost the cascade fight. Result: dark theme rendered
cream background. Operator caught it visually in the next browser
load. Cost: one extra MR (OMOIKANE-842) + one extra deploy cycle
(~13 min) + operator frustration.

**How to apply:**

- Before scoping a CSS selector to fix one property's interaction
  with a state ([open], [disabled], :hover, @media), ask: *which
  specific properties depend on this state?* Scope ONLY those.
- Keep visual + layout properties on the lowest-specificity selector
  the rest of the cascade expects. Pattern:

    /* default rules — no state qualifier */
    .x { border:...; background:...; color:...; padding:...; }

    /* state-only override of the property whose value depends on state */
    selector.x[state] { display: flex; }
    selector.x:not([state]) { display: none; }

- Specificity calculator is a 30-second check. Any time a CSS fix
  raises specificity, grep the same file (and the rest of the
  daemon) for other `.x {` rules — if any of them set the same
  properties at a lower specificity, you're breaking their cascade.
- For `<dialog>` elements specifically: the UA stylesheet's
  `dialog:not([open]) { display: none }` rule is what hides closed
  modals. Don't override `display` at any selector that wins over
  the UA's `dialog:not([open])` unless you mean to.

Canonical incident: [[omoikane-discover-modal-css-regression-20260528]]
(if written separately) or remembered by reference to OMOIKANE-833 →
-842 in the audit trail.

*Source: `memory/feedback_minimum_scoped_css_diff.md`*

### feedback-module-boundary-test-breaks-on-new-files

**Rule:** any new module file added to `omoikane.coach/daemon` that REFERENCES `signal_ledger` in either source or comments MUST be added to `mention_allowed_paths()` in `app/src/outcome_sensor/module_boundary_tests.rs` — or the comment must be reworded to avoid the literal substring.

**Why:** the Phase 2a REQ-40043 module-boundary drift-lock enforces "writes ONLY in `repos::signal_ledger_repo`" AND "mentions ONLY in the allowlist". The allowlist is intentionally tight to prevent accidental cross-module references that hint at private-data leakage paths. A new module like `methodology_proposal.rs` that documents the forward-binding relationship to `calibration_proposer` (which reads `signal_ledger` in MR-7) will fail the test if its comment includes the literal token.

**How to apply:**

1. Before pushing any MR that touches `app/src/*.rs` files, run locally:
   ```
   cargo test --bin omoikane-daemon --tests --locked -j 2 -- \
       signal_ledger_mentioned_only_in_outcome_sensor
   ```
2. If the test fails, either:
   - Add the new file's basename to `mention_allowed_paths()` (preferred; explicit allowlist), OR
   - Reword the comment to avoid the literal substring "signal_ledger" (e.g. use "ledger that holds outcomes" instead).

**Diagnostic path lesson:** CI's 4MB log cap truncates the trace at ~14000 of 26000+ tests. The actual FAIL line is past the truncation, invisible. Local `cargo test --bin omoikane-daemon --tests --locked -j 4` reproduces deterministically — the test count match across the suite is the diagnostic.

**Canonical incident:** 2026-06-02 OMOIKANE-1132 MR-6 reference_grounder pipelines 35519 + 35522 both failed unit_tests for this reason. Diagnosed by running the full test suite locally to find the actual FAIL line. Fix is one line in the allowlist.

Cross-ref: [[feedback-omoikane-daemon-users-id-is-bytea]] is the related Phase 2a CI lesson family.

*Source: `memory/feedback_module_boundary_test_breaks_on_new_files.md`*

### feedback-mr-branch-naming-single-yt-id

Branch name format the pre-push hook accepts:

```
kp/OMOIKANE-XXX-ccs0X-<slug>
```

**Components:**
- `kp/` — owner prefix (or `elli/`); operator is `kp`
- `OMOIKANE-XXX` — **exactly one** YouTrack issue id (no hyphenated pair like `OMOIKANE-731-734-*`)
- `ccs0X` — CCS session tag (`ccs01` / `ccs02` / `ccs03`)
- `<slug>` — kebab-case description

**Why "single YT id only":**

The pre-push hook + `yt-close-from-mr.sh` (the script that auto-closes the YT child when the MR merges via "Closes/Resolves: OMOIKANE-XXX" grammar in commit msg) both rely on the YT id being unambiguous. A branch named `kp/OMOIKANE-731-734-*` doesn't tell the hook whether 731 or 734 is the primary close target.

When an MR touches multiple YT children, pick the **primary close target** for the branch name and reference the others in the commit body via `Closes: OMOIKANE-XXX` / `Refs: OMOIKANE-YYY` grammar.

**Examples:**

| ✅ Correct | ❌ Wrong |
|---|---|
| `kp/OMOIKANE-733-ccs02-doi-mint-live-wiring` | `kp/OMOIKANE-731-734-ccs02-fairness-panel-annual-audit-page` |
| `kp/OMOIKANE-736-ccs02-eurostat-cron-12b3` | `kp/OMOIKANE-fairness-panel-and-audit-page` (no YT id) |
| `kp/OMOIKANE-724-ccs02-final-cron-prom-credentials-bundle` | `kp/OMOIKANE-724-cron-prom` (no ccs0X tag) |

**Caught in:** 2026-05-26 — MR !2517 used `kp/OMOIKANE-731-734-ccs02-fairness-panel-annual-audit-page`. The hook accepted it (passed) but operator flagged it post-merge. Both YT children were referenced in the MR description via Refs grammar; the branch should have picked one (either 731 or 734) as primary.

**How to apply:**

When opening a multi-YT-child MR, pick the highest-priority / most-meaningfully-closed YT id for the branch name. Reference the others via `Refs: OMOIKANE-YYY` in the commit body. Don't compose hyphenated YT-id pairs in branch names.

*Source: `memory/feedback_mr_branch_naming_single_yt_id.md`*

### feedback-mr-description-in-initial-post

When opening a GitLab MR via the API (`POST /api/v4/projects/<id>/merge_requests`), include the `description` field in the initial POST body. Do NOT POST first with minimal payload then PUT the description afterwards — the AIACT-checklist-gate CI job can fire on the empty description before the PUT lands, causing a spurious pipeline failure that needs a manual retry.

**Why:** Caught 2026-05-22 across MRs !2247 and !2249. Both initial pipeline runs failed `aiact_checklist_gate` with `FAIL: MR description is empty.` because the CI scheduler ran the gate within ~5s of MR creation, before my PUT description had landed. MR !2251 included description in the initial POST and passed first try.

**How to apply:**
- Write description JSON to a file FIRST (the heredoc problem with backticks/quotes goes away if you `--data-binary @file.json` rather than inlining)
- Combine `source_branch`, `target_branch`, `title`, `remove_source_branch`, `squash`, AND `description` in one JSON payload
- POST that payload — single round-trip, no race

Related: [[feedback-omoikane-p1c-env-var-tunables]] (operational tuning hygiene), [[feedback-no-shared-main-worktree]] (worktree hygiene).

*Source: `memory/feedback_mr_description_in_initial_post.md`*

### feedback-mr-size-target-2000-loc-bundled

When operator says **"why so many MRs / why dividing the MRs instead of using single big MRs?"** they are NOT saying:

- ❌ "Stop shipping code"
- ❌ "Ship less work"

They ARE saying:

- ✅ "Stop shipping 1-line / 100-300 LOC MRs"
- ✅ "Bundle multiple related improvements into ONE 1500-2000+ LOC MR"
- ✅ "One MR per *substantive chunk of value*, not one per *tiny change*"

## Caught in

2026-05-26 — after shipping 18 MRs in the OMOIKANE-724 lane (most under 500 LOC), operator pushed back. I initially over-corrected by considering "stop shipping more"; then ccs-01 echoed the operator's actual intent at 14:13 UTC: "ship 2000+ LOC bundled MRs, NOT stop shipping." Confirmed by operator at 14:24 UTC: "your practice of shipping 1 line of code instead of 2000+ lines of code and then you making a whole MR just for a tiny change."

## How to apply

Before opening any new MR, ask:
1. **Is this MR ≥1500 LOC** (handler + view + tests + docs combined)? If no → identify 2-4 related improvements to bundle in.
2. **Could 2-3 other in-flight pieces of value-add work fit?** If yes → bundle them.
3. **Do all bundled items touch the same surface or related surfaces?** If yes → ship as one MR with section-headed commit message + `Refs: OMOIKANE-XXX` for each closed/touched YT child.

Examples of right-sized bundling (~1500-2000 LOC):

- "Phase X cron worker + Phase Y UI surface + Phase Z dataset registration + 3 unrelated polish items" — one MR
- "DOI mint hook + concept DOI + retry cron + admin status display" — one MR  
- "Live HTTP fetcher + persistence + cron worker + Prom counter + admin browse UI" — one MR

Examples of wrong size (tiny MRs to avoid):

- One MR per single SQL migration
- One MR per single new Rust module
- One MR per single env-var addition
- One MR to "wire the route" after another MR added the handler
- One MR to fix one clippy warning after another MR

## Branch naming for bundled MRs

Per [[feedback-mr-branch-naming-single-yt-id]]: pick ONE primary YT id for the branch slug. Bundled MR titles can mention "bundle"/"consolidation". Commit body uses `Closes: OMOIKANE-XXX` for primary + `Refs: OMOIKANE-YYY` for the others.

*Source: `memory/feedback_mr_size_target_2000_loc_bundled.md`*

### feedback-n8n-expression-mode-and-buffer

Two n8n gotchas that caused the entire auto-resolve pipeline to be dark for months (2026-06-17 repair, [[pipeline_autoresolve_repair_20260617]]). Both are SILENT — the node "succeeds" but produces garbage.

**Why:** every prior gateway bug has been a "hallucinated node config" (CLAUDE.md). These two are the deadliest because nothing errors.

**How to apply — check BOTH on every SSH/command-node edit:**

1. **A command/url/jsonBody field that contains `{{ }}` templates MUST start with `=`** (expression mode). If the stored string does not start with `=`, n8n passes the `{{ }}` to bash LITERALLY → `base64: invalid input`, and `$('Node Name')` runs as shell command substitution → "command not found". Symptom in this repair: every Runner escalation fail-closed to `high` with an empty plan; `session_risk_audit` stayed empty. Lost on 4 nodes at once (Classify Risk / Commit Prediction / Query Knowledge / Bridge Drain-Queue-on-Resume — the last had the `=` buried MID-string from an edit).

2. **`Buffer` is NOT in n8n's expression sandbox** — only real Code nodes expose it. `{{ Buffer.from(x).toString('base64') }}` in an SSH-node expression throws/returns empty. Use the n8n string extension **`{{ (x).base64Encode() }}`** instead (its `JSON.stringify`/`.base64Encode()`/`.substring()` ARE in the sandbox). The Code-node Launch Claude pattern pre-computes a b64 field BECAUSE Code nodes have Buffer; SSH nodes can't.

**Sweep for both across all workflows when something silently doesn't classify/record:**
```
# per node command: has '{{' but not startswith('=')  -> bug 1
# 'Buffer.from(' anywhere in a non-Code node           -> bug 2
```
**Diagnose fast:** the pipeline debug log (`grep <issue_id> /home/app-user/logs/claude-gateway/pipeline-debug.log`) shows `stdin length=0` + `plan_parse_fail` the instant bug 1 fires. See [[pipeline_autoresolve_repair_20260617]].

*Source: `memory/feedback_n8n_expression_mode_and_buffer.md`*

### feedback-n8n-workflow-export-format-per-file

2026-06-17 (IFRNLLEI01PRD-940). The `workflows/*.json` exports in claude-gateway are NOT serialized consistently file-to-file. Re-dumping a freshly-fetched live workflow with the wrong params produces a massive key-reorder diff that hides the real change and is unreviewable.

**Why:** different exports were written at different times by different tools (raw n8n API dump vs n8n-MCP export), so each file has its own `json.dump` settings AND its own top-level key order.

Confirmed for these two (detect, don't assume):
- `claude-gateway-runner.json` → `json.dumps(obj, indent=2, ensure_ascii=False) + "\n"`
- `claude-gateway-matrix-bridge.json` → `json.dumps(obj, indent=4, ensure_ascii=True) + "\n"`

**How to apply:** to commit a workflow change with a minimal, reviewable diff:
1. `git show HEAD:workflows/<f>.json` → confirm it equals the live pre-change state (compare node names + each node's `jsCode`/`command`).
2. Detect serialization: loop `indent in (2,4)` × `ensure_ascii in (True,False)` until `json.dumps(obj,...)+"\n" == original`.
3. Load the HEAD file (preserves its key order), graft ONLY your delta (e.g. the new node + the one changed `jsCode`, taken verbatim from the live refetch so repo==live), then dump with the detected params.
This turned a 15,820-line churn into a 37-line surgical diff. Cross-ref [[feedback-n8n-expression-mode-and-buffer]]. Also: in the Bridge, `Detect Command.prefix` is misleadingly named — it holds the FULL issue id (`MESHSAT-612`), not the project prefix.

*Source: `memory/feedback_n8n_workflow_export_format_per_file.md`*

### feedback-never-block-request-on-external-llm

In omoikane.coach/daemon Axum handlers, never put a `.await` on `ai_dispatch::invoke` / `extract_for_posting` / `ensure_structured_or_extract` directly on a synchronous HTTP request path. The upstream `claudecode-runner` sidecar has a 75s per-URL timeout and a fallback chain that can stall the request 75–225s when the runner is slow or unhealthy.

**Why:** Caught 2026-05-22 with MR !2249 (OMOIKANE-496). I added `ensure_structured_or_extract(...).await` to `step_gate` so paste-vacancy postings would get structured extraction inline. Operator hit it immediately on posting `c8fa5979`: gate page hung > 120s. Daemon logs: `runner call failed; trying next url url="http://10.255.X.X:8093"`. Hot-reverted via MR !2251 to `tokio::spawn(async move { ensure_structured_or_extract(...).await })`. First render returns in 1.4s with whatever deterministic fallbacks apply; next render (after background extract lands ~10-30s later) sees the populated row.

**How to apply:**
- Any LLM call from an Axum handler → `tokio::spawn(...)` with cloned state, posting_id, user_id
- Render the page with whatever data is currently in the DB. Deterministic fallbacks (e.g. OMOIKANE-490 title-city geo scan) should already cover the empty-state path
- The user refreshes after a few seconds and sees the populated data — one incomplete render >> one render that hangs 1-4 minutes
- The exception: a request that **explicitly** is "do this LLM thing now" (e.g. `/workflow/posting/<id>/run-gate` — the user pressed a button labelled "Re-run gate") can block, but should set a hard timeout that's strictly less than the runner timeout (e.g. 60s) so the response returns with an error before the runner upstream gives up
- Long-term: WebSocket / SSE channel that pushes chip-update events when the row populates, so the page live-refreshes without manual reload

Related: [[feedback-omoikane-p1c-env-var-tunables]] (75s `EXTRACT_TIMEOUT_SECS` env var is itself proof of how slow these calls are).

*Source: `memory/feedback_never_block_request_on_external_llm.md`*

### feedback-no-fragment-prefer-bundled-mrs

The operator explicitly prefers **bigger MRs that deploy + test, not many small MRs**. This was previously documented but I violated it heavily in the 2026-05-26 OMOIKANE-724 session: shipped 17 small MRs across 12 epic phases when ~5-6 bundled MRs would have served.

**Why:** Each fragmentation costs:
- A separate CI cycle (~2-3 min) + queue position + reviewer context-switch
- A rebase-risk increment — every concurrent MR that touches `mod.rs` or any shared file forces a manual rebase (bit me 4× in one session)
- A longer end-to-end "what landed tonight?" reconstruction
- More YT-comment-update load on the operator

The "substrate-first scaffolding" pattern (separate MR for types vs cron vs view-layer) is **only justified for the first 2-3 splits in a multi-phase epic** where natural seams genuinely exist (substrate ≠ migration ≠ admin UI ≠ public surface, ~800-1600 LOC chunks). Beyond that, splitting into 100-300 LOC chunks adds cost without adding clarity.

**How to apply:**

- Default to **one MR per YT child** when child scope is ≤1500 LOC. Split only if the child genuinely needs intermediate substrate that downstream MRs build on (and even then prefer 2 MRs over 4).
- **Bundle MRs across YT children freely** when the work is the same call-chain (e.g. "cron + Prom + admin panel" for one feature lives in one MR even if it ref's 3 YT children).
- When tempted to split for "easier review", consider whether the diff would be readable as one MR with section-headed file-by-file commentary in the description. Usually yes.
- A consolidated MR that closes 2-3 YT children at once is the gold-standard shape; ccs-01 also independently arrived at this pattern same-night ("over-fragmented tonight... should've been 1").

## Caught in

2026-05-26 OMOIKANE-724 marathon session: 17 sub-phase MRs (9a / 10a / 11a / 11b / 12a / 12b1 / 12b2 + their predecessors) where ~5-6 bundles would have done. Recovery: consolidated 12b3 + 10b + 11c-partial + 9b-prep into MR !2515 closing OMOIKANE-734 + OMOIKANE-736 at once. ccs-01 acknowledged same issue ~10:33 UTC: "operator-correct ack: over-fragmented tonight. JSON-LD enrichment was 3 MRs (!2492+!2498+!2499) when it should've been 1".

*Source: `memory/feedback_no_fragment_prefer_bundled_mrs.md`*

### feedback-no-shared-main-worktree

## Rule

For any claude-code agent session (foreground OR background dispatch) that performs git operations on `omoikane.coach/daemon`:

1. **NEVER `cd /app/websites/omoikane.coach/daemon`** (or Elli's `/home/elliz/.../daemon`) as the working directory for ANY git op.
2. **First action:** allocate a per-session worktree from an outside cwd:
   ```bash
   git -C ~/gitlab/websites/omoikane.coach/daemon worktree add /tmp/daemon-<short-purpose> --detach origin/main
   cd /tmp/daemon-<short-purpose>
   ```
3. **All subsequent git ops in that session happen inside the new worktree.**
4. **Cleanup on done** (from a cwd outside the worktree):
   ```bash
   git -C ~/gitlab/websites/omoikane.coach/daemon worktree remove /tmp/daemon-<short-purpose>
   ```

The pre-push hook **enforces** this — when `$CLAUDE_PROJECT_DIR` is set (always true for claude-code sessions), pushes from the canonical clone path are refused with `pre-push: REFUSED — agent session is operating in the shared main worktree`.

## Why (2026-05-19 incident)

Two concurrent claude-code sessions on `nl-claude01` were both operating in `/app/websites/omoikane.coach/daemon/`:

- **Session A** ran `git checkout main && git pull --ff-only` to verify a merged MR.
- **Session B** was mid-stride on its own work (`kp/OMOIKANE-260-...`), about to commit.

When Session B's commit fired, `HEAD` was now pointing at `main` (or whatever Session A left it at), not at OMOIKANE-260. The commit landed on the wrong branch → polluted MR !2023.

The two sessions shared `.git/HEAD` because they shared the worktree. Even though Session A's git ops were "harmless verification", they had load-bearing effects on Session B's branch state.

## How to apply

When dispatching ANY future claude-code agent (background via `nohup claude -p` OR foreground via interactive claude-code) that will modify the daemon repo:

- **Background dispatches**: cwd must be `/tmp/daemon-<purpose>/`, NOT `/app/websites/omoikane.coach/daemon/`. The [[feedback-autonomous-claude-p-loop-dispatch]] pattern was already correct (uses `/tmp/loop-wt-*` worktrees); this rule generalizes.
- **Foreground claude-code (this conversation type)**: same rule — when you need to do git ops on the daemon repo, allocate `/tmp/daemon-cli-<timestamp>/` from a non-daemon cwd. Don't use the canonical clone as scratch space.

For any read-only inspection (`git status`, `git log`, file reads), the canonical clone is still fine — the rule is specifically about ops that touch `HEAD` (checkout, commit, push, worktree-add from inside the canonical path).

## Cross-references

- `omoikane.coach/daemon/scripts/git-hooks/pre-push` Check 0 — enforces the rule
- `omoikane.coach/daemon/CLAUDE.md` § P1.D — surfaces the rule for every agent session
- `/app/websites/omoikane.coach/CLAUDE.md` § P1.D (ankh umbrella) — same surfacing
- `/home/elliz/gitlab/websites/omoikane.coach/CLAUDE.md` § P1.D (fouska umbrella) — TODO when fouska is online
- **NOT codified as a constitution article** — Wave 2 took Article LIX (Option/Result transforms) before the worktree-isolation article could be filed. The rule lives only in P1.D (CLAUDE.md) + pre-push hook Check 0 + this memory. Re-codifying as a constitution article is still possible in a future ingest (would take whatever next-available number is) but not pursued — the hook + P1.D are load-bearing; a constitution article would be documentation-only.
- OMOIKANE-264 — this issue + the MR
- Sibling P1 rules: [[feedback-omoikane-p1c-env-var-tunables]] (P1.C) and [[feedback-omoikane-p1-cargo-test-and-frontend-developer]] (P1.A/B)
- Originating dispatch pattern: [[feedback-autonomous-claude-p-loop-dispatch]] (background loops already follow this correctly via /tmp/loop-wt-*)

*Source: `memory/feedback_no_shared_main_worktree.md`*

### feedback-omoikane-daemon-users-id-is-bytea

When working in `/app/websites/omoikane.coach/daemon`, the `users` table primary key column `users.id` is declared `BYTEA` (16-byte raw UUID payload), NOT `UUID`.

Any new migration that adds a `user_id` foreign key to `users(id)` MUST declare the column `BYTEA NOT NULL` — declaring `UUID NOT NULL` makes the FK fail with PostgreSQL error 42804: `foreign key constraint cannot be implemented. Key columns "user_id" and "id" are of incompatible types: uuid and bytea.`

**Rust-side conventions** (these mirror `app/src/fairness_audit_consent.rs`):

1. **Struct field**: keep `pub user_id: uuid::Uuid`. Consumers see Uuid, not bytes.

2. **Write/bind**: `.bind(user_id.as_bytes().as_slice())` — never `.bind(user_id)` directly. SQLx will not coerce Uuid into BYTEA.

3. **Read pattern**: `query_as` tuple uses `Vec<u8>` for the user_id slot, then convert:
   ```rust
   let row: Option<(i64, Vec<u8>, String, ...)> = sqlx::query_as("SELECT id, user_id, ... FROM ...")
       .bind(user_id.as_bytes().as_slice())
       .fetch_optional(pool).await?;
   if let Some((id, uid_bytes, ...)) = row {
       let user_id_decoded = uuid::Uuid::from_slice(&uid_bytes)
           .context("read_<fn>: malformed user_id bytes")?;
       ...
   }
   ```

4. **Migration CHECK constraints + indexes**: same as for UUID column; only the column type changes.

**Why:** Caught 2026-06-02 on OMOIKANE-1106 (outcome-sensor Phase 1a). My subagent's migration declared `user_id UUID NOT NULL REFERENCES users(id)` and CI pipeline 35475 migration_smoke failed. Fix: replace `UUID` → `BYTEA` in 2 places + update all `.bind(user_id)` calls to `.bind(user_id.as_bytes().as_slice())` + add `Uuid::from_slice` conversion in each `query_as` read site. Cost of mistake: one wasted CI cycle (~6min) + one fix-up commit.

**How to apply:** Before writing any new migration that references `users(id)`, grep for `REFERENCES users(id)` in existing migrations — every existing example uses BYTEA. Mirror that pattern verbatim. If you must verify the live schema, the canonical reference is `app/migrations/20260526134117_user_fairness_audit_consent.sql`.

Cross-ref: [[feedback-clippy-strict-flags-for-omoikane-daemon]] — same posture as the other strict-CI lessons; what works on naive schema doesn't always work against the live one.

*Source: `memory/feedback_omoikane_daemon_users_id_is_bytea.md`*

### feedback-omoikane-p1-cargo-test-and-frontend-developer

## Rule

For any session working in `omoikane.coach/daemon/` (or the umbrella across `daemon/`, `beta/`, `www/`), two rules sit at P1 above the rest of the constitution + cross-machine protocol:

1. **`cargo test --locked` BEFORE every push.** Mandatory per constitution Article XLIII. Run from `~/gitlab/websites/omoikane.coach/daemon/app/`. `cargo check`, `cargo build --tests`, and `cargo test` (without `--locked`) are NOT substitutes — only `--locked` matches CI's exact behaviour. Read the output, summarise it, fix what fails. NEVER push with red tests "to let CI catch them."

2. **Invoke the `frontend-developer` skill on any UI/UX surface.** For any change touching `daemon/app/templates/`, `daemon/app/src/views/`, `daemon/app/static/`, or Hugo layouts/content in `beta/` or `www/`. The skill carries ND-friendly defaults (Article XXXVI), WCAG 2.2 AA + EU EAA accessibility (ASLOP-14), anti-slop copy patterns. Surface as blocker if the skill is unavailable.

## Why

- **Caught 2026-05-19** after multiple consecutive CI failures from Elli's fouska-wireless session pushing daemon Rust changes without running `cargo test --locked` first. CI ran the locked suite, caught the failures, surfaced via failing pipelines + omoikane-dev Matrix.
- **Root cause** wasn't missing documentation — the rule was already mentioned 7+ times across `daemon/CLAUDE.md`, fouska's umbrella, and the constitution. **Root cause was bad surfacing**: the rule was buried mid-file (line 316 of a 601-line umbrella) and framed PASSIVELY ("claude runs cargo test --locked and summarises") rather than as a MUST-DO obligation.
- The Hugo workflow at the top of fouska's umbrella has no test step (correctly — Hugo content doesn't need one). When her session moved to daemon work, the Hugo muscle-memory pattern carried over.

## How to apply

When working on a session that will eventually push omoikane.coach changes:

- Treat the P1 section at the very top of `daemon/CLAUDE.md` and both umbrella `CLAUDE.md` files as binding-on-read. If you're touching anything Rust-affecting under `daemon/app/`, the test run is part of "ready to push" not part of "claude can do this later."
- For UI/UX work, invoke `frontend-developer` skill BEFORE writing the change. Don't author first and validate-via-skill after.
- The pre-push hook on both machines enforces branch naming + YT-ID + claim collisions — but it does NOT run `cargo test --locked`. That's an operator/agent responsibility, hence why it lives at P1 documentation.

## Cross-references

- `omoikane.coach/daemon/CLAUDE.md` § "P1 reminders" (added by !1988, OMOIKANE-220)
- `omoikane.coach/daemon/constitution.md` Article XLIII
- `/app/websites/omoikane.coach/CLAUDE.md` § "P1 reminders" (ankh-side umbrella, local)
- `/home/elliz/gitlab/websites/omoikane.coach/CLAUDE.md` § "P1 reminders" (fouska-side umbrella, local)
- Related: [[feedback_no_balloon_on_k8s_control_plane]] for the general "rule was already documented but didn't surface as P1" failure mode

*Source: `memory/feedback_omoikane_p1_cargo_test_and_frontend_developer.md`*

### feedback-omoikane-p1c-env-var-tunables

## Rule

Any value in `omoikane.coach/daemon` that may need adjustment **in production without a code change** MUST be exposed as an environment variable with a compile-time default. Hardcoding is a constitution violation (Article LIII).

The test: *"would I want to change this in production with a docker restart instead of a CI build cycle?"* — if yes, env var.

## Categories

**Tunable** (env var with default) — MUST use the pattern below:

- Timeouts (HTTP, subprocess, retry budgets, lock acquisition)
- Concurrency / rate limits (semaphore counts, max workers, requests/sec, tokens/min)
- Model names (`EXTRACT_MODEL`, `GATE_MODEL`, `RAG_RERANKER_MODEL`, etc.)
- Polling intervals + cache TTLs
- External URLs / endpoints (failover without rebuild)
- Feature flags + cohort fractions
- Operator-configurable budgets / caps

**Invariant** (stay hardcoded) — these are not tunables:

- Spec-mandated constants (match-gate ≥ 50%, max 5 STAR-R drafts, 4-step workflow)
- Type-level constants (enum cardinality, schema versions)
- Test-asserted constants
- Constitutional invariants (Articles I, II, XV, XVI, XLI, L, etc.)
- Migration ordering values + cryptographic parameters

## Standard pattern (Rust)

```rust
const FOO_DEFAULT: u64 = <value>;

fn foo() -> u64 {
    std::env::var("OMOIKANE_FOO")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(FOO_DEFAULT)
}
```

Naming: `OMOIKANE_<DOMAIN>_<UNIT>` (e.g., `OMOIKANE_EXTRACT_TIMEOUT_SECS`, `OMOIKANE_EXTRACT_MODEL`, `OMOIKANE_RAG_RERANKER_URL`). Suffix encodes the unit: `_SECS`, `_MS`, `_MAX`, `_LIMIT`, `_MODEL`, `_URL`, `_PCT`.

## Canonical incident (2026-05-19)

`EXTRACT_TIMEOUT_SECS` was hardcoded at 45 in `daemon/app/src/`. Production audit showed Haiku-mediated `posting_extract` calls timing out:

```
created_at                | model                     | duration_ms | ok
2026-05-19 12:20:04+00    | claude-haiku-4-5-20251001 |       90046 | f
2026-05-19 12:19:01+00    | claude-haiku-4-5-20251001 |       90079 | f
2026-05-19 12:18:34+00    | claude-haiku-4-5-20251001 |       90053 | f
```

90 s = 45 s primary + 45 s peer-URL retry, both killed by the runner. Direct probe with the same prompt shape (system ~4k tok + user ~1k tok + max_tokens 3k) returned in ~17 s with prompt-cache hit. Production slowdown was the cold-cache path: `claudecode-runner` spawns `claude -p` as a subprocess; first call after a worker tick that misses Anthropic's prompt-cache processes the full ~7k input fresh → 30-60 s end-to-end. 45 s killed the tail.

Two sequential MRs (!2003, !2004) bumped the constant: 20→45, then 45→75. Each required a CI build (~3-5 min) + AWX deploy (~3 min) + verification probe (~5 min). ~15 min cycle per number change.

If the constant had been `OMOIKANE_EXTRACT_TIMEOUT_SECS` env var: `docker restart` on the daemon LXC, ~30 seconds, done. **The cost differential was 30× per adjustment.** When the cold-cache p99 had to be re-measured after each change, the cost was multiplicative.

Operator surfaced the methodology issue same-day. OMOIKANE-241 retrofits the specific case (`EXTRACT_TIMEOUT_SECS` + `EXTRACT_MODEL` → env-overridable). OMOIKANE-242 (MR !N) codifies the general rule as constitution Article LIII + CLAUDE.md P1.C + this memory.

## How to apply

When you're about to write a constant in Rust source that fits the "tunable" categories above:

1. Define the default as a `const`.
2. Wrap it in a getter that reads `OMOIKANE_<DOMAIN>_<UNIT>` from env, falls back to the default.
3. Use the getter everywhere — never read the const directly outside the getter.
4. If the value needs a valid range (e.g., timeout 5-600 s), validate in the getter or document the range in a comment.
5. Document the env var in the relevant runbook OR in a sibling line-comment for now (defer a `docs/runbooks/runtime-tunables.md` catalogue until ≥5 tunables exist).

When you're about to write a constant that's NOT a tunable (spec-mandated, test-asserted, constitutional invariant) — keep it hardcoded. Don't over-apply this rule.

## Cross-references

- `omoikane.coach/daemon/constitution.md` Article LIII (canonical)
- `omoikane.coach/daemon/CLAUDE.md` § P1.C
- 2026-05-19 incident MRs: !2003 (45→), !2004 (75→), OMOIKANE-241 (retrofit `EXTRACT_*` to env), OMOIKANE-242 (this Article)
- Sibling P1 reminders: [[feedback-omoikane-p1-cargo-test-and-frontend-developer]]

*Source: `memory/feedback_omoikane_p1c_env_var_tunables.md`*

### feedback-operator-does-not-watch-matrix-polls

The human-in-the-loop has notifications OFF and voted on **almost none** of the Matrix MSC3381 approval polls in the 1–2 months before 2026-06-16. **Exact measurement 2026-06-17 (IFRNLLEI01PRD-1101, via the @claude Matrix CS API over the 3 rooms): 0 of 824 approval polls voted in the trailing 30d (0.0%); ZERO human events of any kind (response/reaction/message) in #infra-nl-prod/#infra-gr-prod/#chatops in 30d; @dominicus's last poll vote was 2026-05-07 (~41 days ago).** So treating Matrix polls as a real control surface is wrong: they go unanswered (824 un-voted in a month) and the session stalls. (Going forward IFRNLLEI01PRD-1100 logs votes to `event_log` mcp_approval_response; historically the bridge kept only a capped-100 `pollCache`.)

**Why:** an unwatched poll is the worst of both worlds — not autonomous (work stalls on the 30-min `shouldPause`) and not supervised (no one decides). The operator explicitly wants: (1) MORE auto-resolve since they're not in the loop, and (2) SMS for ONLY genuinely-critical cases (SMS is the one channel they actually see).

**How to apply:** design agentic gating around the operator being a **circuit-breaker, not a gatekeeper**. Reversible, prediction-backed actions should auto-resolve; reserve human paging (SMS) for a tight critical set (HIGH-risk, P0-host blast, irreversible, model deviation). Don't add features that assume the operator is watching a chat channel — route anything that genuinely needs them to SMS. This shipped as the autonomy-forward gate ([[autonomy-forward-gate-live-20260616]], epic IFRNLLEI01PRD-1102): enabled via `~/gateway.autonomy_forward` + `~/gateway.autonomy_session_sms` sentinels, kill-switch `rm ~/gateway.autonomy_forward`. The safety floor (irreversible / deviation / no-prediction / jailbreak / P0-reboot) still pauses + pages — never auto.

*Source: `memory/feedback_operator_does_not_watch_matrix_polls.md`*

### feedback-playwright-force-refresh-before-push

# Feedback: force-fire the refresh callback in Playwright before pushing

**Rule:** When editing code inside an auto-refresh / setInterval / poll callback, the local verify step MUST force-invoke the callback explicitly, not just `page.waitForTimeout(N)` to let natural polling fire. Otherwise:
- Wait time is unbounded (intervals vary, localStorage overrides, etc.) — a 20s wait against a 30s default polls zero times.
- A `ReferenceError` *inside* the callback is invisible on page load (the page renders fine because initial render uses different code paths) and only surfaces on the first natural fire — which might be after you've already pushed and walked away.

**Why:** I deployed `kyriakos:f3dacee` 2026-05-13 with a `ReferenceError: nColor is not defined` inside `updateData()`. The page rendered fine on load (initial render path). I "verified" with Playwright + 20s wait — auto-refresh interval is 30s, so updateData() never fired during my window. Pushed to main, AWX deployed, operator hit reload, hit the broken state, came back angry.

**How to apply (template):**

```js
const after = await page.evaluate(async () => {
  // Force the callback under test to run with realistic data — same call the
  // poll path would make, but invoked NOW so any error surfaces immediately.
  const fresh = await fetch('/api/<endpoint>', { cache: 'no-store' }).then(r => r.json());
  window.__<thing>.update(fresh);              // <-- the canonical entry point
  await new Promise(r => setTimeout(r, 500));  // let D3 transitions settle
  return /* probe the DOM for expected post-refresh state */;
});
// Inspect `errs.filter(e => !e.includes('analytics'))` — any pageerror = blocker.
```

**Where the canonical entry points live in this codebase:**
- `kyriakos/static/js/mesh-graph.js`: `window.__meshGraph.update(fullData)` — calls `updateData()`. Also `window.__meshGraph.refreshLinkVisuals()`.
- `kyriakos/static/js/auto-refresh.js`: `updateMeshWidget(data)` (module-local, not on window — go through `window.__meshGraph.update` instead).
- `kyriakos/static/js/chaos.js`: `BASE + '/mesh-stats'` polled at ~5s — surface via `window.__chaos*` if you need to force-fire (check current exports first).

**Test contract:** before pushing, the Playwright spec for a refresh-callback edit MUST do all three:
1. Capture BEFORE state (initial render).
2. Force-invoke the callback.
3. Capture AFTER state + zero page errors.

If it can't show "BEFORE ≠ AFTER" or "BEFORE = AFTER" matches the design intent, the change isn't verified — don't push.

Caught: 2026-05-13. Triggering commit `kyriakos:f3dacee`. Corrected by `kyriakos:7a9cc2a`. See [[dmz-container-count-zero-baked-20260513]] for the full trace.

*Source: `memory/feedback_playwright_force_refresh_before_push.md`*

### feedback-preserve-row-layout-on-status-diagram

# Preserve the existing single-row transit layout on the status diagram

**Rule:** When the status-page network diagram needs more transit bubbles
than fit, the fix is **always** to tune the existing layout (row y position,
horizontal spacing, count cap) — never to introduce a new layout pattern
(fan, arc, per-upstream cluster, multi-row stack).

**Why:** Operator preference, confirmed by direct feedback. 2026-05-16:
faced with 9 transits in a row that was crowding the upstream bubbles, I
rewrote the layout into a per-upstream angular fan (`37462f3`). When the
operator saw it in an incognito window they reacted "holy shit ... complete
disaster ... undo it immediately". The much smaller fix — bumping the row's
y constant from `cy - 0.82 * baseR` to `cy - 1.0 * baseR` — preserved the
existing visual style and was accepted.

**How to apply:** before touching mesh-graph.js layout code:

1. Read `vNodes.forEach` at the top of the file. Note that upstreams are
   pinned at fixed `(fx, fy)` near their sites, transits are pinned in a
   single horizontal row above.
2. Identify the smallest constant you can change to fix the geometric
   problem (row y, row spacing, max-per-upstream, count threshold).
3. Verify the change with a Playwright screenshot + measurement test
   BEFORE committing. Show the operator the screenshot if there's any
   chance they'll dislike the result.
4. If the smallest single-constant change cannot fix it, list 2-3 minimal
   alternatives and ask the operator which to pick — do not unilaterally
   redesign.

**The original layout invariants to preserve:**

- Upstreams at `(site.x ± 70, site.y - 70)` — iFog left of NO, Terrahost
  right of CH, both at y ≈ 123 in the 580 h canvas.
- Transits in a single horizontal row at a single y, centred on `cx`,
  spaced `min(60, W * 0.65 / count)` px apart.
- 60 px transit-to-transit spacing is the operator-accepted aesthetic.

**Don't reach for:** radial / fan / per-upstream clustering / multi-row /
spirals / staircase. Even if they would fit more bubbles "more elegantly".

See also: [[status-diagram-upstream-render-gaps-20260516]],
[[feedback-mesh-graph-cache-buster]].

*Source: `memory/feedback_preserve_row_layout_on_status_diagram.md`*

### feedback-prom-describe-needs-boot-sentinel

When you add a new Prometheus counter on the omoikane.coach/daemon (or any other metrics-crate-instrumented service), `describe_counter!` alone is **insufficient**. The metrics-crate Prometheus exporter only iterates series that have been incremented at least once — a describe call writes HELP/TYPE metadata to a side-table but never emits the line to `/metrics` until first increment.

**Failure mode is invisible at merge time and asymptotic at deploy time:** local tests pass, CI green, `cargo doc` clean, deploy logs `success`. The bug only surfaces when an operator hits `/metrics` and the HELP line is missing — and even then it looks like "deploy lag," not a code bug. On the v2 + Amendment B chain (OMOIKANE-1117) this masked **four** broken counter modules — MR-8c (honesty_clause), MR-8e (disaggregated cells), MR-10 (drift_loop verdicts + proposals), MR-11 (shadow_log obs + rollbacks) — for 1-3 hours each before MR-13 caught + fixed all in one go.

**Why:** `metrics::describe_counter!` registers metadata, but `metrics-exporter-prometheus` only emits a series when it has at least one observed sample. Without a sentinel emit, the series simply never appears in scrape output.

**How to apply (the pattern):**

```rust
pub fn describe() {
    metrics::describe_counter!(METRIC_NAME, "help text. Operator PromQL MUST filter `{label!=\"boot\"}`.");

    // Boot sentinel — emit one zero-value sample so the
    // metrics-crate exporter materializes HELP/TYPE on /metrics
    // before any real increment.
    metrics::counter!(METRIC_NAME, &[("label", "boot")]).increment(0);
}
```

Sentinel-label values must NOT collide with any real-traffic value (use literal `"boot"` — it is not a valid value for any closed enum in the codebase). The describe HELP text MUST tell operators to filter the sentinel out in their PromQL queries.

**Reference modules that do it right:**

- `app/src/metrics_outcome_sensor_consent.rs::register()` — 5-counter + 1-gauge sweep with sentinel labels for `channel`, `op`, `mode`, `lang`, `version`. Canonical pattern.
- `app/src/methodology/...goal_rationale_duration_seconds` — histogram-flavor of the same pattern with `surface="boot"`.

**Cross-ref:** [[feedback-goal-rationale-prom-histogram-empty]] is the original memory documenting this pattern for histograms. This entry generalises to counters.

**Cost of missing it (2026-06-03):**
- 38 minutes of operator-visible "deploy lag" that was actually a deploy-fine + code-bug
- One additional MR (MR-13 !2802) to fix four modules at once
- One verifier-script bug (MR-12 asserted wrong metric name because no live metric existed to compare against during writing)
- A second-stage MR (MR-14 !2804) because the four sentinel emits were still in two different call sites — two of them ran BEFORE the recorder

Whenever you author a new Prom counter in this codebase, the `describe` + sentinel pair are a single atomic unit — never one without the other.

## The second trap: describe() ordering vs recorder install

On `app/src/main.rs` the metrics-crate global recorder is installed by `axum_prometheus::PrometheusMetricLayer::pair()` around line 1448 (search for `PrometheusMetricLayer::pair()` to locate; it moves with refactors). Anything that calls `metrics::counter!(...).increment(...)` BEFORE that line lands on a **no-op global recorder** — the increment compiles fine, executes without error, and registers nothing. The HELP/TYPE line will not appear on `/metrics`.

`describe_counter!` ALSO requires the recorder to be installed; it is silently dropped if called pre-recorder. Two of the four MR-13 sentinel emits (drift_loop, fairness_audit_disaggregated_runner) were wired alongside their `spawn_periodic_worker` calls earlier in main.rs (lines ~1325 and ~1334), so they ran before the recorder and silently no-op'd. MR-14 split each module's `describe()` from its `spawn_periodic_worker()` and moved every `describe()` to AFTER the recorder install, alongside the working `metrics_honesty_clause::describe()` + `metrics_shadow_log::describe()` block.

**Rule:** whenever you wire a new module's `describe()` (or `register()`) into `main.rs`, place the call AFTER `axum_prometheus::PrometheusMetricLayer::pair()`. Spawning the cron worker can stay anywhere — it does not touch the global recorder until its first tick. Visually grep `main.rs` for the recorder-init line before adding the describe.

**Quick local test:** `bash scripts/ci-clippy-gate.sh` will not catch this — it is a runtime ordering bug. The post-deploy verifier (`scripts/post-deploy-verify.sh` after MR-12 + MR-13) is the canonical check; it asserts each HELP line is present on the live `/metrics`.

*Source: `memory/feedback_prom_describe_needs_boot_sentinel.md`*

### feedback-raw-input-ratchet-bump-pattern

When adding ANY new `<input ...>` tag to a Maud view in the omoikane.coach/daemon repo, the `views::a11y::g8_slice_2_raw_input_ratchet::raw_input_count_does_not_exceed_baseline` test will fail and block ALL downstream MRs.

**Why**: The a11y ratchet (in `app/src/views/a11y.rs`) counts raw `input ` tag occurrences across `app/src/views/**.rs` and asserts the count stays ≤ `RAW_INPUT_BASELINE`. Intent is to push contributors toward `views::a11y::labeled_text_input` (+ siblings) for proper screen-reader support. Same for `<textarea>` → `RAW_TEXTAREA_BASELINE`.

**How to apply**: When landing an MR that adds a new `<input>` (including `type="hidden"` / `type="file"` / `type="number"` — anything `labeled_text_input` doesn't cover), bump BOTH:

```rust
// in mod tests of app/src/views/a11y.rs
const RAW_INPUT_BASELINE: usize = N;          // ← bump here
...
let max_starting_input: usize = N;            // ← AND here (in baselines_are_at_or_below_their_starting_snapshot)
```

Plus add a dated comment explaining WHY the new input doesn't fit the helper (mirror the format of OMOIKANE-669 / -495 / -693 / -706 comment blocks already there).

**Two-edit pattern** is intentional — forces operator review on the MR.

**Operator-visible blast radius if you forget**: ALL open MRs (yours + everyone else's) fail CI on this single test. Caught 2026-05-25 OMOIKANE-693 session: OMOIKANE-706 landed `type=hidden name=host` on the OAuth-rotate UI form without the bump, blocking 3 of my downstream MRs (!2431 / !2434 / !2441) + 4 unrelated MRs on the fleet (!2433 / !2439 / !2440 / !2442). Fix shipped as !2444 baseline 224→225.

**Helper conventions**:
- `labeled_text_input` — `type=text|email|password|number` with `<label for="...">`
- `labeled_password_input` — wraps password (per OMOIKANE-687)
- `labeled_textarea` — for `<textarea>`
- Hidden inputs (`type=hidden`) genuinely don't fit any helper — they're infrastructural — so they DO require a baseline bump
- File inputs (`type=file`) — same

**Exception**: when the new input IS a text/email/password/number type and SHOULD use the helper, don't bump — refactor to use the helper instead. The ratchet exists to nudge that conversion.

**Triage**: when CI fails with `raw_input_count_does_not_exceed_baseline`, check `git log -p -10 -- 'app/src/views/' | grep -E "^\+.*<input "` to find the offending addition.

*Source: `memory/feedback_raw_input_ratchet_bump_pattern.md`*

### feedback-silent-return-false-in-worker-loops

When a worker has this shape:

```rust
let _ = sqlx::query("UPDATE ... SET last_attempt_at = NOW() WHERE ...").execute(&db).await;
// ... do work ...
if some_gate(&result) {
    return false;  // ← silent skip
}
```

It creates an **invisible cooldown lock-out**: the row's `last_attempt_at` is now stamped, so the next tick's SELECT excludes it for the cooldown duration, but no log or metric records that the skip happened. Operationally this looks identical to "no work to do" — but the worker is actually rejecting work it should be visible about.

**Why:** Caught 2026-05-29 in `discover_structured_backfill_worker::backfill_pass` (OMOIKANE-904). 1019 nav-chrome-only postings accumulated in 1h cooldown invisibly. Diagnosis took ~30min of manual DB poking (`SELECT COUNT(*) FILTER (WHERE last_attempt_at > NOW() - cooldown) FROM ...`) to identify that ~all "stuck" rows had been silently skipped at the MIN_CLEANED_LEN gate. A WARN + Prom counter would have answered the same question in 5 seconds of `docker logs | grep`.

**How to apply:** When writing or reviewing any worker that follows the "stamp before work" pattern (per OMOIKANE-786 + the discover_structured_backfill `structured_extract_last_attempt_at` pattern):

1. Every `return false` / early-skip branch MUST emit a `tracing::warn!` with enough context to identify the row (source_kind + source_id, or equivalent primary key) and the reason for the skip (raw_len + cleaned_len + threshold, or whatever gate triggered).
2. Every skip branch MUST increment a Prom counter with a label matching the reason. Use a single counter name with a `outcome="..."` label so PromQL `sum by (outcome) (rate(...))` answers "where is each tick's work going?" in one query.
3. Outcome labels MUST be enumerated in a drift-lock test (`for label in [...] { assert!(SRC.contains(label)) }`) so a future refactor can't silently drop one.

The four canonical outcome labels for any extract-style worker:
- `ok_written` — happy path
- `skipped_<reason>` — pre-extract gate fired (e.g., `skipped_short_cleaned`, `skipped_unserializable`, `skipped_dead_url`)
- `extract_failed` — upstream call (LLM, HTTP) returned Err
- (tick-level) `noop` — SELECT returned 0 rows, nothing to do

Pair with the existing per-tick `omoikane_<worker>_outcome_total{outcome="ok"|"noop"|"pass_failed"}` so you have BOTH the row-level breakdown AND the tick-level aggregate.

Related: [[omoikane-904-discover-structured-backfill-silent-gate]] (the diagnostic + fix that motivated this rule). The 200→100 MIN_CLEANED_LEN bump in the same MR is the tactical unblock; the observability is the strategic prevention so this class of bug doesn't recur silently.

**The literal anti-pattern to grep for in PR review:**

```rust
return false;  // followed only by `}` — no log, no metric
```

If you see it in a worker tick body, demand a WARN line above it before approving.

*Source: `memory/feedback_silent_return_false_in_worker_loops.md`*

### feedback-sops-persist-via-dmz-host

## Rule (CORRECTED 2026-06-01 04:00 UTC)

To persist a new env var into `omoikane-daemon`: edit `secrets/shared.env.encrypted` **in the `omoikane.coach/daemon` git repo** and open a normal MR. Do NOT edit the on-host copies at `/srv/omoikane-daemon/secrets/shared.env{,.encrypted}` — both files are REPLACED on every deploy by **AWX template 78 ("Deploy Omoikane Daemon")** which pulls a fresh copy from the daemon repo (path `secrets/shared.env.encrypted`).

The first version of this memory said the file was host-local. **That was wrong** and burned ~90 min of operator time on 2026-06-01:
- ~45 min watching host-side `>> shared.env` edits get wiped 4×
- ~30 min on the wrong "decrypt/edit/re-encrypt on-host" fix
- ~15 min after the next peer's MR merged + auto-deployed and re-overwrote the on-host file with the repo version
- ~5 min discovering the source-of-truth file in `/app/websites/omoikane.coach/daemon/secrets/shared.env.encrypted`

Proof from file metadata: after every deploy, both `shared.env` and `shared.env.encrypted` on each dmz host get fresh `Birth` timestamps matching the deploy time, with size identical to the repo file (not the locally-modified version). AWX deploy = SCP from repo → host, then `sops -d` on host.

## How to apply

### Where the source of truth lives

```
# REAL source of truth (in the daemon repo):
/app/websites/omoikane.coach/daemon/secrets/shared.env.encrypted

# Per-host variants (also in the repo) for host-specific vars:
/app/websites/omoikane.coach/daemon/secrets/shared.notrf01dmz01.env.encrypted
/app/websites/omoikane.coach/daemon/secrets/shared.notrf01dmz02.env.encrypted

# Deployed copies on each dmz host (overwritten on every deploy — DO NOT EDIT):
/srv/omoikane-daemon/secrets/shared.env.encrypted      # SCP target from AWX
/srv/omoikane-daemon/secrets/shared.env                # sops -d output, env_file for compose
```

### Tooling

```
# Age private key (already at this path on the gateway box):
/home/app-user/.config/sops/age/omoikane.txt

# sops binary:
/usr/local/bin/sops

# Age recipient (public key, needed for --age flag on re-encrypt because no .sops.yaml exists):
age1rvwducm3cykzwehze559uzpnacnyfc4rqa86p954q80kdepyg3fqfsu8fz
```

### The fix recipe

```bash
cd /app/websites/omoikane.coach/daemon
git fetch origin main --quiet
git worktree add -b kp/OMOIKANE-<TICKET>-... /tmp/daemon-<purpose> origin/main
cd /tmp/daemon-<purpose>/secrets

AGE_RECIPIENT="age1rvwducm3cykzwehze559uzpnacnyfc4rqa86p954q80kdepyg3fqfsu8fz"
SOPS_KEY=/home/app-user/.config/sops/age/omoikane.txt

# Decrypt
SOPS_AGE_KEY_FILE=$SOPS_KEY sops --input-type dotenv --output-type dotenv \
  -d shared.env.encrypted > /tmp/dec.env

# Idempotent edit via Python (never use `>>` — line endings trap)
python3 << 'PY'
import pathlib
p = pathlib.Path("/tmp/dec.env")
s = p.read_text()
keep_keys = ("MY_NEW_VAR",)
lines = [ln for ln in s.splitlines() if not any(ln.startswith(k + "=") for k in keep_keys)]
lines.append("MY_NEW_VAR=value")
p.write_text("\n".join(lines) + "\n")
PY

# Re-encrypt — MUST pass --age explicitly (no .sops.yaml)
sops --input-type dotenv --output-type dotenv --age "$AGE_RECIPIENT" \
  -e /tmp/dec.env > /tmp/enc.env.encrypted

# ROUND-TRIP VERIFY before commit (avoids 0-byte truncation disaster)
SOPS_AGE_KEY_FILE=$SOPS_KEY sops --input-type dotenv --output-type dotenv \
  -d /tmp/enc.env.encrypted | grep -q "^MY_NEW_VAR=" || { echo "ROUND-TRIP FAIL"; exit 1; }

# Replace + zeroize
mv /tmp/enc.env.encrypted shared.env.encrypted
shred -u /tmp/dec.env

# Commit + push + MR
cd /tmp/daemon-<purpose>
git add secrets/shared.env.encrypted
git commit -m "sops(secrets): add MY_NEW_VAR for X (OMOIKANE-<TICKET>)"
git push -u origin kp/OMOIKANE-<TICKET>-...
# Open MR + arm MWPS via GitLab API as usual; AWX template 78 fires on merge.
```

### Pre-push hook trap

Pre-push hook requires the YT issue to exist. **File the YT issue first** via `mcp__youtrack__create_issue`, get the assigned `idReadable` (e.g. OMOIKANE-1051), and use THAT in the branch name. The hook rejects unresolved IDs.

### Traps

- **`sops -e` without `--age` produces a 0-byte file** and there is no `.sops.yaml` in the repo. If you `mv` that 0-byte file over the source, you've destroyed the source. Always round-trip-verify before replacing.
- **Never `printf '\n...'` over SSH+bash -c** — the `\n` traps through quoting layers and you get literal `n`s. Use Python or a heredoc.
- **Never `>>` append to `shared.env.encrypted`** — it's a binary blob from sops's perspective.
- **The pre-push hook checks YT issue resolution** — file the issue first, use the YT-assigned ID in the branch name. YT IDs can collide with peer branch names that didn't file issues (e.g. peer branch `kp/OMOIKANE-1051-pacing-mode` had no YT issue, my next-filed YT issue auto-got 1051).
- **Grep your env-var checks correctly** — `grep -E "^CAPSOLVER="` does NOT match `CAPSOLVER_API_KEY=`. Use `^CAPSOLVER_API_KEY=` or `^CAPSOLVER` (no `=` anchor).

### Drift-check from the gateway box

```bash
# Verify a key exists in the source-of-truth shared.env.encrypted:
cd /app/websites/omoikane.coach/daemon
git fetch origin main --quiet
git checkout origin/main -- secrets/shared.env.encrypted
SOPS_AGE_KEY_FILE=~/.config/sops/age/omoikane.txt sops --input-type dotenv --output-type dotenv \
  -d secrets/shared.env.encrypted | grep '^MY_KEY='
```

If absent → file MR to add it. If present but container doesn't have it → check `docker compose exec omoikane-daemon printenv` (and fix your grep regex).

## When the bigger redesign is worth it

Three+ env vars added per session is the current pain rate. If the operator wants something better:
1. Add `.sops.yaml` with `creation_rules` so `sops -e` doesn't need `--age` flag every time. Quality-of-life only.
2. Move secret storage to Vault / SeaweedFS-secrets / similar. Daemon polls at boot. Larger rewrite but no more sops drift.

For now: edit the repo source via MR. Round-trip-verify before commit. AWX deploys it.

*Source: `memory/feedback_sops_persist_via_dmz_host.md`*

### feedback-sqlx-fromrow-struct-drift-silent-404

When a struct `#[derive(sqlx::FromRow)]` gains a column (via a new
migration or a struct edit), **every `query_as::<_, T>` site that
loads the struct must add the column to its SELECT** — or sqlx
errors at runtime, `unwrap_or(None|default())` swallows the error,
and the handler silently returns 404 / empty result.

**Why:** Caught 2026-05-29 on OMOIKANE-851. OMOIKANE-639 added
`priority_order INTEGER` to `ai_providers` + the `priority_order:
i32` field to `AiProviderRow`. The LIST handler's SELECT was
updated. The EDIT-form handler's SELECT was not. The latter
returned 404 "no such provider" on EVERY provider kind — even
though the row was present and visible on the LIST view two clicks
away. Operator hit it the first time they tried to swap from
Claude to DeepSeek; the diagnosis took 15 minutes of grep.

The deception is that `unwrap_or(None)` on `Result<Option<T>, sqlx::Error>`
swallows two distinct cases:

1. Row genuinely missing (`Ok(None)`)
2. Row present but sqlx couldn't decode it (`Err(...)`)

Both turn into `None` to the caller. The caller then renders a
"not found" response. No log line, no metric, nothing.

**How to apply:**

When you add a column to a `FromRow` struct OR to a table that
backs one:

1. `grep -n 'query_as::<_, MyStruct>' app/src/` — list every site.
2. Update every SELECT to include the new column.
3. Add a `compile-test` or unit test that runs `query_as` against
   a fixture so a future omission fails CI.
4. Or replace `unwrap_or(None)` with an explicit decode-error log:

```rust
// BAD — swallows decode error as "row missing"
let row: Option<T> = sqlx::query_as("SELECT ...")
    .fetch_optional(pool).await.unwrap_or(None);

// GOOD — logs the actual error so silent 404 becomes visible
let row: Option<T> = match sqlx::query_as("SELECT ...")
    .fetch_optional(pool).await {
    Ok(r) => r,
    Err(e) => {
        tracing::warn!(error = %e, "T query failed");
        None
    }
};
```

**Symptoms that this bug is happening:**

- A handler returns 404 / empty for a record that's clearly in DB
- The LIST view shows the row but the DETAIL/EDIT view 404s
- The 404 hits EVERY id, not just one
- The struct has a `#[derive(sqlx::FromRow)]` and a recent migration
  added a column
- `unwrap_or(None)` or `unwrap_or_default()` is on the query result

Canonical incident: [[omoikane-851-ai-provider-edit-form-404]] (if
written separately) or referenceable via OMOIKANE-851 / MR !2578.

*Source: `memory/feedback_sqlx_fromrow_struct_drift_silent_404.md`*

### feedback-sqlx-migration-row-mismatch-fix-forward

## Symptom

Daemon crash-loops on boot with:

```
Error: DB connect/migrate failed
Caused by:
    0: running sqlx migrations
    1: migration <version> was previously applied but is missing in the resolved migrations
```

Container goes `Restarting (1) N seconds ago`. `/metrics` unreachable. Workers don't tick.

## Root cause

Parallel CI pipelines pushed images out of order:
- Pipeline A's docker job built BEFORE Pipeline B merged
- Pipeline B finished first → ran migration N → DB has row in `_sqlx_migrations`
- Pipeline A finished later → pushed an OLDER image to `:latest` → that image DOESN'T have migration N's file embedded
- Daemon picks up the older image → sqlx::migrate! sees DB has row N but its embedded manifest doesn't → refuses to start (safety guard against ROLLBACK migrations)

This is the same shape as OMOIKANE-871 disk-out-of-space (migration row recorded but DDL not run), but the cause is image-staleness, not DB pressure.

## Fix-forward recipe

ALL three steps in sequence:

1. **Verify columns exist** before doing anything destructive:
   ```sql
   SELECT column_name FROM information_schema.columns 
    WHERE table_name='<table>' AND column_name LIKE '<prefix>%';
   ```
   If columns ARE present, the DDL ran successfully — only the migration row needs deleting.
   If columns ARE NOT present, the DDL was rolled back partway — `DELETE FROM _sqlx_migrations` IS still right (the next deploy will re-apply via `IF NOT EXISTS`).

2. **Delete the migration row** so the older binary boots:
   ```sql
   DELETE FROM _sqlx_migrations WHERE version = <version> RETURNING version;
   ```
   This is safe IF the migration uses `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` / similar idempotent shapes.

3. **Force-recreate both daemons** to clear the crash loop:
   ```bash
   ssh ... "cd /srv/omoikane-daemon/app && sudo docker compose up -d --force-recreate app"
   ```
   Daemon should boot to `INFO database connected, migrations applied`.

## Verification

After force-recreate:
- `docker ps` shows `Up N seconds (healthy)` (not `Restarting`)
- `docker logs --since 1m` shows `INFO database connected, migrations applied`
- Worker activity resumes within one tick

## Followup

When the next pipeline runs (any commit triggers a fresh build), the newer image WILL have the migration file embedded. On boot:
- sqlx sees migration N is NOT in `_sqlx_migrations` (we deleted the row)
- sqlx re-applies the migration → `ADD COLUMN IF NOT EXISTS` is a no-op → INSERT row back into `_sqlx_migrations` → consistent state.

No additional cleanup required.

## How to avoid (prevention)

The race is structural in any CI where parallel pipelines push to the same `:latest` tag without coordinating on ordering. Real fixes:
- Pin images by commit SHA in deploy job, not `:latest`
- Use `docker pull <sha>` in the deploy job
- Add a "newer-than-current" check in the deploy job that compares the candidate image's git SHA to the running container's

Until that's wired, every multi-pipeline-on-main day risks one of these. Diagnostic recipe is fast: 3 SQL queries + 1 force-recreate = <2 min.

## Caught in the wild

2026-05-29 OMOIKANE-907 deploy: pipeline 34635 failed in CI but the daemon HAD briefly deployed -907 successfully at 17:07, ran the migration, populated the columns. Then pipeline 34634 (OMOIKANE-908) finished docker build (had started PRE-907 merge) and pushed `:latest` at 17:11 → next daemon restart picked up the -908 image which doesn't have -907's migration file → crash loop. Fixed via this recipe in <5 min. Writes resumed at 17:20 UTC.

Cross-reference: [[omoikane-904-907-908-906-session-20260529]] (the broader session context).

*Source: `memory/feedback_sqlx_migration_row_mismatch_fix_forward.md`*

### feedback-systemd-user-slice-oom-score

## The rule

Do NOT run any **critical-path / escalation / paging / alerting** service as a systemd `--user` unit. Use a **system-level systemd unit** (or k8s pod with appropriate QoS class) instead.

## Why

systemd's `--user` slice has `OOMScoreAdjust=200` baked in as the default for `user@<uid>.service`. Every process spawned under `user.slice/user-<uid>.slice/user@<uid>.service/app.slice/<unit>.service` inherits that adjustment unless explicitly overridden.

OOM score is roughly: `(RSS / total_memory) * 1000 + oom_score_adj`. So oom_score_adj=200 adds a flat +200 to the score, making user-services almost always the highest-scored process during cgroup or global OOM events. The kernel's victim-selection scan picks them first — even when they have **tens of kilobytes RSS** and the actual memory hogs are 16-GB VMs or 6-GB JVMs.

This is **intentional good design** at the OS layer: better to kill a user-mode webhook than `pvedaemon` or `kubelet`. **But it makes user-systemd a terrible home for anything that must survive memory pressure.**

## How to spot the pattern

Look at the kernel OOM trace's `task_memcg=`. If it contains `user.slice/user-NNN.slice/user@NNN.service/app.slice/<svc>.service`, that's a user-systemd unit running under the +200 adjustment.

```
oom-kill: ... task_memcg=/lxc/VMID_REDACTED/ns/user.slice/user-1000.slice/user@1000.service/app.slice/alertmanager-twilio-bridge.service, task=python3, pid=2532284, uid=1000
Out of memory: Killed process 2532284 (python3) total-vm:28972kB, anon-rss:10080kB ... oom_score_adj:200
```

That 10 KB anon-rss Python script was killed in a host-global OOM event because its `oom_score_adj=200` outranked everything else's score-by-RSS.

## Caught 2026-05-15

`alertmanager-twilio-bridge.service` (the only Tier-1 SMS escalation path in the NL estate) runs as a `--user` unit inside the `nl-claude01` LXC (uid 1000 `app-user`). It's been killed multiple times during nlpve04 host-pressure events:
- May 13 12:34:11 — cgroup OOM inside nl-claude01 LXC
- May 14 22:05:12 — nlpve04 global OOM (same event that killed gitlabrunner02)

Each death is a ~10s window where Tier-1 SMS alerts get silently dropped. Operator chose to leave it where it is (with neo4j heap cap + nl-dmz01 RAM bump now mitigating the host-pressure root cause) but the architectural smell remains: **the most-important-to-survive service is in the slice systemd most-wants-to-kill.**

## How to apply

When choosing where to deploy a new alerting / paging / SMS-bridge / on-call-notifier service:

1. **First choice**: k8s Pod with `resources.requests` set (`Burstable` or `Guaranteed` QoS). Kubelet-managed oom_score_adj scheme protects critical pods; pod cgroup limits prevent collateral damage from other tenants.
2. **Second choice**: system-level systemd unit (not `--user`). `oom_score_adj` defaults to `0` for system services unless explicitly set. Configure `OOMScoreAdjust=-500` in the unit if it's truly critical (this makes the kernel preferentially spare it).
3. **Avoid**: systemd `--user` unit, especially inside an LXC under memory pressure. The OOM math is stacked against you.

## Override knob (if you must use --user)

In the unit file, add:
```
[Service]
OOMScoreAdjust=-100
```
This overrides the inherited +200. Negative values bias the kernel against killing this process. But this is a workaround — the architectural fix is "don't run critical paths as --user".

## Cross-references

- [[librenms_extender_fleet_deployment_20260515]] — the session where this was diagnosed
- [[feedback_pve_root_extender_cache_pattern]] — similar pattern: where the privileged work lives matters more than how it's invoked

*Source: `memory/feedback_systemd_user_slice_oom_score.md`*

### feedback-time-offset-replace-month-order

When constructing a fixed `time::OffsetDateTime` via the `.replace_*()` chain
starting from `now_utc()` (or any current-time source), the order is
significant:

**WRONG (panics on day 31 of a month whose next month has 30 days):**
```rust
let local = time::OffsetDateTime::now_utc()
    .replace_offset(utc_offset)
    .replace_year(2026).unwrap()
    .replace_month(time::Month::June).unwrap()  // ← panics on May 31!
    .replace_day(15).unwrap()
    ...;
```

**RIGHT (set day first):**
```rust
let local = time::OffsetDateTime::now_utc()
    .replace_offset(utc_offset)
    .replace_day(15).unwrap()       // ← always valid (no month has fewer than 15 days)
    .replace_year(2026).unwrap()
    .replace_month(time::Month::June).unwrap()
    ...;
```

**Why:** `time::OffsetDateTime::replace_month()` propagates the current day-of-month.
If `self.day() == 31` AND the target month has 30 days (Apr/Jun/Sep/Nov) — or
the day exceeds Feb's range — the call returns `Err(ComponentRange { name: "day", is_conditional: true })`.

**Failure cadence:** ~2 days per month. May 31 + Aug 31 + Oct 31 cause `replace_month(June/September/November)` to panic. Mar 29-31 cause `replace_month(February)` to panic in non-leap years.

**How to apply:**
- In every test or fixture builder using `.replace_*()` chains, set `.replace_day(15)` (or any value ≤ 28) as the FIRST replace call after `now_utc()`.
- Alternatively, construct via `time::Date::from_calendar_date(year, month, day).unwrap().with_hms(...).unwrap().assume_offset(offset)` — fully explicit, no propagation surprises.
- Grep audit: `rg 'replace_month\(' app/src/` and confirm every callsite either (a) follows a `.replace_day(<=28)` earlier in the chain or (b) constructs from a known-good source.

**Canonical incident:** 2026-05-31 00:16 UTC pipeline 35067 on MR !2709
(OMOIKANE-1001 uniform DISABLED env-flag refactor) failed on
`calendar_providers::tests::vevent_non_utc_input_converts_to_utc` at
`src/calendar_providers.rs:1972:47` because `now_utc().day() == 31` and
`replace_month(June)` tried to produce the non-existent June 31. Fixed
in commit `14113528` by reordering `.replace_day(15)` before
`.replace_month()` + the year replace (which is a no-op when year already
matches but kept for explicit intent). The test was originally written
when calendar-day mattered less; it lurked as a date-dependent flake.

Drift-lock idea (not yet shipped): a CI test that walks the source tree
and refuses `replace_month\(` callsites that aren't preceded by
`replace_day\(\s*([1-9]|1[0-9]|2[0-8])\s*\)` within 5 lines.

*Source: `memory/feedback_time_offset_replace_month_order.md`*

### feedback-verify-rebase-conflict-resolution-via-git-show

When using the Edit tool to resolve merge-conflict markers during `git rebase --continue`, **the Edit can silently fail** with "File has not been read yet" (because git rebase mutated the file out-of-band) AND the subsequent `git add` + `git rebase --continue` will still commit the file with conflict markers intact.

The pattern:
1. `git rebase origin/main` → conflict
2. Edit to remove `<<<<<<<` / `=======` / `>>>>>>>` markers
3. Edit returns error: "File has not been read yet before writing to it"
4. (User ignores the error, proceeds)
5. `git add app/src/main.rs` — git happily stages the WHOLE file, markers and all
6. `git rebase --continue` — commit lands with markers in source
7. `git push --force-with-lease` — broken commit is now on remote
8. MWPS armed → if pipeline passes (somehow), broken commit merges to main

## How to apply

After EVERY `git rebase --continue`:
1. `git show HEAD:<path>` to confirm the committed content is clean (no `<<<<<<<` / `=======` / `>>>>>>>` markers)
2. `cargo check` / `cargo test` (or language-equivalent) — conflict markers are syntactically invalid in Rust, so compile catches them
3. ONLY THEN push

If the Edit tool returned an error during conflict resolution, the fix MUST be re-applied (re-Read the file first, then re-Edit, then re-add, then `git commit --amend`).

## Why this is sneaky

- `git diff --cached` after `git add` doesn't loudly flag conflict markers
- GitLab MWPS doesn't pre-validate the diff — it just waits for the pipeline
- The pipeline takes 2+ minutes to surface the cargo-check failure
- During that window, a peer agent could see your MR + accidentally re-arm MWPS on the broken sha (caught 2026-05-26 — ccs-01 saw the issue, accidentally re-armed)

## Recovery (caught + fixed via fix-up commit pattern)

If the broken commit is already pushed:
1. Cancel MWPS via `POST /merge_requests/<iid>/cancel_merge_when_pipeline_succeeds`
2. Re-read the file (fresh, no stale tool cache), fix markers, save
3. Add + commit as a NEW commit (per project rule: "Prefer to create a new commit rather than amending"); message like `fix(<scope>): resolve merge-conflict markers in <file> from <branch> rebase`
4. Push (regular push, not force — adding new commit on top)
5. Re-arm MWPS with the new HEAD SHA

Related: any peer agents watching your MRs may auto-arm MWPS on the broken SHA; tell them in the coordination channel as soon as you discover the issue.

## Caught in

OMOIKANE-730 Phase 6c (MR !2488): commit `bfee072c` shipped with `<<<<<<< HEAD` / `=======` / `>>>>>>>` markers in `app/src/main.rs:55-59`. Fix-up commit `9917fba9` resolved.

*Source: `memory/feedback_verify_rebase_conflict_resolution_via_git_show.md`*

### feedback-vps-onboarding-addpath-mirror

When onboarding a new VPS as `route-reflector-client` on an FRR route reflector, ALWAYS check that the new peer has the same `addpath-tx-all-paths` setting as a sibling VPS peer in the same address-family. If the sibling has it and the new peer doesn't, the new VPS receives only best-path (1 path per destination) while siblings receive multipath (N paths). Reachability is unaffected but multipath diversity isn't.

**Why:** The 2026-05-06 txhou01vps01 onboarding added `route-reflector-client` + `next-hop-self force` on `neighbor 10.255.200.X` in both `grk8s-frr01` and `grk8s-frr02` but missed the `addpath-tx-all-paths` line that Zurich (`.9`) and Norway (`.7`) peers have. Discovered 2026-05-17 — TX was receiving 47 prefixes from each GR FRR vs CH/NO receiving 146. See [[edge-vps-bgp-audit-20260517]] §D1.

**How to apply:**
1. After adding the new peer, diff its config against a sibling: `vtysh -c "show running-config" | grep -A20 "neighbor <new-ip>"` vs `... "neighbor <sibling-ip>"`.
2. Specifically check the four lines that commonly drift: `route-reflector-client`, `next-hop-self force`, `next-hop-self`, `addpath-tx-all-paths`.
3. Mirror anything missing under `address-family ipv4 unicast` (and `ipv6 unicast` if used for iBGP overlay).
4. Apply with `clear ip bgp <new-ip> soft out` (no session reset needed for outbound policy change).
5. Update the onboarding checklist (referenced as `reference_vps_asa_onboarding_checklist.md`) to make this an explicit step rather than implicit.

**Where this rule kicks in:** Every VPS/DMZ host onboarding that joins iBGP AS65000. Not just GR FRRs — NL FRRs have a similar but distinct asymmetry (see [[edge-vps-bgp-audit-20260517]] §D2). Audit BOTH sides of the RR pair.

*Source: `memory/feedback_vps_onboarding_addpath_mirror.md`*

### feedback-workflow-chunk-concurrency-throttle

2026-06-16. A `Workflow` run that fanned out ~16 concurrent `agent()` calls (the default `min(16, cores-2)` cap) tripped a **server-side** rate limit — error "Server is temporarily limiting requests (not your usage limit) · Rate limited" — and **all 29 agents failed within 33s** because the internal retry/backoff exhausted during the same throttle window. Result was empty (`systemAudit:[]` etc.).

**Why:** thundering-herd burst. The throttle is global to the burst, so per-agent retries fire into the same closed window and give up together.

**How to apply:** For large workflows, bound concurrency well below the cap. Pattern that worked:
```js
const CHUNK = 4
async function retryAgent(thunk){ const a = await thunk(); return a != null ? a : await thunk() }
async function runChunked(thunks, size=CHUNK){
  const out=[]; for(let i=0;i<thunks.length;i+=size){
    out.push(...await parallel(thunks.slice(i,i+size).map(t=>()=>retryAgent(t)))) }
  return out
}
```
Run multi-stage items (e.g. compare→verify) **sequentially inside one thunk** so the verify always sees its compare result and concurrency stays low. Trades wall-clock for reliability — correct call under ultracode. Probe with ONE cheap `Agent` first to confirm the throttle window has passed before relaunching a big fan-out.

*Source: `memory/feedback_workflow_chunk_concurrency_throttle.md`*

### feedback-workflow-fanout-rate-limit-batch-resume

**2026-06-26, the orchestrator-plane-benchmark workflow (wf_f62922a0-129).** A 5-phase workflow (research → dimensions → benchmark-per-dimension → verify → report). The research (5 parallel) + dimension-synthesis succeeded (~1.65M tokens), but the `pipeline(dimensions, bench, verify)` fired **all 11 benchmark agents at once** and EVERY one died with `API Error: Server is temporarily limiting requests (not your usage limit) · Rate limited`. The final-report agent also died → `report` was null → `return report.overall_grade` threw → whole workflow failed.

**Lessons:**
1. **Don't burst a wide fan-out.** A `pipeline()`/`parallel()` over N items starts ~min(16, cores-2) agents near-simultaneously; that burst can trip a transient SERVER-side throttle (distinct from your usage limit) that fails the entire batch. **Batch it**: loop `for (i...; i+=BATCH)` running `pipeline(items.slice(i,i+BATCH), ...)` per group (BATCH≈4). The earlier phase that worked (5 parallel research agents) tells you the safe width.
2. **Resume is cheap recovery.** Re-invoke `Workflow({scriptPath, resumeFromRunId})` — the unchanged PREFIX (research + dimensions) returns from cache instantly; editing at the pipeline makes everything from there run live. Saves re-paying the expensive early phases. Edit the persisted script file (path is in the launch result) + resume, don't resend.
3. **Guard the final return** against a null synthesis agent: `if (!report) return { partial: confirmed.map(...) }` so a single rate-limited report agent returns the partial scores instead of crashing the run (and the partial can be synthesized on a follow-up resume).

[[orchestrator_control_plane_20260626]]

*Source: `memory/feedback_workflow_fanout_rate_limit_batch_resume.md`*

### feedback-youtrack-autocreate-authorized

**Rule:** When an approved plan calls for YouTrack work-tracking (epic + child issues, or standalone issues), create them directly via the YouTrack REST API. Do NOT produce markdown drafts and stop; do NOT ask "should I create these" once the plan is approved.

**Why:** Operator explicitly authorized auto-creation 2026-05-17 during the (b) refactor epic step: *"please call youtrack API and actually create this epic and any other youtrack issues are required during this and future sessions; thanks."* The drafts-only mode added friction without adding safety, since the operator was already running the create-script themselves immediately after.

**How to apply:**
- **Scope of authorization:** any YouTrack issue/epic creation that flows from a plan the operator has already approved in this or a prior session. Plans saved under `docs/plans/` with "Status: Approved" qualify.
- **Out-of-scope (still ask first):** creating issues that don't come from an approved plan; bulk-closing issues; state changes that propagate to parents (per [[feedback-yt-duplicate-close-auto-propagates]] avoid the word "duplicate" in close-comments when parent must stay open); modifying issue assignees; issues that touch security-sensitive fields.
- **Tooling preference:** prefer YouTrack MCP (`youtrack` server) tools when they work; fall back to direct REST API via curl + Bearer token when MCP has known bugs (per [[feedback-youtrack-mcp-state-bug]] for state transitions). Token lookup order: `$YOUTRACK_TOKEN` env → project `.env` → `~/.youtrack_token`.
- **Report after creation:** echo the created issue IDs back to the operator with a brief 1-line per issue summary so they can navigate to them.

**Notable companion rules:**
- [[feedback-yt-duplicate-close-auto-propagates]] — YT auto-propagates Done to parents when "duplicate" appears in close-comment
- [[feedback-youtrack-mcp-state-bug]] — MCP state transitions fail; use direct REST POST with `$type: StateBundleElement`

*Source: `memory/feedback_youtrack_autocreate_authorized.md`*

### feedback-yt-duplicate-close-auto-propagates

## The rule

When mass-closing YT issues and using close-comments that contain `"duplicate of <PARENT-ID>"` or similar duplicate-link phrasing, **always verify the parent's state after the batch**. YouTrack workflow rules can auto-propagate state transitions through the duplicate link, closing the parent unintentionally.

Specifically: if you close child issue C with a comment "duplicate of P", and YT has a workflow rule that detects this kind of "duplicate" relation, it may set P → Done automatically — even though you only ran the state command on C.

## How to apply

Pattern 1 — preferred when the parent must stay open:

```bash
# Avoid the word "duplicate" in the close-comment if the parent should stay open.
# Phrase it as "supersedes" or "rolled into" or "consolidated with" instead.
close_issue C "Closing — same condition is tracked in P; consolidating there."

# Then explicitly verify P is still in the expected state
yt-status P    # expect: Open / In Progress / whatever you intended
```

Pattern 2 — when both can close:

```bash
# Use "duplicate of" freely, but also explicitly close both
close_issue C "Closing as duplicate of P"
close_issue P "Closing — root cause fixed"
```

Pattern 3 — robust mass-close:

```bash
# After any batch, audit the issues you intended to keep open
for ID in <list-of-must-stay-open>; do
  curl -sk -H "Authorization: Bearer $YT_TOKEN" "$YT/api/issues/$ID?fields=resolved" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"$ID resolved={'YES' if d.get('resolved') else 'no'}\")"
done
```

## Caught 2026-05-15

During IFRGRSKG01PRD mass-close (35 stale + 2 duplicates). I closed `-83` (auto-spawned LibreNMS Device Down for grpikvm01) with comment "Closing as duplicate of IFRGRSKG01PRD-85". YT auto-closed `-85` (the operator-maintained "URGENT: bricked PiKVM" tracking issue) via workflow propagation — despite the operator having explicitly asked just minutes earlier to **keep -85 open** as a tracking marker.

Reopened -85 immediately, posted explanation comment. Total invisible-mistake window was ~60 s, no real damage, but easy to miss in a 36-issue batch.

## Cross-references

- (No memory yet for the IFRGRSKG01PRD mass-close session — could write one as `yt_mass_close_audit_resolve_gap_20260515.md` if pattern recurs)
- [[auto_resolve_regression_diagnosis_20260512]] — the parent context: ~28 % auto-resolve rate means weekly stale-cleanup is needed, which means mass-closes happen

*Source: `memory/feedback_yt_duplicate_close_auto_propagates.md`*

### feedback-zenodo-prereserve-doi-for-draft-deposits

When deserializing the response from `POST https://zenodo.org/api/deposit/depositions`, the top-level `doi` field is `None` for unsubmitted drafts. The reserved DOI lives at `metadata.prereserve_doi.doi` (and `metadata.prereserve_doi.recid` carries the integer recid).

**Why:** Zenodo's design — the API reserves a DOI immediately on draft creation (so the deposit page has a permanent URL) but only "promotes" it to the top-level `doi` field once the deposit is published via `POST /api/deposit/depositions/{id}/actions/publish`. Drafts stay reservable + deletable forever; published deposits are immutable.

**How to apply:**

When parsing Zenodo deposit responses, always check both fields:

```rust
pub fn effective_doi(&self) -> Option<&str> {
    self.doi
        .as_deref()
        .filter(|s| !s.is_empty())
        .or_else(|| {
            self.metadata
                .prereserve_doi
                .as_ref()
                .map(|p| p.doi.as_str())
                .filter(|s| !s.is_empty())
        })
}
```

Real Zenodo draft response shape (verified live against deposit 20402089 on 2026-05-26):

```json
{
    "id": 20402089,
    "doi": null,
    "links": {...},
    "metadata": {
        "prereserve_doi": {
            "doi": "10.5281/zenodo.20402089",
            "recid": 20402089
        }
    },
    "state": "unsubmitted",
    "submitted": false
}
```

The DOI shape is `10.5281/zenodo.{recid}` — the recid IS the deposit id.

**Caught 2026-05-26 OMOIKANE-812**: omoikane-daemon was returning `outcome="zenodo_failed"` on every preset edit despite the Zenodo deposit being created successfully because the response-shape model only read `body.doi`. Fix shipped via MR !2547.

**Reference:** `app/src/methodology_registry/zenodo_deposit.rs::DepositResponse::effective_doi` is the canonical implementation; any future Zenodo client code that extracts DOIs should call this method, not match `body.doi` directly.

**Related**: `[[omoikane-724-followup-operator-decisions-20260526]]` — the Zenodo-only mint mode decision that surfaced this gap (it was masked under DataCite-dual-mint mode because DataCite's response shape is different).

*Source: `memory/feedback_zenodo_prereserve_doi_for_draft_deposits.md`*

### feedback-zfs-dio-diagnostic-recipe

When a PVE VM shows `qmpstatus: io-error` with `I/O status: nospace` but the underlying ZFS pool is NOT actually full (`zpool list` capacity well below 100 %), DO NOT trust the "nospace" label. QEMU's qcow2 driver maps EIO from cluster-allocation writes to ENOSPC, so a true EIO from ZFS reads as "nospace" at the QMP layer. Use this 3-command diagnostic to confirm/exclude the OpenZFS 2.3 `dio_verify_wr` race in <60 seconds:

```bash
# 1. Check ZFS for verify-write errors (non-zero = likely DIO race)
ssh root@<pve-host> "zpool events -v | grep dio_verify_wr | tail -5"
# Look for: ereport.fs.zfs.dio_verify_wr, dio_verify_errors counter > 0
#          zio_err = 0x5 (EIO), zio_stage = 0x2000000 (DIO_CHECKSUM_VERIFY)

# 2. Check the QEMU process for cache.direct=true on the failing drive
ssh root@<pve-host> "cat /proc/$(pgrep -f 'kvm.*-id <vmid>')/cmdline | tr '\0' '\n' | grep -E 'cache|aio' | head"
# Vulnerable signature: "cache":{"direct":true,"no-flush":false} + "aio":"io_uring"
# (PVE default for SCSI/Virtio data disks in cache=none mode)

# 3. Check the ZFS direct property on the dataset
ssh root@<pve-host> "zfs get direct <pool>"
# If 'standard' (the OpenZFS 2.3 default) → vulnerable
# If 'disabled' (pre-2.3 behavior, our fix) → safe
```

**Why:** `man zfsprops` says `direct=standard` honours O_DIRECT. ZFS 2.3 added a post-write CRC verify (`DIO_CHECKSUM_VERIFY`) that catches guest userspace mutating the DMA buffer mid-flight. On mismatch, ZFS returns EIO; qcow2's cluster-allocation path maps that EIO to ENOSPC; QEMU `werror=enospc,stop` pauses the VM. The pool is fine — the VM is not.

**How to apply:** Whenever you see "VM paused with io-error nospace" on PVE + ZFS, run the 3 commands above BEFORE assuming pool ENOSPC, fragmentation, or qcow2 size limits. If all 3 line up (DIO errors present + cache.direct=true + direct=standard), apply the fix from [[nl-gpu01_zfs_dio_race_root_cause_20260514]] and resume the VM. The whole diagnostic + fix is <5 minutes vs hours of looking at the wrong thing.

Caught 2026-05-14 — wasted ~30 min initially on ENOSPC angle (zpool list, dataset quotas, qcow2 file_length, refreservations) before realising QMP "nospace" was a lie. Don't repeat that.

*Source: `memory/feedback_zfs_dio_diagnostic_recipe.md`*

### feedback_always_screenshot_visual

NEVER assume something visual/graphic/color is on the website from looking at the code. ALWAYS use Playwright screenshots before claiming such changes completed.

**Why:** Code can be correct but CDN caching, Hugo build issues, CSS bundling, or pipeline failures can mean the live site doesn't match. The user was burned by claims of "deployed" that weren't visually verified.

**How to apply:** For ANY visual change (colors, layout, positioning, new UI elements), the completion check MUST include:
1. Wait for CI pipeline to succeed
2. Take Playwright screenshot of the live site
3. Read and analyze the screenshot
4. Only then report completion

*Source: `memory/feedback_always_screenshot_visual.md`*

### feedback_cisco_small_business_cbs_ssh

When you encounter a Cisco switch on the SMB side of the product line (CBS 250/350, SG 200/300/500, SF series — anything running `cbs_ros` or `Sx-series ROS` firmware, NOT Catalyst IOS), both the device AND the automation client need non-default configuration before netmiko-based drift-sync / deployment will work.

## Rule

**Device side (required once per switch):**
```
configure terminal
 ip ssh password-auth
end
copy running-config startup-config     (or: write memory, accepts Y on "Overwrite file [startup-config]")
```
Verify with `show ip ssh` — look for `SSH Password Authentication is enabled.`

**Client side (netmiko):** use `device_type="cisco_s300"` (covers SG200/SG300/SG500 and CBS250/CBS350 — single driver class). Do **not** use `cisco_ios` — it ReadTimeouts on prompt detection because CBS wraps prompts in ANSI escape codes (`\x1b[K…#`).

## Why

**Why:** CBS firmware defaults to `ip ssh password-auth` **disabled**. When off, the SSH server advertises NO password auth method → paramiko/netmiko can't authenticate at SSH layer and reports `Authentication to device failed` (even though a human using OpenSSH can still connect via the "none" method and then hit the CLI login prompt). Additionally, CBS CLI uses ANSI escape codes around the prompt and `terminal datadump` instead of `terminal length 0` for pager control. Netmiko's `cisco_s300` class sets `ansi_escape_codes=True` + uses `terminal datadump` + handles `write memory` confirmation flow correctly. `cisco_ios` does none of this. Confirmed 2026-04-24 on gr-sw01 + gr2sw01 (CBS 350, firmware cbs_ros 3.5.3.2). Authoritative per Cisco CBS 350 CLI Guide (Telnet/SSH/Slogin commands) + netmiko `cisco_s300.py` source comment.

## How to apply

- When onboarding a new Cisco SMB switch to drift-sync or deploying it via IaC: first SSH in manually (the double-CLI-login is tolerable for a human), enable `ip ssh password-auth` + save, then add to the `device_driver_overrides` map in `network/scripts/detect_drift.py` + `auto_sync_drift.py` with value `cisco_s300`. The `netmiko_type_map` default `'Switch': 'cisco_ios'` stays — only CBS/SG devices override.
- Heuristic for identifying CBS vs Catalyst: `show version` reporting an `Active-image: flash://system/images/image_cbs_ros_*` file or `Sx-series` image is CBS/SG. Catalyst shows `IOS Software` or `IOS-XE Software`.
- If netmiko returns `ReadTimeout: Pattern not detected: '\x1b\[K…#'` on a switch that auth'd successfully, the fix is always `cisco_s300` not a timeout bump.

*Source: `memory/feedback_cisco_small_business_cbs_ssh.md`*

### feedback_converge_diverged_live_branch_in_worktree

When the live working tree (what crons run) sits on a dev branch that has diverged **both ways** from main
(main has work the branch lacks AND the branch runs live features main lacks — e.g. 2026-06-26: branch had
territory-gate / proactive-discovery / conservative-remediation / reconcile dark-fix that were never MR'd),
**do NOT `git reset`/`checkout main` blind** — that un-deploys the branch's live features.

**Why:** A blind advance loses whichever side main lacks. A whole-branch merge can drag old versions if the
branch carries a `git add -A` snapshot commit. The classifier/Runner/governance files are live + high-stakes.

**The lose-nothing pattern (proven 2026-06-26, drift 105→0):**
1. **Merge in an ISOLATED worktree** (`git worktree add wt origin/main; cd wt; git merge <branch>`) so the
   live tree never sees a conflict marker. The 3-way merge uses the merge-base, so it ADDS the branch's
   genuine new features without reverting main (check `git diff origin/main --stat` = mostly insertions).
2. **Triage conflicts:** auto-generated files (wiki/**, interaction-graph.json, scorecards) → `--ours` then
   regenerate (don't hand-merge ~60 of them). Real conflicts → resolve keeping BOTH sides (union alert
   lists; for "stale doc vs comprehensive doc" take the comprehensive one IF the other side's unique content
   auto-merged as separate files — verify that). Workflow JSON exports → the live n8n DB is the truth, the
   export is just a doc, so either side is functionally lossless.
3. **VERIFY both sides present + everything parses BEFORE landing** (grep every main deliverable AND every
   branch feature; py_compile/json/yaml all changed files). This is the lose-nothing gate.
4. Land via MR (CI may fail on spec-lockstep → `check-spec-code-lockstep.py --update-manifest`).
5. **Only then advance the live tree** (`git checkout -B main origin/main` after removing redundant untracked
   files) — safe because main now provably ⊇ the branch. The branch stays pushed = recoverable.

**Guarantee:** branch pushed (recoverable) + main untouched until a verified MR = nothing can be lost even if
the merge is botched.

**Gotcha caught:** parsing `git status -s` with `ln[3:]` breaks if the helper does `.stdout.strip()` (strips
the first line's leading status-column space → column shift). Use `git diff --name-only` + `git ls-files
--others --exclude-standard` for clean one-path-per-line output instead.

**Also:** cron-regenerated tracked artifacts (interaction-graph/registry/scorecard/curriculum/wiki) churn in
place between commits — exclude them from any "uncommitted = real work" signal or it stays falsely amber.

See [[gateway_governance_branch_is_active_wip_20260624]] (now RESOLVED) and [[orchestrator_benchmark_gap_closing_20260626]].

*Source: `memory/feedback_converge_diverged_live_branch_in_worktree.md`*

### feedback_direct_push_repos

These repos bypass the MR workflow: commit + push to main, let CI deploy. Confirmed by operator across four separate sessions.

## Repos

| Repo | Local path | Why direct-push |
|------|------------|-----------------|
| **claude-gateway** | `~/gitlab/n8n/claude-gateway` | Single-operator workflow — MR overhead unnecessary |
| **MeshSat** (products/meshsat) | `~/gitlab/products/meshsat` | Pipeline deploys from main automatically; branches add overhead for solo operator |
| **websites/papadopoulos.tech/kyriakos** | `~/gitlab/websites/papadopoulos.tech/kyriakos` | CI pipeline (`*/5` + on-push) handles build, Docker, AWX deploy. Local Hugo/Playwright testing wastes time since CI fetches live internal-API data (n8n webhooks, Gatus) that shape the final page. **Verify on the live URL after pipeline succeeds.** |
| **infrastructure/common** | `~/gitlab/infrastructure/common` | Shared ansible playbooks — MR friction not worth it for low-risk playbook tweaks that the operator wants to re-run through AWX immediately |

**Apply-with-care rule (still applies to all four)**: narrow the commit to the exact files changed (`git add <files>`, not `-A`), write a 1-line subject + why, run one smoke test after push (re-trigger AWX / reload CI / fetch live URL) before calling the change done.

## NOT applicable — these have real MR workflows

| Repo | Workflow | Reason |
|------|----------|--------|
| `infrastructure/nl/production` | MR via Atlantis | CI-driven Netmiko/NAPALM deploy pipeline, K8s OpenTofu via Atlantis. See MR !249 pattern. |
| `infrastructure/gr/production` | MR (mostly) | Same class as nl. **Exception**: `network/oxidized/*` snapshots are direct-to-main (Oxidized auto-sync convention, see gr/production@d894c64). |

## Why this file exists

Four separate `feedback_push_to_main*` / `feedback_*_push_direct` / `feedback_*_direct_push` memories drifted into existence across sessions, each capturing the same rule for a different repo. `memory-audit.py` flagged two as a cluster on 2026-04-19 (max_sim=0.825), which prompted consolidating all four. Removed originals:

- `feedback_push_to_main_gateway.md` (claude-gateway)
- `feedback_push_to_main.md` (MeshSat)
- `feedback_website_push_direct.md` (portfolio site)
- `feedback_infrastructure_common_direct_push.md` (infrastructure/common)

Future "push directly to main for repo X" corrections should be added as a row to the table above, not as a new file.

*Source: `memory/feedback_direct_push_repos.md`*

### feedback_dont_disturb_foreign_repo_working_tree

**2026-06-27, doing the IFRNLLEI01PRD-1452 judge-fooled alert: I made + recovered a real mess on the infra repo.** The reusable lessons:

## 1. NEVER blind `git stash`/`checkout`/`-b` on a shared repo's LIVE working tree
The `~/gitlab/infrastructure/nl/production` tree was **on an active branch `agora-dashboard` with the operator's uncommitted WIP** (HolisticHealth/RiskAudit alerts being added to `agentic-health-alerts.tf` + main.tf changes) — NOT on main. My `git stash -q; git checkout main; git stash pop` CONFLICTED and left conflict markers + a broken branch. Same trap as [[gateway_governance_branch_is_active_wip_20260624]]. **RULE: to change a file in a shared repo, ALWAYS use a worktree off origin/main** (`git worktree add <wt> -b <branch> origin/main`) — never touch the live tree's branch/stash. Check `git branch --show-current` + `git status` FIRST.

## 2. Recovery when you DID disturb it (lose-nothing)
The WIP was safe in the stash throughout. Recovery: `git reset --hard HEAD` (clear the conflict — WIP is in the stash), `git checkout <original-branch>`, `git stash pop` (re-applies cleanly, same base), then **VERIFY 0 of your changes remain + their work is intact** (grep your marker = 0, grep theirs = present, `git diff | grep -c <your-marker>` = 0). If your edit got mixed into their stashed WIP (you edited before stashing), surgically Edit OUT only your blocks (don't `git checkout` the file — that nukes their WIP too). Delete the broken branch (local + remote).

## 3. agentic-health alerts: yml is DOC, .tf is DEPLOY; yml is 6-space
`prometheus/alert-rules/agentic-health.yml` (gateway repo) "was never wired to K8s — the .tf is the deployed truth." So an alert needs BOTH: the yml (source-of-record) AND `infrastructure/.../monitoring/agentic-health-alerts.tf` (HCL `kubernetes_manifest` PrometheusRule, rules as `{ alert = "..."; expr = "..." }` objects). **The yml `- alert:` indent is 6 spaces** (fields 8, sub 10, folded-desc 12) — I wasted many tries at 8/10/12; ALWAYS `cat -A` the adjacent alert + `python3 -c "import yaml; list(yaml.safe_load_all(...))"` to validate BEFORE committing (the gateway CI does NOT promtool/yaml-validate this file, so a broken yml merges silently). origin/main can be AHEAD of the gateway live tree (newer alert groups). The infra repo's pre-commit hook requires **`tofu fmt`** (OpenTofu — `terraform` is NOT installed). [[feedback_converge_diverged_live_branch_in_worktree]] [[feedback_verify_belief_not_rationalize_observation]]

*Source: `memory/feedback_dont_disturb_foreign_repo_working_tree.md`*

### feedback_etcd_per_node_skew_can_be_counting_artifact

When an etcd alert (etcdHighFsyncDurations / etcdHighCommitDurations / etcdHighNumberOfLeaderChanges) fires heavily on ONE control-plane member and rarely on its peers, do **not** conclude that member's disk/VM is the fault. The alert COUNT is dominated by leadership (the leader does more lease/heartbeat-sensitive work), by alert dedup/issue-spawn artifacts, and by histogram_quantile tail interpolation — none of which mean per-node latency differs.

**Why:** In the 2026-06-23 GR RCA ([[gr_grk8s-ctrl01_etcd_pve01_saturation_rca_20260623]]), grk8s-ctrl01 had 212 etcd triages vs 27/15 on grk8s-ctrl02/03 — looked like a grk8s-ctrl01 disk fault. It wasn't: all 3 members were co-resident on the same saturated host+pool, and **bucket-immune average fsync was identical and lockstep** (grk8s-ctrl01 was often the FASTEST; lifetime cum fsync 11.80ms = lowest of three). The real cause was cluster-wide host I/O saturation gated by a slow shared mirror disk. Chasing the "skewed" node would have wasted the investigation.

**How to apply:**
1. Compute **bucket-immune averages**, not p99 panels: `rate(etcd_disk_wal_fsync_duration_seconds_sum[5m]) / rate(..._count[5m])` per `instance` — pull all members' `:2381/metrics` and compare. If they're within ~10% and move together, the penalty is cluster-wide; stop localizing.
2. Check WHO is leader (`etcd_server_is_leader`) and `etcd_server_leader_changes_seen_total` per member — leadership concentration explains alert-count skew without any latency asymmetry.
3. Treat a scary "p99 = 600-1180ms" with suspicion when most fsync mass sits at 2-8ms (`le=0.008` cumulative) — it's often quantile interpolation across a sparse tail bucket; the real signal is the ~80ms mean + occasional real tails.
4. Verify causal DIRECTION at the event level: `fdatasync`/`slow fdatasync` log lines are below Raft — if they PRECEDE "lost leader"/"leader changed" by seconds, it's disk→etcd, not etcd-looping→fsync.
5. Confirm actual VM placement (`pvesh get /cluster/resources --type vm`) before assuming peers are on a different/quieter host — don't trust a remembered topology.

*Source: `memory/feedback_etcd_per_node_skew_can_be_counting_artifact.md`*

### feedback_gr_dmz_direct_ssh

Access gr-dmz01 via direct SSH over VPN tunnels, NOT via OOB stepstone (203.0.113.X:2222).

**Why:** The OOB stepstone won't stay active permanently. The VPN tunnels are always up and provide direct connectivity to GR site. Direct SSH is simpler and more reliable.

**How to apply:** Use `ssh -i ~/.ssh/one_key operator@gr-dmz01` for all GR DMZ operations in chaos-test.py, chaos-logs.py, and vpn-mesh-stats.py. The host resolves via DNS over the VPN.

**Note:** gr-dmz01 requires sudo for /srv/ access (`echo 'REDACTED_PASSWORD' | sudo -S`). Docker commands work without sudo (operator in docker group).

*Source: `memory/feedback_gr_dmz_direct_ssh.md`*

### feedback_greek_banned_phrase_sou_epanerxomai

The Greek phrase "Σου επανέρχομαι σύντομα" / "σου επανέρχομαι σύντομα" is
**operator-banned** in any Greek-language reply (agent-generated or static).

Correct form: **"Επανέρχομαι σύντομα."** (no "Σου" / "σου").

**Why:** Operator quote: «"Σου επανέρχομαι σύντομα." is NOT a valid greek
phrase ...instead "επανέρχομαι σύντομα." is». The verb επανέρχομαι is
intransitive in this idiom — adding "σου" makes it ungrammatical.

**Where this slipped in:**
- agentic-agri Triage Output Router holding messages (n8n workflow
  `7yq9wKuiSmmQR6OO`, Code node "Triage Output Router")
- Reference copy at `/agentic-agriops/n8n/code-nodes/triage-output-router.v0.3.js`
- Possibly other Greek-language replies once those are written.

**How to apply:**
- Add to banned-phrase section of every Greek-language SYSTEM_PROMPT
  (chat-advisor.py, support-triage.py, agronomy-advisor.py).
- Static templates: replace verbatim.
- When writing new Greek copy, never prefix επανέρχομαι with σου / σε / μου.

*Source: `memory/feedback_greek_banned_phrase_sou_epanerxomai.md`*

### feedback_greek_banned_word_evretiriasmena

The Greek word "ευρετηριασμένα" (past participle of ευρετηριάζω, "to index")
is operator-banned in any Greek-language agent reply. Operator considers it
awkward technical jargon that doesn't read as natural Greek for the
audience (Greek agricultural advisors).

**Replacements:**
- "ευρετηριασμένα" → "καταχωρημένα" / "καταγεγραμμένα" / "διαθέσιμα"
- "ευρετηριάζω"   → "καταχωρώ" / "καταγράφω"
- "ασύμπληρη"     → "δεν έχει ολοκληρωθεί" / "ελλιπής"

**Why:** Operator quote: "ευρετηριασμένα --> this is NOT a greek word;
please make this word not be used again". The word is technically a Greek
verb form but reads like translation-Greek, not natural conversational
Greek for the agricultural advisor audience.

**How to apply:**
- Pin a banned-vocabulary section in EVERY Greek-language agent's
  SYSTEM_PROMPT (chat-advisor, support-triage, agronomy-advisor, teacher-agent).
- Extend the list as the operator flags new awkward words.

*Source: `memory/feedback_greek_banned_word_evretiriasmena.md`*

### feedback_isolate_home_for_classifier_tests

Any test/BDD that runs `scripts/classify-session-risk.py` (or other gateway scripts that read `~/gateway.*` sentinel files) **must set `HOME` to an isolated empty tempdir** in the subprocess env, plus `GATEWAY_DB` to a temp DB.

**Why:** the classifier's band engine (autonomy-forward) is gated on `os.path.exists(os.path.expanduser("~/gateway.autonomy_forward"))`. The live host (`nl-claude01`) has that sentinel **ON** ([[autonomy_forward_gate_live_20260616]]), so an irreversible plan (e.g. `terraform destroy`) classifies **high + `irreversible:*`** locally — but a clean CI runner (`python:3.12-slim`, no sentinel) classifies it **mixed (`iac-plan-or-apply`)**. A BDD assertion keyed on the high/irreversible signal passes locally and **fails in CI** (cost: 1 red pipeline, 2026-06-23, IFRNLLEI01PRD-1260 D2 Round 2).

**How to apply:** in the test runner set `env["HOME"]=tempfile.mkdtemp()` (cleaned in `finally`) + `env["GATEWAY_DB"]=temp_db_from_schema()`. Assert **mode-independent invariants** (e.g. destructive ⇒ `auto_approve_recommended is False`) rather than sentinel-dependent band labels, unless you deliberately create the sentinel inside the isolated HOME. Canonical: `spec/steps/steps.py::_run_classifier` in claude-gateway. General lesson: hermetic tests — never let a test read host state the CI runner lacks.

*Source: `memory/feedback_isolate_home_for_classifier_tests.md`*

### feedback_librenms_env_var_naming_variants

`/app/claude-gateway/.env` defines six overlapping LibreNMS vars:
- `LIBRENMS_URL` + `LIBRENMS_API_KEY` — **NL** instance (nl-nms01)
- `LIBRENMS_GR_URL` + `LIBRENMS_GR_API_KEY` — **GR** instance (gr-nms01)
- `LIBRENMS_NL_KEY` and `LIBRENMS_GR_KEY` — duplicate aliases (sometimes-set, sometimes-not)

`LIBRENMS_GR_API_TOKEN` does NOT exist. `LIBRENMS_API_TOKEN` does NOT exist. **Always _KEY, never _TOKEN.**

**Why:** Three concurrent Claude sessions on 2026-05-11 (IFRGRSKG01PRD-209, -217, -231) each burned ~5 minutes grepping `~/.env` and trying every name variant before finding the working one. The friction is real and recurring.

**How to apply:**
- For NL LibreNMS API calls: `curl -H "X-Auth-Token: $LIBRENMS_API_KEY" "$LIBRENMS_URL/api/v0/..."`
- For GR LibreNMS API calls: `curl -H "X-Auth-Token: $LIBRENMS_GR_API_KEY" "$LIBRENMS_GR_URL/api/v0/..."`
- Endpoint hostnames if you don't have the URL var: `https://nl-nms01.example.net` (NL), `https://gr-nms01.example.net` (GR).
- Both API keys live in `.env` of `claude-gateway`. They are NOT in `~/.env` directly — must be `set -a && source /app/claude-gateway/.env && set +a`.

The two `_KEY`-suffixed aliases (`LIBRENMS_NL_KEY` / `LIBRENMS_GR_KEY`) are inconsistently populated; prefer `LIBRENMS_API_KEY` / `LIBRENMS_GR_API_KEY`.

*Source: `memory/feedback_librenms_env_var_naming_variants.md`*

### feedback_librenms_poller_stall_signature

When a LibreNMS site shows **many devices going ICMP-unreachable inside a ≤2-minute window and ALL recovering inside ≤10 minutes**, the first hypothesis must be **poller-side stall** on the LibreNMS host itself, NOT a real device or LAN outage.

**Why:** Real outages have one of these tells, all absent in a poller stall:
- A single shared infrastructure component (uplink switch, firewall, VTI tunnel) shows a corresponding eventlog entry at the same time.
- Recoveries are staggered (cold-boot of N devices = N different recovery times).
- A subset of "still down" devices remains after the wave — the truly-affected ones.

A poller stall produces: broad scope, synchronized recovery (poller catches up in one batch), and **zero corresponding device-side eventlog**. The 2026-05-11 02:08–02:14 UTC GR flap matched this exactly: 16 devices, all recovered inside 6 minutes, `gr-sw01` had zero eventlog entries via `/api/v0/logs/eventlog/gr-sw01` for the 90 minutes around the wave.

**How to apply:**
1. Before SSHing target devices or invoking device-side runbooks, query `/api/v0/logs/eventlog/<core_switch>` for the flap window. No entries → poller-side.
2. SSH the LibreNMS host (`gr-nms01` for GR, `nl-nms01` for NL) and check `journalctl -u librenms-scheduler -u librenms-poller --since "<flap_start>" --until "<flap_end>"`.
3. Check `/opt/librenms/logs/poller-wrapper.log` for stall / timeout entries.
4. Check whether a poller-config change preceded the flap (rule changes, threshold updates, device adds — `librenms_cororings_nlpve04_threshold_20260510` is one example of churn that can precede a stall).
5. Only after ruling out the poller, start treating the alerts as real device-down events.

This pattern also masks as "site outage" in the agentic alert pipeline — a flap-wave can spawn 3+ duplicate triage tickets for one incident (see `grskg_mass_flap_20260511.md`). Worth flagging early so the operator can collapse the tickets.

*Source: `memory/feedback_librenms_poller_stall_signature.md`*

### feedback_meshsat_hub_no_chaos

NEVER include hub.meshsat.net (container: meshsat-hub, meshsat-hub-nginx, meshsat-mariadb, meshsat-garbd) in chaos testing or Docker stop operations.

**Why:** The MeshSat Hub runs a Galera MariaDB cluster (meshsat-mariadb + meshsat-garbd) that is fragile. Stopping the hub container or its dependencies risks data corruption, cluster split-brain, or SST/IST sync failures. User explicitly flagged this as dangerous.

**How to apply:** hub.meshsat.net is excluded from WEB_SERVICES in mesh-graph.js, DOMAIN_MAP in chaos.js, and DMZ_CONTAINERS in chaos-test.py. Gatus monitoring (read-only HTTP checks) is fine and stays. Only chaos killing is blocked.

*Source: `memory/feedback_meshsat_hub_no_chaos.md`*

### feedback_never_clear_bgp_vps

NEVER run `clear bgp *`, `clear bgp ipv4 unicast *`, or `systemctl restart frr` on VPS nodes (notrf01vps01, chzrh01vps01).

**Why:** These VPS nodes carry REAL internet BGP sessions (AS64512 upstream to Terrahost AS56655, iFog AS34927). `clear bgp *` drops ALL sessions including the upstream eBGP — this causes a production outage for the autonomous system's IPv6 prefix (2a0c:9a40:8e20::/48). The 2026-04-11 chaos test recovery incorrectly ran `clear bgp *` on both VPS nodes.

**What to do instead:**
- Clear ONLY specific iBGP peers: `clear bgp ipv4 unicast <specific-peer-ip>`
- NEVER clear the upstream eBGP peers (2a03:94e0:f253::, 2a03:94e0:f254::, etc.)
- If VPS iBGP peers are stuck, wait for BGP timers (hold time 90s) to retry naturally
- Do NOT add static routes — ALL routing is BGP-driven

**How to apply:** Any BGP recovery after chaos tests must target ONLY the specific stuck peer, never use wildcards. Never restart FRR on VPS nodes.

*Source: `memory/feedback_never_clear_bgp_vps.md`*

### feedback_no_double_flock_same_path

Don't add a second `fcntl.flock(LOCK_EX | LOCK_NB)` on the same file path inside a function whose outer caller already holds an flock on that same path.

**Why:** Linux `flock(2)` is per-fd, not per-process. If a function opens `path.lock` with `open()` and flocks it, then internally calls another function that opens the SAME `path.lock` with a separate `open()` and tries to flock it again, the second `LOCK_EX | LOCK_NB` returns EAGAIN — the same-process holder is treated as a foreign holder. This produced a real production regression on 2026-04-23/24/25 in `scripts/chaos-test.py`: outer flock at line 802 of pre-fix code conflicted with inner `marker_lock()` at line 1024, ABORTing every `chaos-test.py start` invocation for 6 intensive sessions / 18 lost experiments before detection. Fix shipped 2026-04-25 as commit `8075721`. Full timeline + reproducer in `memory/chaos_cron_collision_20260423.md § Re-observation`.

**How to apply:** When you're about to add a `with marker_lock(...)` (or any `fcntl.flock` context) inside a function, audit the call stack above it: if any caller opens the same lock-file path and flocks it, you'll self-conflict. Resolutions in order of preference:
1. Remove one of the two locks. Usually the outer one is redundant if the inner is already cross-process correct (this was the chaos fix).
2. If both locks express different concerns and both are needed, give them DIFFERENT lock-file paths (e.g., `path.start.lock` for the outer concurrent-start guard vs `path.lock` for the cross-drill marker).
3. Never share a single lock fd across the nested calls — the inner code expects to acquire/release independently and that contract breaks when callers hold the same path on a different fd.

Diagnostic tells: an ABORT/collision message rendering all attribute fields as `unknown`/`n/a` (because `existing_marker=None` from a fresh session with no marker file present), combined with the SAME process running both locks. Cheapest reproducer:
```python
import fcntl
fd1 = open('/tmp/x.lock', 'w'); fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)
fd2 = open('/tmp/x.lock', 'w')
try: fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError as e: print(f'errno={e.errno}')  # → 11 (EAGAIN)
```

*Source: `memory/feedback_no_double_flock_same_path.md`*

### feedback_no_emojis

NEVER use emojis anywhere. Not in code, not in UI text, not in Matrix messages, not in YT comments, not in logs, not in status text.

**Why:** User explicitly prohibits emojis. The chaos.js frontend had emojis in baseline text and summary panel ("⚡", "⏸", "✅", "⚠️") — this is wrong.

**How to apply:** Any frontend text, CLI output, log messages, or user-facing strings must use plain text only. Use words like "PASS", "STANDBY", "WARNING" instead of emoji symbols.

*Source: `memory/feedback_no_emojis.md`*

### feedback_no_human_anchor_for_absent_operator

**2026-06-27 — the operator caught me about to build a human-in-the-loop tool for an absent human.** I'd designed IFRNLLEI01PRD-1451's "human/SME eval-label path" (operator labels N sessions → judge ground-truth). The operator stopped me: *"the human is actually absent for months now... is this going to require my involvement?"* — YES, as designed it did, which is the WRONG design.

## THE RULE
This whole platform exists because **the operator stopped voting on approval polls (notifications off) → autonomy-forward**. So any mechanism whose value depends on the human DOING something (labeling sessions, voting, manual review, answering a nudge) will **sit idle forever** and, worse, become a **new dark component** — the exact "looks-live-but-does-nothing" class this session spent all day hunting (dead judge, MemPalace, merged-not-deployed). A `JudgeHumanLabelsStale` alert on an unused labeling table would fire forever. **Don't build it.**

## WHAT TO BUILD INSTEAD — no-human ground-truth anchors
When you need a "ground truth" to calibrate an automated layer (e.g. the LLM judge, which was DEAD 3 weeks — [[llm_judge_dead_3weeks_resurrected_20260627]]), use an anchor that needs ZERO operator involvement:
1. **Outcome-based truth** (strongest) — did the auto-resolve's fix actually HOLD? (the incident's alert cleared AND stayed cleared / didn't re-fire within N hours). Pure data; measures the thing we actually care about — *did autonomy work*. Builds on the -1153 repeat-incident governance.
2. **Frontier-model cross-check** — periodically re-judge a sample with a FRONTIER model (Opus) vs the local gemma judge; divergence = drift. This is exactly what would have caught the dead judge (Opus 4.5 vs local -1). Costs compute, not the operator's time. Mirrors the existing two-judge calibration (`docs/judge-calibration-2026-04-19.md`, 85% agreement baseline).
3. **The deterministic hard-trajectory layer** (already exists) — `session_trajectory` objectively checks "did the required steps happen"; already anchors the composed-verdict.

Operator chose **BOTH 1 + 2** (no-human). A human-label CLI may exist as a PASSIVE on-ramp (if the operator ever spot-checks) but NEVER as the primary anchor and NEVER with a "you haven't labeled" alert. **Litmus test for any new feature: if the absent operator never touches it, does it still deliver its value? If no — redesign.** [[autonomy_forward_gate_20260616]] [[feedback_operator_out_of_loop_complete_dont_defer]]

*Source: `memory/feedback_no_human_anchor_for_absent_operator.md`*

### feedback_no_internal_pipeline_jargon_in_user_replies

When an agent (chat-advisor, support-triage, agronomy-advisor, etc.) speaks
to a non-developer user, it MUST NOT mention internal pipeline phases,
ingestion stages, system architecture, or library names. Examples of jargon
that must never appear in user-facing replies:

- "Phase F του pipeline gov.gr/ΟΠΕΚΕΠΕ/ΕΕ"
- "external_corpus", "RRF", "wiki_articles", "session_transcripts"
- "Phase D / Lane 3 v0", "Tier 1", etc.
- Any backend table / module / signal name

**Why:** Operator tested the AI Advisor with a legal question
("μεταβίβαση ΔΒΕ μεταξύ συγγενών α' βαθμού") and the agent replied that
"η ενότητα regulations/ είναι ακόμη ασύμπληρη (Phase F του pipeline …)".
The agent confabulated "Phase F" — it never appeared in the system prompt
— and exposed implementation details the advisor neither knows nor cares
about.

**How to apply:**
- Add explicit banned-vocabulary lists in agent system prompts.
- When a source is unavailable, say it plainly in user-language:
  "Δεν έχω άμεση πρόσβαση στο πλήρες κείμενο του Κανονισμού X —
  μπορείτε να ελέγξετε στο opekepe.gr ή στο eur-lex.europa.eu."
- Operator can extend the banned list as new jargon-bleeds appear.

*Source: `memory/feedback_no_internal_pipeline_jargon_in_user_replies.md`*

### feedback_no_multimb_bash_var_grep

Building a Cronicle-aware `job_scheduled()` helper for holistic-agentic-health.sh, I cached the full
~180-job `get_schedule` JSON (hundreds of KB–MB) in a bash variable and `echo "$VAR" | grep` per call.
On `nl-claude01` (which had `NodeSystemSaturation` firing) this **segfaulted the whole self-audit
script** (exit 139), twice.

**Why:** bash copies a large variable on every `echo`/expansion; doing that repeatedly under memory pressure
exhausts/corrupts the process. The 138-check holistic script was already memory-heavy.

**Rule:** when a shell helper needs to repeatedly search a large blob (API JSON, big file list), cache it to a
**file** (`curl ... > "$f"`; `grep -q PAT "$f"`), never a shell variable. PID-scope the temp file
(`/tmp/x.$$`) + `trap 'rm -f "$f"' EXIT`. Or stream once (`curl | grep -q`, no variable) if a single check.

**Also (process):** don't keep debugging a memory footgun on a LIVE self-audit script while the node is
saturated — revert to the last clean committed state first (I did: `git checkout`, holistic back to 92%/0-fail),
then fix the helper segfault-safe separately. [[health_audit_24h_20260627]]

*Source: `memory/feedback_no_multimb_bash_var_grep.md`*

### feedback_no_static_routes

NEVER add static routes on the ASA or any other device. ALL inter-site routing is BGP-driven (migrated 2026-04-10).

**Why:** The entire VTI architecture uses BGP with three-tier LP failover (Freedom 200, xs4all 150, FRR transit 100). Static routes would bypass BGP convergence and create routing inconsistencies. The user explicitly stated: "we do NOT add static routes on the ASA or anywhere else, we use BGP."

**How to apply:** If routes are missing after a chaos test, wait for BGP to converge (30-90s). If peers are stuck, clear only the specific stuck peer on the RR (not on VPS). Never touch VPS upstream sessions.

*Source: `memory/feedback_no_static_routes.md`*

### feedback_operator_out_of_loop_complete_dont_defer

**The operator is permanently OUT OF THE LOOP. There is no "remaining step (yours)." If I find myself writing "the one remaining step is yours" / "comment `atlantis apply`" / "merge the MR" / "you deploy this" — STOP. That step is MINE.** Complete it, monitor it through to the verified end-state, and report back AFTER it is actually done — not as a handoff.

**Why:** Operator instruction 2026-06-25, said sharply ("it is never mine — put that deep in your memory"). The entire autonomy-forward philosophy ([[territory_gate_20260625]], `docs/risk-appetite.md`) exists because the operator stopped voting on approval polls and is not watching. Ending a task by deferring the final action to them recreates exactly the stranded-on-an-unwatched-poll failure the whole system was built to kill. A task is not "done" when the code is pushed and an MR is open; it is done when the change is **applied and the live state is verified**.

**How to apply — when work ends in an infra/IaC MR (Atlantis) or any deploy:**
1. Drive it to completion myself: `atlantis plan` is auto/triggered → review the plan → comment **`atlantis apply`** on the MR (I have standing authorization for this; the operator directed it) → then merge.
2. **MONITOR the apply** — poll the MR notes / pipeline / Atlantis output until apply succeeds or errors.
3. **VERIFY THE CLUSTER END-STATE, not "apply succeeded"** — for a PrometheusRule: `kubectl get prometheusrule -n monitoring <name> -o yaml` shows the new rules AND Prometheus has loaded them (`/api/v1/rules` lists the alert). "apply complete" is NOT proof the live state is correct (see [[grafana_sidecar_oom_hardening_20260624]] — a bad apply reported complete while grafana crashlooped). [[feedback_verify_belief_not_rationalize_observation]].
4. If it errors, fix it and retry — do not punt the error back to the operator.
5. Report back ONLY after the live state is confirmed, with the evidence.

**Scope:** applies to atlantis apply, MR merges, deploys, cron installs, sentinel toggles, service restarts — any final action I'd be tempted to describe as the operator's to take. The ONLY things that legitimately wait for the operator are genuine POLL_PAUSE-band decisions (irreversible / real-jailbreak / out-of-appetite), and even those are paged via SMS, not left silent. Routine completion of work I started is never deferred.

*Source: `memory/feedback_operator_out_of_loop_complete_dont_defer.md`*

### feedback_pgrep_self_match_in_monitors

**`pgrep -f <pattern>` matches the polling command's OWN command line.** 2026-06-26: I launched a background wait-loop `until ! pgrep -f run-qa-suite.sh >/dev/null; do sleep 5; done` to detect the QA suite finishing. The QA actually finished (scorecard written at 04:30Z), but the loop NEVER exited — because the loop's own command line contains the string `run-qa-suite.sh`, so `pgrep -f run-qa-suite.sh` always matched the loop itself (plus a leftover `sleep 5` child). I then reported "QA still running" for ~6 turns based on that self-matching pgrep, which was simply false.

**Why:** Persisted to disk + the EXTREME session length: a leftover monitor process can also accrue a garbage `etime` (saw `441077208 days`) from LXC process-accounting/clock glitches — looks like a hang, isn't.

**How to apply:**
- To wait on a background job, **prefer the harness signal** (Bash `run_in_background` re-invokes you on real exit; Monitor emits on its stream) over a hand-rolled `pgrep` poll.
- If you MUST `pgrep`/`ps|grep` for a process: exclude self with `pgrep -f <pat> | grep -v "^$$\$"`, match a UNIQUE token that is NOT in the poller's own command, OR check a completion ARTIFACT instead (e.g. "does the scorecard file exist / is it newer than the launch?") — an artifact check can't self-match.
- **A long-"running" background job is suspect** — before reporting "still running" again, verify against an independent signal (the output file, the result artifact), not the same poll. [[feedback_verify_belief_not_rationalize_observation]]

Real outcome once corrected: the QA had finished 754/1/5=99.21%; the 1 fail (637-events::concurrent_emit_no_loss) was a pre-existing event_log concurrency bug (WAL-transition race, no retry), fixed in scripts/lib/session_events.py `_emit_insert` (idempotent-WAL + retry), verified 0-loss, merged gateway MR !59. QA now green.

*Source: `memory/feedback_pgrep_self_match_in_monitors.md`*

### feedback_show_progress_during_long_waits

When the user submits an action that takes >2-3 seconds (chat agents,
report generators, slow API calls), provide **visible** progress feedback —
animated typing dots, spinner on submit button, or a "thinking" message
bubble. Static status text alone reads as a frozen UI and the user assumes
the system has stuck.

**Why:** Operator tested the AI Advisor chat surface live and reported
"there is no 'loading' animation that shows that the system is actually
working ... so that's a bit weird to wait without feedback" — the chat
takes 20-90s to return and the only feedback was a one-line muted-grey
status. Users perceive that as broken.

**How to apply:**
- For chat-style flows: insert a placeholder assistant bubble with animated
  dots + an elapsed-seconds counter while waiting.
- For form submits: show a spinner inside the submit button (CSS-only,
  toggle a `.busy` class).
- For background jobs: show a progress bar or activity indicator that
  updates at least once per second.
- Plain text status updates ("Working...") are never sufficient on their
  own. Pair with motion.

*Source: `memory/feedback_show_progress_during_long_waits.md`*

### feedback_sonos_volume

Sonos/Squeezebox speakers in this setup are very loud. **15% is the new standard** for all volume settings (music, alerts, notifications). TTS via Voice PE firmware uses 10% (on_tts_start). 20% is the absolute maximum.

**Why:** User corrected the previous 25% max rule — 15% is the new rule (2026-03-16). 40% was "ultra-loud". The notify platform and kitchen alert automation were both at 40%, now fixed to 15%.

**How to apply:** When adjusting any speaker volume in the HAHA setup, use 15% as default. The HA Voice PE device volume (media_player.home_assistant_voice_0957d2_media_player) controls the built-in speaker, not the Squeezebox outputs. Firmware TTS output is 10% (hardcoded in on_tts_start).

*Source: `memory/feedback_sonos_volume.md`*

### feedback_sqlite_wal_transition_lock_race

**Diagnosed + fixed 2026-06-26 in `scripts/lib/handoff_depth.py` (gateway MR !74), the qa/643-concurrent flaky failure.** Parallel `bump()`s lost updates (final depth 6/7 instead of 8).

**The bug (non-obvious):** `_connect()` ran `conn.execute("PRAGMA journal_mode=WAL")` on EVERY connect. On a fresh DELETE-mode DB, N concurrent writers race the rollback->WAL transition; switching journal mode needs an exclusive lock, so the losers get a transient **`sqlite3.OperationalError: database is locked`**. Crucially this fires inside `_connect`, which is called BEFORE the transaction's `try/except` block — so the error propagated out of `bump()` un-retried, and the bump silently vanished. `busy_timeout` did NOT save it because the WAL pragma ran before busy_timeout was set AND the journal-mode switch isn't fully covered by the busy handler.

**The fix (mirror `session_events._emit_insert`, whose docstring already described this exact race):**
1. Set `PRAGMA busy_timeout` FIRST, before any other statement.
2. Only switch to WAL **if not already WAL** (`PRAGMA journal_mode` check) and wrap in `try/except OperationalError: pass` — whichever writer wins sets WAL; the rest operate in the current mode (BEGIN IMMEDIATE + busy_timeout still serialize).
3. Wrap the WHOLE `BEGIN IMMEDIATE ... COMMIT` transaction in a bounded retry loop (`for attempt in range(8): ... except OperationalError: sleep(0.03*(attempt+1)); else: raise`). Never let a contended write silently no-op.
Result: stress 12/12 correct (8 parallel bumps), was ~2/3.

**Diagnostic lessons:**
- **Capture per-subprocess stderr under parallel load — do NOT `2>/dev/null`.** The "database is locked" Exit 1 was invisible until I redirected each parallel worker's stderr to its own file. The lost update looked like a mystery until then.
- **Reproduce with the REAL schema, not a minimal one.** A minimal-schema repro got depth=8 every time (masked the race); only `sqlite3 db < schema.sql` (what the test's `fresh_db` uses) reproduced the loss. Schema size/timing matters for contention races.

**Companion lesson (same MR):** a **static grep-count test assertion goes stale after a DRY refactor.** qa/1100 asserted `busy_timeout=30000` appears exactly 2× ("emit + emit_raw both set it"), but a consolidation routed both through one `_emit_insert` (appears 1×) — code correct, test stale. Fix = assert the PROPERTY (pragma present AND both paths `return _emit_insert(`), not a literal occurrence count. Don't game the code to satisfy a count; fix the assertion to verify the real invariant. [[feedback_sqlite_busy_timeout]] [[feedback_use_real_execution_data_for_regression]]

*Source: `memory/feedback_sqlite_wal_transition_lock_race.md`*

### feedback_url_bracket_autolink_bug

When asking an LLM to emit citations or URL references, instruct it to use
proper Markdown link syntax `[text](url)` — NOT bare URLs inside text-brackets
like `[Πηγή: title — https://example.com]`.

**Why:** Operator tested the AI Advisor chat live and reported a broken
citation link: `https://www.opekepe.gr/mitroo-agroton-kai-agrotikon-ekmetalleyseon%5D`
— the trailing `]` (URL-encoded `%5D`) was captured by marked.js's autolinker
because the URL appeared inside `[...]`. The original chat-advisor.py prompt
said:
> ALWAYS cite sources... Use `[Πηγή: <title> — <url>]` inline.

That format produces `[Πηγή: foo — https://x.com]` which marked.js auto-links
greedily as `https://x.com]`.

**How to apply:**
- **Prompt:** Instruct: "Use proper Markdown link syntax: `[text](https://url)`.
  Never put bare URLs inside text-brackets."
- **Defensive frontend:** also strip trailing `]`, `)`, `,`, `.`, `;`, `:`,
  `!`, `?` from href attributes after marked render — those characters are
  never valid as the last char of a real URL path:
  ```js
  html.replace(/(<a\s+[^>]*href=")([^"]*?)([\]\),.;:!?]+)(")/g,
               (_, p1, url, trail, p4) => p1 + url + p4 + trail);
  ```
- This pattern affects any markdown-rendered LLM output: chat-advisor,
  support-triage, agronomy-advisor, etc.

*Source: `memory/feedback_url_bracket_autolink_bug.md`*

### feedback_use_api_not_direct_db

When changing a service's configuration, **use its management API, never write directly to its database or its generated config files** — even if a direct edit looks faster.

**Why:** Operator instruction 2026-06-23 (verbatim): *"NEVER write directly to databases when there is an API method available."* Triggered while fixing the NPM proxy for the OpenArchiver migration — I started inspecting the NPM SQLite/DB to change a forward host. But that NPM is backed by a **cluster database** (the local `database.sqlite` was a 0-byte decoy); a direct DB write would (a) desync the cluster replicas, (b) be silently overwritten when NPM regenerates the nginx conf, and (c) skip validation/reload the API performs. The generated `*.conf` files have the same problem — they're rebuilt from the DB.

**How to apply:**
- Reverse proxy (NPM): `scripts/npm-api.py` ([[npm_api_access_20260623]]) — never touch `/data/nginx/proxy_host/*.conf` or the NPM DB.
- FreeIPA/IdM: `scripts/ipa.sh` ([[freeipa_admin_keytab_access_20260623]]) — `ipa` CLI / API, never the 389-ds LDAP backend directly.
- Same principle for n8n (public REST `/api/v1`, not the n8n sqlite/postgres), NetBox/YouTrack/GitLab/Proxmox/AWX (all have APIs/MCPs), Wallos, etc.
- If no API exists, say so explicitly and get operator sign-off before any direct DB write; prefer the app's own CLI/migration tooling over raw SQL.
- Persist API credentials in the cred store (`.env` + a `reference` memory) so the system authenticates automatically and never re-asks.

*Source: `memory/feedback_use_api_not_direct_db.md`*

### feedback_verify_agent_generated_doc_claims

**Subagents that author docs will invent specifics that sound right but are false.** 2026-06-26: I ran a 4-agent workflow (one per file) to update CLAUDE.md + README.md + README.extensive.md + MEMORY.md to the current state, from a shared prose brief. Two classes of error the agents shipped that only **human review against the live system** caught:
1. **Fabricated specifics** — an agent wrote that `holistic-agentic-health.sh` checks the orchestrator at "**§40**". The script actually tops out at **§38**; there is no §40 orchestrator check. It invented a plausible section number to make a sentence concrete.
2. **Count drift / source-of-truth mismatch** — the brief said "233 components"; the live `config/component-registry.json` had **239**. One agent used the brief's 233, another re-read the live file and used 239 → the two READMEs disagreed.

**Why:** A prose brief is a lossy snapshot; agents fill gaps with confident-sounding detail and don't cross-check a number against the file that owns it. The fabrication is invisible in the diff (it looks like every other true sentence).

**How to apply:**
- Before committing agent-generated docs, **verify every concrete claim against the live source** — section numbers (`grep` the script), counts (read the config/DB, not the brief), file paths (test they exist), metric names. Treat the brief as a hint, the live system as truth.
- Give doc-agents the **instruction to read the live file for any count** rather than trust the prompt, and to **not invent** a section/ID it hasn't verified.
- A link-check + a count-consistency pass across the sibling docs catches most of it mechanically (I caught the 233/239 split by grepping all three docs for the number).
- This is [[feedback_verify_belief_not_rationalize_observation]] applied to delegated output: the agent's confident sentence is the suspect — verify it, don't ship it. The doc work landed in gateway MR !60 only AFTER reconciling counts to live + deleting the §40 fabrication.

**2026-06-28 REINFORCEMENT — applies to agent FINDINGS/REPORTS too, and verify before ACTING, not just before committing docs.** A 9-agent "assess the system" workflow produced an issues table; I synthesized it into a report listing 7 orange-tier problems. Before fixing any, I re-verified against live sources and **3 of 7 were fabricated/misframed** and dissolved: (a) "4 Cronicle jobs 100% failing" — live API + the system's own `cronicle_metrics.prom` both showed **0 failures** (the named jobs don't even exist as events); (b) "registry-check.py flaky 12/128" — recent runs all `code=0`; (c) "proactive-discovery digest stale 3.5d" — it's a 7-day weekly digest (`DIGEST_INTERVAL_S=7d`), correctly mid-cycle ("digest not due — silent"). I nearly "fixed" non-existent bugs. **Sharpening:** a prose *report from agents* is as suspect as a prose brief, and trusting it costs more when you ACT (fix/commit) than when you merely report. Always spot-verify concrete claims (counts, "X is failing/dark/broken", cadences) against the live metric/API/script **before** acting — even when the report came from a careful verify-effort workflow. Fastest Cronicle health check: `cronicle_metrics.prom`, not the API. Full session: [[agentic_state_orange_verified_20260628]].

*Source: `memory/feedback_verify_agent_generated_doc_claims.md`*

### feedback_verify_belief_not_rationalize_observation

**Root-cause of a real reasoning failure (2026-06-23), to never repeat.** I claimed "the nl-pve01 AMT-reset auto-restarted the openarchiver LXC" — but `gr-pve01` had **89 days uptime** (never rebooted; the AMT reset was `nl-pve01`, a *different* host). I asserted causation from a confident mental model instead of from the system. Operator: "why do you think you screwed up the reasoning?"

**The three compounding failures:**
1. **Never verified my own action.** I said "left the old openarchiver stopped as rollback" but never checked — `vzdump --mode stop` had silently restarted it (it stops→backs up→**restarts** the source). I carried a false fact I'd never confirmed. (See [[feedback_wedged_iscsi_mount_needs_pod_reschedule]] sibling lesson on vzdump.)
2. **Defended the false fact instead of suspecting it.** When I saw it running (contradiction), I treated my belief as fixed and the observation as needing an excuse — so I hunted for a story that preserved "I stopped it" rather than concluding "my belief is wrong, investigate."
3. **A short-name collision handed me the wrong story.** Thinking in "nl-pve01" (not `gr-pve01` vs `nl-pve01`) let the recent salient NL event bleed across the site boundary onto the GR host. `uptime` (one command) would have refuted it instantly; I didn't run it.

**Rules I will hold to:**
- **The belief is the suspect.** When an observation contradicts what I "know", verify the belief first; do NOT rationalize the observation with a plausible cause. A high-confidence causal claim with zero evidence, when the evidence is one command away, is the exact thing the Proving-Your-Work directive forbids.
- **Never attribute a cause to a host without the FULL site-prefixed hostname + a confirming fact** (uptime, /var/log/pve/tasks, dmesg, journal). Same-named hosts at different sites (nlpveNN vs grpveNN) are a conflation trap — this is *why* the [P0] full-hostname rule exists.
- **Treat my own prior actions as unverified until I've checked their effect** — e.g. a "stop the source" migration step must be an explicit `pct stop` + `onboot 0` *verified after* the backup, because `vzdump --mode stop` restarts it.

*Source: `memory/feedback_verify_belief_not_rationalize_observation.md`*

### feedback_wedged_iscsi_mount_needs_pod_reschedule

When a Kubernetes pod is crash-looping for a long time with a **storage open / I/O error** on an iSCSI (democratic-csi) RWO PVC, the cause is often a **wedged iSCSI mount**, not a corrupt disk or app bug. A long-lived pod keeps its volume mounted across *container* restarts, so a mount that went into an EIO state (from an iSCSI session blip / target event) **never recovers** — only a POD reschedule forces a fresh detach (iSCSI logout) + re-attach (fresh login + mount).

**Why:** 2026-06-23, gatus (GR cluster) crash-looped ~28 days — `panic: unable to open database file: out of memory (14)` (SQLite CANTOPEN surfacing as "out of memory"). A diag pod proved the ext4 on the iSCSI vol (`/dev/sdh`) was mounted `rw` but **every read AND write returned `Input/output error`** (even `touch` and reading the db header). PVC was 1% full — not space. The pod was **56d old, its `VolumeAttachment` pinned to one node for 73d** — the container kept restarting but the wedged mount stayed. Fix = `kubectl scale deploy gatus --replicas=0` (wait for VolumeAttachment to clear, ~5s) `→ --replicas=1`. New pod got a fresh iSCSI attach, opened the DB cleanly (`Total endpoint keys to preserve: 40` — **zero data loss**), 1/1 Running. No fsck, no PVC recreate needed.

**How to apply (diagnostic order, least-destructive first):**
1. Confirm it's a wedged mount, not corruption: a diag pod mounting the SAME PVC that ALSO EIO's on a *fresh* attach ⇒ real on-disk/LUN corruption; but if the volume has been attached to one node for many days and never rescheduled, suspect a wedged session first.
2. **Try the cheap fix first:** `scale deploy 0 → wait for the VolumeAttachment to disappear (iSCSI logout) → scale to 1`. Re-attach usually clears EIO and preserves data.
3. Only if a *fresh* attach still EIO's → real corruption → fsck the block device (privileged, volumeMode block) or, for non-critical data, delete+recreate the PVC (storageClass `-delete` reaps the LUN).
4. Check the CSI controller health — if `democratic-csi-iscsi-controller` is flapping (e.g. 2000+ restarts) it can make attach/detach slow; not always the root cause but note it.

Reusable check: `kubectl get volumeattachment | grep <pv>` shows how long/where the iSCSI session has been pinned. A multi-day attachment on a crash-looping pod is the tell. Related storage-vs-API principle: [[feedback_use_api_not_direct_db]].

*Source: `memory/feedback_wedged_iscsi_mount_needs_pod_reschedule.md`*

### gpu01-target-ram-32g

nl-gpu01 (PVE VM VMID_REDACTED on nl-pve03) target memory allocation = **32 GiB** (32768 MB). Set 2026-05-12 during the io-error/freeze RCA, alongside enabling `discard=on` on both qcow2 disks.

**Why:** Operator decided the additional 4 GiB elbow room for the agentic GPU workload (Ollama gemma3:12b + bge-reranker-v2-m3 + Docker containers) is worth the marginal increase in nl-pve03 host pressure. My initial recommendation of "keep at 28 G to avoid feeding the OOM-kill risk" was overridden because:
- The May 10 00:25 global_oom was a one-off, not a recurring pattern.
- The dominant freeze mode was qcow2 io-error (now addressed by `discard=on`), not OOM.
- Operator owns the cluster topology decisions per [[feedback_no_migration_off_nl-pve03]].

**How to apply:**
- Do not propose reducing nl-gpu01 below 32 GiB.
- nl-gpu01 uses PCI passthrough (RTX 3090 Ti); memory is DMA-pinned, ballooning is not possible — the allocation is fixed.
- If nl-pve03 host pressure recurs, look at *other* tenants (K8s nodes, nlcl01file02/nl-iot02/nlnc02, LXC caps, `zfs_arc_max`) — nl-gpu01 is locked at 32 G.

**Related:** [[feedback_no_zramswap_on_pve_hosts]], [[feedback_no_migration_off_nl-pve03]], [[nl-pve03_capacity_pressure_20260422]].

*Source: `memory/feedback_gpu01_target_ram_32g.md`*

### lib/devices.py expects CISCO_PASSWORD; nl-claude01 has CISCO_ASA_PASSWORD

When writing one-off Python that imports `infrastructure/nl/production/network/scripts/lib/devices.py` (`build_profile`, `netmiko_connection`, `fetch_running_config`), the helper raises `EnvironmentError("CISCO_PASSWORD environment variable not set")` unless `CISCO_PASSWORD` is in the env. On `nl-claude01` the password is exported as `CISCO_ASA_PASSWORD` instead (CI-style naming for the ASA-deploy job).

Workaround for ad-hoc scripts:
```python
import os
os.environ.setdefault("CISCO_PASSWORD", os.environ["CISCO_ASA_PASSWORD"])
```

**Why:** `lib/devices.py:get_credentials()` only reads `CISCO_PASSWORD` (default user `operator`). The CI pipeline sets that var directly, but the operator-shell env on nl-claude01 uses `CISCO_ASA_PASSWORD` so the two don't line up.

**How to apply:** Any time you write a small Python script for live-device queries (read-only ACL/show-run/`show access-list` checks against nl-fw01 / nl-sw01 / nlrtr01 / etc.) and want to reuse the existing connection factory rather than hand-rolling Netmiko, do the `setdefault` before instantiating a profile. Don't propose changing the lib to read either name — the lib is the contract the CI deploy jobs depend on. Keep the alias in the ad-hoc script.

*Source: `memory/feedback_cisco_password_env_alias_for_lib_devices.md`*

### n8n task-runner sandbox blocks child_process — use SSH nodes

**The bug.** Building the session-replay endpoint workflow (G4 / IFRNLLEI01PRD-751, 2026-04-29) the Validate Input Code node tried to `require('child_process').execFileSync('sqlite3', [...])` for a session-existence check. Live execution failed with:

```
Module 'child_process' is disallowed [line 16]
  at /usr/lib/node_modules/n8n/node_modules/@n8n/task-runner/dist/js-task-runner/require-resolver.js:16:27
```

n8n 2.47.6 runs Code nodes inside `@n8n/task-runner` which sandboxes the Node.js `require()` resolver. `child_process`, `fs`, `net`, `dgram`, `os` and similar OS-bridging modules are blacklisted. There is no `NODE_FUNCTION_ALLOW_BUILTIN` escape on this version (the older monolithic `n8n-nodes-base.code` allowed it; the new task-runner does not).

**Why:** Code nodes execute inside a per-execution VM context that runs untrusted user code. Allowing `child_process` would let any compromised webhook upload + execute arbitrary binaries. The n8n team made the trade-off in the task-runner refactor.

**The fix.** Move subprocess work into an SSH node, which IS allowed to shell out. For G4, the sqlite3 existence check moved out of the Validate Input Code node and INTO the SSH Claude Resume command:

```bash
# In SSH node command (single bash chain):
SAFE_SID=$(printf %s "$SID" | sed "s/'/''/g")
CNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE session_id='$SAFE_SID'" 2>/dev/null || echo 0)
if [ "$CNT" = "0" ]; then
  printf '%s\n' '{"is_error":true,"error_type":"unknown_session","session_id":"'"$SID"'"}'
  exit 0
fi
cd /app/cubeos && unset CLAUDECODE && \
  claude -r "$SID" -p "$(printf %s "$B64" | base64 -d)" --output-format json --dangerously-skip-permissions
```

The Validate Input Code node was reduced to format-only validation (regex on session_id + payload shape).

**Same fix for the parse Code node:** the original design used `child_process.execFileSync('python3', ['emit-event.py', ...])` to emit a `session_replay_invoked` event_log row. That also blew up. Two options:

1. Drop the event emission from the Code node and rely on `poll-claude-usage.sh` (cron `*/30`) which scans Claude's JSONL log and writes to `llm_usage` — covers the cost/turns side. (We chose this for G4.)
2. Add a downstream SSH node after the Code node that runs `python3 emit-event.py --type session_replay_invoked --session $SID --payload-json "$JSON"`.

**Reusable rule.** Any n8n Code node that tries to:
- `require('child_process')`
- `require('fs')` for direct file write
- `require('net')` / `require('dgram')` for raw socket
- `require('os')` for env-style access (use `process.env` instead)

… will fail at run time with `Module 'X' is disallowed`. Catch this at design time: if your jsCode needs to shell out, put the bash logic in an SSH node and let the Code node only assemble inputs / parse outputs.

**Detection in retrospect.** When an n8n execution returns HTTP 200 with empty body (no error to the client), check `mcp__n8n-mcp__n8n_executions list workflowId=...` then `n8n_executions get id=... mode=error`. The full error message + line number is in `errorInfo.primaryError`. The sandbox error appears as `Module 'X' is disallowed [line N]` — distinctive enough to recognise immediately.

## How to apply

When designing a new n8n workflow that needs subprocess capability:

1. Default to: Webhook → Validate Format Code (pure JS, no `require` of OS modules) → If valid → SSH (does the actual work, including any DB lookup, subprocess, file I/O) → Parse Output Code (pure JS) → Respond.
2. If you must use `process.env`, that works. So does `Buffer.from(...).toString('base64')`. Pure-JS std lib is fine.
3. Existing legacy n8n workflows that pre-date the task-runner sandbox may have `child_process` calls that still execute — they probably run on a different execution path (legacy `n8n-nodes-base.code` typeVersion 1). Don't copy that pattern into new typeVersion 2 nodes.

*Source: `memory/feedback_n8n_sandbox_no_child_process.md`*

### n8n upgrades can silently break workflow nodes

After n8n upgrade (2.40.5→2.41.3), Switch V3.2 nodes silently broke — Prometheus alerts dropped for 4 days with no Matrix notification. The silence looked like stability.

**Why:** n8n node typeVersions can have breaking changes between releases. The `extractValue` function in n8n-core changed how it resolves nested parameters for Switch V3.2, requiring a `conditions.options` block that wasn't needed before. Nodes created via MCP/API are more vulnerable because the UI auto-populates required sub-objects but programmatic creation doesn't.

**How to apply:**
- After any n8n version upgrade, check recent error executions across all alert receiver workflows
- Silence in alert channels is suspicious — verify pipeline health, don't assume stability
- Compare programmatically-created nodes against UI-created equivalents for missing sub-objects
- The n8n API `POST /api/v1/workflows/{id}/deactivate` + `/activate` is needed after any workflow JSON update to reload webhook listeners

*Source: `memory/feedback_n8n_upgrade_regression.md`*

### netplan apply post-eBGP blows netlink timeout

`netplan apply` (and `systemctl restart systemd-networkd`) on a Linux VPS that has an eBGP session with a full IPv6 transit (e.g. iFog AS34927 → 241k prefixes) will hang in `activating` state forever, then exit-code 1, then restart-loop. The error in journalctl: "eth0: Could not enumerate links: Connection timed out" / "Could not enumerate routes: Connection timed out".

**Why:** When networkd starts/reconfigures, it iterates ALL routes/links via netlink. With ~250k IPv6 routes from FRR's BGP RIB pinned in the kernel, the netlink dump exceeds the default read window. networkd treats the timeout as fatal.

**How to apply:** When making netplan changes on chzrh01vps01, notrf01vps01, txhou01vps01 (any VPS with eBGP up): edit the netplan YAML, then **reboot**. Never `netplan apply` online. Operator confirmed this is the standing convention; my workaround attempts on txhou01vps01 (split files, restart loop, kill networkd) all failed for the same root cause. A reboot bypasses it because networkd starts before FRR + before the BGP table is loaded.

**Caught:** 2026-05-06, txhou01vps01 onboarding. Documented in edge/CLAUDE.md comment about anycast slot allocation.

**Workaround pattern that DOES work for runtime adds:** `ip addr add` directly bypasses networkd, persists until reboot. Used during onboarding to bring up anycast addresses before the netplan change could be applied via reboot.

*Source: `memory/feedback_netplan_apply_post_ebgp_blows_netlink_timeout.md`*

### nl-claude01 lacks `zip` — use Python zipfile

`nl-claude01` (app-user host) does **not** have the `zip` command installed. Calling `zip -r9 ...` returns `bash: zip: command not found`.

**Why:** Minimal Debian/Ubuntu container; `zip`/`unzip` are not in the base apt set. Operator hasn't installed them and we shouldn't auto-install.

**How to apply:** When you need to produce a `.zip` archive, skip `zip`/`unzip` and use Python's stdlib `zipfile` instead:

```bash
cd /tmp && python3 -c "
import zipfile, pathlib
src = pathlib.Path('my-archive-root')
with zipfile.ZipFile('my-archive-root.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for p in sorted(src.rglob('*')):
        if p.is_file():
            zf.write(p, arcname=str(p))
"
```

For extraction use `python3 -c "import zipfile; zipfile.ZipFile('foo.zip').extractall()"` or `tar -xf foo.zip` (some tar builds handle zip).

**Reverse direction:** Targets like `defra01agri01` and the GR boxes typically DO have `unzip`. Don't assume parity.

**Caught:** 2026-04-29 building the 9-source rubric bundle — first attempt with `zip` failed; Python zipfile worked first try and produced an identical archive (compressed to ~36% of source size at compresslevel=9).

*Source: `memory/feedback_zip_command_not_on_claude01.md`*

### no-foreign-vs-local-in-company-schema

When designing company-data tables or workers, NEVER bake an
"NL versus everything else" (or "local versus foreign") split into
the schema. Specifically:

- Don't name tables `foreign_*`, `non_nl_*`, `international_*`, etc.
- Don't have two parallel `*_company_enrichment` tables (one keyed on
  KvK, one keyed on `(name, country)`).
- Don't treat NL KvK as the privileged primary identifier with
  everyone else as second-class rows.

**Why:** "Foreign" is parochial — it bakes the originating
jurisdiction's perspective into the schema. From an Athens or London
operator's perspective, NL is foreign. The vocabulary embeds an
assumption about which jurisdiction is privileged that doesn't
generalise.

The binary NL/non-NL split also doesn't scale: adding a Greek AADE
registry would require a third table + third worker. Each jurisdiction
should be equally first-class from the start.

**How to apply:** Use a pluggable architecture from day one:

- `companies` (UUID PK) — one row per real legal entity.
- `company_identifiers` (many-to-one) — `(scheme, value)` PK; each
  identifier is one row. KvK becomes `scheme='nl_kvk'`, AADE becomes
  `scheme='gr_aade'`, LEI becomes `scheme='lei'`, etc. None is
  privileged.
- `company_enrichment` (one-to-one) — payload keyed on `company_id`.
- `RegistryAdapter` trait — one Rust impl per jurisdiction.

**Industry standards to reference (in order):**

1. **GLEIF LEI** (ISO 17442) — 20-char globally unique alphanumeric.
   Free, daily-refreshed CDF dump. ~2.5M entities (regulator-driven,
   sparse for SMEs). <https://www.gleif.org/en/about-lei/introducing-the-legal-entity-identifier-lei>
2. **OpenCorporates** — de facto open standard. `(jurisdiction_code,
   company_number)` PK across ~220M companies in ~140 jurisdictions.
   <https://api.opencorporates.com/documentation/API-Reference>
3. **ISO 6523 ICD** — catalog of identifier schemes themselves (VAT,
   DUNS, LEI, GLN, etc.) with numeric codes.
4. **OpenOwnership BODS** — JSON schema for entity + ownership data;
   `identifiers` array per entity. <https://standard.openownership.org/en/0.4.0/schema/reference.html>
5. **Schema.org Organization** — `identifier` = PropertyValue with
   `propertyID` (leiCode / duns / vatID / …). What brandfetch/Google
   already emit; aligning with this gives free web-of-data
   interop.

**Canonical incident:** OMOIKANE-914 (2026-05-29) shipped a
`foreign_company_enrichment` table with `(canonical_name, country_iso)`
PK. The operator called it out within hours as parochial + non-scaling.
Throttled the live worker (BATCH_SIZE=1 / TICK=3600 / COOLDOWN=86400)
and went back to the drawing board. Full redesign brief at
`/tmp/jurisdiction-aware-company-identity-redesign.md`. Tracked in
[[omoikane-916-jurisdiction-aware-company-identity]].

Cross-ref: [[feedback-runtime-env-wiped-by-awx-deploy]] (kill-switch
env vars need to land in sops canonical too if the throttle should
survive deploys).

*Source: `memory/feedback_no_foreign_vs_local_in_company_schema.md`*

### pct exec hang with running status = host I/O starvation, not LXC crash

When triaging "$service GUI unreachable" or "ssh into an LXC times out", run **all four** of these checks on the PVE host BEFORE concluding the LXC is corrupted, OOM-killed, or needs a reboot:

| signal | what it means |
|---|---|
| `pct status <id>` returns `running` | LXC isn't crashed |
| `pct exec <id> -- uptime` hangs with no output for 8s+ | LXC kernel scheduling is stalled |
| `ps aux` on the host shows the LXC's process with nonzero RSS | the process is still scheduled — just slowly |
| `cat /proc/loadavg` > 15 OR `free -h` shows zramswap ≥95% | host is the problem, not the guest |

If all four hold, the LXC is **I/O-starved by host pressure**, not broken. Rebooting the LXC won't help (and burns a service outage); the fix is on the host: balloon a heavy VM down, stop a non-critical VM, or let `pvestatd auto_balloon` reclaim if floors are set.

**Why:** observed 2026-05-04 on nl-pve01 (n8n LXC unreachable; web GUI timing out at HTTP 000 from outside). All four signals were present — `pct status` running, `pct exec uptime` silent for 8s, `node /usr/bin/n8n start` visible in host ps with 4.0G RSS, host load 22 / zramswap 100%. Matched the documented IFRNLLEI01PRD-704 host-pressure pattern. Without this signature, the obvious next step ("reboot the n8n LXC") would have been a wasted ~30s n8n outage that didn't address root cause.

**How to apply:** When an LXC-hosted service goes unreachable, the diagnostic ladder is:
1. External healthz/curl (confirms GUI down)
2. `pct status` on the host (rules out crash)
3. `pct exec ... -- uptime` (rules out kernel stall vs network)
4. Host `loadavg` + `free -h` + `cat /proc/swaps` (confirms host pressure)
5. THEN decide between balloon-shrink, VM-stop, LXC-reboot, or wait.

Skipping straight to step 5 without 2–4 leads to wrong remediation.

*Source: `memory/feedback_lxc_unreachable_check_host_pressure_first.md`*

### sed -i breaks single-file Docker bind mounts — restart container or write in-place

When editing a config file that's bind-mounted INTO a container as a single file (e.g. `host_path/nginx.conf:/etc/nginx/nginx.conf:ro`), `sed -i` does NOT propagate to the container. The container keeps reading the original inode forever, even though `cat host_path` shows the new content. `nginx -s reload` won't fix it because nginx re-reads from the same stale inode.

**Why:** `sed -i` (and most editors) write to a temp file and rename over the original — the inode changes. Docker's bind-mount remembers the original inode. Directory bind mounts don't have this problem because they bind the directory tree, not a specific file.

**How to apply:**

1. **Detection:** if you edited a file on the host, `nginx -s reload` returned OK, and the live response still shows the old behaviour — `docker exec <container> cat /etc/nginx/nginx.conf` (or `grep`) is the decisive check. If host file says `gzip off` but container says `gzip on`, you hit this trap.
2. **Fix (cleanest):** restart the container — `docker compose restart <service>` — so the bind mount remounts and picks up the new inode. Brief outage but config-clean.
3. **Fix (no restart):** write the new content in place without renaming. Either:
   - `cat new-content > /path/to/file` (truncates + writes, preserves inode)
   - Use `tee` for the same effect
   - **Avoid** `sed -i`, `vim` (default), `mv tmp file`, etc.
4. **Prefer directory bind mounts when designing new compose files** — `host/conf.d:/etc/nginx/conf.d:ro` is `sed -i`-safe; `host/nginx.conf:/etc/nginx/nginx.conf:ro` is not.

Caught 2026-05-07 fixing BREACH gzip on `nl-matrix01`: `sed -i /srv/matrix/nginx-conf/nginx.conf` then `docker exec nginx nginx -s reload` did NOT propagate. Probe still showed `Content-Encoding: gzip`. `docker compose restart nginx` fixed it. Same edit on `nlmattermost01` worked because that mount was a directory (`/etc/nginx/conf.d`), not a single file.

*Source: `memory/feedback_sed_i_breaks_file_bind_mounts.md`*

### session_log dead post-cc-cc (use sessions.duration_seconds for closure)

When computing session-closure / loop-duration / SLA metrics on
`/app/cubeos/claude-context/gateway.db`,
DO NOT join via `session_log.ended_at`. The most recent rows in that table
are `outcome='stale_cleanup' / resolution_type='auto_archived'` from
**2026-04-09 21:01:09** — a one-shot bulk cleanup. The post-2026-04-29
cc-cc dispatch path (9 receivers → `run-triage.sh` → spawn Claude Code
on `nl-claude01`) does NOT write `session_log` rows when a Tier 2
session finishes.

**Correct closure source:** `sessions.duration_seconds` joined on
`issue_id`. Verified live 2026-05-11: 41 of 43 sessions started in the
last 7 days have non-zero `duration_seconds`. Schema:

```sql
SELECT issue_id, duration_seconds FROM sessions WHERE issue_id = ?
```

Treat `duration_seconds == 0` AND `last_active` recent as "still mid-run
or abandoned" — count separately as "open", do not include in median.

**Why:** the cc-cc cutover (`memory/cc_cc_migration_complete_20260429.md`,
commit `484f5da`) moved Tier 2 spawn from OpenClaw → direct SSH. The
session-end writer that used to populate `session_log` was on the
OpenClaw side; it didn't migrate.

**How to apply:** any query that says "find closed sessions in last 7d"
or "SLA for issue X" must read `sessions.duration_seconds`. The
agentic-stats Outcomes block (`scripts/agentic-stats.py`, claude-gateway
MR !7, 2026-05-11) does this — copy that pattern. The lifetime
counters `totals.alerts_auto_resolved` / `totals.alerts_escalated`
still read from `triage.log` and are unaffected.

**Detection one-liner:**
```bash
sqlite3 gateway.db "SELECT MAX(ended_at) FROM session_log;"
# If output is > 2 weeks ago, you are about to query a dead table.
```

Caught while building the portfolio Outcomes tile — original SQL plan
was to join `triage.log` → `session_log.ended_at` for closure
timestamps; live probe returned 0 rows in last 7d.

*Source: `memory/feedback_session_log_dead_post_cc_cc.md`*

### systemd units must declare Restart=

Bare-bones systemd units with `Type=simple` and **no `Restart=` directive** mean any crash/OOM/segfault = permanent outage until manual intervention. The recovery mechanism is missing and you only find out the next time the failure triggers.

**Why:** 2026-05-11 — `n8n.service` was OOM-killed at 06:50 UTC, sat dead for 4h until operator reported live widgets offline. Unit file had only `[Service] Type=simple / ExecStart=n8n start` — no Restart=. This is a recurring shape (cf. IFRNLLEI01PRD-843 cron PATH, scanner_nuclei_silently_broken_20260504): when the recovery mechanism is silently missing, you discover it only when the original failure hits.

**How to apply:**

1. Any time we install/import a `*.service`, before enabling it `cat` the unit and verify `Restart=` is set. If absent, add a drop-in:
   ```
   /etc/systemd/system/<name>.service.d/10-restart.conf:
   [Unit]
   StartLimitBurst=5
   StartLimitIntervalSec=600

   [Service]
   Restart=on-failure
   RestartSec=10
   ```
2. **`StartLimitBurst` / `StartLimitIntervalSec` are `[Unit]` directives, not `[Service]`** — easy to get wrong. Verify post-install with `systemctl show <svc> -p StartLimitIntervalUSec -p StartLimitBurst`.
3. Verify the drop-in actually catches failures by `kill -9 $(systemctl show <svc> -p MainPID --value)` once during the install window — the PID should change and the service re-activate within `RestartSec`.
4. Use a drop-in (`*.d/10-*.conf`), don't edit the upstream unit file — drop-ins survive package upgrades.
5. Audit candidates: any service installed via npm/pip/script-based installer rather than a distro package; package maintainers usually get Restart= right, ad-hoc installers often don't.

*Source: `memory/feedback_systemd_unit_must_have_restart.md`*
