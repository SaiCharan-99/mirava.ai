import { getJSON } from "./api";
import { simClock } from "../world/tracks";
import { mergeItems, type Item, type TableDef } from "./survey";

/** Focus groups (Phases D–G): the active survey, the shared timer, live room state, sessions list, results. */
export interface Counts { invited: number; replied: number; accepted: number; waitlist: number; walking: number; arrived: number }
export type FocusStatus = "draft" | "recruiting" | "gathering" | "in_session" | "finishing" | "completed" | "cancelled";
export interface ActiveSurvey {
  survey_id: string; title: string; mode?: string; status: FocusStatus; start_at_t: number | null; counts: Counts;
  q_index?: number; n_questions?: number; viewers?: number; attended?: number;
  now_t?: number; sim_min_per_real_s?: number; seconds_to_start?: number | null;
}
export interface SessionRow {
  survey_id: string; title: string; mode: string; status: FocusStatus; wave?: number; product_name?: string | null;
  start_at_t?: number | null; start_label?: string | null; completed_t?: number | null; n_attended?: number | null; max_participants?: number;
}
export interface LiveMsg { message_id: string; speaker: number | "moderator"; text: string; seq: number; question_id: string; t: number }
export interface LivePrivate { agent_id: number; kind: string; question_id: string; text: string; t: number; private: true }
export interface LiveState {
  survey_id: string; status: FocusStatus; phase: string; start_at_t: number; now_t: number; q_index: number; n_questions: number;
  counts: Counts; tables: { table_id: string; seats: number[] }[]; messages: Record<string, LiveMsg[]>;
  ballots: Record<string, number[]>; private: LivePrivate[]; arrived_ids: number[]; viewers: number; replies?: Reply[];
  sim_min_per_real_s: number; seconds_to_start: number | null;
}

export const EMPTY_COUNTS: Counts = { invited: 0, replied: 0, accepted: 0, waitlist: 0, walking: 0, arrived: 0 };
export const getActive = () => getJSON<ActiveSurvey | null>("/surveys/active");
export const listSessions = () => getJSON<SessionRow[]>("/surveys");
export const getLiveState = (id: string, table?: string, priv = true) =>
  getJSON<LiveState>(`/surveys/${id}/live-state?include_private=${priv ? 1 : 0}${table ? `&table=${encodeURIComponent(table)}` : ""}`);

/** Real seconds until the start, from the shared world clock (every viewer computes the same number). */
export function secondsLeft(startAt: number | null | undefined, nowSim: number, rate: number): number {
  if (startAt == null) return 0;
  return Math.max(0, (startAt - nowSim) / Math.max(1e-6, rate));
}
export const secondsToStart = (startAt: number | null | undefined) => secondsLeft(startAt, simClock.now(), simClock.rate);

export function mmss(sec: number): string {
  const s = Math.max(0, Math.ceil(sec));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Where a session's card leads: builder, countdown, room or results. */
export function sessionRoute(id: string, status: FocusStatus): string {
  if (status === "draft") return "/insights/focus";
  if (status === "recruiting" || status === "gathering") return `/insights/focus/${id}/wait`;
  if (status === "in_session" || status === "finishing") return `/insights/focus/${id}/room`;
  return `/insights/focus/${id}/results`;
}

/** Banner state for the active survey (null = no banner). */
export type BannerKind = "countdown" | "live" | "done";
export function bannerKind(a: ActiveSurvey | null, dismissed: (id: string) => boolean): BannerKind | null {
  if (!a) return null;
  if (a.status === "recruiting" || a.status === "gathering") return "countdown";
  if (a.status === "in_session" || a.status === "finishing") return "live";
  if (a.status === "completed" && !dismissed(a.survey_id)) return "done";
  return null;
}

const KEY = "mirava.focus.seen";
export function dismissedDone(id: string): boolean {
  try { return (JSON.parse(localStorage.getItem(KEY) ?? "[]") as string[]).includes(id); } catch { return false; }
}
export function dismissDone(id: string): void {
  try { const l = JSON.parse(localStorage.getItem(KEY) ?? "[]") as string[]; localStorage.setItem(KEY, JSON.stringify([...l.filter((x) => x !== id), id].slice(-30))); } catch { /* storage blocked */ }
}

/** Preset goodies for the picker (labels ≤ 60 chars; values steer who finds them worth the trip). */
export const GOODIE_PRESETS: { emoji: string; kind: "merch" | "food" | "accessory" | "voucher"; label: string; value_inr: number }[] = [
  { emoji: "🎁", kind: "merch", label: "Mirava goodie bag", value_inr: 300 },
  { emoji: "☕", kind: "food", label: "Coffee at a café nearby", value_inr: 250 },
  { emoji: "📱", kind: "accessory", label: "Phone case + screen guard", value_inr: 600 },
  { emoji: "🎧", kind: "accessory", label: "Lucky draw: earbuds", value_inr: 400 },
  { emoji: "🍫", kind: "food", label: "Snacks at the lounge", value_inr: 150 },
];
export const DEFAULT_GOODIES = ["Mirava goodie bag", "Coffee at a café nearby", "Snacks at the lounge"];
export interface Reply { agent_id: number; name?: string; age?: number; rsvp: string; channel?: string; t?: number; reason?: string; private?: boolean }

/** Everyone's name and age (one request, cached for the session). */
let namesCache: Promise<Record<number, { name: string; age: number }>> | null = null;
export function agentNames(): Promise<Record<number, { name: string; age: number }>> {
  namesCache ??= getJSON<{ rows: { agent_id: number; name: string; age: number }[] }>("/agents?page_size=1000")
    .then((r) => Object.fromEntries(r.rows.map((a) => [a.agent_id, { name: a.name, age: a.age }])))
    .catch((e: unknown) => { namesCache = null; throw e; });
  return namesCache;
}

export interface Edge { from: number; to: number; type: "persuaded" | "went_along" | "pushed_back"; question_id: string }
export interface ReportQ {
  question_id: string; text: string; type: "single" | "multi" | "scale" | "open"; options?: string[] | null;
  scale?: { min: number; max: number; low_label?: string; high_label?: string } | null;
  distribution: Record<string, number>; pre_distribution: Record<string, number>; shift: Record<string, Record<string, number>>;
  by_segment: Record<string, Record<string, number>>; influence: [string, number, string][]; changed: number; n: number; gap: number;
  quotes: { agent_id: number; name?: string; text: string; tag?: string; answer: unknown; changed: boolean; prestance?: unknown }[];
  values_before?: number[]; values_after?: number[]; themes?: { theme: string; n: number; quote: string; agent_id: number }[];
}
export interface Report {
  questions: ReportQ[]; n_attended: number; changed_people?: number; gap_people?: number; edges?: Edge[];
  gap_pairs?: { agent_id: number; name?: string; question_id: string; said: string; answered: unknown; reason: string }[];
  seats?: Record<string, string>; findings?: { title: string; line: string }[]; summaries: Record<string, string>;
  participation_effect: string; notes: string[];
}

/** Sankey ribbons from a prestance → final shift matrix (option order kept; widths in people). */
export function flows(shift: Record<string, Record<string, number>>): [string, string, number][] {
  const out: [string, string, number][] = [];
  for (const [a, row] of Object.entries(shift)) for (const [b, n] of Object.entries(row)) if (n > 0) out.push([a, b, n]);
  return out;
}

export const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

/** Room items rebuilt from the engine's live state: the current question's phases, messages and ballots. */
export function itemsFromLive(live: LiveState, qids: string[]): Item[] {
  const items: Item[] = [];
  const q = Math.max(-1, live.q_index);
  for (let i = 0; i <= q; i++) items.push({ dt: i * 0.001, kind: "survey_phase", agent_id: null, payload: { phase: "question", question_id: qids[i] } });
  const cur = q >= 0 ? qids[q] : null;
  if (cur && live.phase !== "question") items.push({ dt: 0.5, kind: "survey_phase", agent_id: null, payload: { phase: live.phase === "results" ? "ballot" : live.phase, question_id: cur } });
  for (const [tid, msgs] of Object.entries(live.messages)) {
    for (const m of msgs) if (m.question_id === cur) items.push({ dt: m.t + m.seq * 0.001, kind: "message", agent_id: typeof m.speaker === "number" ? m.speaker : null, table_id: tid, payload: { ...m, table_id: tid } });
  }
  for (const [tid, ids] of Object.entries(live.ballots)) for (const a of ids) items.push({ dt: 1e9, kind: "survey_answer", agent_id: a, table_id: tid, payload: { question_id: cur, table_id: tid } });
  return mergeItems(items);
}

/** Tables before the session: whoever has arrived, eight to a table, in arrival order (chairs fill as people come). */
export function arrivalTables(ids: number[], size = 8): TableDef[] {
  const out: TableDef[] = [];
  for (let i = 0; i < ids.length; i += size) out.push({ table_id: `T${out.length + 1}`, seats: ids.slice(i, i + size) });
  return out.length ? out : [{ table_id: "T1", seats: [] }];
}


/** Final counts the engine stores on a completed session (`surveys/{id}.counts`). */
export interface FinalCounts {
  invited?: number; reached?: number; accepted?: number; attended?: number; answers?: number; late?: number;
  no_show?: number; turned_away?: number; gather_timeout?: boolean; why_empty?: "nobody_reached" | "nobody_accepted" | "no_shows";
}

/** Why nobody took part, in plain words (null when someone did). */
export function emptyReason(c: FinalCounts | undefined | null): string | null {
  if (!c || (c.attended ?? 0) > 0) return null;
  const reached = c.reached ?? c.invited ?? 0;
  const yes = c.accepted ?? 0;
  if (c.why_empty === "nobody_reached" || reached === 0) return "Nobody saw the invite before sign-ups closed, so no one could come. Try a later start time or more channels.";
  if (c.why_empty === "nobody_accepted" || yes === 0) return `${reached} people saw the invite but nobody said yes. A better reward, a closer time or a wider audience may help.`;
  const late = c.turned_away ? ` ${c.turned_away} arrived after it had finished and were turned away.` : "";
  const wait = c.gather_timeout ? " The room waited the full gathering time, then started without them." : "";
  return `${yes} said yes but nobody turned up (${c.no_show ?? yes} no-shows).${wait}${late}`;
}

/** Countdown that ticks smoothly between polls: seconds left at fetch time minus real time since. */
export function liveSecondsLeft(secondsAtFetch: number | null | undefined, fetchedAtMs: number, nowMs: number): number {
  if (secondsAtFetch == null) return 0;
  return Math.max(0, secondsAtFetch - (nowMs - fetchedAtMs) / 1000);
}
