# Network Topology Widget — Implementation Complete (2026-04-10)

## Status: DONE

Real-time interactive D3.js network topology widget on the portfolio site (`kyriakos.papadopoulos.tech/status/`). Shows the complete VPN mesh with per-WAN tunnel status, BGP upstreams, and transit AS paths — updated live every 30s.

## What Was Built

### Data Pipeline

```
vpn-mesh-stats.py (SSH to ASAs/VPS, Prometheus, LibreNMS, RIPE RIS)
       ↓
n8n webhook: GET /webhook/mesh-stats (workflow PrcigdZNWvTj9YaL)
       ↓
Hugo CI bakes to data/mesh_stats.json (instant first paint)
       ↓
auto-refresh.js polls /api/mesh-stats every 30s (live updates)
       ↓
mesh-graph.js D3 force graph + updateData() for in-place refresh
```

### Files Modified

**claude-gateway repo** (`n8n/claude-gateway`):
- `scripts/vpn-mesh-stats.py` — Added BGP session check for xs4all standby detection, `tunnels_standby` per-site field, isolated BGP SSH session

**portfolio repo** (`websites/papadopoulos.tech/kyriakos`):
- `static/js/mesh-graph.js` — Per-WAN parallel links, fan-to-converge geometry, standby rendering, live updateData()
- `static/js/auto-refresh.js` — Full widget update (graph + stat cards + site cards + latency matrix + mobile tunnels + failover + footer)
- `layouts/shortcodes/mesh-health.html` — `data-stat`, `data-site`, `id="mh-tunnel-list"` attributes for DOM targeting, version bumps

### 9 Tunnels Captured (Deduplicated)

| # | Link | WAN | Source of Truth | Check Method |
|---|---|---|---|---|
| 1 | NL ↔ GR | xs4all | NL ASA Tunnel1 | `show interface ip brief` |
| 2 | NL ↔ NO | xs4all | NL ASA Tunnel2 | `show interface ip brief` |
| 3 | NL ↔ CH | xs4all | NL ASA Tunnel3 | `show interface ip brief` |
| 4 | NL ↔ GR | freedom | NL ASA Tunnel4 | `show interface ip brief` |
| 5 | NL ↔ NO | freedom | NL ASA Tunnel5 | `show interface ip brief` |
| 6 | NL ↔ CH | freedom | NL ASA Tunnel6 | `show interface ip brief` |
| 7 | GR ↔ NO | inalan | GR ASA Tunnel2 | `show interface ip brief` via netmiko |
| 8 | GR ↔ CH | inalan | GR ASA Tunnel3 | `show interface ip brief` via netmiko |
| 9 | NO ↔ CH | vps | NO VPS swanctl | `swanctl --list-sas` |

GR Tunnel1/Tunnel4 = other end of NL Tunnel1/Tunnel4 (same IPsec SA, counted once from NL).

### Three Tunnel States

| State | Color | Style | Glow | Particles | When |
|---|---|---|---|---|---|
| `up` (active) | `#22c55e` green (freedom/inalan/vps) or `#15803d` dark green (xs4all) | Solid | Yes | Yes | Tunnel carrying traffic |
| `standby` (dormant) | `#15803d` dark green | Dashed | No | No | xs4all when Freedom is up (BCP38 blocks ESP) |
| `down` | `#ef4444` red | Dashed | No | No | Tunnel interface down |

### xs4all Standby Detection

**Root cause:** ASA tunnel source interface does NOT override the routing table for ESP egress. VPN peer host routes (metric 1 via Freedom, tracked by SLA) steer ALL outbound ESP through `outside_freedom` — including xs4all-sourced tunnels. Freedom ISP drops these via BCP38 (source IP mismatch).

**Detection method:** Separate SSH session to NL ASA runs `show bgp neighbors 10.255.200.1 | include BGP state`. If the xs4all VTI BGP peer is Active/Idle (not Established), all 3 xs4all tunnels are marked `standby`.

**Isolated SSH:** The BGP check runs in its own `ssh_nl_asa()` call. If it fails, `bgp_output` defaults to empty string → `xs4all_bgp = "unknown"` → xs4all tunnels still marked standby (safe default). Critical tunnel/SLA check is never affected.

### Per-WAN Parallel Link Geometry

NL has 2 ISPs (freedom + xs4all), so 2 lines fan out from the NL circle per destination:

```
     NL ──freedom──╲
     NL ──xs4all───╱── GR (single point)
```

- **Source end (NL):** 12px perpendicular offset between the two lines
- **Target end (GR/NO/CH):** Both lines converge to the circle center (single ISP endpoint)
- Labels at midpoint with 50% offset (readable separation)
- Particles taper along the fan: full offset at source, zero at target (`(1-p)` factor)
- Force simulation strength normalized: `0.4 / linkTotal` per link (prevents double-pull on multi-link pairs)

### Node Circle Health

The `nStroke` function determines site circle color:

```js
var down = d.tunnels_total - d.tunnels_up - (d.tunnels_standby || 0);
return down <= 0 ? '#22c55e' : d.tunnels_up > 0 ? '#f59e0b' : '#ef4444';
```

Standby tunnels are subtracted from the "down" count — they're dormant backups, not failures. Currently: NL = 3 up + 3 standby + 0 down = green.

### Live Refresh Architecture

`auto-refresh.js` calls `updateMeshWidget(fullData)` which:

1. **D3 graph** — `window.__meshGraph.update(fullData)`: updates node data (tunnels, WAN, availability), recomputes per-WAN link status from `wanLookup`, re-applies all visual attributes (stroke, dash, filter, glow), updates particle opacity
2. **Stat cards** — `data-stat` selector: tunnels, BGP, failover layers, ClusterMesh, latency, MTTR
3. **Site cards** — `data-site` selector: tunnel counts, uptime %, WAN status, devices, alerts
4. **Latency matrix** — tbody rebuild with CSS color classes
5. **Mobile tunnel list** — `#mh-tunnel-list` innerHTML rebuild
6. **Failover event** — `.mh-failover-event` text update
7. **Footer** — timestamp update

Hugo-baked HTML provides instant first paint. Live data seamlessly replaces it on the first fetch (auto-refresh calls `refresh()` immediately on init).

## Design Decisions

1. **Per-WAN links, not aggregated** — Shows dual-WAN redundancy at a glance. When Freedom fails, you see 3 red lines drop while 3 dark green lines stay.
2. **Fan-to-converge, not parallel** — Two lines from NL converge at the single remote endpoint. Parallel lines at both ends was misleading (implied multiple ISPs at both sites).
3. **Dark green for xs4all, not blue** — Blue was confusing (BGP upstream links are already blue). Dark green (`#15803d`) is distinct from bright green (`#22c55e`) but clearly "green family."
4. **Standby ≠ down** — Dashed dark green (exists but dormant) vs dashed red (actually broken). Standby doesn't count toward node health degradation.
5. **In-place D3 update, not rebuild** — Mutates node/link data objects and re-applies D3 attr calls. Force simulation stays settled, no visual flash, chaos selections preserved.
6. **Isolated BGP SSH** — Separate SSH session for the xs4all BGP check. If it fails, tunnel status is unaffected (learned the hard way — combined session broke everything).

## Verified With Playwright

```
✓ NL ↔ GR (xs4all)  status=standby stroke=#15803d dash=6,3
✓ NL ↔ NO (xs4all)  status=standby stroke=#15803d dash=6,3
✓ NL ↔ CH (xs4all)  status=standby stroke=#15803d dash=6,3
✓ NL ↔ GR (freedom) status=up      stroke=#22c55e dash=solid
✓ NL ↔ NO (freedom) status=up      stroke=#22c55e dash=solid
✓ NL ↔ CH (freedom) status=up      stroke=#22c55e dash=solid
✓ GR ↔ NO (inalan)  status=up      stroke=#22c55e dash=solid
✓ GR ↔ CH (inalan)  status=up      stroke=#22c55e dash=solid
✓ NO ↔ CH (vps)     status=up      stroke=#22c55e dash=solid
```

All 4 site circles: green (`#22c55e`), tunnels_standby correctly excluded from "down" count.

## Commits (chronological)

| Repo | SHA | Description |
|---|---|---|
| portfolio | `50d3bdd` | feat: make mesh topology widget realtime via client-side polling |
| portfolio | `972e512` | feat: show per-WAN parallel links on network topology graph |
| portfolio | `adfb02f` | fix: converge dual-WAN lines at remote site, use color to distinguish ISPs |
| portfolio | `50a36b0` | feat: render xs4all standby tunnels as dashed lines without glow |
| claude-gateway | `7d11c7c` | feat: detect xs4all VTI standby state via BGP session check |
| claude-gateway | `c7bb1b9` | fix: isolate BGP check into separate SSH session |
| portfolio | `3314db3` | fix: preserve "standby" tunnel status instead of coercing to "down" |
| claude-gateway | `40c282b` | feat: add tunnels_standby count to site data in mesh stats API |
| portfolio | `c50bb8d` | fix: treat standby tunnels as healthy for node circle color |
| portfolio | `617e520` | fix: change xs4all color to dark green, bump both JS versions |

## Future Work (from original spec, not yet implemented)

- Status banner with compound state detection (All Clear / Freedom Down / Transit Active)
- Detail panels on node click (BGP peer table, ESP counters, SLA track)
- BFD session visualization between FRR route reflectors
- K8s cluster nodes with Cilium BGP worker states
- ClusterMesh VXLAN overlay link
- Stale data indicator (>600s without refresh)
