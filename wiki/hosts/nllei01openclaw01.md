# nl-openclaw01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-openclaw01 | OpenClaw AI agent | `ssh nl-openclaw01` |

**nl:native/syncthing/CLAUDE.md**
- agents:              nl-claude01 (daemon inactive),  nl-openclaw01 (LXC dormant)
- | `nl-openclaw01` | (LXC `VMID_REDACTED` on `nl-pve03`) | n/a | Dormant — LXC stopped per `cc-cc` mode (since 2026-04-29). |
- | `03lab` | `03_Lab` | nlsyncthing01, grsyncthing01, nl-claude01, nl-openclaw01, fouska-wireless | ~10 GB, ~5,200 files. Lab reference library. Read-only convention on agent nodes. |
- | `nl-openclaw01` | LXC `VMID_REDACTED` on `nl-pve03` — `pct exec` (currently stopped) |

**gateway:CLAUDE.md**
- Path: `/app/reference-library/` (~10 GB, ~5,200 files, synced via Syncthing to nl-claude01; previously also to nl-openclaw01, that LXC was destroyed 2026-04-29).
- > **2026-06-28 status:** the mode abstraction is **vestigial and slated for retirement.** Only `cc-cc` is live. OpenClaw was retired 2026-04-29 and its LXC (`VMID_REDACTED` / `nl-openclaw01`) has since been **destroyed** ("not found on any node") — the `pct start VMID_REDACTED` restore path below is **broken**. All 9 alert receivers SSH-direct to `scripts/run-triage.sh`. `~/gateway.mode` is **stale** (`oc-cc` since 2026-03-11) and harmless (dispatch is hardwired, not read from the file); it reports the wrong mode on the dashboard. Model selection is now centralized via the [Model Orchestration](#model-orchestration-centralized-2026-06-28-mrs-116120) layer, which supersedes the frontend/backend-pairing concept these modes encoded.
- - **Agentic-platform sweep (2026-04-25):** Diagnosed + fixed regression introduced by 04-24 `b9c0661`: `chaos-test.py:cmd_start` outer `fcntl.flock` + `b9c0661`'s inner `marker_lock()` re-flocked the same file on a separate fd → Linux per-fd EAGAIN against the same process → every `chaos-test.py start` ABORTed since 2026-04-23 evening (counter stuck at 122/107 = 6 lost intensives / 18 baseline experiments). Fixed in `8075721` (remove outer flock; inner `marker_lock()` preserves cross-drill protection via `chaos_marker.py:install_marker`) + `b0647df` (refresh stale references in docstring + `save_state` comment). Validated: `test-709-chaos-marker-lock` 5/5 PASS + scratch-isolated 7-step e2e (marker_lock + check + write + own-drill identity + cross-drill raise + exception-attrs + cross-process contention). Side-fix: `node_exporter` on `nl-openclaw01` `Exited(143)` since 2026-04-22 (deliberate `docker stop`) — restored. YT closed: `-728`, `-731`, `-732`. New: `-733` filed for `gemma3:12b` `num_gpu 49` Modelfile pinning. Reusable lesson: `memory/feedback_no_double_flock_same_path.md`. Full summary: `memory/agentic_batch_20260425.md`.

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **Agentic-platform sweep — 2026-04-25** (project): Post-04-24-batch regression diagnosed + fixed (chaos cmd_start self-flock); node_exporter restored on openclaw01; 3 YT alerts moved to Done.
- **agentic_state_orange_verified_20260628** (project): "2026-06-28 verified the post-benchmark 'orange' issue tier against live sources — ALL items dissolved under verification (3 agent fabrications + false_auto_resolve/demotion gap audited to 0 misfires); no code fixes warranted. MRs !123/!124 shipped + reusable Cronicle-API pattern."
- **defra01agri01 SSH pattern — operator + one_key + sudo -i ONLY** (feedback): Hard rule for every SSH session to defra01agri01. User operator with ~/.ssh/one_key only. No passwords ever. Privilege escalation via passwordless sudo -i.
- **OpenClaw deploy checklist** (feedback): When modifying OpenClaw skill scripts, ALWAYS SSH to nl-openclaw01 to verify and sync ALL related files — not just the one you changed.
- **OpenClaw SSH Access Pattern** (feedback): How to SSH to OpenClaw LXC for configuration changes — direct SSH, NOT pct exec
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **K8s Next Session Tasks** (project): Two pending tasks for K8s operational readiness — OpenClaw K8s access + Prometheus/Alertmanager/Gatus alert wiring
- **knowledge_injection** (project): Knowledge injection into triage pipelines. 51 CLAUDE.md + 200+ memories + compiled wiki (45 articles) surfaced at both tiers via 3-signal RRF. Repo sync cron on openclaw01.
- **Per-Model LLM Usage Tracking** (project): llm_usage table, 3-tier token tracking (Tier 0 local GPU, Tier 1 OpenClaw OAuth Sonnet [migrated from OpenAI 2026-04-28 IFRNLLEI01PRD-746], Tier 2 Claude Code), JSONL-based pollers, Prometheus metrics, portfolio live widget. Poller rewrite 2026-04-10. Tier 0 per-call tracking added 2026-04-16. poll-openclaw-usage.sh added 2026-04-28 (replaces poll-openai-usage.sh).
- **Matrix Bridge Architecture** (project): Matrix Bridge (QGKnHGkw4casiWIU) — 73 nodes. Updated 2026-04-07: typography improvements (blockquote, nested lists, strikethrough, paragraph fix in Prepare Bridge Response markdownToHtml).
- **OpenClaw container — SOUL.md / memory-recall / safe-exec already in sync** (project): Audit 2026-04-24 — three CLAUDE.md "Remaining Roadmap" sync items are stale; files already match container md5
- **OpenClaw → Ollama local triage (2026-04-29)** (project): Wired OpenClaw 4.26 to use local Ollama with qwen2.5:7b after failing to make the claude-cli OAuth path work post Anthropic April-4 OpenClaw policy. Working at ~3 min/call latency, $0 cost. Hardware caps model size at 7-12B on this GPU.
- **OpenClaw Tier 1 GPT-5.1 → Sonnet OAuth migration plan** (project): 2026-04-28 audit + plan to replace OpenAI GPT-5.1 in OpenClaw with Sonnet 4.6 via OpenClaw's native --auth-choice claude-cli (Max sub OAuth, $0). Plan file at ~/.claude/plans/replicated-napping-galaxy.md.
- **OpenClaw 4.10+4.11 Upgrade Audit** (project): Audit of OpenClaw releases 2026.4.7-4.11 against current system. Version gap 2026.3.3→4.11 (8 releases). Active Memory, Dreaming, memory-wiki, security hardening. Prioritized recommendations.
- **OpenClaw v2026.4.22 Upgrade Audit** (project): Pre-decision audit of OpenClaw v2026.4.22 (released 2026-04-23) vs our running v2026.4.11. 11 tags / 716 commits ahead. Relevant fixes, traps, non-applicable items, three paths. DECISION PENDING.
- **OpenClaw v2026.4.26 upgrade** (project): 2026-04-29 upgrade from 2026.4.11 to 2026.4.26. Build process, gotchas, persistence, test results.
- **Pipeline Hardening (2026-04-01)** (project): 11 fixes across 5 workflows + 3 scripts. NetBox Step 2-pre in triage, syslog 3-day, [POLL] fallback parser, escalation cooldown 1h, recovery dedup 60s, flapping timeout 4h, watchdog zombie bounce, Parse Response em-dash + [POLL] approval gate regex. All E2E verified.
- **nlpve04 onboarding (COMPLETED)** (project): ASRock GENOAD8X-2T/BCM (AMD EPYC 9334 32C/64T, 128GB DDR5, 6TB max) onboarded as 6th cluster member nlpve04. Clone-of-pve02 corosync rejection → identity wipe → rename → join.
- **Syncthing node inventory location** (reference): 12-node Syncthing mesh roster + IaC home + private discovery/relay setup

*Compiled: 2026-07-03 04:30 UTC*