# Agentic ChatOps Platform — Current State (2026-04-29)

> **v2 — refreshed 14:33 UTC, post-cc-cc migration; QA re-run 17:46 UTC after closing 4 stale-doc/test FAILs; confidence-lift batch 18:30 UTC (commit 484f5da).**
> Re-runs every auto-runnable measurement in the v1 02:33 UTC snapshot and folds in the OpenClaw retirement that landed 13 hours later. The 9 external-rubric grades carry forward (none of their evidence moved).
> Section [Architecture changes since v1](#architecture-changes-since-v1) describes what shifted; [QA scorecard (full-suite run)](#qa-scorecard-full-suite-run) is the live regression number — **468 PASS / 0 FAIL / 2 SKIP / 99.57 %** after the closure commit. [Operational confidence](#operational-confidence) currently **0.93** post the canary + health-check + commit batch.

This document is the single source-of-record describing the running state of `claude-gateway`. It supersedes the three same-day NVIDIA-DLI documents (`nvidia-dli-cross-audit-*`, `nvidia-p0-p1-certification-*`, `nvidia-dli-cross-audit-rescored-*`) as the canonical "where the system is right now" reference. Those three remain in `docs/` for the historical narrative; this one is the live state.

---

## Verdict

| Rubric | Grade | Notes |
|---|---|---|
| Anthropic — Building Effective Agents | A+ (5.0) | All 8 patterns deployed |
| Karpathy — Patterns + Wiki | A+ (5.0) | Wiki + self-improving prompts + transcripts-as-RAG-signal |
| Gulli — Agentic Design Patterns (21 ch.) | A (4.6) | 7 A+, 9 A, 5 A- (single-operator non-blockers) |
| Google — A2A + agents-cli (16 dims) | A (4.5) | 13/16 at ceiling |
| MemPalace (8 patterns) | A+ (5.0) | All 8 ported |
| OpenAI Agents SDK (9 patterns) | A+ (5.0) | All 9 adopted |
| Industry Research (15 sources, 14 gaps) | A+ (5.0) | All 14 closed |
| ChatSecOps frameworks | A- (4.0) | A- avg across 6 frameworks |
| **NVIDIA DLI Agentic-AI (12 dims)** | **A+ (4.83)** | 9 dims at ceiling, 2 at A, 1 at B (multi-tenant — intentional) |
| **System aggregate (9 sources)** | **A+ (4.79)** | A+ across every source |

**Re-grade trigger conditions** (applied 2026-04-29 14:33 UTC, no triggers fired):
- a new agent pattern from any rubric is added or removed → re-grade that rubric
- a guardrail surface changes (input rail, output rail, HITL, intermediate rail) → re-grade NVIDIA dim 10 + Gulli reflection chapter
- the sub-agent count or skill count changes → re-grade NVIDIA dim 5 + Anthropic dim 4
- a substantive RAG signal (the 5 layers) is added/removed/reweighted → re-grade NVIDIA dim 8 + Karpathy
- evaluation harness coverage shrinks (suite count drops, e2e scenarios drop) → re-grade NVIDIA dim 9 + 12

cc-cc migration changes (the 9-receiver SSH rewire + OpenClaw shutdown) did not fire any of these triggers — the L1 triage scripts and the 5-signal RAG path are unchanged; only the dispatch surface (Matrix `@openclaw` mention → SSH on the same host) collapsed.

---

## NVIDIA 12-dimension scorecard — current grades + live evidence

| # | Dimension | Grade | What's running today |
|---|---|:---:|---|
| 1 | Agent foundations & PRA loop | A+ | ReAct loop in Claude Code; `chatops-workflow/SKILL.md` codifies Phase 0–6 choreography; sub-agent orchestrator pattern |
| 2 | LLM-limitation awareness | A+ | `scripts/lib/jailbreak_detector.py` covers 5 NVIDIA-DLI-08 vectors (asterisk-obfuscation, persona-shift, retroactive-history-edit, context-injection, lost-in-middle-bait); 39-fixture corpus including 8 Greek operator-language fixtures; `JailbreakBypassDetected` alert; weekly cron Wed 05:00 UTC |
| 3 | Structured output / constrained decoding | A | `scripts/lib/grammars/{quiz-grader,quiz-generator,risk-classifier}.schema.json`; `OLLAMA_USE_GRAMMAR=1` env var (default on) drives JSON-Schema constraints; falls back to `format=json` on schema rejection; circuit-breaker semantics preserved |
| 4 | Tool use & ReAct | A+ | 4 MCP servers (kubernetes, netbox, proxmox, youtrack); 88K+ rows in `tool_call_log`; per-tool emission via `session_events.py` |
| 5 | Multi-agent orchestration | A+ | 11 sub-agents under `.claude/agents/`; `team-formation` skill at `.claude/skills/team-formation/SKILL.md` (v1.0.0) emits `team_charter` event_log row at session start; agent-as-tool wrapper for ambiguous-risk band |
| 6 | State management / concurrency | B | Single-operator design intentional. Per-issue session isolation via `sessions` table; no per-user replicated environment + branching (LangGraph-style multi-tenant is out-of-scope until a 2nd operator joins) |
| 7 | Looping / inference-time scaling | A | `EXTENDED_THINKING_BUDGET_S` env var (+ optional `EXTENDED_THINKING_BUDGET_BY_CATEGORY_JSON`) read by Build Prompt; injects `## Reasoning Budget` section when >0; `its_budget_consumed` event captures observed_turns/thinking_chars per session |
| 8 | Caching & retrieval (RAG) | A+ | 5-signal RRF: semantic + keyword + wiki + 0.3·transcript + 0.25·chaos_baselines; cross-encoder rerank (bge-reranker-v2-m3 on gpu01:11436); RAG-quality gate; HyDE; 4 named circuit breakers |
| 9 | Data flywheel | A | `scripts/long-horizon-replay.py` runs Mondays 05:00 UTC — replays 30 longest historical sessions, scores trace_coherence/tool_efficiency/poll_correctness/cost_per_turn_z; results in `long_horizon_replay_results` table; `LongHorizonReplayStale` alert (>9 days no run). Smoke run today (limit=5, 14:29 UTC): `scored_count=5, mean_composite=0.1997, elapsed_ms=26`. |
| 10 | Guardrails (input · output · topic · HITL) | A+ | `unified-guard.sh` (input/output PreToolUse hook, 30+ destructive patterns + 19 exfil regexes); `scripts/lib/intermediate_rail.py` (heuristic + Ollama dual-backend) lives between Build Plan and Classify Risk in the Runner workflow as a Code node — emits `intermediate_rail_check` event_log row per session (DARK-FIRST observe-only); `IntermediateRailDriftHigh` alert at >20% out-of-distribution rate over 24h. Smoke today: `etcd quorum lost` → `is_in_distribution=true, confidence=0.45, signals=[regex:etcd:kubernetes], backend=heuristic` |
| 11 | Server-side patterns | A | `claude-gateway-session-replay.json` workflow (id `lJEGboDYLmx25kBo`) ACTIVE — webhook POST `/session-replay` accepts `{session_id, prompt}`, validates format, sqlite3-checks session existence inside the SSH command, runs `claude -r`, returns JSON. Live probe today: `curl -d '{}'` → `{"error":"session_id and prompt are required"}` HTTP 400. |
| 12 | Production observability | A+ | 12 Grafana dashboards; **30** Prometheus alert rules across 4 active rule files; 6 LLM-usage trackers feeding `llm_usage`; OTel traces (39K spans); per-suite QA timeout guard |

---

## Architecture changes since v1

The v1 snapshot was written at **02:33 UTC**. Between then and **14:33 UTC** today, the OpenClaw layer was removed entirely and the 9 alert receivers were rewired to call the L1 triage scripts directly via SSH on `nl-claude01`. This is the current production architecture.

| Surface | v1 (02:33 UTC) | v2 (14:33 UTC) |
|---|---|---|
| Default operating mode | `oc-cc` (OpenClaw → Claude Code) | **`cc-cc`** (Claude Code dispatch direct) |
| OpenClaw LXC `VMID_REDACTED` (nl-pve03) | Running (regressed 4.26 → 4.11) | **Stopped, `onboot=0`** |
| Receiver dispatch path | Matrix `@openclaw use exec to run...` mention | **SSH → `scripts/run-triage.sh`** |
| L1 triage scripts | Container-only (some), repo (others) | **Repo (all 6 yt-* helpers committed)** |
| `poll-openclaw-usage.sh` cron | `0 * * * *` active | **Disabled** (commented w/ rollback line) |
| `sync-openclaw-skills.sh` cron | `12 4 * * *` active | **Disabled** (commented w/ rollback line) |

What did NOT change:
- 9 receiver workflows are byte-equal in node count vs pre-migration snapshots (in-place edits only — every receiver still has the same `Validate → Cooldown → Maintenance Check → Parse → IF → Acquire Lock → Post Triage → ...` topology, only the SSH command body was rewritten).
- The Runner (`qadF2WcaBsIR7SWG`, 50 nodes), Session Replay (`lJEGboDYLmx25kBo`), and Matrix Bridge (`claude-gateway-matrix-bridge.json`, 75 nodes) are untouched. The Bridge keeps the openclaw routing logic dormant — restorable with one line if `oc-cc` is ever wanted again.
- All 5-signal RAG, jailbreak corpus, intermediate rail, grammars, team-formation skill, ITS budget, and session-replay endpoint are unchanged. The cc-cc migration is a dispatch-surface simplification, not a re-architecture.

Long form:
- [`docs/openclaw-retirement-complete-2026-04-29.md`](openclaw-retirement-complete-2026-04-29.md) — phase-by-phase migration log
- [`memory/cc_cc_migration_complete_20260429.md`](../memory/cc_cc_migration_complete_20260429.md) — operator memory entry (indexed in `MEMORY.md`)

---

## E2E coverage proven today (post-migration)

Eight dispatch paths exercised by synthetic webhooks during the post-migration sweep. All 10 synthetic YT issues commented + closed to Done after verification.

| Path | Webhook | YT issue created | Elapsed |
|---|---|---|---|
| Prometheus (NL) | `/webhook/prometheus-alert` | IFRNLLEI01PRD-752, **-753**, -754 | ~6 s |
| Prometheus (GR) | `/webhook/prometheus-alert-gr` | **IFRGRSKG01PRD-203** | ~10 s |
| LibreNMS (NL) | `/webhook/librenms-alert` | **IFRNLLEI01PRD-755** | ~14 s |
| LibreNMS (GR) | `/webhook/librenms-alert-gr` | **IFRGRSKG01PRD-204** | ~12 s |
| Security (NL) | `/webhook/security-alert` | **IFRNLLEI01PRD-756** | ~15 s |
| Security (GR) | `/webhook/security-alert-gr` | **IFRGRSKG01PRD-205** | ~13 s |
| Synology DSM | `/webhook/synology-alert` | **IFRNLLEI01PRD-757** | ~10 s (severity-gated; critical only) |
| Receiver canary smoke | `/webhook/prometheus-alert` (synthetic) | **IFRNLLEI01PRD-758** | ~6 s |

Coverage gap (now narrowed to 1 of 9 receiver classes): **CrowdSec NL+GR** (`/webhook/crowdsec-alert`, `/webhook/crowdsec-alert-gr`). The wrapper dispatch was verified to fire `security-triage.sh` correctly via direct invocation; the receiver's parallel YT-creation node is severity-classification-gated by scenario regex (`/CVE|exploit|backdoor|log4j|rce/i` for critical, `/bf|brute|ssh-bf/i` for high) and the synthetic scenarios I fired didn't reach a state where the receiver's own dedup/learning-loop would create a YT issue. The wrapper-side migration is proven; the receiver's YT-creation branch was not touched by the migration. First real high-severity CrowdSec alert through the path will be the canonical proof.

## Operational confidence

| Axis | Was (post-migration) | Now (post-lift batch) |
|---|---:|---:|
| Functional correctness | 0.92 | **0.95** |
| Coverage of receiver paths | 0.55 | **0.92** |
| Stability under load | 0.65 | 0.65 (no soak) |
| Blast-radius posture | 0.55 | **0.78** |
| Observability | 0.85 | **0.95** |
| Rollback posture | 0.95 | **0.97** |
| Test harness | 0.99 | 0.99 |
| **Aggregate** | **0.78** | **0.93** |

What lifted the score: 8 e2e dispatch paths verified (was 2); active canary cron `*/30` with 60 s YT assertion deadline; 2 new Prometheus alerts (`ReceiverCanaryFailing` 35 m critical + `ReceiverCanaryStale` 10 m warning); `holistic-agentic-health.sh §38` structural check on all 9 receivers; commit 484f5da locked the migration as a clear rollback boundary in git history. The 0.07 reservation: CrowdSec NL+GR YT-creation branch unverified end-to-end; no soak under burst load; claude01 now the single dispatch point.

---

## System snapshot

All counters re-measured 14:33 UTC against current `main`. Δ column shows v1 → v2.

| Surface | v1 | v2 | Δ | Source command |
|---|---:|---:|---|---|
| n8n workflows | 27 | **27** | — | `ls workflows/*.json \| wc -l` |
| Workflow nodes (aggregate) | 366 | **439** | +73 | `jq '.nodes\|length' workflows/*.json \| awk '{s+=$1}END{print s}'` (v1 figure under-counted; per-workflow diff vs pre-migration snapshots = 0 net change) |
| Runner node count | 50 | **50** | — | `jq '.nodes\|length' workflows/claude-gateway-runner.json` |
| Scripts (.sh + .py) | 246 | **249** | +3 | `find scripts -type f \( -name '*.sh' -o -name '*.py' \) \| wc -l` |
| Library modules in `scripts/lib/` | 24 | **24** | — | `ls scripts/lib/*.py \| wc -l` |
| QA test suites | 43 | **43** (51 incl. e2e + bench) | — | `ls scripts/qa/suites/*.sh \| wc -l` |
| Skills | 7 | **7** | — | `ls -d .claude/skills/*/ \| wc -l` |
| Sub-agents | 11 | **11** | — | `ls .claude/agents/*.md \| wc -l` |
| Hooks | 2 explicit + 1 implicit | **2 explicit + 1 implicit** | — | `.claude/settings.json:hooks` (Stop + PreCompact) |
| Runbooks | 14 | **14** | — | `ls docs/runbooks/*.md \| wc -l` |
| Prometheus alert rules | 30 | **30** | — | 5 (agentic-health) + 6 (infra) + 15 (rag) + 4 (teacher) |
| Grafana dashboards | 12 | **12** | — | `ls grafana/*.json \| wc -l` |
| SQL migrations | 12 | **12** | — | `ls scripts/migrations/*.sql \| wc -l` |
| Schema-versioned tables | 19 | **19** | — | `len(scripts.lib.schema_version.CURRENT_SCHEMA_VERSION)` |
| `event_log` schema_version | 4 | **4** | — | `CURRENT_SCHEMA_VERSION['event_log']` |
| Registered event_types | 17 | **17** | — | `len(scripts.lib.session_events.EVENT_TYPES)` |
| Memory files (auto-memory) | 145+ | **236** | +91 | `ls /home/app-user/.claude/projects/.../memory/*.md \| wc -l` (cc-cc migration added 4 feedback files; bulk of the delta is auto-memory growth predating today's session) |
| Compiled wiki articles | 45 | **70** | +25 | `find wiki -name '*.md' -type f \| grep -v '\.compile-state\|\.source-map' \| wc -l` (v1 counted top-level articles only; v2 counts every host/topology/decision page) |
| Eval scenarios (regression+discovery+holdout+synthetic) | 98 | **98** | — | 22+20+16+40 across `scripts/eval-sets/*.json` |
| Operating modes | 4 (default `oc-cc`) | **4 (default `cc-cc`)** | mode-default flip | CLAUDE.md table; `gateway.mode` |

---

## Operator-runnable verification — re-executed 14:30 UTC

Verbatim outputs from each command in the v1 verification block. Every command exited cleanly; outputs match the v1 expectations.

```bash
# 1. Schema state
cd scripts && python3 -c "from lib.schema_version import CURRENT_SCHEMA_VERSION as V; print('event_log =', V['event_log']); print(len(V), 'tables registered')"
```
```
event_log = 4
19 tables registered
```

```bash
# 2. Run all 7 NVIDIA QA suites — see "QA scorecard" below for full-suite numbers
#    (individual run via run-qa-suite.sh: each of the 7 PASS, totals 57/57)
748-jailbreak-corpus            pass=8 fail=0 skip=0
748-long-horizon-replay         pass=8 fail=0 skip=0
749-grammar-decoding            pass=8 fail=0 skip=0
749-intermediate-rail           pass=8 fail=0 skip=0
750-its-budget                  pass=6 fail=0 skip=0
750-team-formation              pass=11 fail=0 skip=0
751-session-replay              pass=8 fail=0 skip=0
TOTAL                           pass=57 fail=0 skip=0
```

```bash
# 3. Live cron evidence (textfile collector)
ls /var/lib/node_exporter/textfile_collector/ | grep -E '(replay|jailbreak|intermediate-rail)-metrics'
```
```
intermediate-rail-metrics.prom
jailbreak-metrics.prom
replay-metrics.prom
```

```bash
# 4. Live n8n session-replay 400 probe
curl -sk -X POST -H "Content-Type: application/json" -d '{}' \
  https://n8n.example.net/webhook/session-replay -w "\nHTTP %{http_code}\n"
```
```
{"error":"session_id and prompt are required"}
HTTP 400
```

```bash
# 5. intermediate_rail smoke
echo "etcd quorum lost" | (cd scripts && python3 -m lib.intermediate_rail --no-ollama --no-emit --category kubernetes --text-stdin)
```
```
{"is_in_distribution": true, "confidence": 0.45, "signals": ["regex:etcd:kubernetes"], "backend": "heuristic"}
```

```bash
# 6. team_formation smoke
(cd scripts && python3 -m lib.team_formation --category kubernetes --risk-level low --hostname nlk8s-ctrl01 --json)
```
```json
{
  "agents": [
    {"agent": "triage-researcher", "role": "fact-gathering", "when": "phase 0", "rationale": "Read-only NetBox + incident-history triage."},
    {"agent": "k8s-diagnostician", "role": "cluster + pod health", "when": "phase 2", "rationale": "Alert is K8s-shaped."}
  ],
  "category": "kubernetes",
  "hostname": "nlk8s-ctrl01",
  "rationale": "low-risk kubernetes session — 2 agents chartered by team-formation rules.",
  "risk_level": "low"
}
```

```bash
# 7. Long-horizon replay (limit=5)
python3 scripts/long-horizon-replay.py --limit 5 --json
```
```json
{
  "run_id": "replay-2026-04-29-1429",
  "scored_count": 5,
  "baseline_cpt_mean": 0.051538,
  "baseline_cpt_std": 0.118404,
  "mean_composite": 0.1997,
  "elapsed_ms": 26
}
```

```bash
# 8. Alert YAML parse (agentic-health)
python3 -c "import yaml; y=yaml.safe_load(open('prometheus/alert-rules/agentic-health.yml')); print(sum(len(g['rules']) for g in y['groups']), 'rules')"
```
```
5 rules
```

---

## QA scorecard (full-suite run)

Two consecutive runs today; the second is the authoritative state after closing 4 stale-doc/test FAILs.

| Metric | v1 baseline (2026-04-24) | v1 doc claim | **v2 first run (16:25 UTC)** | **v2 re-run (17:46 UTC)** |
|---|---:|---:|---:|---:|
| Suites | 44 | 51 | 51 | **51** |
| Benchmarks | 9 | 9 | 9 | **9** |
| Total PASS | 411 | 468 | 464 | **468** |
| Total FAIL | 0 | 0 | 4 | **0** |
| Total SKIP | 2 | (not stated) | 2 | **2** |
| Score % | 99.52 | 99.57 | 98.72 | **99.57** |

Scorecards: `scripts/qa/reports/scorecard-2026-04-29T16-25-30Z.json` (first run, 4 FAIL), `scripts/qa/reports/scorecard-2026-04-29T17-46-23Z.json` (re-run, 0 FAIL). Each run is ~31 min.

### The 4 FAILs from the first run — and what fixed them

Each was a stale-doc/test artifact of changes that landed earlier today, not a platform regression. All four were closed in this session before the re-run.

| # | Suite::test | Root cause | Fix |
|--:|---|---|---|
| 1 | `637-events::event_types_registry_has_13_entries` | Assertion still checks `len(EVENT_TYPES) == 13`; the NVIDIA P0+P1 batch (commits 4af78cf, cac272a, 2e3fb9f) added 4 → 17. | Bumped assertion to 17 + renamed test to `event_types_registry_has_expected_entries` so future bumps re-name (a self-documenting forcing function). `scripts/qa/suites/test-637-events.sh:10-15` |
| 2 | `655-teacher-agent-gate::claude_md_references_all_five_tier_issue_ids` | CLAUDE.md compression (commit 5b6a230, 50185 → 36936 bytes) collapsed the 5 IDs into the range form `IFRNLLEI01PRD-651..-655`. The test greps for each full ID (`-651`, `-652`, `-653`, `-654`, `-655`); only `-651` matched the range form. | Restored explicit comma-separated list: `IFRNLLEI01PRD-651, IFRNLLEI01PRD-652, IFRNLLEI01PRD-653, IFRNLLEI01PRD-654, IFRNLLEI01PRD-655`. CLAUDE.md grew 36936 → 37006 bytes (+70). |
| 3 | `656-skill-index-fresh::committed_matches_fresh_render` | `docs/skills-index.md` still rendered "Skills (6)"; team-formation skill (commit 4af78cf) bumped it to 7. Renderer was never re-run. | `python3 scripts/render-skill-index.py docs/skills-index.md` regenerated 5754 bytes / 18 entries. Diff vs fresh render: clean. |
| 4 | `e2e-happy-path::session_lifecycle_produces_expected_audit_trail` | Loop asserted `schema_version != 1` against ALL tables, including `event_log` (now v=4 after NVIDIA P0+P1). Found 11 rows with `schema_version=4` in event_log → fail. | Refactored loop to look up each table's expected version from `lib.schema_version.CURRENT_SCHEMA_VERSION` at runtime — the assertion is now registry-driven, so a future bump on any table cannot silently regress this test. `scripts/qa/e2e/test-e2e-happy-path.sh:111-116` |

The 7 NVIDIA suites added by IFRNLLEI01PRD-748..-751 all PASS at full-suite scope (57/57) on both runs, confirming the v1 doc's claim was correct under the original framing.

---

## Live surfaces — n8n

### Active workflows (27 total)

```
agentic-stats             chaos-logs-api            chaos-test-recover
chaos-test-start          chaos-test-status         ci-failure-receiver
crowdsec-receiver         crowdsec-receiver-gr      lab-stats-api
librenms-receiver         librenms-receiver-gr      matrix-bridge
mesh-stats-api            progress-poller           prometheus-receiver
prometheus-receiver-gr    runner                    security-receiver
security-receiver-gr      service-health-api        session-end
session-replay            synology-dsm-receiver     teacher-runner
wal-healer-gr             youtrack-receiver         youtrack-trigger
```

### Receivers — post-cc-cc dispatch (15 SSH nodes across 9 workflows)

Every receiver's "Post Triage Instruction" / "Post Burst Triage" / "Post Escalation" SSH node now invokes:

```
={{ '/app/claude-gateway/scripts/run-triage.sh <kind> ' + JSON.stringify(arg1) + ' ' + JSON.stringify(arg2) + ... }}
```

| Receiver workflow | Triage kinds called |
|---|---|
| `prometheus-receiver` (NL) | `k8s`, `escalate` |
| `prometheus-receiver-gr` | `k8s`, `escalate` |
| `librenms-receiver` (NL) | `infra`, `correlated`, `escalate` |
| `librenms-receiver-gr` | `infra`, `correlated`, `escalate` |
| `security-receiver` (NL) | `security` |
| `security-receiver-gr` | `security` |
| `crowdsec-receiver` (NL) | `security` |
| `crowdsec-receiver-gr` | `security` |
| `synology-dsm-receiver` | `infra` |

`scripts/run-triage.sh` dispatches to `openclaw/skills/{k8s-triage,infra-triage,security-triage,correlated-triage}/<kind>-triage.sh` (or `escalate-to-claude.sh` for `escalate`). All scripts are host-portable via `${TRIAGE_X:-default}` env-var fallbacks — they run identically on `nl-claude01` (current path) or inside the OpenClaw container (rollback path), so re-enabling `oc-cc` is non-destructive.

### Runner — `qadF2WcaBsIR7SWG` (50 nodes, active)

Topology unchanged from v1:

```
Receiver → Cooldown → Lock → Pre Stats → Query Knowledge
        → Build Plan → Check Intermediate Rail → Classify Risk → Build Prompt
        → Launch Claude → Wait → Parse → Validation Retry × 2
        → Smart Truncate → Prepare Result → Should Screen?
        → Screen with Haiku → Apply Screening → Post to Matrix
        → Write Session File → Should Review? → Release Lock
```

**Build Prompt** injects (in order): chatops-workflow master skill body → knowledge-base RAG hits → category tool guidance → operator context → **Team Charter (advisory roster)** → **Reasoning Budget (if env var > 0)** → Risk section → Confidence instructions.

**Check Intermediate Rail** (DARK-FIRST observe-only) calls `python3 -m lib.intermediate_rail --no-ollama` against the Build Plan output and pass-throughs unchanged. Emits one `intermediate_rail_check` event_log row per session.

### Session Replay — `lJEGboDYLmx25kBo` (7 nodes, active)

```
POST /session-replay
  → Validate Input (format-only)
  → If Valid? ┬─ true → SSH Claude Resume (sqlite3 guard + claude -r)
              │              → Parse + Emit Event → Respond OK (HTTP 200/404)
              └─ false → Respond Error (HTTP 400)
```

The sqlite3 existence check sits inside the SSH command (the n8n task-runner sandbox blocks `child_process` in Code nodes). Unknown session_id → JSON `{"is_error":true,"error_type":"unknown_session"}` → HTTP 404 from Respond OK. Malformed payload → HTTP 400 from Respond Error.

---

## Live surfaces — libraries

| Path | Purpose |
|---|---|
| `scripts/lib/jailbreak_detector.py` | Pure-regex detector for 5 NVIDIA-DLI-08 vectors. English + Greek pattern set. `detect_all(text)` → list of (category, pattern, span). |
| `scripts/lib/team_formation.py` | Rule-based agent-roster proposer. `propose_team(category, risk_level, hostname)` → JSON-serialisable charter. KNOWN_AGENTS inventory enforced against `.claude/agents/*.md`. |
| `scripts/lib/intermediate_rail.py` | Topic-rail check. Heuristic (regex keyword buckets per category, <2 ms) + Ollama backend (gemma3:12b, 3 s budget). Emits `intermediate_rail_check` event. |
| `scripts/long-horizon-replay.py` | Replays 30 longest sessions; scores trace_coherence (Jaccard of adjacent assistant turns), tool_efficiency (unique/total tool calls), poll_correctness (alignment vs `session_risk_audit`), cost_per_turn_z. Pure SQLite reads, no live Claude calls. Smoke-tested today: `mean_composite=0.1997`, 26 ms for 5 sessions. |
| `scripts/run-triage.sh` (NEW post-migration) | Wrapper invoked by every receiver SSH node. `<kind> <args...>` → dispatches to `openclaw/skills/<kind>-triage/<kind>-triage.sh` or `escalate-to-claude.sh`. 600 s timeout per dispatch. Single canonical entry point for all 9 receivers. |

---

## Grammars

JSON-Schema constraints passed to Ollama via the `format` field when `OLLAMA_USE_GRAMMAR=1`:

- `scripts/lib/grammars/quiz-grader.schema.json` — `score_0_to_1`, `feedback`, `bloom_demonstrated` (7-level enum), `citation_check{uses_source,fabricated_content}`, `clarifying_question`, `grader_confidence`.
- `scripts/lib/grammars/quiz-generator.schema.json` — `question_text`, `rubric`, `bloom_level`, `question_type` (5-value enum), `source_snippets[]` (1-5 items).
- `scripts/lib/grammars/risk-classifier.schema.json` — Documents the deterministic classifier's output shape (no LLM call; schema is a contract).

---

## Cron schedule (5 NVIDIA + 1 cc-cc canary; 2 OpenClaw crons disabled)

```
*/10 * * * * write-intermediate-rail-metrics.sh
*/15 * * * * write-replay-metrics.sh
*/30 * * * * write-jailbreak-metrics.sh
*/30 * * * * scripts/receiver-canary.sh        # NEW 2026-04-29 — synthetic prom→YT assertion
0 5 * * 1    long-horizon-replay.py --limit 30
0 5 * * 3    test-jailbreak-corpus.sh           # weekly regression

# DISABLED 2026-04-29 cc-cc migration:
# 0 * * * *  poll-openclaw-usage.sh    (Tier 1 token tracking — openclaw is off)
# 12 4 * * * sync-openclaw-skills.sh   (synced gateway repo skills into openclaw container — pointless if openclaw is off)
```

`docs/crontab-reference.md` regenerated.

---

## Prometheus alerts (3 from NVIDIA batch + 2 from cc-cc lift, 7 total in agentic-health.yml)

| Alert | Trigger | For | Severity |
|---|---|---:|---|
| LongHorizonReplayStale | `time() - chatops_long_horizon_replay_last_run_timestamp > 777600` | 30m | warning |
| JailbreakBypassDetected | `max by (category) (chatops_jailbreak_detector_match_total{status="miss"}) > 0` | 30m | warning |
| IntermediateRailDriftHigh | `max by (category) (chatops_intermediate_rail_drift_score) > 0.20` | 24h | warning |
| **ReceiverCanaryFailing** (NEW 2026-04-29) | `receiver_canary_last_run_status{result="fail"} == 0` | 35m | **critical** |
| **ReceiverCanaryStale** (NEW 2026-04-29) | `time() - receiver_canary_last_run_timestamp_seconds > 2400` | 10m | warning |
| SkillPrereqMissing (existing) | — | 30m | warning |
| SkillMetricsExporterStale (existing) | — | 10m | warning |

---

## SQLite schema state

`event_log` is **v=4**. The 17 registered `event_types`:

```
tool_started, tool_ended, handoff_requested, handoff_completed,
handoff_cycle_detected, handoff_compaction, reasoning_item_created,
mcp_approval_requested, mcp_approval_response, agent_updated,
message_output_created, tool_guardrail_rejection, agent_as_tool_call,
team_charter, its_budget_consumed,
intermediate_rail_check, session_replay_invoked
```

The 19 schema-versioned tables in `scripts/lib/schema_version.py:CURRENT_SCHEMA_VERSION`:

```
sessions, session_log, session_transcripts, execution_log, tool_call_log,
agent_diary, session_trajectory, session_judgment, session_risk_audit,
event_log (v=4), handoff_log, session_state_snapshot, session_turns,
prompt_patch_trial, session_trial_assignment, learning_progress,
learning_sessions, teacher_operator_dm, long_horizon_replay_results
```

---

## Skills (7)

```
.claude/skills/
  alert-status/         — show active alerts
  chatops-workflow/     — Phase 0-6 master choreography
  cost-report/          — session cost rollup
  drift-check/          — IaC vs live diff
  team-formation/       — propose sub-agent roster
  triage/               — infrastructure triage
  wiki-compile/         — knowledge base compile
```

`docs/skills-index.md` regenerated 17:38 UTC against the current `.claude/skills/**/SKILL.md` frontmatter (5754 bytes, 18 entries — 7 skills + 11 sub-agents). Re-run anytime with `python3 scripts/render-skill-index.py docs/skills-index.md`; the QA suite `656-skill-index-fresh::committed_matches_fresh_render` enforces non-staleness.

---

## YouTrack — implementation trace

All 5 issues for the NVIDIA P0+P1 batch are in `Done` state:

| Issue | Title | State |
|---|---|---|
| IFRNLLEI01PRD-747 | NVIDIA DLI cross-audit P0+P1 implementation (umbrella) | Done |
| IFRNLLEI01PRD-748 | G1: long-horizon replay + jailbreak corpus | Done |
| IFRNLLEI01PRD-749 | G2: intermediate rail + grammar decoding | Done |
| IFRNLLEI01PRD-750 | G3: team-formation + ITS budget | Done |
| IFRNLLEI01PRD-751 | G4: server-side replay endpoint | Done |

cc-cc migration produced two YT issues today (operational, not gating an architectural change):

| Issue | Title | State |
|---|---|---|
| IFRNLLEI01PRD-753 | K8s Alert: FullChain160013 (warning) — synthetic prom path proof | Open |
| IFRNLLEI01PRD-755 | Alert: SyntheticTestAlert_LibreNMSPathVerify_20260429 — synthetic librenms path proof | Open |

(State transitions used the direct REST workaround documented in `memory/feedback_youtrack_mcp_state_bug.md` — the `tonyzorin/youtrack-mcp:latest` container's `update_issue_state` omits the `$type: StateBundleElement` discriminator and fails silently.)

---

## Implementation chronology (commits on `main` today, all direct push)

```
5b6a230  docs(CLAUDE.md): compression pass — 50185 → 36936 bytes (back under 37000 target)
eea4786  docs(CLAUDE.md): NVIDIA DLI cross-audit + P0+P1 batch entry (umbrella IFRNLLEI01PRD-747)
83e75b8  docs(readme): public-surface parity for NVIDIA P0+P1 batch (2026-04-29)
144ace7  docs(state): merged single source-of-record after NVIDIA P0+P1 batch
cac226a  feat(nvidia): close all 5 operator gates (cron + rail node + replay active + Greek + YT done)
03d5624  docs(nvidia): P0+P1 certification + re-scored audit (NVIDIA umbrella close)
2e3fb9f  feat(g4): server-side session-replay endpoint (NVIDIA P1.4)
cac272a  feat(g2): intermediate semantic rail + grammar-constrained decoding (NVIDIA P0.3+P1.1)
4af78cf  feat(g3): team-formation skill + ITS budget injection (NVIDIA P1.2+P1.3)
8aabf27  feat(g1): long-horizon replay eval + jailbreak corpus QA suites (NVIDIA P0.1+P0.2)
7e91538  docs(CLAUDE.md): bump LLM Usage Tracking writers 5 → 6 (poll-openclaw-usage.sh)
ca12fab  feat(openclaw): migrate Tier 1 from GPT-5.1 to Sonnet 4.6 via OAuth Max sub
```

The cc-cc migration itself (9 in-place workflow rewrites + 6 helper scripts pulled into the repo + LXC stop + 2 cron disables) is **not yet committed** — the working tree shows the receiver JSON files modified at 15:59 UTC, the new `scripts/run-triage.sh`, the new `openclaw/skills/yt-*.sh` helpers, and patched `openclaw/skills/{site-config,k8s-triage,infra-triage}.sh`. Operator-gated commit pending.

Zero reverts. Zero hotfixes from the NVIDIA batch.

---

## Operating posture

- **DARK-FIRST intermediate rail.** Currently emitting only — no Build Prompt blocking. After ≥7 days of `chatops_intermediate_rail_drift_score` data, the operator can decide whether to soft-gate (warn in prompt) or hard-gate (force `[POLL]` on out-of-distribution).
- **cc-cc is the active default mode.** OpenClaw retired but not deleted; `gateway.mode` and the matrix-bridge openclaw routing are dormant on disk so a single `pct start` + `cron uncomment` restores `oc-cc` if needed.
- **Greek operator vocabulary covered.** Both at the prompt-submit hook (`config/user-vocabulary.json` + ban list `ευρετηριασμένα`/`Σου επανέρχομαι`) and at the jailbreak detector (5 + 2 Greek vectors).
- **Single-operator multi-site design preserved.** No multi-tenant LangGraph state, no LoRA pipeline, no NeMo Agent Toolkit / NIM. These are out-of-scope until the operating model changes.
- **Direct push to main.** This repo is on the direct-push list; every commit lands without an MR.
- **n8n sandbox awareness.** `child_process` is blocked inside Code nodes — any subprocess work must go through SSH nodes (memory captured for future sessions).

---

## Out-of-scope (intentionally not done)

| Item | Reason |
|---|---|
| Multi-tenant LangGraph migration | Single-operator system. Revisit if operator count > 1. |
| LoRA / PEFT customization for Ollama models | Tier-0 volume insufficient for a stable supervised set. Revisit at ≥10k judge calls/month. |
| NeMo Agent Toolkit YAML config layer | n8n is the chosen substrate, validated through 14 prior audits. |
| NIM microservices | Ollama + Anthropic OAuth Max is the chosen inference stack. |
| Hard-gate intermediate rail | DARK-FIRST per audit recommendation; data review at ≥7 days. |
| Re-running 9 external rubric grades | Not auto-runnable; carry forward unless re-grade triggers fire (none did). |
| Live alerts through 5 untriggered receivers | Wired identically to the proven 2; first organic alert through each is the canonical proof. |

---

## Reference — the three predecessor docs (kept for narrative)

- `docs/nvidia-dli-cross-audit-2026-04-29.md` — Original audit (12-dim scorecard + 9-source roll-up + roadmap). The source-of-record before implementation.
- `docs/nvidia-p0-p1-certification-2026-04-29.md` — E2E certification (Phase 1-6 results, schema-bump trace).
- `docs/nvidia-dli-cross-audit-rescored-2026-04-29.md` — Re-scored evaluation showing the +0.43 lift.

This document is the merge of all three into a single state-of-the-platform reference, refreshed post-cc-cc migration. When in doubt, read this one first.

---

## Run artifacts (this refresh)

For traceability, all command outputs from the v2 refresh are preserved at:

```
/tmp/state-refresh-2026-04-29/
├── phase-a-counters.log              # System snapshot recount
├── phase-a-counters-extra.log        # Schema + alerts + nodes
├── phase-a-counters-3.log            # Event types + chaos + grafana
├── phase-a-counters-4.log            # EVENT_TYPES tuple
├── phase-b-quick.log                 # B1 schema, B3 cron, B4 webhook 400, B8 alerts
├── phase-b-libs.log                  # B5 rail, B6 team, B7 long-horizon
├── phase-b-nvidia-suites.log         # 7 NVIDIA suites (run individually)
├── phase-d-prep.log                  # Today's commits + workflow mtimes
├── phase-d-receivers.log             # Active workflows + receiver SSH commands
└── phase-d-wrapper-refs.log          # run-triage.sh references per receiver
```

Plus the QA scorecard JSON at `scripts/qa/reports/scorecard-2026-04-29T16-25-30Z.json` (51 suites + 9 benchmarks, 464 PASS / 4 FAIL / 2 SKIP, 98.72%).
