// Theme contrast audit: screenshots every screen in pages.json (plus Survey Room states) in Dark and Light
// theme and checks every visible text element against WCAG AA, using the real rendered background pixels
// (so text over canvas, gradients and glass overlays is measured too).
// Usage: node contrast.mjs [--base http://localhost:5173] [--only 01-globe,02-world] [--theme light]
// Output: artifacts/visual/contrast/<theme>/<screen>.png + report.json. Exit code 1 on any failure.
import { chromium } from "playwright";
import { PNG } from "pngjs";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const cfg = JSON.parse(fs.readFileSync(path.join(here, "pages.json"), "utf8"));
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith("--")) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : true]);
  return acc;
}, []));
const base = String(args.base || "http://localhost:5173").replace(/\/$/, "");
const only = args.only ? String(args.only).split(",") : null;
const themes = args.theme ? [String(args.theme)] : ["dark", "light"];
const outRoot = path.join(root, "artifacts/visual/contrast");

const EXTRA = [
  { name: "40-survey-builder", route: "insights/polls/survey/new" },
  { name: "41-survey-recruiting", route: "insights/polls/survey/sv-demo", actions: [{ eval: "window.__ll.surveyRoom('sv-demo','recruiting',0)" }, { wait: 1500 }] },
  { name: "42-survey-discussion", route: "insights/polls/survey/sv-demo", actions: [{ eval: "window.__ll.surveyRoom('sv-demo','discussion',0.6)" }, { wait: 1500 }] },
  { name: "43-survey-results", route: "insights/polls/survey/sv-demo", actions: [{ eval: "window.__ll.surveyRoom('sv-demo','results',1)" }, { wait: 1500 }] },
];
const screens = [...cfg.screens, ...EXTRA].filter((s) => !only || only.includes(s.name));

/** In-page: list visible text elements with their colour (alpha × cumulative opacity) and box. */
function collect() {
  const out = [];
  const parse = (c) => {
    const m = c.match(/[\d.]+/g);
    if (!m) return [0, 0, 0, 0];
    const v = m.map(Number);
    // color-mix() resolves to color(srgb r g b / a) with 0–1 channels
    return c.startsWith("color(") ? [v[0] * 255, v[1] * 255, v[2] * 255, v[3] ?? 1] : v;
  };
  const all = document.querySelectorAll("body *");
  for (const el of all) {
    if (["SCRIPT", "STYLE", "NOSCRIPT", "CANVAS", "svg", "OPTION"].includes(el.tagName)) continue;
    const isSvgText = el instanceof SVGTextElement || el instanceof SVGTSpanElement;
    const own = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim()).join(" ");
    if (!own) continue;
    // emoji-only / symbol-only strings are decorative icons coloured by the font, not by CSS
    if (!/[\p{L}\p{N}]/u.test(own)) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility !== "visible" || cs.display === "none") continue;
    if (el.closest("[disabled],[aria-disabled=true],.hidden")) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.right <= 0 || r.top >= innerHeight || r.left >= innerWidth) continue;
    let op = 1;
    for (let p = el; p && p.nodeType === 1; p = p.parentElement) op *= Number(getComputedStyle(p).opacity);
    if (op < 0.05) continue;
    // clipped by an overflow ancestor (e.g. closed drawer)? skip if box is fully outside it
    let clipped = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const pc = getComputedStyle(p);
      if (pc.overflow !== "visible" || pc.transform !== "none") {
        const pr = p.getBoundingClientRect();
        if (r.left >= pr.right - 1 || r.right <= pr.left + 1 || r.top >= pr.bottom - 1 || r.bottom <= pr.top + 1) { clipped = true; break; }
      }
    }
    if (clipped) continue;
    // covered by another layer (e.g. the globe intro over the world)? skip
    const cx = Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2)), cy = Math.min(innerHeight - 1, Math.max(0, r.top + r.height / 2));
    const top = document.elementFromPoint(cx, cy);
    if (top && top !== el && !el.contains(top) && !top.contains(el)) continue;
    // 3D-scene labels (drei <Html>, pointer-events:none) can sit under a speech bubble with a higher z-index
    const zOf = (n) => { for (let p = n; p && p !== document.body; p = p.parentElement) { const z = parseInt(getComputedStyle(p).zIndex); if (!isNaN(z)) return z; } return 0; };
    const under = [...document.querySelectorAll(".survey-bubble")].some((b) => {
      if (b === el || b.contains(el)) return false;
      const br = b.getBoundingClientRect();
      return cx >= br.left && cx <= br.right && cy >= br.top && cy <= br.bottom && zOf(b) > zOf(el);
    });
    if (under) continue;
    const col = parse(isSvgText ? cs.fill : cs.color);
    const a = (col[3] ?? 1) * op * (isSvgText ? Number(cs.fillOpacity || 1) : 1);
    const size = parseFloat(cs.fontSize), weight = Number(cs.fontWeight) || 400;
    out.push({
      text: own.slice(0, 60), rgb: col.slice(0, 3), a, size, weight,
      box: [r.left, r.top, r.width, r.height].map(Math.round),
      sel: el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + (typeof el.className === "string" && el.className ? "." + el.className.trim().split(/\s+/).join(".") : ""),
      tid: el.closest("[data-testid]")?.getAttribute("data-testid") || "",
    });
  }
  return out;
}

const lum = ([r, g, b]) => {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const ratio = (x, y) => { const [a, b] = [lum(x), lum(y)].sort((p, q) => q - p); return (a + 0.05) / (b + 0.05); };

/** Median background colour under a box, from the screenshot taken with all text made transparent. */
function bgUnder(png, [x, y, w, h]) {
  const px = [];
  const x0 = Math.max(0, x), y0 = Math.max(0, y), x1 = Math.min(png.width, x + w), y1 = Math.min(png.height, y + h);
  const sx = Math.max(1, Math.floor((x1 - x0) / 12)), sy = Math.max(1, Math.floor((y1 - y0) / 6));
  for (let j = y0; j < y1; j += sy) for (let i = x0; i < x1; i += sx) {
    const o = (j * png.width + i) * 4;
    px.push([png.data[o], png.data[o + 1], png.data[o + 2]]);
  }
  if (!px.length) return null;
  px.sort((p, q) => lum(p) - lum(q));
  return px[Math.floor(px.length / 2)];
}

async function main() {
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
  const report = [];
  let failures = 0;
  for (const theme of themes) {
    const dir = path.join(outRoot, theme);
    fs.mkdirSync(dir, { recursive: true });
    const ctx = await browser.newContext({ viewport: cfg.viewport, deviceScaleFactor: 1, reducedMotion: "reduce" });
    await ctx.addInitScript((t) => { try { localStorage.setItem("mirava_theme", t); localStorage.setItem("mirava_seen_globe", "1"); } catch { /* */ } }, theme);
    for (const s of screens) {
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
      try {
        await page.goto(`${base}/${s.route}?visualTest=1`, { waitUntil: "load", timeout: 30000 });
        await page.evaluate((t) => { if (t === "light") document.documentElement.dataset.theme = "light"; else delete document.documentElement.dataset.theme; }, theme);
        await page.waitForTimeout(s.settle ?? 900);
        for (const a of s.actions || []) {
          if (a.eval) await page.evaluate(a.eval);
          if (a.click) await page.click(a.click, { timeout: 5000 });
          if (a.hover) await page.hover(a.hover, { timeout: 5000 });
          if (a.wait) await page.waitForTimeout(a.wait);
        }
        await page.evaluate((t) => { if (t === "light") document.documentElement.dataset.theme = "light"; else delete document.documentElement.dataset.theme; }, theme);
        await page.waitForTimeout(400);
        const shot = path.join(dir, `${s.name}.png`);
        await page.screenshot({ path: shot, animations: "disabled" });
        const items = await page.evaluate(collect);
        await page.addStyleTag({ content: "*,*::before,*::after{color:transparent!important;text-shadow:none!important;-webkit-text-fill-color:transparent!important;caret-color:transparent!important} svg text,svg tspan{fill:transparent!important;stroke:transparent!important}" });
        await page.waitForTimeout(80);
        const bgPng = PNG.sync.read(await page.screenshot({ animations: "disabled" }));
        const bad = [];
        for (const it of items) {
          const bg = bgUnder(bgPng, it.box);
          if (!bg) continue;
          const fg = it.rgb.map((c, i) => c * it.a + bg[i] * (1 - it.a));
          const cr = ratio(fg, bg);
          const large = it.size >= 24 || (it.size >= 18.66 && it.weight >= 700);
          const need = large ? 3 : 4.5;
          if (cr < need) bad.push({ ...it, bg, cr: Math.round(cr * 100) / 100, need, invisible: cr < 1.5 });
        }
        failures += bad.length;
        report.push({ theme, screen: s.name, checked: items.length, failures: bad, errors });
        const inv = bad.filter((b) => b.invisible).length;
        console.log(`${bad.length ? "✗" : "✓"} ${theme.padEnd(5)} ${s.name.padEnd(28)} ${items.length} texts · ${bad.length} below AA${inv ? ` (${inv} nearly invisible)` : ""}${errors.length ? ` · ${errors.length} console errors` : ""}`);
        for (const b of bad.slice(0, args.verbose ? 999 : 6)) console.log(`     ${b.cr}:1 (need ${b.need}) "${b.text}" ${b.sel} [${b.tid}] fg=${b.rgb} bg=${b.bg}`);
      } catch (e) {
        failures++;
        report.push({ theme, screen: s.name, error: String(e) });
        console.log(`✗ ${theme} ${s.name}: ${String(e).split("\n")[0]}`);
      }
      await page.close();
    }
    await ctx.close();
  }
  fs.writeFileSync(path.join(outRoot, "report.json"), JSON.stringify(report, null, 1));
  await browser.close();
  console.log(`\n${failures} contrast failures → artifacts/visual/contrast/report.json`);
  if (failures) process.exitCode = 1;
}
main();
