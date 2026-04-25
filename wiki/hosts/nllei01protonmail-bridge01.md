# nlprotonmail-bridge01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:docker/nlprotonmail-bridge01/protonmail-bridge/CLAUDE.md**
- Protonmail Bridge exposes a Proton Mail account as local IMAP/SMTP, allowing standard mail clients to connect. Runs on `nlprotonmail-bridge01` (10.0.181.X), a Debian 12 LXC container (VMID 201101201, pve01).
- ssh -i ~/.ssh/one_key root@nlprotonmail-bridge01

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Device rebooted. |  | Resolved via Claude session IFRNLLEI01PRD-280 | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-280**: nlprotonmail-bridge01 — container restart. Docker container auto-restarts. Check docker logs if recurring >3x/day.

*Compiled: 2026-04-11 14:13 UTC*