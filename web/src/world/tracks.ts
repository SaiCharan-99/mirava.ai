import type { LiveAgent, LiveSegment } from "../lib/live";

/** One agent's live position plus its queue of upcoming movement segments (metres, sim minutes). */
export interface Track { id: number; x: number; y: number; h: number; mode: string; act: string; moving: boolean; segs: LiveSegment[] }

/** All tracks, keyed by agent id. Lives outside React so the 60 fps loop never re-renders components. */
export class Tracks {
  readonly byId = new Map<number, Track>();

  /** Replace everything from a `hello` frame. */
  reset(agents: LiveAgent[], segs: LiveSegment[]): void {
    this.byId.clear();
    for (const a of agents) this.byId.set(a.id, { id: a.id, x: a.x, y: a.y, h: a.h ?? 0, mode: a.mode ?? "walk", act: a.act ?? "", moving: false, segs: [] });
    this.push(segs);
  }

  /** Drop queued segments of these agents (their route was re-timed: they stopped to talk). */
  replace(ids: number[]): void {
    for (const id of ids) {
      const tr = this.byId.get(id);
      if (tr) tr.segs.length = 0;
    }
  }

  /** Append segments (kept sorted by start time per agent). */
  push(segs: LiveSegment[]): void {
    for (const s of segs) {
      let tr = this.byId.get(s.a);
      if (!tr) {
        tr = { id: s.a, x: s.x0, y: s.y0, h: 0, mode: s.mode, act: "", moving: false, segs: [] };
        this.byId.set(s.a, tr);
      }
      const q = tr.segs;
      if (!q.length || q[q.length - 1].t0 <= s.t0) q.push(s);
      else {
        q.push(s);
        q.sort((p, r) => p.t0 - r.t0);
      }
      if (q.length > 64) q.splice(0, q.length - 64);
    }
  }

  /** Advance every track to sim time t. */
  advance(t: number): void {
    for (const tr of this.byId.values()) step(tr, t);
  }
}

/** Interpolate one track to sim time t, consuming finished segments. */
export function step(tr: Track, t: number): void {
  const q = tr.segs;
  while (q.length && q[0].t1 <= t) {
    const s = q.shift()!;
    tr.x = s.x1;
    tr.y = s.y1;
    tr.mode = s.mode;
  }
  tr.moving = false;
  const s = q[0];
  if (!s || s.t0 > t) return;
  const span = s.t1 - s.t0;
  const f = span > 0 ? (t - s.t0) / span : 1;
  tr.x = s.x0 + (s.x1 - s.x0) * f;
  tr.y = s.y0 + (s.y1 - s.y0) * f;
  tr.mode = s.mode;
  tr.moving = true;
  if (s.x1 !== s.x0 || s.y1 !== s.y0) tr.h = (Math.atan2(s.x1 - s.x0, -(s.y1 - s.y0)) * 180) / Math.PI;
}

/** Sim clock extrapolated between `clock` frames. */
export class SimClock {
  private t0 = 0;
  private wall0 = 0;
  rate = 0.4; // sim minutes per real second
  frozen = false;

  set(t: number, now = performance.now()): void {
    this.t0 = t;
    this.wall0 = now;
  }

  now(wall = performance.now()): number {
    return this.frozen ? this.t0 : this.t0 + ((wall - this.wall0) / 1000) * this.rate;
  }
}

export const tracks = new Tracks();
export const simClock = new SimClock();
