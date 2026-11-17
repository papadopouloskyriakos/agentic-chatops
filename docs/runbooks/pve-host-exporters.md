# PVE host Prometheus exporters (pve-exporter :9221 + node_exporter :9100)

**LIVE 2026-08-25** on all 5 live PVE hosts of `eu-nlgr-pvecl01`:
nl-pve01 (10.0.181.X), nl-pve03 (.25), nlpve04 (.27),
gr-pve01 (10.0.X.X), gr-pve02 (.28). nl-pve02 is POWERED OFF
by design (5/6 baseline, IFRNLLEI01PRD-2646) — deliberately NOT a target.

Closes the zero-PVE-Prometheus-coverage gap: before this, no PVE host was a
Prometheus target and the `PVEMemoryPressure*`/`PVELoadHigh` rules were inert
(the only host signal was the SSH `pve_wedge_*` collector, which stays — its
D-state/pmxcfs-probe canary sees what load/memory series cannot).

## Components

| Piece | Where | What |
|---|---|---|
| `scripts/pve-host-exporters-install.sh` | this repo | Idempotent installer + `--check` drift-check, streamed over SSH (nothing copied to the host) |
| prometheus-pve-exporter **3.10.0** (pinned) | each host, venv `/opt/prometheus-pve-exporter`, unit `prometheus-pve-exporter.service`, user `pve-exporter` | Serves `/pve?cluster=1&node=0` on `<mgmt-ip>:9221` |
| prometheus-node-exporter (Debian pkg) | each host, `/etc/default/prometheus-node-exporter` | `<mgmt-ip>:9100`, PSI/zfs/systemd/processes collectors, textfile dir `/var/lib/prometheus/node-exporter` |
| API identity | cluster-wide (pmxcfs) | `prometheus@pve` + token `pve-exporter` (privsep=1), both with `PVEAuditor` at `/` — same idiom as `pulse@pam!pulse` / `influx@pam!monitoring`. Secret: `~/.config/gateway/pve-exporter.token` (0600) + `.env` `PVE_EXPORTER_TOKEN`; on each host in `/etc/prometheus/pve.yml` (0640 root:pve-exporter) |
| Scrape jobs `pve-exporter`, `pve-node-exporter` | **PER-SITE since 2026-08-26** (NL !521 / GR !133 / NO !32): canonical gated jobs in `k8s/namespaces/monitoring/main.tf` driven by `var.pve_hosts` in each site tfvars (NL = 3 hosts, GR = 2, NO = []) — each cluster scrapes its OWN hosts, partition-resilient both ways | instance = full hostname, site label = var.site |
| Alerts | split 2026-08-26: SITE-LOCAL liveness + pressure in canonical `pve-host-alerts.tf` (count-gated on `var.pve_hosts`, evaluated per site; **includes the `/ on (instance)` PVELoadHigh fix — the April-era expression could never match**); CLUSTER-VIEW group `pve-exporter` stays NL-only in `host-pressure-alerts.tf` (single evaluation); since 2026-11-04 that group also has `PVEGuestRootfsNearFull` (>0.85, 30m) / `PVEGuestRootfsCriticallyFull` (>0.92, 10m) on every LXC rootfs (`pve_disk_usage_bytes / pve_disk_size_bytes`, LXC only; thresholds below 1.0 because ext4's 5% root reserve fails non-root writes at ~0.95; IFRNLLEI01PRD-2983, infra !674) | test/doc copy: `prometheus/alert-rules/pve-host-health.yml` (+`.test.yml`, QA test-726) |
| Dashboard | `dashboards/proxmox-via-prometheus.json` (grafana.com 10347 rev5, uid `pve-exporter-10347`) | Grafana → "Proxmox via Prometheus (pve-exporter)" |

## The one non-obvious design fact

pve-exporter 3.x groups status/version/node/resources/backup-info as
**"cluster collectors"** (`?cluster=1`) — the `?node=1` group is only
config/replication/subscription, all deliberately disabled here (`config`
walks every guest config = one pmxcfs read per guest, ~200 on this cluster).
So **every host serves the WHOLE cluster view** (~236 `pve_up` ids, ~3.5k
series/host): cluster-view rules MUST dedup with `max by (id)` /
`max by (storage)` — and they are evaluated on NL ONLY (evaluating them on
both sites would double every alert). Site-local rules (`up{}`, node_exporter
pressure) are per-cluster by nature and live in the canonical
`pve-host-alerts.tf`. Per-host `scrape_duration_seconds{job="pve-exporter"}` doubles as
that host's API/pmxcfs responsiveness canary.

## Operations

```bash
# drift-check one host (read-only, exit 1 on drift)
ssh -i ~/.ssh/one_key root@nl-pve03 'bash -s -- --check' < scripts/pve-host-exporters-install.sh

# reinstall / converge (token only rewritten when supplied)
ssh -i ~/.ssh/one_key root@nl-pve03 \
  "PVE_EXPORTER_TOKEN='$(cat ~/.config/gateway/pve-exporter.token)' bash -s -- install" \
  < scripts/pve-host-exporters-install.sh

# rotate the token (on any healthy node; pveum is cluster-wide)
ssh -i ~/.ssh/one_key root@nl-pve03 \
  "pveum user token remove prometheus@pve pve-exporter && \
   pveum user token add prometheus@pve pve-exporter --privsep 1 --output-format json && \
   pveum aclmod / -token 'prometheus@pve!pve-exporter' -role PVEAuditor"
# then: update ~/.config/gateway/pve-exporter.token + .env, re-run install on all 5 hosts
```

## Rollback

Per host: `systemctl disable --now prometheus-pve-exporter prometheus-node-exporter`.
Revert the scrape/alert MRs (infra !517 + the per-site trio NL !521 / GR !133 / NO !32 — canonical, revert in all 3 repos). Remove the identity:
`pveum user token remove prometheus@pve pve-exporter && pveum user delete prometheus@pve`.

## Gotchas

- **nlpve04 had a stray unit-less `/usr/local/bin/node_exporter`**
  (and nl-pve03 too) — the installer kills those before enabling the
  packaged unit. If :9100 answers but `systemctl is-active
  prometheus-node-exporter` is inactive, a stray came back.
- Exporters bind the **mgmt IP only** — the installer refuses to run if the
  host's `/etc/hosts` self-entry is not an inside_mgmt address, and `--check`
  FAILs if anything listens on 0.0.0.0:9100/:9221.
- During a pmxcfs wedge the PVE API hangs → pve-exporter scrapes time out
  (job timeout 50s). That is signal, not breakage: `PVEExporterDown` +
  rising `scrape_duration_seconds` for that instance, while the other 4
  reporters keep the cluster-view rules alive.
- `pveum` writes go through pmxcfs — do identity operations on a healthy
  node, never on a wedged one.
- Day-one known-firing state (2026-08-25): `PVEStorageNearFull` for
  `nlpbs01` + `nlpvecl01-nfs` (85.7%) and `PVEGuestNotBackedUp` = 9 —
  genuine findings, not rollout noise.
- Day-one known-firing state of the rootfs rules (2026-11-04): `PVEGuestRootfsNearFull`
  for nlinfluxdb01 (0.895) — genuine; cleared the same day by growing its rootfs
  100G → 150G (its InfluxDB bucket has no retention, ~1.3 GB/week). nl-gitlab01 peaked at 0.955 the same
  morning (disk full, GitLab HTTP 500), which is what the rules were written for.

## In-band BMC SEL exporter (nlpve04, since 2026-11-07, IFRNLLEI01PRD-2992)

On 2026-11-07 06:25:37 UTC nlpve04 (ASRock GENOAD8X-2T/BCM) halted on a PCI SERR from its
BCM57416 10 G NIC (bus 05, both bond0 legs). Firmware-first error handling left no kernel trace;
the BMC System Event Log was the only evidence. `scripts/pve-sel-exporter.py` reads that log
in-band through `/dev/ipmi0` (ipmi_devintf ioctls, read-only: Get SEL Info / Time / Entry, never
clear, never set the clock) so no package is installed on the host.

| Piece | Where |
|-------|-------|
| script | `/usr/local/bin/pve-sel-exporter.py` (from `scripts/pve-sel-exporter.py`) |
| units | `/etc/systemd/system/pve-sel-exporter.{service,timer}` (from `scripts/systemd/`), root, every 5 min + 2 min after boot |
| output | `/var/lib/prometheus/node-exporter/pve_sel.prom` → job `pve-node-exporter` |
| state | `/var/lib/pve-sel-exporter/state.json` (first-seen time per SEL record) |
| alerts | `PVEBMCCriticalEvent` (critical, tier 2 = ntfy quiet topic, never rings; operator 2026-11-07), `PVESelExporterStale` (warning): IaC `k8s/namespaces/monitoring/galera-sel-alerts.tf`, test copy `prometheus/alert-rules/galera-sel.yml` |

Deploy or update (also to another PVE host with a BMC; check `ls /dev/ipmi0` first):

```bash
scp -i ~/.ssh/one_key scripts/pve-sel-exporter.py root@nlpve04:/usr/local/bin/pve-sel-exporter.py
scp -i ~/.ssh/one_key scripts/systemd/pve-sel-exporter.{service,timer} root@nlpve04:/etc/systemd/system/
ssh -i ~/.ssh/one_key root@nlpve04 'chmod 755 /usr/local/bin/pve-sel-exporter.py && systemctl daemon-reload && systemctl enable --now pve-sel-exporter.timer && systemctl start pve-sel-exporter.service'
```

Read the SEL by hand: `python3 /usr/local/bin/pve-sel-exporter.py --stdout` (metrics, plus the newest
critical record per type on stderr) or `--dump` (raw records as hex JSON).

Timestamps: the BMC clock is not UTC-stable. Each host boot logs a clock-sync pair (System Event
offset 5, data2 `00` before / `80` after) that sets it to UTC; later the BMC drifts to its own
offset (+2 h on nlpve04, exported as `pve_sel_bmc_clock_offset_seconds`); after an AC loss
the RTC restarts at 2000-01-01 or 2022-01-01. `pve_sel_last_critical_event_timestamp_seconds` is a
best-effort UTC event time; `PVEBMCCriticalEvent` keys on `pve_sel_last_critical_seen_timestamp_seconds`
(host clock, first sight of the record) instead. The first run seeds every record that already
exists with its event time, so a deploy (or a lost state file) never fires the alert, and an
event logged while the host was hung fires once the host is back.

Not covered: correctable errors (bus correctable, correctable MCE) are counted in
`pve_sel_records` but never alert; a full SEL drops new events (`pve_sel_free_bytes`).
