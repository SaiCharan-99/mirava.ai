import { LiveClient, liveUrl, type LiveEvt, type LiveMsg, type LiveProduct } from "./live";
import { actLabel } from "./agentView";
import { getAgent } from "./api";
import { fmtINR, shortT } from "./time";
import { simClock, tracks } from "../world/tracks";
import { useWorld } from "../state/world";
import type { FixtureProduct, TickerItem } from "../visual-fixtures/types";

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
      cls = "prod";
      html = `<span class="who">💭 ${who}</span> noticed <b>${esc(String(e.product ?? "an ad"))}</b>${e.thought ? `<div class="muted">“${esc(String(e.thought))}”</div>` : ""}`;
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

const nameOf = (id: number): string => names.get(id) ?? `Agent ${id}`;

/** Apply one frame to the store, the tracks and the sim clock. */
export function applyLive(m: LiveMsg): void {
  const st = useWorld.getState();
  switch (m.type) {
    case "hello":
      simClock.rate = m.scale.sim_min_per_real_s;
      simClock.set(m.t);
      tracks.reset(m.agents, m.segments);
      useWorld.setState({ source: "live", t: Math.floor(m.t), ticker: [], products: m.products.map(toProduct), hourOverride: null });
      break;
    case "seg":
      tracks.push(m.items);
      break;
    case "clock":
      simClock.set(m.t);
      if (Math.floor(m.t) !== st.t) useWorld.setState({ t: Math.floor(m.t) });
      break;
    case "stats":
      useWorld.setState({ stats: { ...st.stats, ...m.counts }, ...(m.budget ? { budget: m.budget } : {}) });
      break;
    case "evt": {
      for (const e of m.items) {
        if (e.k === "activity" && typeof e.a === "number") {
          const tr = tracks.byId.get(e.a);
          if (tr && typeof e.act === "string") tr.act = e.act;
        }
        const id = typeof e.a === "number" ? e.a : null;
        const push = () => {
          const it = tickerFor(e, simClock.now(), nameOf);
          if (it) useWorld.setState((s) => ({ ticker: [it, ...s.ticker].slice(0, 60) }));
        };
        const need = [id, typeof e.b === "number" ? e.b : null].filter((x): x is number => x !== null && !names.has(x));
        if (need.length) {
          Promise.all(need.map((x) => getAgent(x).then((d) => names.set(x, d.profile.name)).catch(() => names.set(x, `Agent ${x}`))))
            .finally(push);
        } else push();
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
