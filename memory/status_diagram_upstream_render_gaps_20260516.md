---
name: status-diagram-upstream-render-gaps-20260516
description: "RESOLVED 2026-05-16 (after one false-start iteration). kyriakos.papadopoulos.tech/status/ BGP diagram was rendering 4 transit bubbles all under iFog, 0 under Terrahost (real RIPE+bgp.tools view is 7+2). Final shipped fix: claude-gateway b7c8ca5 (suffix-pair aggregation + per-upstream top-7 cap + min-obs=4 floor in vpn-mesh-stats.py) + kyriakos 402ca0f (mesh-graph.js: transit row y bumped from cy-0.82*baseR to cy-1.0*baseR, single one-constant change; mesh-health.html: cache-buster v=40->41). First attempt 37462f3 introduced a per-upstream radial fan layout — operator rejected as 'complete disaster', reverted via c69581e. Operator preference confirmed: preserve the existing single-row transit visual; never reinvent layouts. Open follow-up: 5-item improvement list discussed (Prometheus alert + visual indicators for BGP failure states) — operator green-lit, not yet built."
metadata: 
  node_type: memory
  type: project
  originSessionId: 2a7d5591-5f5e-4fd2-8fe8-5101e94f5112
---

# kyriakos.papadopoulos.tech/status/ — BGP diagram upstream/transit under-rendering

**Status:** RESOLVED 2026-05-16 (second attempt landed clean). Final shipped:
- `claude-gateway` `b7c8ca5` on `fix/agentic-stats-tier-classify` — aggregation
  rewrite in `scripts/vpn-mesh-stats.py` (suffix-pair counting, MIN_OBS=4 floor,
  MAX_PER_UPSTREAM=7 cap). Output: 7+2 matching bgp.tools.
- `kyriakos` `402ca0f` on `main` — **one-constant** change in
  `static/js/mesh-graph.js`: transit row y from `cy-0.82*baseR` to
  `cy-1.0*baseR` (lifts row from y=100 to y=58 in 580h canvas, gives 65 px
  vertical separation vs the old 23 px). Plus `mesh-health.html` cache-buster
  bump `v=40 → v=41`.

**Failed first attempt (do not redo):** `kyriakos` `37462f3` introduced a
per-upstream radial fan layout (each upstream's transits in an angular arc
above it). Operator rejected hard ("complete disaster"). Reverted in `c69581e`.
Lesson saved: [[feedback-mesh-graph-cache-buster]] + [[feedback-preserve-row-layout-on-status-diagram]].

**Operational gaps still open** (5-item improvement list, operator green-lit,
implementation in progress next session):
1. Make `updateData()` rebuild Layer 2 + 3 on auto-refresh diff (currently
   BGP layer freezes at page load).
2. Colour upstream bubbles by RIPE `power`.
3. Baseline file + "WITHDRAWN" indicator for missing-since-baseline upstreams.
4. Surface `visibility_v6_pct` on the diagram (drop to amber if <95%).
5. **Prometheus alert** (`AS64512_upstreams_changed` etc.) — wired via
   `scripts/write-bgp-upstream-metrics.py` cron → textfile collector →
   alertmanager → Matrix + Twilio. Architecture explained in conversation.

## Data flow (verified by Playwright + direct RIPE STAT)

```
RIPE STAT (no auth, free)
  ├── /data/routing-status/data.json?resource=AS64512
  ├── /data/asn-neighbours/data.json?resource=AS64512       ← upstreams (left-neighbours)
  └── /data/looking-glass/data.json?resource=2a0c:9a40:8e20::/48  ← AS paths
        │
        ▼
scripts/vpn-mesh-stats.py:640-726  (get_ripe_bgp())
        │
        ▼
n8n /webhook/mesh-stats (PrcigdZNWvTj9YaL)  +  Hugo data/mesh_stats.json
        │
        ▼
window.__meshData (baked) + auto-refresh.js poll
        │
        ▼
static/js/mesh-graph.js:188-221  (BGP layer code)
        │
        ▼
SVG render — Layer 2 upstream nodes + Layer 3 transit nodes
```

## What's rendered today (Playwright-extracted from live SVG, 2026-05-16)

* Upstream nodes (Layer 2): **2** — AS34927 iFog (linked from NO), AS56655 Terrahost (linked from CH)
* Transit nodes (Layer 3): **4** — AS6939, AS8218, AS9002, AS58057 — **all linked from iFog**
* Transit links from Terrahost: **0**

## What RIPE actually sees (live, same moment)

* `asn-neighbours` returns 2 left-neighbours: AS34927 (power 243) + AS56655 (power 31) — both rendered correctly
* `looking-glass` returns 364 paths from 320 RIS peers — 97 distinct (transit, upstream) pairs
* Via iFog: 12+ transits (AS6939×142, AS9002×36, AS174×10, AS6830×8, AS8218×7, AS1299×6, AS58057×4, AS34019×4, AS12779×4, AS24482×4, AS29632×3, AS14840×3, …)
* Via Terrahost: AS6939×16, AS1299×9, AS24482×3, + tail

## Root cause — three coupled limits in the rendering pipeline

1. **`vpn-mesh-stats.py:721`** caps transits at `Counter(paths).most_common(5)`. Live top-5 are all iFog because iFog's path counts dominate Terrahost's ~6:1.
2. **Counter key is exact AS-path string**, not (transit, upstream) pair. 4-hop and 5-hop paths get split across keys by RIS-peer prepending (`2497 6939 34927 214304` ≠ `2500 6939 34927 214304`), inflating iFog's dominance and burning slots.
3. **`mesh-graph.js:204`** rejects any `top_paths` entry with `hops.length < 3`. Currently slot #5 is the 2-hop path `34927 214304` (count=4), silently dropped — so only 4 of the 5 slots actually render.

Plus an unrelated structural one: **`mesh-graph.js:25`** has `UP_SITE = { 34927: 'NO', 56655: 'CH' }` — hardcoded site→upstream mapping. NL/GR/TX cannot get an upstream link regardless of RIPE data.

## Patch options (presented to operator, not yet chosen)

| Opt | Change | Effect | Diff size |
|---|---|---|---|
| A | `most_common(5)` → `most_common(25)` in vpn-mesh-stats.py:721 | Terrahost gets 2-3 transit bubbles; iFog → ~12 | 1 char |
| B | Count by `(hop[-3], hop[-2])` pair instead of exact-path string | Collapses RIS-peer noise; tighter top-N | ~6 lines |
| C | Per-upstream `asn-neighbours` call → real eBGP graph | Most accurate; 2 extra RIPE calls; <1s | ~15 lines |
| D | Derive `UP_SITE` from data | NL/GR/TX upstreams render automatically | ~10 lines + needs new field in stats payload |

**Recommended (presented):** B + A combined for the small-diff path. Add C if operator wants the real eBGP graph rather than RIS-observed-only.

## Artifacts saved (do not delete during cleanup)

* `visual-audit/playwright.status-upstream.config.js`
* `visual-audit/tests/status-upstream-audit.spec.js`
* `visual-audit/reports/status-upstream-audit/diagram.png` (cropped SVG screenshot)
* `visual-audit/reports/status-upstream-audit/full-page.png`
* `visual-audit/reports/status-upstream-audit/summary.json` (rendered node/link inventory + baked meshData)

The Playwright test is reusable as a regression check for any future fix: it
extracts the rendered SVG node/link set + the baked `__meshData` and writes a
machine-readable summary.

## Live-state evidence (verified 2026-05-16 ~22:55 UTC)

```
Direct RIPE asn-neighbours AS64512: 2 left-neighbours (AS34927, AS56655)   ← truth
Direct RIPE looking-glass /48:       364 paths, 97 distinct (transit,upstream) pairs   ← truth
n8n /webhook/mesh-stats:             generated_at=2026-05-16T22:56:23Z (live, fresh)
  upstreams: [AS34927 power=243, AS56655 power=31]                          ← matches RIPE
  top_paths: [
    6939 34927 214304 (15),
    8218 34927 214304 (7),
    9002 34927 214304 (6),
    58057 34927 214304 (4),
    34927 214304 (4)    ← rejected by mesh-graph.js (hops<3)
  ]                                                                          ← truncated view
Rendered SVG (Playwright):           4 transit nodes, all linked from iFog   ← matches top_paths after the hops<3 filter
```

## Confidence

**0.95.** End-to-end verified: RIPE API → Python script source → live webhook
payload → Hugo bake → SVG DOM via Playwright. The discrepancy the operator
described ("terrahost has no upstream bubbles at all; ifog has more upstreams
than the ones visible") is exactly what the three coupled limits predict.

The only thing not 100% nailed down is whether the operator wants A+B (data
visible from RIS) or also C (real eBGP graph from per-upstream
`asn-neighbours`) — the right answer depends on what story the diagram should
tell: "what the public internet sees" vs "what we've actually peered". B+A is
the smaller change.

## Related code references

* `scripts/vpn-mesh-stats.py:640-726` — RIPE STAT fetch + top_paths aggregation
* `static/js/mesh-graph.js:19-25` — AS_NAMES + UP_SITE hardcoded
* `static/js/mesh-graph.js:188-221` — Layer 2 + Layer 3 BGP node construction
* `layouts/shortcodes/mesh-health.html:56-57` — Hugo bakes `__meshData` from `site.Data.mesh_stats`

Linked feedback (not yet written — write only after operator picks a fix path):
`[[feedback-ris-path-aggregation-by-suffix]]` (placeholder slug for "count by
truncated AS-path suffix, never by full path string, when visualising").
