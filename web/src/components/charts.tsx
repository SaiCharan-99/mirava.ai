import type { ReactNode } from "react";

/** SVG/HTML chart helpers ported 1:1 from docs/ui-mockup.html (kpi, hbars, stackRow, line, vbars, heatTable). */
export const COLS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

export function Kpi({ l, v, d }: { l: ReactNode; v: ReactNode; d?: ReactNode }) {
  return <div className="card kpi"><div className="l">{l}</div><div className="v">{v}</div>{d ? <div className="d muted">{d}</div> : null}</div>;
}

export type HBar = [string, number, string?, number?];
export function HBars({ rows, max, unit = "%" }: { rows: HBar[]; max: number; unit?: string }) {
  return (
    <div className="list" style={{ gap: 9 }}>
      {rows.map((r, i) => (
        <div key={i}>
          <div className="row between small"><span>{r[0]}</span><b>{r[1]}{unit}{r[3] ? <> <span className="muted xs">(n={r[3]})</span></> : null}</b></div>
          <div className="bar" style={{ height: 9, marginTop: 3 }}><i style={{ width: `${(r[1] / max) * 100}%`, background: r[2] || COLS[i % 6] }} /></div>
        </div>
      ))}
    </div>
  );
}

export function StackRow({ label, parts, cols }: { label: string; parts: number[]; cols: string[] }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="small" style={{ marginBottom: 4 }}>{label}</div>
      <div style={{ display: "flex", height: 22, borderRadius: 6, overflow: "hidden" }}>
        {parts.map((p, i) => (
          <div key={i} style={{ width: `${p}%`, background: cols[i], color: "#05201c", fontSize: 10.5, fontWeight: 700, display: "grid", placeItems: "center" }}>{p > 7 ? `${p}%` : ""}</div>
        ))}
      </div>
    </div>
  );
}

export interface LineSeries { n: string; v: (number | null)[]; c?: string; dash?: string }
export interface LineEvent { i: number; t: string; c?: string }
export function LineChart({ series, w = 720, h = 230, labels = [], ymax = 100, events = [], unit = "%" }:
  { series: LineSeries[]; w?: number; h?: number; labels?: string[]; ymax?: number; events?: LineEvent[]; unit?: string }) {
  const pl = 36, pb = 24, pt = 12, pr = 12, iw = w - pl - pr, ih = h - pt - pb, n = series[0]?.v.length || 2;
  const x = (i: number) => pl + (i * iw) / Math.max(1, n - 1);
  const y = (v: number) => pt + ih - (v / ymax) * ih;
  return (
    <>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%">
        {[0, 1, 2, 3, 4].map((g) => {
          const gy = pt + (ih * g) / 4;
          return <g key={g}><line x1={pl} x2={w - pr} y1={gy} y2={gy} stroke="var(--line)" /><text x={4} y={gy + 4} fontSize={10}>{Math.round(ymax * (1 - g / 4))}{unit}</text></g>;
        })}
        {labels.map((l, i) => (l ? <text key={i} x={x(i)} y={h - 6} fontSize={10} textAnchor="middle">{l}</text> : null))}
        {events.map((e, k) => (
          <g key={k}>
            <line x1={x(e.i)} x2={x(e.i)} y1={pt} y2={pt + ih} stroke={e.c || "var(--amber)"} strokeDasharray="3 3" opacity={0.8} />
            <text x={x(e.i) + 4} y={pt + 10} fontSize={10} style={{ fill: e.c || "var(--amber)" }}>{e.t}</text>
          </g>
        ))}
        {series.map((se, k) => {
          const pts = se.v.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
          return <polyline key={k} fill="none" stroke={se.c || COLS[k]} strokeWidth={2.2} strokeDasharray={se.dash || ""} points={pts} />;
        })}
      </svg>
      <div className="legend">{series.map((se, k) => <span key={k}><i style={{ background: se.c || COLS[k] }} />{se.n}</span>)}</div>
    </>
  );
}

export type VBar = [string, number, string];
export function VBars({ rows, w = 520, h = 200, ymax = 100, unit = "%" }: { rows: VBar[]; w?: number; h?: number; ymax?: number; unit?: string }) {
  const pl = 30, pb = 34, pt = 10, iw = w - pl - 10, ih = h - pt - pb, bw = (iw / Math.max(1, rows.length)) * 0.56;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%">
      {[0, 1, 2, 3, 4].map((g) => {
        const gy = pt + (ih * g) / 4;
        return <g key={g}><line x1={pl} x2={w - 10} y1={gy} y2={gy} stroke="var(--line)" /><text x={2} y={gy + 4} fontSize={10}>{Math.round(ymax * (1 - g / 4))}{unit}</text></g>;
      })}
      {rows.map((r, i) => {
        const cx = pl + (iw * (i + 0.5)) / rows.length, bh = (r[1] / ymax) * ih;
        return (
          <g key={i}>
            <rect x={cx - bw / 2} y={pt + ih - bh} width={bw} height={bh} rx={4} fill={r[2]} />
            <text x={cx} y={pt + ih - bh - 5} fontSize={11} textAnchor="middle" style={{ fill: "var(--ink)", fontWeight: 600 }}>{r[1]}{unit}</text>
            <text x={cx} y={h - 14} fontSize={11} textAnchor="middle">{r[0]}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function HeatTable({ rows, cols, vals, unit = "%", max = 60, titles }:
  { rows: string[]; cols: string[]; vals: number[][]; unit?: string; max?: number; titles?: string[][] }) {
  return (
    <table className="heat">
      <tbody>
        <tr><th />{cols.map((c) => <th key={c} style={{ textAlign: "center" }}>{c}</th>)}</tr>
        {rows.map((r, i) => (
          <tr key={r}>
            <td style={{ textAlign: "left", fontWeight: 500 }}>{r}</td>
            {(vals[i] || []).map((v, j) => (
              <td key={j} title={titles?.[i]?.[j]} style={{ background: `color-mix(in srgb,var(--teal) ${Math.min(85, (v / max) * 85)}%,var(--panel2))`, color: v > max * 0.55 ? "#05201c" : "var(--ink)" }}>{v}{unit}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
