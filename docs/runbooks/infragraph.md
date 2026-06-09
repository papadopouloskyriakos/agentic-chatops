# Runbook: Infragraph — Causal Infra Dependency Graph

**Runbook ID:** RB-IG-001
**Last Updated:** 2026-06-09
**Epic:** IFRNLLEI01PRD-1029 · Plan of record: [`docs/plans/infragraph-implementation-plan.md`](../plans/infragraph-implementation-plan.md)

---

## 1. Overview

One queryable causal graph of the infrastructure (356 nodes / 414 edges at
deploy): topology from PVE cluster API + NetBox (devices, cables) + LibreNMS
dependency parents + the chaos `TUNNEL_GRAPH_EDGE` + operator declarations in
[`docs/host-blast-radius.md`](../host-blast-radius.md); dynamics (expected
cascades, delays, recovery times) learned from `chaos_experiments` and
triage.log co-occurrence. Lives in the G10/G15 tables of
`~/gitlab/products/cubeos/claude-context/gateway.db`.

Consumers: `infra-triage.sh` Step 2-graph (advisory context, fails open),
`classify-session-risk.py` (`infragraph:blast-radius-high(N)` — raises risk
only). Phase B/C consumers per the plan of record.

## 2. Query cheatsheet

```bash
cd ~/gitlab/n8n/claude-gateway
python3 scripts/infragraph-query.py health                                  # counts, freshness, P/R
python3 scripts/infragraph-query.py blast-radius --host nl-pve03        # who is affected
python3 scripts/infragraph-query.py deps --host nl-gpu01                # what it needs
python3 scripts/infragraph-query.py cascade --host nl-pve01 --rule "Device Down"
python3 scripts/infragraph-query.py explain --from ollama --to nl-pve03
```
<!-- VALIDATE: health exit 0 AND nodes_total >= 100 -->

## 3. Reseed / relearn (manual)

```bash
python3 scripts/infragraph-seed.py --all          # 5 sources; per-source isolation; exit 1 if any failed
python3 scripts/infragraph-learn.py --from-chaos --from-incidents
python3 scripts/infragraph-eval.py --replay 2026-05-11   # read-only sanity backtest
```
Cron (nl-claude01): seed `10 4 * * *`, learn `25 * * * *`. Logs:
`~/logs/claude-gateway/infragraph-{seed,learn}.log`.
<!-- VALIDATE: infragraph_last_seed_timestamp{source} within 26h for pve/netbox/librenms -->

## 4. Alert response

| Alert | Meaning | First moves |
|---|---|---|
| `InfragraphMetricsExporterStale` | `write-infragraph-metrics.py` cron wedged | `crontab -l`; run the script manually; check `/var/lib/node_exporter/textfile_collector/infragraph.prom` |
| `InfragraphSeedStale` | a seed source >36h behind (daily cron failed twice or upstream API down) | run `infragraph-seed.py --all`, read stderr per-source; NetBox/LibreNMS reachable? Automated edges self-expire after 7d so predictions degrade visibly (stale_edges), never silently |
| `InfragraphPrecisionDrop` | Phase B shadow precision <0.80/30d | topology changed without reseed, or stale dynamics; inspect `test-results/infragraph-scorecard.json`; HOLD the -1040 B→C gate until resolved |

## 5. Kill-switch / rollback (per phase)

- **Advisory (Phase A):** `export INFRAGRAPH_DISABLED=1` in the triage
  environment (or set it in the receivers' SSH command) — Step 2-graph and the
  risk-classifier signal vanish; triage behaves exactly pre-infragraph.
  Remediation lane consequence (once -1044 lands): INFRAGRAPH_DISABLED =
  **analysis-only mode** — remediation proposals are disabled entirely, per
  the model-based invariant. Never "remediation without predictions".
- **Phase B:** remove `--record` from Step 2-graph + comment the eval cron;
  `infragraph_predictions` is append-only and inert.
- **Phase C:** close infragraph-generated blast-radius control issues (instant
  Phase 1b deactivation); belt-and-braces:
  `DELETE FROM openclaw_memory WHERE category='blast-radius' AND value LIKE '%generated_by%infragraph%'`.

## 6. Improving coverage (operator levers)

The 2026-05-11 backtest's residual misses are GR hosts whose monitoring-path
topology exists in no machine-readable source. Any of these raises coverage:

1. **LibreNMS dependency parents** (best ROI — also improves LibreNMS's own
   alert suppression): Device → Edit → Device Dependencies. Seeder picks them
   up at the next 04:10 run.
2. **NetBox cables**: document switch ports; the netbox seeder derives
   `depends_on` edges from cable terminations.
3. **Declared rows** in `docs/host-blast-radius.md` (MR-reviewed).

## 7. Invariants to respect when extending

- Edge direction: SOURCE depends on TARGET.
- Writers that only know a hostname MUST use `infragraph.resolve_entity()` —
  a wrong-typed twin node is invisible to traversal.
- Incident-mined confidence caps at 0.75 — below the 0.8 Phase-C suppression
  eligibility cutoff, by design.
- All triage-path consumers fail OPEN; the (future) remediation gate fails
  CLOSED. Don't blur the two lanes.
- `infragraph_predictions.verdict` is written ONLY by `infragraph-verify.py`
  (mechanical adjudication — the LLM never judges its own outcome).
