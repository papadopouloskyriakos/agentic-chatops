const { test } = require('@playwright/test');
const { goToStatus } = require('../helpers/status-page');
const path = require('path');

const SHOT_DIR = path.join(__dirname, '..', 'baselines', 'status-page');

test.describe('Status Page -- Screenshot Baselines', () => {
  test.beforeEach(async ({ page }) => { await goToStatus(page); });

  test('full page screenshot at 1440px', async ({ page }) => {
    await page.screenshot({ path: path.join(SHOT_DIR, 'full-page-1440.png'), fullPage: true });
  });

  test('viewport-only screenshot at 1440px', async ({ page }) => {
    await page.screenshot({ path: path.join(SHOT_DIR, 'viewport-1440.png') });
  });

  test('D3 graph section screenshot', async ({ page }) => {
    const graph = page.locator('#mh-graph-container, .mh-graph-wrap, #mh-graph').first();
    if (await graph.isVisible()) {
      await graph.screenshot({ path: path.join(SHOT_DIR, 'graph-section.png') });
    }
  });

  test('stat cards screenshot', async ({ page }) => {
    const stats = page.locator('.mh-stats-grid, .mh-stats').first();
    if (await stats.isVisible()) {
      await stats.screenshot({ path: path.join(SHOT_DIR, 'stat-cards.png') });
    }
  });

  test('service health screenshot', async ({ page }) => {
    const sh = page.locator('#service-health');
    await sh.waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
    if (await sh.isVisible()) {
      await sh.screenshot({ path: path.join(SHOT_DIR, 'service-health.png') });
    }
  });

  test('mobile full page screenshot', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SHOT_DIR, 'full-page-375.png'), fullPage: true });
  });

  test('tablet full page screenshot', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SHOT_DIR, 'full-page-768.png'), fullPage: true });
  });
});
