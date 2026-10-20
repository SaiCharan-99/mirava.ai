import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageTitle } from "../components/Shell";
import { StageChip } from "../components/Profile";
import { useWorld } from "../state/world";
import { useWatch } from "../state/watch";
import { actLabel, bandLabel, incomeLabel } from "../lib/agentView";
import { getJSON, peopleQS, type PeoplePage as PeopleResp, type PeopleQuery, type PeopleRow } from "../lib/api";
import { fmtInt } from "../lib/time";
import { withMode } from "../lib/visualTest";
import type { Fixtures } from "../visual-fixtures/types";

const PAGE = 15;
export const EMPTY: PeopleQuery = { q: "", age: "", income: "", product: "", phoneOld: false, page: 1 };

/** A row as the table shows it (live API row or fixture agent). */
export interface Row {
  id: number; name: string; age: number; job: string; income: string; phone: string; phoneAge: number;
  stages: Record<string, { stage: string; att?: number }>; act: string;
}

const inRange = (age: number, r: string): boolean => {
  if (!r) return true;
  const [lo, hi] = r.split("-").map(Number);
  return age >= lo && age <= (hi || 200);
};
const CURIOUS = ["curious", "researching", "inquiring", "deciding", "purchased"];

/** Client-side filter over fixture agents (visual-test mode / before /live), same rules as the API. */
export function filterFixtures(fx: Fixtures, f: PeopleQuery): Row[] {
  const q = f.q.toLowerCase();
  let rows = fx.agents.filter((a: any) => (!q || a.name.toLowerCase().includes(q) || a.job.toLowerCase().includes(q))
    && (!f.phoneOld || a.phone.age > 5) && inRange(a.age, f.age)
    && (!f.income || incomeLabel(a.income) === bandLabel(f.income))
    && (!f.product || (() => {
      const [p, st] = f.product.split(":");
      const b = a.beliefs[p];
      return !!b && (st === "curious+" ? CURIOUS.includes(b.stage) : b.stage === st);
    })()));
  if (f.phoneOld) rows = rows.slice().sort((a, b) => b.phone.age - a.phone.age);
  return rows.map((a: any) => ({
    id: a.id, name: a.name, age: a.age, job: a.job, income: incomeLabel(a.income), phone: `${a.phone.brand} · ${a.phone.tier}`,
    phoneAge: a.phone.age, stages: a.beliefs, act: a.act,
  }));
}

/** API row → table row. */
const CSV_COLS = ["agent_id", "name", "age", "job", "income_band", "phone_brand", "phone_age_years", "phone_condition"];

/** CSV of every agent matching the filters (all pages), downloaded in the browser. */
async function exportCsv(f: PeopleQuery, fixtureRows: Row[] | null): Promise<void> {
  const raw: PeopleRow[] = fixtureRows ? [] : (await getJSON<PeopleResp>(`/agents?${peopleQS({ ...f, page: 1 }, 1000)}`)).rows;
  const lines = raw.map((r) => [r.agent_id, r.name, r.age, r.occupation, r.income_band, r.phone.brand, r.phone.age_years,
    r.phone.condition]);
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [CSV_COLS, ...lines].map((l) => l.map(esc).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "mirava-agents-simulated.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

export function fromApi(r: PeopleRow): Row {
  const stages: Row["stages"] = {};
  for (const [k, v] of Object.entries(r.stages ?? {})) stages[k] = typeof v === "string" ? { stage: v } : { stage: v.stage, att: v.attitude };
  return {
    id: r.agent_id, name: r.name, age: r.age, job: r.occupation, income: bandLabel(r.income_band),
    phone: `${r.phone.brand}${r.phone.tier ? " · " + r.phone.tier : ""}`, phoneAge: r.phone.age_years, stages, act: actLabel(r.activity ?? ""),
  };
}

function Stage({ b }: { b?: { stage: string; att?: number } }) {
  if (b && b.att === undefined && b.stage !== "unaware") return <StageChip b={{ stage: b.stage, att: 0 }} />;
  return <StageChip b={b && b.att !== undefined ? { stage: b.stage, att: b.att } : null} />;
}

/** People (U-05): search, filters, watch stars, row → World + profile. */
export function PeoplePage() {
  const nav = useNavigate();
  const source = useWorld((s) => s.source);
  const fx = useWorld((s) => s.fixtures);
  const live = useWorld((s) => s.products).filter((p) => p.status === "live");
  const openProfile = useWorld((s) => s.openProfile);
  const watch = useWatch((s) => s.ids);
  const toggle = useWatch((s) => s.toggle);
  const [f, setF] = useState<PeopleQuery>(EMPTY);
  const [qText, setQText] = useState("");
  const [resp, setResp] = useState<{ rows: Row[]; total: number; old: number } | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setF((x) => (x.q === qText ? x : { ...x, q: qText, page: 1 })), 250);
    return () => clearTimeout(id);
  }, [qText]);

  const fixtureRows = useMemo(() => (source !== "live" && fx ? filterFixtures(fx, f) : null), [source, fx, f]);
  useEffect(() => {
    if (source !== "live") return;
    let on = true;
    getJSON<PeopleResp>(`/agents?${peopleQS(f, PAGE)}`)
      .then((r) => on && setResp({ rows: r.rows.map(fromApi), total: r.total, old: r.phone_old_count ?? 0 }))
      .catch(() => on && setResp({ rows: [], total: 0, old: 0 }));
    return () => {
      on = false;
    };
  }, [source, f]);

  const total = fixtureRows ? fixtureRows.length : (resp?.total ?? 0);
  const rows = fixtureRows ? fixtureRows.slice((f.page - 1) * PAGE, f.page * PAGE) : (resp?.rows ?? []);
  const old = fx && source !== "live" ? fx.agents.filter((a) => a.phone.age > 5).length : (resp?.old ?? 0);
  const agents = useWorld((s) => s.stats.agents) || 1000;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const set = (p: Partial<PeopleQuery>) => setF((x) => ({ ...x, ...p, page: p.page ?? 1 }));
  const go = (id: number) => {
    openProfile(id, "overview");
    nav(withMode("/world"));
  };

  return (
    <div className="page">
      <PageTitle title="People" sub={`All ${fmtInt(agents)} agents in the world · ${old} have phones older than 5 years · ${watch.length} watched`}
        right={<button className="btn" title="Download the agents matching these filters (simulated data)"
          onClick={() => void exportCsv(f, fixtureRows)}>Export CSV</button>} />
      <div className="card" data-testid="people-filters" style={{ marginBottom: 14 }}><div className="filters">
        <div style={{ minWidth: 260 }}><label>Search</label><input placeholder="Name or job…" value={qText} onChange={(e) => setQText(e.target.value)} /></div>
        <div><label>Age</label><select value={f.age} onChange={(e) => set({ age: e.target.value })}>
          <option value="">Any</option><option value="18-24">18–24</option><option value="25-34">25–34</option>
          <option value="35-44">35–44</option><option value="45-200">45+</option></select></div>
        <div><label>Income band</label><select value={f.income} onChange={(e) => set({ income: e.target.value })}>
          <option value="">Any</option><option value="<25k">{"< ₹25k"}</option><option value="25-50k">₹25–50k</option>
          <option value="50k-1L">₹50k–1L</option><option value="1-2L">₹1–2L</option><option value=">2L">{"> ₹2L"}</option></select></div>
        <div><label>Product · stage</label><select value={f.product} onChange={(e) => set({ product: e.target.value })}
          title="Product stages fill in once products are live (phase 4)">
          <option value="">Any</option>
          {live.map((p) => <option key={p.id} value={`${p.id}:curious+`}>{p.name} · curious+</option>)}
          {live[0] && <option value={`${live[0].id}:inquiring`}>{live[0].name} · inquired</option>}
        </select></div>
        <div><label>Phone</label><button className={`btn ${f.phoneOld ? "on" : ""}`} onClick={() => set({ phoneOld: !f.phoneOld })}>Older than 5 years</button></div>
        <div><label>&nbsp;</label><button className="btn" onClick={() => { setQText(""); setF(EMPTY); }}>Reset</button></div>
      </div></div>
      <div className="card" data-testid="people-table" style={{ padding: 0 }}>
        <table><tbody>
          <tr><th style={{ width: 34 }} /><th>Name</th><th>Age</th><th>Job</th><th>Income</th><th>Phone</th><th style={{ textAlign: "right" }}>Phone age</th>
            {live.map((p) => <th key={p.id}>{p.name}</th>)}<th>Doing now</th><th /></tr>
          {rows.map((a) => {
            const on = watch.includes(a.id);
            return (
              <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => go(a.id)}>
                <td><span className={`star ${on ? "on" : ""}`} onClick={(e) => { e.stopPropagation(); toggle(a.id); }}>{on ? "★" : "☆"}</span></td>
                <td><b>{a.name}</b></td><td>{a.age}</td><td className="small">{a.job}</td><td className="small">{a.income}</td>
                <td className="small">{a.phone}</td>
                <td className="mono" style={{ textAlign: "right", color: a.phoneAge > 5 ? "var(--red)" : "inherit" }}>{a.phoneAge.toFixed(1)} y</td>
                {live.map((p) => <td className="small" key={p.id}><Stage b={a.stages[p.id]} /></td>)}
                <td className="small muted">{a.act}</td>
                <td><button className="btn sm" data-testid={`interview-${a.id}`} onClick={(e) => { e.stopPropagation(); nav(withMode(`/insights/interview?agent=${a.id}`)); }}>Interview</button></td>
              </tr>
            );
          })}
        </tbody></table>
        <div className="row between small muted" style={{ padding: "10px 14px", borderTop: "1px solid var(--line)" }}>
          <span>Showing {rows.length} of {fmtInt(total)}</span>
          <span><a style={{ cursor: "pointer" }} onClick={() => f.page > 1 && set({ page: f.page - 1 })}>‹</a>{" "}
            {Array.from({ length: Math.min(3, pages) }, (_, i) => i + 1).map((n) => (
              <a key={n} style={{ cursor: "pointer", fontWeight: n === f.page ? 700 : 400 }} onClick={() => set({ page: n })}>{n} </a>))}
            {pages > 3 ? "… " : ""}<a style={{ cursor: "pointer" }} onClick={() => f.page < pages && set({ page: f.page + 1 })}>›</a></span>
        </div>
      </div>
    </div>
  );
}
