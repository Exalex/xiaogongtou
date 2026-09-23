const { chromium } = require('playwright-core');
const LOGS = 'D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/logs/';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 420, height: 880 }, deviceScaleFactor: 2 });
  await page.goto('http://127.0.0.1:8902/', { waitUntil: 'networkidle', timeout: 25000 });
  await page.waitForTimeout(1500);
  const hk = await page.evaluate(() => document.getElementById('hkbtn').className);
  const dbg = await page.evaluate(() => document.getElementById('dbgbtn').className);
  console.log('hkbtn class:', hk, '| dbgbtn class:', dbg);
  await page.screenshot({ path: LOGS + 'console_ui_hotkey.png' });
  await browser.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
