# nl-openclaw01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-openclaw01 | OpenClaw AI agent | `ssh nl-openclaw01` |

**gateway:CLAUDE.md**
- Path: `/app/reference-library/` (~10 GB, ~5,200 files, synced via Syncthing to nl-claude01 + nl-openclaw01).

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **OpenClaw deploy checklist** (feedback): When modifying OpenClaw skill scripts, ALWAYS SSH to nl-openclaw01 to verify and sync ALL related files — not just the one you changed.
- **OpenClaw SSH Access Pattern** (feedback): How to SSH to OpenClaw LXC for configuration changes — direct SSH, NOT pct exec
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **K8s Next Session Tasks** (project): Two pending tasks for K8s operational readiness — OpenClaw K8s access + Prometheus/Alertmanager/Gatus alert wiring
- **knowledge_injection** (project): Knowledge injection into triage pipelines. 51 CLAUDE.md + 200+ memories + compiled wiki (45 articles) surfaced at both tiers via 3-signal RRF. Repo sync cron on openclaw01.
- **Per-Model LLM Usage Tracking** (project): llm_usage table, 3-tier token tracking (Tier 0 local GPU, Tier 1 OpenAI, Tier 2 Claude Code), JSONL-based Claude poller, Prometheus metrics, portfolio live widget. Poller rewrite + data cleanup 2026-04-10.
- **Matrix Bridge Architecture** (project): Matrix Bridge (QGKnHGkw4casiWIU) — 73 nodes. Updated 2026-04-07: typography improvements (blockquote, nested lists, strikethrough, paragraph fix in Prepare Bridge Response markdownToHtml).
- **Pipeline Hardening (2026-04-01)** (project): 11 fixes across 5 workflows + 3 scripts. NetBox Step 2-pre in triage, syslog 3-day, [POLL] fallback parser, escalation cooldown 1h, recovery dedup 60s, flapping timeout 4h, watchdog zombie bounce, Parse Response em-dash + [POLL] approval gate regex. All E2E verified.

*Compiled: 2026-04-11 14:13 UTC*