import { useWorld, type HlMoment, type Highlights } from "../state/world";
import { getJSON } from "./api";
import { worldRef } from "../world/ref";

/** Highlights mode (W-08): banner + moment list + camera jumps between moments; "Back to live" restores. */

let timer: ReturnType<typeof setInterval> | null = null;
const STEP_MS = 3500;

function stopReel(): void {
  if (timer) clearInterval(timer);
  timer = null;
}

/** Camera to one moment (map metres when known, else the first agent). */
export function jumpTo(m: HlMoment): void {
  const st = useWorld.getState();
  if (m.x !== undefined && m.y !== undefined && (m.x !== 0 || m.y !== 0)) st.camera({ kind: "focus", x: m.x, y: m.y, z: 2.5 });
  else if (m.agent_ids[0] !== undefined) worldRef.scene?.focusAgent(m.agent_ids[0]);
}

function startReel(h: Highlights): void {
  stopReel();
  const ms = h.moments.filter((m) => m.x !== undefined);
  if (!ms.length) return;
  let i = 0;
  jumpTo(ms[0]);
  timer = setInterval(() => {
    i = (i + 1) % ms.length;
    jumpTo(ms[i]);
  }, STEP_MS);
}

/** Open highlights for a past day (1-based). Fixture mode uses the mockup's Day 21 list. */
export async function openHighlights(day: number): Promise<void> {
  const st = useWorld.getState();
  if (st.source !== "live") {
    const raw = (st.fixtures as unknown as { highlightsDay21?: [string, string, number][] })?.highlightsDay21 ?? [];
    const moments = raw.map(([hm, title, id]) => {
      const [h, m] = hm.split(":").map(Number);
      return { t: (day - 1) * 1440 + h * 60 + m, agent_ids: [id], title };
    });
    stopReel();
    st.setHighlights({ day, total: moments.length + 32, moments });
    return;
  }
  try {
    const h = await getJSON<{ day: number; moments: HlMoment[] }>(`/world/highlights?day=${day}`);
    const hl = { day, total: h.moments.length, moments: h.moments };
    st.setHighlights(hl);
    startReel(hl);
  } catch {
    st.setHighlights({ day, total: 0, moments: [] });
  }
}

/** Leave highlights mode. */
export function backToLive(): void {
  stopReel();
  useWorld.getState().setHighlights(null);
}
