import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../../components/Shell";
import { HeatTable } from "../../components/charts";
import { getJSON } from "../../lib/api";
import { agentNames, flows, mean, type Edge, type Report, type ReportQ } from "../../lib/focus";
import { launchSurvey, rerunSurvey, type SurveyDoc } from "../../lib/survey";
import { withMode } from "../../lib/visualTest";
import { SessionsCol } from "./SessionsCol";

const COL = ["#2dd4bf", "#f5b041", "#a78bfa", "#94a3b8", "#60a5fa", "#f472b6"];
const INFL_COL: Record<string, string> = { persuaded: "#2dd4bf", conformed: "#f5b041", reinforced: "#60a5fa", unchanged: "#64748b", reacted_against: "#f472b6" };
const EDGE_COL: Record<Edge["type"], string> = { persuaded: "#2dd4bf", went_along: "#f5b041", pushed_back: "#f472b6" };
type Names = Record<number, { name: string; age: number }>;
type Doc = Omit<SurveyDoc, "results"> & { results?: Report; counts?: { attended?: number; accepted?: number }; completed_t?: number; start_label?: string; product_name?: string };

const fmt = (v: unknown) => (Array.isArray(v) ? v.join(", ") : String(v));

/** Before (first private answer) → after (final ballot) flow. */
function Sankey({ q }: { q: ReportQ }) {
  const opts = Array.from(new Set([...(q.options ?? []), ...Object.keys(q.pre_distribution), ...Object.keys(q.distribution)]));
  const tot = Math.max(1, ...[Object.values(q.pre_distribution), Object.values(q.distribution)].map((v) => v.reduce((a, b) => a + b, 0)));
  const W = 640, H = 260, x0 = 185, x1 = W - 185, gap = 8, ih = H - gap * (opts.length - 1);
  const pos = (m: Record<string, number>) => { let y = 0; const o: Record<string, { y: number; h: number; used: number }> = {}; for (const k of opts) { const h = ((m[k] ?? 0) / tot) * ih; o[k] = { y, h, used: 0 }; y += h + gap; } return o; };
  const L = pos(q.pre_distribution), R = pos(q.distribution);
  if (!Object.keys(q.pre_distribution).length) return <div className="xs muted">No first answers were recorded (written surveys answer once).</div>;
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" data-testid="sankey">
        {flows(q.shift).map(([a, b, n], i) => {
          if (!L[a] || !R[b]) return null;
          const h = (n / tot) * ih, ya = L[a].y + L[a].used, yb = R[b].y + R[b].used;
          L[a].used += h; R[b].used += h;
          const m = (x0 + x1) / 2;
          return <path key={i} d={`M${x0},${ya} C${m},${ya} ${m},${yb} ${x1},${yb} L${x1},${yb + h} C${m},${yb + h} ${m},${ya + h} ${x0},${ya + h} Z`} fill={COL[opts.indexOf(a) % COL.length]} opacity={a === b ? 0.28 : 0.75} />;
        })}
        {opts.map((k, i) => (
          <g key={k}>
            <rect x={x0 - 10} y={L[k].y} width={10} height={Math.max(1, L[k].h)} fill={COL[i % COL.length]} rx={2} />
            <rect x={x1} y={R[k].y} width={10} height={Math.max(1, R[k].h)} fill={COL[i % COL.length]} rx={2} />
            <text x={x0 - 16} y={L[k].y + L[k].h / 2 + 4} textAnchor="end" fontSize={12} style={{ fill: "var(--ink2)" }}>{k.slice(0, 22)} · {q.pre_distribution[k] ?? 0}</text>
            <text x={x1 + 16} y={R[k].y + R[k].h / 2 + 4} fontSize={12} style={{ fill: "var(--ink2)" }}>{q.distribution[k] ?? 0} · {k.slice(0, 22)}</text>
          </g>
        ))}
      </svg>
      <div className="row between xs muted"><span>← before the discussion (private first answer)</span><span>final private ballot →</span></div>
    </>
  );
}

/** Who moved whom: participants grouped by table; arrows from the speaker who moved someone to that person. */
function Network({ edges, seats, names }: { edges: Edge[]; seats: Record<string, string>; names: Names }) {
  const W = 560, H = 300, cx = W / 2, cy = H / 2;
  const tables = Array.from(new Set(Object.values(seats))).sort();
  const pts: Record<number, { x: number; y: number }> = {};
  tables.forEach((tb, ti) => {
    const ids = Object.entries(seats).filter(([, t]) => t === tb).map(([a]) => Number(a));
    const ang = (ti / Math.max(1, tables.length)) * 2 * Math.PI - Math.PI / 2;
    const tx = cx + Math.cos(ang) * (tables.length > 1 ? 92 : 0), ty = cy + Math.sin(ang) * (tables.length > 1 ? 92 : 0);
    ids.forEach((a, k) => { const a2 = (k / Math.max(1, ids.length)) * 2 * Math.PI; pts[a] = { x: tx + Math.cos(a2) * 34, y: ty + Math.sin(a2) * 30 }; });
  });
  const moved: Record<number, number> = {};
  for (const e of edges) if (e.type !== "pushed_back") moved[e.from] = (moved[e.from] ?? 0) + 1;
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" data-testid="network">
        <defs>{(["persuaded", "went_along"] as const).map((t) => <marker key={t} id={`ar-${t}`} viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto"><path d="M0,0 L8,4 L0,8 z" fill={EDGE_COL[t]} /></marker>)}</defs>
        {edges.map((e, i) => {
          const A = pts[e.from], B = pts[e.to];
          if (!A || !B) return null;
          return e.type === "pushed_back"
            ? <line key={i} x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke={EDGE_COL[e.type]} strokeDasharray="4 3" strokeWidth={2} />
            : <line key={i} x1={A.x} y1={A.y} x2={B.x - (B.x - A.x) * 0.12} y2={B.y - (B.y - A.y) * 0.12} stroke={EDGE_COL[e.type]} strokeWidth={2} markerEnd={`url(#ar-${e.type})`} />;
        })}
        {Object.entries(pts).map(([a, p]) => {
          const id = Number(a), hub = (moved[id] ?? 0) >= 2;
          return <g key={a}><circle cx={p.x} cy={p.y} r={hub ? 9 : 5.5} fill={COL[id % COL.length]} stroke="var(--bg)" strokeWidth={1.5}><title>{names[id]?.name ?? `#${id}`}</title></circle>
            {hub && <text x={p.x} y={p.y - 13} textAnchor="middle" fontSize={11} style={{ fill: "var(--ink)", fontWeight: 700 }}>{names[id]?.name.split(" ")[0] ?? id}</text>}</g>;
        })}
        {tables.map((tb, ti) => { const ang = (ti / Math.max(1, tables.length)) * 2 * Math.PI - Math.PI / 2; return <text key={tb} x={cx + Math.cos(ang) * 150} y={cy + Math.sin(ang) * 140 + 4} textAnchor="middle" fontSize={10} style={{ fill: "var(--muted)" }}>{tb.replace("T", "Table ")}</text>; })}
      </svg>
      <div className="legend-sm"><span><i style={{ background: EDGE_COL.persuaded }} />persuaded by</span><span><i style={{ background: EDGE_COL.went_along }} />went along with</span><span><i style={{ background: EDGE_COL.pushed_back }} />pushed back against</span><span>dot size = how many people they moved</span></div>
      {!edges.length && <div className="xs muted" style={{ marginTop: 4 }}>Nobody's ballot named a speaker who changed their mind on this question.</div>}
    </>
  );
}

/** Each dot is one person; the line is the average. */
function DotStrip({ q }: { q: ReportQ }) {
  const lo = q.scale?.min ?? 1, hi = q.scale?.max ?? 5;
  const W = 560, H = 150, x = (v: number) => 40 + ((v - lo) / Math.max(1, hi - lo)) * (W - 80);
  const row = (arr: number[], y: number, col: string) => {
    const cnt: Record<number, number> = {};
    const dots = arr.map((v, i) => { const k = (cnt[v] = (cnt[v] ?? 0) + 1); return <circle key={i} cx={x(v) - 24 + ((k - 1) % 8) * 7} cy={y - 6 + Math.floor((k - 1) / 8) * 8} r={3.2} fill={col} />; });
    const m = mean(arr);
    return <>{dots}{arr.length > 0 && <><line x1={x(m)} x2={x(m)} y1={y - 16} y2={y + 18} stroke={col} strokeWidth={3} /><text x={x(m) + 6} y={y - 12} fontSize={11} style={{ fill: col, fontWeight: 700 }}>avg {m.toFixed(1)}</text></>}</>;
  };
  const ticks = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i).filter((v, _, a) => a.length <= 6 || (v - lo) % 2 === 0 || v === hi);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" data-testid="dot-strip">
      {ticks.map((v) => <g key={v}><line x1={x(v)} x2={x(v)} y1={10} y2={H - 26} stroke="var(--line)" /><text x={x(v)} y={H - 8} textAnchor="middle" fontSize={11} style={{ fill: "var(--muted)" }}>{v}{v === lo && q.scale?.low_label ? ` · ${q.scale.low_label}` : v === hi && q.scale?.high_label ? ` · ${q.scale.high_label}` : ""}</text></g>)}
      <text x={2} y={40} fontSize={10.5} style={{ fill: "var(--muted)" }}>before</text><text x={2} y={92} fontSize={10.5} style={{ fill: "var(--muted)" }}>after</text>
      {row(q.values_before ?? [], 40, "#94a3b8")}{row(q.values_after ?? [], 92, "#2dd4bf")}
    </svg>
  );
}

/** Open answers grouped into themes (bubble size = people). */
function Bubbles({ themes }: { themes: NonNullable<ReportQ["themes"]> }) {
  const W = 560, H = 220, pos: [number, number][] = [[82, 112], [215, 100], [322, 152], [402, 70], [492, 142], [150, 180]];
  const max = Math.max(1, ...themes.map((t) => t.n));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" data-testid="theme-bubbles">
      {themes.slice(0, 6).map((t, i) => {
        const r = 22 + (t.n / max) * 34, [x, y] = pos[i], w = t.theme.split(" "), a = w.slice(0, Math.ceil(w.length / 2)).join(" "), b = w.slice(Math.ceil(w.length / 2)).join(" ");
        return <g key={t.theme}><circle cx={x} cy={y} r={r} fill={COL[i % COL.length]} opacity={0.88} />
          <text x={x} y={y - 8} textAnchor="middle" fontSize={11} style={{ fill: "#05201c", fontWeight: 700 }}>{a}</text><text x={x} y={y + 5} textAnchor="middle" fontSize={11} style={{ fill: "#05201c", fontWeight: 700 }}>{b}</text>
          <text x={x} y={y + 19} textAnchor="middle" fontSize={10.5} style={{ fill: "#05201c" }}>{t.n} {t.n === 1 ? "person" : "people"}</text></g>;
      })}
    </svg>
  );
}

function AgeHeat({ q }: { q: ReportQ }) {
  const bands = ["18–24", "25–34", "35–44", "45–59", "60+"].filter((b) => q.by_segment[b]);
  const cols = Array.from(new Set([...(q.options ?? []), ...Object.keys(q.distribution)])).slice(0, 6);
  const vals = bands.map((b) => { const row = q.by_segment[b] ?? {}; const t = Object.values(row).reduce((a, c) => a + c, 0) || 1; return cols.map((c) => Math.round((100 * (row[c] ?? 0)) / t)); });
  return bands.length ? <HeatTable rows={bands} cols={cols.map((c) => c.slice(0, 14))} vals={vals} max={60} /> : <div className="xs muted">No age breakdown.</div>;
}

export function FocusResultsPage() {
  const { surveyId = "" } = useParams();
  const nav = useNavigate();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [err, setErr] = useState("");
  const [names, setNames] = useState<Names>({});
  const [qi, setQi] = useState(0);
  const [busy, setBusy] = useState(false);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    getJSON<Doc>(`/surveys/${surveyId}?include_private=1`).then((d) => { if (live) { setDoc(d); setErr(""); } }).catch((e: unknown) => live && setErr(e instanceof Error ? e.message : String(e)));
    agentNames().then((x) => live && setNames(x)).catch(() => undefined);
    return () => { live = false; };
  }, [surveyId, n]);
  const r = doc?.results;
  const q = r?.questions[qi];
  const edges = useMemo(() => (r?.edges ?? []).filter((e) => !q || e.question_id === q.question_id), [r, q]);
  if (err && !doc) return <div className="page"><PageTitle title="Results" sub="" /><div className="card"><b className="small">Couldn't load the results</b><div className="xs muted">{err}</div><button className="btn sm" style={{ marginTop: 8 }} onClick={() => setN((k) => k + 1)}>↻ Retry</button></div></div>;
  if (!doc) return <div className="page"><PageTitle title="Results" sub="Loading…" /></div>;
  const notDone = doc.status !== "completed";
  const firstChoice = r?.questions.find((x) => x.type === "single" || x.type === "multi");
  const topOf = (d: Record<string, number>) => Object.entries(d).sort((a, b) => b[1] - a[1])[0];
  const top = firstChoice ? topOf(firstChoice.distribution) : undefined;
  const topBefore = firstChoice && top ? firstChoice.pre_distribution[top[0]] ?? null : null;
  const rerun = async () => { setBusy(true); try { const x = await rerunSurvey(doc.survey_id); await launchSurvey(x.survey_id); nav(withMode(`/insights/focus/${x.survey_id}/wait`)); } catch (e) { setErr(String(e)); } setBusy(false); };
  return (
    <div className="page" data-testid="focus-results">
      <PageTitle title={doc.title} sub={`${doc.mode === "focus_group" ? "Focus group" : "Survey"} · ${r?.n_attended ?? 0} people · ${doc.start_label?.split(" · ")[0] ?? ""} · Research Lounge${(doc.wave ?? 1) > 1 ? ` · wave ${doc.wave}` : ""}`}
        right={<><button className="btn" onClick={() => nav(withMode("/insights/focus"))}>← Polls</button>
          <button className="btn" onClick={() => nav(withMode(`/insights/focus/${surveyId}/room`))}>▶ Replay the room</button>
          <button className="btn primary" disabled={busy || notDone} onClick={() => void rerun()}>↻ Run again (wave {(doc.wave ?? 1) + 1})</button></>} />
      {notDone && <div className="card" style={{ marginBottom: 14 }}><b className="small">This session is {doc.status.replace("_", " ")}.</b> <span className="xs muted">Results fill in when everyone has answered.</span></div>}
      {err && <div className="xs" style={{ color: "var(--red)", marginBottom: 8 }}>{err}</div>}
      <div className="grid" style={{ gridTemplateColumns: "1fr 340px", alignItems: "start" }}>
        <div>
          {!r ? <div className="card xs muted">{(doc as { results_error?: string }).results_error ?? "No answers logged yet."}</div> : <>
            <div className="grid g4">
              <div className="card kpi"><div className="l">Took part</div><div className="v">{r.n_attended}</div><div className="d muted">of {doc.counts?.accepted ?? "—"} who said yes</div></div>
              <div className="card kpi"><div className="l">Changed their mind</div><div className="v">{r.n_attended ? Math.round((100 * (r.changed_people ?? 0)) / r.n_attended) : 0}%</div><div className="d muted">{r.changed_people ?? 0} people, on at least one question</div></div>
              <div className="card kpi"><div className="l">Top answer · Q{firstChoice ? r.questions.indexOf(firstChoice) + 1 : 1}</div><div className="v" style={{ fontSize: 18 }}>{top ? top[0].slice(0, 22) : "—"}</div><div className="d muted">{top ? `${top[1]} of ${firstChoice?.n}${topBefore != null ? ` · ${top[1] >= topBefore ? "up" : "down"} from ${topBefore}` : ""}` : "no choice question"}</div></div>
              <div className="card kpi"><div className="l">Said ≠ thought</div><div className="v">{r.gap_people ?? 0} people</div><div className="d muted">said one thing, answered another</div></div>
            </div>
            {r.findings && r.findings.length > 0 && <div className="grid g3" style={{ marginTop: 14 }} data-testid="findings">
              {r.findings.map((f, i) => <div key={i} className="verdict" style={{ borderColor: [undefined, "var(--amber)", "var(--private)"][i] }}><h4>{f.title}</h4><div className="small muted">{f.line}</div></div>)}</div>}
            <div className="card" style={{ marginTop: 14 }}>
              <div className="qtabs">{r.questions.map((x, i) => <button key={x.question_id} className={i === qi ? "on" : ""} onClick={() => setQi(i)}>Q{i + 1} · {x.type === "scale" ? "scale" : x.type === "open" ? "open" : "choice"}</button>)}</div>
              {q && <><h3 style={{ marginTop: 0 }}>Q{qi + 1}. {q.text}</h3>
                {(q.type === "single" || q.type === "multi") && <>
                  <div className="grid g2" style={{ alignItems: "start" }}>
                    <div><div className="xs muted" style={{ marginBottom: 6 }}>How answers moved during the discussion</div><Sankey q={q} /></div>
                    <div><div className="xs muted" style={{ marginBottom: 6 }}>Who moved whom (from the private ballots' “influenced by”)</div><Network edges={edges} seats={r.seats ?? {}} names={names} /></div>
                  </div>
                  <div className="grid g2" style={{ marginTop: 14, alignItems: "start" }}>
                    <div><h3>Why people changed (or didn't)</h3>
                      <div style={{ display: "flex", height: 26, borderRadius: 7, overflow: "hidden" }} data-testid="influence-bar">{q.influence.filter(([, k]) => k > 0).map(([l, k, key]) => <div key={key} title={l} style={{ width: `${(100 * k) / Math.max(1, q.n)}%`, background: INFL_COL[key], display: "grid", placeItems: "center", color: "#05201c", fontSize: 11, fontWeight: 700 }}>{k}</div>)}</div>
                      <div className="legend-sm" style={{ marginTop: 8 }}>{q.influence.map(([l, k, key]) => <span key={key}><i style={{ background: INFL_COL[key] }} />{l} · {k}</span>)}</div></div>
                    <div><h3>Answer by age</h3><AgeHeat q={q} /></div>
                  </div></>}
                {q.type === "scale" && <div className="grid g2" style={{ alignItems: "start" }}>
                  <div><div className="xs muted" style={{ marginBottom: 6 }}>Each dot is one person · line = average</div><DotStrip q={q} /></div>
                  <div><h3>What moved the score</h3>{q.quotes.slice(0, 3).map((x, i) => <div key={i} className="quote" style={{ borderColor: x.changed ? "var(--teal)" : "var(--amber)" }}>“{x.text}” <span className="xs muted">· {names[x.agent_id]?.name ?? x.name ?? `#${x.agent_id}`}{x.changed && x.prestance != null ? ` · moved ${fmt(x.prestance)} → ${fmt(x.answer)}` : ` · ${fmt(x.answer)}`}</span></div>)}</div>
                </div>}
                {q.type === "open" && <div className="grid g2" style={{ alignItems: "start" }}>
                  <div><div className="xs muted" style={{ marginBottom: 6 }}>Themes in the open answers (sizes = people)</div>{q.themes?.length ? <Bubbles themes={q.themes} /> : <div className="xs muted">No open answers yet.</div>}</div>
                  <div><h3>In their words</h3>{(q.themes ?? []).map((t, i) => <div key={t.theme} className="quote" style={{ borderColor: COL[i % COL.length] }}>“{t.quote}” <span className="xs muted">· {t.theme}</span></div>)}</div>
                </div>}
              </>}
            </div>
            <div className="grid g2" style={{ marginTop: 14 }}>
              <div className="card" data-testid="said-vs-answered"><h3>Said out loud vs answered privately</h3><div className="gapmeter" />
                <div className="row between xs muted" style={{ marginTop: 4 }}><span>matched</span><span>{r.gap_people ?? 0} of {r.n_attended} differ</span></div>
                {(r.gap_pairs ?? []).slice(0, 3).map((g, i) => <div key={i} className="item small" style={{ marginTop: 10 }}><b>{names[g.agent_id]?.name.split(" ")[0] ?? g.name ?? `#${g.agent_id}`}</b> said <i>“{g.said}”</i>
                  <div className="privcard" style={{ marginTop: 6 }}><div className="h">PRIVATE BALLOT</div>{fmt(g.answered)}{g.reason ? ` — “${g.reason}”` : ""}</div></div>)}
                {!(r.gap_pairs ?? []).length && <div className="xs muted" style={{ marginTop: 8 }}>Everyone's ballot matched what they said at the table.</div>}</div>
              <div className="card"><h3>Moderator summary</h3>{Object.entries(r.summaries).map(([tid, s]) => <div key={tid} className="small" style={{ marginBottom: 8 }}><b className="xs muted">{tid.replace("T", "Table ")}</b><div>{s}</div></div>)}
                {!Object.keys(r.summaries).length && <div className="xs muted">No summary yet.</div>}
                {r.notes.map((x) => <div key={x} className="xs" style={{ color: "var(--amber)" }}>{x}</div>)}
                <div className="note">After the session, each person keeps their own memory of it. Run the same group again next week to see what stuck.</div></div>
            </div>
          </>}
        </div>
        <SessionsCol cur={surveyId} />
      </div>
    </div>
  );
}
