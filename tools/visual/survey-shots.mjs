// Survey Room review screenshots (not gated; no reference exists): node survey-shots.mjs [base]
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, "../../artifacts/visual/survey-room");
const base = process.argv[2] || "http://localhost:5173";
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const shots = [
  ["builder", "/insights/polls/survey/new?visualTest=1", null],
  ["recruiting", "/insights/polls/survey/sv-demo?visualTest=1", ["recruiting", 0]],
  ["discussion", "/insights/polls/survey/sv-demo?visualTest=1", ["discussion", 0.6]],
  ["ballot", "/insights/polls/survey/sv-demo?visualTest=1", ["ballot", 0.5]],
  ["results", "/insights/polls/survey/sv-demo?visualTest=1", ["results", 1]],
  ["light", "/insights/polls/survey/sv-demo?visualTest=1", ["discussion", 0.6], true],
];
for (const [name, route, freeze, light] of shots) {
  await page.goto(base + route, { waitUntil: "load" });
  await page.waitForTimeout(1200);
  if (light) await page.evaluate(() => { document.documentElement.dataset.theme = "light"; });
  if (freeze) await page.evaluate(([p, g]) => window.__ll.surveyRoom("sv-demo", p, g), freeze);
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(out, `${name}.png`) });
  console.log("✓", name);
}
await browser.close();
