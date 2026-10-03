#!/usr/bin/env node
/**
 * Generates a side-by-side HTML comparison report of baseline vs improved screenshots.
 * Usage: node helpers/compare-report.js
 */
const fs = require('fs');
const path = require('path');

const BASELINE_DIR = path.join(__dirname, '..', 'baselines');
const IMPROVED_DIR = path.join(__dirname, '..', 'improved');
const REPORT_PATH = path.join(__dirname, '..', 'report', 'comparison.html');

function findPngs(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const sub of ['matrix', 'youtrack']) {
    const subDir = path.join(dir, sub);
    if (!fs.existsSync(subDir)) continue;
    for (const f of fs.readdirSync(subDir)) {
      if (f.endsWith('.png')) {
        results.push({ category: sub, name: f, path: path.join(subDir, f) });
      }
    }
  }
  return results;
}

function buildReport() {
  const baselines = findPngs(BASELINE_DIR);
  const improved = findPngs(IMPROVED_DIR);

  // Match baselines to improved by name
  const pairs = [];
  for (const b of baselines) {
    const match = improved.find(i => i.category === b.category && i.name === b.name);
    pairs.push({
      category: b.category,
      name: b.name,
      baseline: b.path,
      improved: match?.path || null,
    });
  }
  // Add improved-only entries
  for (const i of improved) {
    if (!baselines.find(b => b.category === i.category && b.name === i.name)) {
      pairs.push({ category: i.category, name: i.name, baseline: null, improved: i.path });
    }
  }

  pairs.sort((a, b) => `${a.category}/${a.name}`.localeCompare(`${b.category}/${b.name}`));

  const rows = pairs.map(p => {
    const baseImg = p.baseline
      ? `<img src="file://${p.baseline}" style="max-width:100%;border:1px solid #ddd;border-radius:4px;">`
      : '<div style="color:#999;text-align:center;padding:40px;">No baseline</div>';
    const impImg = p.improved
      ? `<img src="file://${p.improved}" style="max-width:100%;border:1px solid #ddd;border-radius:4px;">`
      : '<div style="color:#999;text-align:center;padding:40px;">Not yet captured</div>';

    return `
      <tr>
        <td style="padding:8px;vertical-align:top;">
          <div style="font-weight:600;margin-bottom:4px;">${p.category}/${p.name}</div>
          ${baseImg}
        </td>
        <td style="padding:8px;vertical-align:top;">
          <div style="font-weight:600;margin-bottom:4px;">${p.category}/${p.name}</div>
          ${impImg}
        </td>
      </tr>`;
  }).join('\n');

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Visual Audit Comparison Report</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f8f9fa; }
    h1 { font-size: 20px; color: #333; margin-bottom: 4px; }
    .meta { color: #666; font-size: 13px; margin-bottom: 20px; }
    table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    th { background: #f0f2f5; padding: 12px; text-align: left; font-size: 14px; border-bottom: 2px solid #ddd; }
    td { width: 50%; border-bottom: 1px solid #eee; }
    .summary { background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .stat { display: inline-block; margin-right: 24px; }
    .stat-val { font-size: 24px; font-weight: 700; color: #6638f0; }
    .stat-label { font-size: 12px; color: #666; }
  </style>
</head>
<body>
  <h1>Visual Audit Comparison Report</h1>
  <div class="meta">Generated: ${new Date().toISOString()}</div>
  <div class="summary">
    <span class="stat"><span class="stat-val">${pairs.length}</span><br><span class="stat-label">Total captures</span></span>
    <span class="stat"><span class="stat-val">${pairs.filter(p => p.baseline && p.improved).length}</span><br><span class="stat-label">Matched pairs</span></span>
    <span class="stat"><span class="stat-val">${pairs.filter(p => p.baseline && !p.improved).length}</span><br><span class="stat-label">Baseline only</span></span>
    <span class="stat"><span class="stat-val">${pairs.filter(p => !p.baseline && p.improved).length}</span><br><span class="stat-label">Improved only</span></span>
  </div>
  <table>
    <thead>
      <tr><th>BASELINE (before)</th><th>IMPROVED (after)</th></tr>
    </thead>
    <tbody>
      ${rows}
    </tbody>
  </table>
</body>
</html>`;

  fs.mkdirSync(path.dirname(REPORT_PATH), { recursive: true });
  fs.writeFileSync(REPORT_PATH, html);
  console.log(`Comparison report: ${REPORT_PATH}`);
  console.log(`  ${pairs.length} captures, ${pairs.filter(p => p.baseline && p.improved).length} matched pairs`);
}

buildReport();
