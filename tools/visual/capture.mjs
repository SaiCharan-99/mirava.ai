// Capture screenshots of the mockup or the app for pixel-level comparison.
// Usage:
//   node capture.mjs --target mockup            -> docs/ui-reference/*.png   (reference images, already committed)
//   node capture.mjs --target app               -> artifacts/visual/app/*.png (app must run with ?visualTest=1 support)
//   node capture.mjs --target app --phase 2     -> only screens whose phase <= 2
//   node capture.mjs --target app --only 02-world,03-world-hover
//   node capture.mjs --target app --base http://localhost:4173
// Env: PW_CHROMIUM_PATH=/path/to/chrome to use a specific Chromium binary.
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const cfg = JSON.parse(fs.readFileSync(path.join(here, "pages.json"), "utf8"));

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith("--")) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : true]);
  return acc;
}, []));
const targetName = args.target || "app";
const target = cfg.targets[targetName];
if (!target) { console.error(`Unknown target ${targetName}`); process.exit(2); }
const only = args.only ? String(args.only).split(",") : null;
const maxPhase = args.phase ? Number(args.phase) : null;
const outDir = path.join(root, target.outDir);
fs.mkdirSync(outDir, { recursive: true });

let base = args.base || target.base;
if (!/^https?:|^file:/.test(base)) base = pathToFileURL(path.join(root, base)).href;

function urlFor(route) {
  if (target.router === "hash") return `${base}${target.query || ""}#${route}`;
  return `${base.replace(/\/$/, "")}/${route}${target.query || ""}`;
}

// Serve Inter / JetBrains Mono locally so screenshots are identical offline and online.
const fontDir = (pkg) => path.join(here, "node_modules", "@fontsource", pkg, "files");
const FONT_FILES = {
  "inter-400": [fontDir("inter"), "inter-latin-400-normal.woff2"],
  "inter-500": [fontDir("inter"), "inter-latin-500-normal.woff2"],
  "inter-600": [fontDir("inter"), "inter-latin-600-normal.woff2"],
  "inter-700": [fontDir("inter"), "inter-latin-700-normal.woff2"],
  "mono-400": [fontDir("jetbrains-mono"), "jetbrains-mono-latin-400-normal.woff2"],
  "mono-500": [fontDir("jetbrains-mono"), "jetbrains-mono-latin-500-normal.woff2"],
  "mono-600": [fontDir("jetbrains-mono"), "jetbrains-mono-latin-600-normal.woff2"],
};
const FONT_CSS = [400, 500, 600, 700].map(w => `@font-face{font-family:'Inter';font-style:normal;font-weight:${w};font-display:block;src:url(https://fonts.gstatic.com/__local/inter-${w}.woff2) format('woff2')}`).join("\n") + "\n" +
  [400, 500, 600].map(w => `@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:${w};font-display:block;src:url(https://fonts.gstatic.com/__local/mono-${w}.woff2) format('woff2')}`).join("\n");

async function main() {
  const browser = await chromium.launch(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {});
  const ctx = await browser.newContext({ viewport: cfg.viewport, deviceScaleFactor: 1, colorScheme: "dark", reducedMotion: "reduce" });
  await ctx.route("https://fonts.googleapis.com/**", r => r.fulfill({ status: 200, contentType: "text/css", body: FONT_CSS }));
  await ctx.route("https://fonts.gstatic.com/__local/**", r => {
    const key = r.request().url().split("/").pop().replace(".woff2", "");
    const f = FONT_FILES[key];
    if (!f || !fs.existsSync(path.join(...f))) return r.fulfill({ status: 404, body: "" });
    return r.fulfill({ status: 200, contentType: "font/woff2", body: fs.readFileSync(path.join(...f)) });
  });

  const log = [];
  let n = 0;
  for (const s of cfg.screens) {
    if (only && !only.includes(s.name)) continue;
    if (maxPhase && s.phase > maxPhase) continue;
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(String(e)));
    page.on("console", m => { if (m.type() === "error" && !/fonts\.g/.test(m.text())) errors.push(m.text()); });
    try {
      await page.goto(urlFor(s.route), { waitUntil: "load", timeout: 30000 });
      await page.evaluate(() => document.fonts && document.fonts.ready);
      await page.waitForTimeout(s.settle ?? 700);
      for (const a of s.actions || []) {
        if (a.eval) await page.evaluate(a.eval);
        if (a.click) await page.click(a.click, { timeout: 5000 });
        if (a.hover) await page.hover(a.hover, { timeout: 5000 });
        if (a.wait) await page.waitForTimeout(a.wait);
      }
      await page.waitForTimeout(250);
      // hide (visibility:hidden) the world canvas & mockup-only items so overlays drawn on top stay visible
      const hideSel = s.hide ?? cfg.defaultHide ?? [];
      if (hideSel.length) await page.evaluate((sels) => { for (const sel of sels) document.querySelectorAll(sel).forEach(el => { el.style.visibility = "hidden"; }); }, hideSel);
      const maskSel = s.mask ?? cfg.defaultMask;
      const mask = maskSel.map(sel => page.locator(sel));
      await page.screenshot({ path: path.join(outDir, `${s.name}.png`), mask, maskColor: "#FF00FF", animations: "disabled" });
      // geometry of named regions (data-testid) for the structural check
      const boxes = await page.evaluate(() => {
        const out = {};
        for (const el of document.querySelectorAll("[data-testid]")) {
          const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
          if (r.width < 1 || r.height < 1 || cs.visibility === "hidden" || cs.display === "none") continue;
          const id = el.getAttribute("data-testid");
          if (out[id]) continue; // first occurrence only
          out[id] = [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
        }
        return out;
      });
      fs.writeFileSync(path.join(outDir, `${s.name}.boxes.json`), JSON.stringify(boxes, null, 1));
      n++;
      log.push({ screen: s.name, ok: true, errors });
      console.log(`✓ ${s.name}${errors.length ? `  (${errors.length} console errors)` : ""}`);
    } catch (e) {
      log.push({ screen: s.name, ok: false, errors: [...errors, String(e)] });
      console.log(`✗ ${s.name}: ${String(e).split("\n")[0]}`);
    }
    await page.close();
  }
  fs.writeFileSync(path.join(outDir, "_capture-log.json"), JSON.stringify({ target: targetName, at: new Date().toISOString(), log }, null, 2));
  await browser.close();
  console.log(`\n${n} screenshots → ${path.relative(root, outDir)}`);
  if (log.some(l => !l.ok || l.errors.length)) process.exitCode = 1;
}
main();
