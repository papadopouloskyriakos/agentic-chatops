# Runbook — Synthetic-incident canary (IFRNLLEI01PRD-1154)

## What it is
`scripts/synthetic-incident-canary.sh` (cron `37 2 * * *`, nl-claude01) probes
the **autonomy spine end-to-end**: `classify-session-risk.py` → `infragraph-predict-plan.py`,
asserting each produces its artifact (band + plan_hash from classify; plan_hash +
gate from predict; coherent plan_hash across both). It is the structural defense
against the months-long-silent-dark class (empty plan, missing band, broken gate).

## Why it's safe to run on a cron against production
The spine runs against an **isolated throwaway DB** (`GATEWAY_DB=$(mktemp)`, seeded
from `schema.sql`, deleted via `trap` on exit), **not** the live `gateway.db`. This
structurally eliminates the three top risks:
- **No pollution** — canary rows land in the temp DB, never the real
  `session_risk_audit` / `infragraph_predictions`.
- **No fail-closed-gate collision** — the plan_hash is written to the temp DB only,
  so it can never satisfy a real in-flight session's prediction gate.
- **No real remediation** — no n8n, no real hosts; the plan is read-only (no
  `awx_templates`, no remediation verbs).
A belt-and-suspenders check counts rows in the LIVE db for the `canary-<uuid>`
issue every run and emits `synthetic_incident_canary_live_db_leak` (must be 0).

## Metrics (node_exporter textfile collector)
| metric | meaning |
|---|---|
| `synthetic_incident_canary_stage_ok{stage}` | per-stage 1/0 (classify/predict/verify) |
| `synthetic_incident_canary_stages_passed` | 0-3 |
| `synthetic_incident_canary_live_db_leak` | rows leaked into the live db (must be 0) |
| `synthetic_incident_canary_last_run_timestamp` | freshness |

## Alerts (IaC `agentic-health-alerts.tf`)
- **`SyntheticCanaryLeak`** (`> 0`, tier1+critical → **SMS**) — isolation broke; disable the cron and fix.
- **`SyntheticCanaryFailing`** (`stages_passed < 3` for 6h, warning) — spine degraded.
- **`SyntheticCanaryStale`** (`>48h` or `absent()`, warning) — cron not firing.

## You got paged / want to check
```bash
ssh nl-claude01
bash ~/gitlab/n8n/claude-gateway/scripts/synthetic-incident-canary.sh --verbose   # one run, see each stage
cat /var/lib/node_exporter/textfile_collector/synthetic_canary.prom
tail -40 ~/logs/claude-gateway/synthetic-canary.log
```
- **Leak > 0:** the isolation regressed — a code change pointed the spine at the
  real DB. Disable the cron (`crontab -e`), inspect the script's `GATEWAY_DB`/`--db`
  wiring, re-prove leak=0 with `--verbose`, re-enable.
- **stages_passed < 3:** read the `--verbose` output — which stage failed.
  `classify=0` → classify-session-risk.py crashed / emitted no band (check the
  pipeline-debug.log `_dbg` invoke line). `predict=0` → infragraph-predict-plan.py
  failed. `verify=0` → plan_hash mismatch between the two (a plan_hash_of() drift).

## Rollback / disable
`crontab -e`, comment the `synthetic-incident-canary.sh` line. The script is
read-only against production (isolated DB), so disabling is purely cosmetic — but
it's the documented kill switch. Drop the 4 alerts from the IaC file to fully revert.

## Design notes
Full build notes + why the map's 600-line n8n-driving design was rejected for the
isolated-DB approach: `memory/synthetic_canary_20260621.md`.
