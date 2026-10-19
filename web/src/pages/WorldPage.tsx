import { SurveyPin } from "../world/SurveyPin";
import { useNavigate } from "react-router-dom";
import { useWorld, type Lens, type SideTab } from "../state/world";
import { fmt, fmtINR, fmtInt } from "../lib/time";
import { withMode } from "../lib/visualTest";
import { WorldCanvas } from "../world/WorldCanvas";
import { Minimap } from "../world/Minimap";
import type { FixtureProduct } from "../visual-fixtures/types";
import { HoverCard, Meter, ProfileDrawer, StageChip } from "../components/Profile";
import { useAgentView } from "../components/agentHooks";
import { useWatch } from "../state/watch";
import { initials } from "../lib/agentView";
import { worldRef } from "../world/ref";
import { backToLive, jumpTo, openHighlights } from "../lib/highlights";
import { hhmm } from "../lib/time";
import { isVisualTest } from "../lib/visualTest";
import { studioApi } from "../lib/studio";
import { toast } from "../lib/toast";
import { useEffect, useState } from "react";
import { getJSON } from "../lib/api";

const STAGES = ["aware", "curious", "researching", "inquiring", "deciding", "purchased", "postponed", "rejected"];
const STAGE_COL: Record<string, string> = { aware: "#94a3b8", curious: "#60a5fa", researching: "#a78bfa", inquiring: "#f5b041", deciding: "#fb923c", purchased: "#4ade80", postponed: "#64748b", rejected: "#f87171" };

function LensExtras() {
  const lens = useWorld((s) => s.lens);
  const lp = useWorld((s) => s.lensProduct);
  const setLp = useWorld((s) => s.setLensProduct);
  const live = useWorld((s) => s.products).filter((p) => p.status === "live");
  const prodLens = lens === "aware" || lens === "sentiment";
  return (
    <>
      <div className="seg glass" style={prodLens ? undefined : { display: "none" }}>
        {live.map((p) => (
          <button key={p.id} className={lp === p.id ? "on" : ""} onClick={() => setLp(p.id)}>
            <span className="pdot" style={{ background: p.hex, width: 8, height: 8, marginRight: 5 }} />{p.name}</button>
        ))}
      </div>
      <div className="glass" style={{ padding: "8px 10px", fontSize: 11, ...(lens === "activity" ? { display: "none" } : {}) }}>
        {lens === "aware" ? <div className="legend" style={{ flexDirection: "column", gap: 4 }}>{STAGES.map((s) => <span key={s}><i style={{ background: STAGE_COL[s] }} />{s}</span>)}<span><i style={{ background: "#334155" }} />unaware (dimmed)</span></div>
          : lens === "sentiment" ? <div className="legend" style={{ flexDirection: "column", gap: 4 }}><span><i style={{ background: "#4ade80" }} />positive</span><span><i style={{ background: "#f5b041" }} />neutral</span><span><i style={{ background: "#f87171" }} />negative</span></div>
            : <div style={{ maxWidth: 200 }}>Cones show where each board can be seen (facing + range). Colour = product. See <a href={withMode("/insights/hoardings")}>Insights → Hoardings</a> for notice rates.</div>}
      </div>
    </>
  );
}

/** One watched agent in the side panel (mockup renderSide "watching"). */
function WatchItem({ id }: { id: number }) {
  const { view: a } = useAgentView(id);
  const fx = useWorld((s) => s.fixtures);
  const live = useWorld((s) => s.products).filter((p) => p.status === "live");
  const openP = useWorld((s) => s.openProfile);
  if (!a) return null;
  const fa = fx?.agents.find((x) => x.id === id);
  const th = fx && id === fx.featured.id ? fx.featured.thoughts[0] : fa?.thoughts[0];
  const showTh = useWorld.getState().source !== "live" && th;
  return (
    <div className="item" style={{ cursor: "pointer" }} onClick={() => { worldRef.scene?.focusAgent(id); openP(id); }}>
      <div className="row" style={{ gap: 10 }}>
        <div className="avatar" style={{ background: a.shirt }}>{initials(a.name)}</div>
        <div style={{ flex: 1 }}><b>{a.name}</b><div className="xs muted">{a.act} · {a.place ?? "on the move"}</div></div>
      </div>
      <div className="xs" style={{ marginTop: 6 }}>
        {live.map((p, i) => (
          <span key={p.id}>{i > 0 && <>{"   "}</>}<span className="pdot" style={{ background: p.hex, width: 7, height: 7, marginRight: 4 }} />{p.name}: <StageChip b={a.beliefs[p.id]} /></span>
        ))}
      </div>
      {showTh && <div className="thought" style={{ marginTop: 6, fontSize: 11.5 }}>“{th.txt || "(glanced, no thought)"}”</div>}
    </div>
  );
}

const LENSES: [Lens, string][] = [["activity", "Activity"], ["aware", "Product awareness"], ["sentiment", "Sentiment"], ["hoardings", "Hoardings"]];
const SIDE_TABS: [SideTab, string][] = [["now", "Happening now"], ["watching", "Watching"], ["products", "Products"]];
const CURIOUS_PLUS = ["curious", "researching", "inquiring", "deciding", "purchased"];

function Stats() {
  const s = useWorld((x) => x.stats);
  // no stats message from world-engine yet: show a placeholder instead of misleading zeros
  const v = (n: number): string => (s.agents ? fmtInt(n) : "—");
  const rows: [string, string][] = [["Agents", v(s.agents)], ["Households", v(s.households)],
    ["Relationships", v(s.relationships)], ["Conversations today", v(s.conversations_today)],
    ["Thoughts today", v(s.thoughts_today)], ["Products live", v(s.products_live)]];
  return (
    <div className="wstats" data-testid="world-stats">
      {rows.map(([l, v]) => <div className="stat glass" key={l}><div className="v">{v}</div><div className="l">{l}</div></div>)}
    </div>
  );
}

function Tools() {
  const nav = useNavigate();
  const lens = useWorld((s) => s.lens);
  const setLens = useWorld((s) => s.setLens);
  const camera = useWorld((s) => s.camera);
  return (
    <div className="wtools">
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" data-testid="new-product" onClick={() => nav(withMode("/launch"))}>＋ New product</button>
      </div>
      <div className="seg glass" data-testid="lens-switch">
        {LENSES.map(([k, l]) => (
          <button key={k} data-lens={k} className={lens === k ? "on" : ""} onClick={() => setLens(k)}>{l}</button>
        ))}
      </div>
      <LensExtras />
      <div className="row" style={{ gap: 6 }}>
        <button className="zoombtn" onClick={() => camera({ kind: "in" })}>+</button>
        <button className="zoombtn" onClick={() => camera({ kind: "out" })}>−</button>
        <button className="zoombtn" title="Fit" onClick={() => camera({ kind: "fit" })}>⤢</button>
      </div>
    </div>
  );
}

function Dock() {
  const products = useWorld((s) => s.products);
  const fx = useWorld((s) => s.fx);
  const [busy, setBusy] = useState<string | null>(null);
  const ready = products.filter((p) => p.status === "ready");
  const launch = async (id: string) => {
    if (isVisualTest) return window.__ll.launchFx(id, 0.45);
    if (busy || fx) return toast("One launch at a time — wait for the current one to land");
    setBusy(id);
    try {
      await studioApi.launch(id);
      toast("Launch sent — the world-engine activates the plan at the next sim minute");
    } catch (e) {
      toast(`Launch failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="dock glass" data-testid="launch-dock">
      <div className="row between"><b className="small">Ready to launch</b><span className="xs muted">one at a time</span></div>
      {ready.length ? ready.map((p) => (
        <div className="ditem" data-testid="launch-dock-item" data-product={p.id} key={p.id}>
          <span className="pdot" style={{ background: p.hex }} />
          <div><b>{p.name}</b><div className="xs muted">{p.sites.length} hoardings · reels to ~{p.reel} · {p.stores.length} stores · {p.reviewers} reviewers</div></div>
          <button className="btn primary sm" style={{ background: p.hex, borderColor: p.hex, color: "#1a0d02" }}
            disabled={busy === p.id} onClick={() => void launch(p.id)}>{busy === p.id ? "Launching…" : "🚀 Launch"}</button>
        </div>
      )) : <div className="xs muted">No products ready. <a href={withMode("/launch")}>Open Launch Studio</a></div>}
    </div>
  );
}

function Watching() {
  const ids = useWatch((s) => s.ids);
  return (
    <>
      <h3>Watching ({ids.length})</h3>
      <div className="list">{ids.map((id) => <WatchItem key={id} id={id} />)}</div>
      <p className="xs muted" style={{ marginTop: 10 }}>Star anyone in their profile or on the People page to watch them. Watching never changes what they see.</p>
    </>
  );
}

function SideBody() {
  const tab = useWorld((s) => s.sideTab);
  const ticker = useWorld((s) => s.ticker);
  const products = useWorld((s) => s.products);
  const fx = useWorld((s) => s.fixtures);
  const hl = useWorld((s) => s.hl);
  const openP = useWorld((s) => s.openProfile);
  if (tab === "now" && hl) {
    return (
      <>
        <h3>Highlights · Day {hl.day}</h3>
        <div className="ticker" data-testid="highlights-list">
          {hl.moments.length ? hl.moments.map((m, i) => (
            <div key={i} className="tick" style={{ cursor: "pointer" }}
              onClick={() => { jumpTo(m); if (m.agent_ids[0] !== undefined) openP(m.agent_ids[0], m.session_id ? "conversations" : undefined); }}>
              <div className="t">{hhmm(m.t)}</div>{m.title}{m.text ? <div className="muted">“{m.text}”</div> : null}</div>
          )) : <div className="item muted small">No highlights for this day yet.</div>}
        </div>
      </>
    );
  }
  if (tab === "now") {
    return (
      <>
        <div className="row between" style={{ marginBottom: 10 }}><h3 style={{ margin: 0 }}>Happening now</h3>
          <span className="xs muted">live from world-engine</span></div>
        <div className="ticker" data-testid="event-ticker" style={{ height: "calc(100vh - 290px)", overflow: "hidden" }}>
          {ticker.slice(0, 24).map((x, i) => (
            <div key={i} className={`tick ${x.cls}`}><div className="t">{x.t}</div>
              <span dangerouslySetInnerHTML={{ __html: x.html }} /></div>
          ))}
        </div>
      </>
    );
  }
  const agents = fx?.agents ?? [];
  if (tab === "watching") return <Watching />;
  const n = agents.length || 1;
  const card = (p: FixtureProduct) => {
    const live = p.status === "live";
    const liveAw = useWorld.getState().source === "live" ? useWorld.getState().awareShare[p.id] : undefined;
    const aw = liveAw !== undefined ? liveAw * n : agents.filter((a) => a.beliefs[p.id] && a.beliefs[p.id].stage !== "unaware").length;
    const cu = agents.filter((a) => a.beliefs[p.id] && CURIOUS_PLUS.includes(a.beliefs[p.id].stage)).length;
    return (
      <div className="item" key={p.id}>
        <div className="row between"><span><span className="pdot" style={{ background: p.hex, marginRight: 6 }} /><b>{p.name}</b>{" "}
          <span className="muted xs">{p.brand} · {fmtINR(p.price)}</span></span>
          <span className={`chip ${live ? "green" : "amber"}`} style={{ padding: "0 7px" }}>{live ? "live" : p.status}</span></div>
        {live && p.launched !== null ? (
          <><div className="xs muted" style={{ margin: "6px 0 2px" }}>Launched {fmt(p.launched)}</div>
            <Meter label="Aware" v={aw / n} col={p.hex} /><Meter label="Curious+" v={cu / n} col={p.hex} /></>
        ) : <div className="xs muted" style={{ marginTop: 6 }}>Launch it from the dock on the map.</div>}
      </div>
    );
  };
  return (
    <><h3>Products in this world</h3><div className="list">{products.map(card)}</div>
      <a className="btn sm" style={{ marginTop: 12 }} href={withMode("/insights/overview")}>Compare in Insights →</a></>
  );
}

function DayBar() {
  const t = useWorld((s) => s.t);
  const vals = useWorld((s) => s.dayCounts);
  const products = useWorld((s) => s.products);
  const hl = useWorld((s) => s.hl);
  const today = vals.length - 1;
  const mx = Math.max(1, ...vals);
  return (
    <div className="daybar" data-testid="day-timeline">
      <div><div className="xs muted">WORLD TIME</div>
        <div className="row" style={{ gap: 8 }}><b className="mono">{fmt(t)}</b>
          {hl ? <span className="chip amber" style={{ padding: "1px 7px" }}>Highlights · Day {hl.day}</span>
            : <span className="chip green" style={{ padding: "1px 7px" }}><span className="dotlive" />Live</span>}</div></div>
      <div>
        <div className="days">
          {vals.map((v, i) => {
            const lm = products.filter((p) => p.launched !== null && Math.floor(p.launched / 1440) === i);
            return (
              <div key={i} className={`d ${i === today ? "cur" : ""} ${hl?.day === i + 1 ? "sel" : ""}`} style={{ height: `${Math.max(14, (v / mx) * 100)}%` }}
                title={`Day ${i + 1} · ${v} conversations`} data-testid={`day-${i + 1}`}
                onClick={() => (i === today ? backToLive() : void openHighlights(i + 1))}>
                {lm.map((p, j) => <span key={p.id} className="lm" style={{ background: p.hex, top: -8 - j * 7 }} />)}
              </div>
            );
          })}
        </div>
        <div className="dlabels">{vals.map((_, i) => <span key={i}>{i % 2 === 0 || i === today ? `D${i + 1}` : ""}</span>)}</div>
      </div>
      <div className="row" style={{ gap: 8 }}><span className="legend">
        <span><i style={{ background: "var(--teal)" }} />today</span>
        <span><i style={{ background: "var(--track)" }} />past day · click for highlights</span></span></div>
    </div>
  );
}

function HlBanner() {
  const hl = useWorld((s) => s.hl);
  if (!hl) return null;
  return (
    <div className="banner glass" data-testid="highlights-banner">
      <b>Highlights · Day {hl.day}</b> · {hl.total} moments · replaying the top ones{" "}
      <button className="btn sm" style={{ marginLeft: 10 }} onClick={backToLive}>Back to live</button>
    </div>
  );
}

/** Fallback (architecture §21): after 10 s without `/live`, offer the latest finished day's highlights. */
function EngineDownBanner() {
  const connected = useWorld((s) => s.connected);
  const source = useWorld((s) => s.source);
  const hl = useWorld((s) => s.hl);
  const t = useWorld((s) => s.t);
  const [down, setDown] = useState(false);
  useEffect(() => {
    if (connected || source !== "live") { setDown(false); return; }
    const id = setTimeout(() => setDown(true), 10_000);
    return () => clearTimeout(id);
  }, [connected, source]);
  if (!down || hl) return null;
  const replay = async () => {
    let now = t;
    if (!now) now = Number((await getJSON<{ t?: number }>("/world/state").catch(() => ({ t: 0 }))).t ?? 0);
    const day = Math.max(1, Math.floor(now / 1440));
    void openHighlights(day);
  };
  return (
    <div className="banner glass" data-testid="engine-down-banner">
      <b>Live world unreachable</b> · reconnecting…{" "}
      <button className="btn sm" style={{ marginLeft: 10 }} onClick={() => void replay()}>Replay</button>
    </div>
  );
}

/** World (home, U-02 shell): live map stage, stats, lens switch, ready dock, side panel, day timeline. */
export function WorldPage() {
  const tab = useWorld((s) => s.sideTab);
  const setTab = useWorld((s) => s.setSideTab);
  return (
    <div className="page full"><div className="worldwrap">
      <div className="stage" data-testid="world-stage">
        <WorldCanvas />
        <SurveyPin />
        <canvas className="fxcanvas" data-testid="launch-fx" />
        <Stats />
        <Tools />
        <HlBanner />
        <EngineDownBanner />
        <Dock />
        <Minimap />
        <div className="attrib">Indiranagar from OpenStreetMap · © OpenStreetMap contributors (ODbL)</div>
        <ProfileDrawer />
      </div>
      <div className="side" data-testid="world-side">
        <div className="sidetabs">
          {SIDE_TABS.map(([k, l]) => (
            <button key={k} data-testid={`side-tab-${k}`} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
        <div style={{ padding: "14px 16px", overflow: "auto", flex: 1 }}><SideBody /></div>
      </div>
      <DayBar />
    </div>
      <HoverCard />
    </div>
  );
}
