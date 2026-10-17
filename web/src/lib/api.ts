import type { AgentProfile, AgentState, Belief } from "../types/generated";

/** REST helpers for the api service (base `/api`, proxied to :8000 by vite). */
const BASE = "/api";

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return (await r.json()) as T;
}

export async function putJSON<T>(path: string, body: unknown): Promise<T | null> {
  const r = await fetch(`${BASE}${path}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.headers.get("content-type")?.includes("json") ? ((await r.json()) as T) : null;
}

export interface RelationRow {
  a: number; b: number; kind: string; closeness: number; channel: string; last_t?: number | null;
  other?: { agent_id: number; name: string; age: number; occupation: string };
}
export interface AgentDetail {
  profile: AgentProfile & { household_size?: number; workplace_name?: string };
  state: AgentState;
  relationships: RelationRow[];
  beliefs: Belief[];
}
export interface PeopleRow {
  agent_id: number; name: string; age: number; occupation: string; income_band: string;
  phone: { brand: string; tier?: string; age_years: number; condition: string };
  stages: Record<string, string | { stage: string; attitude?: number }>; watched: boolean; activity?: string;
}
export interface PeoplePage { rows: PeopleRow[]; total: number; phone_old_count?: number; watched_count?: number }
export interface PeopleQuery { q: string; age: string; income: string; product: string; phoneOld: boolean; page: number }

/** Build the GET /agents query string (only set filters are sent). */
export function peopleQS(f: PeopleQuery, pageSize = 15): string {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.age) p.set("age", f.age);
  if (f.income) p.set("income", f.income);
  if (f.product) {
    const [product, stage] = f.product.split(":");
    p.set("product", product);
    if (stage) p.set("stage", stage);
  }
  if (f.phoneOld) {
    p.set("phone_age_gt", "5");
    p.set("sort", "-phone_age");
  }
  p.set("page", String(f.page));
  p.set("page_size", String(pageSize));
  return p.toString();
}

const detailCache = new Map<number, Promise<AgentDetail>>();

/** GET /agents/{id}, cached for the session (refetch with fresh=true). */
export function getAgent(id: number, fresh = false): Promise<AgentDetail> {
  if (fresh || !detailCache.has(id)) {
    const p = getJSON<AgentDetail>(`/agents/${id}`);
    p.catch(() => detailCache.delete(id));
    detailCache.set(id, p);
  }
  return detailCache.get(id)!;
}
