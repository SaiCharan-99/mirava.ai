---
name: visual-check
description: Pixel-level check that the app UI matches docs/ui-mockup.html. Use after building or changing any screen, and before ending a UI phase. Usage /visual-check 4 (phase) or /visual-check 03-world-hover (screen)
argument-hint: "[phase number or screen name]"
---
Verify the UI against the mockup at pixel level for **$ARGUMENTS**.

1. Make sure the web app is running (`make dev`, Vite on http://localhost:5173) and supports `?visualTest=1` (fixtures from `tools/visual/extract-fixtures.mjs`, frozen clock, `window.__ll` hooks, `data-testid` regions — see `docs/INTERFACES.md` §6).
2. Capture and compare:
   - If $ARGUMENTS is a number N: `cd tools/visual && node capture.mjs --target app --phase N && node compare.mjs --phase N`
   - If it is a screen name: `cd tools/visual && node capture.mjs --target app --only $ARGUMENTS && node compare.mjs --only $ARGUMENTS`
   (First time: `cd tools/visual && npm install && npx playwright install chromium`.)
3. Read `artifacts/visual/report.md`.
4. For **every FAIL and REVIEW** screen, open `artifacts/visual/sbs/<screen>.png` with the Read tool (left = reference, middle = app, right = diff in red). Also open the full-size `docs/ui-reference/<screen>.png` and `artifacts/visual/app/<screen>.png` when details are small. Write down concrete differences: element, expected vs actual position/size (use the geometry list in the report), colour, font size/weight, spacing, borders, missing or extra elements, text wrapping.
5. Fix the code (tokens, layout, components). Do not change `docs/ui-reference/*`, `tools/visual/pages.json` thresholds or masks to make a check pass.
6. Re-run steps 2–5 until every gated screen (not REVIEW) PASSES: layout ≤ limit, edges ≤ limit, geometry "ok".
7. For REVIEW screens (world look, night, lenses, launch FX, graph), compare by eye with the reference and with the live mockup (`docs/ui-mockup.html` without `?freeze=1`); fix obvious style differences (tile colours, sprite proportions, cones, firework, night tint).
8. Report the final table and remaining differences; `/end-phase` copies it into `PROGRESS.md` §4.
