import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getJSON } from "../../lib/api";
import { isVisualTest, withMode } from "../../lib/visualTest";
import {
  CHANNELS, MAX_OPTIONS, MAX_PRODUCTS, addOption, cleanQuestions, createSurvey, estimateSurvey, launchSurvey, lintQuestions,
  newQuestion, optionsFromProducts, questionIssues, questionProblems, removeOption, resolveStart, withType,
  type Channel, type EstimateOut, type Goodie, type QType, type QuestionDef, type When,
} from "../../lib/survey";
import { DEFAULT_GOODIES, GOODIE_PRESETS } from "../../lib/focus";
import { POLL_PRESETS, applyPreset, type PollPreset } from "../../lib/presets";
import { useWorld } from "../../state/world";
import { SessionsCol } from "./SessionsCol";

const STAGES = ["", "aware", "curious", "researching", "inquiring"];
const TYPES: [QType, string][] = [["single", "Single choice"], ["multi", "Multiple choice"], ["scale", "Linear scale"], ["open", "Short answer"]];
type WhenKey = "next" | "in5" | "in15" | "in60" | "tomorrow" | "pick";
const WHEN_OPTIONS: [WhenKey, string][] = [["next", "Next slot (~30 min)"], ["in15", "In 15 min"], ["in60", "In 1 hour"], ["tomorrow", "Tomorrow at…"], ["pick", "Pick a time"]];

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

/** Insights → Focus groups: builder (left), who to invite + what they get + estimate (middle), sessions (right). */
export function FocusBuilder() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const simT = useWorld((s) => s.t);
  const [title, setTitle] = useState(params.get("title") ?? "");
  const [topic, setTopic] = useState("");
  const [presetId, setPresetId] = useState<string | null>(params.get("preset"));
  const [mode, setMode] = useState<"focus_group" | "survey">("focus_group");
  const [productIds, setProductIds] = useState<string[]>(params.get("product") ? [String(params.get("product"))] : []);
  const [qs, setQs] = useState<QuestionDef[]>([newQuestion(1)]);
  const [whenKey, setWhenKey] = useState<WhenKey>("next");
  const [hhmm, setHhmm] = useState("18:00");
  const [picked, setPicked] = useState<string[]>(DEFAULT_GOODIES);
  const [custom, setCustom] = useState("");
  const [channels, setChannels] = useState<Channel[]>(["panel", "community", "word_of_mouth", "store_flyer"]);
  const [ageMin, setAgeMin] = useState(""), [ageMax, setAgeMax] = useState("");
  const [income, setIncome] = useState(""), [occupation, setOccupation] = useState("");
  const [phoneAge, setPhoneAge] = useState(params.get("phone_age") ?? "");
  const [stage, setStage] = useState("");
  const [maxN, setMaxN] = useState(40), [tableSize, setTableSize] = useState(8);
  const [products, setProducts] = useState<Prod[]>([]);
  const [prodErr, setProdErr] = useState("");
  const [est, setEst] = useState<EstimateOut | null>(null);
  const [warn, setWarn] = useState<{ question_id: string; kind: string; fix: string }[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (!isVisualTest) void getJSON<Prod[]>("/products?active=1").then(setProducts).catch((e: unknown) => setProdErr(String(e))); }, []);
  const pickPreset = (p: PollPreset, list: Prod[]) => {
    const live = list.filter((x) => x.status === "live");
    const f = applyPreset(p, live.length ? live : list);
    setPresetId(p.id); setTitle(f.title); setTopic(f.topic); setProductIds(f.product_ids); setQs(f.questions); setWarn([]);
  };
  useEffect(() => {   // ?preset=… from the Polls tab: apply once the products are known
    const p = POLL_PRESETS.find((x) => x.id === params.get("preset"));
    if (p && (products.length || prodErr || isVisualTest)) pickPreset(p, products);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [products, prodErr]);
  const chosen = useMemo(() => products.filter((p) => productIds.includes(p.product_id)), [products, productIds]);
  const cohort = useMemo(() => {
    const c: string[] = [];
    if (ageMin) c.push(`age >= ${Number(ageMin)}`);
    if (ageMax) c.push(`age <= ${Number(ageMax)}`);
    if (income) c.push(`income_band = '${income}'`);
    if (occupation) c.push(`LOWER(occupation) LIKE '%${occupation.toLowerCase().replace(/'/g, "")}%'`);
    if (phoneAge) c.push(`phone_age_years > ${Number(phoneAge)}`);
    return c.join(" AND ");
  }, [ageMin, ageMax, income, occupation, phoneAge]);
  const chips = [ageMin || ageMax ? `Age ${ageMin || "any"}–${ageMax || "any"}` : "", income ? `Income ${income}` : "", occupation ? `Job: ${occupation}` : "",
    phoneAge ? `Phone older than ${phoneAge} years` : "", stage && productIds[0] ? `${stage}+ for ${chosen[0]?.name ?? productIds[0]}` : ""].filter(Boolean);
  const start = useMemo(() => resolveStart(simT, whenOf(whenKey, hhmm)), [simT, whenKey, hhmm]);
  const problems = useMemo(() => questionProblems(qs), [qs]);
  const goodies = useMemo<Goodie[]>(() => picked.map((label) => {
    const p = GOODIE_PRESETS.find((x) => x.label === label);
    return p ? { kind: p.kind, label: p.label, value_inr: p.value_inr } : { kind: "other", label: label.slice(0, 60), value_inr: 300 };
  }), [picked]);
  const incentive = useMemo(() => ({ cash_inr: 0, goodies, note: "" }), [goodies]);
  const body = () => ({ title, mode, product_id: productIds[0] ?? null, product_ids: productIds, topic, questions: cleanQuestions(qs),
    cohort_filter: cohort || null, interest_filter: stage && productIds[0] ? { product_id: productIds[0], min_stage: stage } : null,
    max_participants: maxN, table_size: tableSize, incentive, channels, start_at_t: start.t });
  const check = () => { lintQuestions(cleanQuestions(qs)).then((r) => setWarn(r.warnings)).catch(() => undefined); };
  const badTime = start.t === null && whenKey !== "next";

  useEffect(() => {
    if (isVisualTest) { setEst({ eligible: 187, reach: 150, expected_attendance: 40, tables: 5, estimate_usd: 0.31, remaining_interactive_usd: 9.62, lint: [] }); return; }
    if (title.trim().length < 3 || problems.length || badTime || !channels.length) {
      setEst(null);
      setErr(title.trim().length < 3 ? "Give it a title (3+ characters)" : problems[0] ?? (!channels.length ? "Pick at least one way for people to hear about it" : "Pick a valid time (HH:MM)"));
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
    try { const made = await createSurvey(body()); await launchSurvey(made.survey_id); nav(withMode(`/insights/focus/${made.survey_id}/wait`)); }
    catch (e) { setErr(String(e).replace(/^Error: /, "")); }
    setBusy(false);
  };
  const over = est ? est.estimate_usd > est.remaining_interactive_usd : false;
  const leadMin = start.lead ?? 30;
  return (
    <div className="grid" data-testid="focus-builder" style={{ gridTemplateColumns: "1.55fr 1fr 340px", alignItems: "start" }}>
      <div className="grid" style={{ alignContent: "start" }}>
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>New poll</h3>
            <div className="seg"><button className={mode === "focus_group" ? "on" : ""} onClick={() => setMode("focus_group")}>Focus group</button><button className={mode === "survey" ? "on" : ""} onClick={() => setMode("survey")}>Survey (written)</button></div></div>
          <div className="xs muted" style={{ marginTop: 12 }}>Start from a ready-made question set</div>
          <div className="grid g4" data-testid="poll-presets" style={{ marginTop: 6, gap: 8, gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
            {POLL_PRESETS.map((p) => (
              <button key={p.id} data-testid={`preset-${p.id}`} className={`item ${presetId === p.id ? "on" : ""}`} aria-pressed={presetId === p.id}
                style={{ textAlign: "left", cursor: "pointer", borderColor: presetId === p.id ? "var(--teal)" : undefined }} onClick={() => pickPreset(p, products)}>
                <b className="small">{p.label}</b><div className="xs muted" style={{ marginTop: 2 }}>{p.hint} · {p.questions.length} questions</div>
              </button>
            ))}
          </div>
          <div className="grid g2" style={{ marginTop: 12, gap: 10 }}>
            <div><label className="xs muted">Title</label><input value={title} placeholder="e.g. Pixel 10a — price & battery" onChange={(e) => setTitle(e.target.value)} />
              <label className="xs muted" style={{ display: "block", marginTop: 8 }}>Topic <span className="muted">(optional)</span></label><input value={topic} placeholder="What the moderator introduces" onChange={(e) => setTopic(e.target.value)} /></div>
            <div><label className="xs muted">Products <span className="muted">(optional · up to {MAX_PRODUCTS})</span></label>
              <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                {products.map((p) => (
                  <button key={p.product_id} className={`chip ${productIds.includes(p.product_id) ? "teal" : ""}`} style={{ cursor: "pointer" }} aria-pressed={productIds.includes(p.product_id)}
                    disabled={!productIds.includes(p.product_id) && productIds.length >= MAX_PRODUCTS} onClick={() => setProductIds((cur) => toggle(cur, p.product_id))}>{p.name}</button>
                ))}
                {!products.length && <span className="xs muted">{prodErr ? `Couldn't load products (${prodErr})` : "No live or ready products."}</span>}
              </div></div>
          </div>
          <div className="xs muted" style={{ marginTop: 8 }}>
            {mode === "focus_group" ? "They walk to the Research Lounge, sit at round tables, discuss each question with a moderator, then answer privately on a tablet."
              : "They walk to the Research Lounge and answer each question privately, with no discussion."}
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
          <button className="btn sm" style={{ marginTop: 10 }} disabled={isVisualTest || problems.length > 0} onClick={check}>Check questions for bias</button>
        </div>
        <div className="card" data-testid="survey-when">
          <h3>When</h3>
          <div className="seg" role="radiogroup" aria-label="Start time">{WHEN_OPTIONS.map(([k, l]) => <button key={k} role="radio" aria-checked={whenKey === k} className={whenKey === k ? "on" : ""} onClick={() => setWhenKey(k)}>{l}</button>)}</div>
          {(whenKey === "tomorrow" || whenKey === "pick") && <div className="row" style={{ gap: 8, marginTop: 8 }}><label className="xs">Time (24 h)</label><input value={hhmm} onChange={(e) => setHhmm(e.target.value)} style={{ width: 80 }} placeholder="18:00" /></div>}
          <div className="xs" style={{ marginTop: 8 }}>{start.label}</div>
          {start.lead !== null && start.lead < 30 && <div className="xs" style={{ color: "var(--amber)", marginTop: 4 }}>Short notice: only people nearby and free will make it.</div>}
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
      </div>

      <div className="list" style={{ gap: 14 }}>
        <div className="card" data-testid="survey-audience"><h3>Who to invite</h3>
          <div className="row wrap" style={{ gap: 6 }}>{chips.length ? chips.map((c) => <span key={c} className="chip teal">{c}</span>) : <span className="chip">Everyone</span>}</div>
          <div className="grid g2" style={{ gap: 8, marginTop: 10 }}>
            <div><label className="xs muted">Age</label><div className="row" style={{ gap: 4 }}><input value={ageMin} onChange={(e) => setAgeMin(e.target.value)} placeholder="min" /><input value={ageMax} onChange={(e) => setAgeMax(e.target.value)} placeholder="max" /></div></div>
            <div><label className="xs muted">Income</label><select value={income} onChange={(e) => setIncome(e.target.value)}><option value="">Any</option>{["<25k", "25-50k", "50k-1L", "1-2L", ">2L"].map((x) => <option key={x}>{x}</option>)}</select></div>
            <div><label className="xs muted">Job contains</label><input value={occupation} onChange={(e) => setOccupation(e.target.value)} placeholder="any" /></div>
            <div><label className="xs muted">Phone older than (yrs)</label><input value={phoneAge} onChange={(e) => setPhoneAge(e.target.value)} placeholder="any" /></div>
            <div style={{ gridColumn: "span 2" }}><label className="xs muted">Interest in the first product (stage ≥)</label><select value={stage} onChange={(e) => setStage(e.target.value)} disabled={!productIds.length}>{STAGES.map((s) => <option key={s} value={s}>{s || "any stage"}</option>)}</select></div>
          </div>
          <label className="xs muted" style={{ display: "block", marginTop: 12 }}>Max participants <b className="mono" style={{ color: "var(--ink)" }}>{maxN}</b> (1–100)</label>
          <input type="range" min={1} max={100} value={maxN} onChange={(e) => setMaxN(Number(e.target.value))} style={{ width: "100%" }} />
          <div className="grid g2" style={{ marginTop: 10, gap: 10, fontSize: 13 }}>
            <div><div className="xs muted">Tables</div>round tables × <select value={tableSize} onChange={(e) => setTableSize(Number(e.target.value))} style={{ width: 60, padding: "2px 6px" }}>{[6, 7, 8, 9, 10].map((n) => <option key={n}>{n}</option>)}</select></div>
            <div><div className="xs muted">Venue</div>Research Lounge, 100 Ft Rd</div>
            <div><div className="xs muted">Starts</div>in ~{leadMin} sim min (time to walk there)</div>
            <div><div className="xs muted">Eligible</div>{est ? `${est.eligible} people` : "…"}</div>
          </div>
          <h3 style={{ marginTop: 14 }}>What they get for coming</h3>
          <div className="grid g2" style={{ gap: 8 }} data-testid="goodies">{GOODIE_PRESETS.map((g) => (
            <button key={g.label} className={`goodie ${picked.includes(g.label) ? "on" : ""}`} aria-pressed={picked.includes(g.label)}
              disabled={!picked.includes(g.label) && picked.length >= 5} onClick={() => setPicked((cur) => toggle(cur, g.label))}><span className="e">{g.emoji}</span>{g.label}</button>
          ))}
            {picked.filter((l) => !GOODIE_PRESETS.some((g) => g.label === l)).map((l) => (
              <button key={l} className="goodie on" onClick={() => setPicked((cur) => cur.filter((x) => x !== l))}><span className="e">✨</span>{l} ×</button>))}
          </div>
          <form className="row" style={{ gap: 6, marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); const v = custom.trim().slice(0, 60); if (v && picked.length < 5 && !picked.includes(v)) setPicked((c) => [...c, v]); setCustom(""); }}>
            <input value={custom} placeholder="Something else (e.g. free phone check-up)" maxLength={60} onChange={(e) => setCustom(e.target.value)} />
            <button className="btn sm" type="submit" disabled={!custom.trim() || picked.length >= 5}>Add</button>
          </form>
          <div className="xs muted" style={{ marginTop: 6 }}>No cash. Goodies matter differently to different people: gadget fans like accessories, food fans like the coffee.</div>
        </div>
        <div className="card" data-testid="survey-estimate"><h3>Estimate</h3>
          {est ? <div className="grid g2" style={{ gap: 10 }}>
            <div className="card kpi tight"><div className="l">Expected to come</div><div className="v">~{est.expected_attendance}</div><div className="d muted">{est.reach !== undefined ? `of ${est.reach} who will hear` : ""}</div></div>
            <div className="card kpi tight"><div className="l">Model cost</div><div className="v">${est.estimate_usd.toFixed(2)}</div><div className="d muted" style={{ color: over ? "var(--red)" : undefined }}>${est.remaining_interactive_usd.toFixed(2)} left today</div></div>
          </div> : <div className="xs muted" role="status">{err || "Calculating…"}</div>}
          {est?.message && <div className="xs" style={{ color: "var(--amber)", marginTop: 6 }}>{est.message}</div>}
          {over && <div className="xs" style={{ color: "var(--red)", marginTop: 6 }}>Over budget — try fewer participants, fewer questions or the written format.</div>}
          <button className="btn primary" data-testid="survey-launch" style={{ marginTop: 12, width: "100%", justifyContent: "center" }} disabled={!est || busy || over || !est.eligible || isVisualTest} onClick={() => void launch()}>{busy ? "Launching…" : `📋 Launch ${mode === "focus_group" ? "focus group" : "survey"}`}</button>
          {err && est && <div className="xs" style={{ color: "var(--red)", marginTop: 6 }}>{err}</div>}
          <div className="xs muted" style={{ marginTop: 8 }}>Runs inside the always-on world on Google Cloud, even if nobody is watching. Everyone who opens the site sees the same countdown.</div>
        </div>
      </div>
      <SessionsCol />
    </div>
  );
}
