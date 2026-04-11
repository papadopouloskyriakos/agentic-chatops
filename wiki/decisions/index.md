# Architectural Decisions

> Extracted from 44 project memory files. Compiled 2026-04-09 06:19 UTC.

- **03_Lab Reference Library Integration**: 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **agentic_patterns_21_21**: 21/21 agentic design patterns — tri-source audited 11/11 dimensions A+ (100%). 16 YT issues implemented 2026-04-07.
- **alert_pipeline_v2_2026_03_18**: Major alert pipeline upgrade (2026-03-18): flap detection, issue dedup, confidence scoring, error propagation, CI/CD review, retry loops, few-shot prompts, context summarization
- **Tier 2 allowlist audit 2026-03-28**: Allowlist trimmed 236→50, golden test monthly→biweekly, 7 external proposals audited (2 implemented, 5 skipped)
- **ASA Weekly Reboot Suppression**: EEM watchdog timers on both ASAs auto-reboot weekly; 4-layer suppression prevents false alerts
- **CodeGraphContext (CGC) Setup**: Code graph database for CubeOS/MeshSat — Neo4j backend, scheduled reindex (no live watcher), MCP server, 43K nodes across 5 repos
- **dual_source_audit_2026_04_03**: Comprehensive dual-source audit (Anthropic docs + Gulli book) — hooks, sub-agents, skills, guardrails, sanitization, RAG, VPN fix. 8+1 YT issues.
- **Dual-WAN VPN full parity (Freedom + xs4all)**: Both NL WANs have full S2S tunnel coverage. Freedom PPPoE outage auto-handled via xs4all failover, QoS cron, SMS alerting, and trained triage scripts.
- **MeshSat E2E verified**: First real-device E2E test successful — Pi5 AES-256-GCM encrypted SMS decrypted on Android v1.2.1
- **frigate_doorbell**: Frigate NVR (nlfrigate01) and n8n doorbell workflow — architecture, auth, JWT fix, integrations
- **GitHub Public Mirror — agentic-chatops**: Auto-synced public mirror at papadopouloskyriakos/agentic-chatops. CI pipeline sanitizes 99 patterns + gitleaks on every push to main.
- **GitHub Public Mirror Sync (IaC repo)**: IaC repo GitHub sync pipeline — paths, sanitization rules, runner image rebuild process. Second mirror (claude-gateway → agentic-chatops) added 2026-03-24, see github_mirror_chatops.md.
- **gr_chatops_infra**: GR site (gr) ChatOps infrastructure — complete multi-site alert pipeline, triage scripts, n8n workflows, kubeconfig, LibreNMS transport, Alertmanager webhook
- **GR Claude Agent (grclaude01)**: Claude Code agent at GR site for NL maintenance oversight. VMID 201021201, 10.0.X.X, gr-pve01.
- **GR iSCSI Server (gr-pve02)**: GR K8s iSCSI storage — ZFS zvols on PERC H710P, architecture, tunables, AWX PVC fix, SeaweedFS migrated to NFS/sdc
- **haha_voice_pe_upgrade**: HA Voice PE firmware — v7 working (v6 upstream + Squeezebox routing), Ollama q4_0 fix, REST sensors FIXED, 2026-03-16 audit fixes
- **Freedom ISP PPPoE Outage 2026-04-08**: Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration**: IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **IoT Pacemaker HA Cluster**: 3-node Pacemaker/Corosync IoT cluster (nlcl01iot01/nl-iot02/nlcl01iotarb01) — topology, resources, failover behavior, VMID 666
- **K8s Next Session Tasks**: Two pending tasks for K8s operational readiness — OpenClaw K8s access + Prometheus/Alertmanager/Gatus alert wiring
- **knowledge_injection**: CLAUDE.md + memory knowledge injection into triage pipelines. 51 CLAUDE.md files + 200+ feedback memories now surfaced at both tiers. Repo sync cron on openclaw01.
- **Per-Model LLM Usage Tracking**: llm_usage table, per-model token/cost tracking for both tiers, OpenAI admin key polling, Prometheus metrics. Implemented 2026-04-07.
- **maintenance_companion**: Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **Matrix Bridge Architecture**: Matrix Bridge (QGKnHGkw4casiWIU) — 73 nodes. Updated 2026-04-07: typography improvements (blockquote, nested lists, strikethrough, paragraph fix in Prepare Bridge Response markdownToHtml).
- **MeshSat next session plan**: T-Deck → Pi → SMS → Android → SBD → RockBLOCK → Webhook → MeshSat HUB → PGP Email pipeline
- **MeshSat session 2026-03-16**: MSVQ-SC compression, Android SMS, field intelligence, full Android parity (7 phases), 59 unit tests, MESHSAT-57 DONE
- **n8n Technical Facts and Pitfalls**: Key technical facts about n8n, Claude CLI, expression pitfalls, MCP update safety, webhook registration, and known bugs
- **OOB Access via PiKVM + Cloudflare Tunnel**: BROKEN (2026-03-21) — PiKVM bricked by forced package upgrade. Requires physical access to GR site to recover. Cloudflare tunnel config still exists but PiKVM is offline.
- **OpenClaw Audit & Upgrade — 2026-03-25**: Full compliance audit (Gulli book + Anthropic exam guide), config drift fix (6 files deployed), OpenClaw 2026.3.3→2026.3.23, LXC disk 21→64GB, 13 prioritized findings.
- **PiKVM and LTE Gateway Audit**: Audit of grpikvm01 (PiKVM v3) and grlte01 (Cisco C819G LTE) — config, findings, OOB architecture rationale
- **Pipeline Hardening (2026-04-01)**: 11 fixes across 5 workflows + 3 scripts. NetBox Step 2-pre in triage, syslog 3-day, [POLL] fallback parser, escalation cooldown 1h, recovery dedup 60s, flapping timeout 4h, watchdog zombie bounce, Parse Response em-dash + [POLL] approval gate regex. All E2E verified.
- **PVE Kernel Maintenance Automation**: Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25**: Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **Runner and Poller Workflow Flows**: Runner (47 nodes incl. Evaluator-Optimizer), Poller (10 nodes), Session End (12 nodes). Updated 2026-04-07: XML-tagged RAG, hybrid RRF, tool profiles, Evaluator-Optimizer (3 new nodes), 16 PII patterns, tool call limit.
- **S2S Tunnel Benchmark NL<->GR**: IPsec VPN benchmark results, ASA config findings, line speeds, throughput bottleneck analysis (2026-03-21)
- **SeaweedFS Cross-Site Replication**: SeaweedFS bi-directional filer-sync between NL and GR K8s clusters — architecture, quirks, known limitations, and operational gotchas
- **security_alert_receivers**: Security + CrowdSec alert pipelines (4 workflows, 6 CrowdSec hosts), scanner VMs, triage skill (10 steps, 3 TI sources), learning loop, baseline polls, ATT&CK Navigator. 2026-04-07: YT descriptions use markdown tables, triage delegation structured messages, 8 IF node singleValue fixes.
- **n8n template portal submission**: Status and feedback history for the n8n creator portal template submission of the Claude Gateway workflow
- **Thanos Cross-Site Architecture**: Thanos Query federation NL<->GR via ClusterMesh — FULLY OPERATIONAL (2026-03-21). All gaps resolved, 275 targets visible cross-site.
- **Tri-source audit implementation (2026-04-07)**: Full implementation of 16 YT issues to reach 11/11 A+ across all dimensions. Hybrid RRF, eval flywheel, Evaluator-Optimizer, deployment guide.
- **Visual Audit and Typography Improvements**: Playwright visual audit suite + formatting improvements across 10 workflows. markdownToHtml (blockquote, nested lists, strikethrough, paragraph fix), progress poller MCP tool names, triage delegation, YT structured comments. 2026-04-07.
- **VMID UID Schema**: Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.
- **vti_dual_wan_lessons**: VTI dual-WAN deployment lessons — CrowdSec bans, netlink buflen, port_nat_t, UFW gaps found during 2026-04-09 session
- **VTI Migration Completed 2026-04-09**: ASA crypto-map VPN replaced with VTI tunnels. Dual-WAN. strongSwan swanctl+XFRM. BGP transit overlay. E2E failover proven.

## Audit Reports

- [aci-tool-audit.md](../../docs/aci-tool-audit.md)
- [agentic-patterns-audit.md](../../docs/agentic-patterns-audit.md)
- [chatops-audit-2026-03-24.md](../../docs/chatops-audit-2026-03-24.md)
- [chatsecops-industry-audit.md](../../docs/chatsecops-industry-audit.md)
- [evaluation-process.md](../../docs/evaluation-process.md)
- [tri-source-audit.md](../../docs/tri-source-audit.md)
- [tri-source-eval-report-2026-04-07.md](../../docs/tri-source-eval-report-2026-04-07.md)