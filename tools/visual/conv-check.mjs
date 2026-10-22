// Prod check: open an agent's profile → Conversations, click a chat, expect the transcript. node conv-check.mjs [base] [agent]
import { chromium } from "playwright";
const base = process.argv[2] || "https://mirava-ai-hack.web.app", aid = Number(process.argv[3] || 11);
const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => m.type() === "error" && console.log("console:", m.text()));
page.on("response", (r) => r.url().includes("/conversations") && console.log("net:", r.status(), r.url()));
await page.goto(`${base}/world`, { waitUntil: "load" });
await page.waitForFunction(() => window.__ll, null, { timeout: 30000 });
await page.waitForTimeout(4000);
await page.evaluate((a) => window.__ll.openAgent(a, "conversations"), aid);
await page.waitForTimeout(5000);
const rows = page.locator("[data-testid=conversation-list] button");
console.log("rows:", await rows.count(), "detail before:", await page.locator("[data-testid=conversation-detail]").count());
await page.screenshot({ path: "../../artifacts/prod/conv-before.png" });
if (await rows.count() > 1) { await rows.nth(1).click(); await page.waitForTimeout(4000); }
console.log("detail after:", await page.locator("[data-testid=conversation-detail]").count(), "summary:", await page.locator("[data-testid=conversation-summary]").count());
console.log((await page.locator("[data-testid=profile-drawer]").innerText()).slice(0, 1500));
await page.screenshot({ path: "../../artifacts/prod/conv-after.png" });
await browser.close();
