import Phaser from "phaser";
import { useEffect, useRef } from "react";
import { useWorld } from "../state/world";
import { minuteOfDay } from "../lib/time";
import { WorldScene } from "./WorldScene";
import { worldRef } from "./ref";

/** Mounts Phaser into the `world-canvas` region and wires store commands (zoom, focus, time). */
export function WorldCanvas() {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    el.replaceChildren(); // a previous (StrictMode) mount may have left its canvas behind
    let alive = true;
    const scene = new WorldScene();
    scene.onView = (v) => {
      worldRef.view = v;
      worldRef.listeners.forEach((fn) => fn(v));
    };
    scene.onReady = () => {
      if (!alive) return;
      worldRef.scene = scene;
      const s = useWorld.getState();
      scene.setHour(s.hourOverride ?? minuteOfDay(s.t) / 60);
      const pf = worldRef.pendingFocus ?? s.profile?.id ?? null;
      worldRef.pendingFocus = null;
      if (worldRef.pendingFit) { worldRef.pendingFit = false; scene.fit(); }
      else if (pf !== null) scene.focusAgent(pf);
      else if (s.hover) scene.focusAgent(s.hover.id);
    };
    const game = new Phaser.Game({
      type: Phaser.AUTO, parent: el, pixelArt: true, backgroundColor: "#0a0d12",
      scale: { mode: Phaser.Scale.RESIZE, width: el.clientWidth || 800, height: el.clientHeight || 600 },
      scene, banner: false, disableContextMenu: true,
      fps: { target: 60 }, input: { mouse: { preventDefaultWheel: true } },
    });
    const unsub = useWorld.subscribe((s, prev) => {
      const sc = worldRef.scene;
      if (!sc) return;
      if (s.t !== prev.t || s.hourOverride !== prev.hourOverride) sc.setHour(s.hourOverride ?? minuteOfDay(s.t) / 60);
      if (s.zoomCmd && s.zoomCmd !== prev.zoomCmd) {
        const c = s.zoomCmd;
        if (c.kind === "in") sc.zoomBy(1.25);
        else if (c.kind === "out") sc.zoomBy(1 / 1.25);
        else if (c.kind === "fit") sc.fit();
        else if (c.x !== undefined && c.y !== undefined) sc.focusM(c.x, c.y, c.z);
        else sc.focusPx(sc.metro?.x ?? sc.mapW / 2, sc.metro?.y ?? sc.mapH / 2, c.z);
      }
    });
    return () => {
      alive = false;
      unsub();
      useWorld.getState().setHover(null);
      if (worldRef.scene === scene) worldRef.scene = null;
      game.destroy(true);
      game.canvas?.remove();
      el.replaceChildren();
    };
  }, []);
  return <div ref={host} className="phaser-host" data-testid="world-canvas" />;
}
