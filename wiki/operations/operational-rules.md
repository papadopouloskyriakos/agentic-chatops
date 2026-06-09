# Operational Rules

> Auto-compiled from 122 feedback memory files on 2026-05-06 00:48 UTC.
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
- Don't set up ASA-as-RR (adds deviation without HA benefit). Original YT-200 attempt at "fw01 as partial RR" was architecturally regressive.
- Don't add redundant ASA ↔ remote-ASA peerings beyond the existing VTI-direct ones (fw01 ↔ GR-ASA Freedom, rtr01 ↔ GR-ASA budget). They already exist for fast VTI convergence; more would be noise.

## Real HA improvement worth doing

Audit the 2 FRRs per site for failure-domain separation. If NL-FRR01 and NL-FRR02 are both on the same Proxmox host, losing that host loses the entire NL RR service. Same for GR. Move one to a different host/rack. That's the CCIE-shaped HA work, not more iBGP sessions.

*Source: `memory/asa_9_16_bgp_limitations.md`*

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
in `scripts/lib/ios_ssh.py`: `ssh_sw01_config`, `ssh_sw01_command`,
`sw01_port_shutdown(iface)`, `sw01_port_noshut(iface, force_poe_cycle=False)`.
Used by `scripts/chaos-port-shutdown.py` for the autonomous monthly
Freedom-ONT drill. Shared `CISCO_ASA_PASSWORD` credential. Single-try
semantics to avoid the 5-attempt block-for lockout.

*Source: `memory/feedback_never_ssh_sw01.md`*

### feedback_asa_shun_vti

ASA `threat-detection scanning-threat shun` auto-shuns any IP that breaches the per-host burst threshold. fw01's config:

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
| `nl_all_subnets` | NL mgmt/corosync/cctv/rooms/k8s/strongswan/dmz + **10.0.X.X/30** (rtr01↔fw01 budget transit, added 2026-04-22) | new NL subnet or transit lands |
| `ALL_VPS_OVERLAY` | `10.255.X.X/24` + `10.255.X.X/24` + `10.255.200.X/24` + VPS public IPs | new overlay/VTI subnet lands |

## Historical incidents

| Date | Missing from whitelist | Symptom | Fix |
|---|---|---|---|
| 2026-04-12 | `10.255.200.X/24` (VTI mesh) | IKE re-negotiation during chaos test → VTI endpoints shunned → VPN silently dead while interfaces showed up/up | Added to `ALL_VPS_OVERLAY` |
| 2026-04-22 | `10.0.X.X/30` (rtr01↔fw01 budget transit, new from 2026-04-21 migration) | Budget failover traffic + corosync retransmissions + NAT churn during Freedom-shut test → rtr01 (10.0.X.X) burst hit 10 pps → shunned → Budget path dead for 19 min (Freedom was also down) | Added to `nl_all_subnets` |

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
- Missing: rerank service (bge-reranker-v2-m3 at gpu01:11436), cross-chunk synthesis Q2, CMM L3 weekly chaos cron

**How to apply:**
1. Any time you edit `CLAUDE.md` with a cross-cutting behavioral change (new model/backend default, flipped safety threshold, new signal in RRF, etc.) — also open the corresponding section in the Hugo source for the portfolio page (website repo) in the same change set.
2. Before claiming a portfolio page is "current," grep it for every count that appears in `MEMORY.md` Quick Reference (workflows, nodes, MCP servers, tables, skills, dashboards, panels, wiki articles) and reconcile.
3. Treat the portfolio page as a third doc source alongside `CLAUDE.md` and `MEMORY.md` — all three must move together for cross-cutting flips.
4. Push to website main directly per `feedback_website_push_direct.md` — no local Hugo preview needed; CI handles it.
5. **Scope extended (2026-04-24):** `README.md` + `README.extensive.md` are the fourth and fifth doc source — all *five* (CLAUDE.md, MEMORY.md, README.md, README.extensive.md, portfolio page) must move together. The two READMEs sanitize-and-propagate to the public GitHub mirror `papadopouloskyriakos/agentic-chatops` via the `sync_to_github` CI job, so the mirror drifts silently when they lag.

**Reinforcing event (2026-04-24):** The 2026-04-23 IFRNLLEI01PRD-712 umbrella (agents-cli uplift, 11 commits on `main`) shipped CLAUDE.md and scorecard-post-agents-cli-adoption.md but left the two READMEs and the portfolio page at the 2026-04-20 snapshot. A same-session comparison surfaced the drift; fix landed next-day under IFRNLLEI01PRD-725 (commits `b0fb968` + `149bef8`, pipelines #24187 + #24188, GitHub mirror confirmed on `920bd33`). Had the rule been followed, the parity pass would have been part of `0527d03` (Phase H memo) — not a separate session. The pattern to break is: "scorecard memo counts as the portfolio update." It doesn't. Scorecard is internal; portfolio is external.

*Source: `memory/feedback_portfolio_sync_on_major_flips.md`*

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

### feedback_audit_before_mass_delete

When mass-deleting ASA config (NAT rules, ACLs, crypto maps), AUDIT every line before removal — don't just grep and nuke.

**Why:** During crypto-map cleanup, 161 NAT lines matching `outside_freedom|outside_xs4all` were removed by pattern. This missed that there were ZERO dynamic PAT rules for `outside_xs4all`. When Freedom ISP was down, all inside zones lost internet because traffic routed via xs4all had no PAT. Broke the operator's laptop internet.

**How to apply:** Before any mass config removal: (1) categorize what you're removing (exemptions vs PAT vs static), (2) verify outbound PAT exists for ALL active outside interfaces, (3) check for gaps the removal exposes, not just what it removes.

*Source: `memory/feedback_audit_before_mass_delete.md`*

## General

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
   - **(b) silent source rewrite on OUTBOUND control plane** — traffic from src_zone to a peer on outside_X (e.g., a BGP neighbor over a VTI) gets its source translated to the outside_X interface IP. If the peer's BGP/routing table doesn't know the interface-IP's subnet, replies resolve out the public internet and disappear. Diagnostic: fw01 packet capture shows `<interface_ip> > <peer>` for outbound ICMP but no replies; VPS `ip route get <interface_ip>` returns public-internet path.
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
  - fw01 learned the VPS loopback via 3 BGP paths (FRR01 reflecting with Freedom NH, FRR02 reflecting with Budget NH, rtr01 reflecting with Budget NH)
  - All 3 were LP 100 (blanket `FRR_TRANSIT_IN` route-map on all three peers)
  - Tie-break picked rtr01 → Budget path out
  - NO VPS replied via its default Freedom FRR peering → reply came in on fw01's vti-no-f (Freedom) → asymmetric → rpf-violated + nat-rpf-failed drops → Prometheus scrapes timed out → `TargetDown` fired
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

### Always set per-request num_ctx when using Ollama on gpu01

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
that matches PPPoE negotiation on fw01.

**Timing from the 2026-04-22 exercise.**

| Step | Elapsed |
|---|---|
| First `no shutdown` (did NOT work) | T0 |
| `power inline never/auto` + `shut`/`no shut` cycle | T0 + 5 min |
| Ethernet link stable `up (connected)` | + 2 s (after 2 flaps) |
| fw01 `outside_freedom` IP assigned (PPPoE UP) | + 90 s |
| Freedom VTIs Tunnel4/5/6 `up`, BGP Established | + 120 s |
| mesh-stats `Nominal — 9/9 tunnels` | + 120 s |

**When to apply.** Any planned Freedom maintenance that shuts sw01
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

When a script moves between deploy targets — e.g. `/home/app-user/.ssh/one_key` (openclaw container) → `/home/app-user/.ssh/one_key` (claude01) — patching the central config file is necessary but not sufficient. Grep the FULL repo for the old path string before declaring portability done.

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

When the file-server cluster (file01/file02 on this stack) shows an `ocf:heartbeat:exportfs` resource in `crm status`, exports come from the resource-agent invocation, **not** from `/etc/exports` or `/etc/exports.d/*`. `cat /etc/exports` is empty.

**Never run `exportfs -r` (or `-rv`) on these hosts.** It re-syncs to the empty /etc/exports and unexports all currently exported paths. nc01/nc02 active mounts will continue working (clients cached the FH) but new mounts and grace recovery will fail until the export is re-added.

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

**Incident that produced this memory (2026-04-22).** During a live failover test, I needed to reach the GR ASA via the GR stepstone (normally `gr-pve01`). The stepstone didn't have `python3-pexpect`. I ran `apt-get install -y python3-pexpect` on `gr-pve01` — the wrong move. The operator corrected: use grclaude01 for automation, keep pve01 clean. The installed package was left in place (not worth risking a removal on a running PVE host mid-failover) but no further tooling additions.

*Source: `memory/feedback_never_install_tools_on_proxmox.md`*

### Never reuse an existing channel-group number when adding a new LACP bundle

**P0 rule.** Before creating a new LACP bundle on a Cisco switch, run `show etherchannel summary` and pick an unused `channel-group` number. Never assume Po1 (or any specific number) is free.

**Why:** On 2026-04-21 I planned to bundle sw01 Gi1/0/34 + Gi1/0/32 into a new Po1 for the nlrtr01 uplink. sw01's Po1 was **already the production 4-link LACP to nl-fw01 (Gi1/0/21/23/25/27)** — the entire trunk that carries every internal VLAN to the firewall. My `interface Port-channel1 / switchport trunk allowed vlan 2 / switchport trunk native vlan 10` commands rewrote the firewall's trunk config. `channel-group 1 mode active` on Gi1/0/34 added it as a 5th member of the firewall bundle. This caused:

- ~several hours of management-network L2 outage (fw01 untagged VLAN 10 ingress dropped because fw01 Po1.10 expects tagged)
- Asymmetric L2 making triage non-obvious (fw01 → LAN worked; LAN → fw01 silent drop)
- fw01 power cycle during triage
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
On 2026-04-30, chaos test C9 (`docker kill nodered`) escalated from a sidecar-restart event to a **node fence + reboot of iot01**. Root cause: `p_docker_nodered` had `start timeout=90s`. Node-RED's first-after-kill boot took >90 s (loading flows, plugins, etc.). Pacemaker's start operation timed out → counted as start failure → migration-threshold=2 reached after a second retry → group can't migrate cleanly → escalation to fence the failed node. Kept the cluster correct but rebooted iot01 unnecessarily for ~2 min.

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

**Why:** I spent ~30 min on 2026-04-30 chasing wrong diagnoses for Gatus probe timeouts to file01/02:9101 — first claimed it was K8s pod-network routing (wrong: Prometheus from the same pod CIDR scrapes file01:9101 fine), then HTTP/1.0-vs-1.1 protocol mismatch (wrong: ThreadingHTTPServer + protocol_version="HTTP/1.1" didn't fix it), then head-of-line blocking on single-thread server (wrong again). The actual cause was a CNP egress allowlist:

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

### When fixing cron-env gaps, pair PATH + .env-sourcing

When you patch a cron-driven script for an environment-shaped failure (an `.env`-var unset, or a binary-not-found, or a `which()` returning None), audit the OTHER dimension before commit. Both dimensions fail silently under cron, both look like "the alert is broken" rather than "the script is broken," and they tend to surface months apart on different labels of the same alert.

**Why:** `IFRNLLEI01PRD-827` (2026-04-23, commit `088ef45`) patched the `.env`-sourcing half of `scripts/write-skill-metrics.sh` + `scripts/audit-skill-requires.sh` after `SkillPrereqMissing` false-fired on `env:GITLAB_TOKEN`. The PATH half was not touched. Twelve days later (2026-05-05) the same alert false-fired on `bin:kubectl` for k8s-diagnostician + drift-check, triggering five chatops loops in 12h before the second half of the same fix was identified. Same shape hit `weekly-scan.sh` on 2026-05-04 (`scanner_nuclei_silently_broken_20260504`). The general lesson: a cron-env fix is rarely complete in one dimension — the missing PATH and the missing .env-var live next to each other.

**How to apply:** before committing a fix to a cron-driven script, run all three of these:
1. `grep -n 'set -a\|\. .*\.env' <script>` — does it source `.env`? If it has any `os.environ.get(...)` or references env vars at runtime, it must.
2. `grep -n 'export PATH\|PATH=' <script>` — does it set PATH? If it calls (directly or via `which()`/`shutil.which()`) any binary outside `/usr/bin` or `/bin`, it must export PATH explicitly.
3. Simulate cron: `env -i HOME=$HOME LOGNAME=$USER USER=$USER SHELL=/bin/bash PATH=/usr/bin:/bin bash <script>` — watch for missing bins / unset vars in the output. This is what the cron daemon actually inherits.

If any of (1)-(3) flags a gap, fix it in the same commit as the original patch. The alternative is "the same alert false-fires on a different label N weeks later" — which is the literal pattern this rule was born from.

*Source: `memory/feedback_pair_cron_env_fixes_path_and_dotenv.md`*

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

**Why:** On 2026-04-30 I ran Phase 2 NFS auto-flush verification (10:44-10:47, three back-to-back exportfs cycles + manual cycles) followed by T1 HA restart (11:03). At 11:48 — ~45 minutes after the dense phase, with no operator activity — the file02 nfsd kernel fh-cache spontaneously re-poisoned, taking HA down for ~2 min until the manual `pcs resource restart exportfs` recovery. The chaos batch was the trigger; the manifestation was lagged.

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

**Why:** 2026-04-29 — operator caught me proposing fixes for "Max account quota depletion" while we were actively chatting on the same Max account. Their words: "how. the. fuck. are. we. still. chatting. here?" The answer was that OpenClaw's separate OAuth token had its own 5-minute burst window that didn't affect claude01's session. I should have recognized that the moment they pushed back the first time. Three rounds of bad theory + one harmful migration (setup-token, 100% failure rate, profile auto-disabled for 5–24h, had to roll back) before I admitted it.

**How to apply:**
- The error wording from upstream APIs ("out of usage", "extra usage", "quota exceeded") is generic. Don't infer the *cause* from the *message*.
- Always ask: "is anything else on the same account still working?" If yes, the cause is narrower than account-level.
- Identical `errorHash` / `error_id` across multiple retries = same upstream payload = batch-level not per-request — but still doesn't tell you whether the bucket is account, token, or session level.
- Before applying a "fix" that changes the failing path, prove the proposed alternative path actually works on this account with a single small probe call. Do not migrate first and test second.

*Source: `memory/feedback_check_other_sessions_before_account_exhaustion_theory.md`*

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

### feedback_no_static_routes

NEVER add static routes on the ASA or any other device. ALL inter-site routing is BGP-driven (migrated 2026-04-10).

**Why:** The entire VTI architecture uses BGP with three-tier LP failover (Freedom 200, xs4all 150, FRR transit 100). Static routes would bypass BGP convergence and create routing inconsistencies. The user explicitly stated: "we do NOT add static routes on the ASA or anywhere else, we use BGP."

**How to apply:** If routes are missing after a chaos test, wait for BGP to converge (30-90s). If peers are stuck, clear only the specific stuck peer on the RR (not on VPS). Never touch VPS upstream sessions.

*Source: `memory/feedback_no_static_routes.md`*

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

### lib/devices.py expects CISCO_PASSWORD; nl-claude01 has CISCO_ASA_PASSWORD

When writing one-off Python that imports `infrastructure/nl/production/network/scripts/lib/devices.py` (`build_profile`, `netmiko_connection`, `fetch_running_config`), the helper raises `EnvironmentError("CISCO_PASSWORD environment variable not set")` unless `CISCO_PASSWORD` is in the env. On `nl-claude01` the password is exported as `CISCO_ASA_PASSWORD` instead (CI-style naming for the ASA-deploy job).

Workaround for ad-hoc scripts:
```python
import os
os.environ.setdefault("CISCO_PASSWORD", os.environ["CISCO_ASA_PASSWORD"])
```

**Why:** `lib/devices.py:get_credentials()` only reads `CISCO_PASSWORD` (default user `operator`). The CI pipeline sets that var directly, but the operator-shell env on claude01 uses `CISCO_ASA_PASSWORD` so the two don't line up.

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
