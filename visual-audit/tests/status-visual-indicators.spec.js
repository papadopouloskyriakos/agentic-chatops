// Offline test of the visual-indicators batch (items 1-4):
//   - Colour upstream bubbles by RIPE power
//   - WITHDRAWN ghost when a baseline upstream is missing
//   - Visibility gauge text in the top-right of the SVG
//   - updateData refreshes BGP layer on auto-refresh tick
//
// Tests two scenarios via response-rewriting:
//   A) Healthy: both upstreams present, power normal → upstream nodes blue
//   B) Withdrawn: synthetic data with Terrahost (AS56655) removed →
//      AS56655 ghost rendered red, upstream link red
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const URL = 'https://kyriakos.papadopoulos.tech/status/';
const OUT = path.join(__dirname, '..', 'reports', 'status-visual-indicators');
const MESH_GRAPH_PATH = path.join(
  __dirname, '..', '..', '..', '..',
  'websites', 'papadopoulos.tech', 'kyriakos', 'static', 'js', 'mesh-graph.js'
);

test.setTimeout(90000);

async function captureScenario(page, mutator, label, OUT) {
  const localMeshGraphSrc = fs.readFileSync(MESH_GRAPH_PATH, 'utf8');

  const freshLive = await page.request.get('https://kyriakos.papadopoulos.tech/api/mesh-stats', {
    timeout: 30000,
    headers: { 'Cache-Control': 'no-cache' },
  });
  const live = await freshLive.json();
  const freshShape = {
    sites: live.sites,
    tunnels: live.tunnels,
    latencyMatrix: live.latency_matrix,
    bgp: live.public_bgp,
    routeReflectors: live.route_reflectors,
    k8sClusters: live.k8s_clusters,
    dmzNodes: live.dmz_nodes,
    internalBgp: live.bgp,
    bfd: live.bfd,
    clustermesh: live.clustermesh,
  };
  mutator(freshShape);

  await page.addInitScript((data) => {
    Object.defineProperty(window, '__meshData', {
      value: data,
      writable: false,
      configurable: false,
      enumerable: true,
    });
  }, freshShape);

  await page.route(/\/js\/mesh-graph\.js/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: localMeshGraphSrc,
    });
  });

  await page.goto(URL + '?cb=' + Date.now(), { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForFunction(
    () => document.querySelectorAll('#mh-graph svg circle').length > 5,
    { timeout: 30000 }
  ).catch(() => {});
  await page.waitForTimeout(2000);

  await page.locator('#mh-graph-container').first().screenshot({ path: path.join(OUT, `diagram-${label}.png`) });

  const result = await page.evaluate(() => {
    const svg = document.querySelector('#mh-graph svg');
    if (!svg) return { error: 'no svg' };
    const upstreams = [];
    svg.querySelectorAll('circle').forEach((c) => {
      const d = c.__data__;
      if (!d || d.layer !== 2) return;
      const stroke = c.getAttribute('stroke');
      upstreams.push({
        id: d.id, name: d.name, asn: d.asn,
        power: d.power, withdrawn: !!d.withdrawn,
        stroke: stroke,
      });
    });
    const visGauge = svg.querySelector('#mh-vis-gauge');
    const upLinks = [];
    svg.querySelectorAll('line, path').forEach((el) => {
      const d = el.__data__;
      if (!d || d.type !== 'upstream') return;
      upLinks.push({
        source: (d.source && (d.source.id || d.source)),
        target: (d.target && (d.target.id || d.target)),
        withdrawn: !!d.withdrawn,
        stroke: el.getAttribute('stroke'),
      });
    });
    return {
      upstreams,
      upstream_links: upLinks,
      visibility_text: visGauge ? visGauge.textContent : null,
      visibility_fill: visGauge ? visGauge.getAttribute('fill') : null,
    };
  });

  return result;
}

test('visual indicators: healthy scenario', async ({ browser }) => {
  fs.mkdirSync(OUT, { recursive: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const result = await captureScenario(page, () => {}, 'healthy', OUT);
  fs.writeFileSync(path.join(OUT, 'healthy.json'), JSON.stringify(result, null, 2));
  console.log('=== HEALTHY SCENARIO ===');
  console.log(JSON.stringify(result, null, 2));

  expect(result.upstreams.length).toBeGreaterThanOrEqual(2);
  const iFog = result.upstreams.find((u) => u.asn === 34927);
  const terra = result.upstreams.find((u) => u.asn === 56655);
  expect(iFog).toBeTruthy();
  expect(terra).toBeTruthy();
  expect(iFog.withdrawn).toBe(false);
  expect(terra.withdrawn).toBe(false);
  // Two-state colouring: both upstreams blue when healthy.
  expect(iFog.stroke).toBe('#3b82f6');
  expect(terra.stroke).toBe('#3b82f6');
  // Visibility gauge present + parseable
  expect(result.visibility_text).toMatch(/v6 visibility: \d+%/);

  await ctx.close();
});

test('visual indicators: withdrawn-terrahost scenario', async ({ browser }) => {
  fs.mkdirSync(OUT, { recursive: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const result = await captureScenario(
    page,
    (shape) => {
      // Synthetic withdrawal: drop Terrahost from upstreams + top_paths
      shape.bgp.upstreams = (shape.bgp.upstreams || []).filter((u) => u.asn !== 56655);
      shape.bgp.top_paths = (shape.bgp.top_paths || []).filter((p) => {
        const hops = (p.path || '').split(' ');
        return !(hops.includes('56655'));
      });
      shape.bgp.visibility_v6_pct = 73;  // drop visibility to test red gauge
    },
    'withdrawn-terrahost',
    OUT
  );
  fs.writeFileSync(path.join(OUT, 'withdrawn-terrahost.json'), JSON.stringify(result, null, 2));
  console.log('=== WITHDRAWN TERRAHOST SCENARIO ===');
  console.log(JSON.stringify(result, null, 2));

  const terra = result.upstreams.find((u) => u.asn === 56655);
  expect(terra).toBeTruthy();           // ghost present
  expect(terra.withdrawn).toBe(true);
  expect(terra.stroke).toBe('#ef4444'); // red
  // Visibility gauge dropped below 80 → red
  expect(result.visibility_text).toContain('73%');
  expect(result.visibility_fill).toBe('#ef4444');
  // Upstream link to terrahost should also be red
  const terraLink = result.upstream_links.find((l) => l.target === 'AS56655');
  expect(terraLink).toBeTruthy();
  expect(terraLink.withdrawn).toBe(true);

  await ctx.close();
});
