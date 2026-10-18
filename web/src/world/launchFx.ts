/** Launch firework (L-08, mockup drawFx): orb falls → burst rings → flares to every planned site and stocking store →
 * particles, then sparkles over the audience. Drawn on the `launch-fx` overlay canvas in client space. */
import { useWorld, type LaunchFx } from "../state/world";
import { PX_PER_M, worldRef } from "./ref";
import { loadSites, loadStoreXY } from "../components/PlanCanvas";

const DURATION = 3.8;
let sitePx: Record<string, { x: number; y: number }> = {};
let storePx: Record<string, { x: number; y: number }> = {};
let raf = 0;

void loadSites().then((s) => { sitePx = Object.fromEntries(s.map((x) => [x.site_id, { x: x.x * PX_PER_M, y: x.y * PX_PER_M }])); });
void loadStoreXY().then((s) => { storePx = s; });

/** Start (or freeze at `frozen` 0–1) the firework for a product. */
export function playLaunchFx(fx: Omit<LaunchFx, "t0">): void {
  useWorld.setState({ fx: { ...fx, t0: performance.now() } });
  cancelAnimationFrame(raf);
  const loop = () => {
    const done = drawFx();
    if (!done) raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
}

function canvas(): HTMLCanvasElement | null {
  const cv = document.querySelector<HTMLCanvasElement>("[data-testid=launch-fx]");
  if (!cv) return null;
  const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(r.width * d) || cv.height !== Math.round(r.height * d)) {
    cv.width = Math.round(r.width * d);
    cv.height = Math.round(r.height * d);
  }
  return cv;
}

/** Draw one frame; returns true when the animation is over (or nothing to draw). */
export function drawFx(): boolean {
  const cv = canvas();
  const F = useWorld.getState().fx;
  const sc = worldRef.scene;
  if (!cv) return true;
  const c = cv.getContext("2d")!;
  c.setTransform(1, 0, 0, 1, 0, 0);
  c.clearRect(0, 0, cv.width, cv.height);
  if (!F || !sc) return !F;
  const T = F.frozen !== null ? F.frozen * 3.6 : (performance.now() - F.t0) / 1000;
  if (T > DURATION && F.frozen === null) {
    useWorld.setState({ fx: null });
    c.clearRect(0, 0, cv.width, cv.height);
    return true;
  }
  const d = window.devicePixelRatio || 1, col = F.hex;
  const box = cv.getBoundingClientRect();
  const toCv = (x: number, y: number): [number, number] => {
    const p = sc.clientOf(x, y);
    return [(p.x - box.left) * d, (p.y - box.top) * d];
  };
  const [cx, cy] = toCv(sc.mapW * 0.5, sc.mapH * 0.56);
  const sx = cv.width / 2, sy = -40 * d;
  if (T < 0.9) {
    const k = T / 0.9, e = k * k;
    const x = sx + (cx - sx) * e, y = sy + (cy - sy) * e;
    for (let i = 0; i < 14; i++) {
      const kk = Math.max(0, e - i * 0.025);
      c.globalAlpha = 0.5 * (1 - i / 14);
      c.fillStyle = col;
      c.beginPath(); c.arc(sx + (cx - sx) * kk, sy + (cy - sy) * kk, (10 - i * 0.5) * d, 0, 7); c.fill();
    }
    c.globalAlpha = 1;
    const g = c.createRadialGradient(x, y, 0, x, y, 26 * d);
    g.addColorStop(0, "#fff"); g.addColorStop(0.35, col); g.addColorStop(1, col + "00");
    c.fillStyle = g; c.beginPath(); c.arc(x, y, 26 * d, 0, 7); c.fill();
    c.fillStyle = "#fff"; c.font = `700 ${12 * d}px Inter`; c.textAlign = "center"; c.fillText(F.name, x, y - 34 * d);
  }
  if (T >= 0.85 && T < 2.2) {
    const k = (T - 0.85) / 1.35;
    for (let r = 0; r < 3; r++) {
      c.globalAlpha = Math.max(0, 1 - k * 1.3 - r * 0.12);
      c.strokeStyle = col; c.lineWidth = (6 - r * 1.5) * d;
      c.beginPath(); c.arc(cx, cy, (20 + k * (220 + r * 90)) * d, 0, 7); c.stroke();
    }
    c.globalAlpha = 1;
    const g = c.createRadialGradient(cx, cy, 0, cx, cy, 170 * d);
    g.addColorStop(0, `rgba(255,255,255,${Math.max(0, 0.95 - k)})`); g.addColorStop(0.3, col + "88"); g.addColorStop(1, col + "00");
    c.globalAlpha = Math.max(0, 1 - k); c.fillStyle = g; c.beginPath(); c.arc(cx, cy, 170 * d, 0, 7); c.fill(); c.globalAlpha = 1;
  }
  if (T >= 1.0 && T < 3.0) {
    const k = Math.min(1, (T - 1) / 1.3);
    const targets = [...F.sites.map((s) => sitePx[s]), ...F.stores.map((s) => storePx[s])].filter((p): p is { x: number; y: number } => !!p);
    targets.forEach((tp, i) => {
      const [tx, ty] = toCv(tp.x, tp.y);
      const kk = Math.min(1, Math.max(0, k * 1.15 - i * 0.02)), e = 1 - Math.pow(1 - kk, 3);
      const mx = (cx + tx) / 2, my = Math.min(cy, ty) - 140 * d;
      const q = (u: number): [number, number] => [(1 - u) * (1 - u) * cx + 2 * (1 - u) * u * mx + u * u * tx, (1 - u) * (1 - u) * cy + 2 * (1 - u) * u * my + u * u * ty];
      c.globalAlpha = Math.max(0, 0.75 - (T - 2.4) * 1.2);
      c.strokeStyle = col; c.lineWidth = 2.5 * d; c.beginPath();
      const u0 = Math.max(0, e - 0.35);
      for (let u = u0; u <= e; u += 0.02) { const [px, py] = q(u); if (u === u0) c.moveTo(px, py); else c.lineTo(px, py); }
      c.stroke();
      const [hx, hy] = q(e);
      c.globalAlpha = 1;
      const hg = c.createRadialGradient(hx, hy, 0, hx, hy, 10 * d);
      hg.addColorStop(0, "#fff"); hg.addColorStop(0.4, col); hg.addColorStop(1, col + "00");
      c.fillStyle = hg; c.beginPath(); c.arc(hx, hy, 10 * d, 0, 7); c.fill();
      if (e >= 1) { c.globalAlpha = Math.max(0, 1 - (T - 2.2) / 0.8); c.strokeStyle = col; c.lineWidth = 3 * d; c.beginPath(); c.arc(tx, ty, (10 + (T - 2.2) * 40) * d, 0, 7); c.stroke(); }
    });
    c.globalAlpha = 1;
    for (let i = 0; i < 110; i++) {
      const ang = i * 2.399, sp = (90 + ((i * 37) % 140)) * d, kk = Math.min(1, (T - 1) / 1.4);
      c.globalAlpha = Math.max(0, 1 - kk); c.fillStyle = i % 3 ? col : "#fde68a";
      c.beginPath(); c.arc(cx + Math.cos(ang) * sp * kk, cy + Math.sin(ang) * sp * kk + 50 * d * kk * kk, 3 * d, 0, 7); c.fill();
    }
    c.globalAlpha = 1;
  }
  if (T >= 1.4 && T < 3.8) {
    const k = (T - 1.4) / 2.4;
    for (const id of F.audience.slice(0, 90)) {
      const p = sc.agentPx(id);
      if (!p) continue;
      const [ax, ay] = toCv(p.x, p.y - 8);
      const tw = 0.5 + 0.5 * Math.sin(T * 9 + id);
      c.globalAlpha = Math.max(0, Math.min(1, (1 - k) * 1.4)) * tw;
      c.fillStyle = id % 2 ? col : "#fde68a";
      c.beginPath(); c.arc(ax, ay, 2.4 * d, 0, 7); c.fill();
    }
    c.globalAlpha = 1;
  }
  if (T >= 0.9 && T < 3.2) {
    const label = `🚀 ${F.name} launched`;
    c.globalAlpha = Math.min(1, (T - 0.9) * 4, (3.2 - T) * 3);
    c.font = `600 ${12 * d}px Inter`;
    const w = c.measureText(label).width + 22 * d, h = 24 * d, x = cx - w / 2, y = cy - 52 * d;
    c.fillStyle = "rgba(10,13,18,.82)"; c.strokeStyle = col; c.lineWidth = 1.5 * d;
    c.beginPath(); c.roundRect(x, y, w, h, h / 2); c.fill(); c.stroke();
    c.fillStyle = "#fff"; c.textAlign = "center"; c.textBaseline = "middle"; c.fillText(label, cx, y + h / 2 + d);
    c.globalAlpha = 1; c.textBaseline = "alphabetic";
  }
  return false; // frozen frames keep redrawing so late-loading sites and camera moves are reflected
}
