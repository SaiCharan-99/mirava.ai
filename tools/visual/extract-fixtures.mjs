// Extracts the mockup's demo content (freeze mode, Day 23 · Tue 08:40) into a JSON file
// that the real app loads in visual-test mode (?visualTest=1). Run from tools/visual:
//   node extract-fixtures.mjs [../../web/src/visual-fixtures/mockup-fixtures.json]
// Re-run whenever docs/ui-mockup.html changes. Never hand-edit the output.
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const out = path.resolve(process.argv[2] || path.join(root, "web/src/visual-fixtures/mockup-fixtures.json"));
const browser = await chromium.launch(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.route("https://fonts.googleapis.com/**", r => r.fulfill({ status: 200, contentType: "text/css", body: "" }));
await page.goto("file://" + path.join(root, "docs/ui-mockup.html") + "?freeze=1#world", { waitUntil: "load" });
await page.waitForTimeout(800);
const data = await page.evaluate(() => {
  const pickAgent = a => ({ id: a.id, name: a.name, age: a.age, male: a.male, job: a.job, kind: a.kind, special: a.special || null,
    work: a.work ? a.work.name : null, home: a.home.id, income: Math.round(a.inc), interests: a.interests, phone: a.phone,
    savings: a.savings, card: a.card, emi: a.emi, newspaper: a.newspaper, reddit: a.reddit, watch: a.watch,
    beliefs: a.beliefs, act: a.act, place: a.place ? a.place.name : null, x: +a.x.toFixed(2), y: +a.y.toFixed(2), heading: Math.round(a.heading),
    mode: a.mode, moving: a.path.length > 0, look: { skin: a.skin, hair: a.hair, shirt: a.shirt, pants: a.pants, hairLong: a.hairLong, cap: a.cap },
    friends: a.friends, thoughts: a.thoughts.slice(0, 10) });
  return {
    _source: "docs/ui-mockup.html (freeze mode)", t: SIM.min, label: tLabel(SIM.min),
    stats: SIM.stats, ticker: SIM.ticker.slice(0, 24), highlightsDay21: HL,
    products: PRODUCTS, creatives: CREATIVES, siteAssign, sites: SITES.map(s => ({ ...s, ots: undefined, gl: undefined, no: undefined })),
    stores: STORES.map(s => ({ name: s.name, store: s.store, fmt: s.fmt, x0: s.x0, y0: s.y0, x1: s.x1, y1: s.y1 })),
    featured: { id: MEERA.id, thoughts: MEERA_THOUGHTS, conversation: CONVO, conversations: MEERA_CONVS, memories: MEERA_MEM, beliefs: MEERA_BELIEFS },
    agents: agents.map(pickAgent),
    studio: { assets: ASSETS, reel: REEL_TX, claims: CLAIMS, reasons: REASONS, otsPerDay: OTSD },
    graph: { types: KG_TYPES, nodes: KG_NODES, edges: KG_EDGES },
    insights: { hoardings: HO_ROWS }
  };
});
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify(data));
console.log(`fixtures → ${path.relative(process.cwd(), out)} (${(fs.statSync(out).size / 1024).toFixed(0)} KB, ${data.agents.length} agents)`);
await browser.close();
