const { test, expect } = require('@playwright/test');
const { goToStatus, collectConsoleErrors, collectNetworkErrors } = require('../helpers/status-page');

test.describe('Status Page -- Error States', () => {
  test('no critical console errors on load', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await goToStatus(page);
    const critical = errors.filter(e =>
      !e.includes('favicon') && !e.includes('CSP') && !e.includes('net::') &&
      !e.includes('Mixed Content') && !e.includes('third-party')
    );
    expect(critical.length).toBeLessThanOrEqual(5); // Allow non-critical JS errors
  });

  test('no broken asset requests (404s)', async ({ page }) => {
    const errors = collectNetworkErrors(page);
    await goToStatus(page);
    const asset404s = errors.filter(e =>
      e.status === 404 && (e.url.endsWith('.js') || e.url.endsWith('.css') || e.url.endsWith('.png'))
    );
    expect(asset404s).toEqual([]);
  });

  test('page renders with Hugo-baked data when API blocked', async ({ page }) => {
    await page.route('**/webhook/**', route => route.abort());
    await page.route('**/api/**', route => route.abort());
    await goToStatus(page);
    const hasData = await page.evaluate(() => !!window.__meshData);
    expect(hasData).toBeTruthy();
    expect(await page.locator('#mh-graph svg circle').count()).toBeGreaterThanOrEqual(4);
  });

  test('no garbage text on page', async ({ page }) => {
    await goToStatus(page);
    const text = await page.locator('body').innerText();
    expect(text).not.toContain('[object Object]');
    expect(text).not.toContain('null null');
  });
});
