# nl-nas02

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- 1. SSH: `ssh -i ~/.ssh/one_key admin@nl-nas01` or `ssh -i ~/.ssh/one_key synoadm@nl-nas02`

**nl:native/CLAUDE.md**
- Synology NAS (nl-nas01/nl-nas02) — not PVE containers, direct SSH:
- ssh -i ~/.ssh/one_key synoadm@nl-nas02  # DS1513+, sudo requires password
- **Note:** `sshpass` does not work with nl-nas02 (DSM 7.1 keyboard-interactive quirk). Use paramiko for password-based automation.
- | **Synology** | [`synology/`](synology/CLAUDE.md) | nl-nas01, nl-nas02 | 2 Synology NAS (DS1621+ primary, DS1513+ secondary): K8s iSCSI CSI (17 PVs), NFS provisioner, Frigate/Viseron NVR storage, Media, Nextcloud, cert sync, TFTP backup |

**nl:native/synology/CLAUDE.md**
- # Synology NAS Fleet — nl-nas01 / nl-nas02
- | Property | nl-nas01 (Primary) | nl-nas02 (Secondary) |
- **nl-nas02** — LACP bond (802.3ad), 4 physical NICs:
- **nl-nas02** — 4 RAID arrays, 1 volume + NFS mount from syno01:
- **nl-nas02** — 5 disks, all SMART PASSED but Disk 5 has bad sectors:

**nl:native/servarr/CLAUDE.md**
- **Target:** Single `servarr` namespace, Argo CD app-of-apps (`k8s/argocd-apps/servarr/`). NFS PVs for media (nl-nas01+nl-nas02, RWX). iSCSI PVCs for config. Secrets via ExternalSecrets → OpenBao. Drop Watchtower (Argo CD manages versions) and Selfheal (K8s liveness probes).
- │  nl-nas02 NFS /mnt/media2 (/volume2/Media)   │
- | nl-nas02 (10.0.181.X) | `/mnt/media2` (servarr01) | `/volume2/Media` | NZBGet, Whisparr |
- | nl-nas02 (10.0.181.X) | `/volume2/Media` (nl-gpu01) | `/volume2/Media` | xxxfin |
- **Mountpoint gotcha:** nl-gpu01 mounts the same nl-nas01/nl-nas02 exports at **`/volume1/Media`** and **`/volume2/Media`** (1:1), NOT at `/mnt/media`/`/mnt/media2` like servarr01. So a Pinchflat file at servarr01 `/mnt/media/YouTube/...` is the same file at nl-gpu01 `/volume1/Media/YouTube/...`. (This was previously mis-documented as `/mnt/media` for nl-gpu01.)

**nl:native/ncha/CLAUDE.md**
- | nl-nas02 | DS1513+ (physical) | 10.0.181.X | Secondary NAS. |

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-24 | Sensor over limit - Check Device Health Settings | recurred 3x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.

*Compiled: 2026-07-03 04:30 UTC*