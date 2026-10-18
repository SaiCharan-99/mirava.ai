import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../../components/Shell";
import { HBars, HeatTable } from "../../components/charts";
import { isVisualTest, withMode } from "../../lib/visualTest";
import { useWorld } from "../../state/world";
import { worldRef } from "../../world/ref";
import {
  explainWaves, getAgentDetail, getSurvey, getTranscript, mergeItems, paceMs, phaseIndex, rerunSurvey, launchSurvey, roomState,
  subscribeSurvey, type Item, type QResult, type SurveyAgent, type SurveyDoc, type TableDef,
} from "../../lib/survey";
import { Room2D } from "./Room2D";
import { hasWebGL, reducedMotion } from "./roomLayout";

const Room3D = lazy(() => import("./Room3D").then((m) => ({ default: m.Room3D })));
const PALETTE = ["#eab308", "#14b8a6", "#3b82f6", "#f97316", "#0ea5e9", "#ec4899", "#22c55e", "#a78bfa", "#f43f5e", "#84cc16", "#06b6d4", "#f59e0b"];
const TAGS: Record<string, string> = { persuaded: "teal", conformed: "amber", reinforced: "green", reacted_against: "red", unchanged: "" };

interface Fixture { survey: SurveyDoc; tables: TableDef[]; agents: SurveyAgent[]; rsvp: { agent_id: number; rsvp: string; reason: string; arrived: boolean }[]; items: Item[]; answers: Record<string, any>[] }

/** Visual-test freeze requests from `window.__ll.surveyRoom`. */
export const surveyFreeze: { set: ((phase: string, progress: number) => void) | null; pending: [string, number] | null } = { set: null, pending: null };

function resultsFromAnswers(doc: SurveyDoc, answers: Record<string, any>[], agents: Record<number, SurveyAgent>): QResult[] {
  return doc.questions.map((q) => {
    const rows = answers.filter((a) => a.question_id === q.question_id);
    const dist: Record<string, number> = {}, shift: Record<string, Record<string, number>> = {}, seg: Record<string, Record<string, number>> = {};
    for (const a of rows) {
      const v = q.type === "open" ? "answered" : Array.isArray(a.answer) ? a.answer.join("|") : String(a.answer);
      dist[v] = (dist[v] ?? 0) + 1;
      const band = agents[a.agent_id]?.income_band ?? "?";
      (seg[band] ??= {})[v] = (seg[band]?.[v] ?? 0) + 1;
    }
    return { question_id: q.question_id, text: q.text, type: q.type, options: q.options, distribution: dist, shift, by_segment: seg,
      quotes: rows.filter((a) => a.reason).sort((a, b) => Number(b.changed_from_prestance) - Number(a.changed_from_prestance)).slice(0, 6)
        .map((a) => ({ agent_id: a.agent_id, name: agents[a.agent_id]?.name, text: a.reason, tag: a.influence_type, private: false, answer: a.answer, changed: a.changed_from_prestance })),
      changed: rows.filter((a) => a.changed_from_prestance).length, n: rows.length };
  });
}

function shiftFromItems(items: Item[], qid: string): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const it of items) {
    if (it.kind !== "survey_answer" || it.payload.question_id !== qid || it.payload.prestance == null) continue;
    const a = String(it.payload.prestance), b = String(it.payload.answer);
    (out[a] ??= {})[b] = (out[a]?.[b] ?? 0) + 1;
  }
  return out;
}

function Results({ doc, results, items, tab }: { doc: SurveyDoc; results: QResult[]; items: Item[]; tab: string }) {
  const cols = ["#22c55e", "#f5b041", "#60a5fa", "#8b5cf6", "#f97316", "#ec4899", "#2dd4bf", "#94a3b8"];
  if (tab === "waves") return <WavesPanel doc={doc} />;
  return (
    <div className="list" style={{ gap: 12 }}>
      {results.map((q, qi) => {
        const tot = Object.values(q.distribution).reduce((a, b) => a + b, 0) || 1;
        const bars = Object.entries(q.distribution).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v], i): [string, number, string] => [k.length > 28 ? k.slice(0, 27) + "…" : k, Math.round((100 * v) / tot), cols[i % 8]]);
        const shift = Object.keys(q.shift).length ? q.shift : shiftFromItems(items, q.question_id);
        const keys = Array.from(new Set([...Object.keys(shift), ...Object.values(shift).flatMap((r) => Object.keys(r))])).slice(0, 6);
        return (
          <div key={q.question_id} className="item">
            <div className="row between"><b className="small">Q{qi + 1}. {q.text}</b><span className="xs muted">n = {q.n}{q.changed ? ` · ${q.changed} changed` : ""}</span></div>
            {q.type !== "open" && <div style={{ marginTop: 6 }}><HBars rows={bars} max={Math.max(10, ...bars.map((b) => b[1]))} /></div>}
            {q.type !== "open" && keys.length > 1 && doc.mode === "focus_group" && (
              <div style={{ marginTop: 8 }}><div className="xs muted" style={{ marginBottom: 4 }}>Prestance → final (private)</div>
                <HeatTable rows={keys.map((k) => k.slice(0, 14))} cols={keys.map((k) => k.slice(0, 10))} vals={keys.map((a) => keys.map((b) => shift[a]?.[b] ?? 0))} unit="" max={Math.max(1, ...keys.flatMap((a) => keys.map((b) => shift[a]?.[b] ?? 0)))} /></div>
            )}
            <div className="list small" style={{ marginTop: 6, gap: 4 }}>{q.quotes.slice(0, 3).map((x, i) => (
              <div key={i} className="quote" style={{ margin: 0 }}>“{x.text}” <span className="xs muted">— {x.name ?? `#${x.agent_id}`}</span> {x.tag && x.tag !== "unchanged" && <span className={`chip ${TAGS[x.tag] ?? ""}`} style={{ padding: "0 6px", fontSize: 10 }}>{x.tag.replace("_", " ")}</span>}</div>
            ))}</div>
          </div>
        );
      })}
      {Object.entries(doc.summaries ?? {}).map(([tid, s]) => <div key={tid} className="item small"><b>Moderator summary · {tid}</b><div className="xs" style={{ marginTop: 4 }}>{s}</div></div>)}
      <div className="xs muted">Participation effect: taking part becomes part of each agent's memory and may shift later answers.{doc.discussion_skipped ? " Budget ran out: some discussion turns were skipped; all ballots completed." : ""}</div>
    </div>
  );
}

function WavesPanel({ doc }: { doc: SurveyDoc }) {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const w = doc.waves;
  return (
    <div className="list small" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 6 }}>
        <button className="btn primary" disabled={busy || isVisualTest || doc.status !== "completed"} onClick={async () => { setBusy(true); const r = await rerunSurvey(doc.survey_id); await launchSurvey(r.survey_id).catch(() => undefined); nav(withMode(`/insights/polls/survey/${r.survey_id}`)); }}>Run again (wave {(doc.wave ?? 1) + 1})</button>
        <button className="btn" disabled={busy || isVisualTest || !w?.changes.length} onClick={async () => { setBusy(true); await explainWaves(doc.survey_id); setBusy(false); }}>Explain changes</button>
      </div>
      {!w && <div className="xs muted">Save as panel and run again after at least one sim day to compare waves.</div>}
      {w && Object.entries(w.distribution).map(([qid, byWave]) => (
        <div key={qid} className="item"><b>{qid}</b>{Object.entries(byWave).map(([wave, d]) => (
          <div key={wave} className="xs">Wave {wave}: {Object.entries(d).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => `${k.slice(0, 18)} ${v}`).join(" · ")}</div>
        ))}</div>
      ))}
      {w?.changes.slice(0, 12).map((c, i) => (
        <div key={i} className="item xs"><b>#{c.agent_id}</b> {c.question_id}: {String(c.from).slice(0, 20)} → {String(c.to).slice(0, 20)}
          <div className="muted">{c.why?.why ?? "why: not explained yet"}{c.why?.event_ids?.length ? ` (${c.why.event_ids.join(", ")})` : ""}</div></div>
      ))}
    </div>
  );
}

function AgentCard({ sid, aid, agent, items, onClose }: { sid: string; aid: number; agent?: SurveyAgent; items: Item[]; onClose: () => void }) {
  const open = useWorld((s) => s.openProfile);
  const nav = useNavigate();
  const [detail, setDetail] = useState<{ kind: string; payload: Record<string, any> }[]>([]);
  useEffect(() => {
    if (isVisualTest) { setDetail(items.filter((it) => it.agent_id === aid && it.kind.startsWith("survey_")).map((it) => ({ kind: it.kind, payload: it.payload }))); return; }
    void getAgentDetail(sid, aid).then((d) => setDetail(d.items)).catch(() => setDetail([]));
  }, [sid, aid, items]);
  const pre = detail.filter((d) => d.kind === "survey_prestance");
  const ans = detail.filter((d) => d.kind === "survey_answer");
  const heard = detail.filter((d) => d.kind === "survey_heard").slice(-1)[0];
  return (
    <div className="card" data-testid="survey-agent-card" style={{ padding: 12 }}>
      <div className="row between"><b>{agent?.name ?? `#${aid}`}{agent?.age ? `, ${agent.age}` : ""}</b><button className="btn" style={{ padding: "2px 8px" }} onClick={onClose}>×</button></div>
      <div className="xs muted">{agent?.phone ? `Phone: ${agent.phone}` : ""}{agent?.experience ? ` · ${agent.experience.replace("_", " ")}` : ""}</div>
      <div className="list xs" style={{ gap: 4, marginTop: 8 }}>
        {ans.map((a, i) => (
          <div key={i}><b>{a.payload.question_id}</b>: <span style={{ color: "var(--private)" }}>{pre[i] ? String(pre[i].payload.answer).slice(0, 24) : "—"}</span> → <b>{String(a.payload.answer).slice(0, 30)}</b>
            {a.payload.influence_type && a.payload.influence_type !== "unchanged" && <span className={`chip ${TAGS[a.payload.influence_type] ?? ""}`} style={{ marginLeft: 4, padding: "0 5px", fontSize: 9 }}>{a.payload.influence_type}</span>}</div>
        ))}
        {heard && <div style={{ marginTop: 4 }}><span className="privtag">PRIVATE</span> heard: {heard.payload.gist}</div>}
      </div>
      <button className="btn" style={{ marginTop: 8 }} disabled={isVisualTest} onClick={() => { nav(withMode("/world")); setTimeout(() => open(aid, "conversations"), 80); }}>Open profile</button>
    </div>
  );
}

export function SurveyRoomPage() {
  const { surveyId = "" } = useParams();
  const nav = useNavigate();
  const [doc, setDoc] = useState<SurveyDoc | null>(null);
  const [fx, setFx] = useState<Fixture | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [tables, setTables] = useState<TableDef[]>([]);
  const [agents, setAgents] = useState<Record<number, SurveyAgent>>({});
  const [cursor, setCursor] = useState(0);
  const [mode, setMode] = useState<"live" | "replay">("live");
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(!isVisualTest);
  const [frozenPhase, setFrozenPhase] = useState<string | null>(null);
  const [selTable, setSelTable] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [showPrivate, setShowPrivate] = useState(false);
  const [side, setSide] = useState<"transcript" | "results" | "waves">("transcript");
  const [use3d] = useState(() => hasWebGL());
  const liveItems = useRef<Item[]>([]);

  // fixture (visual-test) or API
  useEffect(() => {
    if (isVisualTest) {
      void import("../../visual-fixtures/survey-fixture.json").then((m) => {
        const f = (m.default ?? m) as unknown as Fixture;
        setFx(f); setDoc(f.survey); setTables(f.tables); setItems(mergeItems(f.items));
        setAgents(Object.fromEntries(f.agents.map((a) => [a.agent_id, a])));
        setCursor(mergeItems(f.items).length);
      });
      return;
    }
    let stop = false;
    const load = async () => {
      const d = await getSurvey(surveyId).catch(() => null);
      if (!d || stop) return;
      setDoc(d);
      const tbs = (d.tables ?? []).map((t) => ({ table_id: t.table_id, seats: (t as any).present ?? t.seats }));
      setTables(tbs);
      const tr = await getTranscript(surveyId).catch(() => []);
      const t0 = tr.length ? Math.min(...tr.map((x) => x.t)) : 0;
      const msgs: Item[] = tr.map((x) => ({ dt: x.t - t0 + x.seq * 0.001, kind: "message", agent_id: x.speaker_id, table_id: x.table_id,
        payload: { message_id: x.message_id, speaker: x.speaker === "moderator" ? "moderator" : Number(x.speaker), text: x.text, question_id: x.question_id, table_id: x.table_id } }));
      const all = mergeItems([...msgs, ...liveItems.current.filter((it) => it.kind !== "message")]);
      setItems(all);
      if (mode === "live") setCursor(all.length);
      if (!Object.keys(agents).length) {
        const ids = Array.from(new Set([...(d.participants ?? []).map((p) => p.agent_id)]));
        const names = await Promise.all(ids.slice(0, 120).map((id) => fetch(`/api/agents/${id}`).then((r) => r.json()).catch(() => null)));
        setAgents(Object.fromEntries(ids.map((id, i) => [id, { agent_id: id, name: names[i]?.profile?.name ?? `#${id}`, age: names[i]?.profile?.age,
          color: PALETTE[id % PALETTE.length], phone: names[i] ? `${names[i].profile.possessions.phone.brand} · ${names[i].profile.possessions.phone.age_years} yrs` : undefined, income_band: names[i]?.profile?.income_band }])));
      }
      if (d.status !== "completed" && d.status !== "cancelled" && !stop) setTimeout(load, 3000);
    };
    void load();
    const un = subscribeSurvey(surveyId, (f) => {
      if (f.type === "survey_ballot") liveItems.current.push({ dt: Number(f.t ?? 0), kind: "survey_answer", agent_id: f.agent_id, payload: { question_id: f.question_id, reason: f.note, written: !!f.note } });
      if (f.type === "survey") liveItems.current.push({ dt: Number(f.t ?? 0), kind: "survey_phase", agent_id: null, payload: { phase: f.phase, question_id: f.question_id } });
      if (f.type === "survey_msg") liveItems.current.push({ dt: Number(f.t ?? 0), kind: "message", agent_id: typeof f.speaker === "number" ? f.speaker : null, table_id: f.table_id, payload: { message_id: f.message_id, speaker: f.speaker, text: f.text, table_id: f.table_id } });
      setItems((cur) => mergeItems([...cur.filter((it) => it.kind !== "survey_phase" && it.kind !== "survey_answer"), ...liveItems.current.filter((it) => it.kind !== "message"), ...(f.type === "survey_msg" ? [liveItems.current[liveItems.current.length - 1]] : [])]));
    });
    return () => { stop = true; un(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surveyId]);

  // replay pacing at reading speed
  useEffect(() => {
    if (!playing || mode !== "replay" || cursor >= items.length || reducedMotion()) return;
    const h = setTimeout(() => setCursor((c) => c + 1), paceMs(items[cursor]) / speed);
    return () => clearTimeout(h);
  }, [playing, mode, cursor, items, speed]);
  useEffect(() => { if (mode === "live") setCursor(items.length); }, [items.length, mode]);

  // visual-test hook
  const freeze = useCallback((phase: string, progress: number) => {
    setPlaying(false); setMode("replay"); setFrozenPhase(phase);
    setCursor(phaseIndex(items, phase, progress));
    if (phase === "results") setSide("results");
    if (phase === "discussion") { setSel(tables[0]?.seats[2] ?? null); setShowPrivate(true); }
  }, [items, tables]);
  useEffect(() => {
    surveyFreeze.set = freeze;
    if (surveyFreeze.pending && items.length) { const [p, g] = surveyFreeze.pending; surveyFreeze.pending = null; freeze(p, g); }
    return () => { surveyFreeze.set = null; };
  }, [freeze, items.length]);

  const st = useMemo(() => roomState(items, cursor, tables), [items, cursor, tables]);
  const results = useMemo<QResult[]>(() => {
    if (!doc) return [];
    if (doc.results?.questions?.length) return doc.results.questions;
    if (fx) return resultsFromAnswers(doc, fx.answers, agents);
    return [];
  }, [doc, fx, agents]);
  const privateText = useMemo(() => {
    if (!showPrivate || sel == null) return null;
    const th = items.slice(0, cursor).filter((it) => it.kind === "survey_thought" && it.agent_id === sel).slice(-1)[0];
    const pre = items.slice(0, cursor).filter((it) => it.kind === "survey_prestance" && it.agent_id === sel).slice(-1)[0];
    return th ? String(th.payload.text) : pre ? `My first answer: ${String(pre.payload.answer)}. ${pre.payload.gut_reason}` : null;
  }, [showPrivate, sel, items, cursor]);

  if (!doc) return <div className="page"><PageTitle title="Survey Room" sub="Loading…" /></div>;
  const recruiting = frozenPhase === "recruiting" || (!isVisualTest && ["recruiting", "gathering", "draft"].includes(doc.status));
  const curTable = selTable ?? tables[0]?.table_id ?? "";
  const transcript = st.transcript[curTable] ?? [];
  const parts = isVisualTest && fx ? fx.rsvp.map((r) => ({ agent_id: r.agent_id, rsvp: r.rsvp, rsvp_reason: r.reason, arrived_t: r.arrived ? 1 : null })) : doc.participants ?? [];
  const arrived = parts.filter((p) => p.arrived_t).length, expected = parts.filter((p) => p.rsvp === "accepted" || p.rsvp === "attended").length;
  const qtext = doc.questions[Math.max(0, st.qIndex)]?.text ?? "";
  return (
    <div className="page" data-testid="survey-room">
      <PageTitle title={doc.title} sub={`${doc.mode === "focus_group" ? "Focus group" : "Survey"} · ${doc.venue_name ?? "Research Lounge"} · wave ${doc.wave ?? 1} · ${doc.start_label ?? ""}`}
        right={<><button className="btn" onClick={() => nav(withMode("/insights/polls"))}>← Polls</button><span className="chip">{recruiting ? doc.status : st.phase}</span><span className="sim-badge">SIMULATED</span></>} />
      {recruiting ? (
        <div className="grid g21">
          <div className="card"><div className="row between"><h3 style={{ margin: 0 }}>Invitations and RSVPs</h3><span className="xs muted">reasons are each agent's <span className="privtag">PRIVATE</span> thought</span></div>
            <div className="list small" style={{ marginTop: 10, maxHeight: 560, overflow: "auto" }}>{parts.slice(0, 80).map((p) => (
              <div key={p.agent_id} className="item row between"><span><b>{agents[p.agent_id]?.name ?? `#${p.agent_id}`}</b> <span className="xs muted">· {p.rsvp}</span>{p.rsvp_reason ? <div className="xs" style={{ color: "var(--private)" }}>private: {p.rsvp_reason}</div> : null}</span><span className="xs">{p.arrived_t ? "✓ arrived" : p.rsvp === "accepted" ? "on the way 📋" : ""}</span></div>
            ))}{!parts.length && <div className="xs muted">Invitations sent — waiting for RSVPs…</div>}</div></div>
          <div className="grid" style={{ alignContent: "start" }}>
            <div className="card"><h3>Arrivals</h3><div style={{ fontSize: 34, fontWeight: 700 }}>{arrived}<span className="muted" style={{ fontSize: 18 }}> / {expected}</span></div>
              <div className="xs muted">The session starts when 90% have arrived or 20 sim min after the start time.</div>
              <button className="btn primary" style={{ marginTop: 10 }} onClick={() => { nav(withMode("/world")); const pin = useWorld.getState().surveyPin; setTimeout(() => pin && worldRef.scene?.focusM(pin.x, pin.y, 3), 400); }}>Watch them arrive</button></div>
            <div className="card small"><b>Eligible</b> {doc.eligible ?? "—"} · <b>expected</b> {doc.expected_attendance ?? "—"} · <b>estimate</b> ${Number(doc.estimate_usd ?? 0).toFixed(2)}</div>
          </div>
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "1fr 360px", gap: 14 }}>
          <div>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div className="row between" style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)" }}>
                <div className="small"><b>{st.qIndex >= 0 ? `Q${st.qIndex + 1}` : "Welcome"}</b> {qtext}</div>
                <div className="row" style={{ gap: 6 }} data-testid="survey-tables">
                  {tables.map((t) => <button key={t.table_id} className={`chip ${curTable === t.table_id ? "teal" : ""}`} onClick={() => setSelTable(t.table_id)}>{t.table_id} · {t.seats.length}</button>)}
                  <label className="xs row" style={{ gap: 4 }}><input type="checkbox" checked={showPrivate} onChange={(e) => setShowPrivate(e.target.checked)} /> private thoughts</label>
                </div>
              </div>
              <div data-testid="survey-canvas" style={{ height: 520, position: "relative", background: "#17120d" }}>
                {use3d ? <Suspense fallback={<Room2D tables={tables} agents={agents} st={st} selected={sel} onSelect={setSel} privateText={privateText} mode={doc.mode} />}>
                  <Room3D tables={tables} agents={agents} st={st} selected={sel} onSelect={setSel} focusTable={selTable} onFocusTable={setSelTable} privateText={privateText} mode={doc.mode} frozen={isVisualTest} />
                </Suspense> : <Room2D tables={tables} agents={agents} st={st} selected={sel} onSelect={setSel} privateText={privateText} mode={doc.mode} />}
                {sel != null && <div style={{ position: "absolute", left: 12, bottom: 12, width: 300 }}><AgentCard sid={doc.survey_id} aid={sel} agent={agents[sel]} items={items.slice(0, cursor)} onClose={() => setSel(null)} /></div>}
              </div>
              <div className="row" data-testid="survey-playback" style={{ padding: "8px 14px", gap: 10, borderTop: "1px solid var(--line)" }}>
                <div className="seg"><button className={mode === "live" ? "on" : ""} onClick={() => setMode("live")}>Live</button><button className={mode === "replay" ? "on" : ""} onClick={() => { setMode("replay"); setCursor(0); setPlaying(true); }}>Replay</button></div>
                <button className="btn" onClick={() => setPlaying((p) => !p)} disabled={mode === "live"}>{playing ? "❚❚" : "▶"}</button>
                <div className="seg">{[1, 2, 4].map((s) => <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>)}</div>
                <input type="range" min={0} max={items.length} value={cursor} onChange={(e) => { setMode("replay"); setPlaying(false); setCursor(Number(e.target.value)); }} style={{ flex: 1 }} aria-label="Scrub" />
                <span className="xs muted mono">{cursor}/{items.length}</span>
              </div>
            </div>
          </div>
          <div className="card" style={{ padding: 12 }}>
            <div className="seg" style={{ marginBottom: 10 }}>{(["transcript", "results", "waves"] as const).map((k) => <button key={k} className={side === k ? "on" : ""} onClick={() => setSide(k)}>{k[0].toUpperCase() + k.slice(1)}</button>)}</div>
            {side === "transcript" ? (
              <div data-testid="survey-transcript" className="list small" style={{ gap: 6, maxHeight: 610, overflow: "auto" }}>
                {transcript.map((it) => (
                  <div key={it.payload.message_id} className="item" style={{ padding: "6px 9px" }}>
                    <b className="xs">{it.payload.speaker === "moderator" ? "Moderator" : agents[it.payload.speaker]?.name ?? `#${it.payload.speaker}`}</b>
                    <div className="xs">{it.payload.text}</div></div>
                ))}{!transcript.length && <div className="xs muted">No messages yet at {curTable}.</div>}
              </div>
            ) : (
              <div data-testid="survey-results" style={{ maxHeight: 610, overflow: "auto" }}><Results doc={doc} results={results} items={items} tab={side} /></div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
