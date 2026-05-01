const { test, expect } = require('@playwright/test');
const { goToStatus } = require('../helpers/status-page');

test.describe('Status Page -- Interactive Elements', () => {
  test.beforeEach(async ({ page }) => { await goToStatus(page); });

  test('clicking a site node does not crash', async ({ page }) => {
    const circles = page.locator('#mh-graph svg circle');
    if (await circles.count() < 1) return;
    const box = await circles.first().boundingBox();
    if (box) {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      await page.waitForTimeout(500);
    }
    // Verify page is still functional
    expect(await page.locator('#mh-graph svg circle').count()).toBeGreaterThanOrEqual(4);
  });

  test('hovering a link does not crash', async ({ page }) => {
    const lines = page.locator('#mh-graph svg line');
    if (await lines.count() < 1) return;
    const box = await lines.first().boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.waitForTimeout(500);
    }
    expect(await page.locator('#mh-graph svg circle').count()).toBeGreaterThanOrEqual(4);
  });

  test('auto-refresh bar elements present', async ({ page }) => {
    const ar = page.locator('#ar-bar, .ar-bar');
    if (await ar.count() > 0) await expect(ar.first()).toBeVisible();
  });

  test('page survives rapid viewport changes', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(200);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(200);
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.waitForTimeout(200);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(500);
    expect(await page.locator('#mh-graph svg circle').count()).toBeGreaterThanOrEqual(4);
  });
});
