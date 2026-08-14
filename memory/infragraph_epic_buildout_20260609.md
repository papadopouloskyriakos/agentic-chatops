# Infragraph epic build-out — concept to live model-based control in one day (2026-06-09)

**Epic:** IFRNLLEI01PRD-1029, children -1030..-1045 (16 issues; 13 DONE same day).
**MRs:** claude-gateway !20–!28 (all merged) + IaC `infrastructure/nl/production!327` (Atlantis-applied).
**Plan of record:** `docs/plans/infragraph-implementation-plan.md` · **Runbook:** `docs/runbooks/infragraph.md` (RB-IG-001).

## What was built

A causal infrastructure dependency graph ("world model") integrated into the alert-triage
pipeline as a genuine **model-free → model-based shift enforced in control flow, not data**
(operator-mandated invariant, non-negotiable):

1. **Prediction outside the LLM** — deterministic graph traversal (`infragraph-query.py
   {blast-radius,deps,cascade,predict,explain,health}`), called by the orchestrator.
2. **Mandatory + non-bypassable** — the n8n Runner (`qadF2WcaBsIR7SWG`) chain is
   Classify Risk → **Commit Prediction** → Build Prompt; the Prepare Result gate
   default-DENIES any [POLL] lacking a committed `infragraph_predictions` kind='action'
   row whose `plan_hash` matches the classified plan (`[POLL-WITHHELD:NO-PREDICTION]` →
   analysis-only). `INFRAGRAPH_DISABLED=1` = remediation lane **fails CLOSED**
   (analysis-only mode); the read-only triage enrichment lane fails OPEN.
3. **Mechanical verification** — `lib.action_verdict()` is the ONLY verdict author
   (match | partial | deviation; deviation = unpredicted host = never auto-resolve);
   `infragraph-verify.py` exit codes encode the verdict (0/1/2/3-open/4-missing);
   verdicts + per-alert diffs post to YT as the evidence trail. The LLM never
   adjudicates its own outcome.

## Architecture facts

- **Storage:** rides the existing G10 GraphRAG tables (`source_table='infragraph'`) +
  G15 sidecars `infragraph_dynamics` / `infragraph_predictions` (schema.sql + migration
  `016_infragraph.sql`; registered in `lib/schema_version.py`). Edge direction:
  **SOURCE depends on TARGET**. SQLite recursive CTEs, no new engine.
- **Sources of truth (layered, per-edge provenance + confidence + 7d valid_until on
  automated layers):** `pve` live cluster API 0.95 (188 guests; replaced planned --iac —
  production IaC has no target_node) → `librenms` dependency parents 0.90 (14) →
  `netbox` sites + cables 0.85–0.90 (130 dev + 15 cable edges) → `declared`
  (`docs/host-blast-radius.md` + chaos TUNNEL_GRAPH_EDGE) → `incident` co-occurrence
  miner **capped 0.75 = structurally below the 0.8 suppression-eligibility cutoff**.
  `chaos` upgrades exercised edges to 0.9 with real delay/recovery (149 experiments,
  220 observations folded). Live graph at build: **356 nodes / 414 edges**.
- **Crons (nl-claude01, 6):** seed `10 4 * * *` --all · learn `25 * * * *` ·
  metrics `*/5` · eval --pending `40 * * * *` · scorecard `10 5 * * 1` ·
  propose --scan `45 * * * *`. Logs `~/logs/claude-gateway/infragraph-*.log`.
- **Observability:** `infragraph.prom` textfile exporter; PrometheusRule alerts
  `Infragraph{MetricsExporterStale,SeedStale,PrecisionDrop}` (verified in-cluster);
  holistic-health **§39**; weekly `audit-risk-decisions.sh` invariant section (runs even
  on empty windows; exit 2 if the Runner export ever loses the gate).
- **QA: 65/65 across 8 suites** (schema/seed/query/learn/phase-a/proposal/gate/verify),
  incl. bypass attempts driven against gate code EXTRACTED from the workflow export and
  a test driving the REAL tier1 Phase 1b matcher against a generated rule.

## Evidence (the falsifiable eval)

- **2026-05-11 backtest (n8n OOM + GR mass-flap):** 4 honest rounds 19.5%/0.65 →
  26.4%/0.61 → 28.7%/0.52 → **34.5% coverage / 38.2% escalated / control-ratio 0.367 —
  PASSES the ≤0.5× shuffled-graph criterion**. Each round's misses drove the next source
  (librenms parents → netbox cables → common-cause sibling expansion at 0.6× conf).
  Quiet-day sanity (05-08): 3/24 (the 4-VM sibling burst), control 0.
- **Frozen baseline (first scorecard):** 30d per-incident auto-resolve = **0.4156** —
  the before-number for the -1043 closeout verdict.
- **First live evals (n=2, same night):** natural nlk8s-node03 pred — 9 mined-edge (0.55)
  children predicted, 0 fired (isolated alert; the mined layer over-predicts on quiet
  alerts — exactly why it's capped). Chaos drill NL↔GR budget — predicted quiet,
  observed quiet (failover worked). Synthetic livecheck pred DELETED from prod evidence
  (count-incidents-not-events lesson: never let synthetics pollute metrics).

## Activation decisions (operator, 2026-06-09)

- **"Active right now":** -1040 gate reframed from *precondition-to-ask* →
  **continuous revocation review** (scorecard `gate_b_to_c.all_met` + PrecisionDrop
  alert + weekly audit can pull authority back). Safe because Phase C grants are
  per-rule operator approval — the safety was designed in from day one.
- **First rule approved: IFRNLLEI01PRD-1046** (nlpve04: hosts nlk8s-ctrl01+n8n01,
  rules Device Down*/KubeAPIDown*/Service up/down*). Verified production-exact
  (`check_phase1b_blast_radius` + real YT-open checker): in-scope → dedup @0.9,
  out-of-scope nl-gpu01 → escalates, old manual -894 confirmed closed/inert.
  **Deactivate = close issue -1046.** The live PVE seeder correctly placed
  n8n01/nlk8s-ctrl01 on nlpve04 — the hand-declared doc still says nl-pve01 (stale; live wins).
- Chaos drills now record their cascade prediction at kill time (chaos-suppressed
  alerts exit tier1 BEFORE Step 2-graph, so the drill must record). Drills evidence
  quiet-cascade + recovery dynamics, NOT alert-set precision; precision evidence comes
  from natural traffic (n≥30 expected within days at current alert rates).

## Remaining (data/operator-gated by design)

- **-1040** review when scorecard `all_met` flips (criteria: ≥30 evaluated/≥14d/≥3
  rules/both sites/precision≥0.95 on conf≥0.8/recall≥0.40/control≤0.5×).
- **-1041** full autonomy widening + **Bridge auto-resolve-on-verdict=match** —
  deliberately behind -1040 (flips authority).
- **-1043** closeout verdict vs the 0.4156 baseline.
- chaos-test.py dict→graph refactor: earliest 2026-07-09 (after 30d edge-parity).
- Cosmetic: update `docs/host-blast-radius.md` n8n01 placement nl-pve01→nlpve04.

## Gotchas worth keeping

- n8n API key lives in `~/.claude.json` under `mcpServers["n8n-mcp"].env` (NOT .env);
  PUT payload = only {name,nodes,connections,settings}; CHAOS_SKIP_TURNSTILE=true for
  CLI drills; `set -a; source .env` (plain source doesn't export); QA gate-extraction
  needs `rindex` (the gate's own removal comment quotes the end marker); SQLite
  bare-column MIN() guarantee voids with a second aggregate (reduce in Python);
  schema.sql G-numbering: infragraph is G15 (G11–G14 taken).
