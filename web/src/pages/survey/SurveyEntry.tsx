import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getJSON } from "../../lib/api";
import { isVisualTest, withMode } from "../../lib/visualTest";

interface SurveyRow { survey_id: string; title: string; status: string; wave: number; mode: string }

/** Survey Room entry (addendum B9): a button + a small "Past surveys" menu inside the Polls tab's page-actions. */
export function SurveyEntry() {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<SurveyRow[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open && !isVisualTest) void getJSON<SurveyRow[]>("/surveys").then(setRows).catch(() => setRows([])); }, [open]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  return (
    <div ref={ref} className="row" style={{ gap: 0, position: "relative" }} data-testid="survey-entry">
      <button className="chip teal" style={{ cursor: "pointer", borderRadius: "999px 0 0 999px" }} data-testid="survey-room-button"
        onClick={() => nav(withMode("/insights/polls/survey/new"))}>Survey Room</button>
      <button className="chip teal" title="Past surveys" aria-label="Past surveys" aria-haspopup="menu" aria-expanded={open}
        style={{ cursor: "pointer", borderRadius: "0 999px 999px 0", marginLeft: 1, padding: "3px 7px" }} onClick={() => setOpen((o) => !o)}>▾</button>
      {open && (
        <div className="card" role="menu" style={{ position: "absolute", right: 0, top: 40, zIndex: 30, width: 300, padding: 8 }}>
          <div className="xs muted" style={{ padding: "2px 6px 6px" }}>Past surveys</div>
          {rows.length === 0 && <div className="xs muted" style={{ padding: 6 }}>No surveys yet.</div>}
          {rows.slice(0, 8).map((r) => (
            <button key={r.survey_id} role="menuitem" className="item" style={{ display: "block", width: "100%", textAlign: "left", marginBottom: 4 }}
              onClick={() => nav(withMode(`/insights/polls/survey/${r.survey_id}`))}>
              <b className="small">{r.title}</b><div className="xs muted">{r.mode === "focus_group" ? "Focus group" : "Survey"} · wave {r.wave} · {r.status}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
