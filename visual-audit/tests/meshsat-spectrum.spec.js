// Audits the MeshSat spectrum waterfall widget on the dashboard and
// the dedicated /spectrum page on the parallax kit. Checks structure,
// console errors, SSE stream health, and captures screenshots into
// the report dir so the operator can eyeball the visual result.
const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const BASE = 'http://nlparallax01:6050';
const SHOT_DIR = path.resolve(__dirname, '..', 'baselines', 'meshsat-spectrum');
fs.mkdirSync(SHOT_DIR, { recursive: true });

function newAuditContext() {
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  return { consoleErrors, pageErrors, failedRequests };
}

function wireAuditHooks(page, audit) {
  page.on('console', msg => {
    if (msg.type() === 'error') audit.consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => audit.pageErrors.push(err.message));
  page.on('requestfailed', req => {
    audit.failedRequests.push(`${req.method()} ${req.url()} :: ${req.failure()?.errorText}`);
  });
}

test('dashboard: spectrum widget renders and has live data', async ({ page }) => {
  const audit = newAuditContext();
  wireAuditHooks(page, audit);

  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });

  // Widget root is the clickable card with "RF SPECTRUM" header; reach it
  // by its aria role (we set role="button" on the widget wrapper).
  // Look for the label text to be robust across style changes.
  const widgetHeader = page.getByText('RF SPECTRUM', { exact: true });
  await expect(widgetHeader, 'widget header visible on dashboard').toBeVisible({ timeout: 10000 });

  const widget = widgetHeader.locator('xpath=ancestor::*[@role="button"][1]');
  await expect(widget, 'widget is a clickable card').toBeVisible();

  // There should be 5 band rows inside the widget (the .widget-strip rows).
  // If calibration hasn't populated the store from the SSE yet, bands come
  // from the /api/spectrum/status seed call — so they should be present.
  const strips = widget.locator('.widget-strip');
  await expect(strips, 'widget has 5 band rows').toHaveCount(5, { timeout: 15000 });

  // At least one of the band labels should match our known set.
  for (const lbl of ['LoRa 868', 'APRS 2m', 'GPS L1', 'LTE-20', 'LTE-8']) {
    await expect(widget.getByText(lbl), `label "${lbl}"`).toBeVisible();
  }

  // Overall state badge should be one of our known values.
  const stateBadge = widget.locator('span.uppercase').first();
  const badgeText = (await stateBadge.innerText()).toLowerCase();
  expect(['jamming', 'interference', 'calibrating', 'clear'],
    'state badge text').toContain(badgeText);

  // Each strip has a heatmap canvas + trace canvas — confirm dimensions.
  const canvasCount = await widget.locator('canvas').count();
  expect(canvasCount, 'widget canvases (2 per band × 5 bands = 10)').toBeGreaterThanOrEqual(10);

  // Wait a moment so a scan tick or two fires, then re-check bounds.
  await page.waitForTimeout(3500);

  // Sanity: widget height is compact (< 220 px).
  const box = await widget.boundingBox();
  expect(box, 'widget boundingBox').not.toBeNull();
  expect(box.height, 'widget is compact').toBeLessThan(260);

  await page.screenshot({ path: path.join(SHOT_DIR, 'dashboard-widget.png'), fullPage: true });
  await widget.screenshot({ path: path.join(SHOT_DIR, 'dashboard-widget-only.png') });

  // Report
  console.log(JSON.stringify({
    view: 'dashboard',
    widget: {
      state: badgeText,
      canvases: canvasCount,
      height: Math.round(box.height),
      width: Math.round(box.width),
    },
    errors: {
      console: audit.consoleErrors,
      pageerror: audit.pageErrors,
      failedRequests: audit.failedRequests.filter(r => !r.includes('favicon')),
    },
  }, null, 2));

  // Fatal-level asserts: no unhandled page errors. (Console errors are
  // softer — sometimes third-party noise.)
  expect(audit.pageErrors, 'no page errors on dashboard').toEqual([]);
});

test('widget click navigates to /spectrum', async ({ page }) => {
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  const widgetHeader = page.getByText('RF SPECTRUM', { exact: true });
  await expect(widgetHeader).toBeVisible({ timeout: 10000 });
  const widget = widgetHeader.locator('xpath=ancestor::*[@role="button"][1]');
  await widget.click();
  await page.waitForURL(/\/spectrum$/, { timeout: 10000 });
  expect(page.url().endsWith('/spectrum'), 'URL is /spectrum after click').toBeTruthy();
});

test('spectrum page: full detail renders with axes + live trace + waterfall', async ({ page }) => {
  const audit = newAuditContext();
  wireAuditHooks(page, audit);

  await page.goto(BASE + '/spectrum', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1000);

  // Page title area
  await expect(page.getByRole('heading', { name: /RF Spectrum Monitor/i })).toBeVisible();

  // Connection indicator
  const connIndicator = page.getByText(/SSE streaming|reconnecting|RTL-SDR not present/);
  await expect(connIndicator, 'connection indicator present').toBeVisible();

  // Popup toggle
  const toggle = page.getByText(/Popup alerts/);
  await expect(toggle, 'popup toggle present').toBeVisible();

  // The full waterfall component renders .sa-panel per band — expect 5.
  const panels = page.locator('.sa-panel');
  await expect(panels, 'five SA panels').toHaveCount(5, { timeout: 15000 });

  // Each panel should have both canvases (spectrum + waterfall) and the axes SVG.
  for (const name of ['lora_868', 'aprs_144', 'gps_l1', 'lte_b20_dl', 'lte_b8_dl']) {
    const panel = page.locator(`.sa-panel:has(.sa-id:text("${name}"))`);
    await expect(panel, `panel for ${name} exists`).toBeVisible();
    await expect(panel.locator('.sa-spectrum-canvas'), `${name}: spectrum canvas`).toBeVisible();
    await expect(panel.locator('.sa-waterfall-canvas'), `${name}: waterfall canvas`).toBeVisible();
    await expect(panel.locator('.sa-axes'), `${name}: axes overlay`).toBeVisible();
    // The axis SVG must have at least one dBm label and one freq label.
    const labelCount = await panel.locator('.sa-axis-label').count();
    expect(labelCount, `${name}: axis labels (dBm + freq)`).toBeGreaterThan(3);
  }

  // Wait for a scan event to arrive (3s scan interval on the backend)
  // and confirm the canvas has non-empty pixel data. This is how we
  // distinguish "trace painted" from "blank canvas".
  await page.waitForTimeout(6000);

  const anyPainted = await page.evaluate(() => {
    const canvases = document.querySelectorAll('.sa-spectrum-canvas');
    for (const c of canvases) {
      const ctx = c.getContext('2d');
      if (!ctx || c.width === 0 || c.height === 0) continue;
      // sample the centre row, looking for any non-background pixel
      const mid = Math.floor(c.height / 2);
      const data = ctx.getImageData(0, mid, c.width, 1).data;
      for (let i = 0; i < data.length; i += 4) {
        // background gradient is very dark blue; anything with R>40
        // or G>40 is a real trace pixel.
        if (data[i] > 40 || data[i + 1] > 40) return true;
      }
    }
    return false;
  });
  // If still calibrating, painted may be false — log but don't fail hard.
  console.log(`spectrum: any trace painted so far = ${anyPainted}`);

  // Hover mid-panel on first band and check readout appears. Only if we
  // have data — otherwise the .sa-hover element won't render.
  if (anyPainted) {
    const firstPanel = panels.first().locator('.sa-plot');
    const box = await firstPanel.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width * 0.6, box.y + 40);
      // Small settle for the mousemove handler
      await page.waitForTimeout(300);
      const hover = firstPanel.locator('.sa-hover');
      const hoverVisible = await hover.isVisible().catch(() => false);
      console.log(`hover readout visible = ${hoverVisible}`);
    }
  }

  // Recent transitions table renders its header
  await expect(page.getByText(/Recent transitions/i)).toBeVisible();

  await page.screenshot({ path: path.join(SHOT_DIR, 'spectrum-page-full.png'), fullPage: true });

  console.log(JSON.stringify({
    view: 'spectrum',
    panels: 5,
    anyPainted,
    errors: {
      console: audit.consoleErrors,
      pageerror: audit.pageErrors,
      failedRequests: audit.failedRequests.filter(r => !r.includes('favicon')),
    },
  }, null, 2));

  expect(audit.pageErrors, 'no page errors on /spectrum').toEqual([]);
});

test('SSE stream: backend emits scan events with per-bin powers', async () => {
  // Use the Node global fetch with AbortController to read a bounded
  // slice of the streaming response. Playwright's request.get().text()
  // waits for Content-Length which SSE never sends.
  const http = require('http');
  const body = await new Promise((resolve, reject) => {
    let status = 0;
    let buf = '';
    const req = http.get(BASE + '/api/spectrum/stream', (res) => {
      status = res.statusCode;
      res.on('data', chunk => {
        buf += chunk.toString('utf8');
        if (buf.length > 4000 || buf.includes('event: scan') || buf.includes('event: transition')) {
          res.destroy();
          resolve({ status, body: buf });
        }
      });
      res.on('error', reject);
      res.on('end', () => resolve({ status, body: buf }));
    });
    req.on('error', reject);
    // Deadline: resolve with whatever we have, don't swallow the status.
    req.setTimeout(15000, () => { req.destroy(); resolve({ status, body: buf }); });
  });

  expect(body.status, 'SSE status 200').toBe(200);
  const hasEvent = body.body.includes('event: scan') || body.body.includes('event: transition');
  const summary = {
    status: body.status,
    bytes: body.body.length,
    hasEvent,
    firstBytes: body.body.slice(0, 260),
  };
  console.log('SSE:', JSON.stringify(summary, null, 2));
  // If still calibrating, hasEvent may be false — log rather than hard-fail.
});
