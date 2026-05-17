# nlk8s-ctrl01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:pve/CLAUDE.md**
- | nlk8s-ctrl01-03 | 1011006xx | QEMU | pve01+03 | 4C/8G | K8s control plane |

**gateway:CLAUDE.md**
- - **HAHA + FISHA reliability hardening (2026-04-30)** — closed IFRNLLEI01PRD-704, -801, -802, -803, -804, -805, -815 in one session after the 2026-04-27→04-30 ~66h HAHA outage. Memory entries: [`incident_haha_nfs_stale_fh_20260430.md`](memory/incident_haha_nfs_stale_fh_20260430.md), [`haha_reliability_hardening_20260430.md`](memory/haha_reliability_hardening_20260430.md), [`haha_chaos_engineering_20260430.md`](memory/haha_chaos_engineering_20260430.md). Components live: (a) `monitor_cmd` on all 5 OCF docker resources (HA `/manifest.json`, ESPHome `/`, Z2M wget, Node-RED `/`, Mosquitto `nc -z 1883`); (b) start/stop timeouts raised from 90s to 120-180s on the 4 sidecar resources to avoid fence-on-restart (caught by chaos C9); (c) `nfs-stale-fh-exporter.py` (HTTP/1.1 ThreadingHTTPServer, port 9101) on file01/02 + `exportfs-flush-webhook.py` (port 9107, bearer-token, IP-allowlist 10.0.X.X/27 + 10.0.181.X/24) on file01/02; (d) Pacemaker alert `alert_post_nfs_flush` on FISHA + `clear_arp_nfs.sh` on iot01/02 wired to call the exportfs-flush webhook on `p_fs_iot start` failures with stale-fh signature; (e) `alertmanager-twilio-bridge.py` user-systemd service on nl-claude01:9106 + Alertmanager `twilio-tier1` route matching `tier=1, severity=critical`; (f) Gatus `custom` Twilio provider with API-Key auth (`/srv/atlantis/twilio.env` env_file mounted into Atlantis runner), tier-1 endpoints for HA + NL K8s API + FISHA file01 + FISHA file02; (g) 7 PrometheusRules — `NFSStaleFhPoisoning`, `NFSStaleFhExporterDown`, `NFSStaleFhExporterStalePackets`, `PVEMemoryPressureHigh/Critical`, `PVELoadHigh`, `PVEZramSwapNearFull`; (h) ARP refresh cron on iot01/02 every 5 min (`ping -c 1 -W 2 -I enp6s19 10.0.X.X`); (i) `fence_pve` Python TypeError patched with `dpkg-divert --rename` on iot01/02/iotarb01 + file01/02/filearb01 (survives `apt upgrade fence-agents-pve`); (j) IFRNLLEI01PRD-704 balloon floors set on 6 VMs on nl-pve01 (75% on HA-critical iot01+file01, 50% on others) + balloon device attached on nlk8s-ctrl01 — immediate 5 GiB host memory recovered, ~14 GiB total reclaimable headroom. **14-test chaos catalog run end-to-end**; 12 of 14 confidence rows now >0.90 detection AND recovery. Two rows at acknowledged structural ceilings (in-container freeze rec 0.85 = OCF docker agent limit; FISHA migration rec 0.85 = recorder DB on NFS by operator decision).
- **2026-04-22 re-drift (IFRNLLEI01PRD-692 + -704).** Host drifted back into the same class of memory pressure — load avg 13-25, zramswap 99.96% saturated, 8G free of 94G. Caused `KubeAPIErrorBudgetBurn` via `kube-apiserver-nlk8s-ctrl01` (791 restarts) whose local etcd fsyncs stall under host pressure. Root cause: **no balloon floor on any pve01 VM** — `ctrl01` has `balloon: 0` (device disabled), the other 6 VMs have the device but `balloon:` unset (min=max = no reclaim). `pvestatd auto_balloon` cannot reclaim without a floor. **Remediation pending in IFRNLLEI01PRD-704** (on hold): attach balloon device on ctrl01 (`qm set VMID_REDACTED -balloon 4096`, ~60s downtime, quorum 2-of-3 holds) + set floors on the other 6 live (zero downtime). Total reclaimable headroom ~17 GiB across the fleet.

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-15 | KubeAPIErrorBudgetBurn | Cascading from IFRNLLEI01PRD-566. The apiserver restart cycl | Same mitigation as IFRNLLEI01PRD-566: shut down nlandro | 0.9 |
| 2026-04-15 | KubeClientErrors | nl-pve01 memory pressure: 53 guests (9 VMs + 44 LXCs), 2 | Shut down nlandroidsdk01 (freed ~9.7 GB, 8 CPUs) + nlle | 0.9 |
| 2026-03-25 | KubePodCrashLooping | apiserver-ctrl01 crash looping (498 restarts) is a symptom  | Self-recovered when pve01 load dropped. All 3 apiservers Run | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-257**: KubePodCrashLooping on apiserver nodes correlates with PVE host load spikes. Self-recovers when host load drops. Check node resource pressure (kubectl top nodes) before restarting pods.

## Related Memory Entries

- **alert_pipeline_v2_2026_03_18** (project): Major alert pipeline upgrade (2026-03-18): flap detection, issue dedup, confidence scoring, error propagation, CI/CD review, retry loops, few-shot prompts, context summarization
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 pve01 memory pressure class.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **K8s Next Session Tasks** (project): Two pending tasks for K8s operational readiness — OpenClaw K8s access + Prometheus/Alertmanager/Gatus alert wiring
- **nl-pve01 memory pressure causing apiserver restarts** (project): PVE01 host 88% RAM (2.5x overcommit, zero swap) starved etcd I/O on ctrl01. 754 apiserver restarts. Mitigated by shutting down androidsdk01.

*Compiled: 2026-05-06 00:48 UTC*