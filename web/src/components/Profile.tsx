import { useLayoutEffect, useRef, useState } from "react";
import { useWorld, type ProfileTab } from "../state/world";
import { useWatch } from "../state/watch";
import { useAgentView } from "./agentHooks";
import { ConversationsTab, MemoryTab, ThoughtsTab } from "./ProfileMind";
import { STAGE_COL, initials, inkOn, type AgentView } from "../lib/agentView";
import { fmtINR } from "../lib/time";
import { worldRef } from "../world/ref";
import type { FixtureProduct } from "../visual-fixtures/types";

/** Mockup `meter()` (label, bar, integer value). */
export function Meter({ label, v, col }: { label: string; v: number; col: string }) {
  return (
    <div className="meter"><span className="muted">{label}</span>
      <div className="bar"><i style={{ width: `${Math.round(v * 100)}%`, background: col }} /></div>
      <span className="mono xs">{Math.round(v * 100)}</span></div>
  );
}

/** Mockup `stageChip()`. */
export function StageChip({ b }: { b?: { stage: string; att: number } | null }) {
  if (!b || b.stage === "unaware") return <span className="muted">unaware</span>;
  return (
    <><span style={{ color: STAGE_COL[b.stage] ? `color-mix(in srgb,${STAGE_COL[b.stage]} var(--legible-mix),var(--ink))` : "var(--ink2)", fontWeight: 600 }}>{b.stage}</span>{" "}
      <span className="mono xs muted">{b.att >= 0 ? "+" : ""}{b.att.toFixed(2)}</span></>
  );
}

const useLiveProducts = (): FixtureProduct[] => {
  const products = useWorld((s) => s.products);
  return products.filter((p) => p.status === "live");
};

/** `agent-hovercard` (U-03), positioned 16 px below-right of the pointer like the mockup. */
export function HoverCard() {
  const hover = useWorld((s) => s.hover);
  const { view: a } = useAgentView(hover?.id ?? null);
  const live = useLiveProducts();
  const ref = useRef<HTMLDivElement>(null);
  const [h, setH] = useState(0);
  useLayoutEffect(() => {
    if (ref.current) setH(ref.current.offsetHeight);
  }, [a, hover]);
  const show = !!(hover && a);
  const left = hover ? Math.min(hover.sx + 16, window.innerWidth - 320) : 0;
  const top = hover ? Math.min(hover.sy + 16, window.innerHeight - h - 10) : 0;
  return (
    <div ref={ref} className={`hovercard ${show ? "" : "hidden"}`} data-testid="agent-hovercard" style={{ left, top }}>
      {a && <>
        <div className="hd"><div className="avatar" style={{ background: a.shirt, color: inkOn(a.shirt) }}>{initials(a.name)}</div>
          <div><b style={{ fontSize: 13 }}>{a.name}, {a.age}</b><div className="muted">{a.job}{a.work ? ` · ${a.work}` : ""}</div></div></div>
        <div className="row" style={{ gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
          <span className="chip" style={{ padding: "1px 8px" }}>● {a.act}</span>
          {a.special && <span className="chip violet" style={{ padding: "1px 8px" }}>{a.special}</span>}
          {a.watch && <span className="chip amber" style={{ padding: "1px 8px" }}>★ watching</span>}
        </div>
        <div className="row between"><span className="muted">Phone</span>
          <span>{a.phone.brand} {a.phone.tier} · <b>{a.phone.age} yrs</b> · {a.phone.cond.replace("_", " ")}</span></div>
        <div className="row between"><span className="muted">Interests</span><span>{a.interests.join(", ")}</span></div>
        <div style={{ marginTop: 8 }} className="list">
          {live.map((p) => (
            <div className="row between" key={p.id}><span><span className="pdot" style={{ background: p.hex, width: 8, height: 8, marginRight: 6 }} />{p.name}</span>
              <span><StageChip b={a.beliefs[p.id]} /></span></div>
          ))}
        </div>
        <div className="muted xs" style={{ marginTop: 8 }}>Click for profile · thoughts · conversations · memory</div>
      </>}
    </div>
  );
}

const TABS: [ProfileTab, string][] = [["overview", "Overview"], ["relations", "Relations"], ["possessions", "Possessions"],
  ["thoughts", "Thoughts"], ["conversations", "Conversations"], ["memory", "Memory"]];

function Overview({ a }: { a: AgentView }) {
  return (
    <>
      <p style={{ marginTop: 0 }}>“{a.bio}”</p>
      <div className="attr">
        <div>Age</div><div>{a.age}</div>
        <div>Work</div><div>{a.job}{a.work ? ` · ${a.work}` : ""}</div>
        <div>Home</div><div>Indiranagar · household of {a.household}</div>
        <div>Income band</div><div>{a.income} / month</div>
        <div>Savings · credit</div><div>{fmtINR(a.savings)} · {a.card ? "card" : "no card"} · {a.emi ? "EMI eligible" : "no EMI"}</div>
        <div>Media diet</div><div>{a.media}</div>
        <div>Interests</div><div>{a.interests.join(", ")}</div>
        <div>Disclosure</div><div>{a.disclosure}</div>
      </div>
      <h3 style={{ marginTop: 16 }}>Personality</h3>
      {a.big5.map(([n, v]) => <Meter key={n} label={n.slice(0, 11)} v={v} col="var(--violet)" />)}
      <h3 style={{ marginTop: 16 }}>Right now</h3>
      {a.needs.map(([n, v, c]) => <Meter key={n} label={n} v={v} col={c} />)}
      <div className="item small" style={{ marginTop: 10 }}>● {a.act} · {a.place ?? "on the move"} · today: {a.today}</div>
    </>
  );
}

function Relations({ a, open }: { a: AgentView; open: (id: number) => void }) {
  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>{a.friends.length} relationships · lines on the map show them while this profile is open.</p>
      <div className="list">
        {a.friends.slice(0, 14).map((f) => (
          <div className="item row between" style={{ cursor: "pointer" }} key={f.id} onClick={() => open(f.id)}>
            <span className="row" style={{ gap: 8 }}>
              <span className="avatar" style={{ background: f.shirt, color: inkOn(f.shirt), width: 24, height: 24, fontSize: 10 }}>{initials(f.name)}</span>
              <span><b>{f.name}</b><div className="xs muted">{f.rel} · {f.job}</div></span></span>
            <span style={{ width: 90 }}><div className="meter"><div className="bar"><i style={{ width: `${Math.round(f.c * 100)}%`, background: "var(--violet)" }} /></div>
              <span className="mono xs">{Math.round(f.c * 100)}</span></div></span>
          </div>
        ))}
      </div>
    </>
  );
}

function Possessions({ a }: { a: AgentView }) {
  const ph = a.phone;
  const need = Math.min(1, ph.age / 6 + (ph.cond !== "ok" ? 0.18 : 0) + (1 - ph.batt) * 0.3);
  return (
    <>
      <div className="belief">
        <div className="row between"><b>📱 Phone</b>
          <span className={`chip ${ph.age > 5 ? "red" : ph.age > 3 ? "amber" : "green"}`} style={{ padding: "0 8px" }}>{ph.age} years old</span></div>
        <div className="attr" style={{ marginTop: 8 }}>
          <div>Brand · tier</div><div>{ph.brand} · {ph.tier}</div>
          <div>Condition</div><div>{ph.cond.replace("_", " ")}</div>
          <div>Battery health</div><div>{Math.round(ph.batt * 100)}%</div>
          <div>Satisfaction</div><div>{ph.satisfaction}</div>
          <div>Bought</div><div>{ph.bought}</div>
        </div>
        <Meter label="Need to replace" v={need} col={need > 0.6 ? "var(--red)" : "var(--amber)"} />
        <p className="xs muted" style={{ margin: "4px 0 0" }}>Need rises with age, damage and battery wear. Life events (lost, cracked, slow) push it up suddenly.</p>
      </div>
      <h3 style={{ marginTop: 16 }}>History</h3>
      <div className="list small">{(a.history.length ? a.history : ["No recent events"]).map((h, i) => <div className="item" key={i}>{h}</div>)}</div>
      <h3 style={{ marginTop: 16 }}>Other categories</h3>
      <div className="item small muted">None yet. When a product of a new category launches (e.g. clothing), the world generates each agent's current state for it.</div>
    </>
  );
}

/** `profile-drawer` (U-04): always mounted, off-canvas when closed, 420 px. */
export function ProfileDrawer() {
  const profile = useWorld((s) => s.profile);
  const setTab = useWorld((s) => s.setProfileTab);
  const close = useWorld((s) => s.closeProfile);
  const openP = useWorld((s) => s.openProfile);
  const toggle = useWatch((s) => s.toggle);
  const { view: a, error } = useAgentView(profile?.id ?? null);
  const tab = profile?.tab ?? "overview";
  const open = (id: number) => {
    worldRef.scene?.focusAgent(id);
    openP(id);
  };
  return (
    <div className={`drawer ${profile ? "open" : ""}`} data-testid="profile-drawer">
      {profile && !a && <div className="db small muted">{error ? "Could not load this agent." : "Loading…"}</div>}
      {profile && a && <>
        <div className="dh"><div className="row between">
          <div className="row" style={{ gap: 12 }}>
            <div className="avatar" style={{ background: a.shirt, color: inkOn(a.shirt), width: 42, height: 42, fontSize: 15 }}>{initials(a.name)}</div>
            <div><h2 style={{ margin: 0 }}>{a.name}, {a.age}</h2>
              <div className="small muted">{a.job}{a.special && <> · <span className="chip violet" style={{ padding: "0 7px" }}>{a.special}</span></>}</div></div>
          </div>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn sm" data-testid="watch-toggle" onClick={() => toggle(a.id)}>{a.watch ? "★ Watching" : "☆ Watch"}</button>
            <button className="btn sm ghost" onClick={close}>✕</button>
          </div>
        </div></div>
        <div className="ptabs" data-testid="profile-tabs">
          {TABS.map(([k, l]) => (
            <button key={k} data-testid={`profile-tab-${k}`} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
        <div className="db" data-testid="profile-body">
          {tab === "overview" ? <Overview a={a} /> : tab === "relations" ? <Relations a={a} open={open} />
            : tab === "possessions" ? <Possessions a={a} /> : tab === "thoughts" ? <ThoughtsTab a={a} />
            : tab === "conversations" ? <ConversationsTab a={a} /> : <MemoryTab a={a} />}
        </div>
      </>}
    </div>
  );
}
