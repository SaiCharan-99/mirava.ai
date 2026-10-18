import type { TableDef } from "../../lib/survey";

/** Shared room geometry (metres): round tables on a ring, seats around each table, moderator seat at angle 0. */
export interface SeatPos { agent: number; x: number; z: number; angle: number; table: string; seat: number }
export interface TablePos { table_id: string; x: number; z: number; moderator: { x: number; z: number } }

export const TABLE_R = 1.15;
export const SEAT_R = 1.75;

export function layout(tables: TableDef[]): { tables: TablePos[]; seats: SeatPos[]; radius: number } {
  const n = tables.length;
  const ring = n <= 1 ? 0 : Math.max(4.2, (n * 4.6) / (2 * Math.PI));
  const tps: TablePos[] = [];
  const seats: SeatPos[] = [];
  tables.forEach((t, i) => {
    const a = n <= 1 ? 0 : (i / n) * Math.PI * 2 - Math.PI / 2;
    const cx = Math.cos(a) * ring, cz = Math.sin(a) * ring;
    const k = t.seats.length + 1;                       // +1 = moderator seat
    tps.push({ table_id: t.table_id, x: cx, z: cz, moderator: { x: cx + SEAT_R * Math.cos(-Math.PI / 2), z: cz + SEAT_R * Math.sin(-Math.PI / 2) } });
    t.seats.forEach((aid, j) => {
      const sa = -Math.PI / 2 + ((j + 1) / k) * Math.PI * 2;
      seats.push({ agent: aid, x: cx + SEAT_R * Math.cos(sa), z: cz + SEAT_R * Math.sin(sa), angle: sa, table: t.table_id, seat: j });
    });
  });
  return { tables: tps, seats, radius: ring + SEAT_R + 1.5 };
}

/** WebGL available (else the 2D view is used). */
export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export const reducedMotion = (): boolean => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
