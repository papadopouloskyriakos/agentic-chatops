---
name: feedback-mesh-graph-cache-buster
description: "When changing the behaviour of `static/js/mesh-graph.js` (kyriakos repo), you MUST also bump the cache-buster suffix in `layouts/shortcodes/mesh-health.html` (`?v=N` → `?v=N+1`). Browsers cache by URL — same URL with new content does not invalidate the cache, so users see the old behaviour even after Hugo redeploys."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2a7d5591-5f5e-4fd2-8fe8-5101e94f5112
---

# mesh-graph.js cache-buster must move when JS behaviour changes

**Rule:** Any behavioural change to
`websites/papadopoulos.tech/kyriakos/static/js/mesh-graph.js` must be paired
with a bump of the cache-buster suffix in
`websites/papadopoulos.tech/kyriakos/layouts/shortcodes/mesh-health.html`:

```html
<script src="/js/mesh-graph.js?v=N"></script>   →   ?v=N+1
```

**Why:** Browsers cache `/js/mesh-graph.js?v=N` by full URL. After a Hugo
rebuild + dmz redeploy, the file at that URL has new content, but cached
clients keep using the old response until the URL changes. Without bumping
`?v=`:

- Incognito / first-visit users see the new behaviour
- Returning operators see the OLD behaviour and conclude "nothing changed"

This bit us 2026-05-16: after the first layout patch deployed, the operator
loaded the page in their normal browser, saw no change, and reported
"nothing changed". The deploy was actually fine — the deployed JS had the
patch — but their browser had `?v=39` cached. Bumping to `?v=40` made the
patch visible.

**How to apply:** in the same commit as the mesh-graph.js change, edit
mesh-health.html and bump the version number. Don't rely on operators to
hard-refresh.

**Doesn't apply to:** pure CSS changes, Hugo template changes, data file
changes — only when JS behaviour at the `/js/mesh-graph.js` URL changes.

Same rule applies to other versioned JS includes in the same template:
`chaos.js`, `service-health.js`, `auto-refresh.js`. Check the script tag in
`mesh-health.html` for the file you're editing.

See also: [[status-diagram-upstream-render-gaps-20260516]].
