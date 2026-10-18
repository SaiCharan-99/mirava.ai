import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/Shell";
import { getJSON } from "../../lib/api";
import { isVisualTest, withMode } from "../../lib/visualTest";
import { createSurvey, launchSurvey, lintQuestions, type CreateOut, type QType, type QuestionDef } from "../../lib/survey";

const DEFAULT_QS: QuestionDef[] = [
  { question_id: "q1", text: "What matters most to you in the Pixel 10a?", type: "single", options: ["Battery life", "Price", "Camera", "Brand trust"], discuss: true },
  { question_id: "q2", text: "How likely are you to buy the Pixel 10a in the next 3 months?", type: "scale", scale: { min: 1, max: 5, low_label: "not at all", high_label: "certainly" }, discuss: true },
  { question_id: "q3", text: "What would make you switch to the Pixel 10a?", type: "open", discuss: true },
];
const STAGES = ["", "aware", "curious", "researching", "inquiring"];

/** Survey Room builder (addendum B9): questions, audience, estimate, launch. */
export function SurveyBuilderPage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [title, setTitle] = useState(params.get("title") ?? "Pixel 10a — price and camera");
  const [mode, setMode] = useState<"focus_group" | "survey">("focus_group");
  const [product, setProduct] = useState(params.get("product") ?? "pixel-10a");
  const [topic, setTopic] = useState("Pixel 10a");
  const [qs, setQs] = useState<QuestionDef[]>(DEFAULT_QS);
  const [ageMin, setAgeMin] = useState(""), [ageMax, setAgeMax] = useState("");
  const [income, setIncome] = useState(""), [occupation, setOccupation] = useState("");
  const [phoneAge, setPhoneAge] = useState(params.get("phone_age") ?? "5");
  const [lifestyle, setLifestyle] = useState("");
  const [stage, setStage] = useState("");
  const [maxN, setMaxN] = useState(40), [tableSize, setTableSize] = useState(8), [incentive, setIncentive] = useState(500);
  const [startMode, setStartMode] = useState<"next" | "pick">("next"), [startHour, setStartHour] = useState("18:00");
  const [products, setProducts] = useState<{ product_id: string; name: string; status: string }[]>([]);
  const [est, setEst] = useState<CreateOut | null>(null);
  const [warn, setWarn] = useState<CreateOut["lint"]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!isVisualTest) void getJSON<typeof products>("/products").then(setProducts).catch(() => undefined); }, []);
  const cohort = useMemo(() => {
    const c: string[] = [];
    if (ageMin) c.push(`age >= ${Number(ageMin)}`);
    if (ageMax) c.push(`age <= ${Number(ageMax)}`);
    if (income) c.push(`income_band = '${income}'`);
    if (occupation) c.push(`LOWER(occupation) LIKE '%${occupation.toLowerCase().replace(/'/g, "")}%'`);
    if (phoneAge) c.push(`phone_age_years > ${Number(phoneAge)}`);
    if (lifestyle) c.push(`lifestyle = '${lifestyle}'`);
    return c.join(" AND ");
  }, [ageMin, ageMax, income, occupation, phoneAge, lifestyle]);
  const body = () => ({ title, mode, product_id: product || null, topic, questions: qs, cohort_filter: cohort || null,
    interest_filter: stage && product ? { product_id: product, min_stage: stage } : null, max_participants: maxN, table_size: tableSize,
    incentive_inr: incentive, start_at_t: null });
  useEffect(() => {
    if (isVisualTest) return;
    const h = setTimeout(() => { lintQuestions(qs).then((r) => setWarn(r.warnings)).catch(() => undefined); }, 700);
    return () => clearTimeout(h);
  }, [qs]);
  useEffect(() => {
    if (isVisualTest) { setEst({ survey_id: "sv-demo", eligible: 187, expected_attendance: 40, tables: 5, estimate_usd: 0.31, remaining_interactive_usd: 4.62, lint: [] }); return; }
    const h = setTimeout(() => { setErr(""); createSurvey(body()).then(setEst).catch((e) => setErr(String(e))); }, 600);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, mode, product, topic, qs, cohort, stage, maxN, tableSize, incentive]);
  const upd = (i: number, patch: Partial<QuestionDef>) => setQs((q) => q.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  const move = (i: number, d: number) => setQs((q) => { const c = [...q]; const j = i + d; if (j < 0 || j >= c.length) return c; [c[i], c[j]] = [c[j], c[i]]; return c; });
  const launch = async () => {
    if (!est) return;
    setBusy(true); setErr("");
    try { await launchSurvey(est.survey_id); nav(withMode(`/insights/polls/survey/${est.survey_id}`)); }
    catch (e) { setErr(String(e).replace(/^Error: /, "")); }
    setBusy(false);
  };
  const over = est ? est.estimate_usd > est.remaining_interactive_usd : false;
  return (
    <div className="page" data-testid="survey-builder">
      <PageTitle title="Survey Room" sub="Run a real-world-style focus group or survey with the agents. They decide whether to come, walk to the Research Lounge, discuss, then answer privately."
        right={<><button className="btn" onClick={() => nav(withMode("/insights/polls"))}>← Polls</button><span className="sim-badge">SIMULATED</span></>} />
      <div className="grid g21">
        <div className="grid" style={{ alignContent: "start" }}>
          <div className="card"><div className="filters">
            <div style={{ flex: 2 }}><label>Title</label><input value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            <div><label>Mode</label><div className="seg"><button className={mode === "focus_group" ? "on" : ""} onClick={() => setMode("focus_group")}>Focus group</button><button className={mode === "survey" ? "on" : ""} onClick={() => setMode("survey")}>Survey</button></div></div>
            <div><label>Product</label><select value={product} onChange={(e) => setProduct(e.target.value)}><option value="">(topic only)</option>{(products.length ? products : [{ product_id: "pixel-10a", name: "Pixel 10a", status: "live" }]).map((p) => <option key={p.product_id} value={p.product_id}>{p.name}</option>)}</select></div>
            <div><label>Topic</label><input value={topic} onChange={(e) => setTopic(e.target.value)} /></div>
          </div></div>
          <div className="card" data-testid="survey-questions"><div className="row between"><h3 style={{ margin: 0 }}>Questions ({qs.length}/10)</h3>
            <button className="btn" disabled={qs.length >= 10} onClick={() => setQs((q) => [...q, { question_id: `q${q.length + 1}`, text: "", type: "single", options: ["Yes", "No"], discuss: true }])}>+ Add question</button></div>
            <div className="list" style={{ marginTop: 10 }}>{qs.map((q, i) => (
              <div key={i} className="item">
                <div className="row" style={{ gap: 8 }}><b className="small">Q{i + 1}</b>
                  <input value={q.text} placeholder="Question text" onChange={(e) => upd(i, { text: e.target.value })} style={{ flex: 1, minWidth: 0, width: "auto" }} />
                  <select style={{ width: 150, flex: "none" }} value={q.type} onChange={(e) => { const t = e.target.value as QType; upd(i, { type: t, options: t === "single" || t === "multi" ? q.options ?? ["Yes", "No"] : null, scale: t === "scale" ? { min: 1, max: 5, low_label: "low", high_label: "high" } : null, max_select: t === "multi" ? 2 : null }); }}>
                    <option value="single">Single choice</option><option value="multi">Multiple choice</option><option value="scale">Scale</option><option value="open">Open</option></select>
                  <label className="xs row" style={{ gap: 4 }}><input type="checkbox" checked={q.discuss} onChange={(e) => upd(i, { discuss: e.target.checked })} />discuss</label>
                  <button className="btn" style={{ padding: "2px 7px" }} onClick={() => move(i, -1)}>↑</button><button className="btn" style={{ padding: "2px 7px" }} onClick={() => move(i, 1)}>↓</button>
                  <button className="btn" style={{ padding: "2px 7px" }} onClick={() => setQs((x) => x.filter((_, k) => k !== i))}>×</button></div>
                {(q.type === "single" || q.type === "multi") && <input style={{ marginTop: 6 }} value={(q.options ?? []).join(" · ")} onChange={(e) => upd(i, { options: e.target.value.split("·").map((s) => s.trim()).filter(Boolean).slice(0, 8) })} placeholder="Options separated by ·" />}
                {q.type === "multi" && <div className="xs" style={{ marginTop: 4 }}>max select <input type="number" min={1} max={8} value={q.max_select ?? 2} onChange={(e) => upd(i, { max_select: Number(e.target.value) })} style={{ width: 60 }} /></div>}
                {q.type === "scale" && q.scale && <div className="row xs" style={{ gap: 6, marginTop: 6 }}>
                  <select value={q.scale.max} onChange={(e) => upd(i, { scale: { ...q.scale!, max: Number(e.target.value) } })}><option value={5}>1–5</option><option value={10}>1–10</option></select>
                  <input value={q.scale.low_label} onChange={(e) => upd(i, { scale: { ...q.scale!, low_label: e.target.value } })} placeholder="low anchor" />
                  <input value={q.scale.high_label} onChange={(e) => upd(i, { scale: { ...q.scale!, high_label: e.target.value } })} placeholder="high anchor" /></div>}
                {warn.filter((w) => w.question_id === q.question_id).map((w, k) => <div key={k} className="xs" style={{ color: "var(--amber)", marginTop: 4 }}>⚠ {w.kind.replace("_", " ")}: {w.fix}</div>)}
              </div>
            ))}</div></div>
          <div className="card" data-testid="survey-audience"><h3>Audience</h3><div className="filters">
            <div><label>Age</label><div className="row" style={{ gap: 4 }}><input value={ageMin} onChange={(e) => setAgeMin(e.target.value)} placeholder="min" style={{ width: 60 }} /><input value={ageMax} onChange={(e) => setAgeMax(e.target.value)} placeholder="max" style={{ width: 60 }} /></div></div>
            <div><label>Income</label><select value={income} onChange={(e) => setIncome(e.target.value)}><option value="">Any</option>{["<25k", "25-50k", "50k-1L", "1-2L", ">2L"].map((x) => <option key={x}>{x}</option>)}</select></div>
            <div><label>Occupation</label><input value={occupation} onChange={(e) => setOccupation(e.target.value)} placeholder="any" /></div>
            <div><label>Phone older than (years)</label><input value={phoneAge} onChange={(e) => setPhoneAge(e.target.value)} style={{ width: 80 }} /></div>
            <div><label>Lifestyle</label><input value={lifestyle} onChange={(e) => setLifestyle(e.target.value)} placeholder="e.g. student_life" /></div>
            <div><label>Interested in (stage ≥)</label><select value={stage} onChange={(e) => setStage(e.target.value)}>{STAGES.map((s) => <option key={s} value={s}>{s || "any"}</option>)}</select></div>
          </div>
            <div className="filters" style={{ marginTop: 10 }}>
              <div style={{ flex: 2 }}><label>Max participants: {maxN}</label><input type="range" min={1} max={100} value={maxN} onChange={(e) => setMaxN(Number(e.target.value))} /></div>
              <div><label>Table size</label><select value={tableSize} onChange={(e) => setTableSize(Number(e.target.value))}>{[6, 7, 8, 9, 10].map((n) => <option key={n}>{n}</option>)}</select></div>
              <div><label>Start</label><div className="seg"><button className={startMode === "next" ? "on" : ""} onClick={() => setStartMode("next")}>Next slot</button><button className={startMode === "pick" ? "on" : ""} onClick={() => setStartMode("pick")}>Pick</button></div>{startMode === "pick" && <input value={startHour} onChange={(e) => setStartHour(e.target.value)} style={{ width: 70, marginTop: 4 }} />}</div>
              <div><label>Incentive (₹)</label><input type="number" value={incentive} onChange={(e) => setIncentive(Number(e.target.value))} style={{ width: 90 }} /></div>
            </div>
            <div className="xs muted" style={{ marginTop: 6 }}>Cohort filter: <code>{cohort || "everyone"}</code>{stage && product ? ` · ${product} stage ≥ ${stage}` : ""}</div></div>
        </div>
        <div className="grid" style={{ alignContent: "start" }}>
          <div className="card" data-testid="survey-estimate"><h3>Estimate</h3>
            {est ? <div className="list small">
              <div className="item row between"><span>Eligible agents</span><b className="mono">{est.eligible}</b></div>
              <div className="item row between"><span>Expected attendance</span><b className="mono">{est.expected_attendance}</b></div>
              <div className="item row between"><span>Round tables ({tableSize} seats)</span><b className="mono">{est.tables}</b></div>
              <div className="item row between"><span>Estimated model cost</span><b className="mono">${est.estimate_usd.toFixed(2)}</b></div>
              <div className="item row between"><span>Interactive budget left today</span><b className="mono" style={{ color: over ? "var(--red)" : undefined }}>${est.remaining_interactive_usd.toFixed(2)}</b></div>
              {est.message && <div className="xs" style={{ color: "var(--amber)" }}>{est.message}</div>}
              {over && <div className="xs" style={{ color: "var(--red)" }}>Over budget — try fewer participants, fewer questions or survey mode.</div>}
            </div> : <div className="xs muted">{err || "Calculating…"}</div>}
            <button className="btn primary" data-testid="survey-launch" style={{ marginTop: 12, width: "100%" }} disabled={!est || busy || over || !est.eligible || isVisualTest} onClick={() => void launch()}>Launch {mode === "focus_group" ? "focus group" : "survey"}</button>
            {err && est && <div className="xs" style={{ color: "var(--red)", marginTop: 6 }}>{err}</div>}
            <p className="xs muted" style={{ marginTop: 8 }}>Invited agents decide whether to come (private reasons). Answers are private, one per person per question, on Gemini Flash-Lite. Counts against the interactive budget.</p></div>
        </div>
      </div>
    </div>
  );
}
