import Phaser from "phaser";
import { nightAlpha } from "../lib/time";

import { PX_PER_M } from "./ref";
import { simClock, tracks } from "./tracks";
import { useWorld } from "../state/world";
import { isVisualTest } from "../lib/visualTest";
import type { FixtureAgent } from "../visual-fixtures/types";

type Look = FixtureAgent["look"];
/** One drawable agent in Tiled pixels. */
export interface Drawn { id: number; x: number; y: number; h: number; mode: string; moving: boolean; look: Look; sleeping: boolean }
const U = 4; // mockup sprite unit → Tiled px (matches Z_TO_CAM)
const MOCK_W = 1200; // mockup map width in its units (fixture x/y)
const hex = (c: string): number => parseInt(c.replace("#", "").slice(0, 6), 16);

/** View zoom `z` (mockup units, 0.6–6) → Phaser camera zoom. */
export const Z_TO_CAM = 0.25;
export const Z_MIN = 0.6;
export const Z_MAX = 6;
const BOARD_SCALE = 3; // boards are drawn larger than life so they read on the map

interface TiledObject {
  id: number; name: string; type: string; x: number; y: number; rotation: number;
  properties?: { name: string; value: unknown }[];
}
export interface SiteLite { site_id: string; kind: string; x: number; y: number; facings: number[]; width_m: number; lit: boolean; cone_half_angle_deg?: number; max_distance_m?: number }
/** Baseline (ambient) brand board colours (config/baseline_ads.yaml ids; mockup creatives). */
export const BASELINE_BG: Record<string, string> = { zesto: "#b91c1c", kosha: "#1d4ed8", reelo: "#7c2d12", threadly: "#9d174d" };
const STAGE_COL: Record<string, string> = { aware: "#94a3b8", curious: "#60a5fa", researching: "#a78bfa", inquiring: "#f5b041", deciding: "#fb923c", purchased: "#4ade80", postponed: "#64748b", rejected: "#f87171" };
export interface ViewInfo { x: number; y: number; w: number; h: number; mapW: number; mapH: number; z: number }

/** Phaser scene rendering indiranagar.tmj with labels, site boards, lighting and camera controls (INTERFACES §6.5). */
export class WorldScene extends Phaser.Scene {
  private night!: Phaser.GameObjects.Rectangle;
  private glows!: Phaser.GameObjects.Container;
  private roadLabels: Phaser.GameObjects.Text[] = [];
  private placeLabels: Phaser.GameObjects.Text[] = [];
  private hour = 8 + 40 / 60;
  private z = 1.6;
  mapW = 0;
  mapH = 0;
  metro: { x: number; y: number } | null = null;
  onView: ((v: ViewInfo) => void) | null = null;
  onReady: (() => void) | null = null;
  private agentsG!: Phaser.GameObjects.Graphics;
  private sitesG!: Phaser.GameObjects.Graphics;
  private sites: SiteLite[] = [];
  private flipping = false;
  private drawn: Drawn[] = [];
  private downAt: { x: number; y: number } | null = null;

  constructor() {
    super("world");
  }

  preload(): void {
    this.load.tilemapTiledJSON("indiranagar", "/assets/maps/indiranagar.tmj");
    this.load.image("city-tiles", "/assets/tiles/city.png");
    this.load.json("sites", "/assets/maps/sites.json");
  }

  create(): void {
    const map = this.make.tilemap({ key: "indiranagar" });
    const ts = map.addTilesetImage("city", "city-tiles", 16, 16, 0, 0)!;
    for (const name of ["ground", "landuse", "roads", "rail", "buildings", "decor"]) map.createLayer(name, ts, 0, 0);
    this.mapW = map.widthInPixels;
    this.mapH = map.heightInPixels;
    this.sites = (this.cache.json.get("sites") as SiteLite[]) ?? [];
    this.sitesG = this.add.graphics().setDepth(10);
    this.drawSites();
    const unsub = useWorld.subscribe((st, prev) => {
      if (st.siteAssign !== prev.siteAssign || st.lens !== prev.lens || st.products !== prev.products) this.drawSites();
    });
    this.events.once("destroy", unsub);
    this.agentsG = this.add.graphics().setDepth(15);
    this.night = this.add.rectangle(-200, -200, this.mapW + 400, this.mapH + 400, 0x080e28, 0).setOrigin(0).setDepth(20);
    this.makeGlowTexture();
    this.glows = this.add.container(0, 0).setDepth(21);
    for (const o of (map.getObjectLayer("lights")?.objects ?? []) as TiledObject[]) {
      const r = Number(o.properties?.find((p) => p.name === "radius_m")?.value ?? 14) * PX_PER_M;
      const tint = o.type === "street" ? 0xffc878 : o.type === "site" ? 0xfff0c8 : o.type === "window" ? 0xffd68c : 0xffc078;
      const img = this.add.image(o.x, o.y, "glow").setBlendMode(Phaser.BlendModes.ADD).setTint(tint);
      img.setDisplaySize(r * 2, r * 2).setAlpha(o.type === "street" ? 0.45 : o.type === "site" ? 0.8 : 0.6);
      this.glows.add(img);
    }
    for (const o of (map.getObjectLayer("labels")?.objects ?? []) as TiledObject[]) {
      const road = o.type === "road_label";
      const txt = this.add.text(o.x, o.y, o.name, {
        fontFamily: "Inter", fontSize: road ? "11px" : "10px", fontStyle: road ? "600" : "500",
        color: o.type === "place_label:store" ? "#7dd3fc" : road ? "#e5e7eb" : "#cbd5e1",
        backgroundColor: "rgba(10,13,18,0.65)", padding: { x: 5, y: 2 }, resolution: 2,
      }).setOrigin(0.5).setDepth(30).setAngle(o.rotation);
      (road ? this.roadLabels : this.placeLabels).push(txt);
      if (o.type === "place_label:metro" && !this.metro) this.metro = { x: o.x, y: o.y };
    }
    const cam = this.cameras.main;
    cam.setBackgroundColor("#0a0d12");
    cam.setBounds(-this.mapW * 0.25, -this.mapH * 0.25, this.mapW * 1.5, this.mapH * 1.5);
    this.focusPx(this.metro?.x ?? this.mapW / 2, this.metro?.y ?? this.mapH / 2, this.z);
    this.bindInput();
    this.setHour(this.hour);
    this.scale.on("resize", () => this.emitView());
    this.onReady?.();
  }

  update(): void {
    this.drawAgents();
    if (this.flipping) this.drawSites();
    const inv = 1 / this.cameras.main.zoom;
    const showRoad = this.z >= 0.8;
    const showPlace = this.z >= 1.5;
    for (const t of this.roadLabels) t.setScale(inv).setVisible(showRoad);
    for (const t of this.placeLabels) t.setScale(inv).setVisible(showPlace);
  }

  /** Lighting follows the clock (W-10). */
  setHour(h: number): void {
    this.hour = h;
    if (!this.night) return;
    const a = nightAlpha(h);
    this.night.setFillStyle(0x080e28, a);
    this.glows.setVisible(a > 0).setAlpha(Math.min(1, a * 1.8));
  }

  /** Centre the camera on Tiled pixel coordinates at view zoom z. */
  focusPx(x: number, y: number, z = this.z): void {
    this.z = Phaser.Math.Clamp(z, Z_MIN, Z_MAX);
    const cam = this.cameras.main;
    cam.setZoom(this.z * Z_TO_CAM);
    cam.centerOn(x, y);
    this.emitView();
  }

  /** Centre on world metres. */
  focusM(xm: number, ym: number, z?: number): void {
    this.focusPx(xm * PX_PER_M, ym * PX_PER_M, z);
  }

  /** Zoom by a factor around a screen point (default: centre). */
  zoomBy(f: number, sx?: number, sy?: number): void {
    const cam = this.cameras.main;
    const px = sx ?? cam.width / 2;
    const py = sy ?? cam.height / 2;
    const before = cam.getWorldPoint(px, py);
    this.z = Phaser.Math.Clamp(this.z * f, Z_MIN, Z_MAX);
    cam.setZoom(this.z * Z_TO_CAM);
    cam.preRender();
    const after = cam.getWorldPoint(px, py);
    cam.scrollX += before.x - after.x;
    cam.scrollY += before.y - after.y;
    this.emitView();
  }

  /** Fit the whole map (`__ll.overview`). */
  fit(): void {
    const cam = this.cameras.main;
    const z = (Math.min(cam.width / this.mapW, cam.height / this.mapH) * 1.02) / Z_TO_CAM;
    this.focusPx(this.mapW / 2, this.mapH / 2, z);
  }

  private emitView(): void {
    this.cameras.main.preRender();
    const v = this.cameras.main.worldView;
    this.onView?.({ x: v.x, y: v.y, w: v.width, h: v.height, mapW: this.mapW, mapH: this.mapH, z: this.z });
  }

  private bindInput(): void {
    const cam = this.cameras.main;
    let last: { x: number; y: number } | null = null;
    let lastClick = 0;
    this.input.on("pointerdown", (p: Phaser.Input.Pointer) => {
      last = { x: p.x, y: p.y };
      this.downAt = { x: p.x, y: p.y };
      const now = p.downTime;
      if (now - lastClick < 300) {
        const w = cam.getWorldPoint(p.x, p.y);
        this.focusPx(w.x, w.y, 3);
      }
      lastClick = now;
    });
    this.input.on("pointerup", (p: Phaser.Input.Pointer) => {
      last = null;
      if (this.downAt && Math.abs(p.x - this.downAt.x) + Math.abs(p.y - this.downAt.y) < 4) {
        const a = this.nearest(p.x, p.y);
        if (a) useWorld.getState().openProfile(a.id);
      }
      this.downAt = null;
    });
    this.input.on("gameout", () => {
      if (!(isVisualTest && useWorld.getState().hover?.pinned)) useWorld.getState().setHover(null);
    });
    this.input.on("pointermove", (p: Phaser.Input.Pointer) => {
      if (!p.isDown || !last) {
        if (useWorld.getState().hover?.pinned && isVisualTest) return;
        const a = this.nearest(p.x, p.y);
        const ev = p.event as MouseEvent | undefined;
        useWorld.getState().setHover(a ? { id: a.id, sx: ev?.clientX ?? p.x, sy: ev?.clientY ?? p.y } : null);
        return;
      }
      cam.scrollX -= (p.x - last.x) / cam.zoom;
      cam.scrollY -= (p.y - last.y) / cam.zoom;
      last = { x: p.x, y: p.y };
      this.emitView();
    });
    this.input.on("wheel", (p: Phaser.Input.Pointer, _o: unknown, _dx: number, dy: number) => {
      this.zoomBy(dy > 0 ? 1 / 1.15 : 1.15, p.x, p.y);
    });
  }

  /** Current agent positions: fixtures (visual-test / before hello) or live tracks interpolated at 60 fps. */
  collect(): Drawn[] {
    const st = useWorld.getState();
    const fx = st.fixtures;
    const looks = fx?.agents ?? [];
    const lookOf = (id: number): Look => looks[id % Math.max(1, looks.length)]?.look ?? { skin: "#d9a07b", hair: "#222", shirt: "#14b8a6", pants: "#334155", hairLong: false, cap: false };
    const out: Drawn[] = [];
    if (st.source === "live") {
      tracks.advance(simClock.now());
      for (const tr of tracks.byId.values()) {
        if (tr.mode === "offmap") continue;
        out.push({ id: tr.id, x: tr.x * PX_PER_M, y: tr.y * PX_PER_M, h: tr.h, mode: tr.mode, moving: tr.moving, look: lookOf(tr.id), sleeping: tr.act === "sleep" });
      }
    } else {
      const k = this.mapW / MOCK_W;
      for (const a of looks as (FixtureAgent & { mode?: string; moving?: boolean })[]) {
        out.push({ id: a.id, x: a.x * k, y: a.y * k, h: a.heading, mode: a.mode ?? "walk", moving: !!a.moving, look: a.look, sleeping: a.act === "Sleeping" });
      }
    }
    return out;
  }

  /** Tiled-pixel position of an agent (null if unknown or off the map). */
  agentPx(id: number): { x: number; y: number } | null {
    const d = (this.drawn.length ? this.drawn : this.collect()).find((a) => a.id === id);
    return d ? { x: d.x, y: d.y } : null;
  }

  /** Viewport (client) coordinates of a Tiled-pixel point. */
  clientOf(x: number, y: number): { x: number; y: number } {
    const cam = this.cameras.main;
    const r = this.game.canvas.getBoundingClientRect();
    const kx = r.width / (this.game.canvas.width || r.width), ky = r.height / (this.game.canvas.height || r.height);
    const sx = (x - cam.scrollX - cam.originX * cam.width) * cam.zoom + cam.originX * cam.width;
    const sy = (y - cam.scrollY - cam.originY * cam.height) * cam.zoom + cam.originY * cam.height;
    return { x: r.left + sx * kx, y: r.top + sy * ky };
  }


  /** Centre on an agent at view zoom 3 (`__ll.focus`). */
  focusAgent(id: number, z = 3): boolean {
    const p = this.agentPx(id);
    if (!p) return false;
    this.focusPx(p.x, p.y, z);
    return true;
  }

  /** Nearest agent to a screen point (mockup radius rule; sleepers skipped when zoomed out). */
  nearest(sx: number, sy: number): Drawn | null {
    const w = this.cameras.main.getWorldPoint(sx, sy);
    const lim = ((7 / this.z + 3) * U) ** 2;
    let best: Drawn | null = null;
    let bd = lim;
    for (const a of this.drawn) {
      if (a.sleeping && this.z < 2.2) continue;
      const dx = a.x - w.x;
      const dy = a.y - 3 * U - w.y;
      const dd = dx * dx + dy * dy;
      if (dd < bd) {
        bd = dd;
        best = a;
      }
    }
    return best;
  }

  private drawAgents(): void {
    const g = this.agentsG;
    if (!g) return;
    this.drawn = this.collect();
    g.clear();
    const v = this.cameras.main.worldView;
    const frozen = simClock.frozen;
    const now = performance.now();
    let dimA = 1;
    const r = (c: number, x: number, y: number, w: number, h: number, a = 1) => g.fillStyle(c, a * dimA).fillRect(x * U, y * U, w * U, h * U);
    for (const a of this.drawn) {
      if (a.x < v.x - 60 || a.y < v.y - 60 || a.x > v.right + 60 || a.y > v.bottom + 60) continue;
      const x = a.x / U;
      const y = a.y / U;
      const L = a.look;
      if (a.mode === "idle" && a.sleeping) continue;
      const ring = this.lensRing(a.id);
      dimA = ring === null ? 0.28 : 1;
      if (ring !== undefined && ring !== null) g.lineStyle(0.7 * U, hex(ring), 1).strokeCircle(a.x, a.y - 3 * U, 4.6 * U);
      if (a.moving && a.mode !== "walk") {
        r(0x000000, x - 3, y, 6, 1.2, 0.3);
        const hz = a.h % 180 > 45 && a.h % 180 < 135;
        if (a.mode === "car" || a.mode === "bus" || a.mode === "auto") {
          const col = a.mode === "bus" ? 0x2563eb : a.mode === "auto" ? 0xfacc15 : hex(L.shirt);
          const s = a.mode === "bus" ? 1.8 : 1;
          if (hz) r(col, x - 4 * s, y - 3.5, 8 * s, 4); else r(col, x - 2, y - 6 * s, 4, 7 * s);
          if (hz) r(0xcbd5e1, x - 2, y - 3, 3, 1.5); else r(0xcbd5e1, x - 1.5, y - 5, 3, 1.5);
          continue;
        }
        if (hz) r(0x111827, x - 3.5, y - 1.5, 7, 1.6); else r(0x111827, x - 0.8, y - 4, 1.6, 5);
        r(hex(L.shirt), x - 1.5, y - 5, 3, 3);
        r(hex(L.skin), x - 1.2, y - 7.2, 2.4, 2.2);
        r(0x334155, x - 1.5, y - 7.8, 3, 1.2);
        continue;
      }
      const stp = a.moving && !frozen ? Math.floor(now / 160 + a.id) % 2 : 0;
      r(0x000000, x - 2, y, 4, 1.2, 0.3);
      r(hex(L.pants), x - 1.5, y - 2.5, 1.2, 2.5 - (stp ? 0.6 : 0));
      r(hex(L.pants), x + 0.3, y - 2.5, 1.2, 2.5 - (stp ? 0 : 0.6));
      r(hex(L.shirt), x - 2, y - 5.5, 4, 3.2);
      r(hex(L.skin), x - 1.5, y - 8, 3, 2.6);
      r(hex(L.hair), x - 1.6, y - 8.6, 3.2, 1.2);
      if (L.hairLong) r(hex(L.hair), x - 1.8, y - 8, 0.8, 2.6);
      if (L.cap) r(0xef4444, x - 1.8, y - 9, 3.6, 1.1);
    }
  }

  /** Aware/Sentiment lens ring colour for an agent: colour = aware, null = unaware (dimmed), undefined = no lens. */
  private lensRing(id: number): string | null | undefined {
    const st = useWorld.getState();
    if (st.lens !== "aware" && st.lens !== "sentiment") return undefined;
    const pid = st.lensProduct;
    if (!pid) return null;
    let stage: string | undefined;
    let att = 0;
    if (st.source === "live") {
      const m = st.aware[pid];
      if (m && id in m) { stage = "aware"; att = m[id]; }
    } else {
      const fa = st.fixtures?.agents[id % Math.max(1, st.fixtures.agents.length)];
      const b = fa?.beliefs[pid];
      if (b && b.stage !== "unaware") { stage = b.stage; att = b.att; }
    }
    if (!stage) return null;
    if (st.lens === "aware") return STAGE_COL[stage] ?? "#94a3b8";
    return att > 0.15 ? "#4ade80" : att < -0.1 ? "#f87171" : "#f5b041";
  }

  private makeGlowTexture(): void {
    if (this.textures.exists("glow")) return;
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const g = c.getContext("2d")!;
    const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, "rgba(255,255,255,0.55)");
    grd.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grd;
    g.fillRect(0, 0, 64, 64);
    this.textures.addCanvas("glow", c);
  }

  /** Board colour of what a site shows (product colour, baseline brand, or blank). */
  private boardColour(cr: string | undefined): number {
    if (!cr) return 0x334155;
    const p = useWorld.getState().products.find((x) => x.id === cr);
    if (p) return hex(p.hex);
    return BASELINE_BG[cr] ? hex(BASELINE_BG[cr]) : 0x334155;
  }

  /** Site boards (coloured by their creative, flashing when a launch flips them), facing marks and, in the Hoardings
   * lens, visibility cones coloured by product. */
  private drawSites(): void {
    const g = this.sitesG;
    if (!g) return;
    g.clear();
    const st = useWorld.getState();
    const now = performance.now();
    let flipping = false;
    if (st.lens === "hoardings") {
      for (const s of this.sites) {
        const as = st.siteAssign[s.site_id];
        if (!as) continue;
        const f = as.facing ?? s.facings[0] ?? 0;
        const col = this.boardColour(as.cr);
        const half = Phaser.Math.DegToRad(s.cone_half_angle_deg ?? 50);
        const fr = Phaser.Math.DegToRad(f) - Math.PI / 2;
        const range = (s.max_distance_m ?? 60) * PX_PER_M * BOARD_SCALE * 0.6; // exaggerated like the boards, as in the mockup
        g.fillStyle(col, 0.27).lineStyle(1.2, col, 0.85);
        g.beginPath();
        g.moveTo(s.x * PX_PER_M, s.y * PX_PER_M);
        g.arc(s.x * PX_PER_M, s.y * PX_PER_M, range, fr - half, fr + half, false);
        g.closePath();
        g.fillPath();
        g.strokePath();
      }
    }
    for (const s of this.sites) {
      const x = s.x * PX_PER_M;
      const y = s.y * PX_PER_M;
      const as = st.siteAssign[s.site_id];
      const f = as?.facing ?? s.facings[0] ?? 0;
      const pending = !!as?.flipAt && now < as.flipAt;
      const cr = pending ? (as as { prev?: string }).prev : as?.cr;
      const w = Math.max(6, s.width_m) * PX_PER_M * BOARD_SCALE * 0.5;
      const h = 3.2 * PX_PER_M * BOARD_SCALE * 0.5;
      const rad = Phaser.Math.DegToRad(f); // board's long side is perpendicular to its facing
      g.save();
      g.translateCanvas(x, y);
      g.rotateCanvas(rad);
      g.fillStyle(0x000000, 0.35).fillRect(-w + 3, -h + 3, w * 2, h * 2);
      g.fillStyle(0x111827, 1).fillRect(-w - 1.6, -h - 1.6, w * 2 + 3.2, h * 2 + 3.2);
      g.fillStyle(cr ? this.boardColour(cr) : s.kind === "bus_shelter" ? 0x64748b : 0x334155, 1).fillRect(-w, -h, w * 2, h * 2);
      if (as?.flipAt && now >= as.flipAt && now < as.flipAt + 900) g.fillStyle(0xffffff, 1 - (now - as.flipAt) / 900).fillRect(-w - 4, -h - 4, w * 2 + 8, h * 2 + 8);
      g.restore();
      if (as?.flipAt && now < as.flipAt + 900) flipping = true;
      const faces = as?.facing !== undefined ? [as.facing] : s.facings;
      const prod = st.products.find((p) => p.id === cr);
      for (const face of faces) {
        const r = Phaser.Math.DegToRad(face);
        g.fillStyle(prod ? hex(prod.hex) : 0xcbd5e1, 1).fillCircle(x + Math.sin(r) * (h + 6), y - Math.cos(r) * (h + 6), 2.6);
      }
    }
    this.flipping = flipping;
  }

}
