// @ts-check
const { test } = require('@playwright/test');
const path = require('path');
const fs = require('fs');
const https = require('https');
const { renderIssuePage } = require('../helpers/youtrack-renderer');

require('dotenv').config({ path: path.resolve(__dirname, '../../.env') });

const YT_URL = 'https://youtrack.example.net';
const YT_TOKEN = process.env.YT_TOKEN;
const MODE = process.env.AUDIT_MODE || 'baseline';
const OUT_DIR = path.resolve(__dirname, '..', MODE === 'improved' ? 'improved/youtrack' : 'baselines/youtrack');

/** YouTrack API helper */
async function ytApi(urlPath) {
  const url = `${YT_URL}/api${urlPath}`;
  return new Promise((resolve, reject) => {
    https.get(url, {
      rejectUnauthorized: false,
      headers: { Authorization: `Bearer ${YT_TOKEN}`, Accept: 'application/json' },
    }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error(`YT parse: ${data.slice(0, 200)}`)); }
      });
    }).on('error', reject);
  });
}

async function findIssues(query, top = 3) {
  const encoded = encodeURIComponent(query);
  return ytApi(`/issues?query=${encoded}&$top=${top}&fields=id,idReadable,summary,description`);
}

async function getComments(issueId) {
  return ytApi(`/issues/${issueId}/comments?fields=id,text,author(name),created`);
}

async function getIssue(issueId) {
  return ytApi(`/issues/${issueId}?fields=id,idReadable,summary,description`);
}

// ── Targets ──
const TARGETS = [
  { name: 'crowdsec-issue',    query: 'project: IFRNLLEI01PRD summary: CrowdSec sort by: created desc' },
  { name: 'librenms-issue',    query: 'project: IFRNLLEI01PRD summary: LibreNMS sort by: created desc' },
  { name: 'prometheus-issue',  query: 'project: IFRNLLEI01PRD summary: Prometheus sort by: created desc' },
  { name: 'security-issue',    query: 'project: IFRNLLEI01PRD summary: Security sort by: created desc' },
  { name: 'session-cubeos',    issueId: 'CUBEOS-74' },
  { name: 'triage-result',     issueId: 'IFRNLLEI01PRD-355' },
  { name: 'feature-completion', issueId: 'IFRNLLEI01PRD-318' },
  { name: 'dev-task',          query: 'project: CUBEOS sort by: created desc' },
  { name: 'recent-infra',      issueId: 'IFRNLLEI01PRD-374' },
];

test.beforeAll(() => {
  if (!YT_TOKEN) throw new Error('YT_TOKEN not set in .env');
  fs.mkdirSync(OUT_DIR, { recursive: true });
});

for (const target of TARGETS) {
  test(`capture ${target.name}`, async ({ page }) => {
    let issueId = target.issueId;

    if (!issueId && target.query) {
      const issues = await findIssues(target.query, 1);
      if (!Array.isArray(issues) || issues.length === 0) {
        console.log(`  SKIP ${target.name}: no issues found`);
        test.skip();
        return;
      }
      issueId = issues[0].idReadable;
    }

    console.log(`  Fetching ${target.name} — ${issueId}`);

    // Fetch issue details + comments
    const [issue, comments] = await Promise.all([
      getIssue(issueId),
      getComments(issueId),
    ]);

    const html = renderIssuePage({
      issueId: issue.idReadable || issueId,
      summary: issue.summary || '(no summary)',
      description: issue.description,
      comments: Array.isArray(comments) ? comments : [],
      auditNotes: [
        `Mode: ${MODE} | Captured: ${new Date().toISOString()}`,
        `${Array.isArray(comments) ? comments.length : 0} comment(s)`,
        `Description: ${(issue.description || '').length} chars`,
      ],
    });

    await page.setContent(html, { waitUntil: 'load' });
    await page.waitForTimeout(500);

    const outPath = path.join(OUT_DIR, `${target.name}-${issueId}.png`);
    await page.screenshot({ path: outPath, fullPage: true });
    console.log(`  Saved: ${outPath}`);
  });
}

// ── Comment quality audit (no browser needed) ──
test('audit comment formatting quality', async () => {
  const auditResults = [];
  const issuesToAudit = ['IFRNLLEI01PRD-355', 'IFRNLLEI01PRD-318', 'CUBEOS-74', 'CUBEOS-73'];

  for (const issueId of issuesToAudit) {
    try {
      const comments = await getComments(issueId);
      if (!Array.isArray(comments)) continue;
      for (const comment of comments) {
        const text = comment.text || '';
        const issues = [];

        if (/^===\s|===\s*$/m.test(text)) issues.push('raw-tool-output-markers');
        if (/^\s{2,}\S+\s+\S+\s+\S+/m.test(text)) issues.push('possible-ascii-table');
        if (/\\n/.test(text)) issues.push('escaped-newlines');
        if (!text.startsWith('##') && !text.startsWith('**')) issues.push('no-heading-or-bold-start');
        if (text.length > 500 && !text.includes('|')) issues.push('long-comment-no-table');
        if (text.length > 500 && !text.includes('\n\n') && !text.includes('\\n\\n')) issues.push('long-comment-no-paragraphs');
        if (/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text)) issues.push('raw-iso-timestamp');

        auditResults.push({
          issue: issueId,
          commentId: comment.id,
          author: comment.author?.name,
          length: text.length,
          hasMarkdown: /[*#|`\-]/.test(text),
          issues,
          preview: text.slice(0, 120).replace(/\n/g, '\\n'),
        });
      }
    } catch (err) {
      console.error(`  Failed to audit ${issueId}: ${err.message}`);
    }
  }

  const reportPath = path.join(OUT_DIR, 'comment-quality-audit.json');
  fs.writeFileSync(reportPath, JSON.stringify(auditResults, null, 2));
  console.log(`\nComment Quality Audit (${auditResults.length} comments):`);
  for (const r of auditResults) {
    const flags = r.issues.length > 0 ? ` [${r.issues.join(', ')}]` : ' [OK]';
    console.log(`  ${r.issue} by ${r.author}: ${r.length} chars${flags}`);
  }
});
