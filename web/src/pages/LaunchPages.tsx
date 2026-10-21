/** Launch Studio (L-01 … L-07): product list and the 5-step editor, laid out exactly like the mockup. In visual-test mode
 * the content is the mockup's demo fixtures; live, every card is backed by the products API. */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../components/Shell";
import { GraphView } from "../components/GraphView";
import { PlanCanvas, loadSites, type MapSite } from "../components/PlanCanvas";
import { KINDS, STEPS, kindTitle, studioApi, useStudio, type Asset, type Kind, type Step, type StudioProduct } from "../lib/studio";
import { fmt, fmtINR, fmtInt } from "../lib/time";
import { isVisualTest, withMode } from "../lib/visualTest";
import { toast } from "../lib/toast";

const live = !isVisualTest;
const ARROWS = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"];
const FACES = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const oct = (f: number): number => Math.round((((f % 360) + 360) % 360) / 45) % 8;
const statusChip = (s: string): string => (s === "live" ? "green" : s === "ready" ? "amber" : "");

function Kpi({ l, v }: { l: string; v: ReactNode }) {
  return <div className="card kpi"><div className="l">{l}</div><div className="v">{v}</div></div>;
}

function useProducts(): { products: StudioProduct[]; loaded: boolean; error: string | null } {
  const { products, loaded, error, load } = useStudio();
  useEffect(() => { void load(); }, [load]);
  return { products, loaded, error };
}

async function run<T>(what: string, f: () => Promise<T>): Promise<T | null> {
  try {
    return await f();
  } catch (e) {
    toast(`${what} failed: ${(e as Error).message}`);
    return null;
  }
}

/* ================================================================ list */

export function LaunchListPage() {
  const { products, loaded, error } = useProducts();
  const nav = useNavigate();
  const create = async () => {
    if (!live) return toast("New product draft created (mockup)");
    const name = window.prompt("Product name");
    if (!name?.trim()) return;
    const p = await run("Create", () => studioApi.create({ name: name.trim(), brand: "", category: "Smartphone", price_inr: 0 }));
    if (p) { useStudio.getState().upsert(p); nav(`/launch/${p.product_id}/details`); }
  };
  return (
    <div className="page">
      <PageTitle title="Launch Studio" sub="Create products and their marketing. Products you mark ready appear on the World map, where you launch them one at a time."
        right={<button className="btn primary" onClick={create}>＋ New product</button>} />
      <div className="grid g3" data-testid="products-grid">
        {!loaded && !products.length && <div className="card small muted">Loading products…</div>}
        {products.map((p) => (
          <div className="pcard" data-testid="product-card" data-product={p.id} key={p.id}
            onClick={() => nav(withMode(`/launch/${p.id}/${p.status === "live" ? "plan" : "details"}`))}>
            <div className="stripe" style={{ background: p.hex }} />
            <div className="row between"><span className="xs muted">{p.brand} · {p.cat}</span>
              <span className={`chip ${statusChip(p.status)}`} style={{ padding: "0 8px" }}>{p.status}</span></div>
            <h2 style={{ margin: "8px 0 2px", fontSize: 20 }}>{p.name}</h2>
            <div className="small muted">“{p.tagline}” · {fmtINR(p.price)}</div>
            <div className="grid g3" style={{ marginTop: 14, gap: 8 }}>
              {([["Content", p.contentCount], ["Hoardings", p.sites.length], ["Stores", p.storeNames.length]] as const).map(([l, v]) => (
                <div className="item" style={{ padding: "8px 10px" }} key={l}><div className="xs muted">{l}</div><b className="mono">{v}</b></div>
              ))}
            </div>
            <div className="small" style={{ marginTop: 12 }}>
              {p.status === "live" ? <>Launched {fmt(p.launched ?? 0)} · <Link to={withMode("/insights/overview")} onClick={(e) => e.stopPropagation()}>see insights</Link></>
                : p.status === "ready" ? <>Ready · <Link to={withMode("/world")} onClick={(e) => e.stopPropagation()}>launch it from the World map</Link></> : "Draft"}
            </div>
          </div>
        ))}
        <div className="pcard" data-testid="new-product-card" style={{ borderStyle: "dashed", display: "grid", placeItems: "center", textAlign: "center", color: "var(--muted)" }} onClick={create}>
          <div><div style={{ fontSize: 28 }}>＋</div><b>New product</b><div className="xs">Any category — phones today, clothing tomorrow</div></div>
        </div>
      </div>
      {error && <div className="item small" style={{ marginTop: 12 }}>Could not load products: {error}</div>}
      <div className="card" style={{ marginTop: 16 }}><h3>How a launch works</h3>
        <div className="grid g5 small">
          {[["1 · Details", "Name, price, features, claims, target personas, strategy"], ["2 · Content", "Posters, reel transcript, posts, print ad, store display, reviewer kit"],
            ["3 · Understanding", "Claim risk, creative salience, knowledge graph"], ["4 · Plan (automatic)", "Sites + facing chosen from the world's own foot traffic"],
            ["5 · Ready → Launch", "It appears on the World map's dock; press Launch"]].map(([h, t]) => (
            <div className="item" key={h}><b>{h}</b><div className="muted xs" style={{ marginTop: 4 }}>{t}</div></div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ================================================================ editor */

export function StudioPage() {
  const { productId = "", step = "details" } = useParams();
  const { products, loaded } = useProducts();
  const p = products.find((x) => x.id === productId);
  const nav = useNavigate();
  if (!p) return <div className="page"><PageTitle title="Launch Studio" sub={loaded ? "Unknown product." : "Loading…"} right={<Link className="btn" to={withMode("/launch")}>← All products</Link>} /></div>;
  const st = (STEPS.some(([k]) => k === step) ? step : "details") as Step;
  const si = STEPS.findIndex(([k]) => k === st);
  const Body = { details: StepDetails, content: StepContent, understand: StepUnderstand, plan: StepPlan, ready: StepReady }[st];
  return (
    <div className="page">
      <PageTitle title={<><span className="pdot" style={{ background: p.hex, width: 12, height: 12, marginRight: 8 }} />{p.name}</>}
        sub={<>{p.brand} · {p.cat} · {fmtINR(p.price)} · <span className={`chip ${statusChip(p.status)}`} style={{ padding: "0 8px" }}>{p.status}</span></>}
        right={<><Link className="btn" to={withMode("/launch")}>← All products</Link>{p.status === "ready" && <Link className="btn primary" to={withMode("/world")}>Go to World to launch →</Link>}</>} />
      <div className="steps" data-testid="studio-steps">
        {STEPS.map(([k, l], i) => (
          <button key={k} data-testid={`studio-step-${k}`} className={k === st ? "on" : i < si ? "done" : ""} onClick={() => nav(withMode(`/launch/${p.id}/${k}`))}>
            <span className="n">{i < si ? "✓" : i + 1}</span>{l}
          </button>
        ))}
      </div>
      <div data-testid="studio-body"><Body p={p} key={p.id + st} /></div>
    </div>
  );
}

/* ---------------------------------------------------------------- 1 · details */

const lines = (s: string): string[] => s.split("\n").map((x) => x.trim()).filter(Boolean);

function StepDetails({ p }: { p: StudioProduct }) {
  const locked = p.status === "live" || p.status === "ended";
  const [f, setF] = useState({ name: p.name, brand: p.brand, cat: p.cat, price: p.price ? p.price.toLocaleString("en-IN") : "", offer: p.offer, tagline: p.tagline,
    features: p.features.join("\n"), claims: p.claims.map((c) => c.text).join("\n"), free: isVisualTest ? "Working professionals 24–38 who shoot photos at night and can afford EMI." : "",
    flight: String(p.flight), intensity: p.intensity, goal: "Awareness + consideration among photographers" });
  const [personas, setPersonas] = useState(p.personas);
  const [adding, setAdding] = useState("");
  const [aud, setAud] = useState({ n: p.audienceCount, desc: p.audienceDesc });
  const [stores, setStores] = useState<string[]>(p.storeNames);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    if (!live || locked) return;
    const all = [...personas, ...(f.free.trim() ? [f.free.trim()] : [])];
    const ids = stores.map((n) => ({ "Digital Bazaar": "ST-DIGITAL-BAZAAR", ElectroHub: "ST-ELECTROHUB", PhoneWorld: "ST-PHONEWORLD" } as Record<string, string>)[n] ?? n);
    const r = await run("Save", () => studioApi.patch(p.id, { brand: f.brand, category: f.cat, price_inr: Number(f.price.replace(/[^0-9]/g, "")) || 0,
      launch_offer: f.offer || null, features: lines(f.features), claims: lines(f.claims), target_personas: all,
      strategy: { goal: f.goal, key_message: f.tagline, flight_days: Number(f.flight) || 14, intensity: f.intensity, stores: ids } }));
    if (!r) return;
    useStudio.getState().upsert(r);
    const a = await run("Audience", () => studioApi.audience(p.id));
    if (a) {
      setAud({ n: a.total, desc: a.audience.map((x) => `${x.description} (${x.count})`).join(" · ") });
      useStudio.getState().upsert(await studioApi.get(p.id));
    }
    toast("Saved · audience recompiled");
  };
  const allStores = ["Digital Bazaar", "ElectroHub", "PhoneWorld"];
  return (
    <div className="grid g21">
      <div className="card" data-testid="details-form"><h3>Product</h3>
        <div className="fieldrow"><div><label>Product name</label><input value={f.name} readOnly /></div><div><label>Brand</label><input value={f.brand} onChange={set("brand")} /></div></div>
        <div className="fieldrow"><div><label>Category</label><select value={f.cat} onChange={set("cat")}><option>Smartphone</option><option>Clothing</option><option>Laptop</option><option>Other…</option></select></div>
          <div><label>Price (₹)</label><input value={f.price} onChange={set("price")} /></div></div>
        <div className="fieldrow"><div><label>Launch offer</label><input value={f.offer} onChange={set("offer")} /></div><div><label>Tagline / key message</label><input value={f.tagline} onChange={set("tagline")} /></div></div>
        <label>Key features (one per line)</label><textarea style={{ minHeight: 96 }} value={f.features} onChange={set("features")} />
        <label style={{ marginTop: 12 }}>Claims you will make (checked for risk in Understanding)</label><textarea style={{ minHeight: 80 }} value={f.claims} onChange={set("claims")} />
        {live && !locked && <div className="row" style={{ marginTop: 12, gap: 8 }}><button className="btn primary sm" onClick={save}>Save details</button><span className="xs muted">Saving also recompiles the audience from the personas.</span></div>}
      </div>
      <div className="grid" style={{ alignContent: "start" }}>
        <div className="card" data-testid="personas-card"><h3>Target personas</h3>
          <div className="row wrap" style={{ gap: 6, marginBottom: 10 }}>
            {personas.map((x) => <span key={x} className="chip teal" style={{ cursor: live ? "pointer" : undefined }} onClick={() => live && setPersonas(personas.filter((y) => y !== x))}>{x} ✕</span>)}
            {adding !== "" && live ? (
              <input autoFocus style={{ width: 180, padding: "2px 8px" }} value={adding === " " ? "" : adding} onChange={(e) => setAdding(e.target.value || " ")}
                onKeyDown={(e) => { if (e.key === "Enter" && adding.trim()) { setPersonas([...personas, adding.trim()]); setAdding(""); } if (e.key === "Escape") setAdding(""); }} />
            ) : <span className="chip" style={{ cursor: live ? "pointer" : undefined }} onClick={() => live && setAdding(" ")}>＋ add</span>}
          </div>
          <label>Describe anyone else (free text)</label><textarea style={{ minHeight: 56 }} value={f.free} onChange={set("free")} />
          <div className="item small" style={{ marginTop: 10 }}><b>≈ {fmtInt(aud.n)} agents match</b><div className="xs muted">{aud.desc || "Save to compile the personas into audience rules."}</div></div>
          <p className="xs muted" style={{ margin: "8px 0 0" }}>Personas aim the plan (feed audience, hoarding areas, tracked segment). They never create or change agents.</p>
        </div>
        <div className="card" data-testid="strategy-card"><h3>Strategy</h3><label>Goal</label>
          <select value={f.goal} onChange={set("goal")}><option>Awareness + consideration among photographers</option><option>Drive store visits</option></select>
          <label style={{ marginTop: 10 }}>Channels</label>
          <div className="grid g2 small" style={{ gap: 6 }}>
            {["Hoardings & bus shelters", "Reels / video feed", "Newspaper", "Reviewers", "Community (Reddit-style)", "Store displays"].map((x) => (
              <label key={x} style={{ fontWeight: 500, color: "var(--ink)", display: "flex", gap: 6, alignItems: "center", margin: 0 }}><input type="checkbox" defaultChecked />{x}</label>
            ))}
          </div>
          <div className="fieldrow" style={{ marginTop: 10 }}><div><label>Flight (sim days)</label><input value={f.flight} onChange={set("flight")} /></div>
            <div><label>Intensity</label><div className="seg">{(["low", "medium", "high"] as const).map((k) => (
              <button key={k} className={f.intensity === k ? "on" : ""} onClick={() => setF({ ...f, intensity: k })}>{k[0].toUpperCase() + k.slice(1)}</button>))}</div></div></div>
          <label>Stocked at</label>
          <div className="row wrap" style={{ gap: 6 }}>
            {allStores.map((s) => <span key={s} className={`chip ${stores.includes(s) ? "teal" : ""}`} style={{ cursor: live ? "pointer" : undefined }}
              onClick={() => live && setStores(stores.includes(s) ? stores.filter((x) => x !== s) : [...stores, s])}>{s}</span>)}
            <span className="chip">ShopKart (online)</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- 2 · content */

function Poster({ a }: { a: Asset }) {
  const news = a[0] === "newspaper";
  return (
    <div className="asset">
      <div className="ph" style={{ background: news ? a[4] : `linear-gradient(180deg,transparent 45%,rgba(0,0,0,.45)),${a[4]}` }}>
        {news && <span style={{ position: "absolute", top: 8, left: 10, color: "#111", font: "700 10px Georgia" }}>THE BENGALURU DAILY</span>}
        <span className="tag" style={{ position: "absolute", top: 8, right: 8, fontSize: 10, padding: "2px 7px", borderRadius: 99, background: "rgba(0,0,0,.45)" }}>{a[0].replace("_", " ")}</span>
        <b style={news ? { color: "#111", textShadow: "none" } : undefined}>{a[2]}</b>
        <span style={{ fontSize: 10, opacity: 0.85, ...(news ? { color: "#111" } : {}) }}>{a[3]}</span>
      </div>
      <div className="meta">
        <div className="row between"><b>{a[1]}</b><span className="xs" style={{ color: "var(--green)" }}>✓ screened</span></div>
        {a[5] ? (a[5] < 0.001 ? <div className="xs muted" style={{ marginTop: 4 }}>salience after Understanding</div> : <>
          <div className="row between xs muted" style={{ marginTop: 4 }}><span>salience</span><span className="mono">{a[5].toFixed(2)}</span></div>
          <div className="bar" style={{ height: 5, marginTop: 3 }}><i style={{ width: `${a[5] * 100}%` }} /></div></>)
          : <div className="xs muted" style={{ marginTop: 4 }}>sent to 4 reviewer agents at launch</div>}
      </div>
    </div>
  );
}

function AddContent({ p, onDone }: { p: StudioProduct; onDone: () => void }) {
  const [kind, setKind] = useState<Kind>("hoarding");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [scenes, setScenes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    const uri = file ? await run("Upload", () => studioApi.upload(p.id, kind, file)) : null;
    const r = await run("Add content", () => studioApi.addCreative(p.id, { kind, title: title || kindTitle(kind),
      ...(kind === "reel" ? { transcript: text, scenes: lines(scenes) } : { text }), ...(uri ? { image_uri: uri } : {}) }));
    setBusy(false);
    if (!r) return;
    toast(r.flagged.length ? `Added · flagged: ${r.flagged.join(", ")} (neutralised, kept as data)` : "Added · screened");
    useStudio.getState().upsert(await studioApi.get(p.id));
    onDone();
  };
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="row between"><h3 style={{ margin: 0 }}>Add content</h3><span className="xs muted">Screened by Model Armor · treated as data, never as instructions</span></div>
      <div className="fieldrow" style={{ marginTop: 10 }}>
        <div><label>Kind</label><select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>{KINDS.map((k) => <option key={k} value={k}>{kindTitle(k)}</option>)}</select></div>
        <div><label>Title</label><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={kindTitle(kind)} /></div>
      </div>
      <label>{kind === "reel" ? "Transcript / voice-over" : kind === "reviewer_kit" ? "Spec sheet and key claims" : "Copy (headline first)"}</label>
      <textarea style={{ minHeight: 70 }} value={text} onChange={(e) => setText(e.target.value)} />
      {kind === "reel" && <><label style={{ marginTop: 10 }}>Scenes (one per line)</label><textarea style={{ minHeight: 70 }} value={scenes} onChange={(e) => setScenes(e.target.value)} /></>}
      <div className="row" style={{ gap: 8, marginTop: 10 }}>
        <input type="file" accept="image/*,application/pdf,text/plain" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button className="btn primary sm" disabled={busy || !(text || file)} onClick={submit}>{busy ? "Adding…" : "Add"}</button>
        <button className="btn sm" onClick={onDone}>Cancel</button>
      </div>
    </div>
  );
}

function StepContent({ p }: { p: StudioProduct }) {
  const [open, setOpen] = useState(false);
  const locked = p.status === "live" || p.status === "ended";
  return (
    <>
      <div className="grid g4" data-testid="content-grid">
        {p.assets.map((a, i) => <Poster a={a} key={i} />)}
        <div className="drop" data-testid="upload-zone" style={{ display: "grid", placeItems: "center", cursor: live && !locked ? "pointer" : undefined }} onClick={() => live && !locked && setOpen(true)}>
          <div><div style={{ fontSize: 22 }}>⇪</div><b>Drop images, PDFs or transcripts</b><div className="xs">Screened by Model Armor · treated as data, never as instructions</div></div>
        </div>
      </div>
      {open && <AddContent p={p} onDone={() => setOpen(false)} />}
      {(p.reelRows.length > 0 || isVisualTest) && (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="row between"><h3 style={{ margin: 0 }}>Reel · “After dark” — transcript &amp; scenes</h3><span className="xs muted">Video is given as transcript + scene descriptions; agents “watch” it in their feeds</span></div>
          <table style={{ marginTop: 8 }}><tbody><tr><th style={{ width: 60 }}>Time</th><th>Scene</th><th>Voice-over / caption</th></tr>
            {p.reelRows.map((r, i) => <tr key={i}><td className="mono">{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td></tr>)}</tbody></table>
        </div>
      )}
    </>
  );
}

/* ---------------------------------------------------------------- 3 · understanding */

function StepUnderstand({ p }: { p: StudioProduct }) {
  const types = useStudio((s) => s.graphTypes);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const r = await run("Understanding", () => studioApi.understand(p.id));
    if (r) useStudio.getState().upsert(await studioApi.get(p.id));
    setBusy(false);
  };
  const rows = p.api ? p.api.creatives.filter((c) => c.kind !== "reviewer_kit").map((c) => ({ title: c.title || kindTitle(c.kind), s: c.stimulus?.salience ?? 0, note: c.stimulus?.description ?? "Run Understanding to describe this creative." }))
    : p.assets.filter((a) => a[5]).map((a) => ({ title: a[1], s: a[5], note: p.creativeNotes[a[0]] ?? "" }));
  return (
    <>
      <div className="grid g21">
        <div className="card" data-testid="claims-card">
          <div className="row between"><h2>Claims</h2><span className="legend"><span><i style={{ background: "var(--red)" }} />High risk</span><span><i style={{ background: "var(--amber)" }} />Watch</span><span><i style={{ background: "var(--green)" }} />OK</span></span></div>
          <p className="small muted">Red and amber claims become watched topics — Insights shows whether agents actually talk about them.</p>
          {live && <div className="row" style={{ gap: 8, marginBottom: 10 }}><button className="btn primary sm" disabled={busy} onClick={go}>{busy ? "Understanding…" : p.understood ? "⟳ Re-run understanding" : "Run understanding"}</button>
            <span className="xs muted">Profile (Flash) · claim risk (Pro) · creative salience · knowledge graph</span></div>}
          <div className="list">
            {p.claims.map((c, i) => (
              <div className="item risk" key={i}><span className={`rdot ${c.risk}`} /><div><b>“{c.text}”</b><div className="small muted">{c.reason}</div></div><span className="xs muted">{c.source}</span></div>
            ))}
          </div>
        </div>
        <div className="card" data-testid="creatives-card"><h3>Creative understanding</h3>
          <div className="list">
            {rows.map((r, i) => (
              <div className="item" key={i}>
                <div className="row between small"><b>{r.title}</b><span className="mono xs">salience {r.s.toFixed(2)}</span></div>
                <div className="bar" style={{ height: 5, margin: "6px 0" }}><i style={{ width: `${r.s * 100}%` }} /></div>
                <div className="xs muted">{r.note}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {p.graph && p.graph.nodes.length ? <GraphView graph={p.graph} types={types} key={p.graph.nodes.length} />
        : <div className="card" style={{ marginTop: 14 }} data-testid="knowledge-graph"><h2>Product knowledge graph</h2><p className="small muted">Run Understanding to build the graph.</p></div>}
    </>
  );
}

/* ---------------------------------------------------------------- 4 · plan */

function useMapSites(): Map<string, MapSite> {
  const [m, setM] = useState<Map<string, MapSite>>(new Map());
  useEffect(() => { void loadSites().then((s) => setM(new Map(s.map((x) => [x.site_id, x])))); }, []);
  return m;
}

const KIND_FIX: Record<string, string> = {};

function StepPlan({ p }: { p: StudioProduct }) {
  const ms = useMapSites();
  const [busy, setBusy] = useState(false);
  const [kinds, setKinds] = useState<Record<string, string>>(KIND_FIX);
  useEffect(() => {
    if (!isVisualTest) return;
    void import("../visual-fixtures/mockup-fixtures.json").then((m) => {
      const f = ((m as { default?: unknown }).default ?? m) as { sites: { id: string; kind: string }[] };
      setKinds(Object.fromEntries(f.sites.map((s) => [s.id, s.kind])));
    });
  }, []);
  const locked = p.status === "live" || p.status === "ended";
  const go = async () => {
    setBusy(true);
    const r = await run("Plan", () => studioApi.plan(p.id));
    if (r) useStudio.getState().upsert(await studioApi.get(p.id));
    setBusy(false);
  };
  const intensity = p.intensity;
  const nd = p.newspaperDays;
  const launchDay = p.launched !== null ? Math.floor(p.launched / 1440) + 1 : null;
  const paper = isVisualTest ? "Half-page on Day 24, 26 and 28 · ~210 readers"
    : nd.length ? `Half-page on ${nd.map((d) => (launchDay ? `Day ${launchDay + d}` : d === 0 ? "launch day" : `day +${d}`)).join(", ")}` : "No newspaper ad in the content";
  const revText = isVisualTest ? `${p.reviewers} reviewer agents get a unit at launch (Tanvi Shah, 3 others)` : `${p.reviewers} reviewer agents get a unit at launch`;
  const comm = isVisualTest ? "News-desk post in r/IndiranagarLife + r/BangaloreTech · stocked at " + p.storeNames.join(", ")
    : `News-desk post in ${p.api?.plan?.community_seed.forum ?? "r/BangaloreTech"} · stocked at ${p.storeNames.join(", ") || "—"}`;
  return (
    <>
      <div className="grid g21">
        <div className="card" data-testid="plan-map-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="row between" style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
            <div><h2 style={{ margin: 0 }}>Automatic hoarding plan</h2><div className="xs muted">Chosen from the last 7 sim days of foot traffic by segment · read-only</div></div>
            <span className="row" style={{ gap: 8 }}>
              {live && !locked && <button className="btn sm primary" disabled={busy} onClick={go}>{busy ? "Planning…" : p.sites.length ? "⟳ Re-plan" : "Generate plan"}</button>}
              <span className="chip" style={{ padding: "1px 8px" }}>{p.sites.length} sites · intensity {intensity}</span>
            </span>
          </div>
          <div style={{ position: "relative", height: 470, background: "#0a0d12" }}><PlanCanvas sites={p.sites} stores={p.storeNames} hex={p.hex} /></div>
        </div>
        <div className="card" data-testid="plan-sites" style={{ maxHeight: 528, overflow: "auto" }}><h3>Sites, facing and why</h3>
          <div className="list">
            {p.sites.length === 0 && <div className="item small muted">No plan yet. Generate it after Understanding — sites are picked automatically from the world's foot traffic.</div>}
            {p.sites.map((s) => {
              const kind = (ms.get(s.site_id)?.kind ?? kinds[s.site_id] ?? "billboard").replace("_", " ");
              return (
                <div className="sitecard" key={s.site_id}>
                  <span className="facing" title={`faces ${FACES[oct(s.facing)]}`}>{ARROWS[oct(s.facing)]}</span>
                  <div><b className="mono small">{s.site_id}</b> <span className="xs muted">{kind} · faces {FACES[oct(s.facing)]}</span>
                    <div className="xs" style={{ marginTop: 3 }}>{s.reason}</div></div>
                  <span className="mono xs" title="estimated target OTS per day">{fmtInt(s.ots)}/day</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="grid g4" data-testid="plan-channels" style={{ marginTop: 14 }}>
        {[["Reels / video feed", `~${fmtInt(p.reel)} matching agents · up to 3 views/day · evening & night sessions`], ["Newspaper", paper], ["Reviewers", revText], ["Community & stores", comm]].map(([h, t]) => (
          <div className="card tight" key={h}><b className="small">{h}</b><div className="xs muted" style={{ marginTop: 4 }}>{t}</div></div>
        ))}
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- 5 · ready */

function StepReady({ p }: { p: StudioProduct }) {
  const nav = useNavigate();
  const reds = useMemo(() => p.claims.filter((c) => c.risk === "red").length, [p.claims]);
  const mark = async () => {
    if (!live) return toast("Marked ready (mockup)");
    const r = await run("Mark ready", () => studioApi.ready(p.id));
    if (r) { useStudio.getState().upsert(r); toast(`${p.name} is ready — launch it from the World dock`); }
  };
  return (
    <div className="grid g21">
      <div className="card" data-testid="ready-summary"><h2>Ready to launch?</h2>
        <p className="small muted">When you launch, the world-engine activates this plan at the next sim minute and stamps the launch time.</p>
        <div className="grid g3" style={{ marginTop: 12 }}>
          {([["Hoardings", p.sites.length], ["Reel audience", "~" + fmtInt(p.reel)], ["Reviewers", p.reviewers], ["Stores", p.storeNames.length],
            ["Newspaper days", isVisualTest ? 3 : p.newspaperDays.length], ["Flight", `${p.flight} sim days`]] as const).map(([l, v]) => <Kpi key={l} l={l} v={v} />)}
        </div>
        <div className="item small" style={{ marginTop: 12 }}>
          {isVisualTest ? "⚠ 2 red claims will be carried by the newspaper ad and the bus shelter. Agents may react to them; Insights tracks it."
            : reds ? `⚠ ${reds} red claim${reds > 1 ? "s" : ""} in this product's content. Agents may react to them; Insights tracks it.` : "No red claims found."}
        </div>
      </div>
      <div className="card"><h3>Status</h3>
        {p.status === "ready" ? <><div className="chip amber" style={{ padding: "3px 10px" }}>Ready — waiting on the World dock</div>
          <p className="small">Launch happens from the World map, one product at a time, with the drop animation.</p>
          <a className="btn primary" data-testid="mark-ready" href={withMode("/world")} onClick={(e) => { e.preventDefault(); nav(withMode("/world")); }}>Go to World to launch →</a></>
          : p.status === "live" ? <><div className="chip green" style={{ padding: "3px 10px" }}>Live since {fmt(p.launched ?? 0)}</div>
            <p className="small"><Link to={withMode("/insights/overview")}>See how it's doing in Insights →</Link></p></>
            : <><button className="btn primary" data-testid="mark-ready" disabled={live && !p.sites.length} onClick={mark}>Mark ready</button>
              {live && !p.sites.length && <p className="xs muted">Generate the plan first.</p>}</>}
      </div>
    </div>
  );
}
