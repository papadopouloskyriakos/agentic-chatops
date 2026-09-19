const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests',
  testMatch: ['status-visual-indicators.spec.js'],
  timeout: 120000,
  reporter: [['list']],
  use: {
    headless: true,
    viewport: { width: 1600, height: 1100 },
    ignoreHTTPSErrors: true,
  },
  outputDir: './reports/status-visual-indicators',
});
