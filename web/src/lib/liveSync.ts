import { LiveClient, liveUrl, type LiveEvt, type LiveMsg, type LiveProduct } from "./live";
import { actLabel } from "./agentView";
import { getJSON, type PeoplePage } from "./api";
import { fmtINR, shortT } from "./time";
import { simClock, tracks } from "../world/tracks";
import { useWorld } from "../state/world";
import type { FixtureProduct, TickerItem } from "../visual-fixtures/types";
import { studioApi, toWorldProduct, fromApi, useStudio } from "./studio";
import { playLaunchFx } from "../world/launchFx";
import type { SiteShow } from "../state/world";

const names = new Map<number, string>();
const talks = new Map<string, { topic: string; place: string }>();

const esc = (s: string): string => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

/** Ticker line for one live event (null = not shown). Names come from the cache; unknown ids show "Agent N". */
export function tickerFor(e: LiveEvt, t: number, nameOf: (id: number) => string): TickerItem | null {
  const a = typeof e.a === "number" ? e.a : null;
  const who = a !== null ? esc(nameOf(a)) : "";
  let html: string;
  let cls = "";
  switch (e.k) {
    case "activity": {
      const place = typeof e.place === "string" && e.place ? ` · ${esc(e.place)}` : "";
      html = `<span class="who">${who}</span> ${esc(actLabel(String(e.act ?? "")).toLowerCase())}${place}`;
      break;
    }
    case "life_event": {
      const what = e.type === "lost" ? "lost their phone" : e.type === "broken" ? "'s phone screen cracked" : "'s phone has become slow";
      html = `<span class="who">📱 ${who}</span>${what.startsWith("'") ? "" : " "}${what} — need rises`;
      break;
    }
    case "payday":
      html = `<span class="who">💰 ${who}</span> got paid ${typeof e.amount === "number" ? fmtINR(e.amount) : ""}`;
      break;
    case "notice":
      if (String(e.product ?? "").startsWith("baseline:")) return null;
      cls = "prod";
      html = `<span class="who">💭 ${who}</span> noticed <b>${esc(productName(String(e.product ?? "")) || "an ad")}</b>${e.thought ? `<div class="muted">“${esc(String(e.thought))}”</div>` : ""}`;
      break;
    case "launch": {
      cls = "launch";
      const sm = (e.summary ?? {}) as { sites?: number; stores?: number; reel_audience?: number; reviewers?: number };
      html = `<span class="who">🚀 ${esc(String(e.name ?? e.product ?? ""))} launched</span> · ${sm.sites ?? 0} hoardings · ${sm.stores ?? 0} stores · reels to ~${sm.reel_audience ?? 0} agents · ${sm.reviewers ?? 0} reviewers`;
      break;
    }
    case "review":
      cls = "prod";
      html = `<span class="who">⭐ ${who}</span> published a review: <b>${esc(String(e.title ?? ""))}</b>`;
      break;
    case "post":
      html = `<span class="who">📰 ${who}</span> posted “${esc(String(e.title ?? ""))}”`;
      break;
    case "comment":
      html = `<span class="who">💬 ${who}</span> commented<div class="muted">“${esc(String(e.text ?? ""))}”</div>`;
      break;
    case "purchase":
      cls = "prod";
      html = `<span class="who">🛍️ ${who}</span> bought <b>${esc(String(e.product ?? ""))}</b>`;
      break;
    case "bubble": {
      const b = typeof e.b === "number" ? esc(nameOf(e.b)) : "";
      const info = talks.get(String(e.session_id ?? ""));
      const topic = info?.topic ? ` talked about <b>${esc(info.topic.replace(/^product:/, ""))}</b>` : " talked";
      const place = info?.place ? ` · ${esc(info.place)}` : "";
      if (String(info?.topic ?? "").startsWith("product:")) cls = "prod";
      html = `<span class="who">💬 ${who}${b ? ` &amp; ${b}` : ""}</span>${topic}${place}<div class="muted">“${esc(String(e.text ?? ""))}”</div>`;
      talks.delete(String(e.session_id ?? ""));
      break;
    }
    case "talk":
      talks.set(String(e.session_id ?? ""), { topic: String(e.topic ?? ""), place: typeof e.place === "string" ? e.place : "" });
      if (talks.size > 500) talks.delete(talks.keys().next().value as string);
      return null;
    default:
      return null;
  }
  return { html, cls, t: shortT(t), aid: a };
}

function toProduct(p: LiveProduct): FixtureProduct {
  return { id: p.id, name: p.name, brand: "", price: 0, hex: p.color, status: "live", launched: p.launched_at_t, sites: [], stores: [], reel: 0, reviewers: 0 };
}

/** Day timeline in live mode: one bar per real sim day so far; past days use the average (per-day counts arrive later). */
export function liveDayCounts(t: number, today: number, total: number): number[] {
  const n = Math.floor(t / 1440) + 1;
  const past = n > 1 ? Math.max(1, Math.round((total - today) / (n - 1))) : 0;
  return Array.from({ length: n }, (_, i) => (i === n - 1 ? today : past));
}

const nameOf = (id: number): string => names.get(id) ?? `Agent ${id}`;

let namesP: Promise<void> | null = null;
/** All agent names in ONE request (per-agent lookups flooded the api and queued user actions behind them). */
function loadNames(): Promise<void> {
  namesP ??= getJSON<PeoplePage>("/agents?page_size=1000").then((r) => { for (const row of r.rows) names.set(row.agent_id, row.name); })
    .catch(() => { namesP = null; });
  return namesP;
}

function productName(pid: string): string {
  return useWorld.getState().products.find((p) => p.id === pid)?.name ?? pid;
}

/** hello.sites / launch → what each board shows. */
export function siteMap(items: unknown[]): Record<string, SiteShow> {
  const out: Record<string, SiteShow> = {};
  for (const it of items as { site_id?: string; product_id?: string }[]) {
    if (!it?.site_id || !it.product_id) continue;
    out[it.site_id] = { cr: it.product_id.replace(/^baseline:/, "") };
  }
  return out;
}

/** Products (all statuses) from the API → world store; the live hello only lists launched ones. */
export async function refreshProducts(): Promise<void> {
  try {
    const list = await studioApi.list();
    useStudio.setState({ products: list.map(fromApi), loaded: true });
    const prods = list.map((p) => toWorldProduct(fromApi(p)));
    const st = useWorld.getState();
    useWorld.setState({ products: prods, lensProduct: st.lensProduct && prods.some((p) => p.id === st.lensProduct) ? st.lensProduct
      : prods.find((p) => p.status === "live")?.id ?? null });
  } catch {
    /* api unreachable: keep what /live gave us */
  }
}

/** A `launch` evt: firework, boards flip to the creative, product goes live (all viewers at once). */
function onLaunch(e: LiveEvt): void {
  const pid = String(e.product ?? "");
  const sites = (e.sites as { site_id: string; facing: number }[] | undefined) ?? [];
  const now = performance.now();
  const st = useWorld.getState();
  const assign = { ...st.siteAssign };
  for (const s of sites) assign[s.site_id] = { cr: pid, facing: s.facing, flipAt: now + 1500 + Math.random() * 900, prev: assign[s.site_id]?.cr } as SiteShow;
  const storeNames = ((e.stores as string[] | undefined) ?? []).map((id) => ({ "ST-DIGITAL-BAZAAR": "Digital Bazaar", "ST-ELECTROHUB": "ElectroHub", "ST-PHONEWORLD": "PhoneWorld" } as Record<string, string>)[id] ?? id);
  const products = st.products.map((p) => (p.id === pid ? { ...p, status: "live" as const, launched: simClock.now() } : p));
  useWorld.setState({ siteAssign: assign, products, lensProduct: pid, aware: { ...st.aware, [pid]: st.aware[pid] ?? {} } });
  playLaunchFx({ pid, hex: String(e.color ?? products.find((p) => p.id === pid)?.hex ?? "#2dd4bf"), name: String(e.name ?? pid),
    sites: sites.map((s) => s.site_id), stores: storeNames, audience: (e.audience as number[] | undefined) ?? [], frozen: null });
  setTimeout(() => void refreshProducts(), 3000);
}

/** Apply one frame to the store, the tracks and the sim clock. */
export function applyLive(m: LiveMsg): void {
  const st = useWorld.getState();
  switch (m.type) {
    case "hello":
      simClock.rate = m.scale.sim_min_per_real_s;
      simClock.set(m.t);
      tracks.reset(m.agents, m.segments);
      useWorld.setState({ source: "live", t: Math.floor(m.t), ticker: [], products: m.products.map(toProduct), hourOverride: null,
        siteAssign: siteMap(m.sites), dayCounts: liveDayCounts(m.t, 0, 0) });
      void refreshProducts();
      break;
    case "seg":
      tracks.push(m.items);
      break;
    case "clock":
      simClock.set(m.t);
      if (Math.floor(m.t) !== st.t) useWorld.setState({ t: Math.floor(m.t) });
      break;
    case "stats":
      useWorld.setState({ stats: { ...st.stats, ...m.counts }, ...(m.budget ? { budget: m.budget } : {}), ...(m.awareness ? { awareShare: m.awareness } : {}),
        dayCounts: liveDayCounts(m.t, m.counts.conversations_today ?? 0, m.counts.conversations_total ?? 0) });
      break;
    case "evt": {
      for (const e of m.items) {
        if (e.k === "activity" && typeof e.a === "number") {
          const tr = tracks.byId.get(e.a);
          if (tr && typeof e.act === "string") tr.act = e.act;
        }
        if (e.k === "launch") onLaunch(e);
        if (e.k === "notice" && typeof e.a === "number" && typeof e.product === "string" && !e.product.startsWith("baseline:")) {
          const pid = e.product, aid = e.a;
          useWorld.setState((s) => ({ aware: { ...s.aware, [pid]: { ...(s.aware[pid] ?? {}), [aid]: (s.aware[pid]?.[aid] ?? 0) + 0.05 } } }));
        }
        const id = typeof e.a === "number" ? e.a : null;
        const push = () => {
          const it = tickerFor(e, simClock.now(), nameOf);
          if (it) useWorld.setState((s) => ({ ticker: [it, ...s.ticker].slice(0, 60) }));
        };
        void id;
        if (names.size) push();
        else void loadNames().finally(push);
      }
      break;
    }
  }
}

let client: LiveClient | null = null;

/** Start the /live connection (not in visual-test mode). Fixtures stay on screen until `hello` arrives. */
export function startLive(): void {
  if (client) return;
  client = new LiveClient(liveUrl(), applyLive, (up) => useWorld.setState({ connected: up }));
  client.start();
}
