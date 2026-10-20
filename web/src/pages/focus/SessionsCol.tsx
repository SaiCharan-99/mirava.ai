import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listSessions, mmss, secondsToStart, sessionRoute, type SessionRow } from "../../lib/focus";
import { isVisualTest, withMode } from "../../lib/visualTest";

/** Sessions list (right column on every focus-group page): each card opens builder, countdown, room or results. */
export function SessionsCol({ cur }: { cur?: string }) {
  const nav = useNavigate();
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [err, setErr] = useState("");
  const [, tick] = useState(0);
  useEffect(() => {
    if (isVisualTest) { setRows([]); return; }
    let live = true;
    const load = () => listSessions().then((r) => { if (live) { setRows(r); setErr(""); } }).catch((e: unknown) => live && setErr(e instanceof Error ? e.message : String(e)));
    void load();
    const h = setInterval(() => { void load(); tick((n) => n + 1); }, 5000);
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => { live = false; clearInterval(h); clearInterval(t); };
  }, []);
  const label = (s: SessionRow) => s.status === "draft" ? <span className="chip">draft</span>
    : s.status === "recruiting" || s.status === "gathering" ? <span className="chip teal">starts {mmss(secondsToStart(s.start_at_t))}</span>
    : s.status === "in_session" || s.status === "finishing" ? <span className="chip green"><span className="dotlive" />live</span>
    : s.status === "cancelled" ? <span className="chip">cancelled</span> : <span className="chip">done</span>;
  return (
    <div className="card" data-testid="sessions-list">
      <div className="row between"><h3 style={{ margin: 0 }}>Sessions</h3><span className="xs muted">{rows ? `${rows.length} total` : ""}</span></div>
      {err && <div className="xs" style={{ color: "var(--red)", marginTop: 8 }}>Couldn't load sessions: {err} <button className="btn sm" onClick={() => location.reload()}>Retry</button></div>}
      {!err && rows === null && <div className="xs muted" style={{ marginTop: 8 }}>Loading…</div>}
      {!err && rows !== null && rows.length === 0 && <div className="xs muted" style={{ marginTop: 8 }}>No sessions yet. Launch one with the builder.</div>}
      <div className="sess" style={{ marginTop: 10, maxHeight: 640, overflow: "auto" }}>
        {(rows ?? []).filter((s) => s.status !== "draft").map((s) => (
          <button key={s.survey_id} data-testid={`session-${s.survey_id}`} className={cur === s.survey_id ? "on" : ""} onClick={() => nav(withMode(sessionRoute(s.survey_id, s.status)))}>
            <div className="row between" style={{ gap: 8 }}><span className="ttl">{s.title}</span>{label(s)}</div>
            <div className="xs muted" style={{ marginTop: 3 }}>{s.mode === "focus_group" ? "Focus group" : "Survey (written)"}{s.product_name ? ` · ${s.product_name}` : ""}
              {" · "}{s.n_attended != null ? `${s.n_attended} people` : `up to ${s.max_participants ?? "—"}`}{s.start_label ? ` · ${s.start_label.split(" · ")[0]}` : ""}{(s.wave ?? 1) > 1 ? ` · wave ${s.wave}` : ""}</div>
          </button>
        ))}
      </div>
      <div className="note">Each session is a card. Live and upcoming ones open the room or the countdown; finished ones open their results. Running a session again makes a new wave with the same people.</div>
    </div>
  );
}
