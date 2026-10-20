import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/Shell";
import { getJSON } from "../../lib/api";
import { isVisualTest, withMode } from "../../lib/visualTest";
import {
  CHANNELS, MAX_OPTIONS, MAX_PRODUCTS, addOption, cleanQuestions, createSurvey, estimateSurvey, launchSurvey, lintQuestions,
  newQuestion, optionsFromProducts, questionIssues, questionProblems, removeOption, resolveStart, withType,
  type Channel, type EstimateOut, type Goodie, type QType, type QuestionDef, type When,
} from "../../lib/survey";
import { useWorld } from "../../state/world";

const STAGES = ["", "aware", "curious", "researching", "inquiring"];
const TYPES: [QType, string][] = [["single", "Single choice"], ["multi", "Multiple choice"], ["scale", "Linear scale"], ["open", "Short answer"]];
const GOODIE_KINDS: [Goodie["kind"], string][] = [["voucher", "Voucher"], ["accessory", "Accessory"], ["food", "Food"], ["product_trial", "Product trial"], ["merch", "Merch"], ["other", "Other"]];
type WhenKey = "next" | "in5" | "in15" | "in60" | "tomorrow" | "pick";
const WHEN_OPTIONS: [WhenKey, string][] = [["next", "Next slot"], ["in5", "In 5 min"], ["in15", "In 15 min"], ["in60", "In 1 hour"], ["tomorrow", "Tomorrow at…"], ["pick", "Pick a time"]];

interface Prod { product_id: string; name: string; status: string }

function whenOf(key: WhenKey, hhmm: string): When {
  return key === "next" ? { kind: "next" } : key === "in5" ? { kind: "in", minutes: 5 } : key === "in15" ? { kind: "in", minutes: 15 }
    : key === "in60" ? { kind: "in", minutes: 60 } : key === "tomorrow" ? { kind: "tomorrow", hhmm } : { kind: "pick", hhmm };
}

/** One question card, Google-Forms style: text, type, option rows, scale labels, discuss toggle, order and delete. */
function QuestionCard({ q, i, n, mode, products, issues, warnings, onChange, onMove, onDelete }: {
  q: QuestionDef; i: number; n: number; mode: "focus_group" | "survey"; products: Prod[]; issues: string[]; warnings: { kind: string; fix: string }[];
  onChange: (q: QuestionDef) => void; onMove: (d: number) => void; onDelete: () => void;
}) {
  const choice = q.type === "single" || q.type === "multi";
  const opts = q.options ?? [];
  return (
    <div className="item" data-testid={`survey-q-${i}`}>
      <div className="row" style={{ gap: 8 }}>
        <b className="small">Q{i + 1}</b>
        <input value={q.text} placeholder="Question" aria-label={`Question ${i + 1}`} onChange={(e) => onChange({ ...q, text: e.target.value })} style={{ flex: 1, minWidth: 0, width: "auto" }} />
        <select aria-label="Question type" style={{ width: 150, flex: "none" }} value={q.type} onChange={(e) => onChange(withType(q, e.target.value as QType))}>
          {TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <button className="btn" style={{ padding: "2px 7px" }} aria-label="Move up" disabled={i === 0} onClick={() => onMove(-1)}>↑</button>
        <button className="btn" style={{ padding: "2px 7px" }} aria-label="Move down" disabled={i === n - 1} onClick={() => onMove(1)}>↓</button>
        <button className="btn" style={{ padding: "2px 7px" }} aria-label="Delete question" disabled={n === 1} onClick={onDelete}>×</button>
      </div>

      {choice && (
        <div className="list" style={{ gap: 6, marginTop: 8 }}>
          {opts.map((o, k) => (
            <div key={k} className="row" style={{ gap: 6 }}>
              <span className="muted xs" style={{ width: 16 }}>{q.type === "multi" ? "☐" : "○"}</span>
              <input value={o} placeholder={`Option ${k + 1}`} aria-label={`Option ${k + 1}`} style={{ flex: 1, minWidth: 0, width: "auto" }}
                onChange={(e) => onChange({ ...q, option_source: "custom", options: opts.map((x, m) => (m === k ? e.target.value : x)) })} />
              <button className="btn" style={{ padding: "2px 7px" }} aria-label={`Remove option ${k + 1}`} disabled={opts.length <= 2} onClick={() => onChange(removeOption(q, k))}>×</button>
            </div>
          ))}
          <div className="row" style={{ gap: 8 }}>
            <button className="btn" disabled={opts.length >= MAX_OPTIONS} onClick={() => onChange(addOption(q))}>+ Add option</button>
            <span className="xs muted">{opts.length}/{MAX_OPTIONS}</span>
            {products.length > 0 && <button className="btn" onClick={() => onChange(optionsFromProducts(q, products.map((p) => p.name)))}>Use selected products as options</button>}
            {q.type === "multi" && <label className="xs row" style={{ gap: 4, marginLeft: "auto" }}>choose up to
              <input type="number" min={1} max={Math.max(1, opts.length)} value={q.max_select ?? 2} style={{ width: 56 }} onChange={(e) => onChange({ ...q, max_select: Number(e.target.value) })} /></label>}
          </div>
        </div>
      )}

      {q.type === "scale" && q.scale && (
        <div className="list" style={{ gap: 6, marginTop: 8 }}>
          <div className="row xs" style={{ gap: 8 }}>
            <span>1 to</span>
            <select aria-label="Scale maximum" value={q.scale.max} style={{ width: 70 }} onChange={(e) => onChange({ ...q, scale: { ...q.scale!, max: Number(e.target.value) } })}><option value={5}>5</option><option value={10}>10</option></select>
            <span className="muted">Answers are whole numbers on this scale.</span>
          </div>
          <div className="row xs" style={{ gap: 8 }}>
            <span style={{ width: 20 }}>1 =</span>
            <input value={q.scale.low_label} placeholder="Label for 1 (optional), e.g. Not at all" aria-label="Label for the low end" style={{ flex: 1 }} onChange={(e) => onChange({ ...q, scale: { ...q.scale!, low_label: e.target.value } })} />
            <span style={{ width: 28 }}>{q.scale.max} =</span>
            <input value={q.scale.high_label} placeholder={`Label for ${q.scale.max} (optional), e.g. Certainly`} aria-label="Label for the high end" style={{ flex: 1 }} onChange={(e) => onChange({ ...q, scale: { ...q.scale!, high_label: e.target.value } })} />
          </div>
        </div>
      )}

      {q.type === "open" && <div className="xs muted" style={{ marginTop: 6 }}>People answer in their own words (up to 60).</div>}
      {mode === "focus_group" && (
        <label className="xs row" style={{ gap: 4, marginTop: 8 }}><input type="checkbox" checked={q.discuss} onChange={(e) => onChange({ ...q, discuss: e.target.checked })} />Discuss at the table before answering</label>
      )}
      {issues.map((m, k) => <div key={k} className="xs" style={{ color: "var(--red)", marginTop: 4 }}>{m}</div>)}
      {warnings.map((w, k) => <div key={k} className="xs" style={{ color: "var(--amber)", marginTop: 4 }}>⚠ {w.kind.replace("_", " ")}: {w.fix}</div>)}
    </div>
  );
}

/** Survey Room builder: title, products, questions, timing, reward, how people hear about it, audience, launch. */
export function SurveyBuilderPage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const simT = useWorld((s) => s.t);
  const [title, setTitle] = useState(params.get("title") ?? "");
  const [mode, setMode] = useState<"focus_group" | "survey">("focus_group");
  const [productIds, setProductIds] = useState<string[]>(params.get("product") ? [String(params.get("product"))] : []);
  const [qs, setQs] = useState<QuestionDef[]>([newQuestion(1)]);
  const [whenKey, setWhenKey] = useState<WhenKey>("next");
  const [hhmm, setHhmm] = useState("18:00");
  const [cash, setCash] = useState(500);
  const [goodies, setGoodies] = useState<Goodie[]>([]);
  const [channels, setChannels] = useState<Channel[]>(["panel", "community", "word_of_mouth", "store_flyer"]);
  const [ageMin, setAgeMin] = useState(""), [ageMax, setAgeMax] = useState("");
  const [income, setIncome] = useState(""), [occupation, setOccupation] = useState("");
  const [phoneAge, setPhoneAge] = useState(params.get("phone_age") ?? "");
  const [lifestyle, setLifestyle] = useState("");
  const [stage, setStage] = useState("");
  const [maxN, setMaxN] = useState(40), [tableSize, setTableSize] = useState(8);
  const [products, setProducts] = useState<Prod[]>([]);
  const [est, setEst] = useState<EstimateOut | null>(null);
  const [warn, setWarn] = useState<{ question_id: string; kind: string; fix: string }[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (!isVisualTest) void getJSON<Prod[]>("/products").then(setProducts).catch(() => undefined); }, []);
  const chosen = useMemo(() => products.filter((p) => productIds.includes(p.product_id)), [products, productIds]);
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
  const start = useMemo(() => resolveStart(simT, whenOf(whenKey, hhmm)), [simT, whenKey, hhmm]);
  const problems = useMemo(() => questionProblems(qs), [qs]);
  const incentive = useMemo(() => ({ cash_inr: Math.max(0, Math.min(5000, Math.round(cash) || 0)),
    goodies: goodies.filter((g) => g.label.trim()).map((g) => ({ ...g, label: g.label.trim() })), note: "" }), [cash, goodies]);
  const body = () => ({ title, mode, product_id: productIds[0] ?? null, product_ids: productIds, topic: "", questions: cleanQuestions(qs),
    cohort_filter: cohort || null, interest_filter: stage && productIds[0] ? { product_id: productIds[0], min_stage: stage } : null,
    max_participants: maxN, table_size: tableSize, incentive, incentive_inr: incentive.cash_inr, channels, start_at_t: start.t });
  const check = () => { lintQuestions(cleanQuestions(qs)).then((r) => setWarn(r.warnings)).catch(() => undefined); };
  const badTime = start.t === null && whenKey !== "next";

  useEffect(() => {
    if (isVisualTest) { setEst({ eligible: 187, reach: 150, expected_attendance: 40, tables: 5, estimate_usd: 0.31, remaining_interactive_usd: 9.62, lint: [] }); return; }
    if (title.trim().length < 3 || problems.length || badTime || !channels.length) {
      setEst(null);
      setErr(title.trim().length < 3 ? "Give the survey a title (3+ characters)" : problems[0] ?? (!channels.length ? "Pick at least one way for people to hear about it" : "Pick a valid time (HH:MM)"));
      return;
    }
    // sizing only: the API writes nothing and calls no model until Launch
    const h = setTimeout(() => { setErr(""); estimateSurvey(body()).then((r) => { setEst(r); setWarn(r.lint); }).catch((e) => setErr(String(e).replace(/^Error: /, ""))); }, 800);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, mode, productIds, qs, cohort, stage, maxN, tableSize, start.t, incentive, channels, problems, badTime]);

  const upd = (i: number, q: QuestionDef) => setQs((cur) => cur.map((x, k) => (k === i ? q : x)));
  const move = (i: number, d: number) => setQs((cur) => { const c = [...cur]; const j = i + d; if (j < 0 || j >= c.length) return c; [c[i], c[j]] = [c[j], c[i]]; return c; });
  const toggle = <T,>(list: T[], v: T): T[] => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const launch = async () => {
    if (!est) return;
    setBusy(true); setErr("");
    try { const made = await createSurvey(body()); await launchSurvey(made.survey_id); nav(withMode(`/insights/polls/survey/${made.survey_id}`)); }
    catch (e) { setErr(String(e).replace(/^Error: /, "")); }
    setBusy(false);
  };
  const over = est ? est.estimate_usd > est.remaining_interactive_usd : false;
  const live = products.filter((p) => p.status === "live" || productIds.includes(p.product_id));
  return (
    <div className="page" data-testid="survey-builder">
      <PageTitle title="Survey Room" sub="Invite the agents to a real-world-style survey or focus group. They hear about it, decide whether to come, plan their trip, then answer privately."
        right={<><button className="btn" onClick={() => nav(withMode("/insights/polls"))}>← Polls</button></>} />
      <div className="grid g21">
        <div className="grid" style={{ alignContent: "start" }}>
          <div className="card">
            <div className="filters">
              <div style={{ flex: 2 }}><label>Title</label><input value={title} placeholder="Survey title" onChange={(e) => setTitle(e.target.value)} /></div>
              <div><label>Format</label><div className="seg"><button className={mode === "focus_group" ? "on" : ""} onClick={() => setMode("focus_group")}>Focus group</button><button className={mode === "survey" ? "on" : ""} onClick={() => setMode("survey")}>Survey</button></div></div>
            </div>
            <div className="xs muted" style={{ marginTop: 6 }}>
              {mode === "focus_group" ? "Focus group: they travel to the Research Lounge, sit at tables, discuss each question, then answer privately."
                : "Survey: they travel to the Research Lounge and answer each question privately, with no discussion."}
              {" "}Want instant answers with no travel? <a href={withMode("/insights/polls")} onClick={(e) => { e.preventDefault(); nav(withMode("/insights/polls")); }}>Use a quick poll</a>.
            </div>
            <div style={{ marginTop: 12 }}>
              <label>Products in this survey <span className="muted xs">(optional · up to {MAX_PRODUCTS})</span></label>
              <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                <button className={`chip ${productIds.length === 0 ? "teal" : ""}`} style={{ cursor: "pointer" }} aria-pressed={productIds.length === 0} onClick={() => setProductIds([])}>None</button>
                {live.map((p) => (
                  <button key={p.product_id} className={`chip ${productIds.includes(p.product_id) ? "teal" : ""}`} style={{ cursor: "pointer" }} aria-pressed={productIds.includes(p.product_id)}
                    disabled={!productIds.includes(p.product_id) && productIds.length >= MAX_PRODUCTS} onClick={() => setProductIds((cur) => toggle(cur, p.product_id))}>{p.name}</button>
                ))}
              </div>
              <div className="xs muted" style={{ marginTop: 4 }}>{productIds.length > 1 ? "Questions can compare these products (use them as answer options)." : productIds.length === 1 ? "People are asked about this product." : "No product: a general survey."}</div>
            </div>
          </div>

          <div className="card" data-testid="survey-questions">
            <div className="row between"><h3 style={{ margin: 0 }}>Questions ({qs.length}/10)</h3>
              <button className="btn" disabled={qs.length >= 10} onClick={() => setQs((cur) => [...cur, newQuestion(cur.length + 1)])}>+ Add question</button></div>
            <div className="list" style={{ marginTop: 10 }}>
              {qs.map((q, i) => (
                <QuestionCard key={i} q={q} i={i} n={qs.length} mode={mode} products={chosen} issues={problems.length ? questionIssues(q, i) : []}
                  warnings={warn.filter((w) => w.question_id === `q${i + 1}`)} onChange={(x) => upd(i, x)} onMove={(d) => move(i, d)} onDelete={() => setQs((cur) => cur.filter((_, k) => k !== i))} />
              ))}
            </div>
          </div>

          <div className="card" data-testid="survey-when">
            <h3>When</h3>
            <div className="seg" role="radiogroup" aria-label="Start time">{WHEN_OPTIONS.map(([k, l]) => <button key={k} role="radio" aria-checked={whenKey === k} className={whenKey === k ? "on" : ""} onClick={() => setWhenKey(k)}>{l}</button>)}</div>
            {(whenKey === "tomorrow" || whenKey === "pick") && <div className="row" style={{ gap: 8, marginTop: 8 }}><label className="xs">Time (24 h)</label><input value={hhmm} onChange={(e) => setHhmm(e.target.value)} style={{ width: 80 }} placeholder="18:00" /></div>}
            <div className="xs" style={{ marginTop: 8 }}>{start.label}</div>
            {start.lead !== null && start.lead < 30 && <div className="xs" style={{ color: "var(--amber)", marginTop: 4 }}>Short notice: only people nearby and free will make it.</div>}
            <div className="xs muted" style={{ marginTop: 4 }}>Until then the world carries on as normal. Agents only find out through the ways you pick below.</div>
          </div>

          <div className="card" data-testid="survey-incentive">
            <h3>What people get for coming</h3>
            <div className="row" style={{ gap: 10 }}><div><label>Cash (₹)</label><input type="number" min={0} max={5000} value={cash} onChange={(e) => setCash(Number(e.target.value))} style={{ width: 110 }} /></div>
              <div className="xs muted" style={{ flex: 1 }}>The same amount means more to someone on a small income than a large one.</div></div>
            <div className="list" style={{ gap: 6, marginTop: 8 }}>
              {goodies.map((g, i) => (
                <div key={i} className="row" style={{ gap: 6 }}>
                  <select aria-label="Goodie type" value={g.kind} style={{ width: 130 }} onChange={(e) => setGoodies((cur) => cur.map((x, k) => (k === i ? { ...x, kind: e.target.value as Goodie["kind"] } : x)))}>{GOODIE_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
                  <input value={g.label} placeholder="What is it? e.g. wireless earbuds" aria-label="Goodie description" style={{ flex: 1 }} onChange={(e) => setGoodies((cur) => cur.map((x, k) => (k === i ? { ...x, label: e.target.value } : x)))} />
                  <input type="number" min={0} value={g.value_inr} aria-label="Goodie value in rupees" style={{ width: 90 }} onChange={(e) => setGoodies((cur) => cur.map((x, k) => (k === i ? { ...x, value_inr: Number(e.target.value) } : x)))} /><span className="xs muted">₹</span>
                  <button className="btn" style={{ padding: "2px 7px" }} aria-label="Remove goodie" onClick={() => setGoodies((cur) => cur.filter((_, k) => k !== i))}>×</button>
                </div>
              ))}
              <div><button className="btn" disabled={goodies.length >= 5} onClick={() => setGoodies((cur) => [...cur, { kind: "accessory", label: "", value_inr: 500 }])}>+ Add a goodie</button></div>
            </div>
            <div className="xs muted" style={{ marginTop: 6 }}>Goodies appeal differently: gadget fans like accessories, shoppers like vouchers, chatty people like merch.</div>
          </div>

          <div className="card" data-testid="survey-channels">
            <h3>How people hear about it</h3>
            <div className="list" style={{ gap: 6 }}>{CHANNELS.map((c) => (
              <label key={c.key} className="row" style={{ gap: 8, alignItems: "flex-start" }}>
                <input type="checkbox" checked={channels.includes(c.key)} onChange={() => setChannels((cur) => toggle(cur, c.key))} style={{ marginTop: 3 }} />
                <span><b className="small">{c.label}</b><div className="xs muted">{c.hint}</div></span>
              </label>
            ))}</div>
          </div>

          <div className="card" data-testid="survey-audience"><h3>Audience</h3><div className="filters">
            <div><label>Age</label><div className="row" style={{ gap: 4 }}><input value={ageMin} onChange={(e) => setAgeMin(e.target.value)} placeholder="min" style={{ width: 60 }} /><input value={ageMax} onChange={(e) => setAgeMax(e.target.value)} placeholder="max" style={{ width: 60 }} /></div></div>
            <div><label>Income</label><select value={income} onChange={(e) => setIncome(e.target.value)}><option value="">Any</option>{["<25k", "25-50k", "50k-1L", "1-2L", ">2L"].map((x) => <option key={x}>{x}</option>)}</select></div>
            <div><label>Occupation</label><input value={occupation} onChange={(e) => setOccupation(e.target.value)} placeholder="any" /></div>
            <div><label>Phone older than (years)</label><input value={phoneAge} onChange={(e) => setPhoneAge(e.target.value)} placeholder="any" style={{ width: 80 }} /></div>
            <div><label>Lifestyle</label><input value={lifestyle} onChange={(e) => setLifestyle(e.target.value)} placeholder="e.g. student_life" /></div>
            <div><label>Interested in (stage ≥)</label><select value={stage} onChange={(e) => setStage(e.target.value)} disabled={!productIds.length}>{STAGES.map((s) => <option key={s} value={s}>{s || "any"}</option>)}</select></div>
          </div>
            <div className="filters" style={{ marginTop: 10 }}>
              <div style={{ flex: 2 }}><label>Max participants: {maxN}</label><input type="range" min={1} max={100} value={maxN} onChange={(e) => setMaxN(Number(e.target.value))} /></div>
              <div><label>Table size</label><select value={tableSize} onChange={(e) => setTableSize(Number(e.target.value))}>{[6, 7, 8, 9, 10].map((n) => <option key={n}>{n}</option>)}</select></div>
            </div>
            <div className="xs muted" style={{ marginTop: 6 }}>Cohort filter: <code>{cohort || "everyone"}</code>{stage && productIds[0] ? ` · stage ≥ ${stage} for the first product` : ""}</div></div>
        </div>

        <div className="grid" style={{ alignContent: "start" }}>
          <div className="card" data-testid="survey-estimate"><h3>Estimate</h3>
            {est ? <div className="list small">
              <div className="item row between"><span>Eligible agents</span><b className="mono">{est.eligible}</b></div>
              {est.reach !== undefined && <div className="item row between"><span>Expected to hear about it</span><b className="mono">{est.reach}</b></div>}
              <div className="item row between"><span>Expected attendance</span><b className="mono">{est.expected_attendance}</b></div>
              <div className="item row between"><span>Round tables ({tableSize} seats)</span><b className="mono">{est.tables}</b></div>
              <div className="item row between"><span>Estimated model cost</span><b className="mono">${est.estimate_usd.toFixed(2)}</b></div>
              <div className="item row between"><span>Interactive budget left today</span><b className="mono" style={{ color: over ? "var(--red)" : undefined }}>${est.remaining_interactive_usd.toFixed(2)}</b></div>
              {est.message && <div className="xs" style={{ color: "var(--amber)" }}>{est.message}</div>}
              {over && <div className="xs" style={{ color: "var(--red)" }}>Over budget — try fewer participants, fewer questions or survey format.</div>}
            </div> : <div className="xs muted" role="status">{err || "Calculating…"}</div>}
            <button className="btn" style={{ marginTop: 12, width: "100%" }} disabled={isVisualTest || problems.length > 0} onClick={check}>Check questions</button>
            <button className="btn primary" data-testid="survey-launch" style={{ marginTop: 8, width: "100%" }} disabled={!est || busy || over || !est.eligible || isVisualTest} onClick={() => void launch()}>Launch {mode === "focus_group" ? "focus group" : "survey"}</button>
            {err && est && <div className="xs" style={{ color: "var(--red)", marginTop: 6 }}>{err}</div>}
            <p className="xs muted" style={{ marginTop: 8 }}>Agents decide for private reasons. Answers are private, one per person per question, on Gemini Flash-Lite. Counts against the interactive budget.</p></div>
        </div>
      </div>
    </div>
  );
}
