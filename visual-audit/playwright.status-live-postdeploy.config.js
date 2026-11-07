const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests',
  testMatch: ['status-live-postdeploy.spec.js'],
  timeout: 60000,
  reporter: [['list']],
  use: {
    headless: true,
    viewport: { width: 1600, height: 1100 },
    ignoreHTTPSErrors: true,
  },
  outputDir: './reports/status-live-postdeploy',
});
