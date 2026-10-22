# RAG Pipeline

> 3-channel hybrid retrieval. Compiled 2026-07-03 04:30 UTC.

## Channels

1. **Hybrid Semantic Search (RRF)** — nomic-embed-text 768 dims + keyword LIKE, blended via Reciprocal Rank Fusion
2. **Deterministic Hostname Routing** — claude-knowledge-lookup.sh pattern-matches hostname to CLAUDE.md files
3. **XML-Tagged Injection** — `<incident_knowledge>`, `<lessons_learned>`, `<operational_memory>` tags

### CLI-session RAG capture pipeline

IFRNLLEI01PRD-646/-647/-648 ship a 3-tier pipeline that routes interactive
Claude Code CLI sessions (no YT webhook, no Runner workflow) into the same
RAG tables that agentic Session End populates.

**Tier 1 (-646):** `scripts/backfill-cli-transcripts.sh` — cron-safe wrapper
around `archive-session-transcript.py`. Raised defaults: `--limit 50`,
`--embed`, byte-offset watermark at
`~/gitlab/products/cubeos/claude-context/.cli-transcript-watermark.json`,
`--oldest-first` drains the ~2,300-file backlog oldest-first so everything
eventually lands. Each JSONL becomes `issue_id='cli-<uuid>'` in
`session_transcripts`; sessions with >5000 assistant chars also get a
doc-chain refined summary row at `chunk_index=-1`.

**Tier 2 (-647):** `scripts/extract-cli-knowledge.py` — reads the
`chunk_index=-1` summaries, POSTs each to gemma3:12b (Ollama) with
`format=json` asking for `{root_cause, resolution, subsystem, tags,
confidence}`, inserts into `incident_knowledge` with `project='chatops-cli'`
and a nomic-embed-text embedding. Idempotent via a LEFT-JOIN / NOT-EXISTS
query. Breaker-aware via `rag_synth_ollama`. Zero external cost.

**Tier 3 (-648):** `scripts/parse-tool-calls.py` — `extract_issue_id_from_path()`
gained a CLI fallback: files under `~/.claude/projects/` now resolve to
`issue_id='cli-<uuid>'` so `tool_call_log` rows join back to
`session_transcripts` cleanly. The backfill chains `parse-tool-calls.py`
after archive for each file.

**Retrieval weighting:** `kb-semantic-search.py` has new constant
`CLI_INCIDENT_WEIGHT` (default `0.75`, env override). The main RRF semantic
ranker multiplies sim by this value for rows where `project='chatops-cli'`,
so real infra incidents still win tie-breakers against CLI-extracted
knowledge.

**Cron INSTALLED** (verified 2026-04-24 on `nl-claude01`):
```
30 4 * * * /app/claude-gateway/scripts/backfill-cli-transcripts.sh --embed --oldest-first --limit 50 >> /home/app-user/logs/claude-gateway/cli-transcript-backfill.log 2>&1
```
Firing nightly. 2026-04-24 04:30 UTC run processed 50 files → 255 transcript chunks + 2831 tool-call rows + 25 incident_knowledge extractions (25 inserted, 1 skipped, 1 failed, elapsed 258s).

**QA:** `scripts/qa/suites/test-646-cli-session-rag-capture.sh` — 12/12
PASS in isolation. Covers backfill flags, watermark roundtrip, parse-tool
CLI path inference, extractor tag sanitizer, fetch_pending idempotency, and
CLI_INCIDENT_WEIGHT guards.

**Soak-test run (2026-04-20):** 10 files processed, 12 transcript chunks
+ 245 tool-call rows + 4 summaries + 4 incident_knowledge rows extracted.
Gemma correctly classified the extractions: one summary of *this* session
came back as `subsystem=sqlite-schema` with
`tags=[schema,migration,versioning,data,script,reasoning]` and confidence
0.95.

**Runbook:** [`docs/runbooks/cli-session-rag-capture.md`](../../../../gitlab/n8n/claude-gateway/docs/runbooks/cli-session-rag-capture.md).

### DLI RAG Course Slides

NVIDIA DLI course deck "Building RAG Agents with LLMs" (188 slides, 46 MB) lives at `docs/DLI-RAG-Slides.pptx` (moved from `/tmp/` on 2026-04-17).

Course structure — useful when reasoning about this project's own RAG pipeline:

- Part 1: Environment (Docker microservices, Gradio frontend)
- Part 2: LLM Services (NGC / OpenAI gateway, `ChatNVIDIA` vs `ChatOpenAI`, `integrate.api.nvidia.com`, `api.nvcf.nvidia.com/v2/nvcf`)
- Part 3: LangChain LCEL (`prompt | llm | StrOutputParser()`, `.invoke` vs `.stream`)
- Part 4: Running State Chain (`RunnableAssign` / `RunnableBranch` / `RunnableLambda`, airline chatbot pattern, four paradigms: Unstructured Generation / Structured Retrieval / Guided Generation / Tool Choice)
- Part 5: Documents (chunking, stuffing, map-reduce, refinement, knowledge graph construction + traversal, LangGraph tangent)
- Part 6: Embeddings (asymmetric query/doc model `nvolve-29k`, bi-encoder vs cross-encoder, symmetric vs asymmetric)
- Part 6.4: Semantic guardrails (classifier + branch in embedding space)
- Part 7: Vector DBs (FAISS -> Milvus standalone -> Milvus K8s cluster, Reranker, LongContextReorder, Query Augmentation, **RAG Fusion**, Tool-Selection Agent)
- Part 8: Evaluation (synthetic Q/A generation, pairwise LLM-as-a-judge, **RAGAS** `RagasEvaluatorChain` -- faithfulness metric, already in use in this project)

Overlap with this project:
- Our **5-signal RRF RAG** covers Part 7's "RAG Fusion" with added wiki + transcript + chaos signals.
- Our **RAGAS evaluation** (faithfulness 0.88, precision 0.86, recall 0.88) is the same framework linked in slide 182-184.
- Our **semantic guardrails** via `unified-guard.sh` mirror Part 6.4's classifier/branch pattern.
- Our **HyDE fallback** in `kb-semantic-search.py` is the "Rephrase as Hypothesis" pattern from slide 165.

Consult this deck when extending the RAG stack or explaining RAG concepts to stakeholders.

### feedback-html-scraper-first-match-fragile

When scraping HTML in an n8n Code node, never trust "first `<img>`" / "first `<a>`" / "first `<meta>`" — source pages get search widgets, header banners, ad slots, JS-template literals (`src="'+e.thumb+'"`), schema.org JSON-LD blocks, etc, added upstream over time, and your regex will silently start matching them instead of the article body.

**Why:** the failure mode is silent. The regex matches *something* and returns a value (often empty string between mismatched quote types). The downstream filter (`item.json.imageUrl !== null`) treats empty/garbage as a present-but-falsy value, zeroes the item array, all downstream nodes no-op, n8n reports `status: success`. No alert ever fires. The only way to notice is operator-side ("why hasn't this posted in 9 days?").

**How to apply:** every HTML-scrape regex in this estate's n8n workflows MUST:

1. Whitelist the expected value shape in the capture group itself:
   - For images on withelli.com: `src=["'](\/images\/posts\/[^"']+|https:\/\/withelli\.com\/[^"']+)["']`
   - For canonical article URLs: `href=["'](https:\/\/<host>\/posts\/[^"']+)["']`
2. Prefer parsing `<meta property="og:image" …>` / `<meta property="og:url" …>` from `<head>` over scraping body — Hugo, Jekyll, Next.js, Astro all emit these and they're version-stable.
3. If you DO use a generic-first-match regex, pair it with a sanity check at the end: `if (!url || !url.startsWith('http')) throw new Error('image extraction returned suspicious URL: ' + url)` — converts silent halt into a loud error that surfaces in n8n's execution list.

**Canonical incident:** [[autoposter-silent-halt-search-widget-20260527]] — RSS2Postiz workflow silently stopped publishing for 9 days after withelli.com added a search widget whose JS-template `<img src="'+e.thumb+'">` was emitted before the article image. Same regex would have caught the issue at fix-time if it had whitelisted `/images/posts/…` in the capture group.

### feedback-no-fragment-prefer-bundled-mrs

The operator explicitly prefers **bigger MRs that deploy + test, not many small MRs**. This was previously documented but I violated it heavily in the 2026-05-26 OMOIKANE-724 session: shipped 17 small MRs across 12 epic phases when ~5-6 bundled MRs would have served.

**Why:** Each fragmentation costs:
- A separate CI cycle (~2-3 min) + queue position + reviewer context-switch
- A rebase-risk increment — every concurrent MR that touches `mod.rs` or any shared file forces a manual rebase (bit me 4× in one session)
- A longer end-to-end "what landed tonight?" reconstruction
- More YT-comment-update load on the operator

The "substrate-first scaffolding" pattern (separate MR for types vs cron vs view-layer) is **only justified for the first 2-3 splits in a multi-phase epic** where natural seams genuinely exist (substrate ≠ migration ≠ admin UI ≠ public surface, ~800-1600 LOC chunks). Beyond that, splitting into 100-300 LOC chunks adds cost without adding clarity.

**How to apply:**

- Default to **one MR per YT child** when child scope is ≤1500 LOC. Split only if the child genuinely needs intermediate substrate that downstream MRs build on (and even then prefer 2 MRs over 4).
- **Bundle MRs across YT children freely** when the work is the same call-chain (e.g. "cron + Prom + admin panel" for one feature lives in one MR even if it ref's 3 YT children).
- When tempted to split for "easier review", consider whether the diff would be readable as one MR with section-headed file-by-file commentary in the description. Usually yes.
- A consolidated MR that closes 2-3 YT children at once is the gold-standard shape; ccs-01 also independently arrived at this pattern same-night ("over-fragmented tonight... should've been 1").

## Caught in

2026-05-26 OMOIKANE-724 marathon session: 17 sub-phase MRs (9a / 10a / 11a / 11b / 12a / 12b1 / 12b2 + their predecessors) where ~5-6 bundles would have done. Recovery: consolidated 12b3 + 10b + 11c-partial + 9b-prep into MR !2515 closing OMOIKANE-734 + OMOIKANE-736 at once. ccs-01 acknowledged same issue ~10:33 UTC: "operator-correct ack: over-fragmented tonight. JSON-LD enrichment was 3 MRs (!2492+!2498+!2499) when it should've been 1".

### PVE-clone leaves snmpd.conf sysName pinned to the source host

When a Proxmox node is built by cloning an existing cluster member (vzdump restore, disk image clone, etc.), the **corosync identity wipe** is well-known and covered in `feedback_corosync_cmap_version_mismatch_signature.md`. But `/etc/snmp/snmpd.conf` is **not** in that wipe list — it keeps the source host's hardcoded `sysName <source>` line.

**Why:** the snmpd config is hand-managed (not generated from hostname). The clone-and-rename runbook needs an explicit `sed -i 's/^sysName <source>$/sysName <new>/'  /etc/snmp/snmpd.conf` step. Symptom is the LibreNMS API rejecting the device add with: `Already have device <new> due to duplicate sysName: <source>`.

**How to apply:** Before adding a cloned PVE node to LibreNMS, run on the target:
1. `grep '^sysName' /etc/snmp/snmpd.conf` — confirm it shows the OLD hostname
2. `sed -i 's/^sysName <source>$/sysName <new>$/' /etc/snmp/snmpd.conf && systemctl restart snmpd`
3. Retry the `POST /api/v0/devices` call.

Caught 2026-05-10 onboarding nlpve04 (cloned from nl-pve02) to nl-nms01.

### infragraph-cascade-gating-1118-20260617

2026-06-17. Implemented + LIVE: IFRNLLEI01PRD-1118 cascade-probability gating (claude-gateway MR !32, commit `6beb680`). Epic -1029; addresses the -1065 root cause. Builds on the diagnosis that the InfragraphPrecisionDrop is genuine **over-prediction**, NOT the declared-edges seed bug (see [[k8s-residual-triage-20260617]]).

## What it does
`lib.infragraph.apply_cascade_gating()` gates `expected_cascade` + the shuffled control (symmetric) against learned per-(parent rule-family → child) hit-rates in `infragraph_cascade_stats` (migration 017; learned by `infragraph-learn.py --from-cascades`, hourly :25 cron):
- **Emit-gate** by FAMILY probability ≥ `INFRAGRAPH_CASCADE_MIN_PROB` (default 0.10).
- **Per-item confidence** = EXACT-rule probability, Laplace(1,4) — the signal `precision_conf08` / the -1040 gate consume.
- `MODEL_VERSION=2`. Kill-switch `INFRAGRAPH_CASCADE_GATING=0` = byte-identical legacy. Inert until learn populates stats. **Ruleless callers** (triage cascade-context, propose-blast-radius) are NOT gated (family stat would key on "other"=cold-start) — only the rule-bearing recorded path (what the metric scores) is gated. Action lane (predict_action/cmd_predict) deliberately NOT gated — shadow-only.

## Key findings (reusable for -1119 + future tuning)
1. **Metric direction is diagnostic:** low PRECISION = over-prediction (predict cascades that don't fire); low RECALL = under-prediction (missing edges). -1065 was failing precision, so the seed/missing-edges theory was backwards.
2. **τ=0.10 is the recall-neutral breakpoint:** dropping families with hit-rate < 0.10 removes only never-firers (fired=0) → pure precision gain, ZERO recall cost (0.054→0.097). Higher τ trades recall (0.15→0.144, 0.20→0.153).
3. **precision_conf08 is honestly empty and that's CORRECT:** the best exact-rule hit-rate in the 8-day window is 0.36 (TargetDown 5/14) — no rule reliably cascades yet, so nothing reaches conf≥0.8 and the -1040 gate stays NO-GO. Do NOT lower the Laplace prior to force-populate it (that manufactures false confidence). It populates with data + -1119.
4. **The remaining cap is granularity (-1119 — NOW ALSO SHIPPED, `c4636d4`, same MR !32):** the predictor names the wrong specific rule on the right cascade host (predicts RAGLatency/NodeSaturation; actuals are KubePodNotReady/PodCrashLoopBackOff). -1119 adds rule-family scoring (`lib.score_prediction(family=)` + `rule_family()` {host-down,k8s-pod,rag,resource,backup}) reported in the scorecard/health/Prometheus (`infragraph_precision_family_30d`) + a nested `gate_b_to_c.family` verdict (conf08 gates on `cascade_prob_family`). **Exact `all_met` / -1040 criterion UNCHANGED — operator adopts family at the gate review.** Measured: recall 0.279→0.365; composed with -1118, family precision 0.054→**0.171** (recall-neutral). family conf08 still empty (best family hit-rate 0.474 < 0.8). -1118 removes over-prediction; -1119 fixes the unit. They compose. test-1119 6/6.

## Gotchas
- `infragraph-query.py cmd_cascade` gates the control explicitly (not inside `shuffled_control`) so the action lane's control stays ungated.
- `_cascade_stats` caches on the connection (`conn._igcs_cache`); `learn_cascade_stats` delattr's it after writing.
- QA: `test-1118` (7 cases) + `test-1031` (count 016 tables by name, not LIKE) + `test-1033` (model_version 1→2). schema.sql carries the table for fresh-DB fixtures.

### infragraph-epic-state-20260609

**FINAL STATE (end of 2026-06-09 build-out): SYSTEM LIVE AND ACTIVE.** 13/16 epic children done in one day (MRs !20–!29 + IaC !327, all merged+deployed). The **canonical operator-facing record is in the REPO**: `memory/infragraph_epic_buildout_20260609.md` (indexed in repo MEMORY.md; CLAUDE.md runbook entry + incident record updated on main AND applied to the live-tree branch copy — careful: the live tree runs the operator's branch whose CLAUDE.md is RICHER than main's; never blanket-checkout main's CLAUDE.md over it, apply edits to the branch version). Remaining, gated by data/operator: -1040 review when scorecard `gate_b_to_c.all_met` flips, -1041 autonomy widening + Bridge auto-resolve-on-match (behind -1040), -1043 closeout verdict vs frozen 0.4156 baseline. Watch next session: `~/logs/claude-gateway/infragraph-*.log`, first organic proposals from the :45 scan, first action-prediction verdicts on real remediations.

**Infragraph** (operator-requested "world model" for the agentic system, 2026-06-09): causal infra dependency graph + learned dynamics, integrated into triage. Epic **IFRNLLEI01PRD-1029**, children **-1030..-1045** (16, sequenced M1→M5; -1040 is the human B→C gate). Plan of record: `docs/plans/infragraph-implementation-plan.md`.

**Shipped 2026-06-09 (M1, MR !20, pipeline 36440 green, 21/21 QA):** schema.sql **G15** (NOT G11 — G11-G14 taken) + migration `016_infragraph.sql` (`infragraph_dynamics` sidecar + `infragraph_predictions` shadow log w/ shuffled-control columns), `scripts/lib/infragraph.py`, `scripts/infragraph-query.py` (frozen model_version-1 contract: blast-radius/deps/cascade/explain/health; exit 0/1/2; 2s timeout; `INFRAGRAPH_DISABLED` kill-switch; fail OPEN), QA suites `test-1031-*` + `test-1033-*`, `docs/host-blast-radius.md` populated (was 0 bytes) as declared-edges source of truth.

**Operator decisions (confirmed 2026-06-09):** Phase C = operator approval PER generated blast-radius rule (no auto-activate); n8n Build Prompt Tier-2 injection IS in scope (issue -1038, last Phase A item).

**NON-NEGOTIABLE ARCHITECTURAL INVARIANT (operator, 2026-06-09 — issues -1044/-1045):** genuine model-free → model-based shift enforced in CONTROL FLOW, not data. (1) Prediction computed OUTSIDE the LLM — n8n Runner calls deterministic `predict_action()`; LLM only consumes. (2) NO approval poll (human or auto) without committed `infragraph_predictions` kind='action' row, plan_hash-matched to the plan; missing ⇒ analysis-only session. (3) Verification mechanical — `infragraph-verify.py` writes verdict (match|partial|deviation); LLM never adjudicates its own outcome. **Acceptance test: an approved remediation without a machine prediction must be structurally impossible.** Fail-semantics split: triage enrichment fails open; remediation lane fails CLOSED (`INFRAGRAPH_DISABLED` = analysis-only). Schema plumbing shipped in MR !20 commit `9beca60` (kind/action_kind/action_target/plan_hash/verdict columns; lib refuses action-predictions without plan_hash); 24/24 QA.

**Key design facts:** edge direction = SOURCE depends on TARGET; topology rides existing G10 `graph_entities`/`graph_relationships` with `source_table='infragraph'`; dynamics in sidecar keyed by rel_id; suppression authority only via existing Phase 1b openclaw_memory rows (format at `tier1_suppression.py:173-196`); B→C eval gate: precision ≥0.95 on conf≥0.8 subset, shuffled-control ≤0.5× real, ≥30 preds/14d; eval target = 2026-05-11 cascade replay (≥35/43).

**Next:** -1032 seeders (netbox/iac/tunnels/declared + cron 04:10), -1034 learners, -1035 backtest replay (concept go/no-go BEFORE hot-path wiring), then -1036 Phase A. **-1044/-1045 (invariant gate + verify) sequence AFTER -1032/-1034** — a mandatory gate on an empty graph demotes every remediation to analysis-only. Risk #1 still open on -1031: verify tier1-suppressed alerts land in triage.log (must run on live nl-claude01 DB). Dev worktree was `/home/app-user/worktrees/infragraph-m1` (delete after merge).

**M2 SHIPPED same day (MR !21 merged `cc90332`):** graph LIVE on gateway.db (migration 016 applied) — 356 nodes/414 edges from 5 seeders (`--pve` live cluster API replaced planned `--iac` [no target_node in IaC, no placement in NetBox VMs]; `--librenms` dependency parents added after replay round 1; netbox `--cables`; tunnels via ast.literal_eval; declared). Learners: 149 chaos exps → 220 obs on 18 tunnel edges; miner 3441 entries → 36 edges (conf ≤0.75 by design). **Backtest -1035 verdict GO: 05-11 replay 34.5% coverage / 38.2% escalated / control_ratio 0.367 ✓ (≤0.5 criterion); iteration trail 0.65→0.61→0.52→0.37 via librenms+cables+SIBLING EXPANSION** (common-cause: hosts sharing pve/network parent at-risk at 0.6× conf when sibling alerts — caught the 05-08 15:16 4-VM burst). Crons on nl-claude01: `10 4 * * *` seed --all, `25 * * * *` learn. Files deployed to live tree via `git checkout origin/main --`. QA 35/35. Risk #1 RESOLVED: tier1-suppressed alerts DO land in triage.log. Remaining 05-11 misses = GR monitoring-path topology in no machine-readable source (operator options on -1035: LibreNMS parents / NetBox cables / declared rows). Replay artifacts: `test-results/infragraph-replay-2026-05-{08,11}.json` (gitignored, on-disk).

**PHASE A SHIPPED + DEPLOYED same day (MR !22 merged `c68ce3e` + IaC `production!327` Atlantis-applied + merged):** triage Step 2-graph live in infra-triage.sh (after NetBox step, 5s timeouts, fail-open, INFRAGRAPH_DISABLED guard; live sample nl-pve01 → "58 downstream, expected cascade: n8n01:Device Down conf 0.85…"); classify-session-risk.py `infragraph:blast-radius-high(N)` upward-only signal (live e2e: nl-pve03 read-only plan low→mixed at N=122); exporter `write-infragraph-metrics.py` cron */5 emitting; 3 alerts (MetricsExporterStale/SeedStale/PrecisionDrop) verified in-cluster via kubectl on PrometheusRule agentic-health-alert-rules; holistic §39 (5 checks); runbook RB-IG-001 `docs/runbooks/infragraph.md`; QA 44/44. **Gate A→B clock started 2026-06-09 ~21:00 UTC** (7d green, coverage >0.15 — at 0.14 now, §39 passing, p95<2s). Open Phase A item: -1038 n8n Build Prompt injection (validator-gated). Three crons on nl-claude01: seed 04:10, learn :25 hourly, metrics */5.

**-1038 SHIPPED — PHASE A COMPLETE (2026-06-09 ~21:10 UTC, MRs !23+!24 merged):** classifier emits `result.infragraph` context object ({host, blast_radius_total, by_type, top_affected, cascade[≤8], window_seconds}; key ABSENT on any failure); Runner Build Prompt (workflow `qadF2WcaBsIR7SWG`) renders "## INFRAGRAPH DEPENDENCY CONTEXT" before riskSection — **full Code-node safety runbook followed** (snapshot at /tmp/runner.rollback.json on nl-claude01 → node --check → validator PASSED → PUT → re-fetch/re-validate → toggle → test-fire; rollback = PUT the snapshot). n8n API key location: `jq -r '.mcpServers["n8n-mcp"].env.N8N_API_KEY' ~/.claude.json` (NOT in .env). PUT payload must be only {name,nodes,connections,settings}. Workflow exports are pretty-printed (indent=2). Epic state: -1030..-1038 done; Gate A→B window 06-09→~06-16 (coverage 0.14→needs >0.15); next -1039 Phase B (`cascade --record` + eval cron + scorecard), then -1040 human gate; -1044/-1045 invariant after Phase A mileage.

**-1044 MANDATORY PREDICT GATE LIVE (2026-06-09 ~21:45 UTC, built EARLY per operator, MR !25 `fd04815`):** Runner chain now Classify Risk → **Commit Prediction** (SSH, runs `infragraph-predict-plan.py`: plan_hash byte-parity with classifier, action derivation via classifier's MUTATION_PATTERNS import, commits kind='action' artifact pre-session) → Build Prompt; Prepare Result gate **default-DENIES** unpredicted [POLL]s → `[POLL-WITHHELD:NO-PREDICTION]` + analysis-only banner (Bridge can't parse it); eligible polls carry prediction summary+id into Matrix approval context. INFRAGRAPH_DISABLED = remediation lane fail-CLOSED (analysis-only). lib `predict_action()` + CLI `predict` subcommand (exit 2 without plan-hash). Enforcement ×3: control flow + test-1044 bypass QA (extracts gate from workflow export via **rindex** — first marker occurrence is inside the gate's own removal comment!) + audit-risk-decisions.sh invariant section (runs even on empty windows, exit 2 if export loses gate). QA 52/52. First prod artifact: prediction_id=1 (reboot nl-gpu01 plan). Rollback: PUT `/tmp/runner2.rollback.json`. **Open: -1045** (verdict writing match/partial/deviation by infragraph-verify.py + Bridge auto-resolve gating on verdict; eval --pending already scores mechanically).

**-1045/-1039/-1042 SHIPPED (2026-06-09 ~22:15 UTC, MR !26 `912db1a`) — EPIC 13/16 DONE:** `lib.action_verdict()` = ONLY verdict author (QA writer-scan enforces; match=all-observed-predicted incl. quiet case / partial=predicted-host-wrong-rule / deviation=unpredicted-host=never-auto-resolve); hourly eval cron (:40) writes verdicts + posts YT diff comments; `infragraph-verify.py --prediction-id` exit codes ENCODE verdict (0/1/2/3-window-open/4); **Phase B shadow recording LIVE in triage** (`cascade --record --issue` — started early per operator, append-only/zero-authority); weekly scorecard cron (Mon 05:10) → `test-results/infragraph-scorecard.json` with full gate_b_to_c criteria block; **FROZEN BASELINE: 30d per-incident auto-resolve = 0.4156**; edge-by-edge chaos parity QA (dict keeps authority ≥30d, earliest refactor 2026-07-09). QA 59/59 across 7 suites. 5 crons total. **REMAINING (data/operator-gated, by design): -1040 human gate (earliest ~2026-06-23 when scorecard all_met), -1041 Phase C (behind -1040), -1043 closeout verdict (needs after-number vs 0.4156). Bridge auto-resolve-on-verdict=match deliberately deferred behind -1040 (it flips authority).** Next session: check `~/logs/claude-gateway/infragraph-*.log` health + first real shadow predictions + first Runner execution with Commit Prediction node.

**SYSTEM ACTIVATED 2026-06-09 ~22:45 UTC per operator "active right now" (MRs !27/!28):** -1041 proposal lane LIVE (`infragraph-propose-blast-radius.py` --scan/--bootstrap/--approve/--reject/--list; cron :45; proposals = control YT issue + 'infragraph-proposal' pending row; ONLY --approve activates via 'blast-radius' row; close issue = instant deactivation). **Safety reframe: -1040 gate flipped from precondition-to-ask → continuous revocation review** (per-rule approval IS the safety; scorecard + PrecisionDrop alert + weekly audit revoke). **First real proposal: IFRNLLEI01PRD-1046 (nlpve04)** — pending approval; live PVE data knows n8n01/nlk8s-ctrl01 moved to nlpve04 (declared doc stale, says nl-pve01 — update host-blast-radius.md sometime). Chaos drills now record predictions at kill time (chaos-suppressed alerts never reach Step 2-graph, so drill records; drills are mostly QUIET cascades — verdict/delay evidence, NOT alert-precision evidence; precision comes from natural traffic, n≥30 in days). Drill chaos-2026-06-09-001 (NL↔GR budget) run as first labeled sample. First NATURAL shadow prediction recorded same night (nlk8s-node03, 9 children, -1021). CHAOS_SKIP_TURNSTILE=true needed for CLI drills. 6 crons now (+ propose :45). QA 65/65 across 8 suites.

**FIRST RULE APPROVED + LIVE (2026-06-09 ~23:10 UTC):** operator approved IFRNLLEI01PRD-1046 (nlpve04 blast radius: hosts nlk8s-ctrl01+n8n01, rules Device Down*/KubeAPIDown*/Service up/down*). Production-exact verify: real check_phase1b_blast_radius + real YT-open checker → both in-scope alerts dedup→-1046 @0.9, out-of-scope nl-gpu01 escalates, old -894 confirmed closed/inert. **Deactivate = close issue -1046.** Phase 1b verify recipe: `_yt_open_checker_default(url, token)` from lib.tier1_suppression + `set -a; source .env` (plain `source` doesn't export).

**FIRST EVAL RESULTS (2026-06-09 ~21:56 UTC, n=2):** natural pred #2 (nlk8s-node03 mem alert): 9 mined-edge (conf 0.55) children predicted, 0 fired — isolated alert, no cascade; teaches that the mined layer over-predicts on quiet alerts (why it's capped <0.8). Chaos pred #3 (NL-GR budget drill): predicted quiet, observed quiet (failover worked, 0 alerts) — vacuously correct. Headline precision 0.0 is honest-on-n=2; **the gate metric is precision_conf08 (suppression-eligible subset) — zero samples yet, accumulates from real cascade events on declared/live edges.** Synthetic livecheck pred #1 DELETED from prod evidence (operator's count-incidents-not-events lesson — never let synthetics pollute metrics). Drill recovered clean (failover via Freedom VTI, 600s). Gate: 2/30 evaluated, day 0/14, only sites_ok ✓. Everything runs hands-off via the 6 crons now.

**Session checkpoint 2026-06-09 (~20:00 UTC):**
- *Verification commands + results:* both QA suites via `QA_RESULT_FILE=$(mktemp) bash scripts/qa/suites/test-1031-*.sh / test-1033-*.sh` → **24/24 PASS**; MR pipelines 36440 + 36441 both `success`; fixture blast-radius query 19 ms (<2 s budget). MR created via GitLab REST (`POST /api/v4/projects/30/merge_requests`, token from repo `.env` `GITLAB_TOKEN`) — no gitlab-mcp tools and no `glab` on this host, REST is the working path.
- *Implementation gotchas worth keeping:* (1) migration-fixture trick — pre-seed `schema_migrations` 004..015 so only 016 is pending (earlier migrations need unrelated tables; copied from test-635). (2) SQLite recursive-CTE: bare-column-with-MIN() row guarantee voids with a second aggregate — per-node path reduction must happen in Python. (3) QA suites run `set -u` only; adding `set -e` mid-suite kills the script on expected-nonzero tests — capture `rc=$?` plainly. (4) schema.sql G-sections: G11-G14 already taken; infragraph is **G15**.
- *Confidence:* 0.95 shipped code is correct (evidence: 24/24 QA in-diff, green pipelines, contract exercised end-to-end incl. fail-open exit codes + kill-switch). 0.7 that incident co-occurrence learning (-1034) will yield enough high-confidence edges for the B→C precision gate — chaos-grade dynamics only exist for ~9 tunnel edges; the -1035 backtest is deliberately positioned to falsify this cheaply.
- *Open questions:* (a) cascade window per-edge vs global — revisit after -1035 backtest; (b) does triage.log contain tier1-suppressed alerts (eval ground-truth completeness, risk #1, blocks trusting recall); (c) action vocabulary → graph-operation mapping for `predict_action()` (reboot_host = transient node failure vs config_change = ?) — design in -1044; (d) reversibility flag source (AWX template metadata vs plan annotation) — decide in -1044.

### infragraph_honest_gate_20260624

2026-06-24 — investigated "fix infragraph so the B->C gate (IFRNLLEI01PRD-1040) can graduate." Root cause is NOT a broken graph:

**The gate is mathematically unsatisfiable by honest predictions.** It requires precision_conf08 >= 0.95 on the confidence >= 0.8 band. Measured from live data:
- The 0/20 precision_conf08 was ALL `model_version=1` legacy predictions (structural confidence on declared hard-down topology edges that predict `Device Down`/`KubeAPIDown` — the WRONG failure mode; real incidents are the etcd PERFORMANCE cascade).
- Under the live gating model (v2, -1118) the >=0.8 band is EMPTY: `apply_cascade_gating` already replaces structural confidence with the learned exact cascade_prob (`infragraph.py:581`), and **of 43 well-supported (seen>=8) exact cascade stats, ZERO reach 0.8 and ZERO reach 0.95.** Max in the whole graph = **0.70** (etcdHighCommit; etcdHighFsync 0.64). No real infra cascade is 95% deterministic, so a calibrated predictor cannot emit a 0.8-conf prediction that's then 95% precise. Inflating confidence = exactly what the shuffled-control guards against.
- So the 0.95/0.8 bar (set for AUTO-RESOLUTION) can't be met by honest stochastic predictions. The graph correctly learned that cascades are ~70% likely.

**Also found:** the real etcd cascade IS learned but keyed under generic `parent_family="host-down"` (rule_family had NO etcd class — etcd alerts fell through to per-rule singletons); incident-mined edges hard-cap at 0.75 (`infragraph-learn.py:198`, deliberate — learned edges can't auto-graduate to suppression-eligible); dead over-prediction edge `KubeAPIDown@ctrl01` seen=42/fired=0/P=0.012 (already excluded by the τ=0.10 emit gate, no pruning needed).

**SHIPPED — part 2, MR !51 (`a1f03e3b`, merged main; shadow/eval ONLY, fail-CLOSED action lane untouched):**
- `infragraph-eval.py`: gate evaluates `model_version>=2` (excludes retired v1) → scorecard honest (exact gate NO-GO because the band is genuinely empty, not dead-model noise). New `window_30d_gated`.
- `infragraph-eval.py`: ADVISORY **fold-gate candidate** = family precision on the `cascade_prob_family>=0.60` band (`FOLD_GATE`), the right metric for FOLDING (reversible, floor-guarded — tolerates the ~0.70 ceiling auto-resolve can't). Does NOT change `all_met`.
- `rule_family`: consolidate etcd-internal alerts (fsync/commit/grpc/leader) into one `etcd` family (principled — apiserver/pods left alone to avoid coarsening just to clear the bar = gaming). **Requires `infragraph-learn --from-cascades` on deploy** (invalidates learned stats; weekly :25 cron also recomputes).
- Backtest (30d, DB copy): fold precision_fold_family **0.779 -> 0.808** after etcd consolidation, recall_family 0.38, shuffled-control_ratio 0.0 (falsifiable). QA 1118/1119/1045/1034/1033 green.

**PART 1 — operator SET IT LIVE at 0.80, 2026-06-24 (MR !52, merged main 6705b2c2, deployed+committed to live checkout 2d18dd8):** The fold-gate is now the OPERATIVE Phase C gate at family precision >=0.80 (recall dropped as a blocker — for folding, low recall=under-fold=safe; gates on precision + evidence days>=14/n>=30/rules/sites + shuffled-control<=0.5x). `infragraph-propose-blast-radius.py` now AUTO-APPROVES proposed fold rules when the fold-gate is met AND the sentinel `~/gateway.infragraph_autofold` exists (created = ON). **Triple fail-CLOSED:** rm sentinel = instant kill; scorecard stale >8d = no auto-approve; `INFRAGRAPH_AUTOFOLD_DISABLED=1` = off. Never-auto-resolve floor (critical/irreversible/deviation) UNCHANGED — folding only dedups, never closes issues. **Current live status: authorized=False ("fold-gate not met") because days_observed 7.1 < 14** — precision already 0.808>=0.80 + control 0.0, so the ONLY remaining blocker is the 14-day evidence window. Autonomous folding self-activates in ~7 days when the v2 window fills; no further action. Verified: 4-case autofold gating (absent/NO-GO/MET/stale) + live --scan --dry-run + QA 1118/1119/1045/1034 green. The exact 0.95 AUTO-RESOLUTION gate is unchanged for anything that closes issues. `_autofold_authorized()` reads `test-results/infragraph-scorecard.json`. **Scorecard cron changed weekly(Mon 05:10)→DAILY (`10 5 * * *`)** so the gate refreshes daily and the autofold activates PROMPTLY at day-14 (~2026-07-01), not lagging to the next Monday.

**ACTIVATION VERIFICATION scheduled (operator asked "in 7 days verify it activated"):** NOT a cloud /schedule agent — those can't reach the live gateway.db/sentinel on nl-claude01 (internal host). Instead a LOCAL cron `0 9 1-8 7 *` runs `~/scripts/verify-foldgate-activation.sh` daily 2026-07-01..08. Idempotent (marker `~/gateway.foldgate-verified`): on the first day `_autofold_authorized()`==True it posts ✅ to IFRNLLEI01PRD-1040 + Matrix #infra-nl-prod and stops; if not activated by the 2026-07-08 deadline it posts a ⚠️ diagnosis (days<14 / precision<0.80 / control / sentinel removed / scorecard stale). Test-run 2026-06-24: logs not-yet (days 7.1), no post, no marker — correct. Reusable lesson: host-local verification needs a LOCAL cron, NOT the cloud /schedule skill.

Verification method (reusable): isolated `git worktree` off origin/main + `cp gateway.db backtest.db`; `infragraph-eval.py --db backtest.db --scorecard --no-notify` (output nested under `scorecard` key); re-learn with `infragraph-learn --db ... --from-cascades`. Diagnosis from [[infragraph_cascade_gating_1118_20260617]] follow-on; precision problem = -1065.

**2026-06-25 — REGRESSION + MY OVERCONFIDENT-ANSWER CORRECTION (operator asked "will it ever graduate, when?"):** I measured LIVE `precision_fold_family = 0.59` (7d) / 0.44 (30d), `all_met_fold=False`, days_observed 8.2/14, and confidently told the operator "NEVER graduates at 0.80, 0.59 is the ceiling, consolidation exhausted." **That was WRONG/overconfident — this very memory documents the 2026-06-24 backtest at 0.779→0.808 with the gate expected to auto-activate ~2026-07-01.** So fold precision DROPPED 0.808→0.59 in ONE DAY. The `--from-cascades` consolidation IS already deployed (hourly `25 * * * *` learn cron); re-running it on a DB copy changed nothing (0.59→0.59) — so 0.59 is the CURRENT value but NOT a fixed ceiling. **Most likely cause of the drop: the 2026-06-23..25 incident storm (GR etcd cascade [[gr_grk8s-ctrl01_etcd_gr-pve01_saturation_rca_20260623]] + the nlpve04 wedge + alert flaps) polluted the recent eval window with chaotic non-matching cascades → precision tanks until that ages out; OR my action_verdict #1/#2 changes (08bd/e92c) shifted match counting.** LESSON [[feedback_verify_belief_not_rationalize_observation]]: I should have cross-checked the documented 0.808 before declaring "never." **RESOLVED 2026-06-25 — DEFINITIVE NO-GO, -1040 CLOSED (Done).** Research workflow wf_f3d66535 (4 web agents) → synthesis → I ran a selective-prediction experiment (`scratchpad/foldgate_experiment.py`, v2-only, 770 family-deduped items, **Clopper-Pearson 95% LOWER bounds**, threshold sweep + Mondrian + temporal split). **THREE WALLS prove graduation at 0.80 is impossible:** (1) **confidence ceiling** max cascade_prob_family = **0.639** → the ≥0.80 band is structurally EMPTY (explains precision_conf08_family=0.0); (2) **no graduatable subset** — best CP-lower across ALL thresholds + ALL families = **0.578**, precision curve FLAT 0.645→0.698 as confidence rises → selective/conformal prediction returns the EMPTY SET (a valid impossibility proof per Angelopoulos-Bates LTT / Gang-Wang FSR); (3) **exchangeability VIOLATED** (deepest) — temporal 60/40 split: in-sample **0.843 → out-of-sample 0.300**. **So fold precision is NON-STATIONARY ~0.30-0.84 by incident regime — THIS is the mechanical explanation of the 0.808(06-24)→0.59(06-25) swing: the 0.808 was a real but non-generalizing reading on an early familiar-cascade window; recent etcd-storm window ~0.30; 0.59=blend.** Correction of my own flip-flop: my first "never (0.59 ceiling)" had the wrong reason; my "overconfident, it was 0.808" was also incomplete; the TRUTH = real-but-non-stationary, cannot be CERTIFIED at 0.80 because it doesn't hold on the NEXT incident. **DO NOT lower the bar to ~0.6** — real out-of-sample on novel incidents is ~0.30, so a lowered-bar fold silences real alerts during exactly the novel incidents you need to see. **VERDICT: keep infragraph Phase-B advisory + the live safety invariant PERMANENTLY; only lever is more incident-DIVERSE data (not a better estimator, not a lower bar).** -1040 closed with the full no-go comment. Note: the scheduled 2026-07-01 fold-gate verification cron WILL correctly report not-activated (precision<0.80) = fail-closed working, NOT a regression. Methodology refs (credible): Angelopoulos/Bates/Candès/Jordan/Lei 'Learn then Test' AoAS 2025; Gang/Wang selective-classification FSR 2023; Conformal Risk Control ICLR 2024; Mondrian/class-conditional CP; isotonic/Venn-Abers calibration. Lesson [[feedback_verify_belief_not_rationalize_observation]]: gate on LOWER bounds + out-of-sample, never an in-sample point estimate (the whole 0.808-vs-0.59 confusion was a point-estimate-on-a-shifting-window artifact).

### infragraph-precisiondrop-suppression-20260619

2026-06-19 — Added a Tier-1 Phase-2 (known-pattern) suppression for the **InfragraphPrecisionDrop** Prometheus alert, because it was firing ~2×/day and spawning a full Tier-2 claude-opus session each time that just auto-resolved it (6 of the 10 auto-resolves in the prior 3 days were this one alert closing itself). The precision is genuinely low — the known, tracked `-1065` condition being calibrated by `-1118`/`-1119` toward the `-1040` B→C gate — so the alert is expected noise, not a real incident.

**What was done:** one row inserted into `incident_knowledge` (the same mechanism as the 4 existing noisy-alert rows: KubeClientErrors/HighPodRestartRate/ContainerOOMKilled/TargetDown):
- `id=1452`, `alert_rule='InfragraphPrecisionDrop'`, `hostname='*'` (host-agnostic), `confidence=0.9`, `tags` include a transient keyword (`recovered`) so Phase 2 matches, `issue_id='IFRNLLEI01PRD-1065'`, `project='chatops'`, `valid_until` = 2026-07-19 (review marker only — Phase 2's query does NOT enforce valid_until for `*` rows; they persist until deleted).
- DB: `/app/cubeos/claude-context/gateway.db` (== `~/gateway-state/gateway.db`, a symlink).

**Effect (verified via the exact production CLI):** `run-triage.sh k8s` → `k8s-triage.sh` → `run_tier1_suppression` → `tier1_suppression.py` → InfragraphPrecisionDrop **warning** ⇒ `resolved-knownpattern` (no Tier-2 session). **Critical** instances still `escalate` (Phase 2 excludes critical) — safety preserved. Unrelated rules not over-matched.

**REMOVAL (obligation):** delete the row once infragraph precision recovers / the `-1040` gate is met:
`sqlite3 ~/gateway-state/gateway.db "DELETE FROM incident_knowledge WHERE id=1452;"`
Until then it silently swallows the warning re-fires — so if you're ever debugging "why is InfragraphPrecisionDrop not paging," this row is why. Chose Phase 2 over Phase 1b blast-radius because `-1065` keeps auto-closing (it's not a stable open parent) and Phase 2 closes each re-fire cleanly with no parent-comment spam. Related: [[k8s-residual-triage-20260617]], [[infragraph-cascade-gating-1118-20260617]].

### knowledge_injection

## CLAUDE.md + Memory Knowledge Injection (2026-04-06)

Both ChatOps/ChatSecOps tiers now aware of procedural knowledge from repos and Claude memory files.

### What was added
- **claude-knowledge-lookup.sh** — hostname→CLAUDE.md routing (pve/, docker/, network/, k8s/, native/, edge/) + feedback memory extraction. Memories output first (survive 2000-char truncation). Called at Step 2-kb in infra-triage, k8s-triage, correlated-triage.
- **Build Prompt enrichment** — `claudeMdGuidance` (targeted CLAUDE.md file paths per hostname) + `memorySection` (auto-retrieved feedback rules). Query Knowledge extracts `MEMORY_START/END` block.
- **openclaw-repo-sync.sh** — `*/30` cron on nl-openclaw01. Pulls 23 repos + syncs 51 feedback memories (SSH+tar) + gateway.db read replica (scp).

### Architecture
- All CLAUDE.md reads are LOCAL on both hosts (repos synced by cron, max 30min staleness).
- Semantic search (kb-semantic-search.py) runs LOCAL on OpenClaw — Ollama on nl-gpu01 reachable on same VLAN 181 subnet. No SSH for reads.
- SSH to app-user only for WRITES (SQLite inserts, triage.log appends, CodeGraph).
- Docker compose on openclaw01 has bind mounts: `/root/.claude-memory:/home/node/.claude-memory:ro` + `/root/.claude-data:/home/node/.claude-data:ro`.

### Compiled Wiki KB (2026-04-09)
- **wiki-compile.py** — compiles 7+ sources (70 memories, 37 CLAUDE.md, 28 incidents, 7 lessons, 88 openclaw_memory, 23 docs, 15 skills, 5 dashboards, ~5,200 lab files) into 45 wiki articles at `wiki/`.
- **3-signal RRF** — wiki articles embedded in `wiki_articles` SQLite table (45 rows, nomic-embed-text 768 dims). 3rd ranking signal in `kb-semantic-search.py` hybrid search alongside semantic + keyword.
- **Health checks** — `--health` mode detects staleness (line-number rot in memories) + coverage gaps (incidents without lessons).
- **Cadence** — daily 04:30 UTC cron + on-demand `/wiki-compile` skill. Incremental via SHA-256 checksums.
- **Auto-propagation** — wiki/ is in claude-gateway repo → `openclaw-repo-sync.sh` picks it up on OpenClaw within 30min.

### Pattern impact
Memory (8): A→A+ (compiled wiki = organized semantic memory). Learning (9): A→A+ (health checks surface knowledge gaps). RAG (14): A→A+ (3-signal RRF: semantic + keyword + wiki articles).

### Key paths on openclaw01
- Repos: `/root/gitlab/` (23 repos, mirrors app-user)
- Memories: `/root/.claude-memory/{infrastructure-nl,infrastructure-gr,gateway}/`
- DB replica: `/root/.claude-data/gateway.db`
- Sync script: `/root/openclaw-repo-sync.sh`
- Sync log: `/tmp/openclaw-repo-sync.log`
- Cron: `*/30 * * * * /root/openclaw-repo-sync.sh`

### rag_circuit_breakers

## Library

`scripts/lib/circuit_breaker.py` — three-state breaker (CLOSED / OPEN / HALF_OPEN) per Netflix Hystrix pattern. Thread-safe within process, SQLite-backed state shared across processes via `circuit_breakers` table in `gateway.db`. Decorator API (`@cb.wrap(fallback=...)`) + imperative API (`if not cb.allow(): ...; record_success/record_failure`). Persist-on-init writes a baseline row so the Prometheus exporter sees every breaker even before the first failure.

## Active breakers (2026-04-19)

All wired in `scripts/kb-semantic-search.py`:

| Name | Wraps | Threshold | Cooldown | Fallback |
|---|---|---|---|---|
| `rag_rerank_crossencoder` | `_rerank_via_crossencoder` (bge-reranker-v2-m3 at nl-gpu01:11436) | 3 | 90s | `None` → caller drops to Ollama rerank |
| `rag_embed_ollama` | `_embed_raw` (nomic-embed-text) | 5 | 120s | `None`-vectors → caller handles gracefully |
| `rag_synth_haiku` | `_call_haiku_synth` (Anthropic /v1/messages) | 3 | 180s | empty string → caller degrades to qwen |
| `rag_synth_ollama` | `_call_qwen` in `synthesize_answer` (qwen2.5:7b) | 4 | 120s | empty string |

Pattern is always imperative, not decorator — preserves each call site's existing return-on-failure contract (critical for `ex.map()` pipelines that would propagate exceptions).

## Observability

- `scripts/write-circuit-breaker-metrics.sh` cron `*/5` writes to `/var/lib/node_exporter/textfile_collector/circuit_breaker_metrics.prom`
- Three gauges: `circuit_breaker_state` (0=closed, 1=half_open, 2=open), `circuit_breaker_failure_count`, `circuit_breaker_opened_timestamp_seconds`
- Prometheus alerts in `prometheus/alert-rules/rag-health.yml`:
  - `CircuitBreakerOpen` — fires after a breaker has been OPEN for ≥10 min
  - `CircuitBreakerMetricAbsent` — absent-guard (fires if metric disappears for 2 h)
- CLI: `cd scripts && python3 -m lib.circuit_breaker list` (shows all breakers + state + age). Reset with `... reset <name>`.

## Not wrapped (deliberately)

- `rewrite_query` / `rewrite_query_multi` (L349, L447 in kb-semantic-search.py) — cheap, empty-list fallback already graceful, low operational value.
- Ollama yes/no rerank inside `rerank_candidates` (L601) — is itself the fallback for `rag_rerank_crossencoder`; wrapping it would put two breakers in series, circular.

## How to apply

- When adding a new external API call, wrap it: declare a CircuitBreaker at module top, call `allow()` before the request, `record_success()` on 2xx, `record_failure(exc)` in the `except`. Match the imperative pattern already used; avoid the decorator form in places where exceptions must be swallowed for caller compatibility (most RAG sites).
- When a breaker trips in production, the fast check is `python3 -m lib.circuit_breaker list` to see current state + age. `reset <name>` clears it if the upstream has recovered and you don't want to wait for the cooldown probe.
- The quote-balance heuristic was tried and removed from `validate-n8n-code-nodes.sh` — escaped quotes in strings produce false positives. `node --check` + `new Function()` parse are the authoritative checks; rely on those.

## Commits

Gateway repo main:
- `d6e4e76` library + first wrap (rerank service)
- `6d10b0b` 3 more wraps (embed, haiku synth, ollama synth)

### Q2 cross-chunk synthesis in RAG pipeline

## What

`synthesize_answer()` in `scripts/kb-semantic-search.py` — activated when cross-encoder rerank max score falls below `SYNTH_THRESHOLD` (default 0.7). Produces a direct 2–3 sentence answer with `[N]` citations, prepended to output as `source=synthesis` row.

## Why

Meta-queries ("how many RRF signals?", "current RAG scores?", "EUR cost cap?") need information spread across 3+ chunks. No single doc answers them, so cross-encoder max score is <0.7. Before Q2 these were consistent misses (5 of the hardest 20 queries).

## Key design choices

1. **Fresh candidates** — bypass fusion pool because llama3.2:1b rewrite sometimes hallucinates (observed "RFM" substituted for "RRF"), polluting candidates. `_synth_fresh_candidates()` re-probes `wiki_articles` + `incident_knowledge` using raw query embedding only.
2. **Trigger threshold 0.7** (not 0.3): many relevant-but-indirect matches score ~0.5; at 0.3 we rarely synthesized.
3. **qwen2.5:7b** at `num_ctx=4096` (not 1024) so it can fit 10 chunks × 500 chars + instructions. Takes ~2s warm.
4. **NO_ANSWER escape hatch**: if chunks truly don't contain an answer, model returns `NO_ANSWER` and we skip rather than fabricating.
5. **Prepend, don't replace**: raw retrieved rows still returned after the synthesis row. Downstream consumers (and judge) can cross-check citations.

## Measured impact

50-query hard eval, 3 deterministic runs:
- judge hit@5: 48% → 61% (+13 points)
- substr hit@5: 30% → 44% (synthesis often contains exact strings)
- p50 latency: 3.0s → 3.6s
- p95 latency: 4.0s → 5.1s

## Env controls

- `SYNTH_ENABLED=1` (default on)
- `SYNTH_THRESHOLD=0.7` (cross-encoder max below → trigger)
- `SYNTH_MODEL=qwen2.5:7b` (swap to `haiku` via extension for higher quality at cost)

## How to disable

Set `SYNTH_ENABLED=0`. Pipeline falls back to plain rerank.

## Verified 2026-04-18

H16 ("current RAG scores") — pre-Q2: MISS. Post-Q2: synthesis produced "Faithfulness: 1.000 [3] — Context Precision: 0.964 [3] — Context Recall: 0.995 [3]", judge hit.

### Unified Knowledge Base Wiki

Compiled wiki at `wiki/` in claude-gateway repo (2026-04-09). 45 articles across 8 categories compiled from 7+ knowledge sources.

**Compiler:** `scripts/wiki-compile.py` — source readers for memory files (69), CLAUDE.md (37), SQLite tables (incident_knowledge 28, lessons_learned 7, openclaw_memory 87), docs (22), OpenClaw skills (15), Grafana dashboards (5), 03_Lab manifest (~5,200 files).

**Key features:**
- Incremental compilation via SHA-256 checksums in `wiki/.compile-state.json`
- Health checks: `--health` flag detects staleness (line number refs) + coverage gaps (incidents without lessons)
- RAG integration: wiki articles embedded in `wiki_articles` table (45 rows), 3rd signal in RRF fusion in `kb-semantic-search.py`
- On-demand: `/wiki-compile` skill
- Daily cron: 04:30 UTC (between 04:00 golden-test and 06:03 proactive-scan)

**Highest-value article:** `wiki/operations/operational-rules.md` — all 24 feedback memories compiled by domain (Config Safety, ASA/VPN, K8s, Deployment, Infra Ops, Data Integrity, General).

**Why:** No unified view of knowledge previously existed across 7+ fragmented stores. Inspired by Karpathy's LLM Knowledge Bases pattern.
