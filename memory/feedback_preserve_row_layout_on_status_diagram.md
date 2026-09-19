---
name: feedback-preserve-row-layout-on-status-diagram
description: "On the kyriakos status-page network diagram, the operator's strong preference is to preserve the single-horizontal-transit-row layout above the upstream bubbles. Do NOT invent fan / radial / per-upstream-arc layouts even when more transits need to fit. Adjust constants (row y, spacing, count cap) within the existing single-row layout instead."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2a7d5591-5f5e-4fd2-8fe8-5101e94f5112
---

# Preserve the existing single-row transit layout on the status diagram

**Rule:** When the status-page network diagram needs more transit bubbles
than fit, the fix is **always** to tune the existing layout (row y position,
horizontal spacing, count cap) — never to introduce a new layout pattern
(fan, arc, per-upstream cluster, multi-row stack).

**Why:** Operator preference, confirmed by direct feedback. 2026-05-16:
faced with 9 transits in a row that was crowding the upstream bubbles, I
rewrote the layout into a per-upstream angular fan (`37462f3`). When the
operator saw it in an incognito window they reacted "holy shit ... complete
disaster ... undo it immediately". The much smaller fix — bumping the row's
y constant from `cy - 0.82 * baseR` to `cy - 1.0 * baseR` — preserved the
existing visual style and was accepted.

**How to apply:** before touching mesh-graph.js layout code:

1. Read `vNodes.forEach` at the top of the file. Note that upstreams are
   pinned at fixed `(fx, fy)` near their sites, transits are pinned in a
   single horizontal row above.
2. Identify the smallest constant you can change to fix the geometric
   problem (row y, row spacing, max-per-upstream, count threshold).
3. Verify the change with a Playwright screenshot + measurement test
   BEFORE committing. Show the operator the screenshot if there's any
   chance they'll dislike the result.
4. If the smallest single-constant change cannot fix it, list 2-3 minimal
   alternatives and ask the operator which to pick — do not unilaterally
   redesign.

**The original layout invariants to preserve:**

- Upstreams at `(site.x ± 70, site.y - 70)` — iFog left of NO, Terrahost
  right of CH, both at y ≈ 123 in the 580 h canvas.
- Transits in a single horizontal row at a single y, centred on `cx`,
  spaced `min(60, W * 0.65 / count)` px apart.
- 60 px transit-to-transit spacing is the operator-accepted aesthetic.

**Don't reach for:** radial / fan / per-upstream clustering / multi-row /
spirals / staircase. Even if they would fit more bubbles "more elegantly".

See also: [[status-diagram-upstream-render-gaps-20260516]],
[[feedback-mesh-graph-cache-buster]].
