const { chromium } = require('playwright-core');
const OUT = process.argv[2] || 'D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/logs/console_ui.png';
const OUT2 = process.argv[3] || 'D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/logs/console_ui_dbg.png';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 420, height: 880 }, deviceScaleFactor: 2 });
  await page.goto('http://127.0.0.1:8902/', { waitUntil: 'networkidle', timeout: 25000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: OUT });

  // 1) 调试按钮状态（初始应因 /api/debug = on 而高亮）
  const cls0 = await page.evaluate(() => document.getElementById('dbgbtn').className);
  console.log('dbgbtn class (initial):', cls0);

  // 2) 点击 → 切换
  await page.click('#dbgbtn');
  await page.waitForTimeout(1000);
  const cls1 = await page.evaluate(() => document.getElementById('dbgbtn').className);
  console.log('dbgbtn class (after click):', cls1);
  await page.screenshot({ path: OUT2 });

  // 3) 再点回
  await page.click('#dbgbtn');
  await page.waitForTimeout(800);
  const cls2 = await page.evaluate(() => document.getElementById('dbgbtn').className);
  console.log('dbgbtn class (after 2nd click):', cls2);

  // 4) 打开链路查看
  await page.click('#btn-trace-done').catch(() => {});
  await page.waitForTimeout(1200);
  const traceShown = await page.evaluate(() => document.getElementById('tracebox').className);
  const traceText = await page.evaluate(() => (document.getElementById('tracepre').textContent || '').slice(0, 300));
  console.log('tracebox:', traceShown);
  console.log('tracepre head:', traceText.replace(/\s+/g, ' ').slice(0, 260));
  await page.screenshot({ path: OUT.replace('.png', '_trace.png') });

  await browser.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
