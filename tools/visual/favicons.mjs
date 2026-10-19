// Generate the favicon set from the header logo mark (.logo-mark: 26 px rounded square, conic gradient
// teal → blue → violet from 210°, dark centre dot). Usage: node favicons.mjs → web/public/*
import { chromium } from "playwright";
import { PNG } from "pngjs";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, "../../web/public");
const STOPS = ["#2dd4bf", "#60a5fa", "#a78bfa", "#2dd4bf"]; // --teal, --blue, --violet, --teal (dark tokens)
const DOT = "#0f141c"; // --bg2

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
function colorAt(f) {
  const seg = Math.min(2, Math.floor(f * 3)), t = f * 3 - seg;
  return "#" + mix(hex(STOPS[seg]), hex(STOPS[seg + 1]), t).map((v) => v.toString(16).padStart(2, "0")).join("");
}

/** SVG on a 26-unit grid (same geometry as .logo-mark); the conic gradient is drawn as 72 wedges. */
function svg() {
  const N = 72, c = 13, R = 20;
  const wedges = [];
  for (let i = 0; i < N; i++) {
    const a0 = ((210 + (i * 360) / N) * Math.PI) / 180, a1 = ((210 + ((i + 1.04) * 360) / N) * Math.PI) / 180;
    const p = (a) => `${(c + R * Math.sin(a)).toFixed(3)},${(c - R * Math.cos(a)).toFixed(3)}`;
    wedges.push(`<path d="M${c},${c}L${p(a0)}L${p(a1)}Z" fill="${colorAt((i + 0.5) / N)}" stroke="${colorAt((i + 0.5) / N)}" stroke-width=".12"/>`);
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 26 26"><defs><clipPath id="r"><rect width="26" height="26" rx="7"/></clipPath></defs>` +
    `<g clip-path="url(#r)">${wedges.join("")}</g><circle cx="13" cy="13" r="5" fill="${DOT}"/></svg>\n`;
}

/** ICO container holding PNG images (supported by every current browser). */
function ico(pngs) {
  const head = Buffer.alloc(6 + 16 * pngs.length);
  head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(pngs.length, 4);
  let off = head.length;
  pngs.forEach(([size, buf], i) => {
    const o = 6 + 16 * i;
    head.writeUInt8(size >= 256 ? 0 : size, o); head.writeUInt8(size >= 256 ? 0 : size, o + 1);
    head.writeUInt16LE(1, o + 4); head.writeUInt16LE(32, o + 6);
    head.writeUInt32LE(buf.length, o + 8); head.writeUInt32LE(off, o + 12);
    off += buf.length;
  });
  return Buffer.concat([head, ...pngs.map(([, b]) => b)]);
}

const src = svg();
fs.writeFileSync(path.join(out, "favicon.svg"), src);
const browser = await chromium.launch();
const page = await browser.newPage();
async function render(size, pad = 0, bg = null) {
  await page.setViewportSize({ width: size, height: size });
  const inner = size - 2 * pad;
  await page.setContent(`<html><body style="margin:0;background:${bg ?? "transparent"}"><img src="data:image/svg+xml;base64,${Buffer.from(src).toString("base64")}" style="display:block;margin:${pad}px;width:${inner}px;height:${inner}px"></body></html>`);
  await page.waitForTimeout(50);
  return page.screenshot({ omitBackground: !bg, type: "png" });
}
const write = (name, buf) => { fs.writeFileSync(path.join(out, name), buf); console.log("✓", name, PNG.sync.read(buf).width + "px"); };
write("favicon-32x32.png", await render(32));
write("favicon-16x16.png", await render(16));
write("icon-192.png", await render(192));
write("icon-512.png", await render(512));
// iOS draws its own rounded mask and no transparency: full-bleed on the dark app background
write("apple-touch-icon.png", await render(180, 18, "#0b0f15"));
fs.writeFileSync(path.join(out, "favicon.ico"), ico([[16, await render(16)], [32, await render(32)], [48, await render(48)]]));
console.log("✓ favicon.ico 16/32/48");
await browser.close();
