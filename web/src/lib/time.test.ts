import { describe, expect, it } from "vitest";
import { fmt, hhmm, nightAlpha, shortT } from "./time";

describe("time helpers", () => {
  it("formats the frozen visual-test time", () => {
    const t = 22 * 1440 + 520;
    expect(fmt(t)).toBe("Day 23 · Tue 08:40");
    expect(shortT(t)).toBe("D23 08:40");
    expect(hhmm(0)).toBe("00:00");
  });
  it("night curve matches the mockup", () => {
    expect(nightAlpha(8.67)).toBe(0);
    expect(nightAlpha(21.5)).toBeCloseTo(0.58);
    expect(nightAlpha(18.75)).toBeCloseTo(0.29);
    expect(nightAlpha(6)).toBeCloseTo(0.29);
  });
});
