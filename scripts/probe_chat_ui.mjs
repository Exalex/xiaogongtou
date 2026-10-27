// _probe_chat_ui.mjs — 对话页双视图重构验收探针（webui-probe 模式：一次跑完，输出落盘）
// 用法：node _probe_chat_ui.mjs（需先 adb forward tcp:8900 tcp:8900）
import { chromium } from "file:///C:/Users/79475/.workbuddy/binaries/node/versions/22.22.2-3/node_modules/@playwright/cli/node_modules/playwright-core/index.mjs";
import { mkdirSync, writeFileSync } from "node:fs";

const OUT = "D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/logs/p0/ui";
mkdirSync(OUT, { recursive: true });
const LINES = [];
const log = (...a) => { const s = a.map(x => typeof x === "string" ? x : JSON.stringify(x)).join(" "); LINES.push(s); console.log(s); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const jsErrors = [];
page.on("pageerror", (e) => jsErrors.push("pageerror: " + String(e).slice(0, 200)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) jsErrors.push("console: " + m.text().slice(0, 200)); });

await page.goto("http://127.0.0.1:8900/chat", { waitUntil: "domcontentloaded" });
await sleep(2000);

const shot = async (name) => { await page.screenshot({ path: OUT + "/" + name + ".png" }); log("shot:", name); };
const state = () => page.evaluate(() => {
  const q = (s) => document.querySelector(s);
  const items = document.querySelectorAll(".sitem");
  return {
    bodyClass: document.body.className,
    cnt: (q("#cnt") || {}).textContent,
    items: items.length,
    moreHidden: q("#more") ? q("#more").hidden : null,
    moreText: q("#more") ? q("#more").textContent : null,
    listVisible: q("#view-list") ? getComputedStyle(q("#view-list")).display !== "none" : null,
    detailVisible: q("#view-detail") ? getComputedStyle(q("#view-detail")).display !== "none" : null,
    detailScrollTop: q("#view-detail") ? Math.round(q("#view-detail").scrollTop) : null,
    title: (q("#streamttl") || {}).textContent,
    turnCount: document.querySelectorAll("#stream .turn").length,
    dsCount: document.querySelectorAll("#stream .ds").length,
    acts: document.querySelectorAll("#stream .abtn").length,
    listScrollTop: q("#view-list") ? Math.round(q("#view-list").scrollTop) : null,
    backVisible: q("#back") ? getComputedStyle(q("#back")).display !== "none" : null,
  };
});

// 1) 首屏 = 列表视图
log("=== 1 首屏(列表) ===", await state());
await shot("01-list");

// 2) 点一条「微博」会话 → 应瞬间切到详情视图（无需长滚动）
const pickIdx = await page.evaluate(() => {
  const items = [...document.querySelectorAll(".sitem")];
  const i = items.findIndex(el => ((el.querySelector(".stask") || {}).textContent || "").includes("微博"));
  return i >= 0 ? i : 2;
});
await page.locator(".sitem").nth(pickIdx).click();
await sleep(1200);
log("=== 2 点会话#" + (pickIdx + 1) + " → 详情（应滚动0，直接可见） ===", await state());
await shot("02-detail");

// 3) 详情内「‹ 历史」返回
await page.locator("#back").click();
await sleep(500);
log("=== 3 「‹ 历史」返回 ===", await state());

// 4) 再进详情，用浏览器后退（= 安卓返回键语义）
await page.locator(".sitem").nth(Math.min(pickIdx + 1, 19)).click();
await sleep(900);
log("=== 4a 再进详情 ===", await state());
await page.goBack();
await sleep(600);
log("=== 4b 浏览器后退 → 列表 ===", await state());

// 5) 滚到列表底部 → 加载更多（20 → 40）
await page.evaluate(() => { const v = document.querySelector("#view-list"); v.scrollTop = v.scrollHeight; });
await sleep(400);
await shot("03-list-bottom");
await page.locator("#more").click();
await sleep(1300);
log("=== 5 加载更多 ===", await state());
await page.evaluate(() => { const v = document.querySelector("#view-list"); v.scrollTop = v.scrollHeight; });
await sleep(300);
await shot("04-more-loaded");

// 6) 搜索过滤
await page.fill("#q", "微博");
await sleep(1000);
log("=== 6 搜索「微博」 ===", await state());
await shot("05-search");

// 7) 搜索态下点一条 → 详情里搜到的内容也在
await page.locator(".sitem").nth(0).click();
await sleep(1000);
log("=== 7 搜索态进入详情 ===", await state());
await shot("06-search-detail");

// 8) 宽屏（桌面分栏）
const wide = await browser.newPage({ viewport: { width: 1200, height: 800 } });
await wide.goto("http://127.0.0.1:8900/chat", { waitUntil: "domcontentloaded" });
await sleep(1800);
await wide.locator(".sitem").nth(0).click();
await sleep(1000);
const wideState = await wide.evaluate(() => ({
  bodyClass: document.body.className,
  listVisible: getComputedStyle(document.querySelector("#view-list")).display !== "none",
  detailVisible: getComputedStyle(document.querySelector("#view-detail")).display !== "none",
  listWidth: Math.round(document.querySelector("#view-list").getBoundingClientRect().width),
  backVisible: getComputedStyle(document.querySelector("#back")).display !== "none",
}));
log("=== 8 宽屏分栏 ===", wideState);
await wide.screenshot({ path: OUT + "/07-desktop.png" });
log("shot: 07-desktop");

log("=== JS errors ===", jsErrors.length ? jsErrors : "none");
writeFileSync(OUT + "/probe-report.txt", LINES.join("\n"), "utf8");
await browser.close();
console.log("DONE");
