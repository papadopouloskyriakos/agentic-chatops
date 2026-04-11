# Operational Rules

> Auto-compiled from 24 feedback memory files on 2026-04-09 06:19 UTC.
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

## ASA / VPN / Network

### ASA crypto-map delete+recreate pattern

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

*Source: `memory/feedback_asa_cryptomap_delete_recreate.md`*

### GR ASA SSH requires stepstone via gr-pve01

GR ASA (gr-fw01) SSH access requires a stepstone connection through gr-pve01. Direct SSH from NL (nl-claude01) gets connection reset.

**Why:** The GR ASA likely has SSH ACLs restricting management access to local GR subnets only (10.0.X.X/24), not cross-site NL subnets.

**How to apply:** When SSHing to gr-fw01, use: `ssh -i ~/.ssh/one_key root@gr-pve01` then `ssh operator@10.0.X.X` from there. Or use ProxyJump: `ssh -J root@gr-pve01 operator@gr-fw01` (with appropriate legacy SSH flags for the ASA hop).

*Source: `memory/feedback_gr_asa_ssh_stepstone.md`*

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

*Source: `memory/feedback_never_ssh_sw01.md`*

### feedback_dual_wan_nat_parity

When configuring dual-WAN on ASA, EVERY inside zone needs dynamic PAT on BOTH outside interfaces.

**Why:** The NL ASA had dynamic PAT only for `outside_freedom`. When Freedom went down, all inside zones lost internet because traffic routed via `outside_xs4all` had no PAT. When Freedom came back, `inside_mgmt` still had no Freedom PAT (only rooms had it). This broke the operator's laptop twice in one session.

**How to apply:** When adding a new inside zone or outside interface, always add PAT for ALL outside interfaces. Check with `show run nat | include dynamic` and verify every zone×interface combination exists. The `after-auto source dynamic any interface` pattern works for catch-all PAT.

*Source: `memory/feedback_dual_wan_nat_parity.md`*

## Kubernetes

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

### Always use full hostnames

Always use full hostnames (e.g. nl-nas02, gr-pve01, nl-iot02), never shortened forms (syno02, pve01, iot02).

**Why:** Shortened hostnames cause confusion in a multi-site environment (NL + GR). The full hostname encodes site+cluster+role which is critical for operational clarity. Using "syno02" is ambiguous — it could be NL or GR.

**How to apply:** In all output — tables, commands, memory files, YT comments, Matrix messages — always use the full hostname as it appears in DNS/NetBox. Never abbreviate or strip prefixes.

*Source: `memory/feedback_full_hostnames.md`*

### Data trust hierarchy

Data trust hierarchy — always follow this order when investigating or making claims:

1. **Running config on the live device** (SSH + `show run`, `ip a`, `pct config`, `kubectl get`) — the ONLY 100% truth
2. **LibreNMS** — active monitoring, shows what's happening NOW
3. **NetBox** — CMDB inventory, accurate but manually maintained — can drift if someone forgets to update
4. **03_Lab, GitLab IaC, backups** — supplementary reference, useful context but can be stale

**Why:** NetBox requires manual updates, so it can drift from reality. LibreNMS actively polls devices so it reflects current state. But even LibreNMS can lag or miss things. The only way to know what a device is actually running is to SSH in and check. 03_Lab xlsx files, IaC configs, and backups are all point-in-time snapshots that may not reflect recent changes.

**How to apply:** During triage, always verify critical facts by checking the live device. Never trust a stale xlsx entry or IaC config over what `show run` returns. When 03_Lab data contradicts live state, the live state wins — and flag the 03_Lab entry as potentially outdated.

*Source: `memory/feedback_data_trust_hierarchy.md`*

### feedback_audit_before_mass_delete

When mass-deleting ASA config (NAT rules, ACLs, crypto maps), AUDIT every line before removal — don't just grep and nuke.

**Why:** During crypto-map cleanup, 161 NAT lines matching `outside_freedom|outside_xs4all` were removed by pattern. This missed that there were ZERO dynamic PAT rules for `outside_xs4all`. When Freedom ISP was down, all inside zones lost internet because traffic routed via xs4all had no PAT. Broke the operator's laptop internet.

**How to apply:** Before any mass config removal: (1) categorize what you're removing (exemptions vs PAT vs static), (2) verify outbound PAT exists for ALL active outside interfaces, (3) check for gaps the removal exposes, not just what it removes.

*Source: `memory/feedback_audit_before_mass_delete.md`*

## General

### Atlantis apply command format and architecture

Atlantis apply command must include the project flag: `atlantis apply -p k8s`

**Why:** Both NL and GR IaC repos have a single project named `k8s`. Without `-p k8s`, Atlantis ignores the apply comment.

**How to apply:** When posting apply comments to GitLab MRs for IaC repos, always use `atlantis apply -p k8s`. Same for plan: `atlantis plan -p k8s`.

NL and GR have **separate GitLab instances and separate Atlantis servers**. They can run plans and applies concurrently — there is no shared state or lock between sites.

*Source: `memory/feedback_atlantis_apply.md`*

### MeshSat Android UX feedback

User tested MeshSat Android v1.0.1 on real phone (2026-03-16). Key feedback:

1. **Maps show grey square** — WebView/Leaflet maps never load tiles, just grey. Must fix.
2. **SMS permissions too invasive** — App requests default SMS app role + RECEIVE_MMS/WAP_PUSH which triggers scary Android security warnings. User wants SMS to work with minimal permissions.
3. **Dark/light theme** — App should support both, default to dark. Maps should also respect theme.
4. **GUI simpler than expected** — Backend is complete but UI doesn't surface everything yet.

**Why:** First impression matters. Invasive permissions scare users away before they try the app.

**How to apply:** Fix maps first (visible bug). Reduce SMS permissions to minimum (SEND_SMS + RECEIVE_SMS only, drop default SMS app requirement). Add theme toggle. Don't request permissions the core flow doesn't need.

*Source: `memory/feedback_meshsat_android_ux.md`*

### OpenAI model instruction pattern for OpenClaw

OpenAI models (OpenClaw — now GPT-5.1, migrated from GPT-4o on 2026-04-07) don't reliably follow auto-trigger patterns like "when you see X, do Y via exec" in the system prompt (SOUL.md). Multi-step sequential exec calls are also unreliable. Verify if GPT-5.1 improves this behavior — OpenAI notes "stricter system-message enforcement" in 5.1.

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

### Push directly to main

Push directly to main in the MeshSat repo. Do not create feature branches or MRs.

**Why:** The pipeline deploys from main automatically. Branches add unnecessary overhead for a solo operator.

**How to apply:** When committing MeshSat changes, commit and push to main directly. Ignore the CLAUDE.md convention about branches/MRs for this repo.

*Source: `memory/feedback_push_to_main.md`*

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

### feedback_push_to_main_gateway

Push directly to main for the claude-gateway repo. No feature branches, no MRs.

**Why:** User prefers direct pushes for this repo — MR overhead is unnecessary for a single-operator workflow.

**How to apply:** When committing changes in `/app/claude-gateway`, push to main directly. Ignore the CLAUDE.md convention "Create MRs, don't push directly to main" for this repo.

*Source: `memory/feedback_push_to_main_gateway.md`*

### feedback_sonos_volume

Sonos/Squeezebox speakers in this setup are very loud. **15% is the new standard** for all volume settings (music, alerts, notifications). TTS via Voice PE firmware uses 10% (on_tts_start). 20% is the absolute maximum.

**Why:** User corrected the previous 25% max rule — 15% is the new rule (2026-03-16). 40% was "ultra-loud". The notify platform and kitchen alert automation were both at 40%, now fixed to 15%.

**How to apply:** When adjusting any speaker volume in the HAHA setup, use 15% as default. The HA Voice PE device volume (media_player.home_assistant_voice_0957d2_media_player) controls the built-in speaker, not the Squeezebox outputs. Firmware TTS output is 10% (hardcoded in on_tts_start).

*Source: `memory/feedback_sonos_volume.md`*

### n8n upgrades can silently break workflow nodes

After n8n upgrade (2.40.5→2.41.3), Switch V3.2 nodes silently broke — Prometheus alerts dropped for 4 days with no Matrix notification. The silence looked like stability.

**Why:** n8n node typeVersions can have breaking changes between releases. The `extractValue` function in n8n-core changed how it resolves nested parameters for Switch V3.2, requiring a `conditions.options` block that wasn't needed before. Nodes created via MCP/API are more vulnerable because the UI auto-populates required sub-objects but programmatic creation doesn't.

**How to apply:**
- After any n8n version upgrade, check recent error executions across all alert receiver workflows
- Silence in alert channels is suspicious — verify pipeline health, don't assume stability
- Compare programmatically-created nodes against UI-created equivalents for missing sub-objects
- The n8n API `POST /api/v1/workflows/{id}/deactivate` + `/activate` is needed after any workflow JSON update to reload webhook listeners

*Source: `memory/feedback_n8n_upgrade_regression.md`*
