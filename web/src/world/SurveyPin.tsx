import { useEffect, useRef, useState } from "react";
import { useWorld } from "../state/world";
import { useActiveSurvey } from "../state/activeSurvey";
import { mmss, secondsToStart } from "../lib/focus";
import { PX_PER_M, worldRef } from "./ref";

/** World overlay (addendum B9): "Research Lounge · n/N" pin at the venue while a survey is active, and 📋 on agents
 * walking there. Positions follow the camera every frame; nothing is drawn when no survey is active. */
export function SurveyPin() {
  const pin = useWorld((s) => s.surveyPin);
  const trips = useWorld((s) => s.surveyTrips);
  const active = useActiveSurvey((s) => s.active);
  const host = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ pin: { x: number; y: number } | null; trips: { id: number; x: number; y: number }[] }>({ pin: null, trips: [] });
  useEffect(() => {
    if (!pin) return;
    let raf = 0;
    const loop = () => {
      const sc = worldRef.scene;
      const box = host.current?.parentElement?.getBoundingClientRect();
      if (sc && box) {
        const p = sc.clientOf(pin.x * PX_PER_M, pin.y * PX_PER_M);
        const tr = trips.slice(0, 100).map((id) => {
          const a = sc.agentPx(id);
          if (!a) return null;
          const c = sc.clientOf(a.x, a.y);
          return { id, x: c.x - box.left, y: c.y - box.top };
        }).filter((x): x is { id: number; x: number; y: number } => !!x);
        setPos({ pin: { x: p.x - box.left, y: p.y - box.top }, trips: tr });
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [pin, trips]);
  if (!pin) return <div ref={host} style={{ display: "none" }} />;
  return (
    <div ref={host} data-testid="survey-pin" style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }}>
      {pos.trips.map((t) => <span key={t.id} style={{ position: "absolute", left: t.x + 4, top: t.y - 22, fontSize: 11 }}>📋</span>)}
      {pos.pin && (
        <div className="chip teal" style={{ position: "absolute", left: pos.pin.x, top: pos.pin.y, transform: "translate(-50%,-130%)", pointerEvents: "auto", boxShadow: "0 4px 14px rgba(0,0,0,.35)" }}>
          📍 {pin.name} · {pin.arrived}/{pin.expected} {pin.status === "in_session" ? "in session" : "arrived"}
          {(pin.status === "recruiting" || pin.status === "gathering") && active?.survey_id === pin.survey_id && <> · starts in <b className="mono">{mmss(secondsToStart(active.start_at_t))}</b></>}
        </div>
      )}
    </div>
  );
}
