/** Launch Studio data: API calls (INTERFACES §5) and one view model for fixture mode and live mode. */
import { create } from "zustand";
import { getJSON } from "./api";
import { isVisualTest } from "./visualTest";
import type { FixtureProduct } from "../visual-fixtures/types";

export type Risk = "red" | "amber" | "green";
export type Step = "details" | "content" | "understand" | "plan" | "ready";
export const STEPS: [Step, string][] = [["details", "Details"], ["content", "Content"], ["understand", "Understanding"], ["plan", "Plan"], ["ready", "Ready"]];
export const KINDS = ["hoarding", "bus_shelter", "reel", "social_post", "newspaper", "store_display", "reviewer_kit"] as const;
export type Kind = (typeof KINDS)[number];

/* ---------------------------------------------------------------- API shapes (shared/schemas/product.py) */
export interface ApiStimulus { creative_id: string; salience: number; clarity: number; hook: string; claims_carried: string[]; tone: string; readable_at_distance: boolean; description: string }
export interface ApiCreative { creative_id: string; product_id: string; kind: Kind; title: string; text: string | null; transcript: string | null; scenes: string[]; image_uri: string | null; stimulus: ApiStimulus | null; screened: boolean }
export interface ApiAudience { description: string; filter: Record<string, unknown>; count: number }
export interface ApiPlannedSite { site_id: string; facing: number; creative_id: string; est_target_ots_day: number; reason: string }
export interface ApiPlan { sites: ApiPlannedSite[]; reel: { creative_id?: string | null; audience_size?: number; impressions_day?: number; freq_cap?: number }; newspaper_days: number[]; reviewers: number[]; community_seed: { forum?: string; title?: string }; stores: string[]; flight_days: number; generated_day: number }
export interface GraphNodeIn { id: string; label: string; type: string; desc: string; source: string; risk?: Risk; degree?: number }
export interface GraphIn { nodes: GraphNodeIn[]; edges: { source: string; target: string; rel: string }[] }
export interface ApiProduct {
  product_id: string; name: string; brand: string; category: string; price_inr: number; launch_offer: string | null;
  features: string[]; claims: string[]; target_personas: string[]; audience: ApiAudience[];
  strategy: { goal?: string; key_message?: string; channels?: string[]; flight_days?: number; intensity?: "low" | "medium" | "high"; stores?: string[] };
  creatives: ApiCreative[]; plan: ApiPlan | null; status: "draft" | "ready" | "live" | "ended"; color: string; launched_at_t: number | null;
  understanding: { summary?: string; claims?: { text: string; source: string; risk: Risk; reason: string }[] } | null; graph: GraphIn | null;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = ((await r.json()) as { detail?: string }).detail ?? msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return (await r.json()) as T;
}

export const studioApi = {
  list: () => getJSON<ApiProduct[]>("/products"),
  get: (id: string) => getJSON<ApiProduct>(`/products/${id}`),
  create: (b: Partial<ApiProduct>) => send<ApiProduct>("POST", "/products", b),
  patch: (id: string, b: Partial<ApiProduct>) => send<ApiProduct>("PATCH", `/products/${id}`, b),
  addCreative: (id: string, b: { kind: Kind; title: string; text?: string; transcript?: string; scenes?: string[]; image_uri?: string }) =>
    send<{ creative: ApiCreative; flagged: string[] }>("POST", `/products/${id}/creatives`, b),
  upload: async (id: string, kind: Kind, file: File): Promise<string> => {
    const u = await send<{ upload_url: string; uri: string }>("POST", `/products/${id}/uploads`, { kind, filename: file.name });
    const r = await fetch(u.upload_url, { method: "PUT", body: file, headers: { "Content-Type": file.type || "application/octet-stream" } });
    if (!r.ok) throw new Error(`upload ${r.status}`);
    return u.uri;
  },
  audience: (id: string, personas?: string[]) => send<{ audience: ApiAudience[]; total: number }>("POST", `/products/${id}/audience`, { personas }),
  understand: (id: string) => send<unknown>("POST", `/products/${id}/understand`),
  plan: (id: string) => send<ApiPlan>("POST", `/products/${id}/plan`),
  ready: (id: string) => send<ApiProduct>("POST", `/products/${id}/ready`),
  launch: (id: string) => send<ApiProduct>("POST", `/products/${id}/launch`),
};

/* ---------------------------------------------------------------- view model */
/** One content tile: [kind, title, headline, sub, background, salience (0 = no salience bar)]. */
export type Asset = [string, string, string, string, string, number];
export interface ClaimV { text: string; risk: Risk; reason: string; source: string }
export interface SiteV { site_id: string; facing: number; reason: string; ots: number }
export interface GraphNodeV { id: string; label: string; type: string; desc: string; src: string; risk?: Risk }
export interface GraphV { nodes: GraphNodeV[]; edges: [string, string, string][] }
export interface StudioProduct {
  id: string; name: string; brand: string; cat: string; price: number; hex: string; status: FixtureProduct["status"];
  launched: number | null; tagline: string; offer: string; features: string[]; claims: ClaimV[]; personas: string[];
  audienceCount: number; audienceDesc: string; flight: number; intensity: "low" | "medium" | "high"; storeNames: string[];
  assets: Asset[]; reelRows: [string, string, string][]; creativeNotes: Record<string, string>; graph: GraphV | null;
  sites: SiteV[]; reel: number; reviewers: number; newspaperDays: number[]; contentCount: number; understood: boolean;
  api: ApiProduct | null;
}

const KIND_BG: Record<string, string> = {
  hoarding: "linear-gradient(160deg,#0b1020,#1e1b4b 55%,{c})", bus_shelter: "linear-gradient(160deg,#111827,#7c2d12)",
  reel: "linear-gradient(160deg,#020617,#334155 60%,#f59e0b)", social_post: "linear-gradient(160deg,#1f2937,#475569)",
  newspaper: "linear-gradient(160deg,#e5e7eb,#9ca3af)", store_display: "linear-gradient(160deg,#0f172a,{c})",
  reviewer_kit: "linear-gradient(160deg,#1e293b,#334155)",
};
const KIND_TITLE: Record<string, string> = {
  hoarding: "Hoarding poster", bus_shelter: "Bus-shelter poster", reel: "Reel", social_post: "Social post", newspaper: "Newspaper ad",
  store_display: "Store display", reviewer_kit: "Reviewer kit",
};
export const kindTitle = (k: string): string => KIND_TITLE[k] ?? k;

/** Store id → display name (fictional stores). */
export const STORE_NAMES: Record<string, string> = {
  "ST-DIGITAL-BAZAAR": "Digital Bazaar", "ST-ELECTROHUB": "ElectroHub", "ST-PHONEWORLD": "PhoneWorld", "ST-SHOPKART": "ShopKart",
};

/** API product → view model. */
export function fromApi(p: ApiProduct): StudioProduct {
  const und = p.understanding?.claims ?? [];
  const claims: ClaimV[] = p.claims.map((c) => {
    const u = und.find((x) => x.text === c);
    return { text: c, risk: u?.risk ?? "amber", reason: u?.reason ?? "Not checked yet — run Understanding", source: u?.source ?? "details" };
  });
  for (const u of und) if (!p.claims.includes(u.text)) claims.push({ text: u.text, risk: u.risk, reason: u.reason, source: u.source });
  const assets: Asset[] = p.creatives.map((c) => [c.kind, c.title || kindTitle(c.kind), (c.text || c.transcript || c.title || "").split("\n")[0].slice(0, 60),
    c.kind === "reel" ? `${c.scenes.length} scenes · transcript` : c.image_uri ? "image + copy" : "copy", (KIND_BG[c.kind] ?? KIND_BG.social_post).replace("{c}", p.color),
    c.kind === "reviewer_kit" ? 0 : c.stimulus?.salience ?? 0.0001]);
  const reelC = p.creatives.find((c) => c.kind === "reel");
  const reelRows: [string, string, string][] = reelC ? reelC.scenes.map((s, i) => [`0:${String(i * 3).padStart(2, "0")}`, s,
    (reelC.transcript ?? "").split(/(?<=[.!?])\s+/)[i] ?? ""]) : [];
  const notes: Record<string, string> = {};
  for (const c of p.creatives) if (c.stimulus) notes[c.creative_id] = c.stimulus.description;
  const aud = p.audience.reduce((n, a) => n + a.count, 0);
  const plan = p.plan;
  const g = p.graph;
  return {
    id: p.product_id, name: p.name, brand: p.brand, cat: p.category, price: p.price_inr, hex: p.color, status: p.status,
    launched: p.launched_at_t, tagline: p.strategy.key_message ?? "", offer: p.launch_offer ?? "", features: p.features, claims,
    personas: p.target_personas, audienceCount: plan?.reel.audience_size ?? aud,
    audienceDesc: p.audience.map((a) => a.description).join(" · "), flight: plan?.flight_days ?? p.strategy.flight_days ?? 14,
    intensity: p.strategy.intensity ?? "medium", storeNames: (plan?.stores ?? p.strategy.stores ?? []).map((s) => STORE_NAMES[s] ?? s),
    assets, reelRows, creativeNotes: notes,
    graph: g ? { nodes: g.nodes.map((n) => ({ id: n.id, label: n.label, type: n.type, desc: n.desc, src: n.source, risk: n.risk })), edges: g.edges.map((e) => [e.source, e.target, e.rel]) } : null,
    sites: (plan?.sites ?? []).map((s) => ({ site_id: s.site_id, facing: s.facing, reason: s.reason, ots: s.est_target_ots_day })),
    reel: plan?.reel.audience_size ?? 0, reviewers: plan?.reviewers.length ?? 0, newspaperDays: plan?.newspaper_days ?? [],
    contentCount: p.creatives.length, understood: !!p.understanding, api: p,
  };
}

/** Fixture shapes (mockup-fixtures.json → studio, graph, products). */
export interface StudioFixtures {
  assets: Record<string, Asset[]>; reel: [string, string, string][]; claims: [string, Risk, string, string][];
  reasons: Record<string, string>; otsPerDay: Record<string, number>;
}
export interface GraphFixture { types: Record<string, { c: string; n: string }>; nodes: [string, string, string, string, string, Risk?][]; edges: [string, string, string][] }
type FxProduct = FixtureProduct & { cat?: string; tagline?: string; offer?: string };

const NOVA_NOTES: Record<string, string> = {
  hoarding: "Dark, single product shot, 3-word headline. Readable at 60 m; strong at night.",
  bus_shelter: "Price-led; readable at bus-stop distance; weak hook.",
  reel: "Strong 2-second hook, city at night, captions on. Best for photographers.",
  social_post: "Text-heavy carousel; relevant to longevity-minded buyers.",
  newspaper: "Carries the riskiest claim in the headline.", store_display: "Invites hands-on night-mode demo.",
};

/** Fixture product → view model (visual-test mode reproduces the mockup's demo content). */
export function fromFixture(p: FxProduct, sf: StudioFixtures, g: GraphFixture): StudioProduct {
  const assets = sf.assets["nova-x1"] ?? [];
  const nova = p.id === "nova-x1";
  return {
    id: p.id, name: p.name, brand: p.brand, cat: p.cat ?? "Smartphone", price: p.price, hex: p.hex, status: p.status, launched: p.launched,
    tagline: p.tagline ?? "", offer: p.offer ?? "",
    features: ["200MP main camera with multi-frame night mode", "5,000 mAh battery · 45 W charging", "6.7\" 120 Hz LTPO display", "7 years of OS updates · titanium frame"],
    claims: sf.claims.map(([text, risk, reason, source]) => ({ text, risk, reason, source })),
    personas: ["Mobile photographers", "Young tech professionals", "Night-life & food bloggers", "Upgraders with phones > 4 yrs"],
    audienceCount: 420, audienceDesc: "interests ∋ photography or tech · age 22–40 · income ≥ ₹50k · or phone age > 4 yrs",
    flight: 21, intensity: "high", storeNames: p.stores, assets, reelRows: sf.reel,
    creativeNotes: Object.fromEntries(assets.map((a) => [a[0], NOVA_NOTES[a[0]] ?? ""])),
    graph: { nodes: g.nodes.map(([id, label, type, desc, src, risk]) => ({ id, label, type, desc, src, risk })), edges: g.edges },
    sites: p.sites.map(([sid, f]) => ({ site_id: sid, facing: f, reason: sf.reasons[sid] ?? "High share of target agents passing at slow speed.", ots: sf.otsPerDay[sid] ?? 700 })),
    reel: p.reel, reviewers: p.reviewers, newspaperDays: [1, 3, 5], contentCount: nova ? 7 : 5, understood: true, api: null,
  };
}

/* ---------------------------------------------------------------- store */
interface StudioStore {
  products: StudioProduct[];
  loaded: boolean;
  error: string | null;
  graphTypes: Record<string, { c: string; n: string }>;
  load: () => Promise<void>;
  upsert: (p: ApiProduct) => StudioProduct;
}

export const DEFAULT_TYPES: Record<string, { c: string; n: string }> = {
  product: { c: "#e7edf5", n: "Product" }, feature: { c: "#2dd4bf", n: "Feature" }, claim: { c: "#f87171", n: "Claim" },
  concern: { c: "#60a5fa", n: "Concern" }, competitor: { c: "#f472b6", n: "Competitor" }, segment: { c: "#a78bfa", n: "Audience segment" },
  creative: { c: "#fb923c", n: "Creative" }, entity: { c: "#94a3b8", n: "Brand / store" },
};

export const useStudio = create<StudioStore>((set, get) => ({
  products: [],
  loaded: false,
  error: null,
  graphTypes: DEFAULT_TYPES,
  load: async () => {
    if (isVisualTest) {
      const mod = (await import("../visual-fixtures/mockup-fixtures.json")) as unknown as { default?: unknown };
      const f = (mod.default ?? mod) as { products: FxProduct[]; studio: StudioFixtures; graph: GraphFixture };
      set({ products: f.products.map((p) => fromFixture(p, f.studio, f.graph)), loaded: true, graphTypes: f.graph.types });
      return;
    }
    try {
      set({ products: (await studioApi.list()).map(fromApi), loaded: true, error: null });
    } catch (e) {
      set({ loaded: true, error: String((e as Error).message ?? e) });
    }
  },
  upsert: (p) => {
    const v = fromApi(p);
    const cur = get().products;
    const i = cur.findIndex((x) => x.id === v.id);
    set({ products: i >= 0 ? cur.map((x, j) => (j === i ? v : x)) : [...cur, v] });
    return v;
  },
}));

/** Dock/world summary shape (FixtureProduct) of a studio product. */
export function toWorldProduct(p: StudioProduct): FixtureProduct {
  return { id: p.id, name: p.name, brand: p.brand, price: p.price, hex: p.hex, status: p.status, launched: p.launched,
    sites: p.sites.map((s) => [s.site_id, s.facing]), stores: p.storeNames, reel: p.reel, reviewers: p.reviewers };
}
