const { defineConfig } = require('@playwright/test');
const path = require('path');

require('dotenv').config({ path: path.resolve(__dirname, '../.env') });

module.exports = defineConfig({
  testDir: './tests',
  timeout: 120_000,
  retries: 0,
  fullyParallel: false,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'report', open: 'never' }],
  ],
  use: {
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: 'off',
    video: 'off',
    ignoreHTTPSErrors: true,
  },
  projects: [
    { name: 'matrix', testMatch: 'matrix-visual.spec.js' },
    { name: 'youtrack', testMatch: 'youtrack-visual.spec.js' },
    { name: 'comparison', testMatch: 'synthetic-comparison.spec.js' },
    { name: 'status-page', testMatch: 'status-page-*.spec.js' },
    { name: 'status-firefox', testMatch: 'status-page-dom.spec.js', use: { browserName: 'firefox' } },
    { name: 'status-webkit', testMatch: 'status-page-dom.spec.js', use: { browserName: 'webkit' } },
    { name: 'meshsat-spectrum', testMatch: 'meshsat-spectrum.spec.js' },
    { name: 'meshsat-spectrum-mil', testMatch: 'meshsat-spectrum-mil.spec.js' },
  ],
});
