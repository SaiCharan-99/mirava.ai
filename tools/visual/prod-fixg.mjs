// fix-G prod verification: screenshots into artifacts/prod. node prod-fixg.mjs
import { chromium } from "playwright";
const B = "https://mirava-ai-hack.web.app", O = "../../artifacts/prod";
const br = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
const ctx = await br.newContext({ viewport: { width: 1440, height: 900 } });
const p = await ctx.newPage();
const log = (...a) => console.log(...a);
// 1 + 6: Insights header, budget meter
await p.goto(`${B}/insights/ask`, { waitUntil: "load" }); await p.waitForTimeout(8000);
log("1 SIMULATED in page:", (await p.content()).includes("SIMULATED"), "| budget:", await p.locator("[data-testid=budget-meter]").innerText(), "| tip:", await p.locator("[data-testid=budget-meter]").getAttribute("title"));
await p.screenshot({ path: `${O}/1-insights-header.png` });
// 2 + 5: polls
await p.goto(`${B}/insights/focus`, { waitUntil: "load" }); await p.waitForTimeout(7000);
log("2 sessions:", (await p.locator("[data-testid=sessions-list]").innerText()).replace(/\n/g, " | ").slice(0, 300));
await p.locator("[data-testid=preset-next-phone]").click(); await p.waitForTimeout(4000);
log("5 title:", await p.locator("[data-testid=focus-builder] input").first().inputValue(), "| questions:", await p.locator("[data-testid^=survey-q-]").count());
await p.screenshot({ path: `${O}/5-poll-preset.png`, fullPage: true });
// 3: Sankey on a finished focus group
const sv = await (await p.request.get(`${B}/api/surveys`)).json();
const done = sv.find((s) => s.status === "completed");
if (done) { await p.goto(`${B}/insights/focus/${done.survey_id}/results`, { waitUntil: "load" }); await p.waitForTimeout(8000);
  const sk = p.locator("[data-testid=sankey]"); log("3 sankey:", await sk.count());
  if (await sk.count()) { await sk.scrollIntoViewIfNeeded(); const band = p.locator("[data-testid=sankey-band]").first(); if (await band.count()) await band.hover(); await p.waitForTimeout(500);
    log("3 hover:", await p.locator("[data-testid=sankey-hover]").innerText()); }
  await p.screenshot({ path: `${O}/3-sankey.png`, fullPage: true }); }
// 4: room 3D default
const live = sv.find((s) => s.status === "in_session") ?? done;
if (live) { await p.goto(`${B}/insights/focus/${live.survey_id}/room`, { waitUntil: "load" }); await p.waitForTimeout(9000);
  log("4 room:", live.survey_id, "canvas:", await p.locator("canvas").count(), "3D button on:", await p.locator("button.on", { hasText: "3D" }).count());
  await p.screenshot({ path: `${O}/4-room-3d.png` }); }
// 7: profile conversation + insights conversation
await p.goto(`${B}/world`, { waitUntil: "load" }); await p.waitForFunction(() => window.__ll, null, { timeout: 30000 }); await p.waitForTimeout(4000);
await p.evaluate(() => window.__ll.openAgent(11, "conversations")); await p.waitForTimeout(5000);
const rows = p.locator("[data-testid=conversation-list] button"); if (await rows.count() > 1) { await rows.nth(1).click(); await p.waitForTimeout(4000); }
const det = p.locator("[data-testid=conversation-detail]");
log("7 drawer detail:", await det.count(), "visible:", (await det.count()) ? await det.isVisible() : false);
await p.screenshot({ path: `${O}/7-profile-conversation.png` });
await p.goto(`${B}/insights/conversations`, { waitUntil: "load" }); await p.waitForTimeout(12000);
log("7 insights detail:", (await p.locator("[data-testid=conv-detail]").innerText()).slice(0, 200).replace(/\n/g, " | "));
await p.screenshot({ path: `${O}/7-insights-conversation.png` });
await br.close();
