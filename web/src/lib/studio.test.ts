import { describe, expect, it } from "vitest";
import { fromApi, toWorldProduct, type ApiProduct } from "./studio";
import { siteMap, tickerFor } from "./liveSync";

const P: ApiProduct = {
  product_id: "nova-x1", name: "Nova X1", brand: "Arcline", category: "Smartphone", price_inr: 89999, launch_offer: null,
  features: ["200MP camera"], claims: ["The best camera ever.", "7 years of OS updates."], target_personas: ["Photographers"],
  audience: [{ description: "Photographers", filter: {}, count: 120 }], strategy: { intensity: "high", key_message: "See the night." },
  creatives: [{ creative_id: "c1", product_id: "nova-x1", kind: "reel", title: "After dark", text: null, transcript: "One. Two.",
    scenes: ["Dusk", "Stall"], image_uri: null, stimulus: { creative_id: "c1", salience: 0.8, clarity: 0.7, hook: "h", claims_carried: [], tone: "t", readable_at_distance: true, description: "d" }, screened: true }],
  plan: { sites: [{ site_id: "S-1", facing: 90, creative_id: "c1", est_target_ots_day: 40, reason: "why" }],
    reel: { audience_size: 300 }, newspaper_days: [0, 2], reviewers: [1, 2], community_seed: {}, stores: ["ST-ELECTROHUB"], flight_days: 14, generated_day: 3 },
  status: "ready", color: "#f97316", launched_at_t: null,
  understanding: { claims: [{ text: "The best camera ever.", source: "details", risk: "red", reason: "absolute" }] },
  graph: { nodes: [{ id: "nova-x1", label: "Nova X1", type: "product", desc: "", source: "" }], edges: [] },
};

describe("studio view model", () => {
  it("maps claims risk, plan, stores and reel rows", () => {
    const v = fromApi(P);
    expect(v.claims[0].risk).toBe("red");
    expect(v.claims[1].risk).toBe("amber");
    expect(v.storeNames).toEqual(["ElectroHub"]);
    expect(v.reel).toBe(300);
    expect(v.reelRows).toEqual([["0:00", "Dusk", "One."], ["0:03", "Stall", "Two."]]);
    expect(v.graph?.nodes[0].id).toBe("nova-x1");
    const w = toWorldProduct(v);
    expect(w.sites).toEqual([["S-1", 90]]);
    expect(w.reviewers).toBe(2);
  });
});

describe("live media frames", () => {
  it("maps hello sites to board assignments (baseline prefix stripped)", () => {
    expect(siteMap([{ site_id: "A", product_id: "nova-x1" }, { site_id: "B", product_id: "baseline:zesto" }, {}]))
      .toEqual({ A: { cr: "nova-x1" }, B: { cr: "zesto" } });
  });
  it("ticker lines for launch / review; baseline notices hidden", () => {
    const l = tickerFor({ k: "launch", name: "Nova X1", summary: { sites: 8, stores: 3, reel_audience: 420, reviewers: 4 } }, 0, () => "");
    expect(l?.cls).toBe("launch");
    expect(l?.html).toContain("8 hoardings");
    expect(tickerFor({ k: "notice", a: 1, product: "baseline:zesto" }, 0, () => "A")).toBeNull();
    expect(tickerFor({ k: "review", a: 1, title: "Great" }, 0, () => "Tanvi")?.html).toContain("Great");
  });
});
