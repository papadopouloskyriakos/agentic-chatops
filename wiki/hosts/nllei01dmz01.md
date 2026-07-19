# nl-dmz01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- 3b. **Edge: no automation** — same as native. The VPS (chzrh01vps01, notrf01vps01) and DMZ (nl-dmz01/02, gr-dmz01/02) hosts run critical public-facing services (HAProxy, FRR, strongSwan, CrowdSec, Django app on agri.meshsat.org) with no scheduled drift detection and no deploy pipeline. Manual re-snapshot after incidents or config changes is the only way to keep `edge/` in sync.

**nl:edge/CLAUDE.md**
- ├─ nl-dmz01: portfolio, cubeos-*, mulecube-*, umami (NL only), withelli, withelli-beta, meshsat-hub
- ├─ nldmz02: (baseline only, no services yet — headroom for moving services off nl-dmz01)
- │   ├── nl-dmz01/             — Netherlands, Leiden (QEMU on nl-pve01)
- | nl-dmz01 | Leiden, NL | 10.0.X.X/27 | 21 (DMZ) | nl-pve01 | VMID_REDACTED | Ubuntu 24.04 | portfolio, cubeos-website, cubeos-demo, cubeos-releases, umami (+nginx +postgres), mulecube, mulecube-dashboard, meshsat-hub |
- **NL-only service:** Umami analytics (analytics.cubeos.app) — runs only on nl-dmz01.

**gr:edge/CLAUDE.md**
- **Note:** NL DMZ (nl-dmz01) has the same services plus Umami analytics (NL-only).

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-15 | chaos-dmz |  | Chaos finding (chaos-2026-06-15-002): Convergence 300.0s exc | 0.8 |
| 2026-04-15 | chaos-dmz |  | Chaos finding (chaos-2026-04-15-004): Error budget consumpti | 0.8 |
| 2026-04-14 | chaos-dmz |  | Chaos finding (chaos-2026-04-13-016): Convergence 300.0s exc | 0.8 |
| 2026-04-14 | chaos-dmz |  | Chaos finding (chaos-2026-04-14-002): Error budget consumpti | 0.8 |

## Related Memory Entries

- **apiserver-ctrl01-balloon-chronic-restart-fixed-20260515** (project): "RESOLVED 2026-05-15. nlk8s-ctrl01's kube-apiserver had restartCount=1665 (~27 days of crash-looping, ~24-min cycle). Root cause was the balloon device on the underlying VM (VMID_REDACTED on nlpve04) inflating during host pressure events, leaving the VM with only 3.7 GiB instead of 8 GiB. etcd's WAL/DB page cache got evicted → fsyncs disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kill → restart. Fix: `qm set --balloon 0` + VM reboot to apply [PENDING] (config change cannot live-remove a balloon device)."
- **awx-default-group-zero-capacity-20260620** (project): "2026-06-20 NL AWX default instance-group capacity=0 → all kyriakos portfolio deploys stuck pending → CI timeout. Infra outage, not a code bug."
- **cert-sync playbook — visible unreachable-host banner 2026-04-17** (project): Added observability banner to sync_certs_to_edge.yml so ignore_unreachable skips are no longer silent. Commit 328c6f7.
- **chaos_baseline_metrics_fix_20260416** (project): Chaos baseline comparison fixed (2026-04-16). Was comparing convergence (~37s) vs wall-clock (~136s) = always SLOW. Now uses recovery_seconds. IP tracking added. Live log race fixed.
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **dmz-container-count-zero-baked-20260513** (project): "Status page shows DMZ host 0/0 containers in user's normal browser but 30/30 in incognito — stale browser cache of an HTML that baked containers_total=0 when ssh failed in vpn-mesh-stats.py"
- **feedback-check-working-case-before-writing-refresh-code** (feedback): "When fixing a \"stuck SVG / stale UI\" bug, look at the case that already works correctly in the same code path before writing a new refresh block — the existing pattern usually IS what you should extend."
- **Never truncate or shorten hostnames anywhere** (feedback): STRICT P0 rule. Always full site-prefixed hostnames (notrf01dmz01, notrf01dmz02, nl-pve01, gr-fw01). NEVER dmz01/dmz02/the dmz host/pve01/the asa. No brace-expansion shortcuts in prose either.
- **feedback-systemd-user-slice-oom-score** (feedback): "systemd `--user` (per-user) services run with `oom_score_adj=200` by default. That makes them the kernel's preferred OOM-killer victims even though their RSS is tiny. Critical-path services (Tier-1 SMS, paging, escalation bridges) MUST NOT run as `--user` systemd units — they will die first during any host-pressure event, exactly when you need them most."
- **HAHA chaos engineering catalog 2026-04-30 (~14 tests, 2 bugs surfaced+fixed)** (project): Same-day chaos engineering pass over the whole IoT infrastructure (HAHA + FISHA + sidecars + voice pipeline + cluster fencing). 14 tests run, 2 real bugs surfaced and 1 fixed (nodered start timeout 90s→180s); 1 outstanding (fence_pve list TypeError, IFRNLLEI01PRD-806). Empirical confidence table inside.
- **DMZ disk-full pipeline break + resize to 128G + cleanup cron 2026-04-17** (project): gr-dmz01 / 100% full blocked Ansible tmp-dir creation, producing recurring UNREACHABLE across all portfolio deploy pipelines. Resized both DMZ VMs 64->128G and installed daily cleanup cron.
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by nl-pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 nl-pve01 memory pressure class.
- **librenms-extender-fleet-deployment-20260515** (project): "2026-05-15 fleet-wide LibreNMS extender deployment and hardening. nlpve04 got all 7 extenders from scratch (was bare). proxmox-extender switched to smart-style cache pattern on all 6 PVE hosts to bypass the /etc/pve/priv/authkey.key root-only requirement. apcupsd installed on nl-pve03+nlpve04 (shared SNMP UPS at 10.0.181.X). smart.config fleet sweep found stale gr-pve01 header on nl-pve01+nl-pve03 (now fixed) and empty config on gr-pve02 (5 disks now monitored, incl 2 MegaRAID)."
- **notrf01dmz01 + notrf01dmz02 onboarding — DONE 2026-05-05** (project): Two new public-IP DMZ Docker hosts at Gigahost NO. Active/active SaaS pre-staging complete. Full 6-tunnel mesh + 8/8 iBGP peers established per host. Source of truth = handoff doc. Status page diagram updated 2026-05-06.
- **nl-pve01 memory pressure causing apiserver restarts** (project): PVE01 host 88% RAM (2.5x overcommit, zero swap) starved etcd I/O on nlk8s-ctrl01. 754 apiserver restarts. Mitigated by shutting down androidsdk01.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **security_alert_receivers** (project): Security + CrowdSec alert pipelines (4 workflows, 6 CrowdSec hosts), scanner VMs, triage skill (10 steps, 3 TI sources), learning loop, baseline polls, ATT&CK Navigator. 2026-04-07: YT descriptions use markdown tables, triage delegation structured messages, 8 IF node singleValue fixes.
- **VPS DMZ /27 route is now BGP-driven (not static) on both VPSs** (project): Removed `ip route add 10.0.X.X/27 dev xfrm-nl-f/xfrm-nl` lines from /etc/systemd/system/swanctl-loader.service on notrf01vps01 + chzrh01vps01. FRR now installs the /27 via BGP (proto bgp metric 20 via 10.0.X.X). BFD-driven sub-second failover now actually works for DMZ service traffic.

*Compiled: 2026-07-03 04:30 UTC*