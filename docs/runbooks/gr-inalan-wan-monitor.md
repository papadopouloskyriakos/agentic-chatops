# GR InAlan WAN / inter-site-mesh isolation monitor

**Script:** `scripts/gr-inalan-wan-monitor.py` (canonical, version-controlled)
**Deployed:** `grsyslogng01:/usr/local/bin/gr-inalan-wan-monitor.py`, cron `*/2`
**Origin:** the 2026-06-15 GR isolation — root cause [`memory/session_thermal_and_gr_unreachable_20260616.md`](../../memory/session_thermal_and_gr_unreachable_20260616.md).

## What problem it solves

On 2026-06-15 the GR **InAlan primary WAN** went down ~2h12m (22:58→01:11 UTC). The GR
ASA stayed up and kept the site on its **LTE backup**, but every site-to-site IPsec/VTI
tunnel is anchored to the InAlan public IP `203.0.113.X`, so the **inter-site mesh
dropped**. From NL the whole GR site looked "down/unreachable" and the triage wrongly
concluded it needed physical access with "no path in" — it actually self-recovered.

Normal monitoring **cannot** report this correctly *during* the outage, because the
telemetry path (the mesh) is the thing that's down. And the LTE backup **cannot** carry
the mesh — LTE is **CGNAT** (no inbound ports / no stable public endpoint for the static
IPsec peers). That gap is structural and accepted; this monitor is the mitigation:
detect the isolation GR-side and tell the operator the truth out-of-band.

## How it works

Runs on `grsyslogng01` (has the ASA+switch syslog locally, and keeps **outbound**
internet via LTE during an InAlan outage). Primary signal is a **functional probe**:

| mesh (NL-inside, mesh-only) | internet (public) | state | action |
|---|---|---|---|
| reachable | — | `ok` | none |
| **down** | up | `isolated` | **SMS over LTE** (InAlan WAN down, GR alive on LTE, mesh down) |
| down | down | `dark` | best-effort SMS (GR hard-down or this host's uplink dead) |

- **mesh anchors:** `10.0.181.X, 10.0.X.X, 10.0.181.X` (any-up = mesh up; all-down = mesh down — spread across distinct NL devices so one dead host can't fake an isolation).
- **internet anchors:** `1.1.1.1, 8.8.8.8`.
- **confirm window** `180s` (≈2 cron runs) rides out IPsec rekey blips before alerting.
- **cause attribution** (enriches the SMS, doesn't gate it) from local syslog: `gi7` uplink flaps, ASA `track-1` SLA state, `outside_inalan` DHCP re-lease, LTE bearer-up.
- **re-notify** hourly while isolated; **recovery SMS** with outage duration on clear.
- SMS via the Twilio REST API (API-key basic auth), creds in `/etc/gr-inalan-wan-monitor.env` (root 600, not in git).

## Ops

```bash
# on grsyslogng01 (ssh -i ~/.ssh/one_key root@grsyslogng01)
gr-inalan-wan-monitor.py --status     # JSON: current state + probe + cause signals
gr-inalan-wan-monitor.py --dry-run    # classify + print the SMS it WOULD send
gr-inalan-wan-monitor.py --test-sms   # send one labelled validation SMS
cat  /var/lib/gr-inalan-wan-monitor/state.json   # current state machine
tail /var/lib/gr-inalan-wan-monitor/monitor.log  # per-run history
```

State machine: `state` (ok|isolated|dark), `isolation_began`, `alert_active`, `last_alert`.

## Tuning / disable

- Override via env (in the cron line or `/etc/...env`): `GR_MESH_ANCHORS`, `GR_INET_ANCHORS`,
  `GR_WAN_CONFIRM_S`, `GR_WAN_RENOTIFY_S`, `GR_WAN_FLAP_WINDOW_MIN`.
- **Disable:** `crontab -e` on grsyslogng01, comment the `gr-inalan-wan-monitor` line.
- **Redeploy after edit:** `scp scripts/gr-inalan-wan-monitor.py root@grsyslogng01:/usr/local/bin/`.

## Known limitations / follow-ups

- **No Prometheus metric** — grsyslogng01 has no node_exporter textfile collector, so
  there's no normal-time dashboard/history (the OOB SMS is the during-outage signal). Adding
  a textfile collector + `GRInAlanWANDown` alert would give NL-side visibility when the mesh is up.
- **Single host** — if grsyslogng01 itself dies the monitor stops; no NL-side heartbeat yet.
- It detects + reports; it cannot **prevent** the isolation (the CGNAT/LTE constraint is structural).
  A real fix would need an outbound-initiated overlay (e.g. WireGuard roaming to a public VPS
  rendezvous) for the GR mesh — a separate, larger project.
- OOB-into-GR during an outage still requires the **PiKVM** (IFRGRSKG01PRD-85, bricked — onsite fix).
