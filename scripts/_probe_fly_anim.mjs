// _probe_fly_anim.mjs — 对话页「提交飞行动画」探针（webui-probe 模式：一次跑完，输出落盘）
// 用法：node _probe_fly_anim.mjs（需先 adb forward tcp:18400 tcp:8900）
import { chromium } from "file:///C:/Users/79475/.workbuddy/binaries/node/versions/22.22.2-3/node_modules/@playwright/cli/node_modules/playwright-core/index.mjs";

const OUT = "D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/logs/entry_ui";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const jsErrors = [];
page.on("pageerror", (e) => jsErrors.push("pageerror: " + String(e).slice(0, 160)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) jsErrors.push("console: " + m.text().slice(0, 160)); });

await page.goto("http://127.0.0.1:18400/chat", { waitUntil: "domcontentloaded" });
await sleep(1800);

// 安全任务（代词拦截：0 点击 0 输入干净停）
await page.fill("#task", "给那个发 test");
await sleep(150);

const samples = [];
let shotTaken = false;
const back = (async () => {
  for (let i = 0; i < 26; i++) {
    const s = await page.evaluate(() => {
      const el = document.querySelector(".flypill");
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), op: getComputedStyle(el).opacity, txt: el.textContent.slice(0, 14) };
    });
    samples.push({ ms: i * 55, pill: s });
    if (s && !shotTaken) {
      shotTaken = true;
      try { await page.screenshot({ path: OUT + "/v17_web_fly.png" }); } catch (e) {}
    }
    await sleep(55);
  }
})();
await page.click("#go");
await back;

const hits = samples.filter((x) => x.pill);
console.log("pill seen in", hits.length, "of", samples.length, "samples; screenshot:", shotTaken);
if (hits.length) {
  console.log("first:", JSON.stringify(hits[0]));
  console.log("mid  :", JSON.stringify(hits[Math.floor(hits.length / 2)]));
  console.log("last :", JSON.stringify(hits[hits.length - 1]));
}
await page.screenshot({ path: OUT + "/v17_web_done.png" });
console.log("JS errors:", JSON.stringify(jsErrors));
await browser.close();
