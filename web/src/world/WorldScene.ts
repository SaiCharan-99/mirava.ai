import Phaser from "phaser";
import { nightAlpha } from "../lib/time";

import { PX_PER_M } from "./ref";

/** View zoom `z` (mockup units, 0.6–6) → Phaser camera zoom. */
export const Z_TO_CAM = 0.25;
export const Z_MIN = 0.6;
export const Z_MAX = 6;
const BOARD_SCALE = 3; // boards are drawn larger than life so they read on the map

interface TiledObject {
  id: number; name: string; type: string; x: number; y: number; rotation: number;
  properties?: { name: string; value: unknown }[];
}
export interface SiteLite { site_id: string; kind: string; x: number; y: number; facings: number[]; width_m: number; lit: boolean }
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
    this.drawSites(this.cache.json.get("sites") as SiteLite[]);
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
      const now = p.downTime;
      if (now - lastClick < 300) {
        const w = cam.getWorldPoint(p.x, p.y);
        this.focusPx(w.x, w.y, 3);
      }
      lastClick = now;
    });
    this.input.on("pointerup", () => (last = null));
    this.input.on("pointermove", (p: Phaser.Input.Pointer) => {
      if (!p.isDown || !last) return;
      cam.scrollX -= (p.x - last.x) / cam.zoom;
      cam.scrollY -= (p.y - last.y) / cam.zoom;
      last = { x: p.x, y: p.y };
      this.emitView();
    });
    this.input.on("wheel", (p: Phaser.Input.Pointer, _o: unknown, _dx: number, dy: number) => {
      this.zoomBy(dy > 0 ? 1 / 1.15 : 1.15, p.x, p.y);
    });
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

  /** Site boards with a facing mark (the face points towards its audience). */
  private drawSites(sites: SiteLite[]): void {
    const g = this.add.graphics().setDepth(10);
    for (const s of sites ?? []) {
      const x = s.x * PX_PER_M;
      const y = s.y * PX_PER_M;
      const f = s.facings[0] ?? 0;
      const w = Math.max(6, s.width_m) * PX_PER_M * BOARD_SCALE * 0.5;
      const h = 3.2 * PX_PER_M * BOARD_SCALE * 0.5;
      const rad = Phaser.Math.DegToRad(f); // board's long side is perpendicular to its facing
      g.save();
      g.translateCanvas(x, y);
      g.rotateCanvas(rad);
      g.fillStyle(0x000000, 0.35).fillRect(-w + 3, -h + 3, w * 2, h * 2);
      g.fillStyle(0x111827, 1).fillRect(-w - 1.6, -h - 1.6, w * 2 + 3.2, h * 2 + 3.2);
      g.fillStyle(s.kind === "bus_shelter" ? 0x64748b : 0x334155, 1).fillRect(-w, -h, w * 2, h * 2);
      g.restore();
      for (const face of s.facings) {
        const r = Phaser.Math.DegToRad(face);
        g.fillStyle(0xcbd5e1, 1).fillCircle(x + Math.sin(r) * (h + 6), y - Math.cos(r) * (h + 6), 2.6);
      }
    }
  }
}
