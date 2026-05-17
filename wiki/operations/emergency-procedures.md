# Emergency Procedures

> OOB access, ASA SSH, PiKVM, maintenance companion. Compiled 2026-05-06 00:48 UTC.

## ASA 9.16 BGP limitations — why FRR sidecars exist + why ASAs don't peer with remote RRs

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

## ASA Weekly Reboot — DISABLED

**DISABLED 2026-04-10.** The EEM watchdog auto-reboot applets have been removed from both ASAs.

**Why removed:** The weekly reboot caused recurring VTI tunnel instability, cross-site connectivity failures, and cascading "Service up/down" alerts. The post-reboot VPN check consistently failed to recover Freedom-sourced tunnels (IFRNLLEI01PRD-440). Combined with a ~20-hour Matrix outage (2026-04-09/10), the automatic reboot created more disruption than it prevented.

**What was removed:**
- `no event manager applet weekly-reboot` on nl-fw01 (was 604800s / 7 days)
- `no event manager applet weekly-reboot` on gr-fw01 (was 590400s / 6d20h)
- `write memory` on both ASAs
- Cron `*/5 * * * * asa-reboot-watch.sh` commented out

**What remains:**
- `dailybackup` EEM applet on both ASAs (TFTP backup at 00:58 UTC) — unchanged
- `asa-reboot-watch.sh` script still exists (not deleted, just cron disabled)
- `post-reboot-vpn-check.sh` still exists

**How to apply:** No weekly ASA reboots to plan around anymore. If a manual ASA reload is needed, use the maintenance companion (`/maintenance` in IaC repo) to suppress alerts.

## ASA floating-conn for route changes

Use `timeout floating-conn 0:00:30` on Cisco ASA to handle stale connection entries after routing changes. This is the Cisco-native solution (Cisco doc 113592). **Configured and saved on both ASAs (2026-04-11).**

**Why:** Corosync cluster split 2026-04-11. ASA conn table pinned UDP flows to pre-VTI interface. Initial instinct was to write a cron script, but user correctly pushed back — the ASA has a native feature for this. Always research vendor documentation before building workaround scripts.

**How to apply:**
1. Prefer Cisco-native features over external scripts for ASA behavior
2. `timeout floating-conn 0:00:30` is now active on both nl-fw01 and gr-fw01
3. Null0 blackhole routes (AD 255) added for remote-site subnets on both ASAs — prevents cleartext leakage
4. `sysopt connection preserve-vpn-flows` confirmed DISABLED on both ASAs
5. Use **netmiko** (not expect) for Cisco ASA automation — netmiko venv at `/tmp/netmiko-venv/` on grclaude01
6. GR ASA reachable from grclaude01 at **10.0.X.X** (not 10.0.X.X)

## ASA crypto-map delete+recreate pattern

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

## GR ASA access — direct via grclaude01 netmiko (not OOB public IP)

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

## feedback_asa_shun_vti

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

## feedback_cisco_small_business_cbs_ssh

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

## defra01agri01 SSH pattern — operator + one_key + sudo -i ONLY

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

## GR ASA SSH requires stepstone via gr-pve01

GR ASA (gr-fw01) SSH access requires a stepstone connection through gr-pve01. Direct SSH from NL (nl-claude01) gets connection reset.

**Why:** The GR ASA likely has SSH ACLs restricting management access to local GR subnets only (10.0.X.X/24), not cross-site NL subnets.

**How to apply:** When SSHing to gr-fw01, use: `ssh -i ~/.ssh/one_key root@gr-pve01` then `ssh operator@10.0.X.X` from there. Or use ProxyJump: `ssh -J root@gr-pve01 operator@gr-fw01` (with appropriate legacy SSH flags for the ASA hop).

## feedback_gr_dmz_direct_ssh

Access gr-dmz01 via direct SSH over VPN tunnels, NOT via OOB stepstone (203.0.113.X:2222).

**Why:** The OOB stepstone won't stay active permanently. The VPN tunnels are always up and provide direct connectivity to GR site. Direct SSH is simpler and more reliable.

**How to apply:** Use `ssh -i ~/.ssh/one_key operator@gr-dmz01` for all GR DMZ operations in chaos-test.py, chaos-logs.py, and vpn-mesh-stats.py. The host resolves via DNS over the VPN.

**Note:** gr-dmz01 requires sudo for /srv/ access (`echo 'REDACTED_PASSWORD' | sudo -S`). Docker commands work without sudo (operator in docker group).

## NEVER modify OOB/lifeline systems without explicit approval

NEVER install packages, run system upgrades, or modify configuration on OOB/lifeline systems (PiKVM, LTE gateway, PDU) without explicit step-by-step user approval.

**Why:** On 2026-03-21, `pacman -S --overwrite '*'` on grpikvm01 corrupted libgcc_s.so.1, then `pikvm-update` failed mid-upgrade leaving the system unbootable. The PiKVM was the ONLY remote access path to the GR site with no remote hands available. The system is now bricked.

**How to apply:**
- OOB systems are untouchable infrastructure — their stability is more important than being up-to-date
- Never use `--overwrite '*'` or `--force` on any package manager
- Never run full OS upgrades on remote systems without a tested rollback plan
- If packages need installing, install ONLY the specific package, resolve conflicts manually, and get explicit user approval for each step
- If a package conflict arises, STOP and ask the user — do not try to force through it
- The user explicitly asked for the upgrade, but I should have flagged the risks of upgrading a remote OOB appliance with no fallback access

## NEVER SSH to nl-sw01

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

## OpenClaw SSH Access Pattern

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

## Use SSH ControlMaster/ControlPersist for any externally-routed VM with DDoS auto-mitigation (defra01agri01 + similar)

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

## Wrap `nohup … &` SSH-launched processes in systemd-run --user --scope

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

## VPS SSH access pattern

VPS SSH: `ssh -i ~/.ssh/one_key operator@198.51.100.X` (NO) or `operator@198.51.100.X` (CH). Root login not available.

**Why:** Discovered during 2026-04-10 tunnel outage. `root@` and `app-user@` both fail. Only `operator` with one_key works.

**How to apply:** All VPS operations (strongSwan, HAProxy, XFRM, swanctl) need `echo '<pw>' | sudo -S <cmd>` pattern. Sudo password same as ASA/scanner password in .env. `swanctl` without sudo fails with "Permission denied" on charon.vici socket.

## maintenance_companion

## Maintenance Companion (2026-03-18)

Active maintenance event manager for planned infrastructure events. Hybrid architecture: AWX preferred, direct API fallback.

### Components Built
1. `scripts/maintenance-companion.sh` (claude-gateway) — selfcheck/deps/start/status/check/end/checklist. Fallback ladder: AWX → LibreNMS API → PVE API → SSH → ping.
2. `.claude/commands/maintenance.md` (IaC repo) — `/maintenance` slash command with interactive session instructions, K8s rolling update protocol, self-awareness rules.
3. `openclaw/SOUL.md` addition — maintenance keyword detection → immediate escalation to Claude Code (bypasses triage).
4. `pve/maintenance_window.yml` (common/ansible) — AWX playbook: PVE host + all guests + catastrophic mode.

### Critical Service Map
- **nl-pve01:** n8n (VMID_REDACTED), Matrix (VMID_REDACTED), GitLab (VMID_REDACTED), FreeIPA (VMID_REDACTED), PiHole (VMID_REDACTED)
- **nl-pve02 (VM on nl-nas01):** K8s nlk8s-ctrl02, OpenBao node 2 — minimal impact. **nl-nas01 reboot kills nl-pve02 too.**
- **nl-pve03:** LibreNMS (VMID_REDACTED), YouTrack (VMID_REDACTED), Claude Code (VMID_REDACTED) — companion dies if nl-pve03 reboots
- **K8s:** AWX, Prometheus, Grafana, cert-manager, Argo CD, OpenBao

### Key Design Decisions
- **Why:** Single PVE reboot triggers 80+ LibreNMS alerts → 80+ Matrix messages → triage storms → 80+ YT issues
- **How to apply:** When user mentions planned maintenance, OpenClaw escalates immediately (not triage). Claude Code activates companion for alert suppression + recovery monitoring.
- AWX playbooks already handle LibreNMS maintenance windows (battle-tested, retries). Companion reuses them when AWX is available.
- Self-healing Layer 0 checks all dependencies before operations — adapts when services are down.
- K8s rolling update: never nl-pve01+nl-pve03 simultaneously (etcd quorum). Safe order: nl-pve02 → nl-pve01 → nl-pve03.

### AWX Integration
- URL: `https://awx.example.net`, token: `REDACTED_bacaec8e`
- AWX runs on K8s — if K8s is down, AWX is down, companion falls back to direct API
- Existing playbooks: `common/tasks/librenms_maintenance.yaml` (45min, 3 retries), weekly updates (FISHA/IoT/Matrix/NC)
- New: `pve/maintenance_window.yml` — host + guest maintenance + catastrophic mode

### Testing
- **Not yet tested** with real reboot. Recommended first test: nl-pve02 (7 LXC, 0 QEMU, least risk).

## OOB Access via PiKVM + Cloudflare Tunnel

## STATUS: OFFLINE — PiKVM BRICKED (2026-03-21)

PiKVM was bricked during a package upgrade session. `pacman -S --overwrite '*'` corrupted libgcc_s.so.1 (gcc-libs), then `pikvm-update` upgraded 313 packages but post-install hooks (initramfs, kernel modules) all failed due to the broken library. Power cycle via PDU resulted in unbootable system — not responding to ping.

**Recovery requires physical access to GR site:**
- Pull SD card, mount on another machine, fix libgcc_s.so.1, rebuild initramfs
- Or flash fresh PiKVM image and reconfigure (Cloudflare tunnel, SSH config, UFW, DDNS, SNMP)

## OOB Path (VPN-independent) — NOT WORKING
```
app-user → Cloudflare Tunnel → PiKVM (grpikvm01) → GR ASA (10.0.X.X)
```

## Components
- **Cloudflare Tunnel:** `gr-pikvm-oob` (ID: REDACTED_TUNNEL_ID)
- **Protocol:** HTTP/2 (QUIC blocked by GR firewall)
- **Edge PoPs:** SKG (Thessaloniki) + ATH (Athens)
- **DNS:** `pikvm-gr.example.net` (SSH), `pikvm-gr-web.example.net` (KVM web UI)
- **PiKVM:** grpikvm01, 10.0.X.X (mgmt), eth1=192.168.111.x (LTE), eth2=192.168.112.x (ASA OOB)
- **ASA OOB IP:** 10.0.X.X (dedicated OOB VLAN, not routed through VPN)
- **PiKVM password:** REDACTED_PASSWORD
- **ASA password:** REDACTED_PASSWORD (user: operator)

## Cloudflare Access Protection (both hostnames)
Both SSH and HTTPS routes are protected by Cloudflare Access (Zero Trust):
- **Auth method:** One-time PIN (email OTP) to ixchbtfl@mail.example.net
- **IP whitelist:** NL (203.0.113.X, 203.0.113.X/29), GR (203.0.113.X)
- **Access groups:** 3 groups (same as old grpikvm01-https tunnel)
- **Service token:** 65eb023e-f9a4-4235-a3e5-5fcf9440d061
- **Session duration:** 730h (~30 days)
- **SSH app ID:** efef9638-e37d-472d-9f60-6123aa0a46f8
- **Web app ID:** 7761abb0-7033-4178-a70b-90103f7e82a1
- **Team:** examplecorp
- Unauthenticated requests from unknown IPs return 302 → Access login page
- **SSH (pikvm-gr):** IP bypass policy allows NL/GR IPs without browser auth (required for non-interactive cloudflared SSH). External IPs still hit Access gate. Tunnel ingress does NOT enforce access (Access app handles it at the edge).
- **HTTPS (pikvm-gr-web):** Access enforced at both tunnel ingress AND Access app level. Always requires auth.
- Matches security of old tunnel (`grpikvm01-https`, tunnel ID e1368111, now decommissioned)

## SSH Command (from app-user)
```bash
sshpass -p 'REDACTED_PASSWORD' ssh -o StrictHostKeyChecking=no \
  -o ProxyCommand="$HOME/.local/bin/cloudflared access ssh --hostname pikvm-gr.example.net" \
  root@pikvm-gr.example.net
```
Then from PiKVM: `ssh gr-fw01` (configured in ~/.ssh/config)

## DNS Note
Local DNS (FreeIPA/PiHole at 10.0.181.X) can't resolve pikvm-gr.example.net (example.net is an authoritative zone internally). Added to /etc/hosts on app-user LXC (VMID_REDACTED on nl-pve03).

## Cloudflare API Token
`cfut_eWPhVDYuilGXVI5YlgV1PC827XYzYIA48tBqovHi83bd12dd` — scoped to Tunnel:Edit + DNS:Edit, IP-locked to 203.0.113.X (NL public IP).

## Also Available
- **LTE backup:** PiKVM eth1 → grlte01 (10.0.X.X) — separate LTE gateway
- **NL ASA:** Direct SSH from app-user (same LAN, no OOB needed)

## PVE Kernel Maintenance Automation

PVE kernel maintenance automation ALL COMPLETE. Plan doc: `docs/pve-kernel-maintenance-plan.md`.

**Why:** All 5 PVE nodes need kernel updates requiring reboot. nl-nas01 cascade kills nl-pve02 + 2 Pacemaker arbitrators + all NFS/iSCSI. IoT `no-quorum-policy=suicide` requires careful ordering.

**How to run:** From app-user (NOT AWX EE — no SSH keys in pods):
```bash
# GR (~14 min dry-run, ~60 min real):
ansible-playbook -i localhost, -c local \
  ~/gitlab/infrastructure/common/ansible/playbooks/pve/full_maintenance_gr.yaml \
  -e '{"operator":"kyriakos","dry_run":false,"api_token":"...","matrix_api_token":"..."}'

# NL (~135 min real):
ansible-playbook -i localhost, -c local \
  ~/gitlab/infrastructure/common/ansible/playbooks/pve/full_maintenance_nl.yaml \
  -e '{"operator":"kyriakos","dry_run":false,"skip_synology":false,"api_token":"...","matrix_api_token":"..."}'
```

## PVE Update Sequence (hardened per Proxmox docs)
Per node, the playbook runs:
1. `pveversion -v` + `uname -r` (record before state)
2. `DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y -o Dpkg::Options::='--force-confold'` (keep existing configs)
3. `apt-get autoremove --purge -y` (clean old kernels — PVE never auto-removes them)
4. `proxmox-boot-tool kernel list` → find latest → `proxmox-boot-tool kernel pin <latest>` → `proxmox-boot-tool refresh` (ensures correct kernel boots)
5. `reboot`
6. `pveversion -v` + `uname -r` (verify new kernel running)

## Playbooks (14 files) — infrastructure/common repo
| Phase | Playbook |
|-------|----------|
| Shared | common/tasks/snapshot_state.yaml, chatops/maintenance_mode.yaml, common/tasks/email_report.yaml |
| K8s | k8s/drain_cluster.yaml (`--disable-eviction` for PDB bypass), k8s/restore_cluster.yaml, k8s/validate_storage.yaml |
| GR | pve/full_maintenance_gr.yaml |
| NL | pacemaker/graceful_shutdown.yaml, pacemaker/restore_clusters.yaml (tasks file) |
| NL | nextcloud/maintenance_mode.yaml (tasks file), synology/update_dsm.yaml |
| NL | pve/post_reboot_validation.yaml, pve/tiered_startup_nl.yaml (tasks file), pve/full_maintenance_nl.yaml |

Validation script: `/home/app-user/scripts/post-maintenance-check.sh` (16 health checks, JSON output)

## Proxmox Startup Order (applied 2026-03-25)
T0(1-2) → T1(4) → T2(10-14) → T3(16-18) → T4(20-22) → T5(24) → T6(26) on all 5 nodes.
Key fixes: nlmariadb02/nlredis03 3→10, nlproxysql02/nlhaproxy02 4→14, K8s CP/workers/IoT all got explicit ordering.
GR: grfreeipa01=1, K8s ctrlr=18, K8s node=20, K8s infra LXCs=16 on both gr-pve01+gr-pve02.

## AWX Job Templates (cross-site architecture)
**GR maintenance → NL AWX** template 69 (GR Full Maint). **Dry-run PASS: 55/0, 3.8 min.**
**NL maintenance → GR AWX** template 21 (NL Full Maint). **Dry-run PASS: 73/1 (IoT timing), 12.7 min.**
**NL AWX other templates**: 64=NL Full Maint, 65=K8s Drain, 66=Post-Reboot Validation, 67=ChatOps Maint Mode, 68=Tiered Startup.
**GR AWX**: 20=GR Full Maint (local use). Token: `REDACTED_3ebe4162`.

## Custom AWX EE (awx-ee-maintenance)
**Dockerfile**: `ansible/ee/Dockerfile`. Base: `awx-ee:24.6.1` + kubectl, curl, dig (bind-utils), redis-cli, showmount (nfs-utils), cilium CLI.
**Image**: `10.0.181.X:5555/awx-ee-maintenance:latest` (imported via temp registry to all 7 K8s workers).
**K8s secret** `awx-ssh-one-key` (both sites): SSH key (`/runner/.ssh/one_key`) + kubeconfig (`/runner/.kube/config`).
**EE pull**: `never` (image pre-loaded on nodes, no registry dependency).
**EE IDs**: NL AWX=5, GR AWX=4. Assigned to all maintenance job templates.
**Why**: Default awx-ee lacks kubectl/curl/dig/redis-cli/showmount/cilium. Without custom EE, playbooks would depend on app-user (which goes down during NL maintenance).

## Maintenance Mode (7 files modified)
- 5 n8n workflows: LibreNMS NL/GR, Prometheus NL/GR, WAL Self-Healer GR — check `gateway.maintenance` via piggybacked SSH read
- Gateway watchdog (`scripts/gateway-watchdog.sh`): early return at main()
- OpenClaw infra-triage: exits with confidence 0.1 during maintenance, 50% reduction during 15min cooldown
- SOUL.md: "Maintenance Mode Awareness" section

## GR REAL MAINTENANCE — DONE (2026-03-26)
- gr-pve01: 6.17.2-2-pve → **6.17.13-2-pve**, PVE 9.1.2 → **9.1.6**
- gr-pve02: 6.17.2-2-pve → **6.17.13-2-pve**, PVE 9.1.2 → **9.1.6**
- K8s: 6/6 Ready, 20/20 PVs Bound, iSCSI 19 targets, ZFS ONLINE
- AWX playbook ran pre-maintenance + K8s drain + guest shutdown, then failed on backup-locked CT
- Remaining steps (PVE update/reboot, K8s restore) completed manually
- 5 real-run issues fixed in code (see feedback_pve_maint_lessons.md)

## GR Oversight Agent — grclaude01 (deployed 2026-03-27)
VMID 201021201, 10.0.X.X, gr-pve01. Claude Code 2.1.84 (OAuth).
MCP: Proxmox (all 5 nodes), Kubernetes (NL+GR), NetBox.
kubectl+ansible+SSH to all hosts. 211-line CLAUDE.md with phase-by-phase NL maintenance monitoring timeline.
DNS: A+PTR on GR FreeIPA. NetBox: VM 198, Interface 248, IP 577.
Mission: monitor NL maintenance from GR AWX, intervene on failure, resume manually if needed.

## NL maintenance — status (2026-03-26)
**Completed:**
- Code fixes applied (backup unlock, kernel grep, LibreNMS token, Synology sudo, ChatOps local write, LibreNMS post-maint alert check)
- All NL K8s VMs `onboot=1` verified + fixed (4 VMs were missing it)
- NL dry-run from app-user: **56 OK, 1 failed** (ChatOps SSH to self — fixed), 1 ignored (syno iSCSI retries)

**Blocker RESOLVED:** GR GitLab Container Registry (`10.0.X.X:5050`, HTTP) used as persistent image store. Containerd config_path set on all GR workers. Pull secret via default SA in awx namespace. `pull: missing` on EE.

**NL dry-run from GR AWX: PASS** — 73 OK, 1 failed (IoT 2/3 dry-run timing), 12.5 min. Persistent registry works.

**nl-nas02 (DS1513+) — CANNOT upgrade to DSM 7.2.** Hardware-locked to DSM 7.1.x (Atom D2700, no AES-NI). Synology dropped 7.2 support. Playbook comments fixed, default target changed to `syno01` only. Disk 5 (sde) has 56 bad sectors. Extended Life Phase through 2026. Plan DS1523+ replacement.

**NL real run:** Launch from GR AWX template 21. EE pulls from `10.0.X.X:5050` (GR GitLab registry).
Required extra_vars: `operator`, `dry_run=false`, `api_token`, `matrix_api_token`.
Optional: `synology_targets=both` (to include nl-nas02 for 7.1.x patches), `syno_sudo_pass` (required if targeting nl-nas02).

**Full hostname rule (2026-03-27):** All playbook task names, debug msgs, comments, and echo statements now use full site-prefixed hostnames (nl-pve01 not pve01, gr-pve01 not pve01). 7 playbooks fixed (~34 edits). Also fixed in SOUL.md (10 edits), memory files (17 files, ~60 edits), 4 YT issue summaries.

## YT Issues — ALL DONE
- GR (IFRGRSKG01PRD): 123-128 — Done
- NL (IFRNLLEI01PRD): 265-273, 275 — Done
- 274: CLOSED (LibreNMS token intentional), 276: CLOSED (nl-pve01 swap decommissioned)
