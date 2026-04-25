# nl-iot02

**Site:** NL (Leiden)

## Knowledge Base References

**nl:native/haha/CLAUDE.md**
- | nl-iot02 | 777 | pve03 | 10.0.181.X, 10.0.X.X | QEMU VM. 2C/2S, 4GB RAM, 64GB SSD. Currently **active** (all resources). |
- ssh -i ~/.ssh/one_key root@nl-iot02
- | nl-iot02 | Same as iot01 (active/standby pair, shared NFS storage) |
- crm node standby nl-iot02
- crm node online nl-iot02

**other:/app/n8n/doorbell/CLAUDE.md**
- | Home Assistant | homeassistant.example.net | Pacemaker cluster (active: nl-iot02) |

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Service up/down. |  | Resolved via Claude session IFRNLLEI01PRD-260 | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-260**: nl-iot02 — IoT device service flap. Low priority, self-recovers. See IFRNLLEI01PRD-259 lesson.

## Related Memory Entries

- **Always use full hostnames** (feedback): Never strip site/cluster prefixes from hostnames — use nl-nas02 not syno02, nl-pve01 not pve01
- **haha_voice_pe_upgrade** (project): HA Voice PE firmware — v7 working (v6 upstream + Squeezebox routing), Ollama q4_0 fix, REST sensors FIXED, 2026-03-16 audit fixes
- **IoT Pacemaker HA Cluster** (project): 3-node Pacemaker/Corosync IoT cluster (nlcl01iot01/nl-iot02/nlcl01iotarb01) — topology, resources, failover behavior, VMID 666

*Compiled: 2026-04-11 14:13 UTC*