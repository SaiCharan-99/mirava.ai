import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../../components/Shell";
import { getJSON } from "../../lib/api";
import { getLiveState, mmss, secondsToStart, type Counts, type LiveState } from "../../lib/focus";
import { isVisualTest, withMode } from "../../lib/visualTest";
import { avatarColor } from "../InsightsPage";
import { SessionsCol } from "./SessionsCol";

interface Doc { survey_id: string; title: string; mode: string; status: string; start_at_t?: number | null; start_label?: string | null; wave?: number; counts?: Counts; max_participants?: number; venue_name?: string; error?: string }

/** Countdown to a focus group: one shared ring timer, who is coming, and the private reasons behind each reply. */
export function FocusWaitPage() {
  const { surveyId = "" } = useParams();
  const nav = useNavigate();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [live, setLive] = useState<LiveState | null>(null);
  const [err, setErr] = useState("");
  const [, tick] = useState(0);
  useEffect(() => {
    if (isVisualTest) return;
    let stop = false;
    const load = async () => {
      try {
        const d = await getJSON<Doc>(`/surveys/${surveyId}?include_private=1`);
        if (stop) return;
        setDoc(d); setErr("");
        if (["recruiting", "gathering", "in_session", "finishing"].includes(d.status)) setLive(await getLiveState(surveyId).catch(() => null));
      } catch (e) { if (!stop) setErr(e instanceof Error ? e.message : String(e)); }
      if (!stop) setTimeout(() => void load(), 3000);
    };
    void load();
    const h = setInterval(() => tick((n) => n + 1), 250);
    return () => { stop = true; clearInterval(h); };
  }, [surveyId]);
  if (err && !doc) return <div className="page"><PageTitle title="Focus group" sub="" /><div className="card"><b className="small">Couldn't load this session</b><div className="xs muted">{err}</div><button className="btn sm" style={{ marginTop: 8 }} onClick={() => location.reload()}>↻ Retry</button></div></div>;
  if (!doc) return <div className="page"><PageTitle title="Focus group" sub="Loading…" /></div>;
  const start = live?.start_at_t ?? doc.start_at_t ?? null;
  const total = 30 / 0.4;                                    // ring = default lead (30 sim min) in real seconds
  const left = secondsToStart(start);
  const frac = Math.max(0, Math.min(1, left / total));
  const c = live?.counts ?? doc.counts ?? { invited: 0, replied: 0, accepted: 0, waitlist: 0, walking: 0, arrived: 0 };
  const started = left <= 0 || ["in_session", "finishing", "completed"].includes(live?.status ?? doc.status);
  const top = Math.max(1, c.invited);
  const rows: [string, number][] = [["Invited", c.invited], ["Replied", c.replied], ["Said yes", c.accepted], ["Walking there", c.walking], ["Arrived", c.arrived]];
  const replies = live?.replies ?? [];
  return (
    <div className="page" data-testid="focus-wait">
      <PageTitle title={doc.title} sub={`${doc.mode === "focus_group" ? "Focus group" : "Survey"} · ${doc.venue_name ?? "Research Lounge"}, 100 Feet Road · wave ${doc.wave ?? 1}`}
        right={<button className="btn" onClick={() => nav(withMode("/insights/focus"))}>← Focus groups</button>} />
      {doc.status === "cancelled" && <div className="card" style={{ marginBottom: 14 }}><b>Cancelled.</b> <span className="xs muted">{doc.error ?? ""}</span></div>}
      <div className="grid" style={{ gridTemplateColumns: "1fr 1.2fr 340px", alignItems: "start" }}>
        <div className="card" style={{ textAlign: "center" }}>
          <div className="xs muted" style={{ letterSpacing: ".08em", fontWeight: 700 }}>{started ? "STARTED" : "STARTS IN"}</div>
          <div className="cd-ring" data-testid="countdown-ring"><svg width="250" height="250"><circle cx="125" cy="125" r="110" fill="none" stroke="var(--panel3)" strokeWidth="12" />
            <circle cx="125" cy="125" r="110" fill="none" stroke="var(--teal)" strokeWidth="12" strokeLinecap="round" strokeDasharray="691" strokeDashoffset={String(691 * (1 - frac))} /></svg>
            <div className="num"><div><b data-testid="countdown-time">{mmss(left)}</b><span className="xs muted">sim time {doc.start_label ?? "—"}</span></div></div></div>
          {started && <button className="btn primary" data-testid="go-to-room" style={{ fontSize: 16, padding: "12px 18px" }} onClick={() => nav(withMode(`/insights/focus/${surveyId}/room`))}>Go to the Survey Room →</button>}
          <div className="xs muted" style={{ marginTop: 10 }}>Same timer for every viewer: it counts down to the session's start on the world clock.</div>
        </div>
        <div className="card"><h3>Who is coming</h3>
          {rows.map(([l, v]) => <div key={l} className="funnel-row"><span>{l}</span><div className="bar"><i style={{ width: `${(100 * v) / top}%` }} /></div><b className="mono">{v}</b></div>)}
          <div className="xs muted">{doc.max_participants ?? "—"} seats · extra yeses go on a waitlist ({c.waitlist}) · people walk from wherever they are on the map</div>
          <h3 style={{ marginTop: 16 }}>Replies <span className="privtag">PRIVATE REASONS</span></h3>
          <div className="list small" data-testid="replies" style={{ maxHeight: 280, overflow: "auto" }}>
            {replies.map((r) => (
              <div key={r.agent_id} className="item row" style={{ gap: 10 }}>
                <div className="avatar" style={{ background: avatarColor(r.agent_id), width: 26, height: 26, fontSize: 10 }}>{(r.name ?? "?").split(" ").map((x) => x[0]).join("").slice(0, 2)}</div>
                <div><b>{(r.name ?? `#${r.agent_id}`).split(" ")[0]}{r.age ? `, ${r.age}` : ""}</b> <span className={`chip ${r.rsvp === "accepted" || r.rsvp === "attended" ? "green" : r.rsvp === "waitlist" ? "amber" : ""}`} style={{ padding: "0 7px" }}>{r.rsvp === "accepted" || r.rsvp === "attended" ? "coming" : r.rsvp}</span>
                  {r.channel && <span className="xs muted"> · via {r.channel.replace("_", " ")}</span>}
                  {r.reason && <div className="xs" style={{ color: "var(--private)" }}>“{r.reason}”</div>}</div>
              </div>
            ))}
            {!replies.length && <div className="xs muted">Waiting for replies… people read the invite at their next phone session.</div>}
          </div>
        </div>
        <SessionsCol cur={surveyId} />
      </div>
    </div>
  );
}
