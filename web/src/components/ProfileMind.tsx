import { useEffect, useRef, useState } from "react";
import { useWorld } from "../state/world";
import { getJSON } from "../lib/api";
import { fmt, shortT } from "../lib/time";
import type { AgentView } from "../lib/agentView";

/** Profile tabs 4–6 (U-04): Thoughts, Conversations, Memory. Fixtures in visual-test mode, else the API. */

const STAGES = ["aware", "curious", "researching", "inquiring", "deciding", "purchased"];

interface ThoughtVM { t: number; trig: string; p?: string | null; out: string; txt: string | null; d?: number | null }
interface ConvItemVM { id: string; withName: string; t: number; kind: string; n: number; topics: string }
interface PrepVM { cands: [string, string][]; opening: string; tone: string; withheld: number }
interface DebriefVM { reaction: string; deltas: [string, string][]; intents: string[]; memory: string; imp: number }
interface ConvVM { title: string; self: number; selfName: string; otherName: string; msgs: { sp: number; name: string; tx: string }[]; prep: PrepVM | null; debrief: DebriefVM | null }
interface BeliefVM { p: string; stage: string; att: number; first: string; for: string[]; against: string[]; q: string[] }
interface MemVM { t: number; imp: number; txt: string; k: string }

/* ------------------------------------------------------------------ fixtures (visual-test mode) */

interface FxFeatured {
  id: number;
  thoughts: ThoughtVM[];
  conversation: { id: string; with: number; place: string; t: number; msgs: [number, string][];
    prep: { cands: [string, string][]; opening: string; tone: string };
    debrief: { reaction: string; deltas: [string, string][]; intent: string; memory: string; imp: number } };
  conversations: { id: string; with: number; t: number; kind: string; n: number; topics: string }[];
  memories: { t: number; k: string; imp: number; txt: string }[];
  beliefs: { p: string; stage: string; att: number; first: string; for: string[]; against: string[]; q: string[] }[];
}

const useFeatured = (): FxFeatured | null => {
  const fx = useWorld((s) => s.fixtures);
  return (fx?.featured as unknown as FxFeatured) ?? null;
};
const useFxName = () => {
  const fx = useWorld((s) => s.fixtures);
  return (id: number) => fx?.agents.find((x) => x.id === id)?.name ?? `#${id}`;
};

/* ------------------------------------------------------------------ live API shapes */

interface ApiThought { t: number; kind: string; trigger: { channel: string; session_id?: string; site_id?: string }; text: string; attitude_delta?: number | null; product_id?: string | null }
interface ApiConvItem { session_id: string; with: number | null; with_name?: string; kind: string; t: number; topics: string[]; n_messages: number; rendered: boolean }
interface ApiConv {
  conversation: { session_id: string; place_id?: string | null; t_start: number; topics: string[]; kind: string };
  messages: { seq: number; speaker: number; text: string }[];
  share_plan: { opening: string; tone: string; withheld_count: number; points_to_share: string[]; questions_to_ask: string[]; candidates: { text: string; tag: string }[] } | null;
  debrief: { reaction: string; summary: string; importance: number; intents: string[]; belief_deltas: { subject: string; attitude_delta: number }[] } | null;
  names: Record<string, string | null>;
  store_thoughts?: { seq: number; thought: string; decision?: { chosen?: { text: string; kind: string }; withheld?: string[] } }[];
  survey_items?: { kind: string; payload: Record<string, any> }[];
}
interface ApiBelief { subject: string; stage: string; attitude: number; first_heard: { channel: string; t: number } | null; reasons_for: string[]; reasons_against: string[]; open_questions: string[] }
interface ApiMem { t: number; kind: string; importance: number; text: string }

function useApi<T>(path: string | null): T | null {
  const [v, setV] = useState<{ path: string; data: T } | null>(null);
  useEffect(() => {
    if (!path) return;
    let on = true;
    getJSON<T>(path).then((data) => on && setV({ path, data })).catch(() => on && setV({ path, data: [] as unknown as T }));
    return () => {
      on = false;
    };
  }, [path]);
  return v && v.path === path ? v.data : null;
}

const subjectName = (s: string) => s.split(":").slice(1).join(":") || s;
const signed = (d: number) => `${d > 0 ? "+" : ""}${d.toFixed(2)}`;

/* ------------------------------------------------------------------ Thoughts */

export function ThoughtsTab({ a }: { a: AgentView }) {
  const source = useWorld((s) => s.source);
  const fx = useWorld((s) => s.fixtures);
  const feat = useFeatured();
  const api = useApi<ApiThought[]>(source === "live" ? `/agents/${a.id}/thoughts?limit=50` : null);
  let th: ThoughtVM[] = [];
  if (source !== "live") {
    th = a.id === feat?.id ? feat.thoughts : ((fx?.agents.find((x) => x.id === a.id)?.thoughts ?? []) as ThoughtVM[]);
  } else {
    th = (api ?? []).map((x) => ({
      t: x.t, p: x.product_id, out: x.kind, txt: x.text, d: x.attitude_delta,
      trig: x.trigger.channel === "conversation" ? "Conversation" : x.trigger.channel === "reflection" ? "Night reflection" : x.trigger.channel,
    }));
  }
  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>Private thoughts — never shared with other agents unless {a.name.split(" ")[0]} says them out loud.</p>
      <div className="list" data-testid="thought-list">{th.length ? th.map((x, i) => <Thought key={i} x={x} />)
        : <div className="item muted small">{source === "live" && !api ? "Loading…" : "No thoughts yet."}</div>}</div>
    </>
  );
}

function ProductDot({ id }: { id?: string | null }) {
  const p = useWorld((s) => s.products.find((q) => q.id === id));
  if (!p) return null;
  return <><span className="pdot" style={{ background: p.hex, width: 7, height: 7, marginRight: 4 }} />{p.name} · </>;
}

function Thought({ x }: { x: ThoughtVM }) {
  return (
    <div className="thought">
      <div className="meta"><span>{shortT(x.t)} · {x.trig}</span><span className="privtag">PRIVATE</span></div>
      {x.txt ? `“${x.txt}”` : <span className="muted">{x.out} · passed by without a thought</span>}
      <div className="xs muted" style={{ marginTop: 4 }}><ProductDot id={x.p} />{x.out}{x.d ? ` · attitude ${signed(x.d)}` : ""}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ Conversations */

export function ConversationsTab({ a }: { a: AgentView }) {
  const source = useWorld((s) => s.source);
  const feat = useFeatured();
  const name = useFxName();
  const [open, setOpen] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open) detailRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [open]);
  const list = useApi<ApiConvItem[]>(source === "live" ? `/agents/${a.id}/conversations` : null);
  let items: ConvItemVM[] = [];
  let conv: ConvVM | null = null;
  const first = a.name.split(" ")[0];
  if (source !== "live") {
    if (feat && a.id === feat.id) {
      items = feat.conversations.map((c) => ({ id: c.id, withName: name(c.with), t: c.t, kind: c.kind, n: c.n, topics: c.topics }));
      const c = feat.conversation;
      conv = {
        title: `${fmt(c.t)} · ${c.place}`, self: a.id, selfName: first, otherName: name(c.with).split(" ")[0],
        msgs: c.msgs.map(([sp, tx]) => ({ sp, name: name(sp).split(" ")[0], tx })),
        prep: { cands: c.prep.cands, opening: c.prep.opening, tone: c.prep.tone, withheld: c.prep.cands.filter(([, d]) => d.startsWith("withhold")).length },
        debrief: { reaction: c.debrief.reaction, deltas: c.debrief.deltas, intents: [c.debrief.intent], memory: c.debrief.memory, imp: c.debrief.imp },
      };
    }
  } else {
    items = (list ?? []).map((c) => ({ id: c.session_id, withName: c.with_name ?? `#${c.with}`, t: c.t, kind: c.rendered ? c.kind : "unrendered",
      n: c.n_messages, topics: c.rendered ? c.topics.join(" · ") : `Short chat about ${topicLabel(c.topics[0])} · summary only` }));
  }
  // The newest written-out chat starts open (as in the mockup); clicking a row toggles it inline.
  const initial = items.find((c) => c.kind !== "unrendered")?.id ?? null;
  const pick = open === "" ? null : items.some((c) => c.id === open) ? open : initial;
  const detail = useApi<ApiConv>(source === "live" && pick && items.find((c) => c.id === pick)?.kind !== "unrendered" ? `/conversations/${pick}?as_agent=${a.id}` : null);
  if (source === "live" && detail && !Array.isArray(detail)) conv = liveConv(detail, a.id, first);
  const sel = items.find((c) => c.id === pick) ?? null;
  if (source !== "live" && feat && pick !== feat.conversation.id) conv = null;   // fixtures carry one transcript
  return (
    <>
      <div className="list" data-testid="conversation-list">
        {items.length ? items.map((c) => (
          <div className="item" key={c.id}>
            <button type="button" aria-expanded={pick === c.id} onClick={() => setOpen(pick === c.id ? "" : c.id)}
              style={{ cursor: "pointer", width: "100%", textAlign: "left", border: 0, background: "transparent", color: "inherit", padding: 0 }}>
              <div className="row between"><b>{pick === c.id ? "▾" : "▸"} {c.kind === "focus_group" ? "Focus group" : c.kind === "store" ? `store visit · ${c.withName}` : `with ${c.withName}`}</b><span className="xs muted">{shortT(c.t)} · {c.n ? `${c.n} messages` : "Brief interaction"}</span></div>
              <div className="xs muted">{c.topics}</div>
            </button>
          </div>
        )) : <div className="item muted small">{source === "live" && !list ? "Loading…" : "No conversations yet."}</div>}
      </div>
      {sel && <div ref={detailRef}>{sel.kind === "unrendered"
        ? <p className="small muted" data-testid="conversation-summary" style={{ marginTop: 16 }}>{first} and {sel.withName.split(" ")[0]} chatted briefly; only this summary was kept, so there is no word-for-word transcript.</p>
        : conv ? <Transcript c={conv} /> : <p className="small muted">{detail ? "The transcript could not be loaded. Close and reopen to retry." : "Loading conversation…"}</p>}</div>}
    </>
  );
}

/** "product:pixel-10a" → "pixel-10a"; empty → small talk. */
function topicLabel(t: string | undefined): string {
  return t ? t.replace(/^product:/, "") : "small talk";
}

/** Messages with THIS agent's own private thoughts interleaved (store visits: before each turn; focus groups: before
 * each of their own lines, then their private ballots). Other people's private items never reach the client. */
function interleave(d: ApiConv, self: number, nm: (id: number) => string): { sp: number; name: string; tx: string; priv?: boolean }[] {
  const out: { sp: number; name: string; tx: string; priv?: boolean }[] = [];
  const st = new Map((d.store_thoughts ?? []).map((x) => [x.seq, x]));
  const sv = (d.survey_items ?? []).filter((x) => x.kind === "survey_thought").map((x) => String(x.payload.text));
  let k = 0;
  for (const m of d.messages) {
    const speaker = typeof m.speaker === "number" ? m.speaker : -1;
    const t = st.get(m.seq);
    if (t && speaker === self) out.push({ sp: self, name: nm(self), tx: `thinks: ${t.thought}${t.decision?.withheld?.length ? ` (keeps to self: ${t.decision.withheld.join("; ")})` : ""}`, priv: true });
    if (speaker === self && sv[k]) out.push({ sp: self, name: nm(self), tx: `thinks: ${sv[k++]}`, priv: true });
    out.push({ sp: speaker, name: speaker === -1 ? "Moderator" : nm(speaker), tx: m.text });
  }
  for (const a of (d.survey_items ?? []).filter((x) => x.kind === "survey_answer")) {
    out.push({ sp: self, name: nm(self), tx: `private ballot ${a.payload.question_id}: ${Array.isArray(a.payload.answer) ? a.payload.answer.join(", ") : a.payload.answer} — ${a.payload.reason}`, priv: true });
  }
  return out;
}

function liveConv(d: ApiConv, self: number, selfName: string): ConvVM {
  const nm = (id: number) => (d.names[String(id)] ?? `#${id}`).split(" ")[0];
  const other = Object.keys(d.names).map(Number).find((x) => x !== self) ?? -1;
  const sp = d.share_plan;
  const shared = new Set(sp?.points_to_share ?? []);
  const asked = new Set(sp?.questions_to_ask ?? []);
  const db = d.debrief;
  return {
    title: `${fmt(d.conversation.t_start)}${d.conversation.place_id ? ` · ${d.conversation.place_id}` : ""}`,
    self, selfName, otherName: nm(other),
    msgs: interleave(d, self, nm),
    prep: sp ? { cands: (sp.candidates ?? []).map((c) => [c.text, shared.has(c.text) ? "share" : asked.has(c.text) ? "ask" : `withhold (${c.tag})`] as [string, string]),
      opening: sp.opening, tone: sp.tone, withheld: sp.withheld_count } : null,
    debrief: db ? { reaction: db.reaction, deltas: db.belief_deltas.map((x) => [subjectName(x.subject), `attitude ${signed(x.attitude_delta)}`] as [string, string]),
      intents: db.intents, memory: db.summary, imp: db.importance } : null,
  };
}

function Transcript({ c }: { c: ConvVM }) {
  return (
    <div data-testid="conversation-detail">
      <h3 style={{ marginTop: 16 }}>{c.title}</h3>
      {c.prep ? (
        <div className="privbox" data-testid="private-prep">
          <div className="row between"><b>Before · {c.selfName}'s private prep</b><span className="privtag">PRIVATE</span></div>
          <div className="list small" style={{ marginTop: 6 }}>{c.prep.cands.map(([t, d], i) => (
            <div className="row between" style={{ gap: 10 }} key={i}><span>{t}</span>
              <span className={`xs ${d.startsWith("withhold") ? "" : "muted"}`} style={d.startsWith("withhold") ? { color: "var(--private)" } : undefined}>{d}</span></div>
          ))}</div>
          <div className="xs muted" style={{ marginTop: 6 }}>Share plan → opening: “{c.prep.opening}” · tone: {c.prep.tone} · {c.prep.withheld} thought{c.prep.withheld === 1 ? "" : "s"} withheld</div>
        </div>
      ) : <div className="privbox xs muted">{c.otherName}'s private prep and debrief are shown only in their own profile.</div>}
      <div className="trans" style={{ margin: "10px 0" }}>
        {c.msgs.map((m, i) => (m as { priv?: boolean }).priv
          ? <div className="tmsg b" key={i} style={{ border: "1.5px dashed var(--private)", background: "transparent", color: "var(--private)" }}><span className="who">{m.name} · <span className="privtag">PRIVATE THOUGHT</span></span>{m.tx}</div>
          : <div className={`tmsg ${m.sp === c.self ? "b" : "a"}`} key={i}><span className="who">{m.name} · {i + 1}</span>{m.tx}</div>)}
      </div>
      {c.debrief && (
        <div className="privbox" data-testid="private-debrief">
          <div className="row between"><b>After · {c.selfName}'s private debrief</b><span className="privtag">PRIVATE</span></div>
          <p style={{ margin: "6px 0" }}>“{c.debrief.reaction}”</p>
          {c.debrief.deltas.map(([p, d], i) => <div className="xs" key={i}>• {p}: {d}</div>)}
          {c.debrief.intents.map((x, i) => <div className="xs" style={{ marginTop: 4 }} key={i}>• New intent: {x}</div>)}
          <div className="xs muted" style={{ marginTop: 6 }}>Episodic memory saved (importance {c.debrief.imp}): “{c.debrief.memory}”</div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Memory */

export function MemoryTab({ a }: { a: AgentView }) {
  const source = useWorld((s) => s.source);
  const products = useWorld((s) => s.products);
  const feat = useFeatured();
  const mems = useApi<ApiMem[]>(source === "live" ? `/agents/${a.id}/memories?limit=60` : null);
  const detail = useApi<{ beliefs: ApiBelief[] }>(source === "live" ? `/agents/${a.id}` : null);
  const beliefs = detail && !Array.isArray(detail) ? detail.beliefs : null;
  let bl: BeliefVM[] = [];
  let mem: MemVM[] = [];
  if (source !== "live") {
    if (feat && a.id === feat.id) {
      bl = feat.beliefs;
      mem = feat.memories;
    } else {
      bl = products.filter((p) => p.status !== "draft").map((p) => {
        const b = a.beliefs[p.id];
        return { p: p.id, stage: b?.stage ?? "unaware", att: b?.att ?? 0, first: "—", for: [], against: [], q: [] };
      });
    }
  } else {
    bl = (beliefs ?? []).map((b) => ({ p: subjectName(b.subject), stage: b.stage, att: b.attitude,
      first: b.first_heard ? `${b.first_heard.channel.replace("_", " ")} · ${fmt(b.first_heard.t)}` : "—",
      for: b.reasons_for, against: b.reasons_against, q: b.open_questions }));
    mem = (mems ?? []).map((m) => ({ t: m.t, imp: m.importance, txt: m.text, k: m.kind }));
  }
  return (
    <>
      <h3>Beliefs</h3>
      <div className="list" data-testid="belief-list">
        {bl.length ? bl.map((b) => {
          const p = products.find((q) => q.id === b.p);
          const hex = p?.hex ?? "var(--teal)";
          const si = STAGES.indexOf(b.stage);
          return (
            <div className="belief" key={b.p}>
              <div className="row between"><span><span className="pdot" style={{ background: hex, marginRight: 6 }} /><b>{p?.name ?? b.p}</b></span>
                <span className="xs">{b.stage === "unaware" ? <span className="muted">unaware</span> : <>{b.stage} · attitude <b className="mono">{signed(b.att)}</b></>}</span></div>
              <div className="stagebar">{STAGES.map((s, i) => <span key={s} className={i <= si ? "on" : ""} style={i <= si ? { background: hex } : undefined} />)}</div>
              {b.stage !== "unaware" && <>
                <div className="xs muted">First heard: {b.first}</div>
                {b.for.length > 0 && <div className="xs">👍 {b.for.join(" · ")}</div>}
                {b.against.length > 0 && <div className="xs">👎 {b.against.join(" · ")}</div>}
                {b.q.length > 0 && <div className="xs">❓ {b.q.join(" · ")}</div>}
              </>}
            </div>
          );
        }) : <div className="item muted small">No beliefs about products yet.</div>}
      </div>
      <h3 style={{ marginTop: 16 }}>Episodic memory</h3>
      <div data-testid="memory-list">{mem.map((m, i) => (
        <div className="mem" key={i}><span className="mono xs muted">{m.t > 0 ? shortT(m.t) : "seed"}<br />imp {m.imp}</span>
          <span>{m.txt}<div className="xs muted">{m.k.replace("_", " ")}</div></span></div>
      ))}</div>
      <p className="xs muted">Only {a.name.split(" ")[0]}'s own memories. Retrieval = recency × importance × relevance.</p>
    </>
  );
}
