import { create } from "zustand";
import { putJSON } from "../lib/api";

const KEY = "mirava_watchlist";

function load(): number[] | null {
  try {
    const v = localStorage.getItem(KEY);
    return v ? (JSON.parse(v) as number[]) : null;
  } catch {
    return null;
  }
}

export interface WatchStore {
  ids: number[];
  /** Seed from fixtures when nothing is saved yet (visual-test mode always uses the seed). */
  seed: (ids: number[], force?: boolean) => void;
  toggle: (id: number) => void;
  has: (id: number) => boolean;
}

/** Watchlist (U-04/U-05): Zustand + localStorage, synced with PUT /api/watchlist. Watching never changes the world. */
export const useWatch = create<WatchStore>((set, get) => ({
  ids: load() ?? [],
  seed: (ids, force) => {
    if (force || load() === null) set({ ids });
  },
  toggle: (id) => {
    const cur = get().ids;
    const ids = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    set({ ids });
    try {
      localStorage.setItem(KEY, JSON.stringify(ids));
    } catch {
      /* private mode */
    }
    putJSON("/watchlist", { agent_ids: ids }).catch(() => undefined);
  },
  has: (id) => get().ids.includes(id),
}));
