---
name: feedback-mesh-graph-updatedata-key-shape
description: "When adding code to `mesh-graph.js`'s `updateData(fullData)` that reads keys off fullData, ALWAYS accept BOTH camelCase (initial Hugo-baked __meshData) and snake_case (auto-refresh.js raw /api/mesh-stats payload). Hugo bakes `bgp/dmzNodes/latencyMatrix`; the API returns `public_bgp/dmz_nodes/latency_matrix`. updateData runs every 30s with the snake_case shape — get it wrong and the diagram corrupts state on the first auto-refresh tick."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2a7d5591-5f5e-4fd2-8fe8-5101e94f5112
---

# updateData(fullData) must accept BOTH camelCase + snake_case keys

**Rule:** Any code added to `mesh-graph.js`'s `function updateData(fullData) { ... }` that reads new keys from `fullData` must accept both:

- **camelCase** — Hugo template `layouts/shortcodes/mesh-health.html:56` builds `__meshData` as:
  ```
  $graphData := dict "sites" $stats.sites "bgp" $stats.public_bgp
                     "dmzNodes" $stats.dmz_nodes "latencyMatrix" $stats.latency_matrix ...
  ```
  Used only at IIFE startup for the initial render.

- **snake_case** — `auto-refresh.js` polls `/api/mesh-stats` every 30 s and calls:
  ```js
  fetch(MESH_URL).then(r => r.json()).then(fullData => {
    window.__meshGraph.update(fullData);
  });
  ```
  `fullData` is the **raw n8n payload**, keys are `public_bgp`, `dmz_nodes`, `latency_matrix`, etc.

The existing `updateData` body has been adjusted over time to accept snake_case (`fullData.dmz_nodes`, `fullData.latency_matrix || fullData.latencyMatrix`). Anything new must do the same. Pattern:

```js
var newBgp = (fullData && (fullData.public_bgp || fullData.bgp)) || {};
var newDmz = fullData.dmz_nodes || fullData.dmzNodes || [];
var newLatency = fullData.latency_matrix || fullData.latencyMatrix || {};
```

**Why this matters:** the initial render works fine (camelCase). The bug only manifests **30 s later**, when auto-refresh fires the first tick. Page-load screenshots and short Playwright tests miss it entirely.

**Caught 2026-05-17** on the v=42 deploy of the BGP-layer visibility batch. updateData() read `fullData.bgp` only → first auto-refresh tick saw `undefined.upstreams || []` → flagged every Layer-2 node `withdrawn=true` → both iFog and Terrahost flipped to red WITHDRAWN. Operator hit the bug within minutes of deploy; my Playwright test had captured at t=3s and missed it. Fixed in v=43 (commit `221231c`).

**Mandatory test:** the regression test `visual-audit/tests/status-autorefresh-regression.spec.js` explicitly calls `window.__meshGraph.update(rawApiPayload)` with the actual `/api/mesh-stats` response. Any future updateData refactor that introduces a key-shape mismatch fails this test before it ships. Same pattern: load page → capture state → fetch raw API → call update() → re-capture → assert nothing degraded.

**Don't trust** a page-load screenshot for `updateData()` correctness. The function only runs on auto-refresh, so the first page load doesn't exercise it.

See also: [[feedback-mesh-graph-cache-buster]], [[status-diagram-upstream-render-gaps-20260516]].
