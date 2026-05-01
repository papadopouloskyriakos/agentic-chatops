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
- ssh -i ~/.ssh/one_key admin@nl-nas01    # DS1621+, sudo passwordless

**nl:native/synology/CLAUDE.md**
- # Synology NAS Fleet — nl-nas01 / nl-nas02
- | Property | nl-nas01 (Primary) | nl-nas02 (Secondary) |
- **nl-nas01** — Open vSwitch, 6 physical + 2x 10GbE:
- **nl-nas01** — 9 RAID arrays, 2 volumes + USB + VMM:
- | `/volume1/mnt/nfs/nl-nas01/Media` | NFS4 | 65 TB | 51 TB | 15 TB | 78% | NFS mount from syno01 (rw, soft, TCP) |

**nl:native/fisha/CLAUDE.md**
- | nlcl01filearb01 | — | nl-nas01 (Synology VMM) | QEMU | 10.0.181.X | 10.0.X.X | Arbiter (quorum only) | 1 vCPU | 4 GB |
- 2. **filearb01 runs on Synology VMM** — Hosted on nl-nas01 (DS1621+) via Synology Virtual Machine Manager, not PVE. No VMID in PVE inventory. Managed via DSM > Virtual Machine Manager.

**nl:native/ncha/CLAUDE.md**
- | nl-nas01 | DS1621+ (physical) | 10.0.181.X, **10.0.X.X** | NFS: `/volume1/homes`, `/volume1/Media`. Also DRBD arbitrator host for filearb01. |

**nl:native/haha/CLAUDE.md**
- | 3 | `p_fs_media` | `ocf:heartbeat:Filesystem` | `10.0.X.X:/volume1/Media` → `/mnt/iot/homeassistant/ha_nl-nas01` (NFSv4.1, nconnect=8) |
- | Home Assistant | `ghcr.io/home-assistant/home-assistant:stable` | 2026.3.1 | `/mnt/iot/homeassistant/ha_config:/config`, `/mnt/iot/homeassistant/ha_nl-nas01:/media/usb`, `/etc/localtime:/etc/localtime:ro`, `/run/dbus:/run/dbus:ro`, `/var/run/docker.sock:/var/run/docker.sock` | 80 (emulated hue), 8123 |
- │   └── ha_nl-nas01/           ← NFS from syno01:/volume1/Media

**gr:k8s/CLAUDE.md**
- - No `nl-nas01-csi/` — GR uses `democratic-csi/` (iSCSI + ZFS on gr-pve02, which doubles as Proxmox host and storage server)

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **alert_pipeline_v2_2026_03_18** (project): Major alert pipeline upgrade (2026-03-18): flap detection, issue dedup, confidence scoring, error propagation, CI/CD review, retry loops, few-shot prompts, context summarization
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.

## Physical Documentation (03_Lab)

- `03_Lab/NL/Servers/nl-nas01/20250515_nl-nas01_ansible_inventory.yaml`
- `03_Lab/NL/Servers/nl-nas01/SSD Cache Advisor/20240531_SSD_Cache_Advisor_183GB.png`
- `03_Lab/NL/Servers/nl-nas01/SSD Cache Advisor/20240603_SSD_Cache_Advisor_200GB.txt`
- `03_Lab/NL/Servers/nl-nas01/vm/135 - nlhaha02/20240515_nlhaha02_dpl_notes.txt`

*Compiled: 2026-04-11 14:13 UTC*