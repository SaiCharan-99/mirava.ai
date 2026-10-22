import { create } from "zustand";
import type { Fixtures, FixtureProduct, TickerItem } from "../visual-fixtures/types";

/** Live world stats as streamed by world-engine (`stats` message, INTERFACES §4.4). */
export interface WorldStats {
  agents: number;
  households: number;
  relationships: number;
  conversations_today: number;
  conversations_total: number;
  thoughts_today: number;
  products_live: number;
}

export type Lens = "activity" | "aware" | "sentiment" | "hoardings";
export type SideTab = "now" | "watching" | "products";
export type ProfileTab = "overview" | "relations" | "possessions" | "thoughts" | "conversations" | "memory";
/** One highlight moment (INTERFACES §4.3); fixtures supply only t/title/agent. */
export interface HlMoment { t: number; kind?: string; agent_ids: number[]; x?: number; y?: number; title: string; text?: string; session_id?: string | null }
export interface Highlights { day: number; total: number; moments: HlMoment[] }

/** What a hoarding site shows: a product id or a baseline brand id (`cr`), and the face in use. */
export interface SiteShow { cr: string; facing?: number; flipAt?: number }
/** Launch firework state (`launch-fx` overlay): progress frozen (visual test) or started at t0 (performance.now()). */
export interface LaunchFx { pid: string; hex: string; name: string; sites: string[]; stores: string[]; audience: number[]; t0: number; frozen: number | null }

/** What a hoarding site shows: a product id or a baseline brand id (`cr`), and the face in use. */
export interface SiteShow { cr: string; facing?: number; flipAt?: number }
/** Launch firework state (`launch-fx` overlay): progress frozen (visual test) or started at t0 (performance.now()). */
export interface LaunchFx { pid: string; hex: string; name: string; sites: string[]; stores: string[]; audience: number[]; t0: number; frozen: number | null }

export interface HoverInfo { id: number; sx: number; sy: number; pinned?: boolean }

export interface WorldStore {
  ready: boolean;
  source: "fixtures" | "live";
  t: number;
  stats: WorldStats;
  budget: { used_usd: number; cap_usd: number; slowed?: boolean; calls_today?: number; tokens_today?: number; llm_backend?: string };
  hl: Highlights | null;
  setHighlights: (h: Highlights | null) => void;
  ticker: TickerItem[];
  products: FixtureProduct[];
  siteAssign: Record<string, SiteShow>;
  /** Live lens data: product id → agent id → attitude (agents present are aware). */
  aware: Record<string, Record<number, number>>;
  lensProduct: string | null;
  /** stats.awareness: product id → share of agents aware. */
  awareShare: Record<string, number>;
  /** stats.funnel: live per-product stage counts (replaces fixture-derived Curious+). */
  funnel: Record<string, { aware: number; curious_plus: number; purchased: number }>;
  /** stats.campaigns: paid-campaign flight per product. */
  campaigns: Record<string, { ends_t: number; active: boolean }>;
  fx: LaunchFx | null;
  setLensProduct: (pid: string) => void;
  dayCounts: number[];
  fixtures: Fixtures | null;
  lens: Lens;
  sideTab: SideTab;
  hourOverride: number | null;
  zoomCmd: { kind: "in" | "out" | "fit" | "focus"; x?: number; y?: number; z?: number; seq: number } | null;
  connected: boolean;
  /** Survey Room pin (addendum B9) and agents walking to the venue (📋). */
  surveyPin: { survey_id: string; status: string; name: string; arrived: number; expected: number; x: number; y: number } | null;
  surveyTrips: number[];
  hover: HoverInfo | null;
  profile: { id: number; tab: ProfileTab } | null;
  setHover: (h: HoverInfo | null) => void;
  openProfile: (id: number, tab?: ProfileTab) => void;
  setProfileTab: (tab: ProfileTab) => void;
  closeProfile: () => void;
  setLens: (l: Lens) => void;
  setSideTab: (t: SideTab) => void;
  setHour: (h: number) => void;
  camera: (cmd: Omit<NonNullable<WorldStore["zoomCmd"]>, "seq">) => void;
  loadFixtures: (f: Fixtures) => void;
}

/** Per-day conversation counts for the day timeline (fixture series until world-engine reports real ones). */
function fixtureDayCounts(t: number, today: number): number[] {
  const n = Math.floor(t / 1440);
  return Array.from({ length: n + 1 }, (_, i) => (i === n ? today : Math.round(60 + Math.sin(i * 1.7) * 12 + i * 1.5)));
}

export const useWorld = create<WorldStore>((set, get) => ({
  ready: false,
  source: "fixtures",
  t: 0,
  stats: { agents: 0, households: 0, relationships: 0, conversations_today: 0, conversations_total: 0, thoughts_today: 0, products_live: 0 },
  budget: { used_usd: 0, cap_usd: 15 },
  hl: null,
  setHighlights: (hl) => set({ hl, ...(hl ? { sideTab: "now" as SideTab } : {}) }),
  ticker: [],
  products: [],
  siteAssign: {},
  aware: {},
  lensProduct: null,
  awareShare: {},
  funnel: {},
  campaigns: {},
  fx: null,
  setLensProduct: (lensProduct) => set({ lensProduct }),
  dayCounts: [],
  fixtures: null,
  lens: "activity",
  sideTab: "now",
  hourOverride: null,
  zoomCmd: null,
  connected: false,
  surveyPin: null,
  surveyTrips: [],
  hover: null,
  profile: null,
  setHover: (hover) => set({ hover }),
  openProfile: (id, tab) => set({ profile: { id, tab: tab ?? get().profile?.tab ?? "overview" }, hover: null }),
  setProfileTab: (tab) => {
    const p = get().profile;
    if (p) set({ profile: { ...p, tab } });
  },
  closeProfile: () => set({ profile: null }),
  setLens: (lens) => set({ lens }),
  setSideTab: (sideTab) => set({ sideTab }),
  setHour: (h) => set({ hourOverride: h, t: Math.floor(get().t / 1440) * 1440 + Math.round(h * 60) }),
  camera: (cmd) => set({ zoomCmd: { ...cmd, seq: (get().zoomCmd?.seq ?? 0) + 1 } }),
  loadFixtures: (f) =>
    set({
      ready: true,
      source: "fixtures",
      fixtures: f,
      t: f.t,
      stats: {
        agents: f.stats.agents,
        households: f.stats.households,
        relationships: f.stats.rel,
        conversations_today: f.stats.convToday,
        conversations_total: f.stats.convTotal,
        thoughts_today: f.stats.thoughtsToday,
        products_live: f.products.filter((p) => p.status === "live").length,
      },
      budget: { used_usd: 6.4, cap_usd: 15 },
      ticker: f.ticker,
      products: f.products,
      siteAssign: (f as Fixtures & { siteAssign?: Record<string, SiteShow> }).siteAssign ?? {},
      lensProduct: f.products.find((p) => p.status === "live")?.id ?? null,
      dayCounts: fixtureDayCounts(f.t, f.stats.convToday),
    }),
}));
