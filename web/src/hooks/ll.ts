import { useEffect } from "react";
import { useWorld, type Lens } from "../state/world";
import { worldRef } from "../world/ref";

type ProfileTab = "overview" | "relations" | "possessions" | "thoughts" | "conversations" | "memory";

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
    // stub (phase 2): agents are not on the OSM map yet; centre on the metro at zoom 3
    focus: () => st().camera({ kind: "focus", z: 3 }),
    hoverAgent: stub("hoverAgent"),
    openAgent: stub("openAgent"),
    lens: (name) => st().setLens(name),
    setTime: (hour) => {
      st().setHour(hour);
      worldRef.scene?.setHour(hour);
    },
    overview: () => {
      if (worldRef.scene) worldRef.scene.fit();
      else st().camera({ kind: "fit" });
    },
    highlights: stub("highlights"),
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
