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

import { MAX_OPTIONS, addOption, cleanQuestions, funnelRows, newQuestion, optionsFromProducts, questionIssues, removeOption, resolveStart, withType } from "./survey";

describe("question options (Google-Forms style, 2–4)", () => {
  it("starts blank with two empty option rows", () => {
    const n = newQuestion(3);
    expect(n.question_id).toBe("q3");
    expect(n.text).toBe("");
    expect(n.options).toEqual(["", ""]);
  });
  it("adds up to four options and removes down to two", () => {
    let x = newQuestion(1);
    for (let i = 0; i < 6; i++) x = addOption(x);
    expect(x.options).toHaveLength(MAX_OPTIONS);
    for (let i = 0; i < 6; i++) x = removeOption(x, 0);
    expect(x.options).toHaveLength(2);
  });
  it("flags too many options and too few filled ones", () => {
    expect(questionIssues(q({ options: ["a", "b", "c", "d", "e"] }), 0)).toEqual(["Question 1 can have at most 4 options"]);
    expect(questionIssues(q({ options: ["a", " "] }), 0)).toEqual(["Question 1 needs at least 2 options"]);
  });
  it("uses selected products as options, at most four", () => {
    const o = optionsFromProducts(q({}), ["A", "B", "C", "D", "E"]);
    expect(o.options).toEqual(["A", "B", "C", "D"]);
    expect(o.option_source).toBe("products");
  });
  it("switching type keeps or resets the right fields", () => {
    const sc = withType(q({ options: ["a", "b"] }), "scale");
    expect(sc.options).toBeNull();
    expect(sc.scale).toEqual({ min: 1, max: 5, low_label: "", high_label: "" });          // no meaningless prefilled 'low'/'high'
    expect(withType(sc, "single").options).toEqual(["", ""]);
    expect(withType(q({ options: ["a", "b", "c"] }), "multi").max_select).toBe(2);
  });
  it("cleans questions for the API: trims, drops empty rows, renumbers, clamps multi-select", () => {
    const [a, b, c] = cleanQuestions([
      q({ text: " Which? ", options: [" Battery ", "", "Camera", " "] }),
      q({ type: "multi", options: ["x", "y"], max_select: 9 }),
      q({ type: "scale", options: null, scale: { min: 1, max: 10, low_label: " bad ", high_label: "" } }),
    ]);
    expect(a.text).toBe("Which?");
    expect(a.options).toEqual(["Battery", "Camera"]);
    expect(a.question_id).toBe("q1");
    expect(b.max_select).toBe(2);
    expect(c.options).toBeNull();
    expect(c.scale).toEqual({ min: 1, max: 10, low_label: "bad", high_label: "" });
  });
});

describe("when to start", () => {
  const now = 1440 * 4 + 10 * 60;                       // day 5, 10:00
  it("lets the engine pick the next slot", () => {
    expect(resolveStart(now, { kind: "next" })).toMatchObject({ t: null, lead: null });
  });
  it("starts a number of minutes from now, never sooner than five", () => {
    expect(resolveStart(now, { kind: "in", minutes: 15 })).toMatchObject({ t: now + 15, lead: 15 });
    expect(resolveStart(now, { kind: "in", minutes: 1 }).t).toBe(now + 5);
  });
  it("starts tomorrow at a chosen time", () => {
    expect(resolveStart(now, { kind: "tomorrow", hhmm: "09:30" }).t).toBe(1440 * 5 + 9 * 60 + 30);
    expect(resolveStart(now, { kind: "tomorrow", hhmm: "nonsense" }).t).toBeNull();
  });
  it("picks the next occurrence of a clock time", () => {
    expect(resolveStart(now, { kind: "pick", hhmm: "18:00" }).t).toBe(1440 * 4 + 18 * 60);
    expect(resolveStart(now, { kind: "pick", hhmm: "09:00" }).t).toBe(1440 * 5 + 9 * 60);
  });
  it("describes the notice in plain words", () => {
    expect(resolveStart(now, { kind: "in", minutes: 15 }).label).toContain("in 15 min");
    expect(resolveStart(now, { kind: "in", minutes: 180 }).label).toContain("in 3 h");
  });
});

describe("recruitment funnel", () => {
  it("lists heard → yes → on the way → checked in", () => {
    const o = { reached: 70, seen_by_channel: {}, accepted: 30, accepted_by_channel: {}, declined: 36, waitlist: 1, on_the_way: 29, checked_in: 27,
      turned_away: 0, wave: 2, channels: [], pending: 0 };
    expect(funnelRows(o).map((r) => [r.label, r.n])).toEqual([["Heard about it", 70], ["Said yes", 30], ["On the way", 29], ["Checked in", 27]]);
    expect(funnelRows(undefined)).toEqual([]);
  });
});
