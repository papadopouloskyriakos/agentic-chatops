# Maintenance Mode

When `/home/app-user/gateway.maintenance` exists (JSON file with `started`, `reason`, `eta_minutes`, `operator`), alert processing is suppressed:

- **LibreNMS + Prometheus receivers (NL+GR)**: maintenance check piggybacked on existing SSH load — zero extra latency, returns `maintenanceSuppressed: true`
- **WAL Self-Healer (GR)**: skips healing during maintenance
- **Gateway watchdog**: skips all checks (no restarts, no bounces)
- **OpenClaw infra-triage**: exits immediately with confidence 0.1 during maintenance, 50% reduction during 15min post-maintenance cooldown

The file is created/removed by the AWX `chatops/maintenance_mode.yaml` playbook, or automatically by `scripts/asa-reboot-watch.sh` for scheduled ASA reboots. After removal, a 15-minute cooldown period tags alerts as `post-maintenance-recovery`.

## ASA Weekly Reboot Suppression

Both Cisco ASA firewalls have EEM watchdog timers that auto-reload them:
- **nl-fw01 (NL):** `event timer watchdog time 604800` (7 days from last boot)
- **gr-fw01 (GR):** `event timer watchdog time 590400` (~6d 20h from last boot)

Reboot causes total site network outage (~5-10 min) + cross-site VPN drop. A 4-layer suppression system prevents false alerts:

| Layer | Component | How |
|-------|-----------|-----|
| 1 | LibreNMS | `scripts/asa-reboot-watch.sh` (cron `*/5`) checks ASA uptime, sets maintenance on all devices when reboot < 10min away |
| 2 | gateway.maintenance | Same watcher creates/removes the file automatically with `event_id` field |
| 3 | scheduled-events.json | `config/scheduled-events.json` checked by `infra-triage.sh` + `correlated-triage.sh` as fallback |
| 4 | Agent knowledge | SOUL.md, Runner Build Prompt, incident_knowledge DB (3 entries with embeddings) |

**Key:** Watchdog timers count from boot completion, so reboot times drift ~5min/cycle. The predictive watcher adapts automatically — no fixed cron schedule.

## Freedom ISP PPPoE Monitoring

NL ASA has dual WAN: **Freedom** (primary, 203.0.113.X + /29 subnet, PPPoE) and **xs4all** (backup, 145.53.163.13, single IP, PPPoE). Both WANs have **dual VTI tunnels per peer** — 3 on xs4all (Tunnel1-3) + 3 on Freedom (Tunnel4-6) = 6 total on NL ASA. The old crypto-map configs (48 entries + 59 NAT exemptions each) are unbound but in running config for rollback. Physical path: ASA Po1.6 (VLAN 6) → nl-sw01 Gi1/0/36 (PoE 802.3af) → TP-Link TL-PoE10R splitter (802.3af only) → Genexis XGS-PON ONT (1Gbps fiber).

**VPS 3-tier failover:** Both VPS (NO + CH) have ISP-specific tunnel names with automatic failover:
1. **Freedom direct** (`nl-dmz-freedom`, `nl-mgmt-freedom`, `nl-k8s-freedom` — `auto=start`)
2. **xs4all direct** (`nl-dmz-xs4all`, `nl-mgmt-xs4all`, `nl-k8s-xs4all` — `auto=route`, trap-based)
3. **Via GR backbone** (`nl-dmz-via-gr` — `auto=route`, last resort)

DPD (30s) detects dead Freedom peer → SLA track 1 flips → xs4all default route activates (metric 10). Freedom recovery → SLA track restores Freedom route (metric 1) + DPD restart re-establishes Freedom tunnels automatically. All 6 NL VTI tunnels (3 per WAN) provide full redundancy.

`scripts/freedom-qos-toggle.sh` (cron `*/2`) monitors Freedom PPPoE status:
- **Freedom DOWN** → applies tenant QoS (5/2 Mbps per room b/c/d) + sends **SMS** via Twilio to operator
- **Freedom UP** → removes QoS limits + sends SMS confirmation
- State tracked in `maintenance-state/freedom-qos.state`
- SMS bypasses Matrix dependency (works when Matrix is unreachable during outage)

**Triage integration:** `correlated-triage.sh` detects the Freedom burst pattern (NL "Service up/down" + GR "Devices up/down" simultaneously → 0.95 confidence). `infra-triage.sh` has Freedom fast-path check (SSH to ASA, `show vpdn pppinterface`). 3 `incident_knowledge` entries with embeddings for RAG retrieval.

## PVE Kernel Maintenance Playbooks

Full-site maintenance automation in `infrastructure/common` repo. **Run via AWX (cross-site)**:
- **GR maintenance** → launch from **NL AWX** template 69 (~60 min)
- **NL maintenance** → launch from **GR AWX** template 21 (~135 min)

Custom AWX EE (`awx-ee-maintenance`) with kubectl, curl, dig, redis-cli, cilium, showmount. SSH key + kubeconfig mounted via K8s secret `awx-ssh-one-key`. Image pre-loaded on all 7 K8s workers (`pull: never`). Dockerfile: `infrastructure/common/ansible/ee/Dockerfile`.

Required extra_vars: `operator`, `dry_run`, `api_token` (LibreNMS), `matrix_api_token`. Optional: `skip_email`, `skip_synology`.
