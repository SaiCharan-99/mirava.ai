import { chromium } from "playwright";
const B = "https://mirava-ai-hack.web.app", O = "../../artifacts/prod";
const br = await chromium.launch({ args: ["--use-gl=swiftshader"] });
const p = await (await br.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
for (const sid of ["sv-d3efb0ef", "sv-1eac8c0b"]) {
  await p.goto(`${B}/insights/focus/${sid}/results`, { waitUntil: "load" }); await p.waitForTimeout(9000);
  const tabs = p.locator(".qtabs button"); const n = await tabs.count();
  for (let i = 0; i < n; i++) { await tabs.nth(i).click(); await p.waitForTimeout(800);
    const sk = p.locator("[data-testid=sankey]"); if (!(await sk.count())) continue;
    await sk.scrollIntoViewIfNeeded(); await p.locator("[data-testid=sankey-band]").first().hover({ force: true }); await p.waitForTimeout(500);
    console.log(sid, "Q", i + 1, "hover:", await p.locator("[data-testid=sankey-hover]").innerText());
    await sk.screenshot({ path: `${O}/3-sankey-${sid}.png` }); await p.screenshot({ path: `${O}/3-sankey-page-${sid}.png` }); i = n; }
  console.log(sid, "tabs", n);
}
await p.goto(`${B}/world`, { waitUntil: "load" }); await p.waitForFunction(() => window.__ll, null, { timeout: 30000 }); await p.waitForTimeout(4000);
await p.evaluate(() => window.__ll.openAgent(11, "conversations")); await p.waitForTimeout(5000);
await p.locator("[data-testid=conversation-list] button").nth(0).click(); await p.waitForTimeout(5000);
console.log("drawer detail:", await p.locator("[data-testid=conversation-detail]").count());
await p.screenshot({ path: `${O}/7-profile-transcript.png` });
await br.close();
