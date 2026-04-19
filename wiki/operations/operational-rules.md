# Operational Rules

> Auto-compiled from 36 feedback memory files on 2026-04-11 14:13 UTC.
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

### Atlantis — do NOT spam plan/apply commands

Post `atlantis plan` or `atlantis apply` ONCE on a GitLab MR and WAIT for the response. Do NOT:
- Poll in a loop checking for results
- Re-trigger the same command if it hasn't responded yet
- Post `atlantis unlock` + `atlantis plan` + `atlantis apply` in rapid succession

**Why:** Atlantis processes one command at a time per workspace. Re-triggering creates lock conflicts ("workspace currently locked by apply"), duplicate plan runs, and floods the MR with redundant comments. kube-prometheus-stack plans take 1-3 minutes for the Helm diff.

**How to apply:** Post the command once, then tell the user to check the MR when it's done. If the user asks to check, do ONE API call to read the latest note — don't loop.

*Source: `memory/feedback_atlantis_no_spam.md`*

### Hook output format — silent allow, plain text deny

Claude Code hooks (PreToolUse, PostToolUse, Stop, PreCompact) expect:
- **Exit 0 (allow):** No stdout output. Silent exit. Any stdout is parsed as JSON and triggers "Hook JSON output validation failed" if schema doesn't match.
- **Exit 2 (deny):** Plain text on stdout shown as error message to the model. NOT JSON — just a human-readable string.

**Why:** The unified-guard.sh hook was outputting `{"decision": "allow"}` on every allowed Bash/Edit/Write command. Claude Code tried to parse this as its internal hook response schema, failed, and logged "JSON validation failed" on every tool call. This caused hundreds of spurious errors in sub-agent contexts.

**How to apply:** When writing any hook script, never output anything to stdout on the allow path. Only output on the deny path (exit 2), and use plain text, not JSON.

*Source: `memory/feedback_hook_output_format.md`*

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

### VPS SSH access pattern

VPS SSH: `ssh -i ~/.ssh/one_key operator@198.51.100.X` (NO) or `operator@198.51.100.X` (CH). Root login not available.

**Why:** Discovered during 2026-04-10 tunnel outage. `root@` and `app-user@` both fail. Only `operator` with one_key works.

**How to apply:** All VPS operations (strongSwan, HAProxy, XFRM, swanctl) need `echo '<pw>' | sudo -S <cmd>` pattern. Sudo password same as ASA/scanner password in .env. `swanctl` without sudo fails with "Permission denied" on charon.vici socket.

*Source: `memory/feedback_vps_ssh_access.md`*

### Website deploys — push to production, no local testing

Push website changes directly to main — do not build/test locally with Hugo server.

**Why:** The CI pipeline (*/5 schedule + on-push) handles build, Docker, and AWX deploy to DMZ. Local testing wastes time since the CI fetches live data from internal APIs (n8n webhooks, Gatus) that shape the final page. The user prefers to see changes on the real site immediately.

**How to apply:** For any changes to the `websites/papadopoulos.tech/kyriakos` repo, commit and push to main directly. Verify via Playwright against the live URL after pipeline succeeds. n8n/API endpoints are internal-only (192.168.x) — client-side JS cannot fetch from them; data must be inlined at build time via Hugo `site.Data`.

*Source: `memory/feedback_website_push_direct.md`*

### YouTrack state transitions use command API

YouTrack MCP `update_issue_state` fails with "Unknown workflow restriction" for state transitions (Open→Done, In Progress→Done, etc.). The MCP tool can't handle workflow-restricted state machines.

**Working approach:** Use the YouTrack command API directly:
```bash
curl -s -X POST "https://youtrack.example.net/api/commands" \
  -H "Authorization: Bearer ${YT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"query": "State Done", "issues": [{"idReadable": "ISSUE-ID"}]}'
```
Empty `{}` response = success. Token is `YT_TOKEN` from `.env`.

**Why:** YT MCP's update_issue_state uses direct field API which doesn't respect workflow state machine transitions. The command API (`/api/commands`) executes commands as if typed in the YT UI, which properly handles workflow rules.

**How to apply:** For any YT state change, use curl to `/api/commands` instead of the MCP tool. MCP tools still work for: `add_comment`, `get_issue`, `search_issues`, `get_custom_fields`.

*Source: `memory/feedback_yt_command_api.md`*

### feedback_always_screenshot_visual

NEVER assume something visual/graphic/color is on the website from looking at the code. ALWAYS use Playwright screenshots before claiming such changes completed.

**Why:** Code can be correct but CDN caching, Hugo build issues, CSS bundling, or pipeline failures can mean the live site doesn't match. The user was burned by claims of "deployed" that weren't visually verified.

**How to apply:** For ANY visual change (colors, layout, positioning, new UI elements), the completion check MUST include:
1. Wait for CI pipeline to succeed
2. Take Playwright screenshot of the live site
3. Read and analyze the screenshot
4. Only then report completion

*Source: `memory/feedback_always_screenshot_visual.md`*

### feedback_gr_dmz_direct_ssh

Access gr-dmz01 via direct SSH over VPN tunnels, NOT via OOB stepstone (203.0.113.X:2222).

**Why:** The OOB stepstone won't stay active permanently. The VPN tunnels are always up and provide direct connectivity to GR site. Direct SSH is simpler and more reliable.

**How to apply:** Use `ssh -i ~/.ssh/one_key operator@gr-dmz01` for all GR DMZ operations in chaos-test.py, chaos-logs.py, and vpn-mesh-stats.py. The host resolves via DNS over the VPN.

**Note:** gr-dmz01 requires sudo for /srv/ access (`echo 'REDACTED_PASSWORD' | sudo -S`). Docker commands work without sudo (operator in docker group).

*Source: `memory/feedback_gr_dmz_direct_ssh.md`*

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

### feedback_no_static_routes

NEVER add static routes on the ASA or any other device. ALL inter-site routing is BGP-driven (migrated 2026-04-10).

**Why:** The entire VTI architecture uses BGP with three-tier LP failover (Freedom 200, xs4all 150, FRR transit 100). Static routes would bypass BGP convergence and create routing inconsistencies. The user explicitly stated: "we do NOT add static routes on the ASA or anywhere else, we use BGP."

**How to apply:** If routes are missing after a chaos test, wait for BGP to converge (30-90s). If peers are stuck, clear only the specific stuck peer on the RR (not on VPS). Never touch VPS upstream sessions.

*Source: `memory/feedback_no_static_routes.md`*

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
