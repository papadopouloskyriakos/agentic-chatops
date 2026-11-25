# 2026-08-08 — 4th NL↔GR partition (email-flood discovery path) + sw01/rtr01 cleanup

One session, three arcs: the operator returned to 500+ alert emails → root-caused a ~7h
inter-site partition → shipped the missing alerting → then cleaned up the latched sw01 port
alert and pre-staged the Po4 second-leg repair.

## Arc 1 — the partition (03:32→10:40 UTC) and what hid it
- **Freedom leg** (nl-fw01 Tunnel4 `vti-gr-f` ↔ gr-fw01, peer 203.0.113.X) wedged
  silently 2026-08-07 ~15:57 UTC for **19.5h**: IKEv2 SA READY/UP-ACTIVE but **no IPsec child
  SA installed** (`show crypto ipsec sa peer` returns nothing), VTI ping 0%, BGP
  `10.255.200.X` Idle. Fix: **`vpn-sessiondb logoff ipaddress 203.0.113.X noconfirm`**
  (ASA rejects `clear crypto ikev2 sa <tunnel-id>` — "% Invalid Hostname").
- **Budget leg** (nlrtr01 Tunnel1 ↔ gr-fw01) went lossy-but-up 03:32→10:40 UTC;
  BGP hold-expired 03:54 and stayed down; self-recovered on SA bounce **with rtr01 as
  initiator** — the 08-01 `no config-exchange request` fix is holding.
- Blast radius: corosync **`eu-nlgr-pvecl01`** (cross-site 6-node PVE cluster; ring rides the
  tunnels, NL quorum 4/6 held, GR pair lost quorum) → `cororings` service CRIT on all 4 NL
  PVE; cross-site NMS device-down storms both directions; nc01/nc02 flaps; YT -2303..-2309.
- **The mailbox flood: 1,140 emails** (667 NL NMS + 473 GR NMS) = unlimited LibreNMS
  re-notify (count -1, interval 300) × ~7h × ~9 alerts, counted in OpenArchiver Postgres.

## Arc 2 — fixes shipped same day (all live-verified)
1. **LibreNMS reminder cap**: critical rules count -1→5 on BOTH instances (NL 17 rules, GR
   14; snapshots `/root/alert_rules-backup-20260808.sql` on each nms host).
2. **Template hygiene**: all rules mapped to the Dynamic Global template both sites; the
   blank-`--`-subject emails were the fallback template for unmapped rules, NOT a duplicate
   transport. Fallback template title made informative too.
3. **The detection gap** (the real lesson — `bgp-mesh-watchdog.sh` had watched the leg die
   for 19.5h with zero rules on its metric): **PrometheusRule `intersite-bgp-alert-rules`**
   — `IntersiteBGPLegDown` (crit/10m, NL-side vantage), `IntersiteBGPPartition` (crit/5m),
   `BGPMeshSessionsMissing` (warn/30m), `BGPMeshWatchdogStale` (absent()-guarded dead-man).
   Infra MR !456 (Atlantis-applied+merged) + mirror `prometheus/alert-rules/intersite-bgp-mesh.yml`
   (promtool 4/4) via MR !205. Rules verified loaded+healthy in Prometheus.

## Arc 3 — nl-sw01 latched alert + Po4/Po8 (evening)
- LibreNMS alert 4865 ("Port status up/down", **acked since 06-23**) = device-wide rule
  latched by permanently-down ports. Fixed by `ports.ignore=1` on 12 expected-down ports
  (syno02 thermally parked — "summer vacations"; pqd01 decommissioned; wall jacks;
  StackPort1) → alert resolved (note: clearing-via-ignore writes NO alertlog row/email).
- **Po8 orphan deleted** (zero members, pve04 is deliberately active-backup on Te1/0/43+44;
  triple-checked zero config refs before `no interface Port-channel8`, wr mem).
- **Po4 (sw01↔nlrtr01, the budget-WAN uplink) one-legged since 04-21** — TWO stacked
  causes found: TDR shows **NO cable** in sw01 Gi1/0/32 (0m all pairs vs 12m reference) AND
  rtr01 Gi0/0/0 had lost `channel-group 4` in the April rollback. Member config pre-staged
  both ends (incl. `media-type rj45` on the ISR4321 combo port), descriptions updated, saved;
  **only the ~12m patch cable remains → IFRNLLEI01PRD-2312** (procedure inside).

## Standing facts distilled
- PVE estate = ONE cross-site corosync cluster `eu-nlgr-pvecl01` (gr-pve01=1,
  gr-pve02=2, nl-pve02=3, nl-pve01=4, nl-pve03=5, nlpve04=6; quorum 4).
  "Service up/down" on a PVE host = the `cororings` check ⇒ read it as an inter-site-link
  symptom first.
- ASA 9.16(4) **rejects BFD on VTI interfaces** (tested live on gr-fw01, reverted);
  rtr01-side BFD config stays in place inert for a future ASA.
- Acked LibreNMS alerts are invisible to `alerts?state=1` — query `state=2`.
- CDP+LLDP are off on sw01/rtr01: verify cabling via MAC table (bundle MAC on the LAG) and
  TDR (refuses admin-down ports; needs brief no-shut with far end kept down).

YT: -2303/-2304/-2305/-2307/-2308/-2309 closed Done w/ root cause; -1833 updated (4th
occurrence + new alerting); -2306 annotated (unrelated standing dirty-checkout); **-2312
created** (on-site cable). edge/CLAUDE.md updated via infra MR !457.
