# Freedom ONT auto-heal — PoE cycle for a powered-but-dark ONT (IFRNLLEI01PRD-2992)

**Built 2026-11-07**, from the NL house power-loss postmortem (MR !284). After mains
returned on 2026-11-06 the Genexis XGS-PON ONT came back **powered but dark**: nl-sw01
Gi1/0/36 ("Connection to Freedom Internet") stayed `notconnect` with PoE on (15.4 W) for
8 h, Freedom PPPoE stayed down, and Budget (nlrtr01 Dialer1) carried everything. Nothing
detected the wedge, and nothing would have fixed it. The fix that worked
(2026-11-07 11:59 NL) is the recipe below: link up in 10 s, PPPoE + nl-fw01 Track 1 Up
about 98 s later.

```
interface GigabitEthernet1/0/36
 power inline never
 ! wait 15 s
 power inline auto
 shutdown
 no shutdown
```

`power inline auto` is the port default, so the running config is unchanged afterwards
(nothing to `write memory`).

## What it is

`scripts/freedom-ont-heal.py`, Cronicle job `freedom-ont-heal` (*/2, category gateway). Each
run reads three `show` commands on nl-sw01 and `show track 1` + `show ip address
outside_freedom` on nl-fw01 (netmiko only), classifies, writes
`freedom_ont_autoheal.prom`, and acts only when every gate below opens.

**Signature ("wedged")**, all of:

- Gi1/0/36 status `notconnect` (not `disabled`: an admin-shut port is a drill or a human, not this class);
- `show power inline` Admin `auto`, Oper `on` (powered);
- the port description still names Freedom (a re-patched port is never cycled);
- nl-fw01 Track 1 is confirmed **Down**. Track 1 Up while the port is down means we are
  looking at the wrong port, so the heal never acts. If nl-fw01 cannot be read the state is
  `unconfirmed`: `freedom_ont_autoheal_wedged` is still 1 (so `FreedomOntWedged` fires) but the
  heal does not act and the streak holds (fail closed).

## Gates, in order

| # | Gate | Effect |
|---|---|---|
| 1 | flock singleton | an overlapping run exits 0 (a heal + verify takes up to ~6 min) |
| 2 | signature on ≥ 2 consecutive runs spanning ≥ 240 s, and ≥ 2 of them with every gate open | transient boot/training windows are ignored; when a gate lifts (maintenance window ends, sentinel created) the heal needs 2 fresh un-gated runs instead of acting at once on a streak built while gated |
| 3 | a real maintenance window (`~/gateway.maintenance` **without** `"master_switch": true`) or `~/chaos-state/chaos-active.json` | suppressed. The master-switch marker does **not** block this heal (see below). A maintenance file that is not valid JSON, or whose marker is not boolean `true`, counts as a real window (fail closed). The Freedom-ONT chaos drill shuts the port (`disabled`) **and** sets the marker, so the two never fight. |
| 4 | MUTATIONS=OFF shadow (`~/gateway.mutations_off`) | suppressed unless the lane sentinel `~/gateway.mutations_freedom_ont_allow` exists; every admitted actuation is audited to `~/logs/claude-gateway/mutation-shadow/freedom_ont-exempt-allows.log`. The would-have-acted line goes to the shadow log once per episode. |
| 5 | arming sentinel `~/gateway.freedom_ont_autoheal_armed` | absent = analysis-only (detection + metrics only) |
| 6 | cap | max **3 attempts per rolling 24 h**, exponential backoff 10 min → 20 min between them. The attempt is written to the state file **before** the PoE cycle; an unreadable state file refuses actuation instead of resetting the cap. |
| 7 | escalate | cap reached and still wedged → ONE Matrix `m.notice` per episode + `escalations_total` → `FreedomOntAutohealEscalated`. Escalates immediately, with the restore command, when the PoE restore failed (IOS error or session lost; `sw01_poe_cycle` retries it 3× on fresh sessions first) or when the port is still dark after the cycle and PoE Admin does not read `auto`. |

Both sentinels are in `gateway-master-switch.py` `ARMING_SENTINELS`, so a master-off removes
them (kill-all) and a master-on restores only what was there. They are also in
`OFF_EXEMPT_SENTINELS`, so their presence while the switch is off is not reported as drift.

> **Runs past the master switch (operator decision 2026-11-07, IFRNLLEI01PRD-2992).** The
> gateway master switch has been off since 2026-08-26 (TG primary, the gateway on standby). It
> writes `~/gateway.maintenance` with `"master_switch": true`, and every other gateway actuator
> stops for it. This heal does not: the hung-ONT class is a physical edge fault that no other
> actor heals, and gates 4-7 still bound it. `freedom_ont_autoheal_master_switch_exempt` is 1
> while that applies. After a **fresh** `gateway-master-switch.py off`, re-create the two
> sentinels by hand to keep the heal running. To stop it: `rm ~/gateway.freedom_ont_autoheal_armed`.
> Armed and drill-proven 2026-11-07 16:10-16:13 NL (`--drill-force`: success in 143 s, mesh
> 52/52 BGP and 27/27 tunnels back by 16:17).

## Arm / disarm

```bash
touch ~/gateway.mutations_freedom_ont_allow    # lane through global shadow (needed while ~/gateway.mutations_off exists)
touch ~/gateway.freedom_ont_autoheal_armed     # arm
rm ~/gateway.freedom_ont_autoheal_armed        # disarm (instant; next run is analysis-only)
```

## Observability

`/var/lib/node_exporter/textfile_collector/freedom_ont_autoheal.prom`, every run:
`armed`, `lane_exempt`, `gate_active{gate}`, `suppressed`, `probe_ok{device}`,
`state_info{state}`, `link_down`, `wedged`, `poe_oper_on`, `poe_watts`, `asa_track_up`,
`down_streak`, `down_seconds`, `attempts_total`, `success_total`, `drills_total`,
`escalations_total`, `attempts_24h`, `failure_open`, `last_run_timestamp`, and **only after a
real attempt** `last_result` (1 = link + Track 1 back), `last_link_restored`,
`last_attempt_timestamp`.

| Alert | Expr | Meaning |
|---|---|---|
| `FreedomOntWedged` (warning) | `wedged == 1` for 10 m | the post-power-loss wedge. If `suppressed == 1`, run the recipe by hand. |
| `FreedomOntAutohealFailed` (critical) | `failure_open == 1` for 5 m | a real attempt did not bring Freedom back and it has not been seen healthy since. `last_link_restored == 1` → ONT fine, PPPoE/BRAS is the problem. |
| `FreedomOntAutohealEscalated` (critical) | `increase(escalations_total[30m]) > 0` | cap hit, or PoE restore failed |
| `FreedomOntAutohealStale` (warning) | last run > 15 min ago, or absent | the detector is dark |

Rules: `prometheus/alert-rules/freedom-ont-autoheal.yml` (+ `.test.yml`, promtool via QA
test-726); deployed truth: NL IaC `k8s/namespaces/monitoring/intersite-autoheal-alerts.tf`
group `freedom-ont-autoheal`. Audit trail: `~/logs/claude-gateway/freedom-ont-heal.log`
(healthy runs stay quiet; every other state logs one line), Matrix `m.notice` to
`#infra-nl-prod` on every actuation and escalation.

## CLI

```bash
cd ~/gitlab/n8n/claude-gateway
python3 scripts/freedom-ont-heal.py --dry-run                 # live probe + decision; writes/acts nothing
python3 scripts/freedom-ont-heal.py --snapshot-file snap.json --dry-run   # decision on a fixture
python3 scripts/freedom-ont-heal.py --drill-force             # SUPERVISED live test, see below
```

## Supervised live test (not yet run)

The recipe itself is proven by hand (2026-11-07 11:59 NL). The automated actuation +
verify path has only been exercised against mocks (QA `test-freedom-ont-heal.sh`). To prove
it on the real port, with a human watching:

1. Preconditions: someone who can reach the ONT physically is around; Budget healthy
   (`budget_pppoe_up 1`) and both intersite legs Established (`bgp_mesh_established_count`
   52/52); no chaos drill running. Freedom drops for ~2 min; Budget carries it.
2. `python3 scripts/freedom-ont-heal.py --dry-run` → `healthy`, `no action (healthy)`.
3. `python3 scripts/freedom-ont-heal.py --drill-force` from an interactive shell (it refuses
   without a TTY). It bypasses streak, gates and cap, keeps the port-identity check, cycles
   the port, verifies link (≤ 90 s) and Track 1 (≤ 240 s), and prints `result`. Expect
   link ≈ 10 s, Track 1 ≈ 100 s. A drill counts in `drills_total`, not in the 24 h cap.
4. Check the log line, the Matrix notice and `freedom_ont_autoheal_last_result 1`.
5. If the port is left without PoE (`POE-LEFT-OFF` escalation): on nl-sw01
   `interface GigabitEthernet1/0/36` / `power inline auto` / `shutdown` / `no shutdown`.

## Manual recipe (heal suppressed or disarmed)

SSH to nl-sw01 (netmiko helpers in `scripts/lib/ios_ssh.py`, or by hand), then the
recipe at the top of this page. `ios_ssh.sw01_poe_cycle("GigabitEthernet1/0/36")` runs it
in one session and retries the restore step if the session dies.

## Related

- `scripts/freedom-ont-drill-trigger.sh` / `chaos-port-shutdown.py --scenario freedom-ont-shutdown`:
  the monthly failover drill (admin-shuts the port; this heal ignores `disabled` and the chaos marker).
- `freedom-qos-toggle.sh`: Freedom PPPoE SMS edge (still an early-exit gated script).
- memory `freedom_ont_poe_recycle_gotcha_20260422`: why a plain `no shutdown` does not wake the ONT.
