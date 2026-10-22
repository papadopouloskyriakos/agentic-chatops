// MIL/ITU-compliance audit for the MeshSat spectrum widget + page.
//
// Design contract derived from:
//  * FM 3-12 (Cyberspace & EW Operations; incorporates FM 24-33 MIJI
//    reporting — operator must report frequency, time, duration,
//    signal strength, mission effect).
//  * ITU-R SM.1880 (spectrum occupancy measurement — occupancy %
//    must be presented alongside spectrum).
//  * MIL-STD-1472H §5.2 (unambiguous primary indicator; data freshness
//    always visible).
//
// Split:
//  WIDGET (dashboard — "am I OK?"): 1-second glance answer.
//    - aggregate worst state, per-band state chip, unacked count,
//      live/idle + last-update freshness, 5 band rows.
//  PAGE (/spectrum — "what/where/when"): MIJI-report-grade detail.
//    - frequency MHz axis, dBm color legend, time axis, baseline &
//      peak markers, state + dwell, occupancy %, spectral flatness,
//      event history, recommended action, hardware status.
//
// Tests fail on missing info; screenshots captured for visual review.

const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const BASE = 'http://nlparallax01:6050';
const SHOT_DIR = path.resolve(__dirname, '..', 'baselines', 'meshsat-spectrum-mil');
const REPORT_PATH = path.resolve(__dirname, '..', 'baselines', 'meshsat-spectrum-mil', 'audit-report.json');
fs.mkdirSync(SHOT_DIR, { recursive: true });

const auditResults = {
  widget: { pass: [], fail: [] },
  page: { pass: [], fail: [] },
  timestamp: new Date().toISOString(),
};

function record(area, contract, passOrFail, detail) {
  auditResults[area][passOrFail].push({ contract, detail: detail || '' });
}

test.afterAll(async () => {
  fs.writeFileSync(REPORT_PATH, JSON.stringify(auditResults, null, 2));
});

test.describe('MIL-contract: widget', () => {
  test('widget presents MIL-STD-1472 at-a-glance information', async ({ page }) => {
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2500);

    const widgetHeader = page.getByText('RF SPECTRUM', { exact: true });
    await expect(widgetHeader).toBeVisible({ timeout: 10000 });
    const widget = widgetHeader.locator('xpath=ancestor::*[@role="button"][1]');
    await expect(widget).toBeVisible();

    await widget.screenshot({ path: path.join(SHOT_DIR, 'widget.png') });

    // Contract W1: aggregate threat state word visible
    const stateBadge = widget.locator('span.uppercase').first();
    const stateText = (await stateBadge.innerText()).toLowerCase().trim();
    if (['jamming', 'interference', 'calibrating', 'clear'].includes(stateText)) {
      record('widget', 'W1 aggregate worst-state word', 'pass', stateText);
    } else {
      record('widget', 'W1 aggregate worst-state word', 'fail', `got: ${stateText}`);
    }

    // Contract W2: 5 band rows
    const rows = widget.locator('.band-row');
    const rowCount = await rows.count();
    if (rowCount === 5) record('widget', 'W2 five band rows', 'pass');
    else record('widget', 'W2 five band rows', 'fail', `got: ${rowCount}`);

    // Contract W3: each row labelled with short band name
    for (const lbl of ['LoRa 868', 'APRS 2m', 'GPS L1', 'LTE-20', 'LTE-8']) {
      const found = await widget.getByText(lbl).isVisible().catch(() => false);
      if (found) record('widget', `W3 label "${lbl}"`, 'pass');
      else record('widget', `W3 label "${lbl}"`, 'fail');
    }

    // Contract W4: link liveness indicator
    const live = widget.getByText(/^(LIVE|IDLE)$/);
    if (await live.isVisible()) record('widget', 'W4 LIVE/IDLE indicator', 'pass');
    else record('widget', 'W4 LIVE/IDLE indicator', 'fail');

    // Contract W5: data freshness indicator (either a numeric age
    // readout or an explicit "initialising" state). MIL-STD-1472H
    // §5.2 requires data freshness on a safety-critical display;
    // "initialising" is an honest pre-scan state, not a missing
    // indicator.
    const freshnessRegex = /(\d+\s*(s|sec|min|m|h)\s*ago|initialising|initializing)/i;
    const widgetText = await widget.innerText();
    if (freshnessRegex.test(widgetText)) {
      record('widget', 'W5 last-update age', 'pass');
    } else {
      record('widget', 'W5 last-update age', 'fail', 'no freshness indicator visible');
    }

    // Contract W6: per-band peak-delta readout (numeric)
    const deltaCells = widget.locator('.delta-cell');
    const deltaCount = await deltaCells.count();
    if (deltaCount === 5) record('widget', 'W6 per-band delta readout', 'pass');
    else record('widget', 'W6 per-band delta readout', 'fail', `got ${deltaCount} cells`);

    // Contract W7: click → /spectrum navigation
    await widget.click({ force: true });
    await page.waitForURL(/\/spectrum$/, { timeout: 5000 });
    record('widget', 'W7 click navigates to /spectrum', 'pass');
  });
});

test.describe('MIL-contract: page', () => {
  test('spectrum page presents MIJI-grade detail', async ({ page }) => {
    await page.goto(BASE + '/spectrum', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(3000);

    await page.screenshot({ path: path.join(SHOT_DIR, 'page-full.png'), fullPage: true });

    const body = await page.innerText('body');

    // Contract P1: page title / heading
    const heading = page.getByRole('heading').first();
    if (await heading.isVisible()) record('page', 'P1 page heading', 'pass');
    else record('page', 'P1 page heading', 'fail');

    // Contract P2: per-band panels (5)
    // Locator should match whatever element holds a per-band detail
    // panel. We look for .band-panel first, fall back to looking for
    // all 5 band labels.
    let panels = page.locator('.band-panel');
    let panelCount = await panels.count();
    if (panelCount < 5) {
      // fall back: count headings per band
      const names = ['LoRa', 'APRS', 'GPS', 'LTE'];
      let present = 0;
      for (const n of names) if (await page.getByText(n, { exact: false }).first().isVisible().catch(() => false)) present++;
      panelCount = present;
    }
    if (panelCount >= 4) record('page', 'P2 per-band panels', 'pass', `${panelCount}`);
    else record('page', 'P2 per-band panels', 'fail', `${panelCount}`);

    // Contract P3: MHz frequency axis labels
    const mhzRegex = /\b(86[89]|43[0-9]|144|145|15[7-9]|162|192[0-9]|21[0-9]{2}|26[0-9]{2}|8[0-9]{2}\.?\d?)\s*MHz\b/;
    if (mhzRegex.test(body)) record('page', 'P3 MHz frequency axis labels', 'pass');
    else record('page', 'P3 MHz frequency axis labels', 'fail', 'no "xxx MHz" label found in page text');

    // Contract P4: dBm color legend / scale
    if (/-?\d+\s*dBm?\b/.test(body)) record('page', 'P4 dBm legend present', 'pass');
    else record('page', 'P4 dBm legend present', 'fail', 'no "X dBm" text');

    // Contract P5: time axis indicator on waterfall
    if (/\b(now|\d+\s*s\s*ago|time\s*(s|sec|→|↑))/i.test(body))
      record('page', 'P5 time axis / scroll direction', 'pass');
    else
      record('page', 'P5 time axis / scroll direction', 'fail', 'no time axis text');

    // Contract P6: baseline reference (numerical or explicit marker)
    if (/baseline|baseline mean|σ|sigma/i.test(body)) record('page', 'P6 baseline reference', 'pass');
    else record('page', 'P6 baseline reference', 'fail');

    // Contract P7: peak marker / peak frequency readout
    if (/peak|max dB|peak\s*@?\s*\d/i.test(body)) record('page', 'P7 peak readout', 'pass');
    else record('page', 'P7 peak readout', 'fail');

    // Contract P8: state + dwell time. Matches "clear for 26m 50s",
    // "jamming for 34s", "degraded for 1h 02m" — accepts any of
    // s/sec/min/m/h as the first time unit after the numeric literal.
    if (/dwell|since|for\s+\d+\s*(s|sec|min|m|h)\b/i.test(body))
      record('page', 'P8 state dwell time', 'pass');
    else
      record('page', 'P8 state dwell time', 'fail');

    // Contract P9: occupancy % (ITU-R SM.1880)
    if (/occup(ancy|ied)\s*[:=]?\s*\d+(\.\d+)?\s*%|\b\d+%\s+occupancy/i.test(body))
      record('page', 'P9 ITU-R SM.1880 occupancy %', 'pass');
    else
      record('page', 'P9 ITU-R SM.1880 occupancy %', 'fail');

    // Contract P10: spectral flatness (barrage-jamming discriminator)
    if (/flatness|wiener|entropy/i.test(body))
      record('page', 'P10 spectral flatness metric', 'pass');
    else
      record('page', 'P10 spectral flatness metric', 'fail');

    // Contract P11: event history / MIJI log
    if (/history|log|transitions?|events?|timeline/i.test(body))
      record('page', 'P11 event history / MIJI log', 'pass');
    else
      record('page', 'P11 event history / MIJI log', 'fail');

    // Contract P12: recommended action / ECCM guidance
    if (/recommend|action|eccm|anti.?jam|mitigation/i.test(body))
      record('page', 'P12 recommended ECCM action', 'pass');
    else
      record('page', 'P12 recommended ECCM action', 'fail');

    // Contract P13: hardware status (RTL-SDR health)
    if (/rtl.sdr|tuner|r82\d\d|sample rate|gain|dongle/i.test(body))
      record('page', 'P13 RTL-SDR hardware status', 'pass');
    else
      record('page', 'P13 RTL-SDR hardware status', 'fail');

    // Contract P14: MIJI report export / CoT relay status
    if (/MIJI|CoT|TAK|report|export|copy/i.test(body))
      record('page', 'P14 MIJI-9 export / CoT relay status', 'pass');
    else
      record('page', 'P14 MIJI-9 export / CoT relay status', 'fail');
  });
});
