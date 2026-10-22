const { defineConfig } = require('@playwright/test');
const path = require('path');

require('dotenv').config({ path: path.resolve(__dirname, '../.env') });

module.exports = defineConfig({
  testDir: './tests',
  timeout: 60_000,
  retries: 0,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: 'off',
    video: 'off',
    ignoreHTTPSErrors: true,
  },
  projects: [
    { name: 'outcomes', testMatch: 'outcomes-block.spec.js' },
  ],
});
