// @ts-check
/**
 * Synthetic before/after comparison — renders mock messages with old vs new formatting
 * to demonstrate the visual improvements without needing live alerts.
 */
const { test } = require('@playwright/test');
const path = require('path');
const fs = require('fs');
const { renderAuditPage } = require('../helpers/element-renderer');
const { renderIssuePage } = require('../helpers/youtrack-renderer');

const OUT_DIR = path.resolve(__dirname, '..', 'comparison');

test.beforeAll(() => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
});

// ── Synthetic Matrix Messages ──

const BEFORE_SESSION_RESULT = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.text',
  timestamp: Date.now() - 60000,
  body: '@dominicus [IFRNLLEI01PRD-400] Claude (2m15s):\n\nInvestigated the alert...',
  formatted_body: '<a href="https://matrix.to/#/@dominicus:matrix.example.net">@dominicus</a> '
    + '<p><strong>[IFRNLLEI01PRD-400] Claude (2m15s):</strong></p>'
    + '<p>Investigated the alert on <code>nl-pve02</code>.</p>'
    + '<p><ul>'
    + '<li><strong>Root cause:</strong> ZFS pool <code>rpool</code> at 89% — large VM snapshots from last maintenance window not cleaned up</li>'
    + '<li><strong>Action:</strong> Removed 3 stale snapshots (12GB freed), pool now at 71%</li>'
    + '<li><strong>Prevention:</strong> Added snapshot retention cron to <code>/etc/cron.daily/zfs-snap-cleanup</code></li>'
    + '</ul></p>'
    + '<p>> Note: This host had a similar issue in IFRNLLEI01PRD-286</p>'
    + '<p>CONFIDENCE: 0.92 — Verified pool usage dropped from 89% to 71% after cleanup</p>',
};

const AFTER_SESSION_RESULT = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.text',
  timestamp: Date.now() - 60000,
  body: '@dominicus [IFRNLLEI01PRD-400] Claude (2m15s):\n\nInvestigated the alert...',
  formatted_body: '<a href="https://matrix.to/#/@dominicus:matrix.example.net">@dominicus</a> '
    + '<p><strong>[IFRNLLEI01PRD-400] Claude (2m15s):</strong></p>'
    + '<p>Investigated the alert on <code>nl-pve02</code>.</p>'
    + '<ul>'
    + '<li><strong>Root cause:</strong> ZFS pool <code>rpool</code> at 89% — large VM snapshots from last maintenance window not cleaned up</li>'
    + '<li><strong>Action:</strong> Removed 3 stale snapshots (12GB freed), pool now at 71%</li>'
    + '<li><strong>Prevention:</strong> Added snapshot retention cron to <code>/etc/cron.daily/zfs-snap-cleanup</code></li>'
    + '</ul>'
    + '<blockquote>Note: This host had a similar issue in IFRNLLEI01PRD-286</blockquote>'
    + '<hr><p><strong>Confidence:</strong> <code>0.92</code> — Verified pool usage dropped from 89% to 71% after cleanup</p>',
};

const BEFORE_PROGRESS = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.notice',
  timestamp: Date.now() - 90000,
  body: '14:32 [IFRNLLEI01PRD-400] Working... (1m30s)\n  mcp__proxmox__pve_guest_status\n  mcp__proxmox__pve_node_status\n  mcp__netbox__netbox_get_objects\n  Bash: ssh nl-pve02 "zpool list rpool"\n  mcp__youtrack__get_issue_comments\n  ToolSearch: select:mcp__proxmox__pve_storage',
  formatted_body: '<code>14:32</code> <b>[IFRNLLEI01PRD-400]</b> Working... (1m30s)<br/>'
    + '&nbsp;&nbsp;mcp__proxmox__pve_guest_status<br/>'
    + '&nbsp;&nbsp;mcp__proxmox__pve_node_status<br/>'
    + '&nbsp;&nbsp;mcp__netbox__netbox_get_objects<br/>'
    + '&nbsp;&nbsp;Bash: ssh nl-pve02 "zpool list rpool"<br/>'
    + '&nbsp;&nbsp;mcp__youtrack__get_issue_comments<br/>'
    + '&nbsp;&nbsp;ToolSearch: select:mcp__proxmox__pve_storage',
};

const AFTER_PROGRESS = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.notice',
  timestamp: Date.now() - 90000,
  body: '14:32 [IFRNLLEI01PRD-400] Working... (1m30s)\n  Proxmox: guest status\n  Proxmox: node status\n  NetBox: get objects\n  Bash: ssh nl-pve02 "zpool list rpool"\n  YouTrack: get issue comments\n  ToolSearch: select Proxmox storage',
  formatted_body: '<code>14:32</code> <b>[IFRNLLEI01PRD-400]</b> Working... (1m30s)<br>'
    + '&nbsp;&nbsp;Proxmox: guest status<br>'
    + '&nbsp;&nbsp;Proxmox: node status<br>'
    + '&nbsp;&nbsp;NetBox: get objects<br>'
    + '&nbsp;&nbsp;Bash: ssh nl-pve02 "zpool list rpool"<br>'
    + '&nbsp;&nbsp;YouTrack: get issue comments<br>'
    + '&nbsp;&nbsp;ToolSearch: select Proxmox storage',
};

const BEFORE_TRIAGE = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.text',
  timestamp: Date.now() - 120000,
  body: '@openclaw use the exec tool to run: ./skills/infra-triage/infra-triage.sh nl-pve02 "ZFS pool usage high" critical',
  formatted_body: '<a href="https://matrix.to/#/@openclaw:matrix.example.net">@openclaw</a> use the exec tool to run: <code>./skills/infra-triage/infra-triage.sh nl-pve02 "ZFS pool usage high" critical</code>',
};

const AFTER_TRIAGE = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.text',
  timestamp: Date.now() - 120000,
  body: '@openclaw Investigating: nl-pve02 — ZFS pool usage high (critical)\ninfra-triage.sh nl-pve02',
  formatted_body: '<a href="https://matrix.to/#/@openclaw:matrix.example.net">@openclaw</a> '
    + '<strong>Investigating:</strong> <code>nl-pve02</code><br>'
    + '<small>ZFS pool usage high (critical)</small><br>'
    + '<code>infra-triage.sh nl-pve02</code>',
};

const BEFORE_ALERT = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.text',
  timestamp: Date.now() - 150000,
  body: '\ud83d\udd34 [Prometheus] ALERT: KubePersistentVolumeFillingUp (warning)\nNamespace: monitoring\nNode: nlk8s-node03\nSummary: PersistentVolume is filling up.',
  formatted_body: '<b>\ud83d\udd34 [Prometheus] ALERT:</b> KubePersistentVolumeFillingUp (<code>warning</code>)<br/>'
    + 'Namespace: monitoring<br/>'
    + 'Node: <code>nlk8s-node03</code><br/>'
    + 'Summary: PersistentVolume is filling up.',
};

const AFTER_ALERT = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.text',
  timestamp: Date.now() - 150000,
  body: '\ud83d\udd34 [Prometheus] ALERT: KubePersistentVolumeFillingUp (warning)\nNamespace: monitoring\nNode: nlk8s-node03\nSummary: PersistentVolume is filling up.',
  formatted_body: '<b>\ud83d\udd34 [Prometheus] ALERT:</b> KubePersistentVolumeFillingUp (<code>warning</code>)<br>'
    + 'Namespace: monitoring<br>'
    + 'Node: <code>nlk8s-node03</code><br>'
    + 'Summary: PersistentVolume is filling up.',
};

const BEFORE_SESSION_END = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.notice',
  timestamp: Date.now() - 30000,
  body: 'Session ended for IFRNLLEI01PRD-400. State set to To Verify.\n\nSummary:\nRemoved stale ZFS snapshots on nl-pve02. Pool freed from 89% to 71%.',
  formatted_body: '<p><strong>Session ended for IFRNLLEI01PRD-400.</strong> State set to To Verify.</p>'
    + '<p><strong>Summary:</strong><br>Removed stale ZFS snapshots on nl-pve02. Pool freed from 89% to 71%.</p>',
};

const AFTER_SESSION_END = {
  sender: '@claude:matrix.example.net',
  msgtype: 'm.notice',
  timestamp: Date.now() - 30000,
  body: 'Session ended for IFRNLLEI01PRD-400. State set to To Verify.\n\nSummary:\nRemoved stale ZFS snapshots on nl-pve02. Pool freed from 89% to 71%.',
  formatted_body: '<p><strong>Session ended</strong> for <code>IFRNLLEI01PRD-400</code> — state set to <em>To Verify</em></p>'
    + '<hr>'
    + '<p>Removed stale ZFS snapshots on <code>nl-pve02</code>. Pool freed from 89% to 71%.</p>',
};

// ── Matrix Tests ──

test('Matrix BEFORE — full flow', async ({ page }) => {
  const html = renderAuditPage({
    title: 'BEFORE — Typical Alert Flow',
    category: 'before',
    room: 'infra-nl',
    messages: [BEFORE_ALERT, BEFORE_TRIAGE, BEFORE_PROGRESS, BEFORE_SESSION_RESULT, BEFORE_SESSION_END],
  });
  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT_DIR, 'matrix-BEFORE-flow.png'), fullPage: true });
});

test('Matrix AFTER — full flow', async ({ page }) => {
  const html = renderAuditPage({
    title: 'AFTER — Typical Alert Flow',
    category: 'after',
    room: 'infra-nl',
    messages: [AFTER_ALERT, AFTER_TRIAGE, AFTER_PROGRESS, AFTER_SESSION_RESULT, AFTER_SESSION_END],
  });
  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT_DIR, 'matrix-AFTER-flow.png'), fullPage: true });
});

// ── YouTrack Tests ──

test('YouTrack BEFORE — CrowdSec issue', async ({ page }) => {
  const html = renderIssuePage({
    issueId: 'IFRNLLEI01PRD-400',
    summary: 'CrowdSec: ssh-bf from 203.0.113.42 on nldmz01',
    description: '**CrowdSec Alert**\n\n**Host:** nldmz01\n**Scenario:** crowdsecurity/ssh-bf\n**Source IP:** 203.0.113.42 (US, AS13335 Cloudflare)\n**Events:** 12\n**Decision:** ban 4h\n**Time:** 2026-04-07T14:00:00Z to 2026-04-07T18:00:00Z\n**Severity:** high',
    comments: [{
      author: { name: 'Claude' },
      created: Date.now() - 3600000,
      text: 'CrowdSec alert re-fired: ssh-bf from 203.0.113.42 on nldmz01 at 2026-04-07T15:32:15.000Z (count: 3, flap #2)',
    }],
  });
  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT_DIR, 'youtrack-BEFORE-crowdsec.png'), fullPage: true });
});

test('YouTrack AFTER — CrowdSec issue', async ({ page }) => {
  const html = renderIssuePage({
    issueId: 'IFRNLLEI01PRD-400',
    summary: 'CrowdSec: ssh-bf from 203.0.113.42 on nldmz01',
    description: '## CrowdSec Alert\n\n| Field | Value |\n|-------|-------|\n| Host | `nldmz01` |\n| Scenario | `crowdsecurity/ssh-bf` |\n| Source IP | 203.0.113.42 (US, AS13335 Cloudflare) |\n| Events | 12 |\n| Decision | ban 4h |\n| Time | 2026-04-07T14:00:00Z to 2026-04-07T18:00:00Z |\n| Severity | **high** |',
    comments: [{
      author: { name: 'Claude' },
      created: Date.now() - 3600000,
      text: 'CrowdSec alert re-fired: ssh-bf from 203.0.113.42 on nldmz01 at 2026-04-07T15:32:15.000Z (count: 3, flap #2)',
    }],
  });
  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT_DIR, 'youtrack-AFTER-crowdsec.png'), fullPage: true });
});

test('YouTrack BEFORE — session summary', async ({ page }) => {
  const html = renderIssuePage({
    issueId: 'CUBEOS-80',
    summary: 'Add BPI-M4 Zero REV2 WiFi support',
    description: '## Goal\nUpdate the BPI-M4 Zero image build to support REV2 boards.',
    comments: [{
      author: { name: 'Claude' },
      created: Date.now() - 3600000,
      text: 'Session 2026-04-07: REV2 WiFi support added.\\n\\nBlacklisted rtw88, installed CLM blob, updated boot script. Created CUBEOS-81 for baking fixes into image build. Tested AP mode and client mode on physical board — both working.',
    }],
  });
  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT_DIR, 'youtrack-BEFORE-session.png'), fullPage: true });
});

test('YouTrack AFTER — session summary', async ({ page }) => {
  const html = renderIssuePage({
    issueId: 'CUBEOS-80',
    summary: 'Add BPI-M4 Zero REV2 WiFi support',
    description: '## Goal\nUpdate the BPI-M4 Zero image build to support REV2 boards.',
    comments: [{
      author: { name: 'Claude' },
      created: Date.now() - 3600000,
      text: '## Session Summary\n\nREV2 WiFi support added.\n\n- Blacklisted rtw88 driver\n- Installed CLM blob for BCM4345\n- Updated boot script to skip AP IP on WiFi client\n- Created CUBEOS-81 for baking fixes into image build\n\n**Verified:** AP mode and client mode on physical board — both working.\n\n---\n*Session closed — state set to To Verify*',
    }],
  });
  await page.setContent(html, { waitUntil: 'load' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT_DIR, 'youtrack-AFTER-session.png'), fullPage: true });
});
