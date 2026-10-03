// @ts-check
const { test, expect } = require('@playwright/test');
const path = require('path');

const ssDir = path.join(__dirname, '..', 'screenshots');

// SSE-powered SPA — never use networkidle, always domcontentloaded + wait
const NAV_OPTS = { waitUntil: 'domcontentloaded', timeout: 15000 };
const RENDER_WAIT = 2500; // ms for Vue to mount + API calls

// ─── Helpers ───

/** Navigate and wait for Vue render */
async function goTo(page, path) {
  await page.goto(path, NAV_OPTS);
  await page.waitForTimeout(RENDER_WAIT);
}

/** Collect console errors during a test */
function collectConsoleErrors(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  return errors;
}

/** Collect network failures (non-SSE) */
function collectNetworkErrors(page) {
  const errors = [];
  page.on('response', res => {
    const url = res.url();
    if (url.includes('/api/events')) return;
    if (res.status() >= 400) {
      errors.push(`${res.status()} ${res.url()}`);
    }
  });
  return errors;
}

/** Check page text for garbage values */
async function assertNoGarbageText(page) {
  const body = await page.locator('body').innerText();
  expect(body).not.toContain('[object Object]');
  const lines = body.split('\n').map(l => l.trim()).filter(Boolean);
  for (const line of lines) {
    if (line.startsWith('{') || line.startsWith('[') || line.startsWith('//') || line.includes(':')) continue;
    if (line === 'undefined' || line === 'null') {
      throw new Error(`Found isolated garbage text: "${line}"`);
    }
  }
}

// ════════════════════════════════════════════════════════════════════════════════
// NAVIGATION TESTS
// ════════════════════════════════════════════════════════════════════════════════

test.describe('Navigation', () => {
  test('dashboard loads with correct title', async ({ page }) => {
    await goTo(page, '/');
    await expect(page).toHaveTitle('MeshSat');
    await page.screenshot({ path: path.join(ssDir, 'test-home.png'), fullPage: true });
  });

  const navItems = [
    { label: 'Dashboard', href: '/' },
    { label: 'Comms', href: '/messages' },
    { label: 'Peers', href: '/nodes' },
    { label: 'Bridge', href: '/bridge' },
    { label: 'Interfaces', href: '/interfaces' },
    { label: 'Passes', href: '/passes' },
    { label: 'Map', href: '/map' },
    { label: 'Settings', href: '/settings' },
    { label: 'Audit', href: '/audit' },
    { label: 'Help', href: '/help' },
    { label: 'About', href: '/about' },
  ];

  test('all nav links present', async ({ page }) => {
    await goTo(page, '/');
    for (const item of navItems) {
      const link = page.locator(`nav a[href="${item.href}"]`);
      await expect(link).toBeVisible();
    }
  });

  for (const item of navItems) {
    test(`page loads: ${item.label} (${item.href})`, async ({ page }) => {
      const netErrors = collectNetworkErrors(page);
      await goTo(page, item.href);
      await expect(page).toHaveTitle('MeshSat');
      const slug = item.href.replace(/\//g, '_').replace(/^_/, '') || 'dashboard';
      await page.screenshot({ path: path.join(ssDir, `test-${slug}.png`), fullPage: true });
      const critical = netErrors.filter(e => !e.includes('501') && !e.includes('/meshtastic/'));
      expect(critical).toEqual([]);
    });
  }
});

// ════════════════════════════════════════════════════════════════════════════════
// FRONTEND INTEGRITY TESTS
// ════════════════════════════════════════════════════════════════════════════════

test.describe('Frontend Integrity', () => {

  test('dashboard — key widgets visible', async ({ page }) => {
    await goTo(page, '/');
    await expect(page.locator('button:has-text("IRIDIUM")').first()).toBeVisible();
    await expect(page.locator('button:has-text("MESH")').first()).toBeVisible();
    await expect(page.locator('button:has-text("CELLULAR")').first()).toBeVisible();
    await expect(page.locator('text=MESSAGE QUEUE')).toBeVisible();
    await expect(page.locator('text=ACTIVITY LOG')).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('dashboard — no garbage text', async ({ page }) => {
    await goTo(page, '/');
    await assertNoGarbageText(page);
  });

  test('comms page — message tabs visible', async ({ page }) => {
    await goTo(page, '/messages');
    await expect(page.getByRole('button', { name: 'Mesh Messages' })).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('peers page — heading visible', async ({ page }) => {
    await goTo(page, '/nodes');
    await expect(page.getByRole('heading', { name: 'Peers' })).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('bridge page — heading visible', async ({ page }) => {
    await goTo(page, '/bridge');
    await expect(page.getByRole('heading', { name: 'Bridge' })).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('interfaces page — heading visible', async ({ page }) => {
    await goTo(page, '/interfaces');
    await expect(page.getByRole('heading', { name: 'Interfaces' })).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('passes page — heading visible', async ({ page }) => {
    await goTo(page, '/passes');
    await expect(page.getByRole('heading', { name: /Pass Predictor|Passes/ })).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('settings page — heading visible', async ({ page }) => {
    await goTo(page, '/settings');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('audit page — heading visible', async ({ page }) => {
    await goTo(page, '/audit');
    await expect(page.locator('text=Audit Log')).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('help page loads', async ({ page }) => {
    await goTo(page, '/help');
    await expect(page.getByRole('heading', { name: /Help|Documentation|Guide/ })).toBeVisible();
    await assertNoGarbageText(page);
  });

  test('about page loads', async ({ page }) => {
    await goTo(page, '/about');
    await expect(page.getByRole('heading', { name: /About|MeshSat/ })).toBeVisible();
    await assertNoGarbageText(page);
  });
});

// ════════════════════════════════════════════════════════════════════════════════
// RESPONSIVE TESTS
// ════════════════════════════════════════════════════════════════════════════════

test.describe('Responsive', () => {
  test('dashboard — mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await goTo(page, '/');
    await page.screenshot({ path: path.join(ssDir, 'test-mobile-dashboard.png'), fullPage: true });
    const body = await page.locator('body').innerText();
    expect(body.length).toBeGreaterThan(50);
  });

  test('comms — mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await goTo(page, '/messages');
    await page.screenshot({ path: path.join(ssDir, 'test-mobile-comms.png'), fullPage: true });
    const body = await page.locator('body').innerText();
    expect(body.length).toBeGreaterThan(50);
  });

  test('interfaces — mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await goTo(page, '/interfaces');
    await page.screenshot({ path: path.join(ssDir, 'test-mobile-interfaces.png'), fullPage: true });
    const body = await page.locator('body').innerText();
    expect(body.length).toBeGreaterThan(50);
  });
});

// ════════════════════════════════════════════════════════════════════════════════
// BACKEND API TESTS
// ════════════════════════════════════════════════════════════════════════════════
// Note: Many MeshSat API endpoints return wrapped objects like {gateways: [...]}
// not bare arrays. Some return null when empty. Tests match actual response shapes.

test.describe('Backend API', () => {

  test('health endpoint returns healthy', async ({ page }) => {
    const res = await page.request.get('/health');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe('healthy');
    expect(body.database).toBe(true);
  });

  test('GET /api/status returns connected status', async ({ page }) => {
    const res = await page.request.get('/api/status');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('connected');
  });

  test('GET /api/gateways returns gateway list', async ({ page }) => {
    const res = await page.request.get('/api/gateways');
    expect(res.status()).toBe(200);
    const body = await res.json();
    // Response is {gateways: [...]}
    expect(body).toHaveProperty('gateways');
    expect(Array.isArray(body.gateways)).toBeTruthy();
    expect(body.gateways.length).toBeGreaterThan(0);
    for (const gw of body.gateways) {
      expect(gw).toHaveProperty('type');
    }
  });

  test('GET /api/nodes returns node list', async ({ page }) => {
    const res = await page.request.get('/api/nodes');
    expect(res.status()).toBe(200);
    const body = await res.json();
    // Response is {count: N, nodes: [...]}
    expect(body).toHaveProperty('nodes');
    expect(Array.isArray(body.nodes)).toBeTruthy();
  });

  test('GET /api/messages returns message list', async ({ page }) => {
    const res = await page.request.get('/api/messages?limit=10');
    expect(res.status()).toBe(200);
    const body = await res.json();
    // Response is {limit: N, messages: [...]}
    expect(body).toHaveProperty('messages');
    expect(Array.isArray(body.messages)).toBeTruthy();
  });

  test('GET /api/interfaces returns array', async ({ page }) => {
    const res = await page.request.get('/api/interfaces');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBeTruthy();
  });

  test('GET /api/cellular/status returns modem info', async ({ page }) => {
    const res = await page.request.get('/api/cellular/status');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('connected');
    expect(body).toHaveProperty('port');
    expect(body).toHaveProperty('imei');
  });

  test('GET /api/cellular/sms returns SMS list', async ({ page }) => {
    const res = await page.request.get('/api/cellular/sms?limit=10');
    expect(res.status()).toBe(200);
    const body = await res.json();
    // May be array or null
    expect(body === null || Array.isArray(body)).toBeTruthy();
  });

  test('GET /api/cellular/data/status returns data status', async ({ page }) => {
    const res = await page.request.get('/api/cellular/data/status');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('active');
  });

  test('GET /api/iridium/queue returns queue', async ({ page }) => {
    const res = await page.request.get('/api/iridium/queue');
    expect(res.status()).toBe(200);
    const body = await res.json();
    // Response is {queue: [...]}
    expect(body).toHaveProperty('queue');
    expect(Array.isArray(body.queue)).toBeTruthy();
  });

  test('GET /api/iridium/scheduler returns scheduler state', async ({ page }) => {
    const res = await page.request.get('/api/iridium/scheduler');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('mode');
    expect(body).toHaveProperty('enabled');
  });

  test('GET /api/access-rules returns array', async ({ page }) => {
    const res = await page.request.get('/api/access-rules');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBeTruthy();
  });

  test('GET /api/object-groups returns array or null', async ({ page }) => {
    const res = await page.request.get('/api/object-groups');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body === null || Array.isArray(body)).toBeTruthy();
  });

  test('GET /api/deliveries returns array', async ({ page }) => {
    const res = await page.request.get('/api/deliveries');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBeTruthy();
  });

  test('GET /api/transport/channels returns channel registry', async ({ page }) => {
    const res = await page.request.get('/api/transport/channels');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBeTruthy();
    expect(body.length).toBeGreaterThan(0);
  });

  test('GET /api/config returns config object', async ({ page }) => {
    const res = await page.request.get('/api/config');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(typeof body).toBe('object');
  });

  test('GET /api/audit returns array or null', async ({ page }) => {
    const res = await page.request.get('/api/audit');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body === null || Array.isArray(body)).toBeTruthy();
  });

  test('GET /api/locations/resolved returns location', async ({ page }) => {
    const res = await page.request.get('/api/locations/resolved');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('resolved');
  });

  test('GET /api/zigbee/status returns status', async ({ page }) => {
    const res = await page.request.get('/api/zigbee/status');
    expect(res.status()).toBe(200);
  });

  test('GET /api/presets returns array', async ({ page }) => {
    const res = await page.request.get('/api/presets');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBeTruthy();
  });

  test('GET /api/messages/stats returns stats object', async ({ page }) => {
    const res = await page.request.get('/api/messages/stats');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(typeof body).toBe('object');
  });
});

// ════════════════════════════════════════════════════════════════════════════════
// ERROR DETECTION
// ════════════════════════════════════════════════════════════════════════════════

test.describe('Error Detection', () => {

  test('no console errors on dashboard', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await goTo(page, '/');
    const critical = errors.filter(e =>
      !e.includes('SSE') && !e.includes('EventSource') && !e.includes('net::ERR')
    );
    expect(critical).toEqual([]);
  });

  test('no broken asset requests on dashboard', async ({ page }) => {
    const broken = [];
    page.on('response', res => {
      if (res.status() === 404 && (res.url().includes('/assets/') || res.url().includes('.png') || res.url().includes('.svg'))) {
        broken.push(res.url());
      }
    });
    await goTo(page, '/');
    expect(broken).toEqual([]);
  });

  for (const pg of ['/messages', '/bridge', '/interfaces', '/settings']) {
    test(`no console errors on ${pg}`, async ({ page }) => {
      const errors = collectConsoleErrors(page);
      await goTo(page, pg);
      const critical = errors.filter(e =>
        !e.includes('SSE') && !e.includes('EventSource') && !e.includes('net::ERR')
      );
      expect(critical).toEqual([]);
    });
  }
});
