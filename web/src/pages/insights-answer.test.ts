import { describe, expect, it } from "vitest";
import { toView, starterQuestions } from "./InsightsPage";
import type { AskAnswer } from "../lib/insights";

const answer = (value: number, unit?: string): AskAnswer => ({
  answer_md: "Recorded counts", numbers: [{ label: "<img src=x onerror=alert(1)>", value, source_ref: "sql" }],
  charts: [{ xAxis: { data: ["Phone"] }, series: [{ data: [value] }], _unit: unit }],
  quotes: [], sql: [], caveats: [], suggestions: [],
});

describe("Ask chart units", () => {
  it("does not turn counts of 163, one or zero into percentages", () => {
    for (const n of [163, 1, 0]) {
      const v = toView(answer(n), []);
      expect(v.unit).toBe("");
      expect(v.bars?.[0][1]).toBe(n);
      expect(v.sideHtml).not.toContain("<img");
    }
  });
  it("scales only explicit fractions", () => {
    expect(toView(answer(0.25, "fraction"), []).bars?.[0][1]).toBe(25);
    expect(toView(answer(25, "percent"), []).unit).toBe("%");
  });
  it("offers fixed starters even before product metadata arrives", () => {
    expect(starterQuestions([])).toHaveLength(3);
    expect(starterQuestions([])).toEqual(starterQuestions(["Example"]));
  });
});
