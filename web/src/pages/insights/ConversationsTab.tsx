import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { HBars } from "../../components/charts";
import { getJSON } from "../../lib/api";
import { getConversations, type ConversationsData } from "../../lib/insights";
import { isVisualTest, withMode } from "../../lib/visualTest";
import { useWorld } from "../../state/world";
import { worldRef } from "../../world/ref";

interface Who { agent_id: number | null; name: string | null }
interface Card { session_id: string; t: number; label: string; kind: string; rendered: boolean; a: Who; b: Who; place: string; first_line: string; products: { id: string; name: string }[]; topic: string | null; sentiment: string | null }
interface Person { agent_id: number; name: string | null; age: number | null; occupation: string | null;
  plan: { opening: string | null; share: string[]; kept: string[]; withheld_count: number } | null;
  memory: { text: string | null; importance: number | null } | null; store_thoughts: { text: string }[] }
interface Detail { session_id: string; kind: string; label: string; place: string; place_xy: { x: number; y: number } | null; products: { id: string; name: string }[]; topics?: string[];
  people: Person[]; messages: { seq: number; speaker: number | string; text: string }[]; spread: { chain: Who[]; days: number } | null }

const KIND_LABEL: Record<string, string> = { social: "Friends & family", stranger: "Strangers", store: "In a store", focus_group: "Focus group" };
const FILTERS: [string, string][] = [["", "All"], ["friends", "Friends & family"], ["strangers", "Strangers"], ["store", "In a store"], ["focus", "Focus groups"]];
const COLORS = ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#ec4899", "#14b8a6", "#f97316", "#eab308", "#6366f1"];
const col = (id: number | null) => COLORS[Math.abs(id ?? 0) % COLORS.length];
const ini = (n: string | null) => (n ?? "?").split(" ").map((x) => x[0]).join("").slice(0, 2);
const Av = ({ w, s = 26 }: { w: Who; s?: number }) => <div className="avatar" style={{ width: s, height: s, fontSize: s < 30 ? 10 : 12, background: col(w.agent_id) }}>{ini(w.name)}</div>;

/** Insights → Conversations: KPIs, filters, a paged list, one conversation in full (private parts in purple). */
export function ConversationsTab() {
  const nav = useNavigate();
  const open = useWorld((s) => s.openProfile);
  const [sum, setSum] = useState<ConversationsData | null>(null);
  const [sumErr, setSumErr] = useState("");
  const [products, setProducts] = useState<{ product_id: string; name: string }[]>([]);
  const [product, setProduct] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState(""), [qs, setQs] = useState("");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<{ rows: Card[]; more: boolean } | null>(null);
  const [listErr, setListErr] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [det, setDet] = useState<Detail | null>(null);
  const [detErr, setDetErr] = useState("");
  const [n, setN] = useState(0);
  useEffect(() => { const h = setTimeout(() => { setQs(q); setPage(1); }, 400); return () => clearTimeout(h); }, [q]);
  useEffect(() => {
    if (isVisualTest) return;
    getConversations().then((d) => { setSum(d); setSumErr(""); }).catch((e: unknown) => setSumErr(e instanceof Error ? e.message : String(e)));
    getJSON<{ product_id: string; name: string }[]>("/products?active=1").then(setProducts).catch(() => undefined);
  }, [n]);
  useEffect(() => {
    if (isVisualTest) return;
    setList(null); setListErr("");
    getJSON<{ rows: Card[]; more: boolean }>(`/insights/conversations/list?product=${encodeURIComponent(product)}&kind=${kind}&q=${encodeURIComponent(qs)}&page=${page}`)
      .then((r) => { setList(r); if (r.rows[0] && !sel) setSel(r.rows.find((x) => x.rendered)?.session_id ?? r.rows[0].session_id); })
      .catch((e: unknown) => setListErr(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product, kind, qs, page, n]);
  useEffect(() => {
    if (!sel || isVisualTest) return;
    setDet(null); setDetErr("");
    getJSON<Detail>(`/insights/conversations/${encodeURIComponent(sel)}`).then(setDet).catch((e: unknown) => setDetErr(e instanceof Error ? e.message : String(e)));
  }, [sel]);
  const retry = () => setN((k) => k + 1);
  const name = (id: number | string) => det?.people.find((p) => p.agent_id === id)?.name?.split(" ")[0] ?? `#${id}`;
  const A = det?.people[0], B = det?.people[1];
  return (
    <div data-testid="conversations-tab">
      <div className="grid g4">{(sum?.kpis ?? [["Conversations today", "…", ""], ["About our products", "…", ""], ["Kept something private", "…", ""], ["Word of mouth", "…", ""]]).map((k) => (
        <div key={k[0]} className="card kpi"><div className="l">{k[0]}</div><div className="v">{k[1]}</div><div className="d muted">{k[2]}</div></div>))}</div>
      {sumErr && <div className="xs" style={{ color: "var(--red)", marginTop: 8 }}>Couldn't load the summary: {sumErr} <button className="btn sm" onClick={retry}>↻ Retry</button></div>}
      {sum?.errors && sum.errors.length > 0 && <div className="xs" style={{ color: "var(--amber)", marginTop: 8 }}>Some sections failed to load ({sum.errors.join(", ")}). <button className="btn sm" onClick={retry}>↻ Retry</button></div>}
      <div className="row wrap" style={{ gap: 6, margin: "14px 0" }}>
        <input placeholder="Search what people said…" style={{ width: 260 }} value={q} onChange={(e) => setQ(e.target.value)} />
        <button className={`chip ${product === "" ? "teal" : ""}`} style={{ cursor: "pointer" }} onClick={() => { setProduct(""); setPage(1); }}>All products</button>
        {products.map((p) => <button key={p.product_id} className={`chip ${product === p.product_id ? "teal" : ""}`} style={{ cursor: "pointer" }} onClick={() => { setProduct(p.product_id); setPage(1); }}>{p.name}</button>)}
        <span className="muted">|</span>
        {FILTERS.map(([k, l]) => <button key={k} className={`chip ${kind === k ? "teal" : ""}`} style={{ cursor: "pointer" }} onClick={() => { setKind(k); setPage(1); }}>{l}</button>)}
      </div>
      <div className="grid" style={{ gridTemplateColumns: "320px 1fr 330px", alignItems: "start" }}>
        <div className="card conv-list" data-testid="conv-list" style={{ maxHeight: 760, overflow: "auto" }}><h3>Conversations</h3>
          {listErr && <div className="xs" style={{ color: "var(--red)" }}>Couldn't load: {listErr} <button className="btn sm" onClick={retry}>↻ Retry</button></div>}
          {!listErr && !list && <div className="xs muted">Loading…</div>}
          {list && !list.rows.length && <div className="xs muted">No conversations match these filters yet.</div>}
          {list?.rows.map((x) => (
            <div key={x.session_id} className={`cv ${x.session_id === sel ? "on" : ""}`} onClick={() => setSel(x.session_id)}>
              <div className="row between"><div className="row" style={{ gap: 8 }}><div className="pair"><Av w={x.a} /><Av w={x.b} /></div><b className="small">{(x.a.name ?? "?").split(" ")[0]} & {(x.b.name ?? "?").split(" ")[0]}</b></div><span className="xs muted">{x.label.split(" · ").slice(-1)[0]}</span></div>
              <div className="xs muted" style={{ marginTop: 5 }}>{KIND_LABEL[x.kind] ?? x.kind}{x.place ? ` · ${x.place}` : ""}{x.rendered ? "" : " · topic only"}</div>
              {x.first_line && <div className="small" style={{ marginTop: 4 }}>“{x.first_line}”</div>}
              <div className="row" style={{ gap: 6, marginTop: 6, flexWrap: "wrap" }}>{x.products.map((p) => <span key={p.id} className="chip teal" style={{ padding: "0 7px" }}>{p.name}</span>)}
                {x.topic && <span className="chip" style={{ padding: "0 7px" }}>{String(x.topic).replace(/^product:/, "")}</span>}
                {x.sentiment && x.sentiment !== "neutral" && <span className={`chip ${x.sentiment === "positive" ? "green" : "red"}`} style={{ padding: "0 7px" }}>{x.sentiment}</span>}</div>
            </div>
          ))}
          {list && <div className="row between xs muted"><span>page {page} · 30 per page · newest first</span><span>
            <button className="btn sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>‹</button> <button className="btn sm" disabled={!list.more} onClick={() => setPage((p) => p + 1)}>›</button></span></div>}
        </div>
        <div className="card" data-testid="conv-detail">
          {detErr && <div className="xs" style={{ color: "var(--red)" }}>Couldn't open this conversation: {detErr}</div>}
          {!det && !detErr && <div className="xs muted">{sel ? "Loading…" : "Pick a conversation."}</div>}
          {det && A && <>
            <div className="row between"><div className="row" style={{ gap: 10 }}><div className="pair">{det.people.map((p) => <Av key={p.agent_id} w={p} s={34} />)}</div>
              <div><b>{det.people.map((p) => p.name).join(" & ")}</b><div className="xs muted">{KIND_LABEL[det.kind] ?? det.kind}{det.place ? ` · ${det.place}` : ""} · {det.label}</div></div></div>
              <span>{det.products.map((p) => <span key={p.id} className="chip teal">{p.name}</span>)}</span></div>
            <h3 style={{ marginTop: 14 }}>Before they talked <span className="privtag">PRIVATE</span></h3>
            <div className="grid g2" style={{ gap: 8 }}>{det.people.map((p) => (
              <div key={p.agent_id} className="privcard"><div className="h">{(p.name ?? "").split(" ")[0].toUpperCase()} DECIDED</div>
                {p.plan ? <><div><b>Will share:</b> {p.plan.share.length ? p.plan.share.join("; ") : "only if asked"}</div>
                  <div><b>Keeping private:</b> {p.plan.kept.length ? p.plan.kept.join("; ") : p.plan.withheld_count ? `${p.plan.withheld_count} thing(s)` : "—"}</div></>
                  : <div className="muted">No prep logged (a short chat written from templates).</div>}
                {p.store_thoughts.map((x, i) => <div key={i} style={{ marginTop: 4 }}>💭 {x.text}</div>)}</div>))}</div>
            <h3 style={{ marginTop: 14 }}>What they said</h3>
            <div className="chatcol">{det.messages.map((m) => (
              <div key={m.seq} className={`bub ${m.speaker === A.agent_id ? "l" : "r"}`}><div className="who">{typeof m.speaker === "number" ? name(m.speaker) : "Moderator"}</div>{m.text}</div>))}
              {!det.messages.length && <div className="small muted" data-testid="conv-summary">{det.people.map((p) => (p.name ?? "").split(" ")[0]).join(" and ")} chatted briefly about {(det.topics ?? []).map((t) => String(t).replace(/^product:/, "")).join(", ") || "everyday things"}. Only this summary was kept (budget), so there is no word-for-word transcript.</div>}</div>
            <h3 style={{ marginTop: 14 }}>What each one remembers <span className="privtag">PRIVATE MEMORY</span></h3>
            <div className="list">{det.people.filter((p) => p.memory?.text).map((p) => (
              <div key={p.agent_id} className="row" style={{ gap: 10, alignItems: "flex-start" }}><Av w={p} />
                <div className="privcard" style={{ flex: 1 }}><div className="h">{(p.name ?? "").split(" ")[0].toUpperCase()} · IMPORTANCE {p.memory?.importance ?? "?"}/10</div>{p.memory?.text}</div></div>))}
              {!det.people.some((p) => p.memory?.text) && <div className="xs muted">No memory written yet.</div>}</div>
            <div className="row" style={{ gap: 8, marginTop: 12 }}>
              {det.people.map((p) => <button key={p.agent_id} className="btn sm" onClick={() => { nav(withMode("/world")); setTimeout(() => open(p.agent_id, "conversations"), 80); }}>Open {(p.name ?? "").split(" ")[0]}'s profile</button>)}
              {det.place_xy && <button className="btn sm" onClick={() => { const xy = det.place_xy!; nav(withMode("/world")); setTimeout(() => worldRef.scene?.focusM(xy.x, xy.y, 3), 400); }}>Show on the map</button>}
            </div>
          </>}
          {det && !A && <div className="xs muted">This conversation has no participants recorded.</div>}
          {det && B === undefined && A && <div className="xs muted" style={{ marginTop: 6 }}>Only one side is recorded.</div>}
        </div>
        <div className="list" style={{ gap: 14 }}>
          <div className="card"><h3>What people talk about</h3>{sum ? <HBars rows={sum.topics} max={Math.max(10, ...sum.topics.map((t) => t[1]))} /> : <div className="xs muted">Loading…</div>}<p className="xs muted">{sum?.topics_note}</p></div>
          <div className="card"><h3>Said vs privately thought</h3>{(sum?.gap ?? []).map((g, i) => (
            <div key={i} className="item small" style={{ marginTop: i ? 8 : 0 }}><b>{g[0]}</b><div>Said: {g[1]}</div><div style={{ color: "var(--private)" }}>Thought: {g[2]} <span className="privtag">PRIVATE</span></div></div>))}
            {sum && !sum.gap.length && <div className="xs muted">No store visit has both a private thought and a spoken line yet.</div>}</div>
          <div className="card"><h3>How word spreads</h3>{det?.spread ? <>
            <div className="small">{det.spread.chain.map((w) => (w.name ?? `#${w.agent_id}`).split(" ")[0]).join(" → ")}</div>
            <div className="xs muted" style={{ marginTop: 4 }}>{det.products[0]?.name} reached {det.spread.chain.length} people in {det.spread.days} sim days through these conversations.</div></>
            : <div className="xs muted">{det?.products.length ? "This was the first conversation about it between these people." : "Pick a conversation about a product to trace how word reached it."}</div>}</div>
        </div>
      </div>
    </div>
  );
}
