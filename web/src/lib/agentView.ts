import type { AgentDetail } from "./api";
import type { Fixtures, FixtureAgent } from "../visual-fixtures/types";

/** One normalised agent for the hover card and the profile drawer (from fixtures or GET /agents/{id}). */
export interface AgentView {
  id: number; name: string; age: number; job: string; work: string | null; shirt: string; act: string; place: string | null;
  special: string | null; watch: boolean; interests: string[];
  phone: { brand: string; tier: string; age: number; cond: string; batt: number; satisfaction: string; bought: string };
  beliefs: Record<string, { stage: string; att: number; first?: string }>;
  bio: string; income: string; savings: number; card: boolean; emi: boolean; media: string; disclosure: string; household: number;
  big5: [string, number][]; needs: [string, number, string][]; today: string;
  friends: { id: number; name: string; job: string; rel: string; c: number; shirt: string }[];
  history: string[];
}

export const STAGE_COL: Record<string, string> = {
  aware: "#94a3b8", curious: "#2dd4bf", researching: "#60a5fa", inquiring: "#f5b041", deciding: "#f472b6",
  purchased: "#facc15", postponed: "#a78bfa", rejected: "#f87171",
};

/** Same seeded PRNG as the mockup (used for fixture-only values the mockup derives randomly). */
export function mulberry(a: number): () => number {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const initials = (n: string): string => n.split(" ").map((s) => s[0]).join("").slice(0, 2);

const ACT: Record<string, string> = {
  sleep: "Sleeping", home: "At home", commute: "Commuting", work: "Working", store_shift: "Working", offmap_work: "Working",
  school: "At school", college: "At college", eat: "Eating out", cafe: "At a café", gym: "At the gym", park: "In the park",
  shop: "Shopping", metro: "On the metro",
};

/** Engine `act` code → UI label (commute depends on mode). */
export function actLabel(act: string, mode?: string): string {
  if (act === "commute") return mode === "bus" ? "On the bus" : mode === "two_wheeler" || mode === "auto" ? "Riding" : mode === "car" ? "Driving" : mode === "metro" ? "On the metro" : "Commuting";
  return ACT[act] ?? (act ? act[0].toUpperCase() + act.slice(1) : "");
}

/** Monthly income (₹) → band label, mockup thresholds. */
export function incomeLabel(inc: number): string {
  return inc > 200000 ? ">₹2L" : inc > 100000 ? "₹1–2L" : inc > 50000 ? "₹50k–1L" : inc > 25000 ? "₹25–50k" : "<₹25k";
}
const BAND: Record<string, string> = { "<25k": "<₹25k", "25-50k": "₹25–50k", "50k-1L": "₹50k–1L", "1-2L": "₹1–2L", ">2L": ">₹2L" };
export const bandLabel = (b: string): string => BAND[b] ?? b;

const B5 = ["Openness", "Conscientiousness", "Extraversion", "Agreeableness", "Neuroticism"];

/** Fixture agent → view (matches the mockup's profileHTML / hoverHTML values). */
export function fromFixture(fx: Fixtures, id: number, watch?: boolean): AgentView | null {
  const all = fx.agents as (FixtureAgent & Record<string, any>)[];
  const a = all.find((x) => x.id === id);
  if (!a) return null;
  const meera = id === fx.featured.id;
  const r = mulberry(id * 7);
  const work: string | null = typeof a.work === "string" ? a.work : (a.work?.name ?? null);
  const friends = ((a.friends ?? []) as { id: number; rel: string; c: number }[]).map((f) => {
    const b = all.find((x) => x.id === f.id);
    return { id: f.id, name: b?.name ?? `Agent ${f.id}`, job: b?.job ?? "", rel: f.rel, c: f.c, shirt: b?.look.shirt ?? "#94a3b8" };
  });
  const first = a.name.split(" ")[0];
  const bio = meera
    ? "I'm Meera, 29, a UX designer at a payments startup off 80 Feet Road. Sundays are for street-photo walks. I compare everything before I buy — and I don't talk about money with friends."
    : a.name.startsWith("Ravi Kumar")
      ? "I'm Ravi, 41. I run the pharmacy on 100 Feet Road with my brother. Long days, cricket on the radio. My phone is old but it still works — mostly."
      : `I'm ${first}, ${a.age}. ${a.job}${work ? " at " + work : ""}. I like ${a.interests.slice(0, 2).join(" and ")}${a.interests[2] ? ", and " + a.interests[2] : ""}.`;
  const ph = a.phone;
  return {
    id, name: a.name, age: a.age, job: a.job, work, shirt: a.look.shirt, act: a.act, place: a.place, special: a.special ?? null,
    watch: watch ?? a.watch, interests: a.interests, beliefs: a.beliefs,
    phone: {
      brand: ph.brand, tier: ph.tier, age: ph.age, cond: ph.cond, batt: ph.batt,
      satisfaction: meera ? "0.48 — night camera is poor" : (0.4 + mulberry(id)() * 0.5).toFixed(2),
      bought: meera ? "PhoneWorld · ₹21,999 · 3.2 yrs ago" : `~${ph.age} yrs ago`,
    },
    bio, income: incomeLabel(a.income), savings: a.savings, card: a.card, emi: a.emi,
    media: `Instagram, YouTube${a.reddit ? ", r/BangaloreTech" : ""}${a.newspaper ? ", morning paper" : ""}`,
    disclosure: meera ? "opinions open · money private" : "opinions open · feelings private",
    household: 2 + (id % 4),
    big5: B5.map((n) => [n, r()]),
    needs: [["Energy", 0.62, "var(--green)"], ["Social", 0.48, "var(--blue)"], ["Fatigue", 0.31, "var(--red)"], ["Stimulation", 0.55, "var(--amber)"]],
    today: meera ? "work → lunch at Brew & Byte → photo edit → r/BangaloreTech" : `home → ${work ?? "errands"} → home`,
    friends,
    history: meera ? ["Day 13 · battery died mid photo-walk (life event: slow)", "3.2 years ago · bought at PhoneWorld"]
      : [ph.cond === "cracked" ? "Screen cracked recently" : "No recent events"],
  };
}

const SHIRTS = ["#14b8a6", "#f59e0b", "#3b82f6", "#ef4444", "#8b5cf6", "#22c55e", "#ec4899", "#64748b", "#eab308", "#0ea5e9"];
export const shirtFor = (id: number): string => SHIRTS[id % SHIRTS.length];

/** API detail → view. */
export function fromDetail(d: AgentDetail, watch: boolean): AgentView {
  const p = d.profile;
  const st = d.state;
  const ph = (p.possessions?.phone ?? {}) as Record<string, any>;
  const per = p.persona;
  const big = (per?.big5 ?? {}) as Record<string, number>;
  const disc = (per?.disclosure ?? {}) as Record<string, number>;
  const open = Object.entries(disc).filter(([, v]) => v >= 0.5).map(([k]) => `${k} open`);
  const priv = Object.entries(disc).filter(([, v]) => v < 0.5).map(([k]) => `${k} private`);
  const platforms = Array.from(new Set((p.media?.feed_sessions ?? []).map((s) => String(s[2])))).map((x) => x[0]?.toUpperCase() + x.slice(1));
  const n = (k: string) => Number((st?.needs as Record<string, number> | undefined)?.[k] ?? 0);
  const beliefs: AgentView["beliefs"] = {};
  for (const b of d.beliefs ?? []) beliefs[b.subject] = { stage: b.stage, att: b.attitude, first: String(b.first_heard?.channel ?? "") || undefined };
  const age = Number(ph.age_years ?? 0);
  const plan = (st?.plan ?? []).map((x) => actLabel(String(x.act ?? x.activity ?? ""))).filter(Boolean);
  const work = p.workplace_name ?? null;
  return {
    id: p.agent_id, name: p.name, age: p.age, job: p.occupation, work, shirt: shirtFor(p.agent_id),
    act: actLabel(st?.activity ?? "", st?.mode), place: (st as { place_name?: string } | undefined)?.place_name ?? null, special: p.special_role && p.special_role !== "none" ? p.special_role : null,
    watch, interests: per?.interests ?? [], beliefs,
    phone: {
      brand: String(ph.brand ?? "—"), tier: String(ph.tier ?? ""), age, cond: String(ph.condition ?? "ok"),
      batt: Number(ph.battery_health ?? 1), satisfaction: Number(ph.satisfaction ?? 0).toFixed(2), bought: `~${age} yrs ago`,
    },
    bio: per?.bio_first_person ?? "", income: bandLabel(p.income_band), savings: p.money?.savings_inr ?? 0,
    card: (p.money?.credit_card_limit_inr ?? 0) > 0, emi: !!p.money?.emi_eligible,
    media: [...platforms, p.media?.community ? "r/BangaloreTech" : "", p.media?.newspaper ? "morning paper" : ""].filter(Boolean).join(", ") || "—",
    disclosure: [...open.slice(0, 1), ...priv.slice(0, 1)].join(" · ") || "—",
    household: p.household_size ?? 1,
    big5: (["O", "C", "E", "A", "N"] as const).map((k, i) => [B5[i], Number(big[k] ?? 0)]),
    needs: [["Energy", n("energy"), "var(--green)"], ["Social", n("social"), "var(--blue)"], ["Fatigue", n("fatigue"), "var(--red)"], ["Stimulation", n("stimulation"), "var(--amber)"]],
    today: plan.length ? plan.join(" → ") : "—",
    friends: (d.relationships ?? []).map((r) => {
      const oid = r.a === p.agent_id ? r.b : r.a;
      return { id: oid, name: r.other?.name ?? `Agent ${oid}`, job: r.other?.occupation ?? "", rel: r.kind, c: r.closeness, shirt: shirtFor(oid) };
    }).sort((x, y) => y.c - x.c),
    history: ((ph.history ?? []) as Record<string, unknown>[]).map((h) => String(h.label ?? h.type ?? JSON.stringify(h))),
  };
}
