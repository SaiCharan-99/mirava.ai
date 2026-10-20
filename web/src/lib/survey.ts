/** Survey Room client (addendum B7–B9): shapes, API calls and the timeline → room state model. */
import { getJSON } from "./api";
import { postJSON } from "./insights";
import { liveUrl } from "./live";

export type QType = "single" | "multi" | "scale" | "open";
export interface QuestionDef {
  question_id: string; text: string; type: QType; options?: string[] | null; max_select?: number | null;
  scale?: { min: number; max: number; low_label: string; high_label: string } | null; discuss: boolean;
}
export interface SurveyAgent { agent_id: number; name: string; age?: number; color: string; phone?: string; income_band?: string; experience?: string | null }
export interface TableDef { table_id: string; seats: number[] }
export interface Item { dt: number; kind: string; agent_id: number | null; payload: Record<string, any>; table_id?: string; live?: Record<string, any> | null }
export interface RsvpRow { agent_id: number; rsvp: string; reason?: string; arrived?: boolean | number | null }
export interface SurveyDoc {
  survey_id: string; title: string; mode: "focus_group" | "survey"; status: string; product_id?: string | null; topic?: string;
  questions: QuestionDef[]; wave?: number; panel_id?: string | null; eligible?: number; expected_attendance?: number;
  estimate_usd?: number; actual_usd?: number; start_label?: string; venue_name?: string; tables?: TableDef[];
  participants?: { agent_id: number; rsvp: string; rsvp_reason?: string; arrived_t?: number | null; table_id?: string }[];
  results?: SurveyResults; waves?: Waves | null; live?: { arrived: number; expected: number; status: string } | null;
  summaries?: Record<string, string>; discussion_skipped?: boolean;
}
export interface QResult {
  question_id: string; text: string; type: QType; options?: string[] | null; distribution: Record<string, number>;
  shift: Record<string, Record<string, number>>; by_segment: Record<string, Record<string, number>>;
  quotes: { agent_id: number; name?: string; text: string; tag: string; private: boolean; answer: unknown; changed: boolean }[];
  changed: number; n: number; satisficed?: number; gap?: number;
}
export interface SurveyResults { questions: QResult[]; n_attended: number; changed_share: number; summaries: Record<string, string>; participation_effect: string; notes: string[] }
export interface Waves { distribution: Record<string, Record<string, Record<string, number>>>; changes: { question_id: string; agent_id: number; from_wave: number; to_wave: number; from: unknown; to: unknown; why?: { why: string; event_ids: string[] } | null }[] }
export interface CreateOut { survey_id: string; eligible: number; expected_attendance: number; tables: number; estimate_usd: number; remaining_interactive_usd: number; lint: { question_id: string; kind: string; fix: string }[]; message?: string | null }

export type EstimateOut = Omit<CreateOut, "survey_id">;
/** Draft sizing while the form is edited: no store write, no model call. */
export const estimateSurvey = (body: unknown) => postJSON<EstimateOut>("/surveys/estimate", body);
/** Creates the survey doc: call on Launch only. */
export const createSurvey = (body: unknown) => postJSON<CreateOut>("/surveys", body);

/** Absolute sim minute of the next occurrence of "HH:MM" at least `minLead` minutes after `now` (null if unparsable). */
export function nextClockTime(now: number, hhmm: string, minLead = 30): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm.trim());
  if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) return null;
  const at = Math.floor(now / 1440) * 1440 + Number(m[1]) * 60 + Number(m[2]);
  return at >= now + minLead ? at : at + 1440;
}

/** Client-side problems that would make the API refuse the draft ("Question 2 needs text"). */
export function questionProblems(qs: QuestionDef[]): string[] {
  const out: string[] = [];
  qs.forEach((q, i) => {
    if (!q.text.trim()) out.push(`Question ${i + 1} needs text`);
    else if (q.text.trim().length < 3) out.push(`Question ${i + 1} is too short`);
    if ((q.type === "single" || q.type === "multi") && (q.options ?? []).filter((o) => o.trim()).length < 2) out.push(`Question ${i + 1} needs at least 2 options`);
  });
  return out;
}
export const launchSurvey = (id: string) => postJSON<{ status: string }>(`/surveys/${id}/launch`, {});
export const rerunSurvey = (id: string) => postJSON<{ survey_id: string; wave: number }>(`/surveys/${id}/rerun`, {});
export const explainWaves = (id: string) => postJSON<{ explained: number }>(`/surveys/${id}/explain`, {});
export const lintQuestions = (questions: QuestionDef[]) => postJSON<{ warnings: CreateOut["lint"] }>("/surveys/lint", { questions });
export const getSurvey = (id: string, priv = true) => getJSON<SurveyDoc>(`/surveys/${id}${priv ? "?include_private=1" : ""}`);
export const getTranscript = (id: string) => getJSON<{ table_id: string; question_id: string; seq: number; message_id: string; speaker: string; speaker_id: number | null; text: string; t: number }[]>(`/surveys/${id}/transcript`);
export const getAgentDetail = (id: string, aid: number) => getJSON<{ items: { kind: string; t: number; private: boolean; payload: Record<string, any> }[] }>(`/surveys/${id}/agents/${aid}`);

/** Live room frames: subscribes to one survey on the /live socket (old clients ignore these types). */
export function subscribeSurvey(id: string, onFrame: (f: Record<string, any>) => void): () => void {
  let ws: WebSocket | null = null;
  let stopped = false;
  const open = () => {
    if (stopped) return;
    try { ws = new WebSocket(liveUrl()); } catch { return; }
    ws.onopen = () => ws?.send(JSON.stringify({ type: "sub", survey_id: id }));
    ws.onmessage = (e) => {
      try {
        const m = JSON.parse(String(e.data));
        if (m && typeof m.type === "string" && m.type.startsWith("survey") && m.survey_id === id) onFrame(m);
      } catch { /* ignore */ }
    };
    ws.onclose = () => { if (!stopped) setTimeout(open, 3000); };
  };
  open();
  return () => { stopped = true; ws?.close(); };
}

export interface Bubble { message_id: string; speaker: number | "moderator"; text: string; age: number }
export interface RoomState {
  phase: "gathering" | "question" | "discussion" | "ballot" | "results";
  question_id: string | null;
  qIndex: number;
  bubbles: Record<string, Bubble[]>;           // table → last ≤ 3 public messages (newest last)
  speaker: Record<string, number | "moderator" | null>;
  ballots: Set<number>;                        // agents done with the current question
  notes: Record<number, string>;               // survey mode: reason note cards
  cardSeat: Record<string, number>;            // question card position (seat index) per table
  transcript: Record<string, Item[]>;
}

/** Room state after the first `upto` items (items sorted by dt). Bubbles are public messages only. */
export function roomState(items: Item[], upto: number, tables: TableDef[]): RoomState {
  const st: RoomState = { phase: "gathering", question_id: null, qIndex: -1, bubbles: {}, speaker: {}, ballots: new Set(), notes: {}, cardSeat: {}, transcript: {} };
  for (const t of tables) { st.bubbles[t.table_id] = []; st.speaker[t.table_id] = null; st.transcript[t.table_id] = []; st.cardSeat[t.table_id] = -1; }
  const qs: string[] = [];
  for (let i = 0; i < Math.min(upto, items.length); i++) {
    const it = items[i];
    const tid = it.table_id ?? it.payload.table_id;
    if (it.kind === "survey_phase") {
      const ph = it.payload.phase as RoomState["phase"];
      if (it.payload.question_id && it.payload.question_id !== st.question_id && ph === "question") {
        st.question_id = it.payload.question_id;
        if (!qs.includes(st.question_id!)) qs.push(st.question_id!);
        st.qIndex = qs.length - 1;
        st.ballots = new Set();
        for (const k of Object.keys(st.bubbles)) { st.bubbles[k] = []; st.speaker[k] = null; st.cardSeat[k] = -1; }
      }
      st.phase = ph;
      continue;
    }
    if (it.kind === "message" && tid) {
      const b = st.bubbles[tid] ?? (st.bubbles[tid] = []);
      b.push({ message_id: it.payload.message_id, speaker: it.payload.speaker, text: it.payload.text, age: 0 });
      if (b.length > 3) b.shift();
      st.speaker[tid] = it.payload.speaker;
      (st.transcript[tid] ?? (st.transcript[tid] = [])).push(it);
      const seats = tables.find((t) => t.table_id === tid)?.seats ?? [];
      if (typeof it.payload.speaker === "number") st.cardSeat[tid] = seats.indexOf(it.payload.speaker);
    }
    if (it.kind === "survey_answer" && it.agent_id != null) {
      st.ballots.add(it.agent_id);
      if (it.payload.written) st.notes[it.agent_id] = String(it.payload.reason ?? "");
      const seats = tid ? tables.find((t) => t.table_id === tid)?.seats ?? [] : [];
      if (tid) st.cardSeat[tid] = seats.indexOf(it.agent_id);
    }
  }
  if (upto >= items.length && items.length) st.phase = "results";
  return st;
}

/** Index range for a phase of the first question (visual-test hook `surveyRoom(id, phase, progress)`). */
export function phaseIndex(items: Item[], phase: string, progress: number): number {
  if (phase === "results") return items.length;
  if (phase === "recruiting") return 0;
  const start = items.findIndex((it) => it.kind === "survey_phase" && it.payload.phase === phase);
  if (start < 0) return 0;
  const next = phase === "discussion" ? "ballot" : phase === "ballot" ? "question" : "discussion";
  let end = items.findIndex((it, i) => i > start && it.kind === "survey_phase" && it.payload.phase === next);
  if (end < 0) end = items.length;
  return Math.round(start + 1 + (end - start - 1) * Math.max(0, Math.min(1, progress)));
}

/** Reading-speed pacing for replay: ms to show an item at 1×. */
export function paceMs(it: Item): number {
  if (it.kind === "message") return Math.max(1400, Math.min(5200, String(it.payload.text ?? "").length * 45));
  if (it.kind === "survey_answer") return it.payload.written ? 900 : 140;
  return 60;
}

/** Merge two tables' item lists by dt (stable). */
export function mergeItems(items: Item[]): Item[] {
  return items.map((it, i) => ({ it, i })).sort((a, b) => a.it.dt - b.it.dt || a.i - b.i).map((x) => x.it);
}
