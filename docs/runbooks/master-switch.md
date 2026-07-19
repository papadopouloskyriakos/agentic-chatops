# Master Power Switch (gateway-master-switch.py)

**Ticket:** IFRNLLEI01PRD-1823 · **Live:** 2026-07-17 · **Host:** nl-claude01 only

One switch to power the **complete agentic system** OFF and back ON, with a tamper-evident
transition ledger. "Off" stops **all autonomous behavior** — alert processing, session dispatch,
autonomous actuation. The platform **skeleton stays alive by design**: Cronicle scheduler, metric
exporters, watchdog heartbeat, and the tier-1 SMS dead-man channel keep running so the off state
is observable and a genuine host failure still pages.

## TL;DR

```bash
cd ~/gitlab/n8n/claude-gateway

# Power OFF (soft): no alerts processed, no autonomous actuation, human lanes stay up
python3 scripts/gateway-master-switch.py off --reason "planned power work" --operator kyriakos

# Power OFF (hard): additionally deactivates the dispatch-lane n8n workflows —
# nothing agentic can run at all, not even human-triggered dispatch
python3 scripts/gateway-master-switch.py off --reason "full stop" --hard --kill-sessions

# Power ON — exact restore of the pre-off state (only what was armed before comes back)
python3 scripts/gateway-master-switch.py on --operator kyriakos

# State + consistency checks (exit 4 = drift detected)
python3 scripts/gateway-master-switch.py status --json

# The power-on/power-off ledger
python3 scripts/gateway-master-switch.py log --n 20
```

Always `--dry-run` first if unsure — it prints the full plan and changes nothing.

## What OFF does (soft, default)

| Step | Plane | Detail |
|---|---|---|
| 1 | Snapshot | Pre-state → `~/gateway-state/master-switch/snapshot-current.json` (+ timestamped archive). This is the restore contract. |
| 2 | Maintenance | Creates `~/gateway.maintenance` with `{"master_switch": true}` marker → all 8 maintenance-aware receivers, chaos drills, network self-healers, watchdog checks, platform-controller heals suppress. A **pre-existing operator maintenance file is preserved untouched**. |
| 3 | Sentinels | Removes the **14 autonomy-arming sentinels** (autonomy_forward, platform_controller_armed, renovate_autonomy, sched_reboot, …). **Guards are NEVER touched** (plan_adherence_*, territory_gate, silent_cognition_guard) and inverted kill-switches (tripwire_off, prompt_promotion_holdout_gate_off) are **NEVER created** — power-off tightens, never loosens. |
| 4 | Cronicle | Disables the **9 ungated actuation jobs** found by the 2026-07-17 audit: requeue-escalations, reconcile-completed-sessions.py, gateway-regen-artifacts-weekly, infragraph-propose-blast-radius.py, ap01-pending-mac-block, crowdsec-learn.sh, finalize-prompt-trials.py, scheduled-reboot-promote, renovate-autonomy-promote. (These would otherwise keep dispatching sessions / mutating YT / auto-merging to main during maintenance.) |
| 5 | `--hard` | Also deactivates the dispatch-lane n8n workflows: YouTrack Receiver, Runner, Matrix Bridge, Progress Poller, Session End, CI Failure Receiver, ChatDevOps CI Resume, Synology DSM Receiver, Teacher Runner. |
| 6 | `--kill-sessions` | TERMs in-flight dispatched claude sessions (`/tmp/claude-pid-*`). Without it, running sessions drain naturally. |

**What keeps running during OFF (deliberate):** Cronicle scheduler + all read-only/metrics jobs,
node_exporter textfile writers, the watchdog heartbeat (platform-controller emits it in
maintenance mode), synthetic canary, alertmanager-twilio-bridge (tier-1 SMS dead-man), Matrix
notification crons (session-digest, teacher nudges), and — in soft mode — the human-interactive
lanes (an operator moving a YT issue or talking to the Bridge can still dispatch; use `--hard`
to prevent that).

## What ON does

Exact restore **from the snapshot**: recreates only the sentinels that existed at off, re-enables
only the Cronicle jobs the switch disabled, re-activates only the n8n workflows it deactivated.
Removes the maintenance file **only if master-switch-owned**, and writes
`~/gateway.maintenance-ended` so the 15-minute post-maintenance cooldown engages (triage
confidence is discounted during the recovery-alert flood).

## Logging (the power-on/power-off record)

Every transition is recorded 4 ways:

1. **Hash-chained ledger** — `master_switch_log` table in gateway.db (migration 028).
   `row_hash = sha256(prev_hash + canonical row)`, same construction as the governance chain.
   Verified on every `status` run; any UPDATE/DELETE of a past row breaks the chain.
   Verify manually: `python3 scripts/lib/master_switch_audit.py verify`.
2. **Append-only JSONL** — `~/logs/claude-gateway/master-switch.log`.
3. **Prometheus** — `master_switch.prom`: `gateway_master_switch_state` (1=on/0=off),
   `_transitions_total`, `_chain_intact`, `_partial_last`, `_last_run_timestamp_seconds`.
   Written on every transition; keep it fresh with the `master-switch-metrics` Cronicle job
   (see Activation below).
4. **Matrix notice** — 🔴/🟢 m.notice to `#infra-nl-prod` on every transition.

## Expected side effects & gotchas

- **`--hard` WILL page**: with the dispatch-lane workflows deactivated, `RegistryCriticalDark`
  (tier-1 SMS) fires after ~15–20 min. This is the dead-man deliberately acknowledging the
  critical plane is dark — expect exactly one page, don't "fix" it.
- **Long windows accrue stale-alert debt** (soft or hard): BudgetBandwidthMetricStale (~25 min),
  ASAShunMetricStale (~40 min), PVEWedgeCollectorStale — their writers are maintenance-gated.
  Multi-day: InfragraphSeedStale, TeacherAgentMorningNudgeStale. All warning-severity.
- **Partial transitions**: exit code 3 + `[PARTIAL]` in the Matrix notice. `status` shows what
  drifted. The **restore baseline is preserved** across retries — a partial `off` keeps the
  original armed set (a `off --force` re-off UNIONs, never shrinks, the snapshot), and a partial
  `on` keeps the recorded state `off` so you can just re-run `on` (no `--force` needed) and it
  reads the same baseline. Fix the failing plane, then re-run. The snapshot is written before any
  mutation AND re-saved with the observed outcome, so restore is always possible.
- **`on` refuses without a snapshot** (exit 2) — it never "restores" a guessed state.
- **Concurrency**: flock-guarded (`~/gateway-state/master-switch/.lock`); a second invocation
  exits 5.
- **Unknown `gateway.*` files** are reported by `status`/`off` as unmanaged — if a new arming
  sentinel is added to the platform, **add it to ARMING_SENTINELS in the script** (and the
  classification tables below), else the master switch won't manage it.
- The switch itself depends on nothing it turns off: pure python + local files; Cronicle/n8n
  planes are API calls with per-item error collection.

## Classification tables (2026-07-17 audit, IFRNLLEI01PRD-1823)

- **ARMING (removed on off, restored on on):** alert_yt_autoclose_armed,
  autoclose_toverify_readonly, autonomy_forward, conservative_remediation,
  cronicle_autoquarantine, disk_autogrow_armed, host_reboot_auto, infragraph_autofold,
  judge_autocalibrate_armed, platform_controller_armed, proactive_remediation,
  renovate_autonomy, renovate_timeout_auto, sched_reboot
- **GUARDS (never touched):** plan_adherence_enforce, plan_adherence_gate,
  silent_cognition_guard, territory_gate
- **NEVER CREATED (inverted kill-switches):** tripwire_off, prompt_promotion_holdout_gate_off
- **DATA (never touched):** gateway.db, gateway.mode, gateway.foldgate-verified,
  gateway.proactive-scan-state.json, gateway.maintenance-ended

## Activation (post-merge, one-time)

The switch reads `.env` (Cronicle/Matrix creds) relative to its repo root, so it MUST run from the
live checkout (`~/gitlab/n8n/claude-gateway`), not a bare worktree. After this MR merges and the
live checkout is synced to it:

1. Confirm it resolves the live planes: `python3 scripts/gateway-master-switch.py off --dry-run
   --reason probe` (should list 14 sentinels, 4 guards, 9 Cronicle jobs — no "missing").
2. Create the metrics-refresh Cronicle job (keeps `master_switch.prom` fresh so a stale/broken
   ledger is visible), via the house `create_event` recipe:
   ```bash
   source .env
   curl -s -X POST "$CRONICLE_URL/api/app/create_event?api_key=$CRONICLE_API_KEY" \
     -H 'Content-Type: application/json' -d '{"title":"master-switch-metrics","enabled":1,
     "category":"gateway","plugin":"shellplug","target":"maingrp","timezone":"UTC",
     "timing":{"minutes":[0,5,10,15,20,25,30,35,40,45,50,55]},
     "params":{"script":"#!/bin/sh\npython3 /app/claude-gateway/scripts/gateway-master-switch.py status --emit-metrics >/dev/null 2>&1","annotate":1,"json":1}}'
   ```
3. (Optional) Add Prometheus alerts on `gateway_master_switch_chain_intact == 0` (tier-1) and
   `time() - gateway_master_switch_last_run_timestamp_seconds > 1200` (dead-man), and register
   `prom:master_switch` in `config/component-registry.json`.

## QA

`scripts/qa/suites/test-1823-master-switch.sh` — 13 hermetic tests (isolated HOME + DB, external
planes skipped). Run: `./scripts/qa/run-qa-suite.sh --filter=1823 --no-bench --no-e2e`.

## Rollback

The switch is additive — to remove it entirely: disable the `master-switch-metrics` Cronicle job,
delete the script + lib; the `master_switch_log` table and logs are inert history. If the switch
misbehaves mid-off, manual recovery = `cat ~/gateway-state/master-switch/snapshot-current.json`
and touch the listed sentinels / re-enable the listed jobs by hand.
