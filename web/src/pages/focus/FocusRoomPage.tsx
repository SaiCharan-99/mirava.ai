import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../../components/Shell";
import { getJSON } from "../../lib/api";
import { arrivalTables, getLiveState, itemsFromLive, mmss, secondsToStart, type LiveMsg, type LiveState } from "../../lib/focus";
import { isVisualTest, withMode } from "../../lib/visualTest";
import {
  getSurvey, getTranscript, mergeItems, paceMs, phaseIndex, roomState, subscribeSurvey,
  type Item, type RoomState, type SurveyAgent, type SurveyDoc, type TableDef,
} from "../../lib/survey";
import { useActiveSurvey } from "../../state/activeSurvey";
import { Room2D } from "../survey/Room2D";
import { hasWebGL, reducedMotion } from "../survey/roomLayout";
import { SessionsCol } from "./SessionsCol";

const Room3D = lazy(() => import("../survey/Room3D").then((m) => ({ default: m.Room3D })));
const PALETTE = ["#eab308", "#14b8a6", "#3b82f6", "#f97316", "#0ea5e9", "#ec4899", "#22c55e", "#a78bfa", "#f43f5e", "#84cc16", "#06b6d4", "#f59e0b"];
const STEPS: [RoomState["phase"][], string][] = [[["gathering"], "Gathering"], [["question", "discussion"], "Discussion"], [["ballot"], "Private ballot"], [["results"], "Results"]];
const LIVE = ["recruiting", "gathering", "in_session", "finishing"];

interface Fixture { survey: SurveyDoc; tables: TableDef[]; agents: SurveyAgent[]; items: Item[] }
interface TItem { kind: "msg" | "private"; t: number; speaker: number | "moderator"; text: string; id: string }

/** Visual-test freeze requests from `window.__ll.surveyRoom`. */
export const surveyFreeze: { set: ((phase: string, progress: number) => void) | null; pending: [string, number] | null } = { set: null, pending: null };

export function FocusRoomPage() {
  const { surveyId = "" } = useParams();
  const nav = useNavigate();
  const setInRoom = useActiveSurvey((s) => s.setInRoom);
  const [doc, setDoc] = useState<SurveyDoc | null>(null);
  const [err, setErr] = useState("");
  const [live, setLive] = useState<LiveState | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [tables, setTables] = useState<TableDef[]>([]);
  const [agents, setAgents] = useState<Record<number, SurveyAgent>>({});
  const [trans, setTrans] = useState<Record<string, TItem[]>>({});
  const [cursor, setCursor] = useState(0);
  const [mode, setMode] = useState<"live" | "replay">("live");
  const [playing, setPlaying] = useState(!isVisualTest);
  const [speed, setSpeed] = useState(1);
  const [frozenPhase, setFrozenPhase] = useState<string | null>(null);
  const [selTable, setSelTable] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [showPrivate, setShowPrivate] = useState(true);
  const [use3d, setUse3dRaw] = useState(() => {
    if (isVisualTest || !hasWebGL()) return false;
    try { return localStorage.getItem("ll.room3d") !== "0"; } catch { return true; }
  });
  const setUse3d = (f: (v: boolean) => boolean) => setUse3dRaw((v) => { const n = f(v); try { localStorage.setItem("ll.room3d", n ? "1" : "0"); } catch { /* private mode */ } return n; });
  const [, tick] = useState(0);
  const qids = useRef<string[]>([]);
  const selRef = useRef<string | null>(null);
  selRef.current = selTable;

  useEffect(() => { setInRoom(surveyId); return () => setInRoom(null); }, [surveyId, setInRoom]);
  useEffect(() => { const h = setInterval(() => tick((n) => n + 1), 500); return () => clearInterval(h); }, []);

  // names and colours for everyone (one request)
  useEffect(() => {
    if (isVisualTest) return;
    void getJSON<{ rows: { agent_id: number; name: string; age: number; phone: { brand: string; age_years: number | null }; income_band: string }[] }>("/agents?page_size=1000")
      .then((r) => setAgents(Object.fromEntries(r.rows.map((a) => [a.agent_id, { agent_id: a.agent_id, name: a.name, age: a.age, color: PALETTE[a.agent_id % PALETTE.length],
        phone: a.phone ? `${a.phone.brand} · ${a.phone.age_years ?? "?"} yrs` : undefined, income_band: a.income_band }]))))
      .catch(() => undefined);
  }, []);

  const applyLive = useCallback((st: LiveState) => {
    setLive(st);
    const tbs = st.tables.length ? st.tables : arrivalTables(st.arrived_ids);
    setTables(tbs);
    setItems(itemsFromLive(st, qids.current));
    const tr: Record<string, TItem[]> = {};
    for (const [tid, msgs] of Object.entries(st.messages)) tr[tid] = msgs.map((m) => ({ kind: "msg" as const, t: m.t + m.seq * 0.001, speaker: m.speaker, text: m.text, id: m.message_id }));
    const ptid = selRef.current ?? tbs[0]?.table_id;
    if (ptid) tr[ptid] = [...(tr[ptid] ?? []), ...st.private.map((p, i) => ({ kind: "private" as const, t: p.t + 0.0005, speaker: p.agent_id, text: p.text, id: `p${i}-${p.agent_id}-${p.t}` }))].sort((a, b) => a.t - b.t);
    setTrans(tr);
  }, []);

  // fixture (visual test) · live (engine memory + frames) · completed (replay from the logged transcript)
  useEffect(() => {
    if (isVisualTest) {
      void import("../../visual-fixtures/survey-fixture.json").then((m) => {
        const f = (m.default ?? m) as unknown as Fixture;
        setDoc(f.survey); setTables(f.tables); const it = mergeItems(f.items); setItems(it); setCursor(it.length); setMode("replay");
        setAgents(Object.fromEntries(f.agents.map((a) => [a.agent_id, a])));
      });
      return;
    }
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loadDoc = async () => {
      const d = await getSurvey(surveyId).catch((e: unknown) => { setErr(e instanceof Error ? e.message : String(e)); return null; });
      if (!d || stop) return null;
      setDoc(d); setErr("");
      qids.current = d.questions.map((q) => q.question_id);
      return d;
    };
    const loadLive = async () => {
      try { const st = await getLiveState(surveyId, selRef.current ?? undefined); if (!stop) applyLive(st); return true; }
      catch { return false; }
    };
    const loop = async () => {
      if (stop) return;
      const ok = await loadLive();
      if (!ok) {                                           // not running in the engine any more: completed (or cancelled)
        const d = await loadDoc();
        if (d && !LIVE.includes(d.status)) { void loadReplay(d); return; }
      }
      timer = setTimeout(() => void loop(), 4000);
    };
    const loadReplay = async (d: SurveyDoc) => {
      const tr = await getTranscript(surveyId).catch(() => []);
      if (stop) return;
      const tbs = (d.tables ?? []).map((t) => ({ table_id: t.table_id, seats: (t as TableDef & { present?: number[] }).present ?? t.seats }));
      const t0 = tr.length ? Math.min(...tr.map((x) => x.t)) : 0;
      const qi: Record<string, boolean> = {};
      const it: Item[] = [];
      for (const x of tr) {
        if (!qi[x.question_id]) { qi[x.question_id] = true; it.push({ dt: x.t - t0 - 0.01, kind: "survey_phase", agent_id: null, payload: { phase: "question", question_id: x.question_id } }); }
        it.push({ dt: x.t - t0 + x.seq * 0.001, kind: "message", agent_id: x.speaker_id, table_id: x.table_id, payload: { message_id: x.message_id, speaker: x.speaker === "moderator" ? "moderator" : Number(x.speaker), text: x.text, question_id: x.question_id, table_id: x.table_id } });
      }
      const all = mergeItems(it);
      setTables(tbs); setItems(all); setCursor(all.length); setMode("replay"); setPlaying(false);
      const byT: Record<string, TItem[]> = {};
      for (const x of tr) (byT[x.table_id] ??= []).push({ kind: "msg", t: x.t + x.seq * 0.001, speaker: x.speaker === "moderator" ? "moderator" : Number(x.speaker), text: x.text, id: x.message_id });
      setTrans(byT);
    };
    void (async () => {
      const d = await loadDoc();
      if (!d) return;
      if (LIVE.includes(d.status)) void loop(); else void loadReplay(d);
    })();
    const un = subscribeSurvey(surveyId, (f) => {
      if (f.type === "survey_viewers") { setLive((l) => (l ? { ...l, viewers: Number(f.n) } : l)); useActiveSurvey.getState().setViewers(surveyId, Number(f.n)); return; }
      if (f.type === "survey_msg") {
        const m: LiveMsg = { message_id: String(f.message_id), speaker: f.speaker, text: String(f.text), seq: Number(f.seq ?? 0), question_id: "", t: Number(f.t ?? 0) };
        setItems((cur) => [...cur, { dt: 1e8 + cur.length, kind: "message", agent_id: typeof f.speaker === "number" ? f.speaker : null, table_id: f.table_id, payload: { ...m, table_id: f.table_id } }]);
        setTrans((cur) => ({ ...cur, [f.table_id]: [...(cur[f.table_id] ?? []).filter((x) => x.id !== m.message_id), { kind: "msg", t: m.t, speaker: m.speaker, text: m.text, id: m.message_id }] }));
      }
      if (f.type === "survey" && f.phase) {
        if (f.phase === "question") void loadLive();       // a new question: rebuild from the engine (fresh bubbles, ballots)
        else setItems((cur) => [...cur, { dt: 1e8 + cur.length, kind: "survey_phase", agent_id: null, payload: { phase: f.phase, question_id: f.question_id } }]);
        setLive((l) => (l ? { ...l, phase: f.phase } : l));
      }
      if (f.type === "survey_ballot") setItems((cur) => [...cur, { dt: 1e9 + cur.length, kind: "survey_answer", agent_id: f.agent_id, payload: { question_id: f.question_id, reason: f.note, written: !!f.note } }]);
    }, () => { void loadLive(); });                          // (re)connected: catch up from the engine
    return () => { stop = true; if (timer) clearTimeout(timer); un(); };
  }, [surveyId, applyLive]);

  // replay pacing at reading speed
  useEffect(() => {
    if (!playing || mode !== "replay" || cursor >= items.length || reducedMotion()) return;
    const h = setTimeout(() => setCursor((c) => c + 1), paceMs(items[cursor]) / speed);
    return () => clearTimeout(h);
  }, [playing, mode, cursor, items, speed]);

  // visual-test hook
  const freeze = useCallback((phase: string, progress: number) => {
    setPlaying(false); setMode("replay"); setFrozenPhase(phase);
    setCursor(phaseIndex(items, phase, progress));
    if (phase === "discussion") setSel(tables[0]?.seats[2] ?? null);
  }, [items, tables]);
  useEffect(() => {
    surveyFreeze.set = freeze;
    if (surveyFreeze.pending && items.length) { const [p, g] = surveyFreeze.pending; surveyFreeze.pending = null; freeze(p, g); }
    return () => { surveyFreeze.set = null; };
  }, [freeze, items.length]);

  const st = useMemo(() => {
    const upto = mode === "live" ? items.length : cursor;
    const s = roomState(items, upto, tables);
    if (mode === "live" && live) s.phase = live.phase as RoomState["phase"];
    if (mode === "live" && live && s.qIndex < 0) s.qIndex = live.q_index;
    return s;
  }, [items, cursor, tables, mode, live]);
  const privateText = useMemo(() => {
    if (!showPrivate || sel == null || !live) return null;
    const p = live.private.filter((x) => x.agent_id === sel).slice(-1)[0];
    return p ? p.text : null;
  }, [showPrivate, sel, live]);

  if (err && !doc) return <div className="page"><PageTitle title="Survey Room" sub="" /><div className="card"><b className="small">Couldn't open the room</b><div className="xs muted">{err}</div><button className="btn sm" style={{ marginTop: 8 }} onClick={() => location.reload()}>↻ Retry</button></div></div>;
  if (!doc) return <div className="page"><PageTitle title="Survey Room" sub="Loading…" /></div>;
  const status = live?.status ?? doc.status;
  const running = LIVE.includes(status) && mode === "live";
  const before = running && (status === "recruiting" || status === "gathering");
  const done = !running && (doc.status === "completed" || frozenPhase === "results");
  const curTable = selTable ?? tables[0]?.table_id ?? "";
  const shown = selTable ? tables.filter((t) => t.table_id === selTable) : tables;
  const nq = doc.questions.length;
  const qi = Math.max(0, st.qIndex);
  const counts = live?.counts;
  const attending = before ? counts?.arrived ?? 0 : tables.reduce((n, t) => n + t.seats.length, 0);
  const phaseOn = (i: number) => STEPS[i][0].includes(done ? "results" : st.phase);
  const curIdx = STEPS.findIndex((_, i) => phaseOn(i));
  const lines = (trans[curTable] ?? []).filter((x) => showPrivate || x.kind === "msg").slice(-60);
  const name = (sp: number | "moderator") => (sp === "moderator" ? "Moderator" : agents[sp]?.name.split(" ")[0] ?? `#${sp}`);
  return (
    <div className="page" data-testid="survey-room">
      <PageTitle title="Survey Room" sub={`${doc.mode === "focus_group" ? "Focus group" : "Survey"} · ${doc.title} · ${doc.venue_name ?? "Research Lounge"}`}
        right={<>
          {running ? <span className="chip green"><span className="dotlive" />live</span> : <span className="chip">{done ? "done" : status}</span>}
          <span className="chip">{attending} attending · {tables.filter((t) => t.seats.length).length} tables</span>
          {running && <span className="chip" data-testid="room-viewers">👁 {live?.viewers ?? 0} watching</span>}
          <button className="btn" data-testid="exit-room" onClick={() => (window.history.length > 1 ? nav(-1) : nav(withMode("/insights/focus")))}>Exit room</button>
        </>} />
      <div className="row" style={{ gap: 6, margin: "-4px 0 12px" }} data-testid="room-steps">
        {STEPS.map(([, l], i) => <span key={l} className={`chip ${i < curIdx ? "green" : i === curIdx ? "teal" : ""}`}>{i + 1}. {l}</span>)}
        <span style={{ flex: 1 }} /><span className="chip" data-testid="room-question">{before ? "Waiting to start" : `Question ${qi + 1} of ${nq}`}</span>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "1fr 360px", gap: 14 }}>
        <div className="card" style={{ padding: 0, overflow: "hidden", position: "relative" }}>
          <div data-testid="survey-canvas" style={{ height: 600, position: "relative", background: "#17120d" }}>
            {use3d ? <Suspense fallback={<Room2D tables={shown} agents={agents} st={st} selected={sel} onSelect={setSel} privateText={privateText} mode={doc.mode} />}>
              <Room3D tables={tables} agents={agents} st={st} selected={sel} onSelect={setSel} focusTable={selTable} onFocusTable={setSelTable} privateText={privateText} mode={doc.mode} frozen={isVisualTest} />
            </Suspense> : <Room2D tables={shown} agents={agents} st={st} selected={sel} onSelect={setSel} privateText={privateText} mode={doc.mode} />}
          </div>
          <div className="glass" style={{ position: "absolute", left: 12, top: 12, padding: "8px 12px", maxWidth: 520 }} data-testid="room-card">
            {before ? <><div className="xs muted">People are arriving and taking seats</div><b>{counts?.arrived ?? 0} of {counts?.accepted ?? 0} here · Q1 in {mmss(secondsToStart(live?.start_at_t))}</b></>
              : done ? <><b>Done · {doc.results?.n_attended ?? attending} answered</b> <button className="btn sm primary" style={{ marginLeft: 8 }} onClick={() => nav(withMode(`/insights/focus/${surveyId}/results`))}>See results →</button></>
              : <><div className="xs muted">{st.phase === "ballot" ? "Private ballot · everyone answers alone on a tablet" : "Moderator is going round the table"}</div><b>Q{qi + 1} · {doc.questions[qi]?.text}</b></>}
          </div>
          <div className="room-ctl">
            <div className="seg glass"><button className={selTable === null ? "on" : ""} onClick={() => setSelTable(null)}>Whole room</button>
              {tables.filter((t) => t.seats.length).map((t) => <button key={t.table_id} className={selTable === t.table_id ? "on" : ""} onClick={() => setSelTable(t.table_id)}>{t.table_id.replace("T", "Table ")}</button>)}</div>
            {hasWebGL() && <button className={`btn sm ${use3d ? "on" : ""}`} onClick={() => setUse3d((v) => !v)}>3D</button>}
          </div>
          <div className="glass row" style={{ position: "absolute", left: 12, bottom: 12, padding: "6px 10px", gap: 8 }}>
            {running ? <><span className="chip green" style={{ padding: "1px 8px" }}><span className="dotlive" />Live</span><span className="xs muted">You can leave and come back any time; the session keeps going.</span></>
              : <><div className="seg"><button className={playing ? "on" : ""} onClick={() => { if (cursor >= items.length) setCursor(0); setPlaying((p) => !p); }}>{playing ? "❚❚ Pause" : "▶ Replay"}</button></div>
                <div className="seg">{[1, 2, 4].map((s) => <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>)}</div>
                <input type="range" min={0} max={items.length} value={cursor} onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }} style={{ width: 160 }} aria-label="Scrub" /></>}
          </div>
        </div>
        <div className="card" style={{ display: "flex", flexDirection: "column", height: 600 }}>
          <div className="row between"><b className="small">Transcript · {curTable.replace("T", "Table ")}</b>
            <label className="xs row" style={{ gap: 6 }}><input type="checkbox" checked={showPrivate} onChange={(e) => setShowPrivate(e.target.checked)} /> private thoughts</label></div>
          <div className="row" style={{ gap: 4, flexWrap: "wrap", marginTop: 6 }}>{tables.filter((t) => t.seats.length).map((t) => <button key={t.table_id} className={`chip ${curTable === t.table_id ? "teal" : ""}`} style={{ cursor: "pointer" }} onClick={() => setSelTable(t.table_id)}>{t.table_id} · {t.seats.length}</button>)}</div>
          <div data-testid="survey-transcript" style={{ overflow: "auto", flex: 1, marginTop: 8 }}>
            {lines.map((x) => x.kind === "private"
              ? <div key={x.id} className="privcard" style={{ margin: "6px 0" }}><div className="h">PRIVATE THOUGHT · {name(x.speaker).toUpperCase()}</div>{x.text}</div>
              : <div key={x.id} className="item" style={{ margin: "6px 0", padding: "7px 10px" }}><b className="small" style={{ color: x.speaker === "moderator" ? "var(--teal)" : "var(--ink)" }}>{name(x.speaker)}</b><div className="small">{x.text}</div></div>)}
            {!lines.length && <div className="xs muted">{before ? "The discussion starts when the session begins." : `No messages yet at ${curTable || "this table"}.`}</div>}
          </div>
        </div>
      </div>
      <div style={{ marginTop: 14, maxWidth: 360, marginLeft: "auto" }}><SessionsCol cur={surveyId} /></div>
    </div>
  );
}
