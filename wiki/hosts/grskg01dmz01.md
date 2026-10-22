# gr-dmz01

**Site:** GR (Skagkia)

## Knowledge Base References

**nl:CLAUDE.md**
- 3b. **Edge: no automation** — same as native. The VPS (chzrh01vps01, notrf01vps01) and DMZ (nl-dmz01/02, gr-dmz01/02) hosts run critical public-facing services (HAProxy, FRR, strongSwan, CrowdSec, Django app on agri.meshsat.org) with no scheduled drift detection and no deploy pipeline. Manual re-snapshot after incidents or config changes is the only way to keep `edge/` in sync.

**nl:edge/CLAUDE.md**
- ├─ gr-dmz01: portfolio, cubeos-*, mulecube-*, withelli, withelli-beta, meshsat-hub (GR mirror)
- │   ├── gr-dmz01/             — Greece, Thessaloniki (QEMU on GR gr-pve01)
- | gr-dmz01 | Thessaloniki, GR | 10.0.X.X/27 | 12 (DMZ) | GR gr-pve01 | 201121301 | Ubuntu 24.04 | portfolio, cubeos-website, cubeos-demo, cubeos-releases, mulecube, mulecube-dashboard, meshsat-hub |
- ssh -i ~/.ssh/one_key operator@gr-dmz01
- ### gr-dmz01 (GR) — 24 live containers (verified 2026-06-19)

**gr:docker/CLAUDE.md**
- **Note**: gr-dmz01 (7 containers) is a QEMU VM, not an LXC — SSH access requires `operator` user with sudo. Not yet integrated into the pipeline.

**gr:pve/CLAUDE.md**
- | gr-dmz01 | QEMU | gr-pve01 | DMZ Docker host (10.0.X.X) |

**gr:edge/CLAUDE.md**
- ### DMZ Docker Host (gr-dmz01)
- ssh -i ~/.ssh/one_key operator@gr-dmz01
- 3. **Check GR DMZ containers:** `ssh operator@gr-dmz01 "sudo docker ps"` — all 7 containers should be Up
- - **GR DMZ service configs:** `infrastructure/nl/production/edge/dmz/gr-dmz01/` (NL repo)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-15 | chaos-dmz |  | Chaos finding (chaos-2026-04-15-005): Error budget consumpti | 0.8 |
| 2026-04-14 | chaos-dmz |  | Chaos finding (chaos-2026-04-13-014): Experiment verdict FAI | 0.8 |
| 2026-04-13 | chaos-dmz |  | Chaos finding (chaos-2026-04-13-014): Experiment verdict FAI | 0.8 |

## Related Memory Entries

- **awx-default-group-zero-capacity-20260620** (project): "2026-06-20 NL AWX default instance-group capacity=0 → all kyriakos portfolio deploys stuck pending → CI timeout. Infra outage, not a code bug."
- **cert-sync playbook — visible unreachable-host banner 2026-04-17** (project): Added observability banner to sync_certs_to_edge.yml so ignore_unreachable skips are no longer silent. Commit 328c6f7.
- **chaos_baseline_metrics_fix_20260416** (project): Chaos baseline comparison fixed (2026-04-16). Was comparing convergence (~37s) vs wall-clock (~136s) = always SLOW. Now uses recovery_seconds. IP tracking added. Live log race fixed.
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **dmz-container-count-zero-baked-20260513** (project): "Status page shows DMZ host 0/0 containers in user's normal browser but 30/30 in incognito — stale browser cache of an HTML that baked containers_total=0 when ssh failed in vpn-mesh-stats.py"
- **feedback-check-working-case-before-writing-refresh-code** (feedback): "When fixing a \"stuck SVG / stale UI\" bug, look at the case that already works correctly in the same code path before writing a new refresh block — the existing pattern usually IS what you should extend."
- **feedback-diagnose-deploy-hang-on-host-process-tree-first** (feedback): "When a deploy/Ansible task hangs on a specific host, read the host's process tree FIRST (ps wchan) instead of theorizing about the network."
- **feedback_gr_dmz_direct_ssh** (feedback): GR DMZ (gr-dmz01) — use direct SSH via VPN, NOT OOB stepstone
- **Never truncate or shorten hostnames anywhere** (feedback): STRICT P0 rule. Always full site-prefixed hostnames (notrf01dmz01, notrf01dmz02, nl-pve01, gr-fw01). NEVER dmz01/dmz02/the dmz host/pve01/the asa. No brace-expansion shortcuts in prose either.
- **gr_grk8s-ctrl01_etcd_gr-pve01_saturation_rca_20260623** (project): "2026-06-23 RCA of the GR etcd disk-I/O cascade behind the 91-SMS storm — root cause is chronic gr-pve01 host saturation + a thermally-throttling (SMART-clean, NOT failing) rpool mirror disk nvme2n1, NOT a ctrl01-specific fault. See VERIFIED UPDATE 2026-06-24 — the disk is overheating, not degraded; fix=cooling not replacement."
- **DMZ disk-full pipeline break + resize to 128G + cleanup cron 2026-04-17** (project): gr-dmz01 / 100% full blocked Ansible tmp-dir creation, producing recurring UNREACHABLE across all portfolio deploy pipelines. Resized both DMZ VMs 64->128G and installed daily cleanup cron.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, grdmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **NAT/PAT Audit 2026-04-09** (project): Tri-WAN PAT completed on NL ASA (28 rules). GR ASA NAT_dmz_servers02 /29→/27 fix. Both saved.
- **notrf01dmz01 + notrf01dmz02 onboarding — DONE 2026-05-05** (project): Two new public-IP DMZ Docker hosts at Gigahost NO. Active/active SaaS pre-staging complete. Full 6-tunnel mesh + 8/8 iBGP peers established per host. Source of truth = handoff doc. Status page diagram updated 2026-05-06.
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.
- **security_alert_receivers** (project): Security + CrowdSec alert pipelines (4 workflows, 6 CrowdSec hosts), scanner VMs, triage skill (10 steps, 3 TI sources), learning loop, baseline polls, ATT&CK Navigator. 2026-04-07: YT descriptions use markdown tables, triage delegation structured messages, 8 IF node singleValue fixes.
- **xe-gr-waf-camoufox-blocked-20260531** (project): "xe.gr's AWS WAF (deployed 2026-05-30) blocks the Scrapling/Camoufox stealth browser at the same HTTP 405 as reqwest. Native Firefox UA gets HTTP 200 + JS challenge HTML; Camoufox via our sidecar gets straight 405. Adapter permanently kill-switched until a different bypass (Playwright with manual fingerprint, residential proxy, or upstream-officially-permitted API) is found."

*Compiled: 2026-07-03 04:30 UTC*