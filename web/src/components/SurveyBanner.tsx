import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bannerKind, dismissDone, dismissedDone, mmss, secondsToStart } from "../lib/focus";
import { isVisualTest, withMode } from "../lib/visualTest";
import { startActivePoll, useActiveSurvey } from "../state/activeSurvey";

/** Sticky bar on every page while a focus group is counting down, live, or just finished. */
export function SurveyBanner() {
  const nav = useNavigate();
  const a = useActiveSurvey((s) => s.active);
  const inRoom = useActiveSurvey((s) => s.inRoom);
  const [, tick] = useState(0);
  const [hidden, setHidden] = useState(0);
  useEffect(() => { startActivePoll(); }, []);
  useEffect(() => { const h = setInterval(() => tick((n) => n + 1), 250); return () => clearInterval(h); }, []);
  const kind = bannerKind(a, dismissedDone);
  if (!a || !kind || isVisualTest || hidden < 0) return null;
  const c = a.counts;
  const what = a.mode === "survey" ? "survey" : "focus group";
  if (kind === "countdown") {
    const left = secondsToStart(a.start_at_t);
    return (
      <div className="fg-banner" data-testid="survey-banner" data-kind="countdown">
        📋 <b>{a.title}</b> {what} {left > 0 ? <>starts in <span className="t mono">{mmss(left)}</span></> : <>is about to start</>}
        <span className="muted"> · {c.accepted} accepted · {c.walking} walking to the Research Lounge</span>
        <span style={{ flex: 1 }} />
        <button className="btn sm" onClick={() => nav(withMode(`/insights/focus/${a.survey_id}/wait`))}>View countdown</button>
      </div>
    );
  }
  if (kind === "live") {
    const q = (a.q_index ?? -1) >= 0 && a.n_questions ? ` · Q${(a.q_index ?? 0) + 1}/${a.n_questions}` : "";
    return (
      <div className="fg-banner live" data-testid="survey-banner" data-kind="live">
        <span className="dotlive" /> <b>{a.title}</b> is live in the Survey Room<span className="t mono">{q}</span>
        <span className="muted"> · {a.viewers ?? 0} watching</span>
        <span style={{ flex: 1 }} />
        {inRoom === a.survey_id
          ? <button className="btn sm" onClick={() => nav(-1)}>Exit room</button>
          : <button className="btn sm primary" onClick={() => nav(withMode(`/insights/focus/${a.survey_id}/room`))}>Enter the Survey Room →</button>}
      </div>
    );
  }
  return (
    <div className="fg-banner" data-testid="survey-banner" data-kind="done">
      ✅ <b>{a.title}</b> finished{a.attended != null ? ` · ${a.attended} took part` : ""}
      <span style={{ flex: 1 }} />
      <button className="btn sm primary" onClick={() => { dismissDone(a.survey_id); setHidden((n) => n + 1); nav(withMode(`/insights/focus/${a.survey_id}/results`)); }}>See results →</button>
    </div>
  );
}
