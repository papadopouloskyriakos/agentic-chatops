// @ts-check
const { test } = require('@playwright/test');
const path = require('path');
const fs = require('fs');
const { fetchAllRooms, ROOMS } = require('../helpers/matrix-api');
const { renderAuditPage } = require('../helpers/element-renderer');

require('dotenv').config({ path: path.resolve(__dirname, '../../.env') });

const TOKEN = process.env.MATRIX_CLAUDE_TOKEN;
const MODE = process.env.AUDIT_MODE || 'baseline';
const OUT_DIR = path.resolve(__dirname, '..', MODE === 'improved' ? 'improved/matrix' : 'baselines/matrix');

/** Categories we want to capture and their search criteria */
const CAPTURE_TARGETS = [
  { category: 'librenms-alert',     rooms: ['infra-nl', 'infra-gr'], max: 5, title: 'LibreNMS Alerts' },
  { category: 'prometheus-alert',   rooms: ['infra-nl', 'infra-gr'], max: 5, title: 'Prometheus Alerts' },
  { category: 'crowdsec-alert',     rooms: ['infra-nl'],             max: 5, title: 'CrowdSec Alerts' },
  { category: 'security-finding',   rooms: ['infra-nl'],             max: 5, title: 'Security Findings' },
  { category: 'progress',           rooms: ['infra-nl', 'cubeos'],   max: 6, title: 'Progress Updates' },
  { category: 'session-result',     rooms: ['infra-nl', 'cubeos'],   max: 3, title: 'Session Results' },
  { category: 'triage-delegation',  rooms: ['infra-nl', 'infra-gr'], max: 5, title: 'Triage Delegations' },
  { category: 'session-start',      rooms: ['infra-nl', 'cubeos'],   max: 3, title: 'Session Start Notices' },
  { category: 'busy-notice',        rooms: ['infra-nl', 'cubeos'],   max: 3, title: 'Busy Notices' },
];

let allRoomData;

test.beforeAll(async () => {
  if (!TOKEN) throw new Error('MATRIX_CLAUDE_TOKEN not set in .env');
  fs.mkdirSync(OUT_DIR, { recursive: true });
  console.log(`Fetching messages from ${Object.keys(ROOMS).length} rooms...`);
  allRoomData = await fetchAllRooms(TOKEN);
  console.log('Messages fetched. Room summary:');
  for (const [room, cats] of Object.entries(allRoomData)) {
    const total = Object.values(cats).reduce((s, arr) => s + arr.length, 0);
    const catList = Object.entries(cats).map(([k, v]) => `${k}(${v.length})`).join(', ');
    console.log(`  ${room}: ${total} msgs — ${catList}`);
  }
});

// Generate a test for each capture target
for (const target of CAPTURE_TARGETS) {
  test(`capture ${target.category}`, async ({ page }) => {
    // Collect messages from target rooms
    let messages = [];
    for (const room of target.rooms) {
      const roomCats = allRoomData?.[room] || {};
      const catMsgs = roomCats[target.category] || [];
      messages.push(...catMsgs.map(m => ({ ...m, _room: room })));
    }

    if (messages.length === 0) {
      console.log(`  SKIP ${target.category}: no messages found in ${target.rooms.join(', ')}`);
      test.skip();
      return;
    }

    // Take up to max messages, preferring diversity across rooms
    messages = messages.slice(0, target.max);
    const primaryRoom = target.rooms[0];

    console.log(`  Rendering ${messages.length} ${target.category} messages`);

    const html = renderAuditPage({
      title: `Matrix Audit: ${target.title}`,
      category: target.category,
      room: primaryRoom,
      messages,
      auditNotes: [
        `${messages.length} message(s) captured from ${target.rooms.join(', ')}`,
        `Mode: ${MODE} | Captured: ${new Date().toISOString()}`,
      ],
    });

    await page.setContent(html, { waitUntil: 'load' });
    // Wait for any web fonts to settle
    await page.waitForTimeout(500);

    const outPath = path.join(OUT_DIR, `${target.category}.png`);
    await page.screenshot({ path: outPath, fullPage: true });
    console.log(`  Saved: ${outPath}`);
  });
}

// Special test: capture ALL message types from a single room for a timeline view
test('capture infra-nl full timeline', async ({ page }) => {
  const roomCats = allRoomData?.['infra-nl'] || {};
  let allMsgs = [];
  for (const msgs of Object.values(roomCats)) {
    allMsgs.push(...msgs);
  }
  allMsgs.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
  // Take last 20 messages
  allMsgs = allMsgs.slice(-20);

  if (allMsgs.length === 0) {
    test.skip();
    return;
  }

  const html = renderAuditPage({
    title: 'Matrix Audit: Full Timeline — #infra-nl-prod',
    category: 'full-timeline',
    room: 'infra-nl',
    messages: allMsgs,
    auditNotes: [
      `${allMsgs.length} messages (all types) — chronological order`,
      `Mode: ${MODE} | Captured: ${new Date().toISOString()}`,
    ],
  });

  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForTimeout(500);

  const outPath = path.join(OUT_DIR, 'full-timeline-infra-nl.png');
  await page.screenshot({ path: outPath, fullPage: true });
  console.log(`  Saved: ${outPath}`);
});

test('capture cubeos full timeline', async ({ page }) => {
  const roomCats = allRoomData?.['cubeos'] || {};
  let allMsgs = [];
  for (const msgs of Object.values(roomCats)) {
    allMsgs.push(...msgs);
  }
  allMsgs.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
  allMsgs = allMsgs.slice(-20);

  if (allMsgs.length === 0) {
    test.skip();
    return;
  }

  const html = renderAuditPage({
    title: 'Matrix Audit: Full Timeline — #cubeos',
    category: 'full-timeline',
    room: 'cubeos',
    messages: allMsgs,
    auditNotes: [
      `${allMsgs.length} messages (all types) — chronological order`,
      `Mode: ${MODE} | Captured: ${new Date().toISOString()}`,
    ],
  });

  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForTimeout(500);

  const outPath = path.join(OUT_DIR, 'full-timeline-cubeos.png');
  await page.screenshot({ path: outPath, fullPage: true });
  console.log(`  Saved: ${outPath}`);
});
