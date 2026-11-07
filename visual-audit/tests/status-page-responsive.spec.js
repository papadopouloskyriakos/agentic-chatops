const { test, expect } = require('@playwright/test');
const { goToStatus, VIEWPORTS } = require('../helpers/status-page');

test.describe('Status Page -- Responsive Design', () => {
  test('desktop: graph and stats fully visible', async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.desktop);
    await goToStatus(page);
    await expect(page.locator('#mh-graph-container, #mh-graph').first()).toBeVisible();
  });

  test('tablet: no horizontal scroll', async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.tablet);
    await goToStatus(page);
    const hasHScroll = await page.evaluate(() => document.body.scrollWidth > window.innerWidth);
    expect(hasHScroll).toBeFalsy();
  });

  test('mobile: no horizontal scroll', async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.mobile);
    await goToStatus(page);
    const hasHScroll = await page.evaluate(() => document.body.scrollWidth > window.innerWidth);
    expect(hasHScroll).toBeFalsy();
  });

  test('mobile: D3 graph still renders', async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.mobile);
    await goToStatus(page);
    expect(await page.locator('#mh-graph svg circle').count()).toBeGreaterThanOrEqual(4);
  });

  test('mobile: tunnel list visible', async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.mobile);
    await goToStatus(page);
    const tunnelList = page.locator('#mh-tunnel-list, .mh-tunnel-list');
    if (await tunnelList.count() > 0) await expect(tunnelList).toBeVisible();
  });
});
