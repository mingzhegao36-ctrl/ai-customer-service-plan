const { chromium } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const output = path.resolve(__dirname, '../../../审计/前端-v0.3-证据');
fs.mkdirSync(output, { recursive: true });
const base = process.env.PREVIEW_URL || 'http://127.0.0.1:5173';
(async () => {
  const browser = await chromium.launch({ channel: process.platform === 'win32' ? 'msedge' : undefined, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const report = { date: new Date().toISOString(), browser: browser.version(), source: base, errors: [], samples: [] };
  page.on('pageerror', error => report.errors.push(error.message));
  try {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      for (const route of ['overview', 'chat', 'history', 'assistant', 'connections', 'usage', 'tasks', 'settings', 'modules', 'login']) {
        await page.goto(`${base}/#/${route}`);
        await page.locator('h1').waitFor();
        await page.screenshot({ path: path.join(output, `${route}-${width}.png`), fullPage: true });
        report.samples.push({ route, width, ...await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, title: document.title, height: document.documentElement.scrollHeight })) });
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${base}/#/overview`);
    await page.getByRole('button', { name: '搜索页面与会话', exact: true }).click();
    await page.getByRole('combobox').fill('会话');
    await page.screenshot({ path: path.join(output, '快捷导航-1440.png') });
    const overflow = report.samples.filter(item => item.scrollWidth > item.width);
    if (overflow.length || report.errors.length) throw new Error(JSON.stringify({ overflow, errors: report.errors }));
  } catch (error) {
    report.failure = String(error.stack);
    process.exitCode = 1;
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(output, '视觉检查.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  }
})();
