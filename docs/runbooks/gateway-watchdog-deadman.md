# Runbook — Gateway control-plane dead-man's-switch (IFRNLLEI01PRD-1152)

## What this is
`scripts/gateway-watchdog.sh` (cron `*/5` on `nl-claude01`) watches the 9 n8n
alert receivers + the runner, auto-heals (reactivates workflows, restarts n8n,
kills zombie executions, clears stale locks), and posts to Matrix `#alerts`.

The problem it never solved for itself: **nothing watched the watchdog.** If its
cron, host, `node_exporter`, or the script wedged, everything went silently dark —
and its Matrix alerts are muted by the operator anyway. This dead-man's-switch
closes that gap.

## How it works
On **every** run (via a `trap emit_metrics EXIT`, so it fires on the maintenance,
n8n-down, normal, and `set -e`-abort paths alike) the watchdog writes to
`/var/lib/node_exporter/textfile_collector/gateway_watchdog.prom`:

| metric | meaning |
|---|---|
| `gateway_watchdog_heartbeat_timestamp_seconds{host}` | unix time the watchdog last ran (the heartbeat) |
| `gateway_n8n_healthy` | 1/0 from the `/healthz` check |
| `gateway_workflow_active{workflow}` | 1/0 per workflow, recorded **as found** (pre-reactivation) |

Two Prometheus alerts (deployed truth:
`infrastructure/nl/production/k8s/namespaces/monitoring/agentic-health-alerts.tf`;
doc/test copy: `prometheus/alert-rules/agentic-health.yml`), both
`tier=1 + severity=critical` → **`twilio-tier1` SMS** (and Matrix via `continue=true`):

- **`GatewayWatchdogHeartbeatStale`** — `(time() - heartbeat > 900) OR absent(heartbeat)`, `for: 5m`.
  The `absent()` clause is the crux: a plain staleness expr returns *no series* when
  `node_exporter`/`claude01` is down, so "no data" would otherwise = "no alert" — the
  exact silent-dark failure this exists to kill.
- **`GatewayWorkflowInactive`** — `min by (workflow) (gateway_workflow_active) == 0`, `for: 15m`.
  A workflow stayed inactive across ≥3 watchdog runs → auto-reactivation isn't holding.

> ⚠ Do **not** rename these to `Watchdog` — `main.tf` black-holes `alertname=Watchdog`
> (the Prometheus stock heartbeat) to `receiver=null`.

## You got paged: `GatewayWatchdogHeartbeatStale`
```bash
ssh nl-claude01
crontab -l | grep gateway-watchdog          # cron present?  (expect the */5 line)
tail -30 ~/scripts/watchdog-state/watchdog.log
cat /var/lib/node_exporter/textfile_collector/gateway_watchdog.prom   # fresh ts?
systemctl is-active node_exporter || pgrep -fa node_exporter          # exporter up?
bash ~/scripts/gateway-watchdog.sh           # run one cycle by hand; watch for errors
```
Likely causes: cron removed/disabled; `claude01` LXC down or under memory pressure
(see CLAUDE.md "Known Host Pressure: nl-pve01"); `node_exporter` dead; the script
erroring before the trap (check `set -e` abort in the log). If the metric is fresh
but the alert fired, check Prometheus scrape of the textfile collector.

## You got paged: `GatewayWorkflowInactive`
The named workflow keeps going inactive despite reactivation. Open it in the n8n UI
(`https://n8n.example.net`): a Code-node error on activation, a deleted
workflow, or n8n rejecting activation. Cross-check `~/scripts/watchdog-state/watchdog.log`
for the repeated "INACTIVE, reactivating..." lines.

## Verify / smoke-test
```bash
# fresh heartbeat (age should be < 300s on a healthy host)
python3 - <<'PY'
import time,re
t=open('/var/lib/node_exporter/textfile_collector/gateway_watchdog.prom').read()
m=re.search(r'heartbeat_timestamp_seconds\{[^}]*\}\s+(\d+)',t); print('age',int(time.time())-int(m.group(1)))
PY
# holistic structural guard
./scripts/holistic-agentic-health.sh 2>/dev/null | grep watchdog-deadman
# fault-injection smoke test (do in a maintenance window): stop the cron ~20 min,
# confirm GatewayWatchdogHeartbeatStale fires + SMS arrives, restore cron, confirm resolve.
```

## Rollback
`scripts/gateway-watchdog.sh` is additive (a trap + gauge records; existing heal
logic untouched). To revert: restore the pre-I1 backup on the host
(`~/scripts/gateway-watchdog.sh.pre-i1-*`) and drop the two alert rules from the IaC
file. The metric file is harmless if left.

## History
The receiver-canary (synthetic YT issues every 30 min) was retired 2026-04-30
(commit `2c4af83`) as cutover-only noise. This is **not** a canary revival — it adds
no synthetic load; it passively records that the already-running watchdog executed,
and pages out-of-band when it stops. Full design + the live-vs-repo drift caught
during build: `memory/watchdog_deadman_20260621.md`.
