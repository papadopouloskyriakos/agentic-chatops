const STATUS_URL = 'https://kyriakos.papadopoulos.tech/status/';

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  tablet: { width: 768, height: 1024 },
  mobile: { width: 375, height: 812 },
};

async function goToStatus(page) {
  await page.goto(STATUS_URL, { waitUntil: 'load', timeout: 30000 });
  await page.waitForSelector('#mh-graph svg circle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000);
}

function collectConsoleErrors(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  return errors;
}

function collectNetworkErrors(page) {
  const errors = [];
  page.on('response', res => {
    if (res.status() >= 400 && !res.url().includes('favicon'))
      errors.push({ url: res.url(), status: res.status() });
  });
  return errors;
}

module.exports = { STATUS_URL, VIEWPORTS, goToStatus, collectConsoleErrors, collectNetworkErrors };
