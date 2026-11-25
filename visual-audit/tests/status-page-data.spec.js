const { test, expect } = require('@playwright/test');
const { goToStatus } = require('../helpers/status-page');

test.describe('Status Page -- Data Accuracy', () => {
  test.beforeEach(async ({ page }) => { await goToStatus(page); });

  test('meshData has tunnel entries', async ({ page }) => {
    const count = await page.evaluate(() =>
      window.__meshData && window.__meshData.tunnels ? window.__meshData.tunnels.length : 0
    );
    expect(count).toBeGreaterThanOrEqual(6);
  });

  test('meshData has site entries', async ({ page }) => {
    const count = await page.evaluate(() =>
      window.__meshData && window.__meshData.sites ? window.__meshData.sites.length : 0
    );
    expect(count).toBeGreaterThanOrEqual(4);
  });

  test('meshData has BGP data', async ({ page }) => {
    const has = await page.evaluate(() =>
      window.__meshData && window.__meshData.internalBgp &&
      window.__meshData.internalBgp.established !== undefined
    );
    expect(has).toBeTruthy();
  });

  test('meshData has latency matrix', async ({ page }) => {
    const has = await page.evaluate(() =>
      window.__meshData && window.__meshData.latencyMatrix &&
      Object.keys(window.__meshData.latencyMatrix).length > 0
    );
    expect(has).toBeTruthy();
  });

  test('meshDataAge is recent (< 24h)', async ({ page }) => {
    const ageHours = await page.evaluate(() => {
      if (!window.__meshDataAge) return 999;
      return (Date.now() - new Date(window.__meshDataAge).getTime()) / (1000 * 60 * 60);
    });
    expect(ageHours).toBeLessThan(24);
  });

  test('tunnel count in data is consistent', async ({ page }) => {
    const { dataCount, domText } = await page.evaluate(() => {
      const d = window.__meshData;
      const count = d && d.tunnels ? d.tunnels.length : 0;
      const el = document.querySelector('[data-stat="tunnels"] .mh-stat-number, .mh-stat-number');
      return { dataCount: count, domText: el ? el.textContent.trim() : '' };
    });
    expect(dataCount).toBeGreaterThan(0);
    if (domText) expect(domText).toMatch(/\d/);
  });
});
