/** Knowledge graph (L-04, INTERFACES §6.6): Obsidian-style force graph on canvas — physics, drag, wheel zoom around the
 * cursor, pan, hover neighbours, labels by zoom/degree, search, legend filters, Global/Local, re-layout, fit, details. */
import { useEffect, useRef, useState } from "react";
import type { GraphV, Risk } from "../lib/studio";
import { isVisualTest } from "../lib/visualTest";

const RISK: Record<Risk, string> = { red: "#f87171", amber: "#f5b041", green: "#4ade80" };

interface N { id: string; label: string; type: string; desc: string; src: string; risk?: Risk; x: number; y: number; vx: number; vy: number; fade: number; deg: number; nb: Set<N> }
interface E { s: N; t: N; rel: string }

function mulberry(a: number): () => number {
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const clamp = (v: number, a: number, b: number): number => Math.max(a, Math.min(b, v));
const css = (v: string): string => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

/** The graph engine (one per mounted GraphView); exposed for __ll.graphSelect / graphHover. */
export class KGEngine {
  cv: HTMLCanvasElement | null = null;
  ctx: CanvasRenderingContext2D | null = null;
  nodes: N[] = [];
  edges: E[] = [];
  byId: Record<string, N> = {};
  alpha = 1; zoom = 1; ox = 0; oy = 0; W = 0; H = 0; dpr = 1;
  hover: N | null = null;
  sel: N | null = null;
  drag: { node: N; moved: boolean } | null = null;
  pan: { x: number; y: number; ox: number; oy: number; moved: boolean } | null = null;
  filter: Set<string>;
  q = "";
  mode: "global" | "local" = "global";
  autoFit = false;
  anim: { s: { z: number; ox: number; oy: number; t0: number }; e: { z: number; ox: number; oy: number } } | null = null;
  onChange: () => void = () => {};
  tip: { x: number; y: number; n: N } | null = null;
  private raf = 0;
  private root: string;

  constructor(g: GraphV, public types: Record<string, { c: string; n: string }>) {
    this.filter = new Set(Object.keys(types));
    const r = mulberry(7);
    this.nodes = g.nodes.map((n) => ({ ...n, x: (r() - 0.5) * 400, y: (r() - 0.5) * 300, vx: 0, vy: 0, fade: 1, deg: 0, nb: new Set<N>() }));
    for (const n of this.nodes) this.byId[n.id] = n;
    this.edges = g.edges.filter(([a, b]) => this.byId[a] && this.byId[b]).map(([a, b, rel]) => ({ s: this.byId[a], t: this.byId[b], rel }));
    for (const e of this.edges) { e.s.deg++; e.t.deg++; e.s.nb.add(e.t); e.t.nb.add(e.s); }
    this.root = (this.nodes.find((n) => n.type === "product") ?? this.nodes[0])?.id ?? "";
  }

  mount(cv: HTMLCanvasElement): void {
    this.cv = cv;
    this.ctx = cv.getContext("2d");
    this.resize();
    this.alpha = 1;
    if (isVisualTest) { for (let i = 0; i < 420; i++) this.step(); this.alpha = 0; }
    this.fit(true);
    this.autoFit = !isVisualTest;
    const loop = () => { this.frame(); this.raf = requestAnimationFrame(loop); };
    this.raf = requestAnimationFrame(loop);
  }

  unmount(): void { cancelAnimationFrame(this.raf); this.cv = null; }

  resize(): void {
    if (!this.cv) return;
    const r = this.cv.getBoundingClientRect();
    this.dpr = window.devicePixelRatio || 1;
    this.cv.width = r.width * this.dpr;
    this.cv.height = r.height * this.dpr;
    this.W = r.width;
    this.H = r.height;
  }

  radius(n: N): number { return n.type === "product" ? 14 : 4 + Math.sqrt(n.deg) * 2.4; }
  color(n: N): string { return n.type === "claim" ? RISK[n.risk ?? "amber"] : this.types[n.type]?.c ?? "#94a3b8"; }
  visible(n: N): boolean {
    if (!this.filter.has(n.type)) return false;
    if (this.mode === "local") {
      const c = this.sel ?? this.byId[this.root];
      if (!c || n === c || c.nb.has(n)) return true;
      for (const m of c.nb) if (m.nb.has(n)) return true;
      return false;
    }
    return true;
  }

  step(): void {
    const Ns = this.nodes.filter((n) => this.visible(n));
    const a = this.alpha;
    for (let i = 0; i < Ns.length; i++) for (let j = i + 1; j < Ns.length; j++) {
      const p = Ns[i], q = Ns[j];
      let dx = q.x - p.x, dy = q.y - p.y;
      const d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2);
      const f = (5200 / d2) * a;
      dx /= d; dy /= d;
      p.vx -= dx * f; p.vy -= dy * f; q.vx += dx * f; q.vy += dy * f;
      const minD = this.radius(p) + this.radius(q) + 6;
      if (d < minD) { const o = (minD - d) * 0.5; p.x -= dx * o; p.y -= dy * o; q.x += dx * o; q.y += dy * o; }
    }
    for (const e of this.edges) {
      if (!this.visible(e.s) || !this.visible(e.t)) continue;
      const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.hypot(dx, dy) || 1;
      const L = e.s.type === "product" || e.t.type === "product" ? 120 : 90;
      const f = (d - L) * 0.045 * a;
      const ux = (dx / d) * f, uy = (dy / d) * f;
      e.s.vx += ux; e.s.vy += uy; e.t.vx -= ux; e.t.vy -= uy;
    }
    for (const n of Ns) {
      n.vx -= n.x * 0.008 * a; n.vy -= n.y * 0.008 * a;
      if (n === this.drag?.node) { n.vx = n.vy = 0; continue; }
      n.vx *= 0.78; n.vy *= 0.78; n.x += n.vx; n.y += n.vy;
    }
    this.alpha = Math.max(0, this.alpha * 0.986);
  }

  s2w(x: number, y: number): [number, number] { return [(x - this.ox) / this.zoom, (y - this.oy) / this.zoom]; }

  fit(instant = false): void {
    const Ns = this.nodes.filter((n) => this.visible(n));
    if (!Ns.length) return;
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const n of Ns) { x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y); }
    const z = Math.min(1.5, Math.min((this.W - 100) / (x1 - x0 + 1), (this.H - 130) / (y1 - y0 + 1)));
    this.animateTo(z, this.W / 2 - ((x0 + x1) / 2) * z, this.H / 2 + 18 - ((y0 + y1) / 2) * z, instant);
  }

  focus(n: N): void { const z = Math.max(this.zoom, 1.9); this.animateTo(z, this.W / 2 - n.x * z, this.H / 2 - n.y * z); }

  animateTo(z: number, ox: number, oy: number, instant = false): void {
    if (instant || isVisualTest) { this.zoom = z; this.ox = ox; this.oy = oy; return; }
    this.anim = { s: { z: this.zoom, ox: this.ox, oy: this.oy, t0: performance.now() }, e: { z, ox, oy } };
  }

  frame(): void {
    const cv = this.cv, c = this.ctx;
    if (!cv || !c) return;
    if (this.alpha > 0.004) this.step();
    if (this.autoFit && this.alpha < 0.06) { this.autoFit = false; this.fit(); }
    if (this.anim) {
      const k = Math.min(1, (performance.now() - this.anim.s.t0) / 450), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      const { s, e: t } = this.anim;
      this.zoom = s.z + (t.z - s.z) * e; this.ox = s.ox + (t.ox - s.ox) * e; this.oy = s.oy + (t.oy - s.oy) * e;
      if (k >= 1) this.anim = null;
    }
    const d = this.dpr;
    const T = { line: css("--line2") || "#2f3d50", muted: css("--muted") || "#7f8ea3", ink: css("--ink") || "#fff", ink2: css("--ink2") || "#b3c0d0" };
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, cv.width, cv.height);
    c.setTransform(d * this.zoom, 0, 0, d * this.zoom, d * this.ox, d * this.oy);
    const focus = this.hover ?? this.sel;
    const nb = focus ? focus.nb : new Set<N>();
    const q = this.q.toLowerCase();
    const isLit = (n: N) => (!focus && !q ? true : q ? n.label.toLowerCase().includes(q) : n === focus || nb.has(n));
    for (const n of this.nodes) { const target = this.visible(n) ? (isLit(n) ? 1 : 0.12) : 0; n.fade += (target - n.fade) * (isVisualTest ? 1 : 0.18); }
    for (const e of this.edges) {
      const a = Math.min(e.s.fade, e.t.fade);
      if (a < 0.02) continue;
      const lit = !!focus && (e.s === focus || e.t === focus);
      c.strokeStyle = lit ? this.color(focus === e.s ? e.t : e.s) : T.line;
      c.globalAlpha = lit ? 0.9 : a * 0.55;
      c.lineWidth = ((lit ? 1.6 : 0.8) / this.zoom) * 1.2;
      c.beginPath(); c.moveTo(e.s.x, e.s.y); c.lineTo(e.t.x, e.t.y); c.stroke();
      if (lit) {
        c.globalAlpha = 0.95; c.font = `${10 / this.zoom}px Inter`; c.textAlign = "center"; c.fillStyle = T.muted;
        c.fillText(e.rel.replace(/_/g, " ").toLowerCase(), (e.s.x + e.t.x) / 2, (e.s.y + e.t.y) / 2 - 3 / this.zoom);
      }
    }
    for (const n of this.nodes) {
      if (n.fade < 0.02) continue;
      const r = this.radius(n);
      c.globalAlpha = n.fade;
      if (n === focus || n === this.sel) {
        c.fillStyle = this.color(n); c.globalAlpha = 0.18 * n.fade; c.beginPath(); c.arc(n.x, n.y, r + 8, 0, 7); c.fill(); c.globalAlpha = n.fade;
      }
      c.fillStyle = this.color(n); c.beginPath(); c.arc(n.x, n.y, r, 0, 7); c.fill();
      if (n === this.sel) { c.strokeStyle = T.ink; c.lineWidth = 2 / this.zoom; c.stroke(); }
      const hit = !!q && n.label.toLowerCase().includes(q);
      if (hit) { c.strokeStyle = "#f5b041"; c.lineWidth = 2 / this.zoom; c.beginPath(); c.arc(n.x, n.y, r + 4, 0, 7); c.stroke(); }
      const show = this.zoom > 1.7 || n.type === "product" || n === focus || nb.has(n) || hit || (!focus && n.deg >= 5);
      if (show) {
        const fs = 11 / this.zoom;
        c.font = `${n === focus ? 600 : 500} ${fs}px Inter`; c.textAlign = "center"; c.fillStyle = T.ink2;
        c.globalAlpha = n.fade * (this.zoom > 1.7 || n === focus || nb.has(n) || n.type === "product" ? 1 : 0.7);
        c.fillText(n.label.length > 34 ? n.label.slice(0, 32) + "…" : n.label, n.x, n.y + r + fs * 1.25);
      }
    }
    c.globalAlpha = 1;
  }

  pick(clientX: number, clientY: number): N | null {
    if (!this.cv) return null;
    const r = this.cv.getBoundingClientRect();
    const [x, y] = this.s2w(clientX - r.left, clientY - r.top);
    let best: N | null = null, bd = 1e9;
    for (const n of this.nodes) {
      if (n.fade < 0.3) continue;
      const d = Math.hypot(n.x - x, n.y - y);
      if (d < this.radius(n) + 6 / this.zoom && d < bd) { bd = d; best = n; }
    }
    return best;
  }

  down(e: React.MouseEvent): void {
    this.autoFit = false;
    const best = this.pick(e.clientX, e.clientY);
    if (best) { this.drag = { node: best, moved: false }; this.alpha = Math.max(this.alpha, 0.35); }
    else this.pan = { x: e.clientX, y: e.clientY, ox: this.ox, oy: this.oy, moved: false };
  }

  move(e: React.MouseEvent): void {
    const cv = this.cv!;
    const r = cv.getBoundingClientRect();
    if (this.drag) {
      const [x, y] = this.s2w(e.clientX - r.left, e.clientY - r.top);
      this.drag.node.x = x; this.drag.node.y = y; this.drag.moved = true; this.alpha = Math.max(this.alpha, 0.3);
      return;
    }
    if (this.pan) { this.ox = this.pan.ox + e.clientX - this.pan.x; this.oy = this.pan.oy + e.clientY - this.pan.y; this.pan.moved = true; return; }
    const best = this.pick(e.clientX, e.clientY);
    this.setHover(best, best ? { x: e.clientX - r.left + 14, y: e.clientY - r.top + 14 } : null);
    cv.style.cursor = best ? "pointer" : "grab";
  }

  setHover(n: N | null, at: { x: number; y: number } | null): void {
    this.hover = n;
    this.tip = n && at ? { ...at, n } : null;
    this.onChange();
  }

  up(): void {
    if (this.drag) { if (!this.drag.moved) this.select(this.drag.node); this.drag = null; }
    else if (this.pan) { if (!this.pan.moved) this.select(null); this.pan = null; }
  }

  leave(): void { this.drag = null; this.pan = null; this.setHover(null, null); }

  dbl(e: React.MouseEvent): void {
    const best = this.pick(e.clientX, e.clientY);
    if (best) { this.select(best); this.focus(best); } else this.fit();
  }

  wheel(e: WheelEvent): void {
    e.preventDefault();
    this.autoFit = false;
    const r = this.cv!.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const z = clamp(this.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12), 0.3, 4);
    this.ox = mx - (mx - this.ox) * (z / this.zoom);
    this.oy = my - (my - this.oy) * (z / this.zoom);
    this.zoom = z;
    this.anim = null;
  }

  select(n: N | null): void { this.sel = n; if (this.mode === "local") this.alpha = 0.6; this.onChange(); }
  setMode(m: "global" | "local"): void { this.mode = m; this.alpha = 0.8; this.onChange(); setTimeout(() => this.fit(), 350); }
  search(v: string): void {
    this.q = v.trim();
    const hit = this.q ? this.nodes.find((n) => n.label.toLowerCase().includes(this.q.toLowerCase())) : undefined;
    if (hit) this.focus(hit);
  }
  reheat(): void { for (const n of this.nodes) { n.x += (Math.random() - 0.5) * 40; n.y += (Math.random() - 0.5) * 40; } this.alpha = 1; }
  toggleType(t: string): void { if (this.filter.has(t)) this.filter.delete(t); else this.filter.add(t); this.alpha = Math.max(this.alpha, 0.5); this.onChange(); }
}

/** The mounted engine (for window.__ll). */
export const graphRef: { kg: KGEngine | null } = { kg: null };

const typeLabel = (kg: KGEngine, n: N): string => (n.type === "claim" ? `Claim · ${n.risk} risk` : kg.types[n.type]?.n ?? n.type);

function Details({ kg }: { kg: KGEngine }) {
  const n = kg.sel;
  if (!n) {
    return (
      <>
        <h3>Graph</h3>
        <div className="grid g2 small"><div className="item">Nodes<br /><b className="mono">{kg.nodes.length}</b></div><div className="item">Links<br /><b className="mono">{kg.edges.length}</b></div></div>
        <h3 style={{ marginTop: 14 }}>How to explore</h3>
        <div className="list small">
          <div className="item">🖱 <b>Drag</b> a node — the graph reacts</div>
          <div className="item">🔍 <b>Scroll</b> to zoom · drag background to pan</div>
          <div className="item">✨ <b>Hover</b> to highlight a node's links</div>
          <div className="item">👆 <b>Click</b> for details · <b>double-click</b> to focus</div>
          <div className="item">◎ <b>Local</b> shows 2 hops around the selection</div>
          <div className="item">● Click legend items to filter types</div>
        </div>
        <p className="xs muted" style={{ marginTop: 10 }}>After launch, agents' thoughts and conversation lines link back to these nodes (claim traceability).</p>
      </>
    );
  }
  const links = kg.edges.filter((e) => e.s === n || e.t === n);
  return (
    <>
      <div className="row" style={{ gap: 8 }}><span style={{ width: 12, height: 12, borderRadius: "50%", background: kg.color(n), display: "inline-block" }} />
        <span className="xs muted" style={{ textTransform: "uppercase", letterSpacing: ".06em" }}>{typeLabel(kg, n)}</span></div>
      <h2 style={{ margin: "6px 0 4px" }}>{n.label}</h2><p className="small muted" style={{ margin: "0 0 10px" }}>{n.desc}</p>
      {n.src && <div className="item small">📄 Source: <span className="mono">{n.src}</span></div>}
      <div className="item small" style={{ marginTop: 8 }}>💬 Mentions in thoughts and chats are counted after launch <span className="sim-badge" style={{ marginLeft: 4 }}>SIM</span></div>
      <h3 style={{ marginTop: 14 }}>Linked ({n.nb.size})</h3>
      <div className="list small">
        {links.map((e, i) => {
          const o = e.s === n ? e.t : e.s;
          return (
            <div key={i} className="item row between" style={{ cursor: "pointer" }} onClick={() => { kg.select(o); kg.focus(o); }}>
              <span><i style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: kg.color(o), marginRight: 6 }} />{o.label.length > 30 ? o.label.slice(0, 28) + "…" : o.label}</span>
              <span className="xs muted">{e.rel.replace(/_/g, " ").toLowerCase()}</span>
            </div>
          );
        })}
      </div>
      <button className="btn sm" style={{ marginTop: 12 }} onClick={() => kg.select(null)}>Clear selection</button>
    </>
  );
}

/** `knowledge-graph` card. */
export function GraphView({ graph, types }: { graph: GraphV; types: Record<string, { c: string; n: string }> }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const [kg] = useState(() => new KGEngine(graph, types));
  const [, force] = useState(0);
  const [mode, setMode] = useState<"global" | "local">("global");
  useEffect(() => {
    kg.onChange = () => force((x) => x + 1);
    kg.mount(cv.current!);
    graphRef.kg = kg;
    const c = cv.current!;
    const wh = (e: WheelEvent) => kg.wheel(e);
    c.addEventListener("wheel", wh, { passive: false });
    const ro = new ResizeObserver(() => kg.resize());
    ro.observe(c);
    return () => { kg.unmount(); c.removeEventListener("wheel", wh); ro.disconnect(); if (graphRef.kg === kg) graphRef.kg = null; };
  }, [kg]);
  return (
    <div className="card" style={{ marginTop: 14, padding: 0, overflow: "hidden" }} data-testid="knowledge-graph">
      <div className="row between" data-testid="graph-toolbar" style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
        <div className="row" style={{ gap: 10 }}><h2 style={{ margin: 0 }}>Product knowledge graph</h2><span className="chip">{kg.nodes.length} nodes · {kg.edges.length} links</span>
          <span className="xs muted">drag · scroll · hover · double-click</span></div>
        <div className="row" style={{ gap: 8 }}>
          <input data-testid="graph-search" placeholder="Search nodes…" style={{ width: 200 }} onChange={(e) => kg.search(e.target.value)} />
          <div className="seg" data-testid="graph-mode">
            <button className={mode === "global" ? "on" : ""} onClick={() => { setMode("global"); kg.setMode("global"); }}>Global</button>
            <button className={mode === "local" ? "on" : ""} onClick={() => { setMode("local"); kg.setMode("local"); }}>Local</button>
          </div>
          <button className="btn sm" onClick={() => kg.reheat()}>⟳ Re-layout</button><button className="btn sm" onClick={() => kg.fit()}>⤢ Fit</button>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", height: 520 }}>
        <div style={{ position: "relative", background: "var(--bg)" }}>
          <canvas ref={cv} data-testid="graph-canvas" style={{ width: "100%", height: "100%", display: "block", cursor: "grab" }}
            onMouseDown={(e) => kg.down(e)} onMouseMove={(e) => kg.move(e)} onMouseUp={() => kg.up()} onMouseLeave={() => kg.leave()} onDoubleClick={(e) => kg.dbl(e)} />
          <div className="legend glass" data-testid="graph-legend" style={{ position: "absolute", left: 12, top: 12, padding: "6px 10px" }}>
            {Object.entries(types).map(([k, v]) => (
              <span key={k} style={{ cursor: "pointer", opacity: kg.filter.has(k) ? 1 : 0.35 }} onClick={() => kg.toggleType(k)}>
                <i style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: k === "claim" ? "linear-gradient(90deg,#f87171 33%,#f5b041 33% 66%,#4ade80 66%)" : v.c, marginRight: 5, verticalAlign: 0 }} />{v.n}
              </span>
            ))}
          </div>
          <div className={`kg-tip ${kg.tip ? "" : "hidden"}`} style={kg.tip ? { left: kg.tip.x, top: kg.tip.y } : undefined}>
            {kg.tip && <><b>{kg.tip.n.label}</b><div className="muted xs">{typeLabel(kg, kg.tip.n)} · {kg.tip.n.deg} links</div></>}
          </div>
        </div>
        <div data-testid="graph-details" style={{ borderLeft: "1px solid var(--line)", padding: 16, overflow: "auto" }}><Details kg={kg} /></div>
      </div>
    </div>
  );
}
