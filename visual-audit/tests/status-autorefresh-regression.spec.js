// Regression test: the v=42 deploy had a key-shape bug where
// updateData() read fullData.bgp but auto-refresh.js passes the raw
// /api/mesh-stats payload, which uses public_bgp instead. This caused
// every Layer-2 upstream to flip withdrawn=true on the first 30s auto-
// refresh tick after page load.
//
// This test forces an auto-refresh tick by calling window.__meshGraph
// .update() with the actual API-shape payload, then asserts that the
// upstream nodes stay healthy (NOT withdrawn).
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const URL = 'https://kyriakos.papadopoulos.tech/status/';
const OUT = path.join(__dirname, '..', 'reports', 'status-autorefresh-regression');
const MESH_GRAPH_PATH = path.join(
  __dirname, '..', '..', '..', '..',
  'websites', 'papadopoulos.tech', 'kyriakos', 'static', 'js', 'mesh-graph.js'
);

test.setTimeout(90000);

test('auto-refresh does NOT flip upstreams to withdrawn', async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true });

  // Serve the local (patched) mesh-graph.js so this test exercises the
  // post-fix code even before deploy.
  const localMeshGraphSrc = fs.readFileSync(MESH_GRAPH_PATH, 'utf8');
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

  // Capture initial state — both upstreams should be blue
  const before = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('#mh-graph svg circle').forEach((c) => {
      const d = c.__data__;
      if (!d || d.layer !== 2) return;
      out.push({ id: d.id, withdrawn: !!d.withdrawn, stroke: c.getAttribute('stroke') });
    });
    return out;
  });
  console.log('BEFORE auto-refresh:', JSON.stringify(before));

  // Manually call window.__meshGraph.update with the SAME shape that
  // auto-refresh.js passes (raw /api/mesh-stats response).
  const refreshOk = await page.evaluate(async () => {
    const r = await fetch('/api/mesh-stats', { cache: 'no-store' });
    const fullData = await r.json();
    if (!window.__meshGraph || !window.__meshGraph.update) {
      return { ok: false, reason: '__meshGraph.update not exposed' };
    }
    window.__meshGraph.update(fullData);
    return { ok: true, top_level_keys: Object.keys(fullData).sort() };
  });
  console.log('refresh result:', JSON.stringify(refreshOk));

  await page.waitForTimeout(1500);

  // Capture POST-refresh state — upstreams MUST stay blue/healthy
  const after = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('#mh-graph svg circle').forEach((c) => {
      const d = c.__data__;
      if (!d || d.layer !== 2) return;
      out.push({ id: d.id, asn: d.asn, withdrawn: !!d.withdrawn, stroke: c.getAttribute('stroke') });
    });
    return out;
  });
  console.log('AFTER auto-refresh:', JSON.stringify(after));

  await page.locator('#mh-graph-container').first().screenshot({ path: path.join(OUT, 'diagram-after-refresh.png') });
  fs.writeFileSync(path.join(OUT, 'summary.json'), JSON.stringify({ before, refreshOk, after }, null, 2));

  expect(refreshOk.ok).toBe(true);
  expect(after.length).toBe(2);
  after.forEach((u) => {
    expect(u.withdrawn).toBe(false);
    expect(u.stroke).toBe('#3b82f6');
  });
});
