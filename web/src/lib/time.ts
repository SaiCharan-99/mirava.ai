/** Sim-time helpers mirroring shared/time.py: t = sim minutes since the world epoch (Day 1 = Monday). */
export const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export const dayOf = (t: number): number => Math.floor(t / 1440) + 1;
export const minuteOfDay = (t: number): number => ((t % 1440) + 1440) % 1440;

/** HH:MM clock time. */
export function hhmm(t: number): string {
  const m = minuteOfDay(t);
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(Math.floor(m % 60)).padStart(2, "0")}`;
}

/** "Day 23 · Tue 08:40". */
export function fmt(t: number): string {
  return `Day ${dayOf(t)} · ${DAYS[Math.floor(t / 1440) % 7]} ${hhmm(t)}`;
}

/** Short ticker label "D23 08:40". */
export const shortT = (t: number): string => `D${dayOf(t)} ${hhmm(t)}`;

/** Indian-grouped integer, e.g. 9,338. */
export const fmtInt = (n: number): string => Math.round(n).toLocaleString("en-IN");

/** Rupees, e.g. ₹24,999. */
export const fmtINR = (n: number): string => "₹" + Math.round(n).toLocaleString("en-IN");

/** Darkness of the night overlay for an hour of day (0–24), same curve as the mockup. */
export function nightAlpha(hour: number): number {
  const h = ((hour % 24) + 24) % 24;
  if (h >= 7 && h <= 17.5) return 0;
  if (h > 17.5 && h < 20) return ((h - 17.5) / 2.5) * 0.58;
  if (h >= 20 || h < 5) return 0.58;
  return ((7 - h) / 2) * 0.58;
}
