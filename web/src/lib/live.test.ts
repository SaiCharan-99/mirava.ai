import { describe, expect, it } from "vitest";
import { backoffMs, parseLive } from "./live";
import { applyLive, tickerFor } from "./liveSync";
import { SimClock, Tracks, step, type Track } from "../world/tracks";
import { filterFixtures, EMPTY } from "../pages/PeoplePage";
import { peopleQS } from "./api";
import { actLabel, fromFixture } from "./agentView";
import { useWorld } from "../state/world";
import fixtures from "../visual-fixtures/mockup-fixtures.json";
import type { Fixtures } from "../visual-fixtures/types";

const fx = fixtures as unknown as Fixtures;

describe("live protocol", () => {
  it("parses known frames and rejects junk", () => {
    expect(parseLive("not json")).toBeNull();
    expect(parseLive('{"type":"nope"}')).toBeNull();
    const c = parseLive('{"type":"clock","t":100.5,"speed":2}');
    expect(c).toEqual({ type: "clock", t: 100.5, speed: 2 });
    const s = parseLive('{"type":"seg","items":[{"a":1,"x0":0,"y0":0,"x1":10,"y1":0,"t0":1,"t1":2,"mode":"walk"},{"a":"x"}]}');
    expect(s && s.type === "seg" && s.items.length).toBe(1);
    const h = parseLive('{"type":"hello","t":5,"scale":{"sim_min_per_real_s":0.4},"agents":[{"id":3,"x":1,"y":2,"h":0,"mode":"walk","act":"home"}]}');
    expect(h && h.type === "hello" && h.agents[0].id).toBe(3);
  });
  it("applies stats, hello and evt frames to the store", () => {
    applyLive({ type: "hello", t: 600, scale: { sim_min_per_real_s: 0.4 }, slowed: false, agents: [], segments: [], bubbles: [], products: [], sites: [] });
    applyLive({ type: "stats", t: 601, counts: { agents: 1000, households: 400, relationships: 7000, conversations_today: 3, conversations_total: 9, thoughts_today: 0, products_live: 0 }, budget: { used_usd: 1, cap_usd: 15 } });
    const st = useWorld.getState();
    expect(st.source).toBe("live");
    expect(st.stats.relationships).toBe(7000);
    expect(st.budget.used_usd).toBe(1);
  });
  it("formats ticker lines and escapes text", () => {
    const it1 = tickerFor({ k: "life_event", a: 4, type: "lost" }, 32200, () => "<Meera>");
    expect(it1?.html).toContain("&#60;Meera&#62;");
    expect(it1?.html).toContain("lost their phone");
    expect(it1?.t).toBe("D23 08:40");
    expect(tickerFor({ k: "unknown" }, 0, String)).toBeNull();
  });
  it("backs off exponentially with a cap", () => {
    expect(backoffMs(0)).toBe(1000);
    expect(backoffMs(3)).toBe(8000);
    expect(backoffMs(20)).toBe(30000);
  });
});

describe("interpolation", () => {
  it("moves along queued segments and stops at the end", () => {
    const tr: Track = { id: 1, x: 0, y: 0, h: 0, mode: "walk", act: "", moving: false, segs: [
      { a: 1, x0: 0, y0: 0, x1: 10, y1: 0, t0: 10, t1: 20, mode: "walk" },
      { a: 1, x0: 10, y0: 0, x1: 10, y1: 30, t0: 20, t1: 23, mode: "car" },
    ] };
    step(tr, 5);
    expect(tr.x).toBe(0);
    expect(tr.moving).toBe(false);
    step(tr, 15);
    expect(tr.x).toBeCloseTo(5);
    expect(tr.h).toBeCloseTo(90);
    step(tr, 21.5);
    expect(tr.y).toBeCloseTo(15);
    expect(tr.mode).toBe("car");
    step(tr, 100);
    expect([tr.x, tr.y, tr.moving, tr.segs.length]).toEqual([10, 30, false, 0]);
  });
  it("creates tracks for unknown agents and extrapolates the clock", () => {
    const t = new Tracks();
    t.push([{ a: 9, x0: 1, y0: 1, x1: 2, y1: 2, t0: 0, t1: 1, mode: "walk" }]);
    t.advance(0.5);
    expect(t.byId.get(9)!.x).toBeCloseTo(1.5);
    const c = new SimClock();
    c.rate = 0.5;
    c.set(100, 0);
    expect(c.now(2000)).toBe(101);
    c.frozen = true;
    expect(c.now(9000)).toBe(100);
  });
});

describe("people filters", () => {
  it("phone older than 5 years matches the mockup count and sorts by age", () => {
    const rows = filterFixtures(fx, { ...EMPTY, phoneOld: true });
    expect(rows.length).toBe(fx.agents.filter((a) => a.phone.age > 5).length);
    expect(rows[0].phoneAge).toBeGreaterThanOrEqual(rows[rows.length - 1].phoneAge);
    expect(filterFixtures(fx, { ...EMPTY, q: "meera" }).some((r) => r.name === "Meera Iyer")).toBe(true);
    expect(filterFixtures(fx, { ...EMPTY, age: "25-34" }).every((r) => r.age >= 25 && r.age <= 34)).toBe(true);
  });
  it("builds the /agents query string", () => {
    expect(peopleQS({ ...EMPTY, q: "ux", phoneOld: true, income: "1-2L", page: 2 }, 15))
      .toBe("q=ux&income=1-2L&phone_age_gt=5&sort=-phone_age&page=2&page_size=15");
  });
  it("normalises the featured fixture agent and act labels", () => {
    const v = fromFixture(fx, fx.featured.id)!;
    expect(v.name).toBe("Meera Iyer");
    expect(v.income).toBe("₹1–2L");
    expect(actLabel("commute", "bus")).toBe("On the bus");
    expect(actLabel("cafe")).toBe("At a café");
  });
});

describe("conversation ticker", () => {
  it("joins talk topic/place with the bubble line", async () => {
    const { tickerFor } = await import("./liveSync");
    const nm = (id: number) => ["Meera Iyer", "Arjun Rao"][id] ?? `Agent ${id}`;
    expect(tickerFor({ k: "talk", a: 0, b: 1, session_id: "s1", topic: "product:pulse-5", place: "Brew & Byte" }, 10, nm)).toBeNull();
    const it = tickerFor({ k: "bubble", a: 0, b: 1, session_id: "s1", text: "Hey!" }, 12, nm)!;
    expect(it.html).toContain("Meera Iyer &amp; Arjun Rao");
    expect(it.html).toContain("<b>pulse-5</b>");
    expect(it.html).toContain("Brew &#38; Byte");
    expect(it.cls).toBe("prod");
  });
});
