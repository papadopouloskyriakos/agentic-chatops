# RCA — `nat-no-xlate-to-pat-pool` + `nat-rpf-failed` on nl-fw01

## Summary

At 2026-04-22T16:05Z while documenting the 10 Budget-ISP parity gaps, the
initial evidence against parity included:

```
nat-no-xlate-to-pat-pool     829,075
nat-rpf-failed               264,802
```

These looked like active drops. They were not.

## Actual rate (post clear asp drop, 2026-04-22T~18:11Z)

A fresh 5-minute observation window after `clear asp drop` showed:

| Counter | 5-min delta |
|---|---|
| `nat-no-xlate-to-pat-pool` | **0** |
| `nat-rpf-failed` | **0** |
| `rpf-violated` | 1 (~0.003/s) |
| `acl-drop` | 2 413 (~8/s — normal internet ACL noise) |

So both "NAT drop" counters are not accumulating. The 829 075 + 264 802
totals are **cumulative history**, not ongoing failures — they logged the
transient bad-NAT state that existed between the 2026-04-21 xs4all→budget
migration commit and the sequence of identity-NAT patches that landed
across today:

1. `10.0.X.X/30` added to `whitelist_shun_nlgr_all_subnets →
   nl_all_subnets` (post shun incident, 2026-04-22)
2. Section-1 identity NAT rules added for `dmz_servers02 ↔ outside_budget`
   covering `NET_k8s_rr` → `NET_budget_transit`, `NET_vti_mesh`,
   `NET_gr_private`, `NET_vps_ch`, `NET_vps_no`
3. After-auto `source dynamic any interface` (PAT) added on all inside
   zones that egress via outside_budget

The drop counters are cumulative since last power-cycle / `clear asp drop`,
so they retain the pre-fix history even after the underlying path
becomes healthy.

## Verification methodology

```python
# Before clear
asa.send_command("show asp drop | include nat|rpf")
# ... "nat-no-xlate-to-pat-pool 829075, nat-rpf-failed 264802"

time.sleep(60)
# identical counters — delta = 0 → confirmed not accumulating

asa.send_command("clear asp drop")
time.sleep(300)
asa.send_command("show asp drop | include nat|rpf")
# ... counters absent from output = 0 hits (ASA omits 0-value counter lines)
```

## What changes

- Gaps #3 and #4 in the Budget-ISP parity gate are marked **RESOLVED**.
- The fix already landed; there was no new action required today.
- Monitoring: node_exporter textfile `asa_binding_drift.prom` already tracks
  the Section-1 identity NAT rules via `asa_nat_rule_present` metric; the
  associated alert would page us if any rule regresses.

## Why the counters weren't zero to begin with

Cisco ASA keeps ASP drop counters since boot or last `clear asp drop`,
whichever is more recent. During the 2026-04-21 migration + 2026-04-22
mid-test patches, every "missing identity NAT" and "asymmetric path" 5-tuple
incremented these counters before the fix landed. Nothing cleared them
after the fix, so they retained the historical total.

**Recommendation: add a post-migration runbook step** to `clear asp drop`
after any NAT/routing change, so the snapshot taken for the next audit
reflects the fixed state rather than the pre-fix history.
