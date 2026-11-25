# Implementation Prompt: DMZ Cluster Monitoring + Full Chaos Engineering Suite

## Objective

Extend the portfolio status page (`kyriakos.papadopoulos.tech/status/`) with:
1. DMZ cluster nodes on the network topology graph
2. Monitoring for 5 clustered web services from both NL and GR sites
3. Full chaos engineering suite covering both VPN tunnel sabotage AND web service failover testing

## Current State (2026-04-10)

### What's Already Built

**Network Topology Widget** (`mesh-graph.js v25`):
- 17 nodes: 4 sites (pinned), 4 FRR RRs (pinned), 2 K8s clusters (pinned), 2 upstream AS (pinned), 5 transit AS (pinned)
- 18 links: 9 VPN tunnels, 2 eBGP-K8s, 1 ClusterMesh, 2 upstream, 5 transit
- Status banner (normal/degraded/critical), click detail panels, stale data indicator
- Failover animation with toast notifications
- Industry-standard D3 force simulation (all nodes pre-computed + frozen)
- Link type legend, per-WAN parallel links (freedom + xs4all fan-to-converge)
- xs4all standby detection via BGP session check

**Service Health** (`service-health.js v8`):
- Dual-Gatus architecture: NL Gatus + GR Gatus for cross-site monitoring
- 37 services across 8 categories, zero blank cells
- localStorage cache for instant first paint
- Modern minimal design with sticky column headers

**Chaos Engineering** (`chaos.js` + `chaos-test.py`):
- VPN tunnel sabotage: 4 pre-built scenarios + custom multi-tunnel selection
- Cloudflare Turnstile CAPTCHA protection
- SSH to ASAs (pexpect/netmiko) and VPS hosts (swanctl) for tunnel kill/restore
- Dead-man switch via `at` command for auto-recovery
- Live device syslog streaming during active tests
- Rate limit: 1 test per hour
- Frontend: tunnel toggle dots, kill bar, confirm modal, log panel, summary panel

### What's Missing

1. **DMZ nodes not on the topology graph** — nl-dmz01 and gr-dmz01 are not visualized
2. **4 of 5 target domains not in Gatus** — only kyriakos.papadopoulos.tech is monitored
3. **No web service chaos testing** — only VPN tunnel sabotage exists
4. **No container-level monitoring** — Docker container status not exposed in any API

---

## Infrastructure Reference

### DMZ Hosts

| Host | Site | IP | PVE Host | vCPUs | RAM |
|------|------|-----|----------|-------|-----|
| nl-dmz01 | NL | 10.0.X.X | nl-pve01 | 2 | 4GB |
| gr-dmz01 | GR | 10.0.X.X | gr-pve01 | 2 | 4GB |

Both run identical Docker stacks — active-active HA. DNS/Cloudflare routes to both via HAProxy on VPS nodes (NO + CH) or direct.

### SSH Access to DMZ Hosts

```bash
# NL DMZ (from app-user on nl-claude01)
ssh -i ~/.ssh/one_key operator@nl-dmz01
# Password for sudo: REDACTED_PASSWORD

# GR DMZ (from app-user, via OOB gateway)
ssh -p 2222 -i ~/.ssh/one_key app-user@203.0.113.X
# Then from grclaude01:
ssh -i ~/.ssh/one_key operator@gr-dmz01
```

### 5 Target Websites (Clustered on Both DMZ Hosts)

| Domain | Container | Port (both hosts) | Image |
|--------|-----------|-------------------|-------|
| kyriakos.papadopoulos.tech | portfolio | 443 | ghcr.io/papadopouloskyriakos/portfolio:latest |
| get.cubeos.app | cubeos-website | 8446 | ghcr.io/cubeos-app/website:latest |
| meshsat.net / hub.meshsat.net | meshsat-website | 8452 | ghcr.io/papadopouloskyriakos/meshsat-website:latest |
| mulecube.com | mulecube | 8444 | ghcr.io/papadopouloskyriakos/mulecube:latest |

### Full Docker Service Inventory (Both DMZ Hosts)

12 containers per host, each in its own `docker-compose.yml`:
- portfolio, cubeos-website, cubeos-demo, cubeos-releases
- mulecube, mulecube-dashboard
- meshsat-website, meshsat-docs, meshsat-releases
- withelli, beta-withelli
- NL-only: umami (analytics)

IaC paths:
- NL: `/app/infrastructure/nl/production/edge/dmz/nl-dmz01/`
- GR: `/app/infrastructure/nl/production/edge/dmz/gr-dmz01/`

Each service directory has `docker-compose.yml` + certs mounted from `/srv/certs/`.

### Gatus Configuration (Terraform)

- NL Gatus: `/app/infrastructure/nl/production/k8s/namespaces/gatus/main.tf`
- GR Gatus: `/app/infrastructure/gr/production/k8s/namespaces/gatus/main.tf`

Currently monitoring `kyriakos.papadopoulos.tech` only. Need to add:
- `get.cubeos.app`
- `meshsat.net`
- `hub.meshsat.net`
- `mulecube.com`

### Existing Chaos Test Tunnel Definitions (`chaos.js` lines 7-20)

```javascript
TINFO = {
  'NL ↔ GR|xs4all':  { asa: 'nl-fw01', iface: 'Tunnel1', nameif: 'vti-gr' },
  'NL ↔ NO|xs4all':  { asa: 'nl-fw01', iface: 'Tunnel2', nameif: 'vti-no' },
  'NL ↔ CH|xs4all':  { asa: 'nl-fw01', iface: 'Tunnel3', nameif: 'vti-ch' },
  'GR ↔ NO|inalan':  { asa: 'gr-fw01', iface: 'Tunnel2', nameif: 'vti-no' },
  'GR ↔ CH|inalan':  { asa: 'gr-fw01', iface: 'Tunnel3', nameif: 'vti-ch' },
  'NO ↔ CH|vps':     { asa: 'notrf01vps01', iface: 'swan0', nameif: 'ipsec-ch' }
};
```

Backend: `scripts/chaos-test.py` (663 lines) — SSH pexpect to ASAs, netmiko via OOB for GR, swanctl for VPS.

---

## Implementation Plan

### Phase 1: Add Gatus Monitoring for 4 Missing Domains

**Files to modify:**
- `/app/infrastructure/nl/production/k8s/namespaces/gatus/main.tf`
- `/app/infrastructure/gr/production/k8s/namespaces/gatus/main.tf`

Add identical endpoint blocks to both NL and GR Gatus configs:

```hcl
{
  name     = "CubeOS"
  group    = "📱 Applications"
  url      = "https://get.cubeos.app"
  interval = "30s"
  conditions = [
    "[STATUS] == 200",
    "[RESPONSE_TIME] < 3000"
  ]
},
{
  name     = "MeshSat"
  group    = "📱 Applications"
  url      = "https://meshsat.net"
  interval = "30s"
  conditions = [
    "[STATUS] == 200",
    "[RESPONSE_TIME] < 3000"
  ]
},
{
  name     = "MeshSat Hub"
  group    = "📱 Applications"
  url      = "https://hub.meshsat.net"
  interval = "30s"
  conditions = [
    "[STATUS] == 200",
    "[RESPONSE_TIME] < 3000"
  ]
},
{
  name     = "Mulecube"
  group    = "📱 Applications"
  url      = "https://mulecube.com"
  interval = "30s"
  conditions = [
    "[STATUS] == 200",
    "[RESPONSE_TIME] < 3000"
  ]
},
```

**Deploy:** Create MR → Atlantis plan → Atlantis apply → verify both Gatus APIs return the new endpoints.

**Verification:**
```bash
curl -sf "https://nl-gatus.example.net/api/v1/endpoints/statuses" | python3 -c "import json,sys; [print(e['name']) for e in json.load(sys.stdin) if 'CubeOS' in e['name'] or 'MeshSat' in e['name'] or 'Mulecube' in e['name']]"
```

### Phase 2: Add DMZ Nodes to Topology Graph

**Files to modify:**
- `scripts/vpn-mesh-stats.py` — add `dmz_nodes` section to API output
- `static/js/mesh-graph.js` — add Layer 1.5 DMZ nodes + links to site nodes

**API data structure (add to vpn-mesh-stats.py output):**
```python
"dmz_nodes": [
    {
        "id": "NL-DMZ", "label": "DMZ", "site": "NL",
        "host": "nl-dmz01", "ip": "10.0.X.X",
        "containers_total": 12, "containers_up": 12,
        "services": ["portfolio", "cubeos-website", "mulecube", "meshsat-website", ...],
    },
    {
        "id": "GR-DMZ", "label": "DMZ", "site": "GR",
        "host": "gr-dmz01", "ip": "10.0.X.X",
        "containers_total": 11, "containers_up": 11,
        "services": [...],  # same minus umami
    },
],
```

**Container health check (vpn-mesh-stats.py):**
```bash
# SSH to DMZ host, count running containers
ssh -i ~/.ssh/one_key operator@nl-dmz01 'docker ps --format "{{.Names}}" | wc -l'
# Or check specific containers
ssh -i ~/.ssh/one_key operator@nl-dmz01 'docker ps --format "{{.Names}}|{{.Status}}" | head -15'
```

**Graph rendering (mesh-graph.js):**
- New node type: `nodeType: 'dmz'`, Layer 1.5
- Color: `#f97316` (orange, Tailwind orange-500) — distinct from RR (purple) and K8s (cyan)
- Radius: 16px
- Position: between site node and K8s node, pinned
- Links: `site → DMZ` (type: 'dmz-link')
- Tooltip: host, IP, container count, service list
- Detail panel: per-container status table

### Phase 3: DMZ Web Service Chaos Engineering

**New chaos scenarios to add to `chaos-test.py`:**

#### Scenario A: Single Container Kill
```python
{
    "id": "dmz-container-kill",
    "name": "Kill Single DMZ Container",
    "description": "Stop one web service container on one DMZ node, verify cross-site failover",
    "params": {
        "host": "nl-dmz01|gr-dmz01",
        "container": "portfolio|cubeos-website|meshsat-website|mulecube",
        "duration_seconds": 120,
    },
    "mechanism": "SSH to host → docker stop <container> → wait → docker start <container>",
    "expected_impact": "Service unreachable from the killed site. Other site serves traffic. DNS failover via HAProxy/Cloudflare.",
    "verification": [
        "Gatus NL reports DOWN for the killed service",
        "Gatus GR still reports UP (or vice versa)",
        "Response time from surviving site increases",
        "After recovery: both sites report UP within 30s",
    ],
}
```

#### Scenario B: Full DMZ Node Kill
```python
{
    "id": "dmz-node-kill",
    "name": "Kill All Containers on DMZ Node",
    "description": "Stop ALL containers on one DMZ node, verify full cross-site failover",
    "params": {
        "host": "nl-dmz01|gr-dmz01",
        "duration_seconds": 180,
    },
    "mechanism": "SSH to host → docker stop $(docker ps -q) → wait → docker start $(docker ps -aq)",
    "expected_impact": "All web services on that site unreachable. Other site serves all traffic.",
}
```

#### Scenario C: Combined Tunnel + DMZ Kill
```python
{
    "id": "tunnel-plus-dmz",
    "name": "Tunnel Kill + DMZ Container Kill",
    "description": "Kill VPN tunnel AND a DMZ container simultaneously — worst-case failover test",
    "params": {
        "tunnel": "NL ↔ GR|freedom",
        "host": "gr-dmz01",
        "container": "portfolio",
        "duration_seconds": 120,
    },
    "mechanism": "Kill tunnel (existing ASA shutdown) + Kill container (Docker stop)",
    "expected_impact": "GR portfolio unreachable. NL portfolio accessible. VPN failover to xs4all/FRR transit.",
}
```

**Backend implementation (`chaos-test.py` additions):**

```python
def ssh_dmz_docker(host, action, container=None):
    """SSH to DMZ host and execute Docker command."""
    if host == "nl-dmz01":
        ssh_cmd = f"ssh -i ~/.ssh/one_key operator@{host}"
    elif host == "gr-dmz01":
        # Via OOB gateway
        ssh_cmd = "ssh -p 2222 -i ~/.ssh/one_key app-user@203.0.113.X 'ssh operator@gr-dmz01'"
    
    if action == "stop":
        docker_cmd = f"docker stop {container}" if container else "docker stop $(docker ps -q)"
    elif action == "start":
        docker_cmd = f"docker start {container}" if container else "docker start $(docker ps -aq)"
    elif action == "status":
        docker_cmd = "docker ps --format '{{.Names}}|{{.Status}}'"
    
    # Execute via subprocess with timeout
    result = subprocess.run(
        [*ssh_cmd.split(), docker_cmd],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout

def execute_dmz_chaos(params):
    """Execute DMZ container chaos test with dead-man switch."""
    host = params["host"]
    container = params.get("container")  # None = all containers
    duration = params["duration_seconds"]
    
    # Safety: verify container exists and is running
    status = ssh_dmz_docker(host, "status")
    if container and container not in status:
        return {"error": f"Container {container} not found on {host}"}
    
    # Kill
    ssh_dmz_docker(host, "stop", container)
    
    # Schedule auto-recovery (dead-man switch)
    recovery_cmd = f"docker start {container}" if container else "docker start $(docker ps -aq)"
    schedule_recovery(host, recovery_cmd, duration + 60)
    
    return {
        "action": "dmz-container-kill",
        "host": host,
        "container": container or "ALL",
        "duration": duration,
        "killed_at": datetime.utcnow().isoformat(),
        "auto_recover_at": (datetime.utcnow() + timedelta(seconds=duration + 60)).isoformat(),
    }
```

**Frontend additions (`chaos.js`):**

1. Add mode toggle: "Tunnels" / "DMZ Services" in the chaos kill bar
2. In DMZ mode, show a dropdown of DMZ hosts + containers instead of tunnel toggles
3. Pre-built scenario selector: "Single Container" / "Full Node" / "Combined"
4. During active DMZ test: poll `/api/service-health` every 5s and highlight affected services in red
5. Summary panel: show which services were affected, from which site, recovery time

### Phase 4: E2E Testing

**Test matrix:**

| Test | Scenario | Expected | Verification |
|------|----------|----------|-------------|
| T1 | Kill `portfolio` on nl-dmz01 | GR serves portfolio, NL returns 5xx | Gatus NL DOWN, GR UP |
| T2 | Kill `portfolio` on gr-dmz01 | NL serves portfolio, GR returns 5xx | Gatus GR DOWN, NL UP |
| T3 | Kill all containers on nl-dmz01 | GR serves all services | All services: NL DOWN, GR UP |
| T4 | Kill NL↔GR tunnel + `portfolio` on GR | Only NL portfolio reachable via xs4all/transit | Tunnel failover + service failover |
| T5 | Kill `cubeos-website` on both hosts | get.cubeos.app completely down | Both sites DOWN, compound status CRITICAL |
| T6 | Recovery from T1 | `docker start portfolio` → NL comes back <30s | Both Gatus UP |

**Playwright E2E test script:**
```javascript
// 1. Start chaos test via API
// 2. Poll service-health until affected service shows DOWN
// 3. Verify surviving site still shows UP
// 4. Trigger recovery
// 5. Poll until both sites show UP
// 6. Verify topology graph shows correct status throughout
// 7. Verify failover toast appears
// 8. Screenshot at each stage
```

### Phase 5: Monitoring Dashboard Integration

After chaos tests, add Grafana panels:
- DMZ container uptime per host (from Docker health checks or Prometheus node-exporter)
- Cross-site failover latency (time from container kill to DNS failover detection)
- Service reachability matrix (NL→service, GR→service, NO→service, CH→service)

---

## Files to Modify (Complete List)

### Infrastructure (IaC repos, needs MR + Atlantis)
- `infrastructure/nl/production/k8s/namespaces/gatus/main.tf` — add 4 Gatus endpoints
- `infrastructure/gr/production/k8s/namespaces/gatus/main.tf` — add 4 Gatus endpoints

### Backend (claude-gateway repo)
- `scripts/vpn-mesh-stats.py` — add `dmz_nodes` section with container health via SSH
- `scripts/chaos-test.py` — add `ssh_dmz_docker()`, `execute_dmz_chaos()`, 3 new scenarios
- `scripts/service-health.py` — add DMZ-specific category or enhance existing Application category

### Frontend (portfolio repo)
- `static/js/mesh-graph.js` — add DMZ nodes (Layer 1.5, orange), links, tooltips, detail panels
- `static/js/chaos.js` — add DMZ mode toggle, container selector, DMZ scenarios
- `static/js/auto-refresh.js` — update DMZ node data on refresh
- `static/js/service-health.js` — highlight affected services during chaos tests
- `layouts/shortcodes/mesh-health.html` — pass DMZ data to D3, add mode toggle HTML
- `assets/css/extended/custom.css` — DMZ node styles, chaos DMZ mode styles

### Documentation
- `docs/prompt-network-topology-widget.md` — update with DMZ nodes + chaos suite
- `docs/prompt-chaos-engineering-dmz.md` — this file (mark phases as DONE)

---

## Testing & Verification

1. **Gatus endpoints:** `curl` both Gatus APIs, verify 4 new endpoints returning status
2. **Topology graph:** Playwright screenshot showing DMZ nodes with container counts
3. **Service health:** All 5 domains showing NL + GR response times, zero blanks
4. **Chaos container kill:** SSH to DMZ, `docker stop portfolio`, verify Gatus detects within 60s
5. **Chaos E2E via UI:** Select DMZ container → Kill → observe live status changes → Recover → verify
6. **Combined chaos:** Tunnel kill + container kill → verify compound failover works
7. **Rate limits:** Verify 1-hour cooldown applies to DMZ tests too
8. **Dead-man switch:** Kill container, wait for auto-recovery, verify container restarts

---

## Safety Constraints

- **NEVER kill containers on both DMZ hosts simultaneously** unless explicitly testing total outage (T5)
- **Dead-man switch mandatory** — `at` command or cron schedules auto-recovery
- **Turnstile CAPTCHA required** for all chaos actions (existing pattern)
- **Rate limit shared** between tunnel and DMZ chaos (1 test per hour total)
- **SSH key auth only** — no password in scripts (use `~/.ssh/one_key`)
- **sudo password** needed for Docker on DMZ hosts: `REDACTED_PASSWORD`
