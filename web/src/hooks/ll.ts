import { useEffect } from "react";
import { useWorld, type Lens, type ProfileTab } from "../state/world";
import { worldRef } from "../world/ref";
import { openHighlights } from "../lib/highlights";


/** The visual-test / automation API (INTERFACES §6.4). Stubs are marked and listed in PROGRESS.md §9. */
export interface LLHooks {
  featured(): number;
  focus(id: number): void;
  hoverAgent(id: number): void;
  openAgent(id: number, tab: ProfileTab): void;
  lens(name: Lens): void;
  setTime(hour: number): void;
  overview(): void;
  highlights(day: number): void;
  launchFx(productId: string, progress: number): void;
  graphSelect(nodeId: string): void;
  graphHover(nodeId: string): void;
}

declare global {
  interface Window { __ll: LLHooks }
}

const stub = (name: string) => () => console.info(`[__ll] ${name}: arrives in a later phase`);

export function makeHooks(): LLHooks {
  const st = useWorld.getState;
  return {
    featured: () => st().fixtures?.featured.id ?? 0,
    focus: (id) => {
      if (!worldRef.scene?.focusAgent(id)) worldRef.pendingFocus = id; // applied when the scene is ready
    },
    hoverAgent: (id) => {
      const run = (tries: number) => {
        const sc = worldRef.scene;
        if (!sc?.focusAgent(id)) {
          // scene still loading: focus centres the agent, so point at the canvas centre (agent head ≈ 9 px up)
          const el = document.querySelector("[data-testid=world-canvas]")?.getBoundingClientRect();
          if (el && tries === 60) st().setHover({ id, sx: el.left + el.width / 2, sy: el.top + el.height / 2 - 9, pinned: true });
          if (tries > 0) setTimeout(() => run(tries - 1), 50);
          return;
        }
        const p = sc.agentPx(id)!;
        const c = sc.clientOf(p.x, p.y - 12);
        st().setHover({ id, sx: c.x, sy: c.y, pinned: true });
      };
      run(60);
    },
    openAgent: (id, tab) => {
      if (!worldRef.scene?.focusAgent(id)) worldRef.pendingFocus = id;
      st().openProfile(id, tab ?? "overview");
    },
    lens: (name) => st().setLens(name),
    setTime: (hour) => {
      st().setHour(hour);
      worldRef.scene?.setHour(hour);
    },
    overview: () => {
      if (worldRef.scene) worldRef.scene.fit();
      else st().camera({ kind: "fit" });
    },
    highlights: (day) => void openHighlights(day),
    launchFx: stub("launchFx"),
    graphSelect: stub("graphSelect"),
    graphHover: stub("graphHover"),
  };
}

/** Install window.__ll for the app's lifetime. */
export function useLiveHooks(): void {
  useEffect(() => {
    window.__ll = makeHooks();
  }, []);
}
