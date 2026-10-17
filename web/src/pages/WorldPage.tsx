import { useNavigate } from "react-router-dom";
import { useWorld, type Lens, type SideTab } from "../state/world";
import { fmt, fmtINR, fmtInt } from "../lib/time";
import { withMode } from "../lib/visualTest";
import { WorldCanvas } from "../world/WorldCanvas";
import { Minimap } from "../world/Minimap";
import type { FixtureProduct } from "../visual-fixtures/types";

const LENSES: [Lens, string][] = [["activity", "Activity"], ["aware", "Product awareness"], ["sentiment", "Sentiment"], ["hoardings", "Hoardings"]];
const SIDE_TABS: [SideTab, string][] = [["now", "Happening now"], ["watching", "Watching"], ["products", "Products"]];
const CURIOUS_PLUS = ["curious", "researching", "inquiring", "deciding", "purchased"];

function Meter({ label, v, col }: { label: string; v: number; col: string }) {
  return (
    <div className="meter"><span className="muted">{label}</span>
      <div className="bar"><i style={{ width: `${Math.round(v * 100)}%`, background: col }} /></div>
      <span className="mono">{Math.round(v * 100)}%</span></div>
  );
}

function Stats() {
  const s = useWorld((x) => x.stats);
  const rows: [string, string | number][] = [["Agents", fmtInt(s.agents)], ["Households", fmtInt(s.households)],
    ["Relationships", fmtInt(s.relationships)], ["Conversations today", fmtInt(s.conversations_today)],
    ["Thoughts today", fmtInt(s.thoughts_today)], ["Products live", s.products_live]];
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
  const ready = products.filter((p) => p.status === "ready");
  return (
    <div className="dock glass" data-testid="launch-dock">
      <div className="row between"><b className="small">Ready to launch</b><span className="xs muted">one at a time</span></div>
      {ready.length ? ready.map((p) => (
        <div className="ditem" data-testid="launch-dock-item" data-product={p.id} key={p.id}>
          <span className="pdot" style={{ background: p.hex }} />
          <div><b>{p.name}</b><div className="xs muted">{p.sites.length} hoardings · reels to ~{p.reel} · {p.stores.length} stores · {p.reviewers} reviewers</div></div>
          <button className="btn primary sm" style={{ background: p.hex, borderColor: p.hex, color: "#1a0d02" }}
            title="Launching arrives in phase 4">🚀 Launch</button>
        </div>
      )) : <div className="xs muted">No products ready. <a href={withMode("/launch")}>Open Launch Studio</a></div>}
    </div>
  );
}

function SideBody() {
  const tab = useWorld((s) => s.sideTab);
  const ticker = useWorld((s) => s.ticker);
  const products = useWorld((s) => s.products);
  const fx = useWorld((s) => s.fixtures);
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
  if (tab === "watching") {
    const w = agents.filter((a) => a.watch);
    return (
      <>
        <h3>Watching ({w.length})</h3>
        <div className="list">
          {w.map((a) => (
            <div className="item" key={a.id}>
              <div className="row" style={{ gap: 10 }}>
                <div className="avatar" style={{ background: a.look.shirt }}>{a.name.split(" ").map((s) => s[0]).join("").slice(0, 2)}</div>
                <div style={{ flex: 1 }}><b>{a.name}</b><div className="xs muted">{a.act} · {a.place ?? "on the move"}</div></div>
              </div>
            </div>
          ))}
        </div>
        <p className="xs muted" style={{ marginTop: 10 }}>Star anyone in their profile or on the People page to watch them. Watching never changes what they see.</p>
      </>
    );
  }
  const n = agents.length || 1;
  const card = (p: FixtureProduct) => {
    const live = p.status === "live";
    const aw = agents.filter((a) => a.beliefs[p.id] && a.beliefs[p.id].stage !== "unaware").length;
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
  const today = vals.length - 1;
  const mx = Math.max(1, ...vals);
  return (
    <div className="daybar" data-testid="day-timeline">
      <div><div className="xs muted">WORLD TIME</div>
        <div className="row" style={{ gap: 8 }}><b className="mono">{fmt(t)}</b>
          <span className="chip green" style={{ padding: "1px 7px" }}><span className="dotlive" />Live</span></div></div>
      <div>
        <div className="days">
          {vals.map((v, i) => {
            const lm = products.filter((p) => p.launched !== null && Math.floor(p.launched / 1440) === i);
            return (
              <div key={i} className={`d ${i === today ? "cur" : ""}`} style={{ height: `${Math.max(14, (v / mx) * 100)}%` }}
                title={`Day ${i + 1} · ${v} conversations`}>
                {lm.map((p, j) => <span key={p.id} className="lm" style={{ background: p.hex, top: -8 - j * 7 }} />)}
              </div>
            );
          })}
        </div>
        <div className="dlabels">{vals.map((_, i) => <span key={i}>{i % 2 === 0 || i === today ? `D${i + 1}` : ""}</span>)}</div>
      </div>
      <div className="row" style={{ gap: 8 }}><span className="legend">
        <span><i style={{ background: "var(--teal)" }} />today</span>
        <span><i style={{ background: "var(--panel3)" }} />past day · click for highlights</span></span></div>
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
        <canvas className="fxcanvas" data-testid="launch-fx" />
        <Stats />
        <Tools />
        <Dock />
        <Minimap />
        <div className="attrib">Indiranagar from OpenStreetMap · © OpenStreetMap contributors (ODbL)</div>
        <div className="drawer" data-testid="profile-drawer" />
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
      <div className="hovercard hidden" data-testid="agent-hovercard" />
    </div>
  );
}
