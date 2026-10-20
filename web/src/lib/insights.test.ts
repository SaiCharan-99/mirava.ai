import { describe, expect, it } from "vitest";
import { parseSse } from "./insights";

describe("parseSse", () => {
  it("skips keep-alive comments and reads data items", () => {
    const items = parseSse(': ping\n\ndata: {"step":"a"}\n\n: ping\n\ndata: {"answer":{"answer_md":"x"}}\n\n');
    expect(items).toEqual([{ step: "a" }, { answer: { answer_md: "x" } }]);
  });
});
