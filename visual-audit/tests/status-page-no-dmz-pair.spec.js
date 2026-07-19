const { test, expect } = require('@playwright/test');
const { goToStatus } = require('../helpers/status-page');
const path = require('path');
const fs = require('fs');

const SHOT_DIR = path.join(__dirname, '..', 'screenshots', 'no-dmz-audit');
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe('NO-DMZ pair audit (post 2026-05-05 onboarding)', () => {
  test.beforeEach(async ({ page }) => {
    await goToStatus(page);
    // give the D3 sim more time to settle since we added 2 new nodes
    await page.waitForTimeout(3500);
  });

  test('extract rendered graph state', async ({ page }) => {
    const apiPayload = await page.evaluate(async () => {
      const res = await fetch('/api/mesh-stats', { cache: 'no-store' });
      return res.ok ? await res.json() : { error: res.status };
    });
    fs.writeFileSync(
      path.join(SHOT_DIR, 'live-mesh-stats.json'),
      JSON.stringify(apiPayload, null, 2)
    );

    const graphState = await page.evaluate(() => {
      const svg = document.querySelector('#mh-graph svg');
      if (!svg) return { error: 'no svg' };
      const circles = Array.from(svg.querySelectorAll('circle'))
        .map(c => ({
          cx: parseFloat(c.getAttribute('cx')) || 0,
          cy: parseFloat(c.getAttribute('cy')) || 0,
          r: parseFloat(c.getAttribute('r')) || 0,
          fill: c.getAttribute('fill') || c.style.fill || '',
        }));
      const labels = Array.from(svg.querySelectorAll('text'))
        .map(t => ({
          text: (t.textContent || '').trim(),
          x: parseFloat(t.getAttribute('x')) || 0,
          y: parseFloat(t.getAttribute('y')) || 0,
        }))
        .filter(l => l.text.length > 0);
      const linkCount = svg.querySelectorAll('line, path.mh-link, .link').length;
      return { circleCount: circles.length, labels, linkCount };
    });
    fs.writeFileSync(
      path.join(SHOT_DIR, 'graph-state.json'),
      JSON.stringify(graphState, null, 2)
    );

    console.log('=== API dmz_nodes ===');
    if (apiPayload.dmz_nodes) {
      apiPayload.dmz_nodes.forEach(n => console.log(`  ${n.id} site=${n.site} host=${n.host} containers=${n.containers_up}/${n.containers_total}`));
    }
    console.log('=== rendered text labels (sorted) ===');
    [...graphState.labels].sort((a,b) => a.text.localeCompare(b.text)).forEach(l => console.log(`  "${l.text}" @ (${l.x|0},${l.y|0})`));

    expect(apiPayload.dmz_nodes).toBeDefined();
    const ids = apiPayload.dmz_nodes.map(n => n.id);
    expect(ids).toContain('NO-DMZ01');
    expect(ids).toContain('NO-DMZ02');
  });

  test('screenshot graph at 1440x900', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(SHOT_DIR, 'full-page-1440.png'), fullPage: true });
    const graph = page.locator('#mh-graph-container, .mh-graph-wrap, #mh-graph').first();
    if (await graph.isVisible()) {
      await graph.screenshot({ path: path.join(SHOT_DIR, 'graph-1440.png') });
    }
  });

  test('screenshot at 1920x1080 (more graph room)', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: path.join(SHOT_DIR, 'full-page-1920.png'), fullPage: true });
    const graph = page.locator('#mh-graph-container, .mh-graph-wrap, #mh-graph').first();
    if (await graph.isVisible()) {
      await graph.screenshot({ path: path.join(SHOT_DIR, 'graph-1920.png') });
    }
  });

  test('screenshot site cards', async ({ page }) => {
    const stats = page.locator('.mh-sites, .mh-stats-grid').first();
    if (await stats.isVisible()) {
      await stats.screenshot({ path: path.join(SHOT_DIR, 'site-cards.png') });
    }
  });

  test('chaos page renders NO-DMZ in selector', async ({ page }) => {
    // chaos page is reachable from status page via "Run a chaos test" link
    await page.goto('https://kyriakos.papadopoulos.tech/chaos/', { waitUntil: 'load', timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(SHOT_DIR, 'chaos-page-1440.png'), fullPage: true });

    const dmzOptions = await page.evaluate(() => {
      const selects = document.querySelectorAll('select.chaos-dmz-selector, select[id*="dmz"], select[name*="dmz"]');
      const out = [];
      selects.forEach(s => {
        const opts = Array.from(s.options).map(o => o.text + '=' + o.value);
        out.push({ id: s.id, name: s.name, options: opts });
      });
      // also any elements that mention dmz hosts
      const bodyText = document.body.innerText || '';
      const hits = bodyText.match(/(notrf01dmz0[12]|NO[- ]?DMZ[- ]?[12]?|nl-dmz01|gr-dmz01)/g) || [];
      return { selects: out, bodyHits: [...new Set(hits)] };
    });
    fs.writeFileSync(path.join(SHOT_DIR, 'chaos-page-dmz.json'), JSON.stringify(dmzOptions, null, 2));
    console.log('chaos page DMZ-related text hits:', dmzOptions.bodyHits);
    console.log('chaos page DMZ selectors:', JSON.stringify(dmzOptions.selects, null, 2));
  });
});
