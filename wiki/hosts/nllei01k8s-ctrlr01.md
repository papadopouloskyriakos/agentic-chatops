# nlk8s-ctrl01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:pve/CLAUDE.md**
- | nlk8s-ctrl01-03 | 1011006xx | QEMU | pve01+03 | 4C/8G | K8s control plane |

**gateway:CLAUDE.md**
- - **nlk8s-ctrl01 chronic apiserver crash-loop RESOLVED (2026-05-15 12:59 UTC, IFRNLLEI01PRD-863):** kube-apiserver had restartCount=**1665** (~27 days of crashing every ~24 min). Cause: VM VMID_REDACTED on nlpve04 had `balloon: 4096` active while peers nlk8s-ctrl02/nlk8s-ctrl03 had `balloon: 0`. nlpve04 host pressure → pvestatd auto-ballooned nlk8s-ctrl01 down to 3.7 GiB → etcd WAL/DB page cache evicted → fsync 288 ms (vs peer 70-80 ms) → apiserver KV/Range timeouts → `/healthz` HTTP 500 → kubelet liveness-kill → restart cycle. **Trap that delayed the fix:** `qm set --balloon 0` only writes a `[PENDING]` config change — doesn't live-remove the QEMU balloon device. `pvestatd` keeps reading the still-active old value and re-inflates within ~10 min. Force-deflate via `qm monitor balloon <mb>` is temporary. **Real fix is `qm set --balloon 0` + `qm reboot`** — reboot applies `[PENDING]` and the balloon device is gone entirely (no `balloon:` line in `qm status --verbose` post-fix). Verified durability: balloon device absent, VM 7.7/6.3 GiB free, etcd commit 75 ms, `/readyz` 46 ms, restartCount stable since 12:59 UTC. **Architectural rule** (no balloon on any etcd / apiserver / DB VM) in [`memory/feedback_no_balloon_on_k8s_control_plane.md`](memory/feedback_no_balloon_on_k8s_control_plane.md). **The `[PENDING]` gotcha** in [`memory/feedback_pve_balloon_zero_needs_reboot.md`](memory/feedback_pve_balloon_zero_needs_reboot.md). Full memory: [`memory/apiserver_ctrl01_balloon_chronic_restart_fixed_20260515.md`](memory/apiserver_ctrl01_balloon_chronic_restart_fixed_20260515.md). Plus same-day mass-close pass on IFR projects (NL 59→1, GR 38→2 = **94 issues closed** total — most stale per the auto-resolve gap doc; details in YT comments) + HAProxy BREACH ACL fix on 3 VPS (chzrh01 + notrf01 + **txhou01** — original IFRNLLEI01PRD-845 description named only 2; fix uses var-capture pattern matching existing `is_matrix`/`is_analytics` idiom; details in [`memory/librenms_extender_fleet_deployment_20260515.md`](memory/librenms_extender_fleet_deployment_20260515.md) Edge HAProxy section).

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-15 | KubeAPIErrorBudgetBurn | Cascading from IFRNLLEI01PRD-566. The apiserver restart cycl | Same mitigation as IFRNLLEI01PRD-566: shut down nlandro | 0.9 |
| 2026-04-15 | KubeClientErrors | nl-pve01 memory pressure: 53 guests (9 VMs + 44 LXCs), 2 | Shut down nlandroidsdk01 (freed ~9.7 GB, 8 CPUs) + nlle | 0.9 |
| 2026-03-25 | KubePodCrashLooping | apiserver-ctrl01 crash looping (498 restarts) is a symptom  | Self-recovered when nl-pve01 load dropped. All 3 apiserv | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-257**: KubePodCrashLooping on apiserver nodes correlates with PVE host load spikes. Self-recovers when host load drops. Check node resource pressure (kubectl top nodes) before restarting pods.

## Related Memory Entries

- **alert_pipeline_v2_2026_03_18** (project): Major alert pipeline upgrade (2026-03-18): flap detection, issue dedup, confidence scoring, error propagation, CI/CD review, retry loops, few-shot prompts, context summarization
- **alerting_dispositions_silences_20260624** (project): "2026-06-24 alerting policy + the 'silence forever the not-actionable' silences created (GR etcd cascade, NL AS64512CountLow/InfragraphPrecisionDrop), killers kept live. Plus the NL-etcd-unmonitored gap."
- **apiserver-ctrl01-balloon-chronic-restart-fixed-20260515** (project): "RESOLVED 2026-05-15. nlk8s-ctrl01's kube-apiserver had restartCount=1665 (~27 days of crash-looping, ~24-min cycle). Root cause was the balloon device on the underlying VM (VMID_REDACTED on nlpve04) inflating during host pressure events, leaving the VM with only 3.7 GiB instead of 8 GiB. etcd's WAL/DB page cache got evicted → fsyncs disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kill → restart. Fix: `qm set --balloon 0` + VM reboot to apply [PENDING] (config change cannot live-remove a balloon device)."
- **feedback_never_abbreviate_hostnames** (feedback): "[P0] NEVER abbreviate or truncate a hostname — always the complete site-prefixed name (gr-pve01 not gr, nl-pve01 not pve01). Operator-anger rule, reinforced 2026-06-24."
- **feedback-no-balloon-on-k8s-control-plane** (feedback): "Never run k8s control-plane VMs (kube-apiserver / etcd / scheduler / controller-manager) with an active Proxmox balloon device. etcd is fsync-sensitive; when host pressure causes balloon to reclaim guest memory, etcd's WAL/DB page cache gets evicted → fsyncs become disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kills → restart cycle. Caught 2026-05-15: nlk8s-ctrl01 had 1665 restarts (27 days of crash-looping) because of this."
- **feedback-pve-balloon-zero-needs-reboot** (feedback): "On Proxmox, `qm set <vmid> --balloon 0` does NOT live-remove the QEMU balloon device — it queues a [PENDING] config change for the next VM restart. The active config + the running balloon device stay in place. Force-deflating via `qm monitor balloon <mb>` is temporary; pvestatd auto_balloon will re-inflate within ~10 min based on the still-active config. To truly disable balloon, run `qm set --balloon 0` AND reboot the VM."
- **HAHA chaos engineering catalog 2026-04-30 (~14 tests, 2 bugs surfaced+fixed)** (project): Same-day chaos engineering pass over the whole IoT infrastructure (HAHA + FISHA + sidecars + voice pipeline + cluster fencing). 14 tests run, 2 real bugs surfaced and 1 fixed (nodered start timeout 90s→180s); 1 outstanding (fence_pve list TypeError, IFRNLLEI01PRD-806). Empirical confidence table inside.
- **health_audit_20260629** (project): "2026-06-29 agentic-system + orchestrator health audit. System GREEN (holistic 93%, 0 fail); 1 open item nlk8s-ctrl02 saturation; HolisticHealthFailing flaps; 3 empty tables=dormant features; audit methodology."
- **HAHA NFS stale-fh outage 2026-04-27 → 2026-04-30 (RESOLVED, ~66h 39m)** (project): Home Assistant down 2026-04-27 14:55 → 2026-04-30 09:34 UTC (~66h 39m). HA Python crashed with Bus error during nfs-group migration; container kept running so Pacemaker never noticed. Apr 30 02:15 weekly-update reboot exposed nlcl01file02 fh-cache poisoning. Fixed by restarting Pacemaker exportfs resource.
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by nl-pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 nl-pve01 memory pressure class.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **infragraph-epic-state-20260609** (project): "Infragraph epic IFRNLLEI01PRD-1029 FINAL STATE — model-based control LIVE 2026-06-09 (13/16 done, system active, first rule -1046 approved); canonical record in repo memory/infragraph_epic_buildout_20260609.md"
- **K8s Next Session Tasks** (project): Two pending tasks for K8s operational readiness — OpenClaw K8s access + Prometheus/Alertmanager/Gatus alert wiring
- **Pipeline Hardening (2026-04-01)** (project): 11 fixes across 5 workflows + 3 scripts. NetBox Step 2-pre in triage, syslog 3-day, [POLL] fallback parser, escalation cooldown 1h, recovery dedup 60s, flapping timeout 4h, watchdog zombie bounce, Parse Response em-dash + [POLL] approval gate regex. All E2E verified.
- **nl-pve01 memory pressure causing apiserver restarts** (project): PVE01 host 88% RAM (2.5x overcommit, zero swap) starved etcd I/O on nlk8s-ctrl01. 754 apiserver restarts. Mitigated by shutting down androidsdk01.
- **pve04_pvestatd_wedge_20260625** (project): nlpve04 PVE-management wedge (pvestatd D-state, cluster status=unknown, claude01 LXC OOM). RESOLVED 2026-06-27 WITHOUT a reboot — `systemctl restart pve-cluster` (un-hangs pmxcfs, releases D-state) THEN `restart pvestatd`. The 06-25 "reboot is the ONLY fix" was WRONG. IFRNLLEI01PRD-1419.
- **Session summary IFRNLLEI01PRD-987** (project): Compacted session context for IFRNLLEI01PRD-987
- **sms_alert_fatigue_dedup_20260623** (project): 2026-06-23 fixed the 91-SMS/7d alert-fatigue leak — session->SMS path now dedups on a root-cause CLUSTER key + edge-trigger instead of issue_id
- **yt_triage_alert_remediation_20260625** (project): 2026-06-25 YouTrack triage (8 issues closed with evidence) + the IFRNLLEI01PRD-1408 commit-label mislabel finding + active-alert remediation (in progress).

*Compiled: 2026-07-03 04:30 UTC*