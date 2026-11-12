# GR watches NL (`NLSiteDegraded`)

**Since 2026-11-07.** IFRNLLEI01PRD-2992 (NL power-loss postmortem, MR !284), operator decision B.

## Why

During the 2026-11-06/07 house power loss the GR paging bridge on grclaude01 sent one
SMS at 21:26 NL (`ntfy-health DOWN paged sms ok=True`) when ntfy on nl-matrix01 died,
and saw ntfy recover at 03:48 NL. Nothing watched NL itself, so 03:30 → 11:09 NL passed in
silence while 46 guests were still down. NL cannot page about its own death: its alert intake
(nltg01), its Prometheus/Alertmanager and its paging bridge (nl-claude01) die with it.

## What it is

`scripts/gr-watches-nl.py`, run every minute on **grclaude01** by
`gr-watches-nl.timer` → `gr-watches-nl.service` (oneshot, `--once`). It probes key NL services
from GR and raises the alert `NLSiteDegraded` through the **local GR paging bridge**
(`scripts/paging-bridge.py`, `POST http://127.0.0.1:9106/alert`, Alertmanager webhook format).

| Check | Role | Probe from GR |
|---|---|---|
| TG intake | critical | `GET http://10.0.181.X:8080/api/healthz` → 200 + `ok` (nltg01, primary NL alert intake; the same direct target as the NL `territory-grounder` blackbox job) |
| NL Prometheus+Alertmanager | critical | NodePort `:30090` on nlk8s-node02/03/04/01 (`10.0.X.X/.22/.23/.20`, first that answers): `/-/ready` + `/api/v1/alertmanagers` with ≥ 1 active Alertmanager |
| nl-claude01 | critical | TCP `10.0.181.X:22` and an `SSH-` banner (a storage-dead host dies at the banner) |
| n8n | normal | `GET https://n8n.example.net/healthz` → `"ok"` |
| Home Assistant | normal | `GET http://10.0.181.X:8123/manifest.json` (HAHA VIP) |
| Nextcloud | normal | `GET https://nextcloud.example.net/status.php` → `"maintenance":false` |
| public edge | info (never counted) | `GET https://matrix.example.net/ntfy/v1/health` over the VPS edge, not the NL↔GR tunnels |

Each HTTP/TCP check gets 2 attempts (5 s timeout, 1.5 s apart); the Prometheus check tries each
node once. All checks run in parallel; a healthy run takes ~0.4 s, a fully dark NL ~20 s.

## The rule

- **Degraded run** = any **critical** check failing, **or ≥ 2** counted checks failing.
  Critical = the NL alerting chain itself: if one of them is down, NL is blind or mute.
  A single normal service down is not a site problem; NL's own alerting covers it.
- **Page** when degraded for **5 consecutive runs** (~5 min, `GRWATCH_DEGRADED_AFTER`).
- **Re-notify every 60 min** (`GRWATCH_RENOTIFY_S=3600`) while still degraded. Each
  notification carries its own episode key (`instance=nl-from-gr@<start>#<n>`), so the hourly
  cadence is owned by the checker and does not depend on the bridge's re-page policy
  (`PAGING_REPAGE_S`, or the "episode-once" change still unmerged on branch
  `fix/paging-bridge-episode-once-quiet-tier`).
- **One recovery push** after **3 consecutive not-degraded runs** (`GRWATCH_RECOVER_AFTER`),
  only for an episode that was paged: a `resolved` for the last key → the bridge's
  `[nl] NLSiteDegraded resolved` push. Checks still failing below the rule are listed in it.
- A healthy run in the middle of an episode does not end it (hysteresis); a degraded streak
  shorter than 5 runs is silent.
- **Observer self-check:** if GR itself cannot reach 1.1.1.1 / 9.9.9.9 / 8.8.8.8 on :443, the run
  is skipped and the counters are frozen. That is GR isolation, which `gr-inalan-wan-monitor`
  already pages; it must not also read as "NL degraded".
- The message names each failing check and its error, the start time in NL time and UTC, and a
  hint from the public-edge check: edge DOWN too → "NL looks down as a whole"; edge OK while
  every counted check fails → "suspect the NL-GR path (partition) rather than an NL site loss".

## Channels and the ULTRA SMS allowlist

Labels: `alertname=NLSiteDegraded site=nl observer=gr source=gr-watches-nl tier=1
severity=critical`, and **no `page="sms"` label**. The bridge therefore:

- pushes to ntfy `alrt-tier1` (priority 5) when ntfy is reachable;
- when the publish fails, uses its **capped SMS fail-over** (`[PUSH-DOWN] [FIRING]
  NLSiteDegraded …`, `PAGING_SMS_FAILOVER_CAP_PER_H=3`, shared with all GR tier-1 pages).

NL site loss / isolation is in the operator's ULTRA class ("site isolation may SMS"), so the
fail-over SMS is within policy. Since ntfy lives on nl-matrix01 in NL, a full NL outage is
exactly the case where ntfy is down. Then the checker's page and each hourly re-notify go out as
SMS (≤ 1/h), next to the bridge's own one-off `[GR-ULTRA] PagingPushDown` SMS. The recovery push
is push-only (the bridge never fails a resolve over to SMS).

**Fallback:** if the bridge is not listening, or answers that it has no record of the episode
(a bridge restart between the last page and the recovery), the checker publishes the push
directly to ntfy with the bridge's own ntfy settings (`GRWATCH_BRIDGE_ENV`). The checker never
sends SMS itself. A bridge POST that times out (30 s) counts as delivered: retrying could double
an SMS.

## Deliberately not honoured

`~/gateway.maintenance` on nl-claude01 is NOT read. It is the TG-graduation master switch
and has been on permanently since 2026-08-26; honouring it would mute this watcher forever, and
a watcher of a dead NL could not read it anyway. Use the GR-local mute instead.

## Files and deployment

| What | Where |
|---|---|
| script (deployed copy) | grclaude01 `/home/app-user/scripts/gr-watches-nl.py` (beside `paging-bridge.py` + `lib/ntfy.py`) |
| units | `/etc/systemd/system/gr-watches-nl.{service,timer}` (source `scripts/systemd/`) |
| state | `/var/lib/gr-watches-nl/{state.json,mute.json,lock}` (`StateDirectory=`, owned by app-user) |
| bridge env read for the fallback + test | `/home/app-user/.config/am-twilio/env` (ntfy keys only) |
| QA | `scripts/qa/suites/test-gr-watches-nl.sh` (hermetic, 30 tests) |

Deploy or update from nl-claude01 (a merged `main` checkout):

```bash
scp -i ~/.ssh/one_key scripts/gr-watches-nl.py app-user@10.0.X.X:/home/app-user/scripts/
scp -i ~/.ssh/one_key scripts/systemd/gr-watches-nl.service scripts/systemd/gr-watches-nl.timer root@10.0.X.X:/etc/systemd/system/
ssh -i ~/.ssh/one_key root@10.0.X.X 'systemctl daemon-reload && systemctl enable --now gr-watches-nl.timer'
```

## Operating it

```bash
ssh -i ~/.ssh/one_key root@10.0.X.X
systemctl list-timers gr-watches-nl.timer
journalctl -u gr-watches-nl -n 20 --no-pager -o short-iso      # one line per run
sudo -u app-user python3 /home/app-user/scripts/gr-watches-nl.py --status
# planned NL work: hold pages (probing continues; max 24 h, then it re-arms on its own)
sudo -u app-user python3 /home/app-user/scripts/gr-watches-nl.py --mute 2h --reason "nlpve04 reboot"
sudo -u app-user python3 /home/app-user/scripts/gr-watches-nl.py --unmute
```

A mute holds firing pages only. If NL is still degraded when it expires, the page goes out; a
recovery for an already-paged episode is never held. **Kill switch:** `systemctl disable --now
gr-watches-nl.timer` (prefer the mute: a disabled timer is a dark watcher nobody notices).

A run line looks like `run degraded=False failing=0/6 cd=0 ch=412 episode=none action=none`
(`cd`/`ch` = consecutive degraded / healthy runs). A failing bridge POST exits 1, so the
service shows as failed in `systemctl --failed`.

## Testing (no SMS)

1. **Bridge contract, zero side effects:** `--check-bridge` → `GET /health` + `POST /alert`
   with a `resolved` alert for a never-paged key. The bridge answers
   `{"pushed":0,"sms":0,"deduped":0,"resolved":0}`: payload parsed, nothing sent.
2. **One real TEST push:** `--test` starts a **sandbox copy of the deployed bridge** on a
   random free port for ~20 s (the bridge always binds 0.0.0.0; the checker talks to it on
   127.0.0.1) with an env file that carries only the four ntfy keys (no `TWILIO_*`) and
   `PAGING_SMS_FAILOVER=0`, so no SMS is possible on that path. It runs 8 cycles against two
   fake failing checks (192.0.2.1 TEST-NET-1 + a refused loopback port) and asserts exactly one
   firing POST, exactly one ntfy push titled `[TEST] NLSiteDegraded`, and zero SMS. The live
   bridge and the live state are not touched.
3. **Count on the ntfy side** (nl-claude01, operator read-only login from
   `~/.config/gateway/ntfy-operator.cred`):
   `GET http://10.0.X.X:8880/alrt-tier1/json?poll=1&since=<unix ts>` with Basic auth.
4. **Hermetic:** `bash scripts/qa/suites/test-gr-watches-nl.sh` (fake clock + the real
   `paging-bridge.py` handler with sends monkeypatched).

Verified 2026-11-07: `--check-bridge` OK on the live bridge; `--test` PASS (ntfy topic showed
exactly 1 `[TEST] NLSiteDegraded` message since the test start, Twilio showed no SMS in the
window); live runs `failing=0/6 action=none`.

## Limits and follow-ups

- **Who watches the watcher:** nothing yet. grclaude01:9100 is not scraped (same gap as the
  GR bridge metrics, IFRNLLEI01PRD-2706), and a dead-man in NL is useless for this case. A
  failing run is only visible in `systemctl --failed` on grclaude01.
- The Prometheus node list is static (`10.0.X.X-.23`). If the NL workers are renumbered,
  update `DEFAULT_TARGETS` or pass `--targets <json>`.
- `n8n`/`Nextcloud` resolve to both NPMs (nlnpm01 `10.0.181.X` and grnpm01
  `10.0.X.X`); either path proves the NL backend. Every GR→NL check except the public edge
  rides an intersite tunnel, so an NL↔GR partition also reads as degraded. It pages with the
  partition hint, beside `IntersiteBGPPartition`.
