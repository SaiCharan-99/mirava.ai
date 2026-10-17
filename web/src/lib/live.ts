/** world-engine `/live` WebSocket protocol (INTERFACES §4.4): message types, parsing and a reconnecting client. */

export interface LiveAgent { id: number; x: number; y: number; h: number; mode: string; act: string }
export interface LiveSegment { a: number; x0: number; y0: number; x1: number; y1: number; t0: number; t1: number; mode: string }
export interface LiveProduct { id: string; name: string; color: string; launched_at_t: number | null }
export interface LiveCounts {
  agents: number; households: number; relationships: number; conversations_today: number;
  conversations_total: number; thoughts_today: number; products_live: number;
}
export interface LiveStats { t: number; counts: LiveCounts; budget?: { used_usd: number; cap_usd: number }; awareness?: Record<string, number> }
export type LiveEvt = { k: string; a?: number; b?: number; text?: string; product?: string | null; [key: string]: unknown };

export type LiveMsg =
  | { type: "hello"; t: number; scale: { sim_min_per_real_s: number }; slowed: boolean; agents: LiveAgent[];
      segments: LiveSegment[]; bubbles: LiveEvt[]; products: LiveProduct[]; sites: unknown[]; stats?: LiveStats | Partial<LiveCounts> }
  | { type: "seg"; items: LiveSegment[] }
  | { type: "evt"; items: LiveEvt[] }
  | ({ type: "stats" } & LiveStats)
  | { type: "clock"; t: number; speed: number };

const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Parse one frame; returns null for anything malformed or unknown (never throws). */
export function parseLive(raw: string): LiveMsg | null {
  let m: any;
  try {
    m = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!m || typeof m !== "object" || typeof m.type !== "string") return null;
  switch (m.type) {
    case "hello":
      if (!num(m.t)) return null;
      return {
        type: "hello", t: m.t, scale: { sim_min_per_real_s: num(m.scale?.sim_min_per_real_s) ? m.scale.sim_min_per_real_s : 0.4 },
        slowed: !!m.slowed, agents: Array.isArray(m.agents) ? m.agents.filter((a: any) => num(a?.id) && num(a?.x) && num(a?.y)) : [],
        segments: Array.isArray(m.segments) ? m.segments.filter(isSeg) : [], bubbles: Array.isArray(m.bubbles) ? m.bubbles : [],
        products: Array.isArray(m.products) ? m.products : [], sites: Array.isArray(m.sites) ? m.sites : [], stats: m.stats,
      };
    case "seg":
      return Array.isArray(m.items) ? { type: "seg", items: m.items.filter(isSeg) } : null;
    case "evt":
      return Array.isArray(m.items) ? { type: "evt", items: m.items.filter((e: any) => e && typeof e.k === "string") } : null;
    case "stats":
      return m.counts && typeof m.counts === "object" ? { type: "stats", t: num(m.t) ? m.t : 0, counts: m.counts, budget: m.budget, awareness: m.awareness } : null;
    case "clock":
      return num(m.t) ? { type: "clock", t: m.t, speed: num(m.speed) ? m.speed : 1 } : null;
    default:
      return null;
  }
}

function isSeg(s: any): s is LiveSegment {
  return !!s && num(s.a) && num(s.x0) && num(s.y0) && num(s.x1) && num(s.y1) && num(s.t0) && num(s.t1);
}

/** Reconnect delay: exponential backoff 1 s → 30 s cap. */
export const backoffMs = (attempt: number): number => Math.min(30000, 1000 * 2 ** Math.min(attempt, 5));

/** Engine WebSocket URL (VITE_ENGINE_WS overrides the local default). */
export function liveUrl(): string {
  const base = (import.meta.env?.VITE_ENGINE_WS as string | undefined) || "ws://localhost:8100";
  return `${base.replace(/\/$/, "")}/live`;
}

/** WebSocket to /live that reconnects with backoff and hands parsed frames to `onMsg`. */
export class LiveClient {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(private url: string, private onMsg: (m: LiveMsg) => void, private onStatus: (up: boolean) => void = () => {}) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
  }

  private connect(): void {
    if (this.stopped || typeof WebSocket === "undefined") return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.retry();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.onStatus(true);
    };
    ws.onmessage = (e) => {
      const m = typeof e.data === "string" ? parseLive(e.data) : null;
      if (m) {
        try {
          this.onMsg(m);
        } catch (err) {
          console.warn("[live] handler error", err);
        }
      }
    };
    ws.onerror = () => ws.close();
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      this.onStatus(false);
      this.retry();
    };
  }

  private retry(): void {
    if (this.stopped) return;
    this.timer = setTimeout(() => this.connect(), backoffMs(this.attempt++));
  }
}
