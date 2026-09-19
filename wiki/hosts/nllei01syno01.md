# nl-nas01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-pve02 | Proxmox hypervisor (**VM on nl-nas01**) | `ssh nl-pve02` |
- 1. SSH: `ssh -i ~/.ssh/one_key admin@nl-nas01` or `ssh -i ~/.ssh/one_key synoadm@nl-nas02`

**nl:k8s/CLAUDE.md**
- │   ├── nl-nas01-csi/ # Synology DS1621+ iSCSI CSI (retain + delete classes)
- - **Synology iSCSI (`synology-csi-nl-nas01-iscsi-retain`)**: Databases, metrics, stateful workloads (Prometheus, Loki, Postgres, Thanos, SeaweedFS)

**nl:native/CLAUDE.md**
- Synology NAS (nl-nas01/nl-nas02) — not PVE containers, direct SSH:
- ssh -i ~/.ssh/one_key admin@nl-nas01    # DS1621+, sudo passwordless
- | **Synology** | [`synology/`](synology/CLAUDE.md) | nl-nas01, nl-nas02 | 2 Synology NAS (DS1621+ primary, DS1513+ secondary): K8s iSCSI CSI (17 PVs), NFS provisioner, Frigate/Viseron NVR storage, Media, Nextcloud, cert sync, TFTP backup |

**nl:native/synology/CLAUDE.md**
- # Synology NAS Fleet — nl-nas01 / nl-nas02
- | Property | nl-nas01 (Primary) | nl-nas02 (Secondary) |
- **nl-nas01** — Open vSwitch, 6 physical + 2x 10GbE:
- **nl-nas01** — 9 RAID arrays, 2 volumes + USB + VMM:
- | `/volume1/mnt/nfs/nl-nas01/Media` | NFS4 | 65 TB | 51 TB | 15 TB | 78% | NFS mount from syno01 (rw, soft, TCP) |

**nl:native/servarr/CLAUDE.md**
- **Target:** Single `servarr` namespace, Argo CD app-of-apps (`k8s/argocd-apps/servarr/`). NFS PVs for media (nl-nas01+nl-nas02, RWX). iSCSI PVCs for config. Secrets via ExternalSecrets → OpenBao. Drop Watchtower (Argo CD manages versions) and Selfheal (K8s liveness probes).
- │  nl-nas01 NFS /mnt/media  (/volume1/Media)   │
- | nl-nas01 (10.0.181.X) | `/mnt/media` (servarr01) | `/volume1/Media` | Sonarr, Radarr, Bazarr, NZBGet, Whisparr, LazyLibrarian, Headphones, Navidrome, Audiobookshelf, slskd, Pinchflat |
- | nl-nas01 (10.0.181.X) | `/volume1/Media` (nl-gpu01) | `/volume1/Media` | Plex, Jellyfin, Whishper |
- **Mountpoint gotcha:** nl-gpu01 mounts the same nl-nas01/nl-nas02 exports at **`/volume1/Media`** and **`/volume2/Media`** (1:1), NOT at `/mnt/media`/`/mnt/media2` like servarr01. So a Pinchflat file at servarr01 `/mnt/media/YouTube/...` is the same file at nl-gpu01 `/volume1/Media/YouTube/...`. (This was previously mis-documented as `/mnt/media` for nl-gpu01.)

**nl:native/ncha/CLAUDE.md**
- ├── Media → NFS 10.0.X.X (nl-nas01, VLAN 88)
- | nlcl01filearb01 | VM | nl-nas01 | 10.0.181.X, 10.0.X.X | Corosync/Pacemaker quorum voter only. No DRBD disk. |
- | nl-nas01 | DS1621+ (physical) | 10.0.181.X, **10.0.X.X** | NFS: `/volume1/homes`, `/volume1/Media`. Also DRBD arbitrator host for filearb01. |
- | 88 | 10.0.X.X/24 | NFS storage traffic (dedicated, high throughput). nlnc01↔nlcl01file01, nlnc02↔nlcl01file01, nl-nas01. |

**nl:native/haha/CLAUDE.md**
- ├── Media → NFS 10.0.X.X (nl-nas01, VLAN 88) → /volume1/Media
- ├── Backups → NFS 10.0.X.X (nl-nas01, VLAN 88) → /volume1/Backup/habackup
- | nlcl01iotarb01 | — | nl-nas01 | 10.0.181.X | Synology VMM. Corosync/Pacemaker quorum voter + SBD + DC. No workload. |
- | 3 | `p_fs_media` | `ocf:heartbeat:Filesystem` | `10.0.X.X:/volume1/Media` → `/mnt/iot/homeassistant/ha_nl-nas01` (NFSv4.1, nconnect=8) |
- | Home Assistant | `ghcr.io/home-assistant/home-assistant:stable` | 2026.3.1 | `/mnt/iot/homeassistant/ha_config:/config`, `/mnt/iot/homeassistant/ha_nl-nas01:/media/usb`, `/etc/localtime:/etc/localtime:ro`, `/run/dbus:/run/dbus:ro`, `/var/run/docker.sock:/var/run/docker.sock` | 80 (emulated hue), 8123 |

**nl:docker/nlservarr01/servarr/pinchflat/CLAUDE.md**
- | `/mnt/media/YouTube/` | Downloaded videos storage (NFS from nl-nas01) |

**gr:k8s/CLAUDE.md**
- - No `nl-nas01-csi/` — GR uses `democratic-csi/` (iSCSI + ZFS on gr-pve02, which doubles as Proxmox host and storage server)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-23 | DSM: The UPS device connected to nl-nas01 has ente | recurred 3x in 30d without durable fix | analysis-only pending root-cause | N/A |
| 2026-06-21 | DSM: Data backup task on nl-nas01 partially comple | recurred 5x in 30d without durable fix | analysis-only pending root-cause | N/A |
| 2026-06-21 | Sensor over limit - Check Device Health Settings | recurred 3x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **alert_pipeline_v2_2026_03_18** (project): Major alert pipeline upgrade (2026-03-18): flap detection, issue dedup, confidence scoring, error propagation, CI/CD review, retry loops, few-shot prompts, context summarization
- **HAHA chaos engineering catalog 2026-04-30 (~14 tests, 2 bugs surfaced+fixed)** (project): Same-day chaos engineering pass over the whole IoT infrastructure (HAHA + FISHA + sidecars + voice pipeline + cluster fencing). 14 tests run, 2 real bugs surfaced and 1 fixed (nodered start timeout 90s→180s); 1 outstanding (fence_pve list TypeError, IFRNLLEI01PRD-806). Empirical confidence table inside.
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).
- **pve04_pvestatd_wedge_20260625** (project): nlpve04 PVE-management wedge (pvestatd D-state, cluster status=unknown, claude01 LXC OOM). RESOLVED 2026-06-27 WITHOUT a reboot — `systemctl restart pve-cluster` (un-hangs pmxcfs, releases D-state) THEN `restart pvestatd`. The 06-25 "reboot is the ONLY fix" was WRONG. IFRNLLEI01PRD-1419.
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **Scanner nuclei + testssl silent failure root cause + fix (PATH)** (project): Both daily security scanners had nuclei + testssl silently failing in the 03:00 cron run because cron's default PATH excludes /usr/local/bin. Fixed by exporting PATH at top of weekly-scan.sh.

## Physical Documentation (03_Lab)

- `03_Lab/NL/Servers/nl-nas01/20250515_nl-nas01_ansible_inventory.yaml`
- `03_Lab/NL/Servers/nl-nas01/SSD Cache Advisor/20240531_SSD_Cache_Advisor_183GB.png`
- `03_Lab/NL/Servers/nl-nas01/SSD Cache Advisor/20240603_SSD_Cache_Advisor_200GB.txt`
- `03_Lab/NL/Servers/nl-nas01/vm/135 - nlhaha02/20240515_nlhaha02_dpl_notes.txt`

*Compiled: 2026-07-03 04:30 UTC*