import { describe, expect, it } from "vitest";
import { arrivalTables, bannerKind, flows, itemsFromLive, mmss, secondsLeft, sessionRoute, type ActiveSurvey, type LiveState } from "./focus";
import { roomState } from "./survey";

const counts = { invited: 10, replied: 6, accepted: 4, waitlist: 0, walking: 2, arrived: 1 };
const act = (status: ActiveSurvey["status"]): ActiveSurvey => ({ survey_id: "sv-1", title: "T", status, start_at_t: 1000, counts });

describe("shared timer", () => {
  it("counts down on the world clock and adjusts to a slowed rate", () => {
    expect(secondsLeft(1000, 900, 0.4)).toBe(250);
    expect(secondsLeft(1000, 900, 0.2)).toBe(500);
    expect(secondsLeft(1000, 1200, 0.4)).toBe(0);
    expect(mmss(102.2)).toBe("01:43");
    expect(mmss(0)).toBe("00:00");
  });
});

describe("banner", () => {
  it("shows countdown, live, then finished until dismissed", () => {
    expect(bannerKind(act("recruiting"), () => false)).toBe("countdown");
    expect(bannerKind(act("gathering"), () => false)).toBe("countdown");
    expect(bannerKind(act("in_session"), () => false)).toBe("live");
    expect(bannerKind(act("completed"), () => false)).toBe("done");
    expect(bannerKind(act("completed"), () => true)).toBeNull();
    expect(bannerKind(null, () => false)).toBeNull();
  });
  it("routes each session card to the right page", () => {
    expect(sessionRoute("a", "recruiting")).toBe("/insights/focus/a/wait");
    expect(sessionRoute("a", "in_session")).toBe("/insights/focus/a/room");
    expect(sessionRoute("a", "completed")).toBe("/insights/focus/a/results");
  });
});

describe("live room", () => {
  const live: LiveState = {
    survey_id: "sv-1", status: "in_session", phase: "discussion", start_at_t: 900, now_t: 950, q_index: 1, n_questions: 3, counts,
    tables: [{ table_id: "T1", seats: [1, 2, 3] }],
    messages: { T1: [{ message_id: "m1", speaker: "moderator", text: "Q1?", seq: 0, question_id: "q1", t: 905 },
      { message_id: "m2", speaker: 2, text: "Battery.", seq: 3, question_id: "q2", t: 930 }] },
    ballots: { T1: [] }, private: [], arrived_ids: [1, 2, 3], viewers: 2, sim_min_per_real_s: 0.4, seconds_to_start: 0,
  };
  it("re-entering shows the current question, not the first", () => {
    const st = roomState(itemsFromLive(live, ["q1", "q2", "q3"]), 99, live.tables);
    expect(st.qIndex).toBe(1);
    expect(st.bubbles.T1.map((b) => b.text)).toEqual(["Battery."]);
    expect(st.speaker.T1).toBe(2);
  });
  it("seats people as they arrive before the start", () => {
    expect(arrivalTables([5, 6, 7, 8, 9, 10, 11, 12, 13], 8).map((t) => t.seats.length)).toEqual([8, 1]);
    expect(arrivalTables([])).toEqual([{ table_id: "T1", seats: [] }]);
  });
  it("turns a shift matrix into flows", () => {
    expect(flows({ a: { a: 3, b: 1 }, b: { b: 2 } })).toEqual([["a", "a", 3], ["a", "b", 1], ["b", "b", 2]]);
  });
});
