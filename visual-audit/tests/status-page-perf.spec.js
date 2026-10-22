const { test, expect } = require('@playwright/test');
const { STATUS_URL } = require('../helpers/status-page');

test.describe('Status Page -- Performance', () => {
  test('page loads under 10 seconds', async ({ page }) => {
    const start = Date.now();
    await page.goto(STATUS_URL, { waitUntil: 'load', timeout: 30000 });
    expect(Date.now() - start).toBeLessThan(10000);
  });

  test('D3 graph renders under 5 seconds after load', async ({ page }) => {
    await page.goto(STATUS_URL, { waitUntil: 'load', timeout: 30000 });
    const start = Date.now();
    await page.waitForSelector('#mh-graph svg circle', { timeout: 10000 });
    expect(Date.now() - start).toBeLessThan(5000);
  });

  test('total resource count is reasonable', async ({ page }) => {
    await page.goto(STATUS_URL, { waitUntil: 'load', timeout: 30000 });
    await page.waitForTimeout(2000);
    const count = await page.evaluate(() => performance.getEntriesByType('resource').length);
    expect(count).toBeLessThan(50);
  });

  test('no layout shift after initial render', async ({ page }) => {
    await page.goto(STATUS_URL, { waitUntil: 'load', timeout: 30000 });
    await page.waitForSelector('#mh-graph svg circle', { timeout: 10000 }).catch(() => {});
    const firstPos = await page.evaluate(() => {
      const el = document.querySelector('#mh-graph-container, #mh-graph, .post-content');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { top: r.top, left: r.left };
    });
    if (!firstPos) return;
    await page.waitForTimeout(3000);
    const secondPos = await page.evaluate(() => {
      const el = document.querySelector('#mh-graph-container, #mh-graph, .post-content');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { top: r.top, left: r.left };
    });
    if (!secondPos) return;
    expect(Math.abs(firstPos.top - secondPos.top)).toBeLessThan(5);
    expect(Math.abs(firstPos.left - secondPos.left)).toBeLessThan(5);
  });
});
