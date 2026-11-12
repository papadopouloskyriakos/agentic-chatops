# Renovate MR Autonomy lane (IFRNLLEI01PRD-1645)

Extends the autonomy-forward gate (human-as-circuit-breaker) to a new trigger lane: when the
self-hosted Renovate bot (`renovate-bot`, NL GitLab user 44) opens a merge request, triage it
through a dependency-aware risk/reversibility gate and — if every required gate passes — **autonomously
merge it**. Ships **DARK**: nothing acts until `~/gateway.renovate_autonomy` exists AND the n8n workflow
is active AND the GitLab webhook is registered. Operator posture (2026-07-06): *everything that passes
review* auto-merges, but the gates scale with blast radius and stateful bumps are hard-blocked on a
verified restore point.

## Pipeline
```
Renovate opens MR → GitLab merge_request webhook → n8n "NL - Renovate MR Autonomy"
  → SSH: scripts/renovate-mr-gate.sh --event-json -
      parse+filter (renovate-bot ∧ state=opened ∧ target=main)
      → classify   (classify-renovate-mr.py: {package,updateType,statefulness} → tier; UNKNOWN→critical, fail closed)
      → gate 1  CI pipeline == success                                             (hard)
      → gate 2  mr-review.sh verdict==APPROVE at the tier's confidence threshold    (hard)
      → gate 3  renovate-presnapshot.sh: create+VERIFY (+ rehearse) a restore point (critical/stateful only)
      → decide  AUTO (all gates ∧ ¬never_auto) | POLL | SKIP
      → act (live only):
          rollout gate      renovate-rollout.py — tier enabled at this stage? under daily cap? (else POLL/HOLD)
          INDEP. floor      lib/renovate_floor.py re-checks the floor (policy ⟂ decider); merge only if ALLOW
          merge             PUT with sha=<reviewed head> (server-side TOCTOU close)
          post-merge        nohup renovate-postmerge-verify.sh → health-poll → AUTO-REVERT on failure + page
          POLL              renovate-escalate.py → MR comment + SMS (/alert-session) + Matrix
      → audit   append THROUGH lib/renovate_audit.py (SHA-256 hash chain — tamper-evident)
```

## Tiers (config/renovate-stateful-services.json — data-driven)
| tier | what | gates | can auto-merge? |
|---|---|---|---|
| routine | stateless patch/minor/digest | CI-green + review APPROVE (τ 0.80) | yes |
| elevated | stateless **major** / Renovate config change | + hardened review (τ 0.90), no snapshot | yes |
| critical | **any** bump of a stateful service (DB/broker/vector/object store, app-with-DB) | + **verified snapshot** | only with a verified restore point |

## Snapshot method (grounded 2026-07-06)
Only 2 of 20 stateful docker guests can `pct/qm snapshot` (influxdb01 ZFS-subvol, gpu01 qcow2); the rest
are `raw-on-dir`/`nfs` with no snapshot feature. So `renovate-presnapshot.sh` takes **per-engine logical
dumps via `docker exec`** on the target guest, and **verifies** them (fail-closed). The remote worker is
shipped as one base64 blob (injection/quoting-safe) so artifacts are taken *and verified on the guest*.
Bespoke logical dumps: postgres/pgvector/timescale, mariadb/mysql, mongo, redis/valkey, actualbudget,
**meilisearch** (tar of `/meili_data`), **milvus** (verified etcd snapshot + MinIO/milvus data tar),
**etcd** (verified `etcdctl snapshot`). **Postgres additionally gets a RESTORE-REHEARSAL** — the dump is
restored into a throwaway container of the same image and smoke-queried (`SELECT 1`) before the restore
point is accepted (a *tested* restore, not just an integrity check); gated by `RENOVATE_RESTORE_REHEARSAL`
+ a size cap, fail-closed. **Every other stateful engine** (elasticsearch/opensearch, clickhouse, influxdb,
qdrant/weaviate, cassandra, rabbitmq, minio, apps-with-embedded-DB, …) → a **generic verified data-volume
tar** taken with the container **paused** (cgroup-freezer, then unpaused) so the copy is *consistent*, not
torn; bespoke dumps are preferred where a logical dump is cleaner. **`openbao`/`vault` → always POLL**
(secret-store migration is near-irreversible) — also flagged `never_auto` at the classifier layer.

**Automated post-merge rollback** (`renovate-postmerge-verify.sh`, launched async after each live
auto-merge): waits for the docker-plane redeploy, polls the affected container's health for a window, and
on failure **auto-reverts the deploy** (GitLab revert API on `main` → CI redeploys the OLD image) and
pages the operator. For a stateful bump the DB *data* restore is NOT auto-applied (auto-restoring prod
data is itself high-risk) — the operator is paged with the `RESTORE_CMD`. Automate the reversible part;
escalate the irreversible-data part.

## Safety properties (enforced + tested) — mapped to the no-human-in-loop standards
- **Fail closed everywhere:** shadow by default; any error/missing signal → POLL. UNKNOWN statefulness →
  critical+snapshot (an unlisted DB never slips through as routine). `never_auto` engines (openbao/vault)
  always POLL — enforced at the classifier AND the snapshot mechanism.
- **Independent enforcement:** the AUTO-merge floor lives in `lib/renovate_floor.py` (policy), and the gate
  re-checks it independently before merging (a bug in the decider can't merge out of policy). The merge PUT
  pins the exact reviewed `sha` so GitLab rejects it server-side if Renovate pushed a new commit (TOCTOU).
- **Verified + automated rollback:** critical/stateful cannot AUTO without a *verified* snapshot (postgres
  gets a real restore-rehearsal; generic tars are taken with the container paused). After a live merge,
  `renovate-postmerge-verify.sh` health-checks the service and **auto-reverts the deploy** on failure + pages.
- **Human as circuit-breaker, not gatekeeper:** a POLL actually pages (`renovate-escalate.py` → MR comment +
  SMS + Matrix, deduped); kill switch `rm ~/gateway.renovate_autonomy`.
- **Staged rollout:** arming starts a CANARY (routine-only, few/day, `config/renovate-autonomy-rollout.json`);
  `renovate-autonomy-promote.py` widens scope only on clean data (N auto-merges, 0 rollbacks, M days) and
  demotes on a rollback. Not all-tiers-at-once.
- **Tamper-evident ledger + zero-invariant:** every decision appends through a SHA-256 hash chain
  (`lib/renovate_audit.py`); an edited/deleted row breaks it → `renovate_autonomy_chain_ok=0`
  (`RenovateAuditChainBroken` tier-1). Invariant `renovate_autonomy_merged_without_snapshot_total==0`
  (`RenovateMergedWithoutSnapshot` tier-1) + weekly `audit-renovate-decisions.sh`.
- **Tests (all hermetic):** classifier 16 · gate 20 · presnapshot 19 · enforcement 14 · rollout 10 · observability 12 = **91 checks**.

## Go-live sequence (deliberate, reversible at every step)
1. **Import the workflow** (`workflows/claude-gateway-renovate-mr-autonomy.json`) into n8n via n8n-mcp
   `n8n_create_workflow` / `n8n_update_full_workflow` (an interactive session where the MCP can reach the
   instance — headless MCP hits SSRF on the private IP `10.0.X.X`), or the n8n UI import. It is created **inactive**.
2. **Shadow-bake:** activate the workflow (webhook registers at `https://n8n.example.net/webhook/gitlab-mr`),
   register the GitLab hook, but LEAVE the sentinel off → the gate runs on every real MR and audits its
   *would-decide* while merging nothing. Watch `renovate_autonomy_decisions_total` for ≥1–2 weeks.
3. **Register the GitLab webhook** (merge_request only) on project 30:
   ```
   curl -sS -X POST -H "PRIVATE-TOKEN: $GITLAB_TOKEN" -H "Content-Type: application/json" \
     https://gitlab.example.net/api/v4/projects/30/hooks \
     -d '{"url":"https://n8n.example.net/webhook/gitlab-mr","merge_requests_events":true,
          "push_events":false,"tag_push_events":false,"issues_events":false,"note_events":false,
          "pipeline_events":false,"job_events":false,"deployment_events":false,"releases_events":false,
          "wiki_page_events":false,"enable_ssl_verification":true,"token":"'"$GITLAB_WEBHOOK_SECRET"'"}'
   ```
   Enforce the secret: add Header Auth (or an IF on `{{ $json.headers['x-gitlab-token'] }}`) on the webhook node.
4. **Arm (starts a CANARY, not full-live):** `touch ~/gateway.renovate_autonomy`. Per
   `config/renovate-autonomy-rollout.json` the lane begins at stage `canary` = **routine tier only, ≤3
   auto-merges/day**; elevated/critical still POLL to you. `renovate-autonomy-promote.py` (weekly) widens
   scope canary→expand→full on clean data and demotes on any rollback. `RenovateAutonomyShadowStillOn` (14d) nudges arming.
5. Register the Cronicle jobs:
   `*/5 * * * * scripts/write-renovate-autonomy-metrics.py` (metrics + chain-verify) ·
   `25 5 * * 1 scripts/write-renovate-audit-metrics.sh` (weekly floor-invariant + chain → `renovate_autonomy_audit_fail`/`_chain_broken`) ·
   `40 5 * * 1 scripts/renovate-autonomy-promote.py --apply` (data-driven stage promotion — writes the
   mutable stage/clock to `~/gateway-state/renovate-rollout-state.json`, NOT the git-tracked config, so a
   drift-sync can't reset the stage). Run
   `write-renovate-audit-metrics.sh` once on deploy so `RenovateAutonomyAuditStale` doesn't fire on the gap.
   Register `prom:renovate_autonomy_metrics` (critical) in the component registry for a dead-man.
6. Deploy `prometheus/alert-rules/renovate-autonomy.yml` in-cluster as a PrometheusRule via IaC.
7. **Recommended out-of-band control:** add a GitLab branch-protection / approval rule on `main` of project 30
   so no in-script bug can merge without the server-side gate — defense in depth beyond `renovate_floor.py`.

## Timeout-to-auto (2026-07-07) — silence ≠ veto, for reversible bumps

The operator is not reachable via Matrix/SMS, so a POLL on a REVERSIBLE stateful/elevated bump would
stall forever (the anti-pattern the autonomy-forward gate killed on the incident side). Instead:

- **Eligible** (single source of truth, `scripts/lib/renovate_deferred.py::eligible`): NOT `never_auto`
  ∧ tier `critical`/`elevated` ∧ reversible `update_type` (minor/patch/digest/lockfile). A **POLL** on an
  eligible MR **records a deferred entry** (`renovate_deferred_merges`, migration 025) with a grace
  deadline (config `timeout_auto.grace_hours`, default 48h) and posts **one passive MR comment** (no SMS).
- `scripts/renovate-deferred-merge-processor.py` (Cronicle, hourly) picks up entries past their deadline,
  resolves terminal states cheaply (MR closed/merged/rebased/vetoed), enforces `daily_cap`, and for the
  rest **re-invokes the gate with `RENOVATE_DEFERRED_ELAPSED=1`** — which overrides ONLY the rollout-stage
  POLL and lets the merge proceed through the **same** path: fresh tested snapshot + independent floor +
  sha-pin + post-merge auto-rollback. Every other safety gate is unchanged.
- **NEVER timeout-auto'd:** `never_auto` engines (openbao/vault) and **MAJOR** (data-migrating) bumps —
  they escalate/park for an explicit decision.
- **Veto** (human as break-glass): add the `timeout_auto.veto_label` (`renovate-hold`) label to the MR, or
  close it. Checked at record-time AND at merge-time.
- **Gated behind BOTH** `~/gateway.renovate_autonomy` AND `~/gateway.renovate_timeout_auto`. Either absent
  = **byte-identical legacy** (POLL forever). `touch ~/gateway.renovate_timeout_auto` = on; `rm` = off.
- **Pull-review surface:** `scripts/renovate-pending.py` prints SCHEDULED (auto-merging, veto to stop) vs
  PARKED (needs an explicit decision) — surfaced in-session instead of pushing pages nobody reads.
- **Metrics:** `renovate_deferred_pending` / `_overdue` (processor dead-man) / `_status_total{status}` /
  `renovate_timeout_auto_enabled` (write-renovate-autonomy-metrics.py). Tests: `test-renovate-timeout-auto.sh` (22).

## Rollback / freeze
- **Instant freeze:** `rm ~/gateway.renovate_autonomy` → back to shadow (audits, merges nothing), byte-identical.
- **Narrow scope:** edit `config/renovate-autonomy-rollout.json` `enabled_tiers`/`max_auto_merges_per_day`
  (or the promoter auto-demotes on a rollback). Deactivate the n8n workflow / delete the GitLab hook to stop entirely.
- A merged bump that broke a service is **auto-reverted** by `renovate-postmerge-verify.sh` (deploy revert +
  page). For a stateful bump the DB *data* restore is held for the operator — run the `RESTORE_CMD` from the page.

## Scope boundary (by design)
Covers only the **pinned-tag Renovate plane**. `:latest` images are updated by **watchtower** (75 compose
files) with no Renovate MR — this lane never sees them.

## Hardening 2026-07-07 (go-live + adversarial-verification sweep — supersedes stale bits above)
The lane went live (canary, routine-only) and an 8-agent adversarial verification found + closed real gaps.
Full detail: [`memory/renovate_autonomous_mission_20260707.md`](../../memory/renovate_autonomous_mission_20260707.md)
+ [`memory/renovate_epic_followups_batch_20260707.md`](../../memory/renovate_epic_followups_batch_20260707.md). Changes to the pipeline above:

- **Routine review is now DETERMINISTIC, not the Claude review.** `renovate-mr-gate.sh` routes **routine → `renovate-structural-review.py`** (APPROVE @0.96 iff every hunk is a pure version/tag/digest edit in a manifest — fail-closed); elevated/critical still go to `mr-review.sh`. Reason: the Claude review returned EMPTY in the n8n SSH context → nothing ever auto-merged. The structural regex only treats a bare integer as a version when it is a **docker tag** (`redis:8`, immediately after `:`), so numeric config edits (`replicas: 2→5`, ports) are REQUEST_CHANGES.
- **CI-timing catch-up = `renovate-reconcile.sh`** (Cronicle `renovate-reconcile` id `emratzydyel`, `*/15`). GitLab doesn't re-fire the MR webhook when CI goes green, so the reconciler re-feeds open green-CI renovate-bot MRs (by AUTHOR, not just the `renovate` label) through the same gate. A **rate-cap hold now un-marks the dedup** so the next tick retries once daily budget frees (was one-shot-per-SHA → stalled forever).
- **`never_auto` now also covers:** any Atlantis-managed MR (helm/terraform/k8s or `[INFRA]` title → rebase+plan-review+canary, never auto-applied) **and any Dockerfile-manager MR** (`dockerfile_needs_review`, default true — a Dockerfile bump needs a `build`, but deploy_docker only `pull`s, so it never deploys AND postmerge false-PASSes on the old-image container; POLL for human rebuild+review). CNI/ingress add an `atlantis_canary` gate.
- **Post-merge is now 3-way, never a blind revert.** `renovate-postmerge-verify.sh` health-checks the affected container by **host+service derived from the PATH** (`docker/<host>/<svc>/…` OR `edge/dmz/<host>/<svc>/…`; the service is the dir, NOT the bumped package — a Dockerfile `uv` bump health-checks `librechat`). Outcomes: found+healthy→OK; found+unhealthy→auto-revert (stateless) / hold-for-operator (stateful); **container NEVER located → INCONCLUSIVE → escalate, NOT revert** (broadening host-detection can't spuriously auto-revert a good deploy). `images/<x>` CI base images → no host → skipped.
- **Docker-tag MAJORs re-detected from the diff** (`redis 7.x→8.x` carries no `major-update` label) → parked, not timeout-auto'd.
- **Daily cap excludes synthetic test rows** (`mr_iid ≥ 9000`) so a stub can't steal real canary budget (the `renovate-rollout.py` counter uses `CAST(COALESCE(mr_iid,'0') AS INT) < 9000`).
- **Alerts:** `RenovateAutonomyFloorBreach` (tier-1, `merged_without_snapshot_total > 0`) + `RenovateAutonomyMetricsStale` (writer dead-man) in `prometheus/alert-rules/agentic-health.yml`. The lane's 8 components (reconciler, promote, deferred-processor, metric writers, n8n workflow, audit table, prom writers) are registered in the orchestrator's `config/component-registry.json`.
- MRs: gateway !160/!161/!163/!166/!167/!168. Tests: `test-renovate-{classifier,structural-review,rollout,mr-gate,timeout-auto,postmerge}` all green.
