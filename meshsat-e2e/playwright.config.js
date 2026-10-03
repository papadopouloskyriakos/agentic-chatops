const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 30000,
  retries: 1,
  fullyParallel: false,
  reporter: [['list'], ['html', { outputFolder: 'report', open: 'never' }]],
  use: {
    baseURL: 'http://nl-mule01-wireless:6050',
    headless: true,
    viewport: { width: 1280, height: 800 },
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 10000,
  },
});
