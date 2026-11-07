# nl-iot02

**Site:** NL (Leiden)

## Knowledge Base References

**nl:native/haha/CLAUDE.md**
- | nl-iot02 | 777 | nl-pve03 | 10.0.181.X, 10.0.X.X | QEMU VM. 2C/2S, 4GB RAM, 64GB SSD. Active or passive (alternates each weekly update). |
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

- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **gpu01-target-ram-32g** (feedback): "Operator's chosen RAM allocation for nl-gpu01 is 32 GiB (32768 MB), not the historical 28 GiB. Don't argue this down to 28 G citing nl-pve03 host pressure — operator owns the trade-off."
- **HAHA chaos engineering catalog 2026-04-30 (~14 tests, 2 bugs surfaced+fixed)** (project): Same-day chaos engineering pass over the whole IoT infrastructure (HAHA + FISHA + sidecars + voice pipeline + cluster fencing). 14 tests run, 2 real bugs surfaced and 1 fixed (nodered start timeout 90s→180s); 1 outstanding (fence_pve list TypeError, IFRNLLEI01PRD-806). Empirical confidence table inside.
- **HAHA reliability hardening 2026-04-30 (Phases 1-5 implemented)** (project): Same-day follow-up after the 2026-04-27 → 2026-04-30 ~66h HAHA outage. App-level OCF docker monitor_cmd, NFS auto-flush, NFS stale-fh exporter, proactive ARP, host-pressure alerts, Twilio escalation. T1 e2e verified: 18s detect, 3m30s recover.
- **haha_voice_pe_upgrade** (project): HA Voice PE firmware — v7 working (v6 upstream + Squeezebox routing), Ollama q4_0 fix, REST sensors FIXED, 2026-03-16 audit fixes
- **HAHA NFS stale-fh outage 2026-04-27 → 2026-04-30 (RESOLVED, ~66h 39m)** (project): Home Assistant down 2026-04-27 14:55 → 2026-04-30 09:34 UTC (~66h 39m). HA Python crashed with Bus error during nfs-group migration; container kept running so Pacemaker never noticed. Apr 30 02:15 weekly-update reboot exposed nlcl01file02 fh-cache poisoning. Fixed by restarting Pacemaker exportfs resource.
- **IoT Pacemaker HA Cluster** (project): 3-node Pacemaker/Corosync IoT cluster (nlcl01iot01/nl-iot02/nlcl01iotarb01) — topology, resources, failover behavior, VMID 666
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).

*Compiled: 2026-07-03 04:30 UTC*