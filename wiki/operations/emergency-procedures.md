# Emergency Procedures

> OOB access, ASA SSH, PiKVM, maintenance companion. Compiled 2026-04-09 06:53 UTC.

## ASA Weekly Reboot Suppression

Both Cisco ASA firewalls use EEM watchdog timers for automatic reboots:
- **nl-fw01 (NL):** `event timer watchdog time 604800` (7 days from boot)
- **gr-fw01 (GR):** `event timer watchdog time 590400` (~6d20h from boot)

**Why:** ASA reboot causes total site network outage (~5-10 min), cascading "Service up/down" alerts across all 137 NL devices + GR VPN drop. Without suppression, creates 4+ YT issues, wastes Claude Code compute, clutters Matrix.

**How to apply:** 4-layer defense-in-depth:
1. **LibreNMS maintenance** — `scripts/asa-reboot-watch.sh` (cron `*/5`) checks ASA uptime via SSH, sets maintenance on all devices when reboot < 10min away
2. **gateway.maintenance file** — same watcher creates/removes the file automatically
3. **scheduled-events.json** — `config/scheduled-events.json` checked by `infra-triage.sh` as fallback
4. **Agent knowledge** — SOUL.md, Runner Build Prompt, incident_knowledge DB (3 entries with embeddings)

**Key files:**
- Watcher: `scripts/asa-reboot-watch.sh` (cron every 5min)
- Config: `config/scheduled-events.json`
- Modified: `infra-triage.sh` (line 72+), `correlated-triage.sh` (line 38+), `SOUL.md`, Runner Build Prompt

**Reboot times drift** ~5min per cycle (watchdog counts from boot completion). Fixed cron won't work — the predictive watcher adapts automatically.

Implemented 2026-04-03. First real test: NL ~2026-04-10 09:28 UTC, GR ~2026-04-08 17:34 UTC.

## BGP / VTI Tunnel Troubleshooting (2026-04-10)

All inter-site routing is BGP-driven (no static routes). Troubleshoot cross-site connectivity issues in this order:

### 1. Check BGP peer state
```
show bgp ipv4 unicast summary    ! on ASA — all VTI + FRR peers should be Established
```
- Freedom VTI peer (10.255.200.10/11) DOWN → Freedom tunnel failed, traffic should auto-failover to FRR transit (LP 100, ~30s)
- xs4all VTI peer (10.255.200.0/1) showing Active/Idle → **NORMAL while Freedom is UP** (xs4all dormancy, not a failure)
- FRR peers (10.0.X.X/4 or 10.0.X.X/4) DOWN → FRR LXC issue, check `pct status <VMID>`

### 2. Check tunnel ESP health
```
show crypto ipsec sa | include interface|pkts dec
```
- Freedom tunnels (vti-*-f) should show encaps AND decaps > 0
- xs4all tunnels (vti-gr/no/ch) showing encaps > 0, decaps = 0 → **NORMAL** (dormancy, not failure)
- ALL tunnels showing decaps = 0 → check `show interface Tunnel<N>` (admin down?) and `show vpn-sessiondb l2l`

### 3. Cross-site subnet unreachable after route change
**Symptom:** Ping to GR subnet fails but `show route <subnet>` shows valid BGP route.
**Cause:** Stale ASA connection table entries from the old forwarding path.
**Fix:**
```
clear conn address <subnet> netmask <mask>    ! on BOTH ASAs
```
This was the fix for corosync blackhole during the BGP cutover (2026-04-10).

### 4. Freedom ISP down → full failover sequence
1. SLA track 1 detects BNG unreachable (~15s)
2. Default route switches to xs4all (metric 10)
3. Freedom VTI BGP sessions drop (DPD 30s + BGP hold 30s)
4. xs4all tunnels activate (outer ESP now exits correct interface)
5. xs4all VTI BGP sessions establish
6. All traffic flows via xs4all
7. QoS toggle applies tenant rate limits (`freedom-qos-toggle.sh`)
8. SMS sent via Twilio

### 5. xs4all tunnel UP but no traffic (expected behavior)
**Root cause:** ASA `tunnel source interface` does NOT override routing table for outer ESP egress. VPN peer host routes via outside_freedom (metric 1) force ALL ESP out Freedom. Freedom ISP drops xs4all-sourced ESP (BCP38).
**This is NOT a failure.** xs4all tunnels activate automatically when Freedom goes down.

## ASA crypto-map delete+recreate pattern

Never modify Cisco ASA crypto-map entries in-place when changing the peer list. Always fully delete (`no crypto map <name> <seq> ...` for all 3 lines: match, peer, proposal) then re-create.

**Why:** In-place `set peer` changes update the running config but leave stale internal IKEv2 Traffic Selector (TS) matching tables. The ASA will reject CREATE_CHILD_SA requests with TS_UNACCEPTABLE even though `show run` looks correct. Discovered during the Freedom ISP outage (2026-04-08) when GR ASA entries 37/38 had 145.53.163.13 added as secondary peer — `show run` showed the peer correctly but IKEv2 TS narrowing kept rejecting the traffic selectors. Only a full delete+recreate fixed it.

**How to apply:** Any time you add, remove, or reorder peers on an existing crypto-map entry:
```
no crypto map <name> <seq> match address <acl>
no crypto map <name> <seq> set peer <peers>
no crypto map <name> <seq> set ikev2 ipsec-proposal <proposal>
crypto map <name> <seq> match address <acl>
crypto map <name> <seq> set peer <new_peers>
crypto map <name> <seq> set ikev2 ipsec-proposal <proposal>
```

## GR ASA SSH requires stepstone via gr-pve01

GR ASA (gr-fw01) SSH access requires a stepstone connection through gr-pve01. Direct SSH from NL (nl-claude01) gets connection reset.

**Why:** The GR ASA likely has SSH ACLs restricting management access to local GR subnets only (10.0.X.X/24), not cross-site NL subnets.

**How to apply:** When SSHing to gr-fw01, use: `ssh -i ~/.ssh/one_key root@gr-pve01` then `ssh operator@10.0.X.X` from there. Or use ProxyJump: `ssh -J root@gr-pve01 operator@gr-fw01` (with appropriate legacy SSH flags for the ASA hop).

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
