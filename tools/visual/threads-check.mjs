// World threads check (Phase I): opening a profile draws one violet line per relationship on the map; closing removes
// them. node threads-check.mjs [base]   (app running on :5173, fixture mode)
import { chromium } from "playwright";

const base = process.argv[2] || "http://localhost:5173";
const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(`${base}/world?visualTest=1`, { waitUntil: "load" });
await page.waitForFunction(() => window.__ll && window.__ll.featured() > 0, null, { timeout: 20000 });
const id = await page.evaluate(() => window.__ll.featured());
await page.evaluate((a) => window.__ll.openAgent(a, "relations"), id);
await page.waitForTimeout(1500);
const open = await page.evaluate(() => window.__ll.threads());
const listed = await page.locator("[data-testid=profile-drawer] .list .item").count();
await page.screenshot({ path: "../../artifacts/visual/world-threads.png" });
await page.locator("[data-testid=profile-drawer] .btn.ghost").click();
await page.waitForTimeout(600);
const closed = await page.evaluate(() => window.__ll.threads());
await browser.close();
console.log(JSON.stringify({ agent: id, lines_open: open, relations_listed: listed, lines_after_close: closed }));
if (!(open > 0 && closed === 0)) { console.error("✗ threads check failed"); process.exit(1); }
console.log("✓ threads check passed");
