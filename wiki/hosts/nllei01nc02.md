# nlnc02

**Site:** NL (Leiden)

## Knowledge Base References

**nl:native/CLAUDE.md**
- nlnc01/nlnc02, nlcl01file01/nlcl01file02, filearb01, iot01/iot02, nlcl01iotarb01, hpb01, nl-gpu01 require explicit key:
- | **NCHA** (Nextcloud HA) | [`ncha/`](ncha/CLAUDE.md) | nlnc01, nlnc02 + 21 supporting hosts | 9-layer Nextcloud HA cluster: NPM → HAProxy → Apache+PHP → ProxySQL → Galera → Redis Sentinel → DRBD+OCFS2+NFS → FreeIPA → Synology NAS |

**nl:native/ncha/CLAUDE.md**
- ├─ 10.0.181.X  nlhaproxy01 (nl-pve01) — nlnc01 PRIMARY, nlnc02 BACKUP
- └─ 10.0.181.X  nlhaproxy02 (nl-pve03) — nlnc02 PRIMARY, nlnc01 BACKUP (cross-site)
- └─ 10.0.181.X  nlnc02 (QEMU, nl-pve03) — BACKUP
- ssh -i ~/.ssh/one_key root@nlnc02
- | nlhaproxy02 | VMID_REDACTED | nl-pve03 | 10.0.181.X | HAProxy 3.3.5. Same frontends, nlnc02=PRIMARY (cross-site failover). |

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-21 | Service up/down | recurred 7x in 30d without durable fix | analysis-only pending root-cause | N/A |
| 2026-04-03 | Service up/down. |  | Resolved via Claude session IFRNLLEI01PRD-336 | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-336**: Nextcloud (nlnc02) service up/down is often caused by PHP-FPM pool exhaustion or MariaDB connection limits. Check systemctl status php-fpm and mariadb connections.

## Related Memory Entries

- **gpu01-target-ram-32g** (feedback): "Operator's chosen RAM allocation for nl-gpu01 is 32 GiB (32768 MB), not the historical 28 GiB. Don't argue this down to 28 G citing nl-pve03 host pressure — operator owns the trade-off."
- **NFS exports managed by Pacemaker have no /etc/exports** (feedback): On clusters where exports are provisioned by an `ocf:heartbeat:exportfs` resource, NEVER run `exportfs -r` to refresh — it sees an empty /etc/exports and silently unexports everything. Use `pcs resource restart exportfs` instead.
- **HAHA reliability hardening 2026-04-30 (Phases 1-5 implemented)** (project): Same-day follow-up after the 2026-04-27 → 2026-04-30 ~66h HAHA outage. App-level OCF docker monitor_cmd, NFS auto-flush, NFS stale-fh exporter, proactive ARP, host-pressure alerts, Twilio escalation. T1 e2e verified: 18s detect, 3m30s recover.
- **HAHA NFS stale-fh outage 2026-04-27 → 2026-04-30 (RESOLVED, ~66h 39m)** (project): Home Assistant down 2026-04-27 14:55 → 2026-04-30 09:34 UTC (~66h 39m). HA Python crashed with Bus error during nfs-group migration; container kept running so Pacemaker never noticed. Apr 30 02:15 weekly-update reboot exposed nlcl01file02 fh-cache poisoning. Fixed by restarting Pacemaker exportfs resource.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **nl-pve03 capacity pressure (2026-04-22)** (project): nl-pve03 mirrors pre-remediation nl-pve01 pattern — no swap/zram, sustained 92%+ memory, hosts K8s ctrlr+NMS+GPU inference. Apply same zram fix; OOM blast radius is the K8s control-plane share + LibreNMS + Ollama inference simultaneously.
- **session-thermal-and-gr-unreachable-20260616** (project): "2026-06-16 triage — NL \"thermal\" was stale phantom data; GR site was isolated ~06-15 22:58 → RECOVERED by 2026-06-17 (GR back online, reachable from NL)"

*Compiled: 2026-07-03 04:30 UTC*