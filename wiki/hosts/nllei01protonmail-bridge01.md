# nlprotonmail-bridge01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:images/CLAUDE.md**
- | `protonmail-bridge/` | debian:bookworm-slim | `latest` | ~336MB | ProtonMail Bridge from official .deb — IMAP/SMTP gateway. Deployed to nlprotonmail-bridge01. |
- **Why here?** Proton does not publish an official Docker image. The community image (`shenxn/protonmail-bridge`) was abandoned. We build our own from the official `.deb` release, which includes `libfido2` and all dependencies. Version pinned via `ARG BRIDGE_VERSION`. The deploy host needs `docker login` to the private registry to pull (configured on nlprotonmail-bridge01).

**nl:docker/nlprotonmail-bridge01/protonmail-bridge/CLAUDE.md**
- Protonmail Bridge exposes a Proton Mail account as local IMAP/SMTP, allowing standard mail clients to connect. Runs on `nlprotonmail-bridge01` (10.0.181.X), a Debian 12 LXC container (VMID 201101201, pve01).
- ssh -i ~/.ssh/one_key root@nlprotonmail-bridge01

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Device rebooted. |  | Resolved via Claude session IFRNLLEI01PRD-280 | 0.9 |

*Compiled: 2026-04-09 06:19 UTC*