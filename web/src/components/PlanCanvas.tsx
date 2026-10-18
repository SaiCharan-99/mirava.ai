/** `plan-canvas`: the map with numbered planned sites, their visibility cones and the stocking stores (mockup drawPlan). */
import { useEffect, useRef } from "react";
import { buildBase } from "../world/Minimap";
import type { SiteV } from "../lib/studio";

export interface MapSite { site_id: string; kind: string; x: number; y: number; facings: number[]; lit: boolean; cone_half_angle_deg: number; max_distance_m: number; area_label: string }
const TILE_M = 8;          // base image: 1 px per 8 m tile
const TILE_PX = 16;        // Tiled px per tile

let sitesP: Promise<MapSite[]> | null = null;
let storesP: Promise<Record<string, { x: number; y: number }>> | null = null;

/** sites.json (metres). */
export function loadSites(): Promise<MapSite[]> {
  sitesP ??= fetch("/assets/maps/sites.json").then((r) => r.json() as Promise<MapSite[]>).catch(() => []);
  return sitesP;
}

/** Store name → Tiled-pixel position, from the map's `place_label:store` labels. */
export function loadStoreXY(): Promise<Record<string, { x: number; y: number }>> {
  storesP ??= fetch("/assets/maps/indiranagar.tmj").then((r) => r.json()).then((tmj: { layers: { name: string; objects?: { type: string; name: string; x: number; y: number }[] }[] }) => {
    const out: Record<string, { x: number; y: number }> = {};
    for (const o of tmj.layers.find((l) => l.name === "labels")?.objects ?? []) if (o.type === "place_label:store") out[o.name] = { x: o.x, y: o.y };
    return out;
  }).catch(() => ({}));
  return storesP;
}

export function PlanCanvas({ sites, stores, hex }: { sites: SiteV[]; stores: string[]; hex: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let alive = true;
    Promise.all([buildBase(), loadSites(), loadStoreXY()]).then(([base, all, sxy]) => {
      const cv = ref.current;
      if (!alive || !cv) return;
      const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
      cv.width = r.width * d;
      cv.height = r.height * d;
      const c = cv.getContext("2d")!;
      const W = base.width, H = base.height;
      const z = Math.min(cv.width / W, cv.height / H);
      const ox = (cv.width - W * z) / 2, oy = (cv.height - H * z) / 2;
      c.fillStyle = "#0a0d12";
      c.fillRect(0, 0, cv.width, cv.height);
      c.imageSmoothingEnabled = false;
      c.globalAlpha = 0.75;
      c.drawImage(base, ox, oy, W * z, H * z);
      c.globalAlpha = 1;
      const byId = new Map(all.map((s) => [s.site_id, s]));
      sites.forEach((ps, i) => {
        const s = byId.get(ps.site_id);
        if (!s) return;
        const x = ox + (s.x / TILE_M) * z, y = oy + (s.y / TILE_M) * z;
        const fr = (ps.facing * Math.PI) / 180, half = (s.cone_half_angle_deg * Math.PI) / 180;
        const range = Math.max((s.max_distance_m / TILE_M) * z, 14 * d);
        c.fillStyle = hex + "40";
        c.strokeStyle = hex;
        c.lineWidth = d;
        c.beginPath();
        c.moveTo(x, y);
        c.arc(x, y, range, fr - Math.PI / 2 - half, fr - Math.PI / 2 + half);
        c.closePath();
        c.fill();
        c.stroke();
        c.fillStyle = hex;
        c.beginPath();
        c.arc(x, y, 7 * d, 0, 7);
        c.fill();
        c.fillStyle = "#1a0d02";
        c.font = `700 ${9 * d}px Inter`;
        c.textAlign = "center";
        c.textBaseline = "middle";
        c.fillText(String(i + 1), x, y);
      });
      for (const name of stores) {
        const p = sxy[name];
        if (!p) continue;
        const x = ox + (p.x / TILE_PX) * z, y = oy + (p.y / TILE_PX) * z;
        c.fillStyle = "#0ea5e9";
        c.fillRect(x - 5 * d, y - 5 * d, 10 * d, 10 * d);
        c.fillStyle = "#e0f2fe";
        c.font = `600 ${10 * d}px Inter`;
        c.textAlign = "left";
        c.fillText(name, x + 8 * d, y);
      }
    });
    return () => { alive = false; };
  }, [sites, stores, hex]);
  return <canvas ref={ref} data-testid="plan-canvas" style={{ width: "100%", height: "100%", display: "block" }} />;
}
