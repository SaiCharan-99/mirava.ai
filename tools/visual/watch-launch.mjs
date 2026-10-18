// Second viewer for the launch acceptance check: waits for the firework + ticker line, saves a screenshot.
import { chromium } from "playwright";
const out = process.argv[2] ?? "launch-viewer2.png";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto("http://localhost:5174/world");
await page.waitForSelector("[data-testid=launch-dock-item]", { timeout: 60000 });
console.log("viewer2 ready; dock:", await page.$$eval("[data-testid=launch-dock-item]", (e) => e.map((x) => x.dataset.product)));
const t0 = Date.now();
let fxAt = null;
while (Date.now() - t0 < 120000) {
  try {
  const lit = await page.evaluate(() => {
    const c = document.querySelector("[data-testid=launch-fx]");
    if (!c || !c.width) return 0;
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let n = 0; for (let i = 3; i < d.length; i += 400) if (d[i] > 0) n++; return n;
  });
  if (lit > 20 && !fxAt) { fxAt = Date.now(); await page.screenshot({ path: out }); console.log("viewer2: firework visible, lit samples", lit); }
  const tick = await page.$$eval(".tick", (e) => e.map((x) => x.textContent).find((t) => t.includes("launched")) ?? null);
  if (tick && fxAt) { console.log("viewer2 ticker:", tick); break; }
  } catch { /* page reloaded (HMR); keep watching */ }
  await page.waitForTimeout(150);
}
console.log(fxAt ? "viewer2 OK" : "viewer2: no firework seen");
await browser.close();
