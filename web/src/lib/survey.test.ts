import { describe, expect, it } from "vitest";
import { nextClockTime, questionProblems, type QuestionDef } from "./survey";

const q = (over: Partial<QuestionDef>): QuestionDef => ({ question_id: "q1", text: "What matters most?", type: "single", options: ["A", "B"], discuss: true, ...over });

describe("nextClockTime", () => {
  it("picks today when still ahead by the minimum lead", () => {
    expect(nextClockTime(1440 * 3 + 10 * 60, "18:00")).toBe(1440 * 3 + 18 * 60);
  });
  it("rolls to tomorrow when too soon or past", () => {
    expect(nextClockTime(1440 * 3 + 17 * 60 + 45, "18:00")).toBe(1440 * 4 + 18 * 60);
    expect(nextClockTime(1440 * 3 + 20 * 60, "09:30")).toBe(1440 * 4 + 9 * 60 + 30);
  });
  it("rejects bad input", () => {
    expect(nextClockTime(0, "25:00")).toBeNull();
    expect(nextClockTime(0, "soon")).toBeNull();
  });
});

describe("questionProblems", () => {
  it("is empty for a valid draft", () => expect(questionProblems([q({})])).toEqual([]));
  it("names the question that needs text", () => {
    expect(questionProblems([q({}), q({ text: "  " })])).toEqual(["Question 2 needs text"]);
  });
  it("needs two non-empty options on choice questions only", () => {
    expect(questionProblems([q({ options: ["A", ""] })])).toEqual(["Question 1 needs at least 2 options"]);
    expect(questionProblems([q({ type: "open", options: null })])).toEqual([]);
  });
});
