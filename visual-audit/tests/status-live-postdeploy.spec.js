// Post-deploy audit against the live kyriakos.papadopoulos.tech/status/
// — no injection, no route rewrites. Measures the actual deployed state.
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const URL = 'https://kyriakos.papadopoulos.tech/status/';
const OUT = path.join(__dirname, '..', 'reports', 'status-live-postdeploy');

test.setTimeout(60000);

test('live deployed diagram: 7+2 transits with proper spacing', async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true });

  await page.goto(URL + '?cb=' + Date.now(), { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForFunction(
    () => document.querySelectorAll('#mh-graph svg circle').length > 5,
    { timeout: 30000 }
  ).catch(() => {});
  await page.waitForTimeout(2500);

  await page.locator('#mh-graph-container').first().screenshot({ path: path.join(OUT, 'diagram.png') });
  await page.screenshot({ path: path.join(OUT, 'full-page.png'), fullPage: true });

  const rendered = await page.evaluate(() => {
    const svg = document.querySelector('#mh-graph svg');
    if (!svg) return { error: 'no svg' };
    const nodes = [], seen = new Set();
    svg.querySelectorAll('circle, g').forEach((el) => {
      const d = el.__data__;
      if (!d || typeof d.id === 'undefined' || seen.has(d.id)) return;
      seen.add(d.id);
      nodes.push({ id: d.id, name: d.name, layer: d.layer, x: d.x, y: d.y });
    });
    const links = [], lseen = new Set();
    svg.querySelectorAll('line, path').forEach((el) => {
      const d = el.__data__;
      if (!d || !d.type) return;
      const s = (d.source && (d.source.id || d.source)) || null;
      const t = (d.target && (d.target.id || d.target)) || null;
      if (!s || !t) return;
      const k = `${s}::${t}::${d.type}`;
      if (lseen.has(k)) return;
      lseen.add(k);
      links.push({ source: String(s), target: String(t), type: d.type });
    });
    return { nodes, links, svgWidth: svg.clientWidth, svgHeight: svg.clientHeight };
  });

  const upstreams = rendered.nodes.filter((n) => n.layer === 2);
  const transits = rendered.nodes.filter((n) => n.layer === 3);
  const transitLinks = rendered.links.filter((l) => l.type === 'transit');

  const byUpstream = {};
  transitLinks.forEach((l) => {
    if (!byUpstream[l.source]) byUpstream[l.source] = [];
    byUpstream[l.source].push(l.target);
  });

  const closest = {};
  upstreams.forEach((u) => {
    let best = Infinity;
    transits.forEach((t) => {
      const d = Math.hypot(t.x - u.x, t.y - u.y);
      if (d < best) best = d;
    });
    closest[u.id] = Math.round(best);
  });

  const transitRowY = transits.length ? Math.round(transits.reduce((a, t) => a + t.y, 0) / transits.length) : null;
  const upstreamY = upstreams.length ? Math.round(upstreams[0].y) : null;
  const verticalGap = upstreamY && transitRowY ? upstreamY - transitRowY : null;

  const result = {
    svg_dims: [rendered.svgWidth, rendered.svgHeight],
    upstreams: upstreams.map((n) => ({
      id: n.id, name: n.name, x: Math.round(n.x), y: Math.round(n.y),
    })),
    transit_count: transits.length,
    transit_row_y_avg: transitRowY,
    vertical_gap_row_to_upstream: verticalGap,
    transits_per_upstream: Object.fromEntries(
      Object.entries(byUpstream).map(([u, ts]) => [u, { count: ts.length, ids: ts }])
    ),
    closest_transit_to_upstream_px: closest,
    transits: transits.map((n) => ({
      id: n.id, name: n.name, x: Math.round(n.x), y: Math.round(n.y),
    })),
  };

  fs.writeFileSync(path.join(OUT, 'summary.json'), JSON.stringify(result, null, 2));

  console.log('=== LIVE POST-DEPLOY MEASUREMENTS ===');
  console.log(JSON.stringify(result, null, 2));

  expect(upstreams.length).toBe(2);
  expect(byUpstream['AS34927']?.length).toBe(7);
  expect(byUpstream['AS56655']?.length).toBe(2);
  expect(closest['AS34927']).toBeGreaterThanOrEqual(40);
  expect(closest['AS56655']).toBeGreaterThanOrEqual(40);
});
