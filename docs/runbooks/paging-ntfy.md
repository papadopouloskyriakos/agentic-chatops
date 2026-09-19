# Paging: tier-1 → ntfy phone push; SMS only for ULTRA-urgent

**Since 2026-08-25** (operator-approved plan; supersedes "tier-1 → Twilio SMS").
The operator dislikes SMS: 526 SMS/~$77 in Jul–Aug 2026, mostly Gatus flap pairs
and hourly re-pages. The phone channel is now **ntfy** (already on the operator's
Android for Element UnifiedPush); Twilio SMS survives only for the ULTRA-urgent
set + as a capped fail-over.

## Architecture

```
Prometheus NL/GR/NO ── Alertmanager  tier=1 & severity=critical ──► paging bridge (page-tier1 receiver)
Alertmanager  alertname=Watchdog  ────────────────────────────────► paging bridge /heartbeat  (repeat 2m)
paging bridge  = scripts/paging-bridge.py
    NL: nl-claude01:9106 (user unit paging-bridge.service; old alertmanager-twilio-bridge.service MASKED)
    GR: grclaude01:9106 (system unit; deployed COPY at /home/app-user/scripts/)
    NO: → NL bridge over the overlay (unchanged)
    ├─ every tier-1 alert → ntfy topic alrt-tier1 (priority 5, edge-triggered: ONE push per firing
    │  episode; re-page only after PAGING_REPAGE_S=6h quiet; resolved → one quiet push)
    ├─ labels.page == "sms" → Twilio SMS too  ◄── THE ULTRA ALLOWLIST, declared on the PrometheusRule
    ├─ ntfy publish fails → SMS fail-over (cap PAGING_SMS_FAILOVER_CAP_PER_H=3, then 1 notice/h)
    ├─ ntfy /v1/health fails ×3 → one "PagingPushDown" SMS (edge-triggered) + paging_ntfy_up=0
    ├─ Watchdog silent >15 min → "PrometheusHeartbeatLost site=X": ntfy always; SMS only when
    │  site == PAGING_SITE (NL pages nl, GR pages gr; site=no is ntfy-only — an overlay flap must
    │  not double-page beside the partition SMS)
    └─ metrics → /var/lib/node_exporter/textfile_collector/paging_bridge.prom (NL scraped; GR not yet)
Gatus (NL) ── native ntfy provider → alrt-tier1 (Twilio provider REMOVED)
freedom-qos-toggle.sh: Freedom DOWN → SMS+push (ULTRA) · RECOVERED → push only
budget-pppoe-health.sh: dual-WAN fail → SMS+push (ULTRA) · recovery → push only
gr-inalan-wan-monitor.py (grsyslogng01, LTE): isolation → SMS+push (ULTRA) ·
    re-notify → push hourly, SMS ≤ every GR_WAN_SMS_RENOTIFY_S=6h · restored → push only
```

## The ULTRA-urgent set (operator decision 2026-08-25)

SMS + ntfy: **site partition/isolation** (`IntersiteBGPPartition` [`page="sms"`],
GR-isolated monitor, NL dual-WAN fail) · **paging path dead** (PagingPushDown,
PrometheusHeartbeatLost own-site) · **hypervisor** (`PVEPmxcfsWedged`,
`PVEMemoryPressureCritical` [both `page="sms"`]) · **Freedom ISP DOWN**.
Everything else tier-1 (the 8 edge-security alerts, plus `TerritoryGrounderDown` —
outside-in probe of TG's console `/api/healthz`, 5m, operator decision 2026-09-18 "ntfy",
TG-565; NL `estate-alerts.tf` group `territory-grounder`) = ntfy only. The 26 alerts
SMS-disabled on 2026-08-01 stay **Matrix/YouTrack-only** (operator: do not restore).

## ntfy server

Matrix stack on nl-matrix01 (`docker/nl-matrix01/matrix/` in NL infra repo,
infra MR !518). **Real auth since 2026-08-25**: `auth-file /var/lib/ntfy/user.db`
(host `/srv/matrix/ntfy-data/`), `deny-all` + ACLs: `everyone up* rw` (UnifiedPush),
`alerts-pub alrt-* write-only` (token in gateway `.env` `NTFY_TOKEN`), `kyriakos
alrt-* read-only` + `up* rw`. Publish URLs: NL LAN `http://10.0.X.X:8880`,
GR/phone public `https://matrix.example.net` (root `alrt-*` nginx route).
⛔ **Never change `NTFY_BASE_URL`** — live Synapse pushers hold absolute root `up…`
pushkeys. Operator credentials: `~/.config/gateway/ntfy-operator.cred` on
nl-claude01 (user `kyriakos` + password + token).
Gatus reads the token via `TF_VAR_gatus_ntfy_*` (Atlantis `/srv/atlantis/ntfy.env`) and the drift CI
fetches OpenBao `secret/ci/gatus-ntfy` (seeded 2026-08-25 with the node root token — see memory
`reference_openbao_admin_access`; drift pipeline #50661 verified clean).

**Phone setup (operator, one-time):** ntfy app → Settings → Manage users → add
user `kyriakos` for `https://matrix.example.net` (password from the cred
file) → Subscribe to topic `alrt-tier1` → enable instant delivery + a loud
per-topic sound. Test: `bash -c 'set -a; . .env; set +a; curl -H "Authorization: Bearer $NTFY_TOKEN" -d test "$NTFY_URL/alrt-tier1?title=test&priority=3"'`

## Phone app — what the first onboarding taught us (2026-08-26)

- **nginx routes the app needs on the public hostname** (`matrix.example.net`, infra !518/!520/!522): `/_matrix/push/v1/notify`, `/ntfy/` (prefix-stripped), **`/v1/`** (the app validates a user against `/v1/account` — without this route it says "login failed" even with a correct password), and **one topic-list route** `^/((up…|alrt-…)(,(up…|alrt-…))*)(/.*)?$` — the app multiplexes ALL topics of a server over one WebSocket at `/topicA,topicB/ws`; single-topic routes 404 it into element-web → "connection error: websocket not supported", and that also kills UnifiedPush (Element push) on the same connection.
- **401 on `/alrt-tier1/auth` with the right username = a stale stored user entry on the phone.** Manage users → delete the entry → subscribe again → enter the credential fresh. The password is deliberately the operator's chosen one; never rotate it unasked ([[feedback_hand_over_requested_secrets_dont_rotate_unasked]]).
- **Diagnose from the server, not the phone:** nginx access log (`/srv/matrix/nginx-logs/access.log`, UA `ntfy/1.x`) shows path + status + the Basic-auth username; ntfy's manager stat `subscribers=N` (`docker logs ntfy`) is the truth for live streaming subscriptions — a long-lived JSON stream is only logged by nginx when it closes. After repeated WS failures the app may switch to ntfy's JSON-stream protocol; that is still real-time.
- **Test WebSocket upgrades with `curl --http1.1`** (HTTP/2 has no Upgrade semantics → false 400).
- **Click action:** every page carries a `Click` URL → Grafana alerting list filtered on the alertname (`PAGING_CLICK_URL?search=…`). Alertmanager's `generatorURL` is the in-cluster Prometheus (`monitoring-kube-prometheus-prometheus.monitoring:9090`, dead from a phone) — `PAGING_USE_GENERATOR_URL=1` re-enables it only if Prometheus ever gets a public `externalUrl`.
- **A bridge that publishes via the public route must probe `NTFY_HEALTH_URL=https://matrix.example.net/ntfy/v1/health`** (root `/v1/health` is element-web) — the GR bridge false-fired one PagingPushDown SMS before this was set.

## Config (gateway `.env`, env-overridable)

`NTFY_URL` · `NTFY_TOPIC_TIER1=alrt-tier1` · `NTFY_TOKEN` · `PAGING_SITE=nl|gr` ·
`PAGING_SMS_FAILOVER=1` · `PAGING_SMS_FAILOVER_CAP_PER_H=3` · `PAGING_REPAGE_S=21600` ·
`PAGING_NTFY_PROBE_S=60` · `PAGING_NTFY_DOWN_AFTER=3` · `PAGING_WATCHDOG_TIMEOUT_S=900` ·
`PAGING_TEXTFILE` · `PAGING_DRY_RUN=0` · `PAGING_SMS_LABEL=page` / `_VALUE=sms` · `NTFY_HEALTH_URL` (public-route bridges) · `PAGING_CLICK_URL` / `PAGING_USE_GENERATOR_URL=0`.
GR bridge env lives in `/home/app-user/.config/am-twilio/env` on grclaude01
(`AM_TWILIO_ENV` — name kept for compatibility). ⚠ A bridge publishing via the PUBLIC
route must set `NTFY_HEALTH_URL=https://matrix.example.net/ntfy/v1/health` —
the root `/v1/health` is element-web, not ntfy (caught live 2026-08-26: one false
PagingPushDown SMS from the GR bridge).

## Kill switches / maintenance

- `PAGING_SMS_FAILOVER=0` in `.env` + restart → no SMS fail-over (ULTRA `page=sms` still SMSes).
- `PAGING_DRY_RUN=1` + restart → both channels log-only (Alertmanager upgrades, Watchdog tests).
- `XDG_RUNTIME_DIR=/run/user/1000 systemctl --user stop paging-bridge` → no pages at all;
  Matrix/YT triage (`webhook-n8n` sibling route) is untouched.
- Revoke the publish token: `docker exec -e NTFY_AUTH_FILE=/var/lib/ntfy/user.db ntfy ntfy token list` → `token remove alerts-pub tk_…` on nl-matrix01.
- ⛔ Do NOT unmask/re-enable `alertmanager-twilio-bridge.service` — masked on purpose
  (SMS-only legacy path; a "fix-it" session must not resurrect it).

## Self-monitoring

`PagingBridgeStale` + `PagingPushDown` (critical, deliberately **no tier** — a dead
bridge can't page through itself; they reach Matrix/YT). The bridge SMSes
PagingPushDown internally the moment its probe fails 3×. Registry:
`prom:paging_bridge` (critical). **Known limitation:** the NL unit runs in the user
slice at `oom_score_adj=200` (OOM-killed 4× on 2026-08-25) — a root-installed system
unit with `OOMScoreAdjust=-500` would harden it (operator decision pending). GR
bridge metrics are written but **unscraped** (no Prometheus scrapes
grclaude01:9100) — the new alerts are NL-scoped; adding the GR scrape is a
follow-up.

## Rollback

Bridge: `systemctl --user unmask alertmanager-twilio-bridge && systemctl --user disable --now paging-bridge && systemctl --user enable --now alertmanager-twilio-bridge`
(old script returns via `git checkout <pre-cutover> -- scripts/alertmanager-twilio-bridge.py`).
ntfy/nginx: revert infra MR !518 files + `docker restart ntfy` / `nginx -s reload`.
Gatus / labels / Alertmanager: revert the infra MRs via Atlantis.

## Deliberately out of scope

Restoring the 26 SMS-disabled alerts · quiet topic for non-tier-1 criticals ·
off-estate dead-man for the bridge itself · cross-site Watchdog · NO local bridge ·
iOS (`upstream-base-url` unset) · `ntfy.example.net` hostname · deleting the
retired `/alert-session` code · Gatus alerting for GR/NO · MeshSat SOS SMS (product).
Historical docs/memories keep the name `alertmanager-twilio-bridge.py` deliberately.
