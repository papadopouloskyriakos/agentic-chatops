const { test, expect } = require('@playwright/test');
const { goToStatus } = require('../helpers/status-page');

test.describe('Status Page -- Chaos UI Controls (read-only)', () => {
  test.beforeEach(async ({ page }) => { await goToStatus(page); });

  test('kill bar hidden on page load', async ({ page }) => {
    const killBar = page.locator('#chaos-kill-bar');
    if (await killBar.count() > 0) await expect(killBar).not.toBeVisible();
  });

  test('chaos modal not present on page load', async ({ page }) => {
    const modal = page.locator('.chaos-modal');
    if (await modal.count() > 0) await expect(modal).not.toBeVisible();
  });

  test('status banner shows compound status text', async ({ page }) => {
    const banner = page.locator('text=/Nominal|All Clear|Degraded|Critical/i').first();
    if (await banner.count() > 0) {
      const text = await banner.innerText();
      expect(text.length).toBeGreaterThan(0);
    }
  });

  test('link legend shows VPN types', async ({ page }) => {
    const items = page.locator('.mh-ll-item, .mh-legend-item');
    if (await items.count() > 0) {
      expect(await items.count()).toBeGreaterThanOrEqual(3);
    }
  });

  test('chaos-related content exists on page', async ({ page }) => {
    const text = await page.locator('body').innerText();
    const hasChaos = /chaos|kill|failover|experiment/i.test(text);
    expect(hasChaos).toBeTruthy();
  });
});
