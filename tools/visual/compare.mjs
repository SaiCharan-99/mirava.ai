// Compare app screenshots with the mockup references.
// Usage: node compare.mjs [--only a,b] [--phase N]
// Outputs (in artifacts/visual/):
//   sbs/<name>.png    reference | app | diff, side by side  -> LOOK AT THESE with the Read tool
//   diff/<name>.png   pixel diff (red = different)
//   report.md         table of results; exit code 1 if any gated screen fails
//
// Two metrics:
//   layout   = % of 8x8 blocks whose average colour differs (tolerance 10/255). Catches wrong colours,
//              spacing, sizes, missing panels.                                         GATE <= maxLayout (default 6%)
//   edges    = % of 16x16 blocks where one image has visible edges (borders, text, lines) and the other
//              doesn't. Catches moved borders, shifted grids, distorted cards.         GATE <= maxEdge (default 6%)
//   geometry = every data-testid region in the reference must exist in the app with x/y/width/height
//              within ±6 px (±2% of size for large regions).                            GATE: no violations
//   pixel    = % of differing pixels (pixelmatch). Information only.
// Calibration (mockup vs itself with distortions): moving the sidebar 38 px → layout 19%, edges 19%;
// card padding +4 px → layout 14%, edges 10%; same layout with different text/digits → layout 1.7%, edges 0.5%.
// So the app must render the mockup's demo data in ?visualTest=1 mode (see docs/INTERFACES.md §6).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const cfg = JSON.parse(fs.readFileSync(path.join(here, "pages.json"), "utf8"));
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith("--")) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : true]);
  return acc;
}, []));
const only = args.only ? String(args.only).split(",") : null;
const maxPhase = args.phase ? Number(args.phase) : null;

const refDir = path.join(root, cfg.targets.mockup.outDir);
const appDir = path.join(root, cfg.targets.app.outDir);
const outDir = path.join(root, "artifacts/visual");
for (const d of ["sbs", "diff"]) fs.mkdirSync(path.join(outDir, d), { recursive: true });

function layoutDiff(a, b, w, h, block = 8, tol = 10) {
  let diff = 0, total = 0;
  for (let by = 0; by < h; by += block) for (let bx = 0; bx < w; bx += block) {
    let ra = 0, ga = 0, ba = 0, rb = 0, gb = 0, bb = 0, n = 0;
    for (let y = by; y < Math.min(by + block, h); y++) for (let x = bx; x < Math.min(bx + block, w); x++) {
      const i = (y * w + x) * 4;
      ra += a[i]; ga += a[i + 1]; ba += a[i + 2]; rb += b[i]; gb += b[i + 1]; bb += b[i + 2]; n++;
    }
    const d = Math.max(Math.abs(ra - rb), Math.abs(ga - gb), Math.abs(ba - bb)) / n;
    total++; if (d > tol) diff++;
  }
  return diff / total;
}


function edgeDiff(a, b, w, h, block = 16, minEdges = 6) {
  const E = (img) => {
    const L = new Float32Array(w * h);
    for (let i = 0; i < w * h; i++) L[i] = 0.3 * img[i * 4] + 0.59 * img[i * 4 + 1] + 0.11 * img[i * 4 + 2];
    const e = new Uint8Array(w * h);
    for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
      const g = Math.abs(L[y * w + x + 1] - L[y * w + x - 1]) + Math.abs(L[(y + 1) * w + x] - L[(y - 1) * w + x]);
      e[y * w + x] = g > 18 ? 1 : 0;
    }
    return e;
  };
  const ea = E(a), eb = E(b);
  let d = 0, t = 0;
  for (let by = 0; by < h; by += block) for (let bx = 0; bx < w; bx += block) {
    let na = 0, nb = 0;
    for (let y = by; y < Math.min(by + block, h); y++) for (let x = bx; x < Math.min(bx + block, w); x++) { na += ea[y * w + x]; nb += eb[y * w + x]; }
    t++; if ((na > minEdges) !== (nb > minEdges)) d++;
  }
  return d / t;
}

function geometryDiff(refBoxesP, appBoxesP) {
  if (!fs.existsSync(refBoxesP)) return [];
  const ref = JSON.parse(fs.readFileSync(refBoxesP, "utf8"));
  const app = fs.existsSync(appBoxesP) ? JSON.parse(fs.readFileSync(appBoxesP, "utf8")) : {};
  const issues = [];
  for (const [id, r] of Object.entries(ref)) {
    const a = app[id];
    if (!a) { issues.push(`missing [data-testid=${id}]`); continue; }
    const tol = (v) => Math.max(6, Math.round(v * 0.02));
    const names = ["x", "y", "width", "height"];
    const bad = names.map((n, i) => Math.abs(a[i] - r[i]) > tol(r[i] || 0) ? `${n} ${a[i]} vs ${r[i]}` : null).filter(Boolean);
    if (bad.length) issues.push(`${id}: ${bad.join(", ")}`);
  }
  return issues;
}

function sideBySide(ref, app, diff, w, h) {
  const gap = 12, out = new PNG({ width: w * 3 + gap * 2, height: h });
  out.data.fill(255);
  for (const [img, ox] of [[ref, 0], [app, w + gap], [diff, 2 * (w + gap)]])
    for (let y = 0; y < h; y++) img.data.copy(out.data, (y * out.width + ox) * 4, y * w * 4, (y + 1) * w * 4);
  return out;
}

const rows = [];
const geoNotes = [];
let failed = 0;
for (const s of cfg.screens) {
  if (only && !only.includes(s.name)) continue;
  if (maxPhase && s.phase > maxPhase) continue;
  const refP = path.join(refDir, `${s.name}.png`), appP = path.join(appDir, `${s.name}.png`);
  if (!fs.existsSync(refP)) { rows.push([s.name, "—", "—", "—", "—", "no reference", "FAIL"]); failed++; continue; }
  if (!fs.existsSync(appP)) { rows.push([s.name, "—", "—", "—", "—", "not captured", s.reviewOnly ? "REVIEW" : "FAIL"]); if (!s.reviewOnly) failed++; continue; }
  const ref = PNG.sync.read(fs.readFileSync(refP)), app = PNG.sync.read(fs.readFileSync(appP));
  if (ref.width !== app.width || ref.height !== app.height) { rows.push([s.name, "—", "—", "—", "—", `size ${app.width}x${app.height} ≠ ${ref.width}x${ref.height}`, "FAIL"]); failed++; continue; }
  const { width: w, height: h } = ref;
  const diff = new PNG({ width: w, height: h });
  const px = pixelmatch(ref.data, app.data, diff.data, w, h, { threshold: 0.12, includeAA: false, alpha: 0.25 }) / (w * h);
  const lay = layoutDiff(ref.data, app.data, w, h);
  const edg = edgeDiff(ref.data, app.data, w, h);
  const geo = s.reviewOnly ? [] : geometryDiff(refP.replace(/\.png$/, ".boxes.json"), appP.replace(/\.png$/, ".boxes.json"));
  const max = s.maxLayout ?? cfg.defaultMaxLayout, maxE = s.maxEdge ?? cfg.defaultMaxEdge ?? max;
  const pass = lay <= max && edg <= maxE && geo.length === 0;
  if (geo.length) geoNotes.push(`### ${s.name}\n` + geo.map(g => `- ${g}`).join("\n"));
  const status = s.reviewOnly ? "REVIEW" : pass ? "PASS" : "FAIL";
  if (status === "FAIL") failed++;
  fs.writeFileSync(path.join(outDir, "diff", `${s.name}.png`), PNG.sync.write(diff));
  fs.writeFileSync(path.join(outDir, "sbs", `${s.name}.png`), PNG.sync.write(sideBySide(ref, app, diff, w, h)));
  rows.push([s.name, (lay * 100).toFixed(1) + "%", (edg * 100).toFixed(1) + "%", geo.length ? `${geo.length} issues` : "ok", (px * 100).toFixed(1) + "%", `${(max * 100).toFixed(0)}% / ${(maxE * 100).toFixed(0)}%`, status]);
}

const md = [
  "# Visual check report", "",
  `Generated ${new Date().toISOString()} · references: ${path.relative(root, refDir)} · app: ${path.relative(root, appDir)}`, "",
  "| Screen | Layout (gate) | Edges (gate) | Geometry (gate) | Pixel (info) | Limits layout/edges | Result |", "|---|---|---|---|---|---|---|",
  ...rows.map(r => `| ${r.join(" | ")} |`), "",
  ...(geoNotes.length ? ["## Geometry issues (data-testid regions: app vs reference, px)", "", ...geoNotes, ""] : []),
  "Magenta boxes are masked dynamic regions (world canvas, live counters).",
  "Open `artifacts/visual/sbs/<screen>.png` (reference | app | diff) for every FAIL and REVIEW row and fix what differs.",
].join("\n");
fs.writeFileSync(path.join(outDir, "report.md"), md);
console.log(md);
process.exitCode = failed ? 1 : 0;
