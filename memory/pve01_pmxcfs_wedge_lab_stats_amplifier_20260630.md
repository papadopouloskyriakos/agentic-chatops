# nl-pve01 pmxcfs wedge → matrix outage; lab-stats.py amplifier (2026-06-30)

## Symptom → root cause (one line)
Operator report "something's wrong with matrix" → `@claude` bot couldn't reach matrix.example.net (public edge TLS-OK but connection died proxying to backend; internal Synapse 10.0.X.X timed out). Root cause: **nl-pve01 pmxcfs (the `/etc/pve` FUSE fs) was wedged**, and matrix is LXC `VMID_REDACTED` (`nl-matrix01`) on that host → went down with the host.

## The wedge signature (diagnostic, NOT CPU)
- `load average: 163.07, 162.73, 162.42` on **20 cores**, but `vmstat` = **97% CPU idle, 0% iowait**. The "load" was ~163 tasks in **D-state (uninterruptible sleep)**, all `wchan=filename_create` against `/etc/pve` = hung pmxcfs. Proxmox MCP `pve_list_nodes` showed nl-pve01 `status: unknown` (pvestatd couldn't read pmxcfs).
- Dozens of `pvesh`/`qm`/`pct`/`pveproxy`/`pvestatd` piled in D-state. Disk (`rpool` 2% used), corosync (Quorate: Yes), were all HEALTHY → wedge was NOT disk/quorum/corosync.
- **Same failure class** as documented: [[feedback_pve_mgmt_wedge_pmxcfs_restart]] (2026-06-27 pve04) and the 2026-06-23 `pve01_rpool_suspend_heatwave`.

## Amplifier (root cause of the pile-up, the NEW finding)
134 stuck `pvesh get /cluster/resources --type node` processes, all orphaned to pid 1. Source: **`scripts/lab-stats.py:208`** (the `/webhook/lab-stats` portfolio API) SSHed to **nl-pve01** with `ConnectTimeout=8` + `subprocess timeout=15` but **no server-side `timeout`** on pvesh. When pmxcfs stalled, the `subprocess` timeout killed the LOCAL `ssh` client — but the REMOTE `bash -c pvesh …` was already in D-state on pmxcfs, and **D-state ignores SIGKILL** (it cannot be killed, not even by the SSH session closing) → it orphaned to pid 1 and stayed forever. Every subsequent lab-stats webhook call (frontend polls `/webhook/lab-stats`) added another orphan → 134 → pmxcfs deadlocked entirely.
- Its sibling `scripts/infragraph-seed.py` was already hardened for this on 2026-06-27 (multi-host fallback + comment at L54-57). lab-stats.py was missed.

## Fix applied (MR `fix/lab-stats-pve01-wedge-amplifier`)
`scripts/lab-stats.py get_compute()` now:
1. Iterates `PVE_CLUSTER_HOSTS = [nl-pve03, nlpve04, nl-pve02, nl-pve01]` (healthy host FIRST, pve01 LAST as fallback; env `LAB_STATS_PVE_HOSTS` overrides) — any cluster member returns all node resources.
2. Wraps pvesh server-side: `timeout 20 pvesh …` (reclaims a slow-but-not-wedged pmxcfs before D-state).
3. `subprocess timeout=30`, first-success-wins, all-fail raises.
Verified: `get_compute()` returns correct per-node threads/RAM for all 6 nodes via pve03. Live webhook serves from this working tree so the fix is effective immediately.

## Recovery (operator-driven)
Operator hard-powered-off nl-pve01 via PDU (brute-force clear of the wedge). On power-restore: host came back clean (load 0.8, pmxcfs 1.6s, no D-state). `pve-guests` autostart brought up the ~40 `onboot:1` guests in sequence (~5 min). matrix LXC VMID_REDACTED was manually started (onboot:1 but not yet reached by autostart at first check); Synapse + postgres + nginx + element-web + hookshot + mas + ntfy docker stack came up healthy; bot `@claude` whoami + `/sync` (9 rooms) working; public endpoint serving again. **Only the docker TEMPLATE `VMID_REDACTED` stays stopped (expected).**

## Corrections / gotchas
- **n8n is on nlpve04, NOT pve01.** CLAUDE.md's "Known Host Pressure: nl-pve01" wrongly said n8n LXC (VMID_REDACTED) lives on pve01 — live `pvesh /cluster/resources` shows `nlpve04 VMID_REDACTED lxc running nl-n8n01`. Same VMID-node-digit decode-drift class as claude01 (said pve03, actually pve04). n8n was NOT affected by the pve01 outage (stayed up, http=200 throughout). CLAUDE.md corrected.
- **The `pve-cluster` restart fix is the no-reboot path** ([[feedback_pve_mgmt_wedge_pmxcfs_restart]]): `systemctl restart pve-cluster` FIRST (FUSE teardown returns EIO → releases D-states instantly) THEN `reset-failed pvestatd && restart pvestatd`. Restarting pvestatd ALONE stays D-state. The operator chose PDU power-cycle instead this time (also effective). For NEXT time, prefer the pve-cluster restart (no guest impact, instant).
- **D-state on pmxcfs cannot be killed by SIGKILL** — only pmxcfs unwedging (pve-cluster restart) or host reboot reclaims it. So a client-side `subprocess timeout` is INSUFFICIENT to prevent orphans; you need server-side `timeout` AND avoiding the wedged host.
- **Monitoring gap still open** (noted 2026-06-25 too): the wedge fires only a generic `NodeSaturation` (which mis-reads as CPU). Needs a distinct alert on `pvestatd failed` / `guest status=unknown` / **D-state mgmt-proc count** (the canary that caught this). A session-local persistent watcher (`logs/claude-gateway/watch-pve01.sh`) now emits on D-state>25 / pmxcfs-pvesh-rc!=0 / guest-loss, but a permanent Prometheus alert is the real fix.

## Monitoring armed (session-length)
`watch-pve01.sh` polls pve01 every 90s; emits on boot-settle, **guest-loss (set-difference vs settled baseline, so the always-stopped template doesn't false-fire)**, wedge-forming (dstate>25 / pmxcfs>6s), severe (node offline / pmxcfs timeout / dstate>50), recovery, + ~15-min heartbeat.
