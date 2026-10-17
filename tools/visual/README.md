# Visual check — pixel-level UI verification

Makes sure the app looks **exactly** like `docs/ui-mockup.html`. Claude Code runs it at the end of every phase that touches UI (the `/visual-check` skill does it for you).

## What it does
1. `capture.mjs --target app` opens the running app at 1440×900 in headless Chromium with `?visualTest=1`, performs the actions listed in `pages.json` (clicks, hover hooks) and saves a screenshot + the bounding boxes of every `data-testid` region for each screen.
2. `compare.mjs` compares each app screenshot with the reference in `docs/ui-reference/` and gates on three checks:

| Check | What it catches | Gate |
|---|---|---|
| **Layout** — % of 8×8 blocks whose average colour differs | wrong colours, sizes, spacing, missing panels | ≤ 6% (10% for agent-specific screens) |
| **Edges** — % of 16×16 blocks where borders/text/lines appear in one image but not the other | shifted grids, moved borders, distorted cards | ≤ 6% (10%) |
| **Geometry** — every `data-testid` region in the reference must exist in the app at the same x/y/width/height (±6 px or ±2%) | anything misplaced or mis-sized, missing regions | zero issues |
| Pixel (info only) | exact pixel differences | — |

Calibration on the mockup itself: moving the sidebar by 38 px → layout 19% / edges 19% / 19 geometry issues (FAIL); same layout with different text and digits → layout 1.7% / edges 0.5% (PASS).

3. It writes `artifacts/visual/report.md`, `artifacts/visual/diff/*.png` and **`artifacts/visual/sbs/*.png` (reference | app | diff side by side)**. Claude Code must open the side-by-side images with the Read tool for every FAIL and every REVIEW screen and fix what it sees.

## Rules for the app (so the comparison is meaningful)
- **Same viewport and fonts:** desktop 1440×900; Inter + JetBrains Mono self-hosted via `@fontsource` (no network fonts).
- **Visual-test mode:** when the URL has `?visualTest=1` the app must:
  - load the **demo fixtures** instead of live data. Generate them from the mockup with `node extract-fixtures.mjs` → `web/src/visual-fixtures/mockup-fixtures.json` (agents with positions, stats, ticker, products, sites, the featured agent's thoughts/conversation/memories/beliefs, studio content, graph, hoardings rows). Never hand-edit; re-run if the mockup changes;
  - freeze animation and the world clock at Day 23 · Tue 08:40;
  - expose `window.__ll` with `featured()`, `focus(id)`, `hoverAgent(id)`, `openAgent(id, tab)`, `lens(name)`, `setTime(hour)`, `overview()`, `highlights(day)`, `launchFx(productId, progress)`, `graphSelect(id)`, `graphHover(id)` (see `docs/INTERFACES.md` §6.4).
- **Same `data-testid` names** as the mockup for every region listed in `docs/INTERFACES.md` §6. Inspect the mockup or `docs/ui-reference/*.boxes.json` for the full list per screen.
- Canvases (globe, world, minimap, launch FX, knowledge graph, plan map, sites map) are hidden and the event ticker is masked automatically; `REVIEW` screens (world look, night, lenses, launch FX, graph) are not gated — compare them by eye.
- Do **not** add mockup-only elements (`data-testid=mockup-only`: the "Mockup" chip and the ×1/×10/×60 speed buttons); they are hidden in captures.

## Commands
```bash
cd tools/visual
npm install                      # once
npx playwright install chromium  # once
npm run check                    # capture app (must be running on :5173) + compare
node capture.mjs --target app --phase 2      # only screens built up to phase 2
node compare.mjs --phase 2
node capture.mjs --target app --only 03-world-hover && node compare.mjs --only 03-world-hover
node extract-fixtures.mjs                    # (re)generate web/src/visual-fixtures/mockup-fixtures.json
node capture.mjs --target mockup             # regenerate references (only if the mockup changes)
node capture.mjs --target selftest && node compare.mjs   # sanity: mockup vs mockup → all 0.0%
```
`PW_CHROMIUM_PATH=/path/to/chrome` overrides the browser binary if needed.

## Interactive check (optional, in addition)
- **Claude in Chrome:** start Claude Code with `claude --chrome` (requires the Claude in Chrome extension and `/login` with a Claude plan) and ask it to open `http://localhost:5173` and `docs/ui-mockup.html` side by side, take screenshots and compare.
- **Playwright MCP:** `.mcp.json` in the repo root registers the Playwright MCP server, so Claude Code can drive a browser and take screenshots during development (approve it when prompted).
These are for exploring; the scripted check above is the gate.
