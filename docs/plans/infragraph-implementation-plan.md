# Infragraph — Implementation Plan of Record

**Epic:** IFRNLLEI01PRD-1029 · **Children:** IFRNLLEI01PRD-1030..-1043 · **Approved:** 2026-06-09

## Context

The agentic triage system's #1 quantified weakness is cascade-symptom escalation: the 2026-05-11 n8n OOM produced 43 symptom escalations that dragged the per-incident auto-resolve rate from a ~55–65% steady state to 28.57%. Dependency knowledge today is scattered (NetBox topology, operator-declared Phase 1b blast-radius rows in `openclaw_memory`, a hardcoded `TUNNEL_GRAPH_EDGE` dict in `chaos-test.py:241-265`, prose memories) and `docs/host-blast-radius.md` is an **empty file**. Meanwhile `chaos_experiments` already records per-run dynamics (mttd/mttr/expected_alerts/convergence) that nothing consumes as a predictive model.

**Goal:** one queryable causal graph — topology seeded from NetBox/IaC, dynamics learned from chaos runs and incident history — integrated into the triage hot path. **Advisory first, suppression authority earned** through a shadow-mode eval with hard, falsifiable thresholds. Tracked as a YouTrack epic (IFRNLLEI01PRD) with full docs.

**Operator decisions (confirmed):** Phase C uses *operator approval per generated rule*; the n8n Build Prompt Tier-2 injection *is in scope* as the last Phase A issue.

## Architectural invariant (operator-mandated 2026-06-09, NON-NEGOTIABLE)

This is a genuine **model-free → model-based** shift, not a euphemism. The
distinction is **control flow, not data**. Three hard structural requirements
(child issues IFRNLLEI01PRD-1044 / -1045):

1. **Prediction is computed outside the LLM.** Blast-radius / cascade /
   action-consequence prediction comes from deterministic graph traversal —
   `infragraph.predict_action(action)` returning a structured artifact
   `{predicted_alerts[], propagation_delay, recovery_time, confidence,
   blast_radius_count}` committed to `infragraph_predictions` (kind='action').
   The **orchestrator (n8n Runner)** calls it between Classify Risk and Build
   Prompt. The LLM receives the prediction as prompt input; it is never the
   predictor.
2. **Prediction is mandatory and non-bypassable.** A remediation proposal is
   NOT eligible to reach the approval poll (human OR auto) without a committed
   prediction row whose `plan_hash` matches the classified plan. Missing
   artifact → session demoted to **analysis-only** (findings posted, no
   executable proposal). The LLM cannot skip, override, or decide whether to
   use it.
3. **Verification is mechanical.** Post-execution, the orchestrator runs
   `infragraph-verify.py`: code diffs observed alerts vs the prediction within
   its window and writes the verdict. `match AND reversible AND
   blast_radius < threshold` → auto-resolve with the diff as evidence.
   Deviation → surprise → escalate. The LLM does not adjudicate its own
   outcome.

**Acceptance test (operator's words):** *can an approved remediation exist
without a machine-computed, committed prediction attached?* Must be
structurally **no** — enforced in three places: the Prepare Result control-flow
gate, an e2e QA test that attempts the bypass and must fail, and a weekly
`audit-risk-decisions.sh` extension asserting zero approved/auto-resolved
sessions without a joined prediction row.

**Fail-semantics split (consequence of the invariant):** the read-only triage
enrichment lane still **fails open** (alert triage never blocks on infragraph).
The remediation lane **fails closed**: infragraph down or
`INFRAGRAPH_DISABLED=1` ⇒ remediation proposals disabled entirely. The
kill-switch means "analysis-only mode", never "remediation without
predictions". The LLM stays the reasoner interpreting predictions; it is not
the predictor.

## Headline design decisions

| Decision | Choice | Why |
|---|---|---|
| Storage | Extend existing `graph_entities`/`graph_relationships` (`schema.sql:304-328`) + new sidecar `infragraph_dynamics` + `infragraph_predictions` tables | Topology fits the existing GraphRAG layer; dynamics need indexed columns; sidecar avoids touching `populate-graph.py` writers |
| Engine | SQLite `WITH RECURSIVE` CTEs, no kuzu/networkx | Repo convention; ~350 nodes is trivial for the <2s latency budget |
| Declared edges | Populate `docs/host-blast-radius.md` as git-reviewed source-of-truth table; seeder parses it | MR-reviewed provenance for hand-declared edges; DB is runtime view |
| Phase C mechanism | Generate Phase 1b `openclaw_memory` blast-radius rows (exact format from `tier1_suppression.py:173-196`) gated on **operator approval per rule**, keyed to control YT issues | Zero hot-path code change — Phase 1b already enforces these with conf 0.90 + auto-deactivation on issue close; honors no-false-positive invariant |
| `TUNNEL_GRAPH_EDGE` | Mirror into graph now; refactor chaos-test.py to read graph only after ≥30d byte-parity (QA check) | The dict guards the chaos safety BFS — safety-critical |
| Failure mode | Everything fails OPEN (`INFRAGRAPH_DISABLED=1` env kill-switch; non-zero exit = "no graph data") | Triage must never block on infragraph |

## M1 — Schema + library + query CLI

**`schema.sql`** — new `-- G15: Infragraph` section:
- New `entity_type` values on `graph_entities`: `physical_host`, `pve_node`, `vm`, `lxc`, `service`, `network_device`, `tunnel`, `bgp_session`, `site` (names = full site-prefixed hostnames per P0 rule; tunnels `tunnel:NL-GR:budget`; `source_table='infragraph'`, attributes JSON carries vmid/site/netbox_id/role/ip).
- New `rel_type` values: `runs_on`, `depends_on`, `routes_via`, `member_of`, `backs_up_to`, `peers_with`.
- `infragraph_dynamics` (1:1 with edge): `rel_id UNIQUE FK`, `source` (declared|chaos|incident|netbox|iac), `expected_alerts` JSON, `delay_p50_s/delay_p95_s/recovery_p50_s`, `observation_count`, `last_validated`, `valid_until` (NULL = open-ended; netbox/iac edges get now+7d, refreshed by daily seed — dead seeder ⇒ visible expiry), `confidence`, `schema_version`.
- `infragraph_predictions` (shadow log): parent_{issue_id,host,rule}, `window_seconds`, `predicted` JSON, `control_predicted` JSON (degree-preserving shuffled-graph negative control, seeded per-day), `evaluated_at`, `actual` JSON, `tp/fp/fn`, `control_tp/control_fp`, `model_version`, `schema_version`.
- Index: `idx_gr_source_type ON graph_relationships(source_id, rel_type)` + sidecar indexes.

**Register both tables** in `scripts/lib/schema_version.py` (`CURRENT_SCHEMA_VERSION` + `SCHEMA_VERSION_SUMMARIES`, stamp every INSERT).

**`scripts/lib/infragraph.py`** — traversal (depth cap 5, confidence product along path, `valid_until` filter), upsert-with-provenance (reuse `populate-graph.py` upsert pattern), dynamics streaming update, shuffled-graph control generator.

**`scripts/infragraph-query.py`** — stable JSON on stdout, exit 0/1(empty)/2(error), 2s self-timeout, `elapsed_ms` in output:

```
blast-radius --host H [--depth 3]
  → {"query":"blast_radius","host":H,"depth":3,"generated_at":ISO,
     "nodes":[{"name","entity_type","site","distance","via","path":[...],
               "confidence","source"}],
     "counts":{"total":N,"by_type":{...}},"elapsed_ms":N}
deps --host H              # same shape, reverse direction
cascade --host H --rule R [--window auto] [--record --issue YT-ID]
  → {"query":"expected_cascade","host","rule","window_seconds",
     "predictions":[{"host","rule","expected_delay_s":{"p50","p95"},
                     "confidence","observations","source","last_validated"}],
     "model_version","prediction_id":int|null,"elapsed_ms"}
     # --record writes infragraph_predictions incl. control_predicted
     # window = max(900, 2×max p95) per-edge
explain --from A --to B    → {"reachable",
     "paths":[{"hops":[{"from","rel","to","confidence"}],"length","min_confidence"}]}  # top-3
health → {"nodes_total","nodes_by_type","edges_total","edges_by_rel","edges_by_source",
     "stale_edges","last_seed":{netbox,iac,tunnels,declared},
     "dynamics_coverage","predictions":{"total","evaluated","precision_30d","recall_30d"}}
```

This JSON contract is what `infra-triage.sh`, `classify-session-risk.py`, and the eval consume — freeze it at `model_version 1`.

## M2 — Builders (seed + learners) + first hard evidence

**`scripts/infragraph-seed.py`** (idempotent upserts; stamps `last_seed.<source>`):
- `--netbox`: devices/VMs/sites/VLANs via NetBox API → `runs_on`, `member_of`, roles.
- `--iac`: `tofu show -json` over `/app/infrastructure/{nl,gr}/production` → VM/LXC→pve_node (vmid, target_node), `backs_up_to`.
- `--tunnels`: import `TUNNEL_GRAPH_EDGE` from chaos-test.py → site/tunnel nodes, `routes_via`/`peers_with`, source='declared', conf 1.0.
- `--declared`: parse `docs/host-blast-radius.md` table (`| source | rel_type | target | expected_alerts | notes |`).
- Cron: daily 04:10 UTC, all sources.

**`scripts/infragraph-learn.py`**:
- `--from-chaos`: per completed `chaos_experiments` row → map targets to edges, refresh dynamics (expected_alerts ∪ observed, delay←mttd, recovery←mttr, observation_count++, confidence from verdict history). Hooked at end of chaos-test.py run + hourly idempotent sweep (experiment_id watermark).
- `--from-incidents`: mine triage.log (`ts|host|rule|site|outcome|conf|dur|issue`) co-occurrence — children within 900s on hosts ≤2 topology hops; require **≥3 observations AND ≥3× lift** over base rate before writing. Also ingest `incident_knowledge` rows where root-cause host ≠ alert host.

**Backtest (first evidence, before any hot-path change):** `infragraph-eval.py --replay 2026-05-11` — run the model retroactively against the n8n-OOM cascade; report how many of the 43 symptom escalations it would have predicted. This validates the concept on historical data at zero risk.

## M3 — Phase A: advisory enrichment (zero authority)

- **`openclaw/skills/infra-triage/infra-triage.sh`**: new `Step 2-graph` right after Step 2-pre NetBox lookup (~line 620): call `blast-radius` + `cascade` (no `--record`), append compact summary to `FINDINGS` + "## Infragraph context" section in the YT comment (Step 7). Guarded by `INFRAGRAPH_DISABLED`, fails open.
- **`scripts/classify-session-risk.py`**: advisory signal `infragraph:blast-radius-high(N)` when downstream count ≥ 8 — bumps risk **upward only**, never lowers; `infragraph:unavailable` on error with classification unaffected. Audited in `session_risk_audit` as today.
- **n8n Build Prompt node** (in scope, last Phase A issue): inject compact cascade context into the Tier 2 prompt. Follows the full Code-node safety runbook (snapshot → edit → `--check` → `validate-n8n-code-nodes.sh` → PUT → re-fetch → toggle → commit).
- **Gate A→B:** 7 days green graph health (no staleness alerts, dynamics_coverage > 0.15), holistic §39 passing, Step 2-graph p95 elapsed_ms < 2s.

## M4 — Phase B: shadow prediction + eval (still zero authority)

- Step 2-graph switches to `cascade --record --issue $ISSUE_ID` — every parent alert logs prediction + shuffled-graph control.
- **`scripts/infragraph-eval.py`** (hourly cron): for closed windows, actual = distinct (host,rule) in triage.log within (parent_ts, parent_ts+window]; compute TP/FP/FN for real and control predictions. Verify first (risk #1) that tier1-suppressed alerts also land in triage.log; if not, evaluator additionally reads the tier1 audit rows.
- Weekly scorecard → `test-results/infragraph-scorecard.json` (P/R 7d/30d, control deltas, sample counts) + Prometheus gauges.
- **Gate B→C (all must hold — this is the falsifiable eval):**
  - ≥30 evaluated predictions over ≥14 days, ≥3 distinct parent rules, both sites represented
  - **precision ≥ 0.95** on the confidence ≥ 0.8 subset (only subset eligible for suppression)
  - recall (documented as lower bound — unrelated alerts in window count as FN) ≥ 0.40
  - **shuffled-graph control precision ≤ 0.5× real precision** — if the control matches the real model, the graph adds nothing and Phase C is REJECTED
  - simulated-suppression audit: 0 critical / 0 later-escalated alerts would have been wrongly folded
  - baseline snapshot: 30d per-incident auto-resolve rate + escalation counts (from `agentic-stats.py` outcomes block) frozen into the scorecard.

## M5 — Phase C: earned authority via existing Phase 1b

- **`scripts/infragraph-propose-blast-radius.py`**: when a recorded prediction has ≥N high-confidence children, create a control YT issue containing the candidate `openclaw_memory` JSON (exact `tier1_suppression.py` Phase 1b format: `{hosts, host_patterns, rules, description, started_at}` + metadata tag `generated_by:infragraph`) and post to Matrix. **The memory row is written only after operator approval.** Auto-deactivation on issue close = existing Phase 1b semantics; no suppression-path code change.
- Generated rules feed the weekly `scripts/audit-risk-decisions.sh` review surface.
- chaos-test.py graph-parity QA check (graph tunnel edges == TUNNEL_GRAPH_EDGE); dict refactor only after 30d parity, separate issue.
- **Success metric:** per-incident 7d auto-resolve delta vs the frozen Phase B baseline; replay target ≥35/43 of the 2026-05-11 cascade would have folded.

## Testing & observability

- **QA suites** (`scripts/qa/suites/`, JSONL convention): schema/DDL+version stamps; query CLI (fixture graph in temp DB, exact JSON shapes, depth caps, <2s, fail-open exit codes); learners (synthetic triage.log + chaos rows → expected dynamics); eval (canned predictions vs actuals → exact P/R + control sanity).
- **e2e** `scripts/qa/e2e/test-e2e-infragraph.sh`: most recent completed `chaos_experiments` tunnel-kill row as ground truth — `cascade` for the killed target must ⊇ the row's expected_alerts with delays within p95. Live chaos run = M4 acceptance demo.
- **holistic-agentic-health.sh §39 "Infragraph"**: counts nonzero, last_seed < 26h, dynamics_coverage, unevaluated backlog, scorecard freshness.
- **`scripts/write-infragraph-metrics.py`** (cron */5 → `/var/lib/node_exporter/textfile_collector/infragraph.prom`): nodes/edges by type+source, last_seed timestamps, predictions evaluated, precision/recall/control 7d. Alerts in `prometheus/alert-rules/agentic-health.yml`: `InfragraphMetricsExporterStale`, `InfragraphSeedStale`, `InfragraphPrecisionDrop`.
- `docs/crontab-reference.md` regen after cron additions.

## YouTrack epic (IFRNLLEI01PRD)

Epic: **"Infragraph — causal infra dependency graph with learned dynamics"**. Children (sequenced, feature branch + MR each):

1. Design doc + schema DDL + query contract committed to `docs/plans/` — S
2. Schema + schema_version registry + `lib/infragraph.py` + QA schema suite — M
3. Seeders ×4 + populate `docs/host-blast-radius.md` + daily cron — M
4. `infragraph-query.py` CLI + QA query suite — M
5. Learners (chaos + incident co-occurrence) + QA learn suite — M
6. **Backtest replay vs 2026-05-11 cascade (first hard evidence)** — S
7. Phase A: triage Step 2-graph + risk-classifier signal + YT comment section — M
8. Exporter + Prometheus alerts + holistic §39 + crontab-reference — S
9. Phase A (n8n): Build Prompt Tier-2 injection, validator-gated — S
10. Phase B: shadow recording + `infragraph-eval.py` + scorecard cron + e2e chaos test — M
11. **Phase B→C gate review — explicit go/no-go with scorecard attached** — S (human gate)
12. Phase C: propose-blast-radius generator + operator-approval flow + audit hook — M
13. chaos-test.py graph-parity check — S
14. Runbook + wiki + CLAUDE.md one-liner + closeout eval report — S

## Docs

- `docs/plans/infragraph-implementation-plan.md` — this design.
- `docs/runbooks/infragraph.md` — RB-ID + VALIDATE comments: reseed, scorecard interpretation, approve/reject proposed rules, per-phase rollback, staleness-alert response.
- `docs/host-blast-radius.md` — populated as declared-edges table + seed-pipeline header.
- CLAUDE.md one-liner under Operational runbooks (per "where to add content" allocation).

## Rollback per phase

- **A:** `INFRAGRAPH_DISABLED=1` (instant, no deploy); all callers fail open.
- **B:** drop `--record` + stop eval cron; predictions table append-only and inert.
- **C:** close infragraph-generated control issues (instant Phase 1b deactivation); belt-and-braces `DELETE FROM openclaw_memory WHERE category='blast-radius' AND value LIKE '%generated_by%infragraph%'`.

## Risks

1. triage.log completeness as eval ground truth — verify in issue #2 before trusting recall.
2. Co-occurrence confounds → ≥3 obs + 3× lift + 2-hop constraint; needs ≥30d log history for base rates.
3. Recall is a lower bound by construction — documented in scorecard.
4. n8n node lives outside repo — advisory-only so drift is harmless.
5. NetBox/IaC drift → 7d valid_until expiry makes seeder failure visible, not silently wrong.
6. Sparse chaos coverage (~9 chaosable edges) — conf ≥0.8 cutoff naturally restricts Phase C to evidenced edges.

## Verification (end-to-end)

1. `python3 scripts/lib/schema_version.py` shows both new tables; QA schema suite PASS.
2. `infragraph-seed.py` all sources → `infragraph-query.py health` shows nonzero nodes/edges, fresh last_seed.
3. `infragraph-query.py blast-radius --host nl-pve03` returns gpu01 VM + dependents in <2s.
4. Backtest replay report on 2026-05-11 cascade (issue #6) — the concept's go/no-go evidence.
5. Live triage of a real alert shows "## Infragraph context" in the YT comment; `INFRAGRAPH_DISABLED=1` removes it cleanly.
6. e2e chaos ground-truth test PASS; holistic §39 PASS; `infragraph.prom` present and fresh.
7. After ≥14d shadow: scorecard meets/fails the B→C thresholds — either outcome is a documented, evidence-backed result (the eval is designed to be able to fail).
