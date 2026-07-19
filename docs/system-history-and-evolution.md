# The claude-gateway agentic system: origin & evolution

> **Compiled:** 2026-06-21
> **Method:** reconstructed by a 6-lane parallel-reader workflow over git history, the dated `docs/`, `memory/` files, CLAUDE.md's incident log, and YouTrack epic IDs. Five lanes (genesis, backend/model, ops-hardening, governance/autonomy, knowledge/RAG) returned full citation-backed timelines; the sixth (April platform-engineering) over-ran and was stopped, so the April engineering details (QA suite, schema versioning, SDK batch) are filled from CLAUDE.md's platform-features section and are slightly less commit-granular than the rest.

---

## In one breath

It was **born 2026-03-05** (`690ac67`, "initial project structure") to replace a tedious manual loop — a human SSHing into the dev box, running Claude Code by hand, pasting in YouTrack issue context, and babysitting 5–15-minute sessions. The founding idea: **YouTrack issue → n8n → Claude Code → Matrix (human-in-the-loop) → YouTrack**, with "no SDK dependency, works with any Claude Code version." In ~3.5 months and **664 commits** it grew from that chat bridge into a multi-site, self-monitoring, self-documenting agentic ops platform that now auto-resolves real production incidents. Notably, from **day 2 onward the system authors its own commits** — the first commits are by the human (`llzzrrdd`); from `c4f6290` on, almost everything is `Claude Runner` with `Co-Authored-By: Claude`.

The commit cadence tells the macro-story by itself:

| Month | Commits | Character |
|---|---:|---|
| 2026-03 | 222 | Birth → bridge → platform (frantic build) |
| 2026-04 | 297 | Self-audit & hardening (densest month) |
| 2026-05 | 79 | Operating at scale, incident-driven |
| 2026-06 | 66 | Toward real autonomy |

---

## The eras

### Era 0 — Genesis & the day-2 pivot (Mar 5–7)

The very first commit shipped a **tmux-based v1**: n8n SSHed into the dev box `ankh`, spawned one `tmux` session per issue (`claude-CUBEOS-XX`), drove it with `send-keys`, and scraped output with `capture-pane` into a single `#claude-gateway` Matrix room. It was **thrown out within hours**. After "3+ hours of fighting it" (the "Why not tmux" section in `c4f6290`), the canonical architecture was born on **day 2**: SSH headless `claude -p "…" --output-format json` for turn 1 (returns a `session_id`), then `claude -r <id> -p …` to resume — clean JSON, clean session continuity, no screen-scraping. So the architecture everyone thinks of as "v1" is technically **v2, born Mar 6**.

That same day produced a bug-storm whose fixes became the system's durable control primitives — nearly all of them about **stopping the system from triggering itself**:

- **sha256 + line-count dedup** (`199f094`) — invented to dedup tmux scrollback, later became the *alert-dedup pattern* in every receiver.
- **Execution-storm guard** (`107c456`) — lockfile + `unset CLAUDECODE &&` prepended to every call (the `CLAUDECODE` env var was silently blocking nested headless sessions).
- **Parse JSON from stderr, not stdout** (`f9ec7f7`) — the CLI wrote JSON to stderr, so every parse fell through to "No response from Claude."
- **`!done` cooldown marker** (`7804702`) — posting the YouTrack summary re-fired the webhook and restarted the session; clean-up now happens *before* posting.
- **Message queuing + bang commands** (`020aa09`) — `!done`/`!status`/`!cancel` bypass the lock.

By Mar 7, state moved from `/tmp` JSON to **SQLite** (`efabd15`) — the substrate that would later hold every knowledge, transcript, diary, wiki, usage, and learning table — plus a central command router (`!session`/`!issue`/`!pipeline`/`!system`).

### Era 1 — From bridge to platform (Mar 10–29)

- **Mar 10 — Two-tier architecture (`16a9298`).** OpenClaw introduced as a fast/cheap **Tier-1 triage** agent in front of the heavy Tier-2 Claude Code, with the 4-mode routing (`oc-cc`/`oc-oc`/`cc-cc`/`cc-oc`) switchable via `!mode`. Same day the single `#claude-gateway` room (alive only ~4 days) was **decommissioned** for prefix-routed operational rooms (`#cubeos`, `#meshsat`, `#infra-*`).
- **Mar 13 — ChatOps proper.** The pivot from issue/chat-driven to **alert-driven**: LibreNMS receiver + infra-triage skill + a background-launch/progress-polling Runner (Claude runs via `nohup`, a Poller posts tool activity to Matrix). This is when it became an autonomous incident responder. A custom **Proxmox MCP** (15 tools) landed the same day.
- **Mar 18 — Second site.** GR (Greece, `gr`) onboarded with its own dedicated LibreNMS — seeding the NL/GR dual-clone receiver pattern.
- **Mar 23 — The "21/21 agentic patterns" merge (`c3002c8`).** In one day: per-project **slot locks** (concurrency across dev/infra-nl/infra-gr), session **cost & outcome tracking**, the **incident knowledge base + RAG injection** (`807c8ff` — retrieval is born), **cross-tier reflection**, **approval-timeout escalation**, and **interactive `[POLL]` plan selection** (MSC3381). This is the moment it became a *measurable agentic platform*, not just automation.
- **Mar 24 — First formal grade: A−** (`chatops-audit-2026-03-24.md`, `IFRNLLEI01PRD-222`), benchmarked against Antonio Gulli's *Agentic Design Patterns* + Anthropic's Claude Certified Architect exam guide. Plus a sanitized **GitHub public mirror**.
- **Mar 25 / Mar 29 — The three subsystems crystallize.** ChatDevOps (CI Failure Receiver + dev rooms, `c61ca60`) on the 25th; **ChatSecOps** (CrowdSec + security receivers + a self-hosted MITRE ATT&CK Navigator, `07811b4`) on the 29th. The **ChatOps / ChatSecOps / ChatDevOps** trichotomy that still defines the repo is a *late-March construct* — not present at birth.

### Era 2 — The self-audit & hardening month (April)

April is the densest month (297 commits) and its signature is a **continuous external-source audit → scorecard → remediation-sprint cadence**: the system repeatedly graded itself against published frameworks and closed the gaps. The audit lineage runs Gulli's book → tri-source eval (`tri-source-eval-report-2026-04-07`) → industry benchmark (`industry-benchmark-2026-04-15`) → NVIDIA DLI Agentic-AI (`nvidia-dli-cross-audit-2026-04-29`, graded A then lifted to **A+ 4.83**) → the OpenAI Agents SDK → eventually the *LLM Engineer's Handbook* (June). Two parallel build-outs:

**(a) The engineering/governance hardening layer:**

- **Apr 19 — RAG circuit breakers** (`IFRNLLEI01PRD-631`) — 4 named breakers around every external retrieval call.
- **Apr 20 — OpenAI SDK adoption batch** (`IFRNLLEI01PRD-635..-643`): **schema versioning** on session/audit tables, immutable per-turn snapshots, 13 typed `event_log` events, lifecycle hooks, a 3-behavior **rejection taxonomy** (allow/reject_content/deny), the `HandoffInputData` envelope, gemma3 transcript compaction, plus the two governance items below.
- **QA suite** (44 files, 411/0/2 by Apr 23) and the **preference-iterating prompt patcher** (`-645`, A/B trials at the prompt level).

**(b) The knowledge/memory explosion** (see "Building a memory" below) — the **Apr 9 double landing** of the Karpathy wiki-compiler + MemPalace, the **Apr 18** RAG overhaul (25%→88% hit@5), local-first judge (Apr 19), CLI-session capture + the 5-tier teacher-agent (Apr 20).

### Era 3 — The great migration (late April)

The model topology had been consolidating onto Anthropic: OpenClaw's Tier-1 model churned `devstral → GPT-4o → GPT-5.1 (Apr 7) → claude-sonnet-4-6 via OAuth Max ($0, Apr 28, IFRNLLEI01PRD-746)`. Then, **back-to-back**, the very OAuth path adopted on Apr 28 was killed:

- **Apr 29 — OpenClaw retired; cc-cc becomes default (`484f5da`).** Driven by Anthropic's **April-4 ban on OAuth tokens for third-party tools** (OpenClaw is third-party) + an OpenClaw 2026.4.26 MCP-bind regression. The clean-exit insight from the same-day audit: **"OpenClaw was never doing the triage analysis — the bash scripts (`k8s-triage.sh` 40 KB, `infra-triage.sh` 58 KB) are the agent; OpenClaw was a thin spawn-and-run wrapper."** So all 9 alert receivers were rewired to **SSH directly into `nl-claude01`** via a single `run-triage.sh` entry point. The migration also forced 6 `yt-*` helpers + `escalate-to-claude.sh` (which had lived *only* inside the OpenClaw container) into version control — removing a hidden SPOF. OpenClaw was **stopped, not deleted** (LXC `onboot=0`, modes dormant) — reversible-by-design.
- **Apr 30 — Twilio SMS bridge** (`alertmanager-twilio-bridge.py`) replaces the lost OpenClaw notification path.

### Era 4 — Operating at scale (May–June)

The center of gravity shifted from *building the platform* to *operating a growing multi-site mesh*. The operational surface grew on every axis: **5→6 PVE nodes** (nlpve04), **4→5 edge VPS sites** (Houston/TX), the **Norway-DMZ pair** entered the mesh, AS64512 BGP/VTI relationships spanned all VPS — and **each expansion broke a self-monitoring assumption baked in for a smaller topology**. The era's defining failure-class is the **months-long silent failure**, almost always caught and then permanently guarded:

| Date | Incident | Permanent guardrail it produced |
|---|---|---|
| 05-04 | Scanners (`nuclei`/`testssl`) **dark ~5 weeks** (cron PATH excludes `/usr/local/bin`) | `export PATH` + stderr breadcrumbs; lesson memory |
| 05-05 | SeaweedFS cross-site replication **stuck 145 days** | First cross-site DR runbook; per-pod diagnosis discipline |
| 05-07 | BREACH gzip (CVE-2013-3587) across the public estate | 3-layer fix (base images + per-repo + IaC) |
| 05-12→14 | nl-gpu01 daily freezes — **`discard=on` was a symptom-fix**; true cause = OpenZFS 2.3 **Direct-I/O verify-write race** | `direct=disabled` on **all 6 PVE hosts** + `check-zfs-dio-disabled.sh` drift-check |
| 05-15 | apiserver `ctrl01` **crash-looping 27 days** (restartCount 1665) from balloon-evicted etcd cache | No-balloon-on-control-plane rule; the `[PENDING]`-balloon reboot gotcha |
| 05-16→17 | Public BGP diagram under-rendering (4+0 vs real 7+2 transits) | AS64512 4-alert Prometheus family + `upstream-bgp-failure` runbook |
| 06-15→17 | GR site isolated when InAlan WAN dropped (you can't monitor a site through the link that's down) | **Out-of-band** GR-side probe + SMS (`gr-inalan-wan-monitor.py`) |

Two big resilience proofs landed here too: the **Freedom XGS-PON outage (4d 15h, May 8–13)** rode VTI failover with **zero user-visible downtime**, and the dev side scaled out with an **orchestrator-workers** architecture for safe 4-way parallel coding (May 17).

### Era 5 — Toward real autonomy (June)

- **Jun 9 — Infragraph "world model" (`IFRNLLEI01PRD-1029`)** built concept-to-live in one day: a causal infra dependency graph (356 nodes / 414 edges, 5 truth layers) that gives the remediation lane a **fail-CLOSED, `plan_hash`-keyed prediction gate** (no approval poll without a committed machine prediction) and **mechanical match/partial/deviation verdicts** the LLM cannot author. Backtest passed a falsifiable shuffled-control criterion (0.367 ≤ 0.5×).
- **Jun 16 — Autonomy-forward gate (`IFRNLLEI01PRD-1102`).** Measurement (`-1101`) showed the operator voted on **0 of 824 polls** in 30 days (last vote May 7). The binary gate was stranding ~56% of sessions on an unanswered poll. Replaced with 3 bands — **AUTO / AUTO_NOTICE+SMS / POLL_PAUSE+SMS** — and a new session→SMS path. "Human as **circuit-breaker**, not gatekeeper."
- **Jun 17 — The dark-pipeline repair + first real auto-resolve.** Investigation revealed the whole autonomy stack had been **dark for months across 5 layers** (lost `=` expression-mode + `Buffer`-in-sandbox → empty plans → fail-closed; close-out never wired → 353 sessions piled up; AWX-runbooks-as-risk → 100% polling). After the repair, the **first genuine Tier-2 auto-resolve** happened: `IFRNLLEI01PRD-1117` (nlnc01 service up/down, critical) — a real 26-turn `claude-opus-4-8` session (conf 0.86) confirmed recovery, classified band=AUTO, reconciled to YT Done.

---

## The deepest through-lines (the evolutionary logic)

**1. The autonomy arc — gatekeeper → circuit-breaker.** This is the cleanest causal chain in the codebase; each step is *forced by the prior step's specific failure mode*:

> v0 polls were pure overhead on read-only work → **`-632`** binary `auto = risk-low` gate (Apr 19) → but it could only auto-resolve *reads* and had no machine notion of what a *mutating* action would do → **`-1029`** infragraph world-model + fail-CLOSED prediction gate + mechanical verdicts (Jun 9) → but the gate assumed a watching human who had actually left (0/824) and stranded ~56% of sessions → **`-1102`** 3-band circuit-breaker + SMS (Jun 16) → and the whole stack turned out to have never run in production → **Jun 17** 5-layer repair + first real auto-resolve.

A counterintuitive corollary: turning the autonomy gate **off** reverts to *legacy* risk handling, which is **less** strict on destructive ops (`terraform destroy` was only MIXED pre-retag; `mkfs`/`zpool destroy`/`dropdb` were unmatched). The runbook explicitly says "keep it ON" — the more-autonomous mode is also the safer one.

**2. Designed autonomy ≠ operating autonomy.** Every layer's ambition repeatedly outran its plumbing (Build-Prompt fragility deferring the `-632` wiring; the 5-layer dark pipeline behind `-1102`). The recurring lesson: the spine only counts when proven end-to-end on a real alert.

**3. The audit-driven cadence.** From the Mar 24 A− grade onward, the system used external frameworks as a north star — Gulli's book, the Claude Certified Architect rubric, NVIDIA DLI, the OpenAI Agents SDK, industry benchmarks, the LLM Engineer's Handbook — each producing a scorecard and a remediation sprint. It even records the *limits of its own metrics* (the judge-calibration doc says 85% agreement means trend lines are "comparable but noisy").

**4. Building a memory (single-signal → multi-signal retrieval).** `incident_knowledge` + semantic RAG (Mar 23) → +keyword → **+wiki** (Apr 9, Karpathy wiki-compiler) → **+transcript** (Apr 9, MemPalace `session_transcripts` + `agent_diary` + temporal `valid_until` + auto-save hooks) → **+chaos baselines** (Apr 15, 5-signal RRF) → then **reranked/fused/synthesized** (Apr 18 DLI overhaul: dedicated bge-reranker service on nl-gpu01, RAG-Fusion, LongContextReorder — **25%→88% hit@5**). Discipline throughout: **no new infrastructure** (reused SQLite + nomic-embed + Ollama; explicitly rejected ChromaDB) and **store everything, make it findable** (CLI-session capture closed a ~2,300-session gap on Apr 20). The system even turns its knowledge *outward* — the **5-tier teacher-agent** (Apr 20) teaches the *operator* agentic-systems theory from the system's own compiled docs.

**5. Single-site → multi-site mesh.** NL → +GR (Mar 18) → +Norway-DMZ pair (May 5) → +Houston/TX (May 6), with BGP/VTI overlay across all VPS. The maturation endpoint: **self-monitoring that survives its own telemetry path failing** (out-of-band GR probe + SMS, June 17) and **honest telemetry under failure** (emit stale-flags instead of 0/0; per-incident not per-event metrics).

**6. Cost-to-$0 / provider consolidation.** `GPT-4o → GPT-5.1 → claude-sonnet-4-6 (OAuth Max) → single-provider Claude estate`; local-first judge/synth on the GPU; **no fine-tuning** (an explicit ADR — behavioral adaptation is prompt-policy iteration + RAG, never weight updates). Tier-2 marginal cost is $0 on the Max subscription, though the API-equivalent (~$16,420) is still tracked for honesty.

---

## Where it is now (mid-June 2026)

A single-provider (Anthropic) **cc-cc** platform: 9 alert receivers SSH directly into `nl-claude01`, with a GR oversight twin (`grclaude01`). Retrieval is a multi-stage 5-signal RRF pipeline over **~21,600 embedded vectors** (incident_knowledge 1,423 / wiki 2,905 / transcripts 17,219 / chaos 70), evaluated by RAGAS + a 2-model judge jury, with auto-regenerating architecture/metrics docs. Governance is a **3-band autonomy-forward gate** backed by an infragraph world-model and a fail-CLOSED prediction gate — and as of Jun 17 it has **actually auto-resolved its first real production incident**, with a safety floor (irreversible / deviation / no-prediction / P0-reboot) that no sentinel can override and an `rm`-one-file kill-switch.
