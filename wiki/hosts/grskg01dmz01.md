# gr-dmz01

**Site:** GR (Skagkia)

## Knowledge Base References

**nl:CLAUDE.md**
- 3b. **Edge: no automation** — same as native. The VPS (chzrh01vps01, notrf01vps01) and DMZ (nl-dmz01/02, gr-dmz01/02) hosts run critical public-facing services (HAProxy, FRR, strongSwan, CrowdSec, Django app on agri.meshsat.org) with no scheduled drift detection and no deploy pipeline. Manual re-snapshot after incidents or config changes is the only way to keep `edge/` in sync.

**nl:edge/CLAUDE.md**
- ├─ gr-dmz01: portfolio, cubeos-*, mulecube-*, withelli, withelli-beta, meshsat-hub (GR mirror)
- │   ├── gr-dmz01/             — Greece, Thessaloniki (QEMU on GR pve01)
- | gr-dmz01 | Thessaloniki, GR | 10.0.X.X/27 | 12 (DMZ) | GR pve01 | 201121301 | Ubuntu 24.04 | portfolio, cubeos-website, cubeos-demo, cubeos-releases, mulecube, mulecube-dashboard, meshsat-hub |
- ssh -i ~/.ssh/one_key operator@gr-dmz01
- ### gr-dmz01 (GR) — 16 containers

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

- **cert-sync playbook — visible unreachable-host banner 2026-04-17** (project): Added observability banner to sync_certs_to_edge.yml so ignore_unreachable skips are no longer silent. Commit 328c6f7.
- **chaos_baseline_metrics_fix_20260416** (project): Chaos baseline comparison fixed (2026-04-16). Was comparing convergence (~37s) vs wall-clock (~136s) = always SLOW. Now uses recovery_seconds. IP tracking added. Live log race fixed.
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **feedback_gr_dmz_direct_ssh** (feedback): GR DMZ (gr-dmz01) — use direct SSH via VPN, NOT OOB stepstone
- **Never truncate or shorten hostnames anywhere** (feedback): STRICT P0 rule. Always full site-prefixed hostnames (notrf01dmz01, notrf01dmz02, nl-pve01, gr-fw01). NEVER dmz01/dmz02/the dmz host/pve01/the asa. No brace-expansion shortcuts in prose either.
- **DMZ disk-full pipeline break + resize to 128G + cleanup cron 2026-04-17** (project): gr-dmz01 / 100% full blocked Ansible tmp-dir creation, producing recurring UNREACHABLE across all portfolio deploy pipelines. Resized both DMZ VMs 64->128G and installed daily cleanup cron.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **NAT/PAT Audit 2026-04-09** (project): Tri-WAN PAT completed on NL ASA (28 rules). GR ASA NAT_dmz_servers02 /29→/27 fix. Both saved.
- **security_alert_receivers** (project): Security + CrowdSec alert pipelines (4 workflows, 6 CrowdSec hosts), scanner VMs, triage skill (10 steps, 3 TI sources), learning loop, baseline polls, ATT&CK Navigator. 2026-04-07: YT descriptions use markdown tables, triage delegation structured messages, 8 IF node singleValue fixes.

*Compiled: 2026-05-06 00:48 UTC*