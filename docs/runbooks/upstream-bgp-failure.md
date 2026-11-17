# Upstream BGP failure runbook (AS64512)

Triggered by: `AS64512UpstreamMissing`, `AS64512UpstreamCountLow`,
`AS64512VisibilityLow`. Meta-alert `AS64512BGPMetricsExporterStale`
fires when the exporter itself stops producing data.

## Topology recap

```
AS64512 (our /48 = 2a0c:9a40:8e20::/48)
  ├── upstream: iFog            AS34927   power ≈ 240
  └── upstream: Gigahost/       AS56655   power ≈  30
              Terrahost

iFog peers with ~7 transit ASes for our prefix.
Terrahost peers with ~2 transit ASes.

Both upstreams must drop for us to be globally unreachable.
Losing one = single-homed (no redundancy) — still functional.
```

## Where the data comes from

- Exporter:  `scripts/write-bgp-upstream-metrics.py` on `nl-claude01`, cron `*/5`
- Textfile:  `/var/lib/node_exporter/textfile_collector/bgp_upstream.prom`
- Source:    RIPE STAT live API (no auth), 3 calls per run:
  - `routing-status/data.json?resource=AS64512`
  - `asn-neighbours/data.json?resource=AS64512`
  - `looking-glass/data.json?resource=2a0c:9a40:8e20::/48`

## Severity decision tree

```
                Both upstreams visible?
                ├── YES → just visibility blip → AS64512VisibilityLow
                │         (warning, 15 min for:) — check RIPE/bgp.tools
                │
                └── NO  → which one is missing?
                        ├── iFog       → critical (we route most traffic via iFog)
                        ├── Terrahost  → critical (still single eBGP away from outage)
                        └── BOTH       → CRITICAL — site is globally unreachable
                                          page Tier-1 immediately
```

## Investigation steps

1. **Confirm at independent vantage points.** RIPE can have transient gaps.
   - bgp.tools:    `https://bgp.tools/prefix/2a0c:9a40:8e20::/48#connectivity`
   - Cloudflare:   `https://radar.cloudflare.com/as214304`
   - If at least one of those shows the upstream healthy, treat as RIPE-only
     hiccup. Wait 5-10 min and re-check; the alert will auto-resolve.

2. **Check our routers haven't dropped the session.** From the operator side,
   we're a customer of iFog/Terrahost — the eBGP sessions live on THEIR
   routers, not ours. But the BGP customer-portal at each:
   - iFog:       email `support@ifog.ch` + their customer portal
   - Gigahost:   email `support@gigahost.no` + their customer portal

3. **Verify our prefix is still being announced** (sanity check that we
   haven't shut down our own BGP). From any node on the mesh:
   ```bash
   # NL FRR
   ssh root@nlk8s-ctrl01 'sudo nsenter -t $(pgrep frr) -n ip route show 2a0c:9a40:8e20::/48'
   # If empty: our origin AS isn't injecting the route — we caused this.
   ```

4. **Confirm RIPE STAT itself is healthy.**
   ```bash
   curl -s 'https://stat.ripe.net/data/routing-status/data.json?resource=AS64512' \
     | jq '.data.visibility.v6'
   ```
   If this returns null or 5xx, the issue is at RIPE and our alerts are noise.

5. **Run the exporter manually to confirm metrics flow.**
   ```bash
   ssh nl-claude01 /app/claude-gateway/scripts/write-bgp-upstream-metrics.py
   ssh nl-claude01 cat /var/lib/node_exporter/textfile_collector/bgp_upstream.prom
   ```

## Common false-positive sources

- **RIS peer reshuffle:** RIPE occasionally rebalances which collectors see
  which paths. Visibility can drop to 80-95 % for an hour with no real-world
  impact. The 15-min `for:` clause on `AS64512VisibilityLow` absorbs most.
- **Upstream maintenance window:** iFog or Gigahost rebooting a transit
  router can cause a few minutes of session drop. The 10-min `for:` clause
  on `AS64512UpstreamMissing` absorbs typical maintenance.
- **First boot of the exporter:** if cron hasn't fired yet, the staleness
  alert will fire 30 min after deploy. Wait one cron cycle.

## Related

- Status diagram: `https://kyriakos.papadopoulos.tech/status/`
  (BGP layer renders the same data, refreshed at page load).
- Memory: `memory/status_diagram_upstream_render_gaps_20260516.md`.
- Lessons: `memory/feedback_mesh_graph_cache_buster.md`,
  `memory/feedback_preserve_row_layout_on_status_diagram.md`.
