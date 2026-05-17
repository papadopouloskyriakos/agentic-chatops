# nl-dmz01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- 3b. **Edge: no automation** — same as native. The VPS (chzrh01vps01, notrf01vps01) and DMZ (nl-dmz01/02, gr-dmz01/02) hosts run critical public-facing services (HAProxy, FRR, strongSwan, CrowdSec, Django app on agri.meshsat.org) with no scheduled drift detection and no deploy pipeline. Manual re-snapshot after incidents or config changes is the only way to keep `edge/` in sync.

**nl:edge/CLAUDE.md**
- ├─ nl-dmz01: portfolio, cubeos-*, mulecube-*, umami (NL only), withelli, withelli-beta, meshsat-hub
- │   ├── nl-dmz01/             — Netherlands, Leiden (QEMU on pve01)
- | nl-dmz01 | Leiden, NL | 10.0.X.X/27 | 21 (DMZ) | pve01 | VMID_REDACTED | Ubuntu 24.04 | portfolio, cubeos-website, cubeos-demo, cubeos-releases, umami (+nginx +postgres), mulecube, mulecube-dashboard, meshsat-hub |
- **NL-only service:** Umami analytics (analytics.cubeos.app) — runs only on nl-dmz01.
- ssh -i ~/.ssh/one_key operator@nl-dmz01

**gr:edge/CLAUDE.md**
- **Note:** NL DMZ (nl-dmz01) has the same services plus Umami analytics (NL-only).

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-15 | chaos-dmz |  | Chaos finding (chaos-2026-04-15-004): Error budget consumpti | 0.8 |
| 2026-04-14 | chaos-dmz |  | Chaos finding (chaos-2026-04-13-016): Convergence 300.0s exc | 0.8 |
| 2026-04-14 | chaos-dmz |  | Chaos finding (chaos-2026-04-14-002): Error budget consumpti | 0.8 |

## Related Memory Entries

- **cert-sync playbook — visible unreachable-host banner 2026-04-17** (project): Added observability banner to sync_certs_to_edge.yml so ignore_unreachable skips are no longer silent. Commit 328c6f7.
- **chaos_baseline_metrics_fix_20260416** (project): Chaos baseline comparison fixed (2026-04-16). Was comparing convergence (~37s) vs wall-clock (~136s) = always SLOW. Now uses recovery_seconds. IP tracking added. Live log race fixed.
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **Never truncate or shorten hostnames anywhere** (feedback): STRICT P0 rule. Always full site-prefixed hostnames (notrf01dmz01, notrf01dmz02, nl-pve01, gr-fw01). NEVER dmz01/dmz02/the dmz host/pve01/the asa. No brace-expansion shortcuts in prose either.
- **DMZ disk-full pipeline break + resize to 128G + cleanup cron 2026-04-17** (project): gr-dmz01 / 100% full blocked Ansible tmp-dir creation, producing recurring UNREACHABLE across all portfolio deploy pipelines. Resized both DMZ VMs 64->128G and installed daily cleanup cron.
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 pve01 memory pressure class.
- **notrf01dmz01 + notrf01dmz02 onboarding — in flight 2026-05-05** (project): Two new public-IP DMZ Docker hosts at Gigahost NO. Unit 1+2+3 done (hardening, UFW, full 6-tunnel IPsec mesh including xs4all via rtr01). Unit 4 (FRR + iBGP) partially up — 3/8 BGP peers established. Plan at /home/app-user/.claude/plans/wobbly-snacking-biscuit.md.
- **nl-pve01 memory pressure causing apiserver restarts** (project): PVE01 host 88% RAM (2.5x overcommit, zero swap) starved etcd I/O on ctrl01. 754 apiserver restarts. Mitigated by shutting down androidsdk01.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **security_alert_receivers** (project): Security + CrowdSec alert pipelines (4 workflows, 6 CrowdSec hosts), scanner VMs, triage skill (10 steps, 3 TI sources), learning loop, baseline polls, ATT&CK Navigator. 2026-04-07: YT descriptions use markdown tables, triage delegation structured messages, 8 IF node singleValue fixes.
- **VPS DMZ /27 route is now BGP-driven (not static) on both VPSs** (project): Removed `ip route add 10.0.X.X/27 dev xfrm-nl-f/xfrm-nl` lines from /etc/systemd/system/swanctl-loader.service on notrf01vps01 + chzrh01vps01. FRR now installs the /27 via BGP (proto bgp metric 20 via 10.0.X.X). BFD-driven sub-second failover now actually works for DMZ service traffic.

*Compiled: 2026-05-06 00:48 UTC*