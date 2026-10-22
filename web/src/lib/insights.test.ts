import { describe, expect, it } from "vitest";
import { parseSse } from "./insights";

describe("parseSse", () => {
  it("skips keep-alive comments and reads data items", () => {
    const items = parseSse(': ping\n\ndata: {"step":"a"}\n\n: ping\n\ndata: {"answer":{"answer_md":"x"}}\n\n');
    expect(items).toEqual([{ step: "a" }, { answer: { answer_md: "x" } }]);
  });
});

import { axisLines } from "../components/charts";
describe("axisLines", () => {
  it("keeps short labels and wraps long ones into ≤ 2 lines of max chars", () => {
    expect(axisLines("Pixel 10a", 12)).toEqual(["Pixel 10a"]);
    const l = axisLines("Galaxy S26 Ultra Titanium Edition", 10);
    expect(l.length).toBe(2);
    l.forEach((x) => expect(x.length).toBeLessThanOrEqual(10));
  });
});
