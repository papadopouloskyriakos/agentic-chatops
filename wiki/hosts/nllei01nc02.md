# nlnc02

**Site:** NL (Leiden)

## Knowledge Base References

**nl:native/ncha/CLAUDE.md**
- ssh -i ~/.ssh/one_key root@nlnc02
- | nlnc02 | VMID_REDACTED | pve03 | 10.0.181.X, 10.0.X.X | Nextcloud 32.0.6, PHP 8.4.18, Apache 2.4.58 |
- | nlnc02 | Nextcloud | Same as nc01 (shared OCFS2 storage, identical app) |

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Service up/down. |  | Resolved via Claude session IFRNLLEI01PRD-336 | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-336**: Nextcloud (nlnc02) service up/down is often caused by PHP-FPM pool exhaustion or MariaDB connection limits. Check systemctl status php-fpm and mariadb connections.

## Related Memory Entries

- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details

*Compiled: 2026-04-11 14:13 UTC*