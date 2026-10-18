import type { ViewInfo, WorldScene } from "./WorldScene";

/** Tiled pixels per metre (16 px tiles of 8 m). */
export const PX_PER_M = 2;

/** The live scene (one World page at a time); used by window.__ll and the minimap. Phaser-free for tests. */
export const worldRef: { scene: WorldScene | null; view: ViewInfo | null; listeners: Set<(v: ViewInfo) => void>; pendingFocus: number | null; pendingFit: boolean } = {
  pendingFocus: null, pendingFit: false, scene: null, view: null, listeners: new Set(),
};
