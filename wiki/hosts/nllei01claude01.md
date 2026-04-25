# nl-claude01

**Site:** NL (Leiden)

## Knowledge Base References

**gr:CLAUDE.md**
- You (Claude Code on `nl-claude01`) have SSH access to ALL GR hosts via `~/.ssh/one_key` over the IPsec VPN. Use this for read-only investigation during triage.

**gateway:CLAUDE.md**
- - **Claude Code host (NL):** `nl-claude01` — SSH as `app-user`
- Path: `/app/reference-library/` (~10 GB, ~5,200 files, synced via Syncthing to nl-claude01 + nl-openclaw01).

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **GR ASA SSH requires stepstone via gr-pve01** (feedback): SSH to gr-fw01 only works via gr-pve01 as a jump host — direct SSH from NL is rejected (connection reset).
- **GitHub Public Mirror — agentic-chatops** (project): Auto-synced public mirror at papadopouloskyriakos/agentic-chatops. CI pipeline sanitizes 99 patterns + gitleaks on every push to main.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **n8n Technical Facts and Pitfalls** (project): Key technical facts about n8n, Claude CLI, expression pitfalls, MCP update safety, webhook registration, and known bugs
- **VMID UID Schema** (project): Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.
- **VTI BGP outage investigation 2026-04-11** (project): NL-GR inter-site VTI tunnels down, BGP not peering, complete GR unreachability from NL. Root cause identified.

*Compiled: 2026-04-11 14:13 UTC*