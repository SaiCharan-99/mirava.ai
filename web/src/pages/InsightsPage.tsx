import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../components/Shell";
import { HBars, HeatTable, Kpi, LineChart, StackRow, VBars } from "../components/charts";
import { isVisualTest, withMode } from "../lib/visualTest";
import { loadFixtures, type Fixtures } from "../visual-fixtures/types";
import { useWorld } from "../state/world";
import * as D from "../visual-fixtures/insights-demo";
import {
  ask, getConversations, getHoardings, getOverview, getSegments, getSources, initials, mdToHtml, postJSON,
  type AskAnswer, type AskAnswerView, type ConversationsData, type HoardingsData, type OverviewData, type QuoteView,
  type SegmentsData, type SiteRow, type SourcesData,
} from "../lib/insights";
import { getJSON } from "../lib/api";
import { SurveyEntry } from "./survey/SurveyEntry";

const ITABS: [string, string][] = [["ask", "Ask"], ["overview", "Overview"], ["sources", "Sources"], ["hoardings", "Hoardings"],
  ["segments", "Segments"], ["conversations", "Conversations"], ["polls", "Polls"], ["interview", "Interview"]];

interface ProdInfo { name: string; hex: string }
type Names = Record<number, { name: string; age: number; shirt?: string; job?: string; phoneAge?: number }>;

function useFixtures(): Fixtures | null {
  const [f, setF] = useState<Fixtures | null>(null);
  useEffect(() => { if (isVisualTest) void loadFixtures().then(setF); }, []);
  return f;
}

/** Data hook: fixtures in visual-test mode, the API otherwise. */
function useData<T>(demo: T, load: () => Promise<T>, deps: unknown[] = []): T | null {
  const [d, setD] = useState<T | null>(isVisualTest ? demo : null);
  useEffect(() => {
    if (isVisualTest) return;
    let live = true;
    load().then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return d;
}

function Quote({ q, names }: { q: QuoteView; names: Names }) {
  const nav = useNavigate();
  const open = useWorld((s) => s.openProfile);
  const a = q.agent_id != null ? names[q.agent_id] : undefined;
  const name = a?.name ?? q.name ?? `#${q.agent_id}`;
  return (
    <div className="quote" style={q.private ? { borderLeftColor: "var(--private)" } : undefined}>
      “{q.text}” <span className="xs muted">— <a href="#" onClick={(e) => { e.preventDefault(); if (q.agent_id != null) { nav(withMode("/world")); setTimeout(() => open(q.agent_id!, "overview"), 80); } }}>{name}</a>{a?.age ? `, ${a.age}` : ""} · {q.kind}</span>{" "}
      {q.private ? <span className="privtag">PRIVATE THOUGHT</span> : null}
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="card"><p className="small muted" style={{ margin: 0 }}>{children}</p></div>;
}

// ---------------------------------------------------------------- Ask
function AnswerBlock({ a, names }: { a: AskAnswerView; names: Names }) {
  return (
    <div className="answer">
      {a.steps.length > 0 && <div className="list" style={{ gap: 4, marginBottom: 10 }}>{a.steps.map(([t, d], i) => <div key={i} className="toolstep">✓ <code>{t}</code> {d}</div>)}</div>}
      <p style={{ marginTop: 0 }} dangerouslySetInnerHTML={{ __html: a.html }} />
      {a.bars && (
        <div className="grid g2"><div><VBars rows={a.bars} w={420} h={190} ymax={a.ymax ?? 100} /><div className="xs muted">{a.barsNote}</div></div>
          <div className="small" dangerouslySetInnerHTML={{ __html: a.sideHtml ?? "" }} /></div>
      )}
      {a.quotes.map((q, i) => <Quote key={i} q={q} names={names} />)}
      {a.sql && a.sql.length > 0 && (
        <details style={{ marginTop: 10 }}><summary className="small" style={{ cursor: "pointer", color: "var(--teal)" }}>{a.sqlLabel ?? `Show SQL (${a.sql.length} quer${a.sql.length === 1 ? "y" : "ies"})`}</summary>
          <div className="sqlbox" style={{ marginTop: 8 }}>{a.sql.join("\n\n")}</div></details>
      )}
      {a.caveats && <div className="xs muted" style={{ marginTop: 8 }}>{a.caveats}</div>}
    </div>
  );
}

function toView(ans: AskAnswer, steps: string[]): AskAnswerView {
  const ch = (ans.charts || [])[0] as { xAxis?: { data?: string[] }; series?: { data: number[] }[]; _source_ref?: string } | undefined;
  const xs = ch?.xAxis?.data ?? [];
  const ys = ch?.series?.[0]?.data ?? [];
  const pct = ys.every((v) => v <= 1);
  const bars = xs.length ? xs.map((x, i): [string, number, string] => [x, Math.round((pct ? 100 : 1) * (ys[i] ?? 0) * 10) / 10, ["#22c55e", "#8b5cf6", "var(--teal)", "#f97316", "#60a5fa", "#f5b041"][i % 6]]) : undefined;
  const ymax = bars ? Math.max(10, ...bars.map((b) => b[1])) * 1.15 : undefined;
  return {
    steps: steps.map((s) => { const m = s.match(/^(\S+)\s(.*)$/); return [m ? m[1] : s, m ? m[2] : ""] as [string, string]; }),
    html: mdToHtml(ans.answer_md), bars, ymax: ymax ? Math.ceil(ymax) : undefined, barsNote: bars ? "simulated · from the query shown below" : undefined,
    sideHtml: ans.numbers.length ? `<b>Key numbers</b><ul style="margin:6px 0 0;padding-left:18px">${ans.numbers.slice(0, 5).map((n) => `<li>${n.label}: <b>${Number.isInteger(n.value) ? n.value.toLocaleString("en-IN") : n.value.toFixed(n.value < 1 ? 3 : 1)}</b></li>`).join("")}</ul>` : "",
    quotes: ans.quotes.map((q) => ({ agent_id: q.agent_id, name: q.name, text: q.text, kind: q.kind ?? "", private: q.private })),
    sql: ans.sql, caveats: ans.caveats.length ? "Caveats: " + ans.caveats.join(" ") : undefined, suggestions: ans.suggestions,
  };
}

function AskTab({ names }: { names: Names }) {
  const [thread, setThread] = useState<{ q: string; a: AskAnswerView | null; steps: string[] }[]>(isVisualTest ? D.DEMO_ASK.map((x) => ({ ...x, steps: [] })) : []);
  const [q, setQ] = useState("");
  const [sugg, setSugg] = useState<string[]>(D.DEMO_SUGGESTIONS);
  const busy = thread.some((t) => t.a === null);
  const run = async (question: string) => {
    if (!question.trim() || isVisualTest) return;
    setQ("");
    const idx = thread.length;
    setThread((t) => [...t, { q: question, a: null, steps: [] }]);
    const steps: string[] = [];
    try {
      const ans = await ask(question, (s) => { steps.push(s); setThread((t) => t.map((x, i) => (i === idx ? { ...x, steps: [...steps] } : x))); });
      setThread((t) => t.map((x, i) => (i === idx ? { ...x, a: toView(ans, steps.filter((s) => !s.startsWith("Reading the data") && !s.startsWith("Checked") && !s.startsWith("Writing"))) } : x)));
      if (ans.suggestions?.length) setSugg(ans.suggestions);
    } catch (e) {
      setThread((t) => t.map((x, i) => (i === idx ? { ...x, a: { steps: [], html: `Sorry — ${String(e)}`, quotes: [] } } : x)));
    }
  };
  return (
    <div className="grid g31">
      <div>
        <div className="list" data-testid="ask-thread" style={{ gap: 14 }}>
          {thread.length === 0 && <div className="answer"><p className="small muted" style={{ margin: 0 }}>Ask a question about the simulated world. Answers come only from logged data: SQL on curated views, semantic search over thoughts and messages, cohorts and likely-buyer segments.</p></div>}
          {thread.map((t, i) => (
            <div key={i} className="list" style={{ gap: 14 }}>
              <div className="qbubble">{t.q}</div>
              {t.a ? <AnswerBlock a={t.a} names={names} /> : (
                <div className="answer"><div className="list" style={{ gap: 4 }}>{t.steps.map((s, k) => <div key={k} className="toolstep">… {s}</div>)}<div className="toolstep">… thinking</div></div></div>
              )}
            </div>
          ))}
        </div>
        <form className="askbar" data-testid="ask-input" style={{ marginTop: 14 }} onSubmit={(e) => { e.preventDefault(); void run(q); }}>
          <input placeholder="Ask about any product, place, segment, conversation…" value={q} onChange={(e) => setQ(e.target.value)} disabled={busy} />
          <button className="btn primary" type="submit" disabled={busy}>Ask</button>
        </form>
        <div className="sugg" data-testid="ask-suggestions" style={{ marginTop: 10 }}>{sugg.map((s) => <button key={s} onClick={() => void run(s)}>{s}</button>)}</div>
      </div>
      <div className="grid" style={{ alignContent: "start" }}>
        <div className="card"><h3>What the assistant can use</h3><div className="list small">{[["Raw log", "every thought, message, exposure, inquiry, purchase (BigQuery)"], ["Semantic search", "VECTOR_SEARCH over thoughts, chats, posts, reviews"], ["Cohorts", "any filter on agents: age, income, phone age, stage…"], ["Likely-buyer model", "need × interest × affordability × stage"], ["Poll / interview", "ask agents now (uses budget, asks first)"]].map(([h, t]) => <div key={h} className="item"><b>{h}</b><div className="xs muted">{t}</div></div>)}</div></div>
        <div className="card"><h3>Faithfulness</h3><p className="small muted" style={{ margin: 0 }}>Every number comes from a tool result; quotes are verbatim and private thoughts are labelled. If a check fails, the answer is regenerated or the claim is dropped.</p></div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Overview
function OverviewTab() {
  const d = useData<OverviewData>(D.DEMO_OVERVIEW, getOverview);
  if (!d) return <Empty>Loading overview…</Empty>;
  return (
    <>
      <div className="grid g4">{d.kpis.map((k, i) => <Kpi key={i} l={k[0]} v={k[1]} d={k[2]} />)}</div>
      <div className="grid g21" style={{ marginTop: 14 }}>
        <div className="card"><h3>Awareness and curious+ over sim days</h3>{d.series.length ? <LineChart series={d.series} labels={d.labels} ymax={d.ymax} events={d.events} /> : <p className="small muted">No product is live yet.</p>}</div>
        <div className="card"><h3>Funnel today</h3>
          <table><tbody><tr><th>Stage</th>{d.funnel.cols.map((c) => <th key={c}>{c}</th>)}</tr>
            {d.funnel.rows.map((r) => <tr key={String(r[0])}><td>{r[0]}</td>{r.slice(1).map((v, i) => <td key={i} className="mono">{typeof v === "number" ? v.toLocaleString("en-IN") : v}</td>)}</tr>)}</tbody></table>
          <p className="xs muted">{d.note}</p></div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Sources
function SourcesTab() {
  const d = useData<SourcesData>(D.DEMO_SOURCES, getSources);
  if (!d) return <Empty>Loading sources…</Empty>;
  return (
    <div className="grid g21">
      <div className="card"><h3>Where people first heard</h3>{d.stacks.map((s) => <StackRow key={s.label} label={s.label} parts={s.parts} cols={d.cols} />)}
        <div className="legend">{d.labels.map((l, i) => <span key={l}><i style={{ background: d.cols[i] }} />{l}</span>)}</div></div>
      <div className="card"><h3>Top paths to a store inquiry</h3><div className="list small">{d.paths.map((r) => <div key={r[0]} className="item row between"><span>{r[0]}</span><b className="mono">{r[1]}</b></div>)}</div>
        <p className="xs muted">{d.note}</p></div>
    </div>
  );
}

// ---------------------------------------------------------------- Hoardings
function SitesMap({ rows, sites }: { rows: SiteRow[]; sites: { site_id: string; x: number; y: number }[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    cv.width = r.width * dpr; cv.height = r.height * dpr;
    const c = cv.getContext("2d");
    if (!c || !sites.length) return;
    const xs = sites.map((s) => s.x), ys = sites.map((s) => s.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const z = Math.min((cv.width * 0.9) / Math.max(1, x1 - x0), (cv.height * 0.9) / Math.max(1, y1 - y0));
    const ox = (cv.width - (x1 - x0) * z) / 2, oy = (cv.height - (y1 - y0) * z) / 2;
    const rate = Object.fromEntries(rows.map((x) => [x[0], x[6]]));
    for (const s of sites) {
      const v = rate[s.site_id];
      if (v === undefined) { c.fillStyle = "#334155"; } else c.fillStyle = v > 7 ? "#4ade80" : v > 5 ? "#f5b041" : "#f87171";
      c.beginPath(); c.arc(ox + (s.x - x0) * z, oy + (s.y - y0) * z, (4 + (v ?? 0) * 0.6) * dpr, 0, 7); c.fill();
      c.strokeStyle = "#0a0d12"; c.lineWidth = 1.5 * dpr; c.stroke();
    }
  }, [rows, sites]);
  return <canvas ref={ref} id="sitesMap" data-testid="sites-map" style={{ width: "100%", height: "100%", display: "block" }} />;
}

function HoardingsTab({ prods, fx }: { prods: Record<string, ProdInfo>; fx: Fixtures | null }) {
  const demo = useMemo<HoardingsData | null>(() => {
    if (!isVisualTest) return null;
    const ins = (fx as unknown as { insights?: { hoardings: SiteRow[] }; sites?: { id: string; x: number; y: number }[] } | null);
    return { kpis: D.DEMO_HOARDINGS_KPIS, rows: ins?.insights?.hoardings ?? [], heat: D.DEMO_HOARDINGS_HEAT, themes: D.DEMO_HOARDINGS_THEMES,
      sites: (ins?.sites ?? []).map((s) => ({ site_id: s.id, x: s.x, y: s.y })) };
  }, [fx]);
  const live = useData<HoardingsData>(null as unknown as HoardingsData, getHoardings);
  const d = isVisualTest ? demo : live;
  const [sel, setSel] = useState<string | null>(null);
  const [th, setTh] = useState<{ text: string; t: number }[]>([]);
  useEffect(() => { if (sel && !isVisualTest) void getJSON<{ text: string; t: number }[]>(`/insights/hoardings/${sel}/thoughts`).then(setTh); }, [sel]);
  if (!d) return <Empty>Loading hoardings…</Empty>;
  const fmt = (n: number) => Math.round(n).toLocaleString("en-IN");
  return (
    <>
      <div className="grid g3">{d.kpis.map((k, i) => <Kpi key={i} l={k[0]} v={k[1]} d={k[2]} />)}</div>
      <div className="grid g21" style={{ marginTop: 14 }}>
        <div className="card" data-testid="sites-table"><div className="row between"><h3 style={{ margin: 0 }}>Site leaderboard · last 7 sim days</h3><span className="xs muted">OTS = in the cone, in front, looking towards it</span></div>
          <table style={{ marginTop: 8 }}><tbody>
            <tr><th>Site</th><th>Faces</th><th>Location</th><th>Showing</th><th style={{ textAlign: "right" }}>OTS/day</th><th style={{ textAlign: "right" }}>Glance</th><th style={{ textAlign: "right" }}>Notice</th><th style={{ textAlign: "right" }}>Thoughts</th><th style={{ textAlign: "right" }}>Sentiment</th></tr>
            {d.rows.map((r, i) => (
              <tr key={i} style={{ cursor: "pointer" }} onClick={() => setSel(r[0])}>
                <td className="mono small" style={{ whiteSpace: "nowrap" }}>{r[0]}</td><td>{r[1]}</td><td className="small">{r[2]}</td>
                <td>{prods[r[3]] ? <><span className="pdot" style={{ background: prods[r[3]].hex, width: 8, height: 8, marginRight: 5 }} />{prods[r[3]].name}</> : <span className="muted">baseline</span>}</td>
                <td className="mono" style={{ textAlign: "right" }}>{fmt(r[4])}</td><td className="mono" style={{ textAlign: "right" }}>{r[5]}%</td>
                <td style={{ textAlign: "right" }}><b className="nrate" style={{ color: r[6] > 7 ? "var(--green)" : r[6] > 5 ? "var(--amber)" : "var(--red)" }}>{r[6]}%</b></td>
                <td className="mono" style={{ textAlign: "right" }}>{r[7]}</td><td className="mono" style={{ textAlign: "right" }}>{r[8]}</td>
              </tr>
            ))}</tbody></table>
          {sel && !isVisualTest && <div className="list small" style={{ marginTop: 10 }}><b>Private thoughts at {sel}</b>{th.map((x, i) => <div key={i} className="item">“{x.text}” <span className="privtag">PRIVATE THOUGHT</span></div>)}{!th.length && <span className="muted xs">none rendered yet</span>}</div>}
        </div>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}><div style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}><h3 style={{ margin: 0 }}>Notice rate on the map</h3></div>
          <div style={{ height: 330, background: "#0a0d12" }}><SitesMap rows={d.rows} sites={d.sites ?? []} /></div>
          <div className="legend" style={{ padding: "10px 14px" }}><span><i style={{ background: "#4ade80" }} />&gt; 7%</span><span><i style={{ background: "#f5b041" }} />5–7%</span><span><i style={{ background: "#f87171" }} />&lt; 5%</span></div></div>
      </div>
      <div className="grid g2" style={{ marginTop: 14 }}>
        <div className="card"><h3>Notice rate by hour (all sites)</h3><HeatTable rows={d.heat.rows} cols={d.heat.cols} vals={d.heat.vals} max={10} /></div>
        <div className="card"><h3>What people think when they notice</h3><div className="list small">{d.themes.map((t, i) => <div key={i} className="item">“{t[0]}” <span className="xs muted">· {t[1]} similar</span></div>)}</div>
          <p className="xs muted">For media owners: rank sites by notice rate × target share, not raw traffic.</p></div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Segments
function SegmentsTab() {
  const [p, setP] = useState("");
  const d = useData<SegmentsData>(D.DEMO_SEGMENTS, () => getSegments(p), [p]);
  if (!d) return <Empty>Loading segments…</Empty>;
  if (!d.heat) return <Empty>No product is live yet.</Empty>;
  const cur = d.product ?? d.products[0]?.id;
  return (
    <>
      <div className="row between" style={{ marginBottom: 12 }}>
        <div className="seg">{d.products.map((x) => <button key={x.id} className={x.id === cur ? "on" : ""} onClick={() => setP(x.id)}>{x.name}</button>)}</div>
        <span className="xs muted">Likely-buyer score = need × interest × affordability × stage weight · aggregated, never per person</span>
      </div>
      <div className="grid g21">
        <div className="card"><h3>Likely buyers · age × income (share of segment)</h3>
          <HeatTable rows={d.heat.rows} cols={d.heat.cols} vals={d.heat.vals} max={40} titles={d.heat.n?.map((r) => r.map((n) => `n = ${n}`))} />
          <p className="xs muted">Cells show the share of agents in that segment with a likely-buyer score ≥ 0.5. Hover in the real app shows n and top reasons.</p></div>
        <div className="card"><h3>Lifestyles most likely to buy — and why</h3><div className="list small">{d.lifestyles.map((r) => (
          <div key={r[0]} className="item"><div className="row between"><b>{r[0]}</b><b className="mono">{r[3]}</b></div><div className="xs muted">{r[1]}</div><div className="xs">Why: {r[2]}</div></div>
        ))}</div></div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Conversations
function ConversationsTab() {
  const d = useData<ConversationsData>(D.DEMO_CONVERSATIONS, getConversations);
  if (!d) return <Empty>Loading conversations…</Empty>;
  return (
    <>
      <div className="grid g3">
        <div className="card"><h3>What people talk about</h3><HBars rows={d.topics} max={40} /><p className="xs muted">{d.topics_note}</p></div>
        <div className="card" style={{ gridColumn: "span 2" }}><h3>Said vs privately thought</h3>
          <table><tbody><tr><th>Topic</th><th>Said out loud</th><th>Privately thought</th><th>Gap</th></tr>
            {d.gap.map((r, i) => <tr key={i}><td>{r[0]}</td><td className="small">{r[1]}</td><td className="small" style={{ color: "var(--private)" }}>{r[2]}</td><td className="xs muted">{r[3]}</td></tr>)}</tbody></table></div>
      </div>
      <div className="grid g2" style={{ marginTop: 14 }}>
        <div className="card"><h3>Reviewers · private opinion vs published review</h3><div className="list small">{d.reviewers.map((r, i) => (
          <div key={i} className="item"><b>{r[0]}</b> · {r[1]}<div className="xs" style={{ color: "var(--private)", marginTop: 4 }}>Private: {r[2]}</div><div className="xs" style={{ marginTop: 2 }}>Published: {r[3]}</div></div>
        ))}</div></div>
        <div className="card"><h3>Community threads</h3><div className="list small">{d.threads.map((r, i) => (
          <div key={i} className="item"><div className="xs muted">{r[0]} · {r[2]}</div><b>{r[1]}</b><div className="xs muted">{r[3]}</div></div>
        ))}</div></div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Polls
interface PollDoc { poll_id: string; status: string; question: string; options: string[]; n: number; distribution?: Record<string, number>;
  by_phone_age?: { rows: string[]; cols: string[]; vals: number[][] }; quotes?: { agent_id: number; name: string; text: string }[]; t?: number; cost_usd?: number; seconds?: number }

function PollsTab({ names }: { names: Names }) {
  const [question, setQuestion] = useState(D.DEMO_POLL.question);
  const [opts, setOpts] = useState(D.DEMO_POLL.optionsText);
  const [cohort, setCohort] = useState("");
  const [est, setEst] = useState<{ estimate_usd: number; n: number; seconds_est: number } | null>(null);
  const [doc, setDoc] = useState<PollDoc | null>(null);
  const [err, setErr] = useState("");
  const options = opts.split("·").map((s) => s.trim()).filter(Boolean);
  useEffect(() => {
    if (isVisualTest) return;
    const h = setTimeout(() => { postJSON<{ estimate_usd: number; n: number; seconds_est: number }>("/insights/poll", { question, options, cohort: cohort || null }).then(setEst).catch(() => setEst(null)); }, 400);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question, opts, cohort]);
  useEffect(() => { if (!isVisualTest) void getJSON<PollDoc[]>("/insights/polls").then((l) => l[0] && setDoc(l[0])).catch(() => undefined); }, []);
  const runPoll = async () => {
    setErr("");
    try {
      const r = await postJSON<{ poll_id: string }>("/insights/poll", { question, options, cohort: cohort || null, confirm: true });
      const poll = async () => { const p = await getJSON<PollDoc>(`/insights/poll/${r.poll_id}`).catch(() => null); if (p) setDoc(p); if (!p || p.status !== "done") setTimeout(poll, 1500); };
      void poll();
    } catch (e) { setErr(String(e)); }
  };
  const view = isVisualTest ? D.DEMO_POLL : null;
  const dist = doc?.distribution ?? {};
  const total = Object.values(dist).reduce((a, b) => a + b, 0);
  const cols = ["#94a3b8", "#60a5fa", "#22c55e", "#8b5cf6", "#f97316", "#f5b041", "#ec4899", "#2dd4bf"];
  const bars = view ? view.bars : Object.entries(dist).sort((a, b) => b[1] - a[1]).map(([k, v], i): [string, number, string] => [k, Math.round((100 * v) / Math.max(1, total)), cols[i % 8]]);
  const q0 = view ? view.quote : doc?.quotes?.[0] ? { agent_id: doc.quotes[0].agent_id, name: doc.quotes[0].name, text: doc.quotes[0].text, kind: "poll answer", private: false } : null;
  const heat = view ? view.heat : doc?.by_phone_age;
  return (
    <div className="grid g12">
      <div className="card"><h3>New poll</h3><label>Question</label><textarea value={question} onChange={(e) => setQuestion(e.target.value)} />
        <label style={{ marginTop: 10 }}>Options</label><input value={opts} onChange={(e) => setOpts(e.target.value)} />
        <label style={{ marginTop: 10 }}>Ask</label>
        <select value={cohort} onChange={(e) => setCohort(e.target.value)}><option value="">{D.DEMO_POLL.cohorts[0]}</option><option value="phone_age_years > 5">{D.DEMO_POLL.cohorts[1]}</option></select>
        <div className="item small" style={{ marginTop: 10 }}>Estimated cost <b>{view ? view.estimate : est ? `$${est.estimate_usd.toFixed(2)}` : "…"}</b> from the interactive budget · ~{est ? est.seconds_est : 60} s · answers come from each agent's own memory</div>
        <button className="btn primary" style={{ marginTop: 10 }} onClick={() => void runPoll()}>Run poll</button>
        {err && <div className="xs" style={{ color: "var(--red)", marginTop: 6 }}>{err}</div>}</div>
      <div className="card"><div className="row between"><h3 style={{ margin: 0 }}>{view ? view.title : doc ? `Result · ${doc.status === "done" ? `${(doc.n || 0).toLocaleString("en-IN")} agents${doc.seconds ? ` · ${doc.seconds} s · $${(doc.cost_usd ?? 0).toFixed(3)}` : ""}` : doc.status}` : "No poll yet"}</h3><span className="sim-badge">SIMULATED</span></div>
        {doc && !view && <div className="xs muted" style={{ marginTop: 4 }}>{doc.question}</div>}
        <div style={{ marginTop: 10 }}><HBars rows={bars} max={view ? view.max : Math.max(10, ...bars.map((b) => b[1]))} /></div>
        {heat && <><h3 style={{ marginTop: 14 }}>By phone age</h3><HeatTable rows={heat.rows} cols={heat.cols} vals={heat.vals} max={80} /></>}
        {q0 && <Quote q={q0} names={names} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Interview
interface Turn { role: "me" | "ai"; text: string; mem?: string }
function InterviewTab({ names, fx }: { names: Names; fx: Fixtures | null }) {
  const [list, setList] = useState<{ agent_id: number; name: string; occupation: string; phone: { age_years: number } }[]>([]);
  const [sel, setSel] = useState<number | null>(isVisualTest ? D.DEMO_INTERVIEW.selected : null);
  const [chat, setChat] = useState<Turn[]>(isVisualTest ? (D.DEMO_INTERVIEW.chat as Turn[]) : []);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!isVisualTest) void getJSON<typeof list>(`/insights/interview/agents?q=${encodeURIComponent(search)}`).then((l) => { setList(l); if (sel === null && l[0]) setSel(l[0].agent_id); }).catch(() => undefined); }, [search]); // eslint-disable-line react-hooks/exhaustive-deps
  const rows = isVisualTest
    ? D.DEMO_INTERVIEW.agents.map((id) => { const a = fx?.agents.find((x) => x.id === id); return { agent_id: id, name: a?.name ?? "", occupation: a?.job ?? "", phone: { age_years: a?.phone.age ?? 0 }, shirt: a?.look.shirt }; })
    : list.map((a) => ({ ...a, shirt: undefined as string | undefined }));
  const cur = rows.find((r) => r.agent_id === sel);
  const first = cur?.name.split(" ")[0] ?? "";
  const send = async () => {
    if (!q.trim() || sel === null || isVisualTest) return;
    const question = q;
    setQ(""); setBusy(true);
    setChat((c) => [...c, { role: "me", text: question }]);
    try {
      const r = await postJSON<{ answer: string; memories: { text: string; t: number }[] }>("/insights/interview", { agent_id: sel, question, session_id: `iv-${sel}` });
      setChat((c) => [...c, { role: "ai", text: r.answer, mem: r.memories.length ? "memories used: " + r.memories.map((m) => m.text.slice(0, 50)).join(" · ") : "" }]);
    } catch (e) { setChat((c) => [...c, { role: "ai", text: `(${String(e)})` }]); }
    setBusy(false);
  };
  return (
    <div className="grid g12">
      <div className="card"><h3>Interview someone</h3><input placeholder="Search agents…" style={{ marginBottom: 10 }} value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="list">{rows.slice(0, 8).map((a) => (
          <div key={a.agent_id} className="item row" style={{ gap: 10, cursor: "pointer", ...(a.agent_id === sel ? { borderColor: "var(--teal)", background: "var(--teal-soft)" } : {}) }}
            onClick={() => { setSel(a.agent_id); if (!isVisualTest) setChat([]); }}>
            <div className="avatar" style={{ background: a.shirt ?? "var(--c2)" }}>{initials(a.name)}</div>
            <div><b>{a.name}</b><div className="xs muted">{a.occupation} · phone {Math.round((a.phone?.age_years ?? 0) * 10) / 10} yrs</div></div>
          </div>
        ))}</div></div>
      <div className="card"><div className="row between"><h3 style={{ margin: 0 }}>{isVisualTest ? D.DEMO_INTERVIEW.title : cur ? `${cur.name}${names[cur.agent_id]?.age ? `, ${names[cur.agent_id].age}` : ""} · in character` : "Pick someone"}</h3>
        <span className="xs muted">{isVisualTest ? D.DEMO_INTERVIEW.note : `grounded only in ${first}'s own memories`}</span></div>
        <div className="chat" style={{ marginTop: 10 }}>{chat.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>{m.text}{m.mem ? <div className="xs muted" style={{ marginTop: 6 }}>{m.mem}</div> : null}</div>
        ))}{busy && <div className="msg ai">…</div>}</div>
        <form className="askbar" style={{ marginTop: 10 }} onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <input placeholder={isVisualTest ? D.DEMO_INTERVIEW.placeholder : `Ask ${first || "them"}…`} value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn primary" type="submit" disabled={busy}>Send</button></form></div>
    </div>
  );
}

// ---------------------------------------------------------------- page
export function InsightsPage() {
  const { tab = "ask" } = useParams();
  const nav = useNavigate();
  const fx = useFixtures();
  const [prods, setProds] = useState<Record<string, ProdInfo>>({});
  const [live, setLive] = useState<{ n: number; day: string }>({ n: 0, day: "" });
  useEffect(() => {
    if (isVisualTest) {
      if (fx) setProds(Object.fromEntries(fx.products.map((p) => [p.id, { name: p.name, hex: p.hex }])));
      return;
    }
    void getJSON<{ product_id: string; name: string; color: string; status: string }[]>("/products").then((l) => {
      setProds(Object.fromEntries(l.map((p) => [p.product_id, { name: p.name, hex: p.color }])));
      setLive((s) => ({ ...s, n: l.filter((p) => p.status === "live").length }));
    }).catch(() => undefined);
    void getJSON<{ label: string }>("/world/state").then((s) => setLive((x) => ({ ...x, day: s.label.split(" · ")[0] }))).catch(() => undefined);
  }, [fx]);
  const names = useMemo<Names>(() => (fx ? Object.fromEntries(fx.agents.map((a) => [a.id, { name: a.name, age: a.age, shirt: a.look.shirt, job: a.job, phoneAge: a.phone.age }])) : {}), [fx]);
  const chip = isVisualTest ? D.DEMO_DATA_CHIP : `Data: Day 1 → ${live.day || "…"} · ${live.n} product${live.n === 1 ? "" : "s"} live`;
  const body: Record<string, () => ReactNode> = {
    ask: () => <AskTab names={names} />, overview: () => <OverviewTab />, sources: () => <SourcesTab />,
    hoardings: () => <HoardingsTab prods={prods} fx={fx} />, segments: () => <SegmentsTab />, conversations: () => <ConversationsTab />,
    polls: () => <PollsTab names={names} />, interview: () => <InterviewTab names={names} fx={fx} />,
  };
  return (
    <div className="page">
      <PageTitle title="Insights" sub="Ask anything about what the world has seen, thought, said and bought. Answers come only from logged data."
        right={<>{tab === "polls" && <span style={{ position: "relative", width: 0, height: 0, marginRight: -9 }}><span style={{ position: "absolute", right: "-180px", bottom: 22 }}><SurveyEntry /></span></span>}<span className="chip">{chip}</span><span className="sim-badge">SIMULATED</span></>} />
      <div className="tabs" data-testid="insights-tabs">{ITABS.map(([k, l]) => (
        <button key={k} data-testid={`insights-tab-${k}`} className={tab === k ? "on" : ""} onClick={() => nav(withMode(`/insights/${k}`))}>{l}</button>
      ))}</div>
      <div data-testid="insights-body">{(body[tab] ?? body.ask)()}</div>
    </div>
  );
}

