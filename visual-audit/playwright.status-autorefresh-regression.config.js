const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests',
  testMatch: ['status-autorefresh-regression.spec.js'],
  timeout: 90000,
  reporter: [['list']],
  use: {
    headless: true,
    viewport: { width: 1600, height: 1100 },
    ignoreHTTPSErrors: true,
  },
  outputDir: './reports/status-autorefresh-regression',
});
