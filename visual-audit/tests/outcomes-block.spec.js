const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

/**
 * Pre-deploy verification for the Outcomes block (auto-resolve % sparkline +
 * closed-loop median/p95) inserted after the Token Usage chart in the
 * agentic-stats shortcode.
 *
 * Points at a local Hugo dev server (BASE_URL env var, default 127.0.0.1:1318)
 * so the spec runs against the shortcode + JSON in this branch, before pushing
 * to GitLab CI / kyriakos.papadopoulos.tech.
 */
const BASE = process.env.BASE_URL || 'http://127.0.0.1:1318';
const PAGE_URL = BASE + '/projects/agentic-chatops/';
const OUT_DIR = path.resolve(__dirname, '../reports');

test.describe('Outcomes block — pre-deploy verification', () => {
  let consoleErrors = [];
  let state = null;

  test.beforeAll(async ({ browser }) => {
    if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await ctx.newPage();
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', e => consoleErrors.push('pageerror:' + e.message));

    await page.goto(PAGE_URL + '?_=' + Date.now(), { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1500);

    // Full-section screenshot of the Usage area (token-usage widget + new outcomes block)
    const section = await page.locator('.agentic-stats').first();
    await section.screenshot({ path: path.join(OUT_DIR, 'outcomes-after.png') });

    state = await page.evaluate(() => {
      const txt = el => el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '';
      const sparkSvg = document.querySelector('.as-outcomes .as-spark');
      const polyline = document.querySelector('.as-outcomes .as-spark-line');
      const dot = document.querySelector('.as-outcomes .as-spark-dot');
      const outcomes = Array.from(document.querySelectorAll('.as-outcomes .as-outcome'));
      const dataScript = document.getElementById('agentic-stats-data');
      let parsed = null;
      try { parsed = JSON.parse(dataScript.textContent); } catch (e) {}

      return {
        blockExists: !!document.querySelector('.as-outcomes'),
        header: txt(document.querySelector('.as-outcomes-header')),
        outcomeCount: outcomes.length,
        labels: outcomes.map(o => txt(o.querySelector('.as-outcome-label'))),
        values: outcomes.map(o => txt(o.querySelector('.as-outcome-val'))),
        subs: outcomes.map(o => txt(o.querySelector('.as-outcome-sub'))),
        feet: outcomes.map(o => txt(o.querySelector('.as-outcome-foot'))),
        deltaClasses: outcomes.map(o => {
          const d = o.querySelector('.as-outcome-delta');
          return d ? d.className : null;
        }),
        sparkExists: !!sparkSvg,
        sparkAria: sparkSvg ? sparkSvg.getAttribute('aria-label') : null,
        sparkCount: document.querySelectorAll('.as-outcomes .as-spark').length,
        // Tier-2 autonomy tile (index 1) gets a sparkline at parity with Auto-resolve.
        tier2HasSpark: (() => {
          const t = document.querySelectorAll('.as-outcomes .as-outcome')[1];
          return t ? !!t.querySelector('.as-spark') : false;
        })(),
        polylinePts: polyline ? polyline.getAttribute('points') : null,
        dotPos: dot ? { cx: dot.getAttribute('cx'), cy: dot.getAttribute('cy') } : null,
        openBadge: txt(document.querySelector('.as-outcome-open')),
        p95Val: txt(document.querySelector('.as-outcome-p95')),
        // Position: outcomes block must come AFTER the chart, BEFORE the model breakdown.
        chartBeforeOutcomes: (() => {
          const chart = document.querySelector('.as-chart');
          const outc = document.querySelector('.as-outcomes');
          if (!chart || !outc) return false;
          return chart.compareDocumentPosition(outc) & Node.DOCUMENT_POSITION_FOLLOWING;
        })(),
        modelsAfterOutcomes: (() => {
          const outc = document.querySelector('.as-outcomes');
          const models = document.querySelector('.as-models');
          if (!models || !outc) return false;
          return outc.compareDocumentPosition(models) & Node.DOCUMENT_POSITION_FOLLOWING;
        })(),
        parsedData: parsed && parsed.outcomes ? parsed.outcomes : null,
      };
    });

    fs.writeFileSync(path.join(OUT_DIR, 'outcomes-state.json'), JSON.stringify(state, null, 2));
    await ctx.close();
  });

  test('1. Outcomes block renders after the Token Usage chart', () => {
    expect(state.blockExists, 'as-outcomes container not found').toBeTruthy();
    expect(state.header).toBe('Outcomes');
    expect(state.outcomeCount).toBe(3);
    expect(state.chartBeforeOutcomes).toBeTruthy();
    expect(state.modelsAfterOutcomes).toBeTruthy();
  });

  test('2. Three tiles with the right labels', () => {
    expect(state.labels).toEqual(['Auto-resolve', 'Tier-2 autonomy', 'Closed-loop time']);
    expect(state.subs[0]).toMatch(/rolling \d+d/);   // Auto-resolve
    expect(state.subs[1]).toMatch(/rolling \d+d/);   // Tier-2 autonomy
    expect(state.subs[2]).toMatch(/last \d+d/);      // Closed-loop time
  });

  test('3. Auto-resolve + Tier-2 tiles show a percentage value', () => {
    expect(state.values[0]).toMatch(/^\d+%$/);
    expect(state.values[1]).toMatch(/^\d+%$|^—$/);   // Tier-2: % or empty-state em dash
  });

  test('4. Closed-loop tile shows median (≈0s or duration) + p95 duration', () => {
    // Median is legitimately ≈0s when instant Tier-1 closes dominate the count.
    expect(state.values[2]).toMatch(/^≈0s$|^\d+m( \d+s)?$|^\d+s$|^\d+h( \d+m)?$/);
    expect(state.p95Val).toMatch(/^\d+m( \d+s)?$|^\d+s$|^\d+h( \d+m)?$/);
  });

  test('5. Auto-resolve sparkline renders as inline SVG with polyline + tip dot', () => {
    expect(state.sparkExists).toBeTruthy();
    expect(state.sparkAria).toMatch(/Auto-resolve rolling 7d/);
    expect(state.polylinePts).toBeTruthy();
    expect(state.polylinePts.split(' ').length).toBeGreaterThanOrEqual(2);
    expect(state.dotPos).toBeTruthy();
  });

  test('5b. Tier-2 autonomy tile has a sparkline at parity with Auto-resolve', () => {
    expect(state.tier2HasSpark).toBeTruthy();
    // Both rate tiles carry a sparkline; the empty-state SVG still has the class,
    // so a present gate.daily series yields two .as-spark nodes minimum.
    expect(state.sparkCount).toBeGreaterThanOrEqual(2);
  });

  test('6. Delta lines carry correct semantic tone classes', () => {
    // auto-resolve: better when delta positive → bad tone if negative
    // closed-loop: better when delta negative → bad tone if positive
    state.deltaClasses.forEach((c, i) => {
      if (!c) return;
      expect(c, `tile #${i} class`).toMatch(/as-delta-(good|bad|flat)/);
    });
  });

  test('7. "N open" badge shows only when count > 0', () => {
    const nOpen = state.parsedData && state.parsedData.closed_loop && state.parsedData.closed_loop.n_open;
    if (nOpen && nOpen > 0) {
      expect(state.openBadge).toMatch(new RegExp('^' + nOpen.toLocaleString() + ' open$'));
    } else {
      expect(state.openBadge).toBe('');
    }
  });

  test('8. Foot text mentions the comparison window / context in human language', () => {
    // Auto-resolve + Closed-loop feet carry a prior-window comparison; the Tier-2
    // gate foot carries a bands summary ("N auto / N human of N") or empty state.
    state.feet.forEach((f, i) => {
      expect(f, `tile #${i} foot`).toMatch(
        /prior 7d|no prior window|no events yet|no closed loops yet|auto \/ \d+ human|no sessions yet/);
    });
  });

  test('9. No new JS console errors introduced', () => {
    const novel = consoleErrors.filter(e =>
      !e.includes('analytics.cubeos.app') &&
      !e.includes('Failed to load resource') &&
      !e.includes('favicon')
    );
    expect(novel, 'novel console errors: ' + JSON.stringify(novel)).toHaveLength(0);
  });

  test('10. Outcomes JSON schema present in inlined data', () => {
    expect(state.parsedData).toBeTruthy();
    expect(state.parsedData.window_days).toBe(7);
    expect(state.parsedData.auto_resolve).toBeTruthy();
    expect(state.parsedData.closed_loop).toBeTruthy();
    expect(Array.isArray(state.parsedData.auto_resolve.daily)).toBeTruthy();
    expect(state.parsedData.auto_resolve.daily.length).toBe(56);
    // Tier-2 gate + its daily sparkline series (mirrors auto_resolve.daily length).
    expect(state.parsedData.gate).toBeTruthy();
    expect(Array.isArray(state.parsedData.gate.daily)).toBeTruthy();
    expect(state.parsedData.gate.daily.length).toBe(56);
  });
});
