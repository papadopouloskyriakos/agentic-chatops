# Post-mortem: NL house power loss and 14-hour partial outage (2026-11-06/07)

**Status:** Resolved 2026-11-07 ~12:01 NL · **Tracking:** IFRNLLEI01PRD-2992 (+ TG-649, TG-650, TG-652, TG-654)
**Author:** claude-gateway (agent) · **Severity:** SEV-1 (site power loss; one hypervisor's 46 guests down 14 h)
**Data loss:** None found. ZFS, the NAS RAID and Galera all came back clean (§10).

All times are **NL local (CET, UTC+1)** unless marked UTC.

---

## 1. Executive summary

At **21:24 on 2026-11-06** the house lost mains power (Liander outage 8482781, reported 21:32, ended 03:35). `nl-pve03` is on direct mains and died at once. `nlpve04` ran on the APC Smart-UPS for 10 minutes, then apcupsd halted it cleanly at 21:34. Battery runtime was only ~10 minutes at 51 % load, so the UPS ran flat a few minutes later and took `nl-sw01`, `nl-fw01` and `nl-nas01` down with it. The whole NL site was dark until power returned at **~03:30**.

When power came back, **most of the estate did not**:

1. **nlpve04 never started its guests**, on three separate boots (23:31, 03:32, 11:14). A typo in `/etc/hosts` gave nlpve04's address the short name `nl-pve03`. At a cold boot pmxcfs could not resolve its own node name without DNS, and DNS is a guest on the other host. `pve-guests` ran once, failed, and is never retried. 46 guests (n8n, GitLab, YouTrack, LibreNMS, Territory Grounder, Pi-hole, Music Assistant, paops, Proton bridges, Nextcloud's nlnc01, a Galera node, a k8s control-plane node, nl-claude01 itself) stayed off for **~14 hours**.
2. **Home Assistant stayed down** even though its VM was back at 03:49: its Pacemaker group waits on an NFS mount from an encrypted NAS share that DSM does not auto-mount.
3. **Galera** could not form a primary component after a full-cluster crash; Nextcloud and the other DB users were down until a manual bootstrap.
4. **The Freedom fiber ONT hung**: PoE on, Ethernet link down. Internet ran on the Budget line until it was power-cycled from the switch.
5. At **07:25** nlpve04 also **hung** on a fatal PCIe error (SERR) from its 10 G NIC. That was a separate hardware event, found only in the BMC event log.
6. **MeshSat customers were hit in Norway too.** The NO cluster's workers reach their own API server through the NL tunnel. While NL was dark (21:43 → 23:35 and 23:59 → 03:42), the Hub, Shop, Mailing list and Twenty support desk were **down for ~5 h 35 m**.

**Paging only half worked.** The GR paging bridge sent one SMS at 21:26 ("ntfy down": the paging server on nl-matrix01 had died with nl-pve03). But Territory Grounder (alert intake), NL Prometheus and the paging exporters were all on the dead hosts (TG-650), and nothing outside NL watched NL's health. When power came back at 03:30, the paging server returned at 03:48, and nothing said that the estate was still down. Recovery started only when the operator woke up at ~11:09, 7.5 hours after power returned. From then on every fix was remote and took ~50 minutes.

---

## 2. Impact

| What | Down | Duration |
|---|---|---|
| Whole NL site (network gear dark) | ~21:38 → ~03:31 | ~6 h |
| nl-pve03 guests (Matrix, FreeIPA, NPM, Vaultwarden, SMTP relays, nlk8s-ctrl03 / nlk8s-node02 / nlk8s-node03, nl-gpu01, NFS nlcl01file02, the HA VM nl-iot02, nlcl01mariadb02) | 21:24 → 03:49 (and again 11:09 → 11:20 for an operator reboot) | ~6 h 25 m |
| **nlpve04 guests (46)**, incl. n8n, GitLab, YouTrack, LibreNMS, TG, Pi-hole, syslog-ng, PBS, OpenObserve/Healthchecks/Langfuse, servarr/Music Assistant, paops, Proton bridges, nlnc01, nlcl01mariadb01, nlk8s-ctrl01 / nlk8s-node04, nl-claude01 | 21:34 → 11:41-11:50 | **~14 h 10 m** |
| Home Assistant (user-visible) | 21:24 → 11:32 | **~14 h 08 m** |
| Music Assistant / Lyrion speakers | 21:34 → 11:43 | ~14 h |
| Nextcloud, other Galera users | 21:24 → 11:54 | ~14 h 30 m |
| NL Kubernetes API | ~21:30 → ~11:50 | ~14 h 20 m |
| Freedom fiber (traffic on Budget line) | 03:31 → 12:00:50 (plus the dark period before) | ~8 h 30 m on backup |
| Paging: NL alert intake + Prometheus down (one GR SMS at 21:26 "ntfy down", then nothing) | 21:34 → 11:47 | ~14 h |
| GitLab CI: nlgitlabrunner03 (omoikane pool) | 21:24 → 12:03 (no onboot) | ~14 h 40 m |
| **MeshSat Hub, Shop + ordering, Mailing list, Twenty support desk (NO k8s)** | 21:43 → 23:35 and 23:59 → 03:42 | **~5 h 35 m** (see §5) |
| **MeshSat:** status.meshsat.net + the MeshSat assistant (phone, SMS, WhatsApp, support mail replies, web chat, Messenger) | 21:34 → ~11:48 | ~14 h (see §5) |
| **Data loss** | none | n/a |

GR was not affected beyond cross-site links. **NO was affected**: its k8s workers depend on the NL network (§4, cause #7).

---

## 3. Timeline (NL time)

### 2026-11-06: power loss
- **21:24:22** Mains lost. nlups01 on battery at 51 % load. **nl-pve03 dies** (direct mains).
- **21:34:45** apcupsd on nlpve04 reaches `MINUTES 3` → clean shutdown (guests shut down cleanly).
- **21:37:19** nl-nas01 shuts down (DSM log: encrypted share "Backup" unmounted by SYSTEM).
- ~21:38 UPS output gone → nl-sw01, nl-fw01 dark. NL quorum lost (3/6: nlpve04 halted + GR).
- **23:21-23:47** Grid flaps: nl-pve03 boots three times (23:21, 23:30, 23:34), never long enough to start guests.
- **23:31** nlpve04 boots; **pve-guests fails** (pmxcfs cannot resolve `nlpve04`).
- **23:33** brief mains failure; **23:49** mains fails again → **23:51:52** apcupsd halts nlpve04 again.

### 2026-11-07: power back, estate half back
- **~03:30-03:32** Power restored (Liander: 03:35). nl-pve03, nl-sw01, nl-fw01, nl-nas01 boot.
- **03:32:59** nlpve04 boots; **03:33:26 pve-guests fails again** (same cause). None of its 46 guests start.
- **03:49:17** nl-pve03 finishes starting its guests. Home Assistant's VM is up, but `p_fs_backup` cannot mount (the encrypted share is not mounted on the NAS), so the HA stack stays stopped. nlcl01mariadb02 cannot form a Galera primary on its own.
- 03:31 → nl-fw01 sends PPPoE PADIs every ~32 s on `outside_freedom`; no answer (ONT hung). Traffic runs over Budget.
- **07:25:37** nlpve04 hangs: BMC logs a Critical Interrupt, **PCI SERR on bus 05 (BCM57416 10 G NIC, both bond0 ports)**. No kernel log (firmware-first error handling).
- ~11:09-11:14 Operator wakes up, cleanly reboots nl-pve03 and power-cycles nlpve04. **11:14:35 pve-guests fails a third time.**
- ~11:22 Operator starts nl-claude01 by hand; recovery session starts 11:26.

### 2026-11-07: remote recovery
- 11:31:27 Operator mounts the encrypted "Backup" share in DSM → **11:32 Home Assistant back**.
- 11:39 `/etc/hosts` alias fixed on all 4 PVE hosts; nlpve04's failed PVE services started.
- 11:41 nl-pihole01 + nlservarr01 started → **11:43 Music Assistant back** (7/7 speakers).
- 11:42-11:50 `startall` brings up the remaining 33 onboot guests on nlpve04.
- 11:45-11:48 Matrix bot path (n8n) verified; TG back (TG session); paops selftest green, SIP registered; Proton bridges logged in.
- **11:53-11:54 Galera** re-bootstrapped from nlcl01mariadb02 (equal seqno 32351129), nlcl01mariadb01 rejoined by IST, garbd started → size 3, Primary.
- 11:55 Nextcloud verified (status, login, WebDAV, `occ`).
- 11:59:12 Freedom ONT PoE-cycled from nl-sw01 Gi1/0/36 → link up in 10 s → **12:00:50 PPPoE up**, default route back on Freedom.
- 12:03 nlgitlabrunner03 started (it has no onboot flag).
- 12:25-12:27 Freedom PPPoE flapped once ("Peer not responding / LCP down"; BRAS address changed .232 → .233) and came back on its own. Traffic briefly moved to Budget.
- 12:40 Encrypted "Backup" share set to auto-mount via DSM Key Manager.
- 12:55 TG session applies a `pve-guests` drop-in on all 4 PVE nodes (TG-649).
- ~13:00 LibreNMS "UPS on battery" alert added (NL + GR); the nlpve04 hang traced to the NIC via the BMC SEL.
- 13:00-13:30 Full estate sweep (§10), missed jobs re-run.

---

## 4. Root cause analysis

### Trigger: grid outage (external)
Liander outage 8482781, followed by ~30 minutes of mains flapping before the final ~4 h gap. Not preventable on our side.

### Cause #1: the UPS covers ~13 minutes, and only part of the site
The SMT1500IC ran ~10 minutes at 51 % (~500 W) on a battery from 2026-01-27 (the rack runs at ~40 °C). nl-pve03 is not on the UPS at all. A UPS can only bridge short dips; it cannot keep the site up through a multi-hour outage, so the real question is how cleanly everything comes back.

### Cause #2 (latent, the main multiplier): a wrong `/etc/hosts` alias plus a one-shot `pve-guests`
All four PVE hosts carried `10.0.181.X nlpve04.example.net nl-pve03` since ~2026-05-10. On nlpve04 the node name only resolved through DNS. Its single resolver was nlfreeipa01, a guest on nl-pve03. On a whole-site cold boot that resolver is not up yet, so pmxcfs failed 14 times and came up only after the dependent units had already failed. `pve-guests` is a one-shot unit with no retry. It failed on all three boots. On nl-pve03 the same typo made `nl-pve03` resolve to **two** addresses (.25 and .27). It never bit there, because .25 comes first.

This stayed hidden for six months because every earlier reboot was a single host, with DNS still up on the other one.

### Cause #3 (latent): Home Assistant's critical path includes a non-essential, encrypted NFS mount
`g_iot_stack` is an ordered Pacemaker group. `p_fs_backup` (HA's backup folder, NFS from the NAS share "Backup") sits before the HA containers. "Backup" is a DSM encrypted share with no Key Manager entry, so it stays unmounted after every NAS reboot. HA's VM was healthy from 03:49, but HA stayed down until a human typed the passphrase in DSM.

### Cause #4: Galera does not self-recover from a full-cluster crash
Both data nodes went down uncleanly. On restart neither may bootstrap (`safe_to_bootstrap: 0`), so both waited for each other in a reconnect loop. That is by design (it avoids split-brain), but it needs a human or a runbook, and nothing alerted on it.

### Cause #5: the Freedom ONT hangs after a power loss
The Genexis XGS-PON ONT came back with PoE on (15.4 W) but no Ethernet link (`notconnect`) for 8 h. This is the known PoE-recycle gotcha (2026-04-22). Nothing detects it or heals it automatically.

### Cause #6 (separate hardware event): PCIe SERR on nlpve04's 10 G NIC
At 07:25:37 the BCM57416 (bus 05, both functions = both bond0 legs) raised a PCI SERR. The board's firmware-first error handling halted the host with no kernel trace; the BMC SEL is the only evidence. This is the first occurrence in the SEL (52 entries). It may or may not be related to the power events.

### Cause #7 (latent, customer-facing): the NO MeshSat cluster depends on the NL network
The NO k8s worker nodes reach their own cluster's API server (`no-api-k8s`, VIP 10.255.X.X) through a **BGP route over the NL IPsec tunnel** (`ip route get 10.255.X.X` on notrf01dmz01 → `via 10.255.200.X dev xfrm-nl-xs4all proto bgp`; notrf01dmz02 → `via 10.255.200.X dev xfrm-nl-xs4all`). When the NL network went dark, the workers (notrf01dmz01, notrf01dmz02, notrf01dmz06) lost their control plane and went NotReady. Kubernetes evicted the MeshSat pods, and they could not run again until NL was back (workers Ready and Hub pods recreated at 03:38). The control-plane nodes (notrf01dmz03-05) stayed Ready, which is why the services running there (sign-in, MQTT, Reticulum, TAK) were only briefly affected.

Two monitoring traps hid this at first. NO Prometheus replica 0 has gaps in exactly those windows. Replica 1 looks continuous, but kube-state-metrics and the Hub's own series are simply absent then, and absent data is not evidence of "up". The edge HAProxy downtime counters are the authoritative customer view.

### Contributing: no paging, no external watcher
TG (primary alert intake), its blackbox and ntfy exporters, and NL Prometheus all ran on the two dead hosts. Nothing outside NL watches NL's health: the GR paging bridge only watches the paging server itself. It sent one SMS at 21:26 when ntfy died and nothing after ntfy returned at 03:48, so a 14-hour outage produced a single page (TG-650). The UPS "on battery" state was also never alerted: LibreNMS maps APC `onBattery` to a *warning* state, and the only generic state rule matches *critical*.

### Contributing: onboot gaps
nlgitlabrunner03 (the only ready omoikane runner) has no `onboot` flag.

---

## 5. MeshSat customer impact

Source: the backend `downtime` counters on all three edge HAProxies (chzrh01vps01, notrf01vps01, txhou01vps01). They agree, and they only cover the outage window (txhou01vps01's HAProxy started at ~21:24 NL).

| Service | Served from | During the outage |
|---|---|---|
| **Hub, Shop + ordering, shop site, Mailing list, Twenty support desk** | NO k8s (notrf01) | **down 21:43 → 23:35 and 23:59 → 03:42 (~5 h 35 m; ~19,800-20,300 s of backend downtime per edge)** |
| Sign-in (auth) | NO k8s | brief, 4-8 min in total |
| Bridge MQTT, Reticulum, TAK | NO k8s | brief, 0-4 min |
| Website, Docs, Installer | GR DMZ + NL DMZ | **up** (GR carried it, < 30 s) |
| status.meshsat.net (Kener) | NL DMZ only (nl-dmz01 on nlpve04) | **down** 21:34 → ~11:45 |
| MeshSat assistant (published phone line, SMS, WhatsApp, support@meshsat.net replies, shop web chat, Messenger) | paops on nlpaops01 (nlpve04) | **down** 21:34 → ~11:48. Mail was queued at Proton, not lost. |

When Kener came back it **auto-opened 19 incidents (11:54-12:34)**. All were false: NL Prometheus had just restarted, and Kener counts "no data" as degraded. All auto-resolved. They may have emailed subscribers.

---

## 6. What went well

- **No data loss anywhere.** The ZFS pools, NAS RAID, PBS datastore and Galera (equal seqno on both nodes) came back clean.
- **The UPS shutdown coupling worked**: nlpve04 was halted cleanly twice instead of losing power.
- **MeshSat devices kept working**: Bridge MQTT, Reticulum and TAK stayed reachable apart from a few minutes, and the website and docs were carried by GR.
- **Everything was fixed remotely** once someone was awake: no site visit, ~50 minutes from first look to all named services green.
- **Persistent journals, the BMC SEL and the DSM log** gave exact timestamps for every step, so this report is built from evidence.
- **Cross-session coordination worked**: the TG session owned TG's recovery and the `pve-guests` fix. This session did the hypervisors, data and network, with no conflicts.

## 7. What went wrong

- **7.5 hours passed between power returning and anyone starting recovery.** The only page was a single GR SMS at 21:26 ("ntfy down"); nothing watched whether NL came back.
- **A six-month-old typo turned a 6-hour outage into a 14-hour one.** It was invisible until both NL hosts cold-booted at the same time.
- **Single points of failure inside the site:** nlpve04's only DNS server was a guest on nl-pve03, and HA was gated on a NAS share that needs a human.
- **Recovery depends on order, and nothing enforces it:** DNS, then the DB cluster, then the apps. Each layer had to be fixed by hand.
- **The MeshSat status page and assistant sit on one NL host**, so the customer-facing status page could not report the outage it was built for, then reported 19 false ones.
- **Agent-side mistake (corrected in-session):** an early report said the UPS battery "failed its self-test". SNMP showed the last test result was "invalid" (not failed) and the replace-battery flag was off.

---

## 8. Action items (improvements)

Status as of 2026-11-07 18:30 NL: ✅ done · 🔲 open. Effort is a rough estimate.

| # | Action | Priority | Effort | Status / owner |
|---|---|---|---|---|
| 0 | **Keep the NO MeshSat cluster independent of NL**: NO-internal traffic, above all the workers' path to their own API VIP 10.255.X.X, must not transit the NL tunnel (local route or local announcement instead of a BGP best path via `xfrm-nl-xs4all`). Then run a drill: drop the NL tunnels and check the NO workers stay Ready | **P0** | M | ✅ **done 11-07**: worker↔CP iBGP (local-pref 200) + a `suppress_prefixlength 0` rule keep 10.255.X.X inside NO (infra !685, notrf01 !111); **drill passed** on notrf01dmz06 (lease renewals ≤9 s, node stayed Ready, the VIP route stayed direct) |
| 1 | Fix the `/etc/hosts` alias on all PVE hosts | P0 | done | ✅ 11:39 (agent) |
| 2 | `pve-guests` waits for pmxcfs (`/etc/pve/local`) before start-all; prove it with a reboot drill | P0 | S | ✅ drop-in applied (TG-649); 🔲 reboot drill once the replacement nl-pve01 rejoins (IFRNLLEI01PRD-2995) |
| 3 | ≥2 resolvers on different hosts/sites for every PVE node (nlpve04 had one) | P0 | S | ✅ both hosts now 3 resolvers, **other host first** (a host boots before its own guests); all NL guests audited and fixed (!286, doc fix !289) |
| 4 | Encrypted "Backup" share auto-mounts at NAS boot (DSM Key Manager) | P0 | done | ✅ 12:40 (operator choice: automatic) |
| 5 | Off-site dead-man for NL: something in GR or on a VPS pages (ntfy/SMS) when NL TG/Prometheus/nl-claude01 go silent | P0 | M | ✅ **done 11-07**: GR watches NL (`NLSiteDegraded` via the GR paging bridge: ntfy push, SMS when ntfy is down, hourly re-notify) (!285). Follow-up: grclaude01:9100 is not scraped yet |
| 6 | Alert on UPS on-battery (LibreNMS NL + GR) | P1 | done | ✅ rules NL 28 / GR 20 |
| 7 | Startup order across hosts: DNS (FreeIPA/Pi-hole), then Galera, then dependants (PVE `startup: order=` + boot delays), and one DNS server per host | P1 | M | ✅ **done 11-07**: tiered `startup: order=/up=` on both hosts (DNS → Galera → dependants), ≥2 resolvers on every NL guest, nlk8s-frr01/02 allowed to the IPA resolvers in the nl-fw01 ACL (saved), doc !286. Pi-hole left as is (operator) |
| 8 | Galera full-crash handling: alert on "no Primary" and a scripted, guarded bootstrap (highest seqno, refuse on mismatch) | P1 | M | ✅ **done 11-07**: `galera_*` metrics + `GaleraNoPrimary` alert + `galera-guarded-bootstrap.py` (refuses on a seqno mismatch, never automatic) (!287, infra !683). `GaleraNoPrimary` pages via ntfy (tier 1, operator 11-07, infra !687) |
| 9 | Freedom hung-ONT auto-heal: Gi1/0/36 `notconnect` + PoE on for >5 min → PoE-cycle (fits the intersite L0 heal lane) | P1 | S | ✅ **done + ARMED 11-07**: `freedom-ont-heal.py` (Cronicle `emw6ixgbqqi`, */2), 3 cycles/24 h + backoff + escalate, own exemption lane, 4 alerts (!288, infra !684). Supervised `--drill-force` 16:10 NL: **success in 143 s**, BGP 52/52 + tunnels 27/27 back by 16:17. Armed 16:19; on the operator's decision it runs past the master switch, and only a real maintenance window blocks it (!290, infra !686) |
| 10 | Remove HA's dependency on the backup mount: take `p_fs_backup` out of the ordered `g_iot_stack` chain (optional colocation) | P2 | S | ✅ **done 11-07**: `p_fs_backup` out of `g_iot_stack` (colocation + optional order), HA config bind `:rslave` so a late Backup mount still reaches the container; staged in a shadow CIB, `crm_simulate` clean, applied |
| 11 | MeshSat status page: a second Kener instance outside NL, plus a grace period for "no data" after a Prometheus restart (no auto-incidents for a cold start) | P1 | M | ✅ **done 11-07**: Kener no-data grace period + a static GR-DMZ fallback page at the edge (infra !682). Follow-ups: DOWN threshold, tor-onion confirmation |
| 12 | MeshSat assistant line: a Twilio failover (voicemail/forward) when paops' SIP registration is gone | P1 | S | 🔲 backlog (IFRNLLEI01PRD-2994) |
| 13 | nlpve04 NIC: watch for SERR recurrence (in-band SEL exporter, or cable the BMC LAN 10.0.181.X), then review the bnxt_en firmware (225.0.148.0) | P2 | M | ✅ **done 11-07**: in-band SEL exporter on nlpve04 (`pve-sel-exporter`, `/dev/ipmi0`) + `PVEBMCCriticalEvent` (!287, infra !683), on the ntfy quiet topic (tier 2, operator 11-07, infra !687); firmware review later |
| 14 | UPS: runtime test, battery check, and decide whether nl-pve03 goes on a UPS (Oukitel assessment 2026-10-13) | P2 | M | 🔲 review + plan (IFRNLLEI01PRD-2993) |
| 15 | onboot audit: every guest that ran before the outage should have `onboot=1` or a documented reason (nlgitlabrunner03 had none) | P2 | S | ✅ nlgitlabrunner03 `onboot=1` |
| 16 | Cronicle: enable catch-up for daily regenerators so missed runs replay after host downtime (5 jobs had to be re-run by hand) | P2 | S | ✅ **done 11-07**: `catch_up=1` + `max_children=1` on 8 idempotent daily jobs (`cronicle-catch-up.py`); `backup-gateway-db.sh` skips when a backup <60 min old exists, so replays leave one backup (!288) |
| 17 | Re-run the missed nlpve04 weekly vzdump (49 guests, last good 10-31), or accept until 11-14 | P1 | S | 🔲 the 11-08 one-shot timer was lost when nlpve04 crashed 11-07 23:20 NL (transient unit). Rescheduled as reboot-safe `rerun-backup-20261109.timer`, 2026-11-09 01:30 NL; result in `/var/log/rerun-backup-20261108.log` |
| 18 | nl-sw01 Te1/1/6 (a Po3 leg to nl-pve03) logs SFP "Voltage low" (3.04-3.06 V vs 3.10 V) 35-142 times a day since at least 09-22. That's the same warning Te1/1/3 logged before it died. Replace the module proactively (the SR-X order is pending) | P1 | S | 🔲 **to discuss** (IFRNLLEI01PRD-2996). Not a temperature issue (67.9 °C): Te1/1/6 is an OEM copper SFP-10G-T coded as SFP-10G-SR, and copper 10G draws more power than the port supplies (3.04 V). Recommendation: genuine Cisco SFP-10G-SR-X optics + fibre, or a DAC |
| 19 | Master-switch side effect: since 2026-08-26 (TG became primary) `~/gateway.maintenance` makes several gateway health scripts exit early. `budget-pppoe-health.sh` and `vps-route-health.sh` write nothing, and `intersite_autoheal.prom` is frozen with an old failed attempt, so `IntersiteAutohealFailed` fires permanently. Exempt read-only monitors from the switch, or retire them together with their alerts | P1 | S | ✅ **done 11-07**: the 3 read-only monitors run past the master switch again (alerting edge still suppressed); intersite heal metrics truthful, `IntersiteAutohealFailed` keys on `failure_open` and has cleared (!288, infra !684) |
| 20 | nl-fw01 Gi1/5 (Po1 member) counts giants. **Not outage-caused:** Freedom delivers inbound IP packets of 1493–1500 bytes over PPPoE although nl-fw01 negotiated 1492, and nl-fw01 drops them in hardware (proven with DF pings: IP 1492 replies, ≥1493 = one giant each). nl-sw01 dropped them at the ONT port until 2025-12-04 and nl-fw01 has since; the counting member follows the PPPoE MAC hash, and the 11-07 reboot only moved it from Gi1/7 to Gi1/5 | P2 | S | ✅ **closed 11-07, accepted** (operator): unchanged for ≥ 18 months, TCP protected by the MSS clamp, no user-visible effect (IFRNLLEI01PRD-2997) |
| 21 | notrf01dmz03-05 `etcd-snapshot-ship` failed 01:17-01:35 UTC 11-07 (target: NO backup gateway, pods ~13 h old). Confirm tonight's run | P2 | S | 🔲 check the 11-08 run |
| 22 | TG must model the nlpve04 RAM swap (nlgitlabrunner02 vs nlandroidsdk01/nlmacos01) instead of treating a stop as a crash | P1 | done | ✅ TG-654 live 13:14 NL; TG-652 (fail-closed on a failed actor read) is with the TG session |

---

## 9. Lessons recorded as standing rules

1. **Guests not auto-starting after a cold boot:** check pmxcfs `Unable to resolve node name` and `getent hosts` first (`feedback_pve_hosts_self_alias_cold_boot`).
2. **A host that "froze" with no kernel trace:** read the BMC SEL in-band (`/dev/ipmi0`) before guessing (`feedback_silent_host_freeze_read_bmc_sel`).
3. **Freedom ONT:** it is PoE-powered from nl-sw01 Gi1/0/36; the agent power-cycles it itself and never asks the operator (`freedom_ont_poe_recycle_gotcha_20260422`).
4. **Verify a DSM encrypted-share passphrase non-destructively** (`SYNO.Core.Share.Crypto.Key verify`); never test by unmounting a share that HA depends on (`reference_dsm_keymanager_automount_synowebapi`).
5. **TG approvals** come from the TG session directly to the operator, never relayed (`feedback_tg_approvals_direct_from_operator`).
6. **nlgitlabrunner02 off while nlandroidsdk01/nlmacos01 run = the RAM policy**, not a fault (TG-654).
7. **A late sub-mount is invisible inside a running container** unless the bind is `:rslave`; stage Pacemaker changes in a shadow CIB and run `crm_simulate` first (`feedback_docker_bind_rprivate_hides_late_submounts`).
8. **Cronicle has no automatic catch-up by default:** after nl-claude01 downtime, re-run the missed daily regenerators via `run_event`, and classify a failing job by its run history before calling it outage damage (`feedback_after_claude01_downtime_rerun_missed_cronicle`).

---

## 10. Appendix: verified state after recovery (sweep 2026-11-07 ~13:00-13:30)

Read-only sweep by four checkers plus the agent; every OUTAGE item below was re-checked before it was acted on or reported.

### Recovered and verified
- **Hypervisors:** quorum 4/6 (nl-pve01 gone, nl-pve02 off, both by design); all onboot guests running; TG-649 drop-in active.
- **Guests (both NL hosts):** every running LXC and VM checked at the service level: FreeIPA (9/9 services), Pi-hole, NPM (27 upstreams OK), Vaultwarden, Matrix, SMTP relays (queues empty), ProxySQL, Redis (master/replica + sentinel), Galera (3/Primary/Synced), HAProxy, FRR route reflectors (13/13 Established), OpenBao (unsealed), GitLab (11/11), n8n, YouTrack, InfluxDB, LibreNMS (poller + rrdcached), syslog-ng, Frigate (8/8 cameras), nl-gpu01 (Ollama ×2, rerank), servarr (incl. Music Assistant, 7/7 speakers), paops, Proton bridges, Nextcloud, OpenObserve/Healthchecks/Langfuse, PBS, Twenty, LiteLLM, WireGuard, the DMZ sites + Kener.
- **Storage:** NAS RAID + SMART clean, encrypted share mounted (auto-mount on), ZFS on all 4 hosts 0 new errors, FISHA NFS serving from nlcl01file02, PVCs bound, Velero locations Available.
- **Kubernetes:** NL 5/7 Ready (nlk8s-ctrl02 + nlk8s-node01 are on the gone nl-pve01), apiserver/etcd ready; GR and NO unchanged.
- **Network:** Freedom primary again (203.0.113.X, Track 1 Up); 27/27 tunnels, 227/227 BGP sessions; AS64512 visible to 311/311 RIS peers.

### Outage leftovers fixed during the sweep
- Re-ran the jobs missed while nl-claude01 was down: gateway DB backup, infragraph seed, interaction graph, audit metrics, synthetic canary, agora health notification (component registry back to 0 critical-dark).
- Re-ran the k8s cronjobs `awx-pg-dump` (NL) and `backup-gateway-canary` (NL), both Succeeded; NL Velero daily backup caught up (10:52 UTC, Completed).
- Re-ran the NL PBS pull-sync from grpbs02 (2 groups had failed with connection resets): TASK OK, 0 failed groups.

### Security scanners (checked 2026-11-07 ~17:00-17:30 NL, after the sweep)
- **nlsec01 has no 7 November run:** the VM is on nlpve04 and booted at 10:46; its cron fires at 03:00 UTC. Left alone; the next run is 8 November.
- **grsec01's 7 November report raised three HIGHs, all echoes of this outage:** `Scan target went dark` for 203.0.113.X and 203.0.113.X (its nmap ran 04:15-04:54, inside the Freedom outage) and `IPv6 surface unassessed` (its 04:15 query to nl-prometheus got no answer, so the check reported the gap, as designed). At 17:12 the ports answered from GR again and the query returned 159. The four returning ports are accepted in `policy.yaml`, so the 8 November run should clear all three. That run's nuclei IP pass (100%) skipped the Freedom URLs and is not a valid sample for IFRNLLEI01PRD-2977. YouTrack comments 5-38754 and 5-38755; infra `native/sec/CLAUDE.md` § Gotchas (`cdd7a4e9`).
- **nl-fw01 at 17:14:** up since 03:33; PPPoE up since the 16:10-16:13 drill; Track 1 changed state once more at about 17:13 with no PPPoE drop and no heal attempt (`freedom_ont_autoheal_attempts_total 0`): a drill by the claude-gateway session (operator), not an unexplained event.
- **Scanner log fix (same evening):** both scanners' `weekly-scan.sh` counted lines with `$(grep -c … || echo 0)`, which returns `0` twice when the count is 0 and logged `integer expression expected` on every clean run. Fixed on both (infra `e52e33f1`); proof is the 8 November `cron.log`.

### Pre-existing problems found (not caused by the outage; listed so they are not lost)
Each of these was verified as broken **before** 2026-11-06 20:24 UTC (dates in brackets).

- **Gatus NL + GR reds** (already failing at 19:55 UTC 11-06): Cilium BGP Sessions (3 < 4), IPsec Tunnels (query returns 0 < 16), Backup Gateway (Gatus probes an in-cluster URL; the gateway itself works, canaries pass on both sites), Velero UI (503; velero-ui CrashLoopBackOff on all 3 clusters), FISHA nlcl01file01 (on the gone nl-pve01).
- **`IntersiteAutohealFailed`** fired from a metrics file frozen since 2026-08-26 20:55. Cleared 11-07 by action 19.
- **Synthetic canary** 1/3 stages (classify + verify fail) for at least 25 daily runs.
- **Cronicle jobs failing on every run:** renovate-autonomy-metrics (since 11-06 05:30), renovate-reconcile (exit 127, since 11-04), faiss-index-sync (1 GB memory limit, since 11-04; **fixed 11-07, !298**: it had still finished each run as an orphaned child), renovate-deferred-merge-processor and disk-autogrow-scan (exit 127, since 10-29).
- **Guest hygiene:** `logrotate` fails on almost every LXC ("error in file terminal-sessions"); the healthops consume-feeder exits 1 whenever there is nothing to feed (pipefail); nl-gitlab01 snmpd binds `[::1]` with IPv6 disabled; nldocuseal01's caddy crash-loops with an empty `HOST` (since 2026-04-28; not in the serving path); nlcl01file02 `postfix@-` has no main.cf; nl-gpu01 and nlservarr01 still mount shares from the dead nl-nas02; Syncthing folder "Google Profile" has lost its folder marker.
- **NPM:** jellyfin (no container on nl-gpu01) and wireguard (nlwireguard01 not on a live host) return 502.
- **n8n:** RSS2Postiz errors every 10 minutes (Postiz is on the gone nl-pve01 since 10-04).
- **Network:** nl-sw01 had no syslog forwarding from 09-28 to 11-06; Po4 runs on one member ("NO CABLE", 08-08); the TEMP Te1/0/37 trunk for nl-pve01 is saved in startup-config (revert pending, IFRNLLEI01PRD-2871); txhou01vps01 `systemd-networkd` failed since 09-07; releases.cubeos.app answers 503 through chzrh01vps01 only (GR backend rate-limits that source).
- **GR:** gr-pve01 runs at load ~22 / 92 % RAM (up 71 days); GR backup-gateway logs a chronic broken-pipe pattern (since at least 11-04) and GR `awx-pg-dump` failed on earlier days too.
- **Platform (holistic check):** otel_spans/session_quality writers dark since ~08-26, spec↔code drift, always-on text over budget, 39 credentials past their rotation date, 12 skills changed without a version bump.
- **Known hardware:** nl-pve03 rpool mirror degraded (Kingston RMA, IFRNLLEI01PRD-2273).
- **Ghost doorbell rings** 11-07 13:48 / 14:48 / 15:28 NL (Honeywell wireless chime, no G4 press). Possibly related: on 11-06 the chime rang at every power return. Split out to IFRNLLEI01PRD-2998.
- **Home Assistant UniFi Protect integration** dead since 2026-09-17/22 (HA 2026.9 needs Protect ≥ 7.2.105, the Cloud Key runs 6.1.68): IFRNLLEI01PRD-2894, decision pending.
- **Knowledge base:** rows 6456-6462 in `incident_knowledge` carry this incident's findings and are searchable. `faiss-index-sync` had been marked failed on every run since 11-04 (Cronicle's 1 GB `job_memory_max`, 3.6 GB peak), but the Python child kept running after its shell was killed, so the index was still refreshed (29 of 29 runs completed after the 11-07 reboot). Fixed 11-07 (!298): rows are streamed into one float32 array (peak 559 MB) and index writes are atomic; the job exits 0 again.
- **Not checked:** Healthchecks.io check states (no read API key in `.env`); nl-claude01's own log forwarding to syslog-ng (no event since syslog-ng came back).
