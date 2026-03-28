# GR Lab Infrastructure ChatOps — Implementation Spec

## Context

Copy-paste this entire file as the initial prompt for a new Claude Code session in the claude-gateway repo (`~/gitlab/n8n/claude-gateway`). Read CLAUDE.md in this repo first for the NL implementation reference — we're replicating the same ChatOps infrastructure for the GR (Greece/Thessaloniki) site.

Also read the GR IaC repo CLAUDE.md (`~/gitlab/infrastructure/gr/production/CLAUDE.md`) for full GR infrastructure context.

## Problem

The NL site (`nl`) has a complete ChatOps pipeline:
- Matrix rooms for alerts and commands (`#infra-nl-prod`)
- n8n workflows for LibreNMS alerts, Prometheus alerts, session management
- OpenClaw triage skills (infra-triage, k8s-triage, correlated-triage)
- Maintenance companion for planned events
- YouTrack project `IFRNLLEI01PRD` with custom fields

The GR site (`gr`) has **none of this**. It has:
- Prometheus + Alertmanager firing alerts (13 custom rules) → currently only to Matrix `#alerts` (NL-wide, no GR-specific room)
- AWX at `https://gr-awx.example.net` (K8s-hosted, 9 job templates)
- YouTrack project `IFRGRSKG01PRD` (exists, 33 issues)
- GitLab at `https://gr-gitlab.example.net/` (separate instance, project ID: 5)
- Dedicated GR LibreNMS instance (`gr-nms01`) hosted at the GR site, monitoring all GR devices
- No n8n alert receiver workflows for GR
- No dedicated Matrix room for GR infra alerts
- No OpenClaw triage skills for GR

## What to Build

### 1. Matrix Room: `#infra-gr-prod`

Create a dedicated Matrix room for GR infrastructure:
- Room alias: `#infra-gr-prod:matrix.example.net`
- Members: `@claude`, `@openclaw`, `@dominicus`
- Purpose: GR infra alerts, triage output, maintenance companion, commands
- Update the Matrix Bridge workflow to listen to this room and route `IFRGRSKG01PRD-*` issues here

### 2. n8n Workflow: `claude-gateway-prometheus-receiver-gr`

Clone the existing Prometheus receiver (`CqrN7hNiJsATcJGE`) but for GR alerts:
- **Trigger:** Webhook POST to `/prometheus-alert-gr`
- **Alert source:** GR Alertmanager (configure webhook receiver pointing to `https://n8n.example.net/webhook/prometheus-alert-gr`)
- **Fingerprint:** `alertname:namespace` (same as NL)
- **Persistence:** Dual-store — staticData + `active-prom-alerts-gr.json`
- **Dedup:** Same flap detection, 4h recovery TTL, auto-escalation after 2+ flaps
- **Matrix room:** Post to `#infra-gr-prod` (NOT `#infra-nl-prod`)
- **YT project:** `IFRGRSKG01PRD` (NOT `IFRNLLEI01PRD`)
- **Triage instruction:** `@openclaw` with GR-specific k8s-triage (see below)

### 2b. n8n Workflow: `claude-gateway-librenms-receiver-gr`

Clone the existing LibreNMS receiver (`Ids38SbH48q4JdLN`) but for GR alerts:
- **Trigger:** Webhook POST to `/librenms-alert-gr`
- **Alert source:** `gr-nms01` (dedicated GR LibreNMS, configure alert transport webhook to NL n8n via VPN)
- **Persistence:** Dual-store — staticData + `active-alerts-gr.json`
- **Dedup:** Per-hostname, same flap detection + 4h recovery TTL
- **Matrix room:** Post to `#infra-gr-prod`
- **YT project:** `IFRGRSKG01PRD`
- **Triage instruction:** `@openclaw` with GR-specific infra-triage

### 3. GR Alertmanager Configuration

Configure the GR Alertmanager to send webhooks to n8n:
- File: `~/gitlab/infrastructure/gr/production/k8s/namespaces/monitoring/custom-alerts.tf` (or alertmanager config)
- Add webhook receiver: `https://n8n.example.net/webhook/prometheus-alert-gr`
- Route: all non-Watchdog/InfoInhibitor/info alerts to the webhook
- **Note:** This is a cross-site webhook — GR Alertmanager → NL n8n (via IPsec VPN tunnel)

### 4. OpenClaw Skills: GR Triage

Create GR-specific triage skills (or extend existing ones):

**Option A (recommended): Extend existing skills with site awareness**
- Add `--site gr` flag to `infra-triage.sh` and `k8s-triage.sh`
- When site=gr: use GR YouTrack project (`IFRGRSKG01PRD`), GR kubeconfig context, GR SSH targets
- Avoids duplicating 1000+ lines of shell scripts

**Option B: Separate GR skills**
- `openclaw/skills/gr-infra-triage/` and `openclaw/skills/gr-k8s-triage/`
- Separate SKILL.md files, separate scripts
- More isolation but more maintenance

### 5. GR Kubeconfig for OpenClaw

OpenClaw needs kubectl access to the GR cluster for triage:
- GR K8s API: `https://gr-api-k8s.example.net:6443`
- Add GR kubeconfig context to claude-runner's `~/.kube/config` (if not already there)
- Add GR context to OpenClaw container (docker cp or mount)
- Triage scripts need `--context gr` or `KUBECONFIG` pointing to GR cluster

### 6. Maintenance Companion: GR Support

Extend `scripts/maintenance-companion.sh` with GR host awareness:
- GR PVE hosts: `gr-pve01`, `gr-pve02`
- GR configs path: `~/gitlab/infrastructure/gr/production/pve/`
- GR has its own dedicated LibreNMS (`gr-nms01`) — use its API for maintenance windows (same pattern as NL)
- Get `gr-nms01` URL and API key at session start, store in `.env` as `LIBRENMS_GR_URL` / `LIBRENMS_GR_API_KEY`
- Additionally support Prometheus Alertmanager silences for K8s-specific alerts
- GR AWX at `https://gr-awx.example.net` (different token than NL AWX)

### 7. Matrix Bridge Updates

Update the Matrix Bridge workflow (`QGKnHGkw4casiWIU`):
- Add `#infra-gr-prod` to the rooms list (poll `/sync`)
- Route `IFRGRSKG01PRD-*` issues to `#infra-gr-prod`
- Support `!issue` commands for GR YouTrack project
- Both `@claude` and `@openclaw` must join the new room

### 8. YouTrack Custom Fields for GR

Ensure `IFRGRSKG01PRD` has the same custom fields as `IFRNLLEI01PRD`:
- Hostname, Alert Rule, Severity, VMID, PVE Host, Resolution Type
- Namespace, Pod, Alert Source
- Use the YouTrack MCP to check/create these

### 9. `/maintenance` Slash Command: GR Support

Update the IaC repo `/maintenance` slash command to work in GR context:
- `.claude/commands/maintenance.md` in `~/gitlab/infrastructure/gr/production/`
- GR-specific host table, critical services, dependency map
- GR uses LibreNMS maintenance windows (same as NL) + Prometheus Alertmanager silences for K8s alerts

## GR Infrastructure Reference

| Host | Role | Notes |
|------|------|-------|
| gr-pve01 | Primary PVE | Physical server |
| gr-pve02 | Secondary PVE + NFS/iSCSI storage | Also serves K8s storage at 10.0.188.X |
| gr-fw01 | Core firewall (ASA 5508-X) | Public IP: 203.0.113.X, IPsec to NL/CH/NO |
| gr-sw01, sw02 | Core switches | Local site |
| grskg02sw01 | Remote switch | Different building |
| gr-dmz01 | DMZ VM (Ubuntu 24.04) | 7 Docker containers (portfolio, cubeos, mulecube) |
| gr-gitlab01 | GitLab instance | `https://gr-gitlab.example.net/` |
| gr-pihole01 | DNS | PiHole + Yacht |
| grnetalertx01 | Network monitoring | NetAlertX (L2 network scanning) |
| gr-nms01 | LibreNMS (dedicated GR instance) | Hosted at GR site, monitors all GR devices. Get URL + API key at session start. Same role as NL's nl-nms01. |
| grnpm01 | Reverse proxy | NPM + MariaDB + Syncthing |
| K8s nodes (3) | Worker nodes | 10.0.58.X-22, Cilium, ClusterMesh to NL |

## Key Differences: GR vs NL

| Aspect | NL (nl) | GR (gr) |
|--------|-------------|-------------|
| Monitoring | LibreNMS (SNMP) + Prometheus | LibreNMS + Prometheus + NetAlertX |
| Alert source | LibreNMS webhooks + Prometheus | LibreNMS webhooks + Prometheus |
| Alert suppression | LibreNMS maintenance windows | LibreNMS maintenance windows + Alertmanager silences |
| PVE hosts | 3 (pve01/02/03) | 2 (pve01/02) |
| K8s nodes | 7 (3 ctrl + 4 worker) | 3 (workers only, no dedicated ctrl plane?) |
| AWX | `https://awx.example.net` | `https://gr-awx.example.net` |
| GitLab | `https://gitlab.example.net/` | `https://gr-gitlab.example.net/` |
| Matrix room | `#infra-nl-prod` | `#infra-gr-prod` (TO CREATE) |
| YT project | `IFRNLLEI01PRD` | `IFRGRSKG01PRD` |
| LibreNMS | nl-nms01 (NL devices) | gr-nms01 (GR devices, dedicated instance at GR site) |
| VPN to NL | — | IPsec tunnel (ASA-to-ASA) |

## Cross-Site Considerations

1. **n8n runs on NL only** (nl-n8n01 on pve01). GR alerts must traverse the IPsec VPN to reach n8n webhooks. If VPN is down, GR alerts won't reach the pipeline.

2. **Matrix runs on NL only** (nl-matrix01 on pve01). Same VPN dependency.

3. **TLS certs**: NL cert-manager produces wildcard cert → OpenBao → GR consumes. If NL cert-manager fails, GR certs don't renew.

4. **ClusterMesh**: NL and GR K8s clusters are connected via Cilium ClusterMesh (mTLS/SPIRE). Cross-cluster service discovery is active.

5. **Thanos federation**: GR Prometheus → Thanos sidecar → NL Thanos query. Cross-site metrics available in NL Grafana.

## Definition of Done

- [ ] Matrix room `#infra-gr-prod` created, both bots joined
- [ ] n8n Prometheus receiver workflow for GR created and active
- [ ] GR Alertmanager configured to send webhooks to NL n8n
- [ ] OpenClaw triage skills work with GR site (k8s context, YT project)
- [ ] Matrix Bridge updated to listen to new room + route GR issues
- [ ] YouTrack `IFRGRSKG01PRD` has all required custom fields
- [ ] Maintenance companion supports GR hosts (Prometheus silences, GR PVE configs)
- [ ] `/maintenance` slash command in GR IaC repo
- [ ] End-to-end test: trigger a GR Prometheus alert → triage → YT issue → Matrix notification

## Tone

Same as NL: active, concise, proactive. The GR site should feel like a first-class citizen, not an afterthought. Same quality of triage, same response time, same Matrix visibility.
