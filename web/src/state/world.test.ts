import { describe, expect, it } from "vitest";
import { useWorld } from "./world";
import { makeHooks } from "../hooks/ll";
import { anglesFor, stepPhi } from "../globe/GlobeIntro";
import fixtures from "../visual-fixtures/mockup-fixtures.json";
import type { Fixtures } from "../visual-fixtures/types";

describe("world store + __ll hooks", () => {
  it("loads fixtures frozen at Day 23 · Tue 08:40", () => {
    useWorld.getState().loadFixtures(fixtures as unknown as Fixtures);
    const s = useWorld.getState();
    expect(s.t).toBe(22 * 1440 + 520);
    expect(s.stats.agents).toBe(1000);
    expect(s.stats.products_live).toBe(2);
    expect(s.dayCounts).toHaveLength(23);
  });
  it("setTime jumps within the current day and lens switches", () => {
    const ll = makeHooks();
    ll.setTime(21.5);
    expect(useWorld.getState().t % 1440).toBe(21 * 60 + 30);
    expect(Math.floor(useWorld.getState().t / 1440)).toBe(22);
    ll.lens("hoardings");
    expect(useWorld.getState().lens).toBe("hoardings");
    expect(ll.featured()).toBe((fixtures as unknown as Fixtures).featured.id);
  });
  it("cobe angles centre Bengaluru", () => {
    const [phi, theta] = anglesFor([12.9719, 77.6412]);
    expect(phi).toBeCloseTo(Math.PI - (77.6412 * Math.PI) / 180 + Math.PI / 2);
    expect(theta).toBeCloseTo(0.2264, 3);
    let p = phi - 2.4;
    for (let i = 0; i < 600; i++) p = stepPhi(p, phi); // ~10 s at 60 fps
    expect(Math.abs(p - phi)).toBeLessThan(0.01);
  });
});
