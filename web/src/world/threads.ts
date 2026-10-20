import { getJSON } from "../lib/api";

/** Map "threads" (Phase I): relationship lines for the selected person, dotted lines for conversations happening now. */
export interface TalkLine { a: number; b: number; topic: string; t0: number }
export const TALK_TTL_MIN = 20;
export const liveTalks = new Map<string, TalkLine>();

/** A `talk` live event opened a conversation (remote chats are not drawn: the two are not together). */
export function onTalk(e: Record<string, unknown>, nowSim: number): void {
  if (typeof e.a !== "number" || typeof e.b !== "number" || e.place === "on WhatsApp") return;
  liveTalks.set(String(e.session_id ?? `${e.a}-${e.b}-${nowSim}`), { a: e.a, b: e.b, topic: String(e.topic ?? ""), t0: nowSim });
  if (liveTalks.size > 400) liveTalks.delete(liveTalks.keys().next().value as string);
}

/** Drop conversations older than 20 sim minutes. */
export function pruneTalks(nowSim: number): void {
  for (const [k, v] of liveTalks) if (nowSim - v.t0 > TALK_TTL_MIN || nowSim < v.t0 - 1) liveTalks.delete(k);
}

/** Everyone the selected person knows (fetched once per profile open, cached). */
const relCache = new Map<number, number[]>();
export async function relationsOf(id: number): Promise<number[]> {
  const hit = relCache.get(id);
  if (hit) return hit;
  const d = await getJSON<{ relationships: { a: number; b: number }[] }>(`/agents/${id}`);
  const ids = Array.from(new Set(d.relationships.map((r) => (r.a === id ? r.b : r.a))));
  relCache.set(id, ids);
  return ids;
}
