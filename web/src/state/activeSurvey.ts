import { create } from "zustand";
import { getActive, type ActiveSurvey, type Counts } from "../lib/focus";
import { isVisualTest } from "../lib/visualTest";

/** The one active focus group / survey, for the banner, countdown and room (fed by /live `survey` events, with a
 *  5 s poll of /api/surveys/active as the fallback). */
interface ActiveStore {
  active: ActiveSurvey | null;
  inRoom: string | null;
  setFromEvent: (e: Record<string, unknown>) => void;
  setViewers: (id: string, n: number) => void;
  refresh: () => Promise<void>;
  setInRoom: (id: string | null) => void;
}

export const useActiveSurvey = create<ActiveStore>((set, get) => ({
  active: null,
  inRoom: null,
  setFromEvent: (e) => {
    const cur = get().active;
    const id = String(e.survey_id ?? "");
    if (!id) return;
    const status = String(e.status ?? cur?.status ?? "recruiting") as ActiveSurvey["status"];
    if (status === "cancelled") { set({ active: null }); return; }
    set({ active: {
      ...(cur && cur.survey_id === id ? cur : {}),
      survey_id: id, title: String(e.title ?? (cur?.survey_id === id ? cur.title : "Focus group")), status,
      mode: (e.mode as string | undefined) ?? cur?.mode,
      start_at_t: e.start_at_t != null ? Number(e.start_at_t) : cur?.start_at_t ?? null,
      counts: (e.counts as Counts | undefined) ?? cur?.counts ?? { invited: 0, replied: 0, accepted: 0, waitlist: 0, walking: 0, arrived: 0 },
      q_index: e.q_index != null ? Number(e.q_index) : cur?.q_index, n_questions: e.n_questions != null ? Number(e.n_questions) : cur?.n_questions,
      viewers: e.viewers != null ? Number(e.viewers) : cur?.viewers, attended: e.attended != null ? Number(e.attended) : cur?.attended,
    } });
  },
  setViewers: (id, n) => { const a = get().active; if (a && a.survey_id === id) set({ active: { ...a, viewers: n } }); },
  refresh: async () => {
    if (isVisualTest) return;
    try { set({ active: await getActive() }); } catch { /* keep the last known state */ }
  },
  setInRoom: (id) => set({ inRoom: id }),
}));

let polling = false;
/** Start the fallback poll once (5 s). */
export function startActivePoll(): void {
  if (polling || isVisualTest) return;
  polling = true;
  void useActiveSurvey.getState().refresh();
  setInterval(() => { void useActiveSurvey.getState().refresh(); }, 5000);
}
