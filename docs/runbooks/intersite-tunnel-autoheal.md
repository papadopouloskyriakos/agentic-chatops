# Intersite tunnel auto-heal — the 3-layer wedged-SA response (IFRNLLEI01PRD-1833)

**Built 2026-08-14**, after the 5th NL↔GR partition. Detection was already proven
(`IntersiteBGPLegDown` created YT -2338 one minute after the Freedom leg died on 08-12) —
what was missing was a consumer: the issue sat Open for 34 h, and the pre-existing light
healer `vti-freedom-recovery.sh` was **shadow-suppressed the whole time** (MUTATIONS=OFF
since 07-18; its shadow log shows `would actuate` from 23:51Z on, every 3 min). This
runbook documents the three response layers, their switches, and the drill procedure.

## The layers

| Layer | Component | Trigger | Action | Latency |
|---|---|---|---|---|
| 0 | `scripts/vti-freedom-recovery.sh` (Cronicle `emqurqyc45l`, */3) · `scripts/vti-budget-recovery.sh` (`emqurqyiw6i`, */3) | device-local: WAN up + VTI up + BGP not Established | light `clear crypto ipsec sa peer` (child-SA renegotiation) on nl-fw01 / nlrtr01 | ~3 min |
| 1 | **On-device** nlrtr01: `ip sla 10` (icmp to 10.255.200.X via Tunnel1, 30 s) → `track 10` (delay down 90/up 30) → EEM applet `INTERSITE-BUDGET-LEG-HEAL` | data-path probe dead 90 s | `clear crypto session remote 203.0.113.X` (full IKE re-init + INITIAL_CONTACT flushes GR's stale SAs) | ~90 s |
| 2 | `scripts/intersite-tunnel-heal.py`, invoked by `bgp-mesh-watchdog.sh` (Cronicle `emqurqyj26j`, */5) after the metrics publish | an intersite leg down ≥2 consecutive watchdog runs (≥10 min = L0/L1 already failed) + wedge signature | **full both-ends runbook re-key** per leg: GR ASA `vpn-sessiondb logoff tunnel-group <leg peer> noconfirm` + `clear crypto ipsec sa peer` (via the :2222 stone), NL device logoff/clear — all netmiko | ~10–12 min |

Layer 1 is edge-triggered — one clear per track down-transition, so a hard GR outage
produces exactly one harmless clear, never a storm. Layer 2's wedge signature requires
**GR's public IP to answer plain-internet ping** (site up = wedge; site dark = outage →
escalate, don't clear) and **frozen decaps across two 20 s samples** (or *no SA data*,
the 08-08 variant). Rising decaps = not wedged = no action.

## Switches

| Switch | Effect |
|---|---|
| `~/gateway.intersite_autoheal_armed` | arms Layer 2 (registered in `gateway-master-switch.py` ARMING_SENTINELS — master-off removes it). `rm` = Layer 2 analysis-only. |
| `~/gateway.mutations_intersite_allow` | the **intersite exemption lane** through global MUTATIONS=OFF shadow (TG-lane pattern). Lets Layers 0+2 act while the estate stays in shadow; every admitted actuation is audited to `~/logs/claude-gateway/mutation-shadow/intersite-exempt-allows.log`. `rm` = whole lane back to log-only. |
| `mutation-mode.py on` | global shadow off — the exemption sentinel becomes moot; arming still governs Layer 2. |
| rtr01 rollback | `no event manager applet INTERSITE-BUDGET-LEG-HEAL` · `no track 10` · `no ip sla schedule 10` · `no ip sla 10` |

Backoff/escalation (Layer 2, platform-controller pattern): per-leg exponential cooldown
600 s → 3600 s, **3 heals without lasting recovery → ESCALATE** (Matrix critical +
`intersite_autoheal_escalations_total`) and no further attempts in the window.

## Observability

- `intersite_autoheal.prom` (textfile): `armed`, per-leg `attempts_total` / `success_total` /
  `last_result`, `escalations_total`, `last_run_timestamp` — written every watchdog cycle.
- Alerts (`prometheus/alert-rules/intersite-autoheal.yml`, deployed via the monitoring
  namespace tf): `IntersiteAutohealFailed` (critical), `IntersiteAutohealEscalated`
  (critical), `IntersiteAutohealStale` (warning, only while armed).
- Audit trail: `~/logs/claude-gateway/intersite-heal.log` + Matrix `m.notice` to
  `#infra-nl-prod` on every actuation/escalation + the exemption audit log.
- rtr01 Layer 1 leaves `INTERSITE-HEAL:` syslog lines (forwarded to syslog-ng).

## Manual CLI

```bash
cd ~/gitlab/n8n/claude-gateway
python3 scripts/intersite-tunnel-heal.py --check --live      # decision, no action
python3 scripts/intersite-tunnel-heal.py --heal freedom      # gated heal
python3 scripts/intersite-tunnel-heal.py --drill-force budget # drill: bypass gates, verify, report
```

## Drill procedure (run after any change to this lane)

1. Preflight: `bgp_mesh_established_count` 52/52; both legs Established.
2. Layer 1 action: twin applet `event none` + `event manager run` → session bounces,
   BGP `10.255.200.X` back ≤2 min. Remove twin.
3. Layer 1 trigger: repoint `ip sla 10` at a dead 10.255.200.x → track down ~90 s →
   applet fires once → restore target.
4. Layer 2: `--drill-force budget` then `--drill-force freedom` (each ≤10 min so
   `IntersiteBGPLegDown` never fires; the other leg carries traffic).
5. QA: `scripts/qa/suites/test-intersite-autoheal.sh` green; negative check: healthy
   mesh + everything armed → two watchdog cycles with zero actuations.

First full drill: 2026-08-14 (all stages, both legs). QA suite: `test-intersite-autoheal.sh`.
Related: `edge/CLAUDE.md § Total NL↔GR partition` (the manual runbook Layer 2 automates),
`memory/intersite_partition_both_legs_20260814`.
