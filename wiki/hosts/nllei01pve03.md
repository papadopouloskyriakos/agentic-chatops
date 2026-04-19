# nl-pve03

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | List LXCs on a node | `pve_list_lxc(node="nl-pve03")` | `ssh nl-pve03 "pct list"` |
- | List VMs on a node | `pve_list_vms(node="nl-pve03")` | `ssh nl-pve03 "qm list"` |
- | Get LXC config | `pve_lxc_config(node="nl-pve03", vmid=VMID_REDACTED)` | `ssh nl-pve03 "pct config VMID_REDACTED"` |
- | Get VM config | `pve_vm_config(node="nl-pve03", vmid=VMID_REDACTED)` | `ssh nl-pve03 "qm config VMID_REDACTED"` |
- | Get guest status | `pve_guest_status(node="nl-pve03", vmid=VMID_REDACTED, type="lxc")` | `ssh nl-pve03 "pct status VMID_REDACTED"` |

**nl:native/librenms/CLAUDE.md**
- | nl-nms01 | NL (Leiden) | `https://nl-nms01.example.net/` | nl-pve03 | — | 10.0.181.X | Primary NMS — monitors 137 devices (NL + GR) |

**nl:native/pve/CLAUDE.md**
- | nl-pve03 | i9-14900K | 24C/32T | 134.7 GB | bond0 (802.3ad, 10G) | 3.6 TB ZFS | GPU node (RTX 3090 Ti passthrough) |

**nl:native/servarr/CLAUDE.md**
- | PVE Host | nl-pve03 |

**nl:docker/nlservarr01/servarr/pinchflat/CLAUDE.md**
- # Or via PVE host (QEMU VM VMID_REDACTED on nl-pve03):
- ssh nl-pve03 "qm guest exec VMID_REDACTED -- <command>"
- ssh nl-pve03
- **VM Details**: VMID VMID_REDACTED on nl-pve03, IP 10.0.181.X, Ubuntu 24.04, 6 vCPU, 12 GB RAM.

**nl:pve/CLAUDE.md**
- | nl-pve03 | Dell Precision 3680 | i9-14900K (32T) | 128 GB | NVMe ZFS | 34 | 14 |
- ├── nl-pve03/
- | `nl-pve03-local-zfs` | Local ZFS | 29 LXC, 10 QEMU | Performance workloads |

## Related Memory Entries

- **CodeGraphContext (CGC) Setup** (project): Code graph database for CubeOS/MeshSat — Neo4j backend, scheduled reindex (no live watcher), MCP server, 43K nodes across 5 repos
- **AWX EE Image Persistence Problem** (feedback): Custom EE images imported via ctr are lost on K8s node reboot. Need persistent registry or image in PVC.
- **GR Claude Agent (grclaude01)** (project): Claude Code agent at GR site for NL maintenance oversight. VMID 201021201, 10.0.X.X, gr-pve01.
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **OOB Access via PiKVM + Cloudflare Tunnel** (project): BROKEN (2026-03-21) — PiKVM bricked by forced package upgrade. Requires physical access to GR site to recover. Cloudflare tunnel config still exists but PiKVM is offline.
- **OpenObserve Grafana datasource deployed via GitOps** (project): OpenObserve (10.0.181.X:5080) added as Grafana datasource via additionalDataSources in kube-prometheus-stack Helm values
- **Operational Activation Audit 2026-04-10** (project): Comprehensive audit scoring operational activation (not just implementation). 21/21 tables populated after remediation. 8 YT issues (445-452).
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **VMID UID Schema** (project): Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.

## Physical Documentation (03_Lab)

- `03_Lab/NL/Servers/nl-pve03/20241222_nl-pve03_interfaces.md`
- `03_Lab/NL/Servers/nl-pve03/20241222_nl-pve03_network_changes.md`
- `03_Lab/NL/Servers/nl-pve03/20241222_nl-pve03_sdn.md`
- `03_Lab/NL/Servers/nl-pve03/20241222_nl-pve03_storage.md`
- `03_Lab/NL/Servers/nl-pve03/20250330-1711_nl-pve03_interfaces.cfg`
- `03_Lab/NL/Servers/nl-pve03/20250515_nl-pve03_ansible_inventory.yaml`
- `03_Lab/NL/Servers/nl-pve03/Desktop-nlamt02-2025-05-25-00-02.jpg`
- `03_Lab/NL/Servers/nl-pve03/lxc/VMID_REDACTED - nlwhiteboard01/nlwhiteboard01_docker-compose.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/VMID_REDACTED - nlimaginary01/nlimaginary01_docker-compose.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/VMID_REDACTED - nlopenwebui01/20241223_nlopenwebui01.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/VMID_REDACTED - nlollama01/20241224_nlollama01.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/132 - nlelastiflow01/20240414_nlelastiflow01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve03/lxc/132 - nlelastiflow01/kibana-8.2.x-flow-codex.ndjson`
- `03_Lab/NL/Servers/nl-pve03/lxc/143 - nlimap01/20240827_nlimap01_lxc_build_notes.txt`
- `03_Lab/NL/Servers/nl-pve03/lxc/143 - nlimap01/20240827_nlimap01_lxc_build_notes.txt~`
- `03_Lab/NL/Servers/nl-pve03/lxc/150 - nllobechat01/20240905_nllobechat01_dpl_notes.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/150 - nllobechat01/20241224 Backup Before Destroy/.env`
- `03_Lab/NL/Servers/nl-pve03/lxc/150 - nllobechat01/20241224 Backup Before Destroy/docker-compose.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/150 - nllobechat01/20241224 Backup Before Destroy/minio-bucket-config.json`
- `03_Lab/NL/Servers/nl-pve03/vm/100 - haos9.5 (nlhaos01)/FireAngel hittemelder 230V kopen We ❤️ Smart! ROBBshop.url`

*Compiled: 2026-04-11 14:13 UTC*