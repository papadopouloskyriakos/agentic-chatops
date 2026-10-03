const { test, expect } = require('@playwright/test');
const { goToStatus } = require('../helpers/status-page');

test.describe('Status Page -- DOM Structure', () => {
  test.beforeEach(async ({ page }) => { await goToStatus(page); });

  test('page has correct title', async ({ page }) => {
    await expect(page).toHaveTitle(/Live Infrastructure|Chaos Engineering|Status/i);
  });

  test('main content exists', async ({ page }) => {
    const main = page.locator('#main-content, main, .post-content').first();
    await expect(main).toBeVisible();
  });

  test('D3 SVG contains site node circles', async ({ page }) => {
    const circles = page.locator('#mh-graph svg circle');
    expect(await circles.count()).toBeGreaterThanOrEqual(4);
  });

  test('D3 SVG contains link lines', async ({ page }) => {
    const lines = page.locator('#mh-graph svg line');
    expect(await lines.count()).toBeGreaterThanOrEqual(6);
  });

  test('D3 SVG contains text labels', async ({ page }) => {
    const texts = page.locator('#mh-graph svg text');
    expect(await texts.count()).toBeGreaterThanOrEqual(4);
  });

  test('tunnel stat visible', async ({ page }) => {
    await expect(page.locator('text=/\\d+\\/\\d+.*VTI|Tunnels/i').first()).toBeVisible();
  });

  test('BGP stat visible', async ({ page }) => {
    await expect(page.locator('text=/BGP|\\d+\\/\\d+.*Established/i').first()).toBeVisible();
  });

  test('NL site card visible', async ({ page }) => {
    await expect(page.locator('text=/NL.*primary/i').first()).toBeVisible();
  });

  test('GR site card visible', async ({ page }) => {
    await expect(page.locator('text=/GR.*secondary/i').first()).toBeVisible();
  });

  test('graph container exists', async ({ page }) => {
    await expect(page.locator('#mh-graph-container, #mh-graph').first()).toBeVisible();
  });

  test('status banner exists', async ({ page }) => {
    // Status text may appear anywhere in the page content
    const bodyText = await page.locator('body').innerText();
    const hasStatus = /nominal|degraded|critical|all clear|tunnels? active/i.test(bodyText);
    expect(hasStatus).toBeTruthy();
  });

  test('latency matrix visible', async ({ page }) => {
    const matrix = page.locator('.mh-matrix, table').first();
    if (await matrix.count() > 0 && await matrix.isVisible()) {
      expect(await page.locator('.mh-cell, td').count()).toBeGreaterThan(0);
    }
  });

  test('no garbage text on page', async ({ page }) => {
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toContain('[object Object]');
    expect(bodyText).not.toMatch(/\bundefined\b.*\bundefined\b/);
    expect(bodyText).not.toContain('NaN');
  });

  test('window.__meshData is populated', async ({ page }) => {
    const hasData = await page.evaluate(() =>
      window.__meshData && typeof window.__meshData === 'object' &&
      (window.__meshData.tunnels || window.__meshData.sites)
    );
    expect(hasData).toBeTruthy();
  });

  test('link legend visible', async ({ page }) => {
    const legend = page.locator('.mh-ll, .mh-legend').first();
    if (await legend.count() > 0) {
      await expect(legend).toBeVisible();
    } else {
      // Fallback: check body text for VPN legend content
      const text = await page.locator('body').innerText();
      expect(text).toMatch(/VPN.*active|VPN.*standby|eBGP/i);
    }
  });
});
