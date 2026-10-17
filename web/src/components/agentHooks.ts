import { useEffect, useState } from "react";
import { useWorld } from "../state/world";
import { useWatch } from "../state/watch";
import { fromDetail, fromFixture, type AgentView } from "../lib/agentView";
import { getAgent } from "../lib/api";

/** Agent view for an id: fixtures before /live (and in visual-test mode), else GET /api/agents/{id}. */
export function useAgentView(id: number | null): { view: AgentView | null; error: boolean } {
  const source = useWorld((s) => s.source);
  const fx = useWorld((s) => s.fixtures);
  const watched = useWatch((s) => (id === null ? false : s.ids.includes(id)));
  const [live, setLive] = useState<{ id: number; v: AgentView | null; err: boolean } | null>(null);
  useEffect(() => {
    if (id === null || source !== "live") return;
    let on = true;
    getAgent(id)
      .then((d) => on && setLive({ id, v: fromDetail(d, false), err: false }))
      .catch(() => on && setLive({ id, v: null, err: true }));
    return () => {
      on = false;
    };
  }, [id, source]);
  if (id === null) return { view: null, error: false };
  if (source !== "live") {
    const v = fx ? fromFixture(fx, id, watched) : null;
    return { view: v, error: false };
  }
  if (!live || live.id !== id) return { view: null, error: false };
  return { view: live.v ? { ...live.v, watch: watched } : null, error: live.err };
}
