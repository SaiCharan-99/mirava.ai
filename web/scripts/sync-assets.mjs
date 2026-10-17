// Copies the generated map assets the browser needs from ../assets into public/assets (git-ignored).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, "../../assets");
const dst = path.resolve(here, "../public/assets");
const files = ["maps/indiranagar.tmj", "maps/sites.json", "maps/stores.json", "tiles/city.png"];
for (const f of files) {
  const from = path.join(src, f);
  if (!fs.existsSync(from)) { console.error(`missing ${from} — run \`make map\``); process.exit(1); }
  fs.mkdirSync(path.dirname(path.join(dst, f)), { recursive: true });
  fs.copyFileSync(from, path.join(dst, f));
}
console.log(`synced ${files.length} map assets → web/public/assets`);
