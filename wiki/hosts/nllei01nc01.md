# nlnc01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:native/CLAUDE.md**
- nlnc01/nlnc02, nlcl01file01/nlcl01file02, filearb01, iot01/iot02, nlcl01iotarb01, hpb01, nl-gpu01 require explicit key:
- | **NCHA** (Nextcloud HA) | [`ncha/`](ncha/CLAUDE.md) | nlnc01, nlnc02 + 21 supporting hosts | 9-layer Nextcloud HA cluster: NPM → HAProxy → Apache+PHP → ProxySQL → Galera → Redis Sentinel → DRBD+OCFS2+NFS → FreeIPA → Synology NAS |

**nl:native/ncha/CLAUDE.md**
- ├─ 10.0.181.X  nlhaproxy01 (nl-pve01) — nlnc01 PRIMARY, nlnc02 BACKUP
- └─ 10.0.181.X  nlhaproxy02 (nl-pve03) — nlnc02 PRIMARY, nlnc01 BACKUP (cross-site)
- ├─ 10.0.181.X  nlnc01 (QEMU, nl-pve01) — PRIMARY
- ssh -i ~/.ssh/one_key root@nlnc01
- | nlhaproxy01 | VMID_REDACTED | nl-pve01 | 10.0.181.X | HAProxy 3.3.5. Frontends: HTTPS(:443), Redis(:6380), ProxySQL(:6034), Collabora(:9980), Stats(:8404). nlnc01=PRIMARY. |

**gateway:CLAUDE.md**
- - **Autonomy-forward gate — human as circuit-breaker, LIVE + ENABLED 2026-06-16 (epic IFRNLLEI01PRD-1102, merged to main `778406b`):** the operator stopped voting on the Matrix approval polls (notifications off), so the old binary `auto=risk==low` gate stranded ~56% of sessions on the 30-min pause and paged no one. Replaced with a 3-band model in `classify-session-risk.py`: **AUTO** (low or reversible+prediction-eligible MIXED → `[AUTO-RESOLVE]`), **AUTO_NOTICE** (reversible MIXED on a P0 host / wide blast → auto + parallel SMS), **POLL_PAUSE** (HIGH / irreversible / deviation / no-prediction / jailbreak / P0-reboot → poll+pause+SMS). New session→SMS path via `/alert-session` on the Twilio bridge (dedup by issue_id, HIGH-only per operator). Irreversible re-tagging closed real gaps (`terraform destroy` was MIXED; `mkfs`/`zpool destroy`/`dropdb` unmatched). **Enable/kill via sentinel files: `touch ~/gateway.autonomy_forward ~/gateway.autonomy_session_sms` = ON; `rm` = instant byte-identical-legacy revert** (no n8n edit). Safety floor (never auto): deviation/irreversible/no-prediction/partial/jailbreak — keyed on the fail-CLOSED -1044 prediction gate; band-aware weekly invariant in `audit-risk-decisions.sh`. Decisions vs plan: POLL_PROCEED folded into AUTO_NOTICE (no bridge surgery); verdict-gating is the pre-execution prediction gate (the match/partial/deviation verdict is post-execution). Runbook: [`docs/runbooks/risk-based-auto-approval.md`](docs/runbooks/risk-based-auto-approval.md) § Autonomy-forward gate. Full memory: [`memory/autonomy_forward_gate_20260616.md`](memory/autonomy_forward_gate_20260616.md). **Live-verified 2026-06-17 — first REAL Tier-2 auto-resolve: IFRNLLEI01PRD-1117 (nlnc01 Service up/down, critical) ran a genuine 26-turn claude-opus-4-8 session (conf 0.86), confirmed the host recovered, classified band=AUTO → reconcile → YT Done + `session_log.resolution_type=auto_resolved`. Gate discriminates correctly: 4 AUTO (low/read-only) vs 8 POLL_PAUSE since enablement — the high-risk seaweedfs OOM (-1113) correctly went POLL_PAUSE, not auto. Trace any auto-resolve via `grep <id> ~/logs/claude-gateway/pipeline-debug.log`.**

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-21 | Service up/down | recurred 6x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **autonomy-forward-gate-live-20260616** (project): "Autonomy-forward risk gate (3-band, human as circuit-breaker) is LIVE + ENABLED on nl-claude01 and merged to main; how to operate/kill it."
- **NFS exports managed by Pacemaker have no /etc/exports** (feedback): On clusters where exports are provisioned by an `ocf:heartbeat:exportfs` resource, NEVER run `exportfs -r` to refresh — it sees an empty /etc/exports and silently unexports everything. Use `pcs resource restart exportfs` instead.
- **HAHA chaos engineering catalog 2026-04-30 (~14 tests, 2 bugs surfaced+fixed)** (project): Same-day chaos engineering pass over the whole IoT infrastructure (HAHA + FISHA + sidecars + voice pipeline + cluster fencing). 14 tests run, 2 real bugs surfaced and 1 fixed (nodered start timeout 90s→180s); 1 outstanding (fence_pve list TypeError, IFRNLLEI01PRD-806). Empirical confidence table inside.
- **HAHA reliability hardening 2026-04-30 (Phases 1-5 implemented)** (project): Same-day follow-up after the 2026-04-27 → 2026-04-30 ~66h HAHA outage. App-level OCF docker monitor_cmd, NFS auto-flush, NFS stale-fh exporter, proactive ARP, host-pressure alerts, Twilio escalation. T1 e2e verified: 18s detect, 3m30s recover.
- **Corosync cluster split incident 2026-04-11** (project): PVE 5-node cluster split — stale ASA conn table routed nl-pve01 knet via outside_freedom instead of VTI. Fixed by clear conn + timeout floating-conn on both ASAs.
- **GR Site Isolation 2026-04-17 (stale IPsec SA)** (project): NL↔GR VTI/BGP break 2026-04-17 ~05:23 UTC. Root cause = stale IPsec SA on Tunnel4 (Freedom VTI). Fix = `clear crypto ipsec sa peer 203.0.113.X` on NL ASA. Resolved 08:48 UTC.
- **HAHA NFS stale-fh outage 2026-04-27 → 2026-04-30 (RESOLVED, ~66h 39m)** (project): Home Assistant down 2026-04-27 14:55 → 2026-04-30 09:34 UTC (~66h 39m). HA Python crashed with Bus error during nfs-group migration; container kept running so Pacemaker never noticed. Apr 30 02:15 weekly-update reboot exposed nlcl01file02 fh-cache poisoning. Fixed by restarting Pacemaker exportfs resource.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout

*Compiled: 2026-07-03 04:30 UTC*