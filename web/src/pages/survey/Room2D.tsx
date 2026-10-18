import type { RoomState, SurveyAgent, TableDef } from "../../lib/survey";
import { layout, TABLE_R } from "./roomLayout";

/** 2D top-down SVG room (no-WebGL fallback): same tables, seats, bubbles, ballots and note cards as the 3D view. */
export function Room2D({ tables, agents, st, selected, onSelect, privateText, mode }: {
  tables: TableDef[]; agents: Record<number, SurveyAgent>; st: RoomState; selected: number | null;
  onSelect: (id: number) => void; privateText: string | null; mode: string;
}) {
  const L = layout(tables);
  const R = L.radius;
  const sc = 40;
  const W = R * 2 * sc, H = R * 2 * sc;
  const X = (x: number) => (x + R) * sc, Y = (z: number) => (z + R) * sc;
  const ballot = st.phase === "ballot" || st.phase === "results";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" role="img" aria-label="Survey room, top view" style={{ display: "block" }}>
      <defs><radialGradient id="floor"><stop offset="0" stopColor="#2a2118" /><stop offset="1" stopColor="#14110d" /></radialGradient></defs>
      <rect width={W} height={H} fill="url(#floor)" rx={18} />
      {L.tables.map((t) => (
        <g key={t.table_id}>
          <circle cx={X(t.x)} cy={Y(t.z)} r={TABLE_R * sc} fill="#7c5a3a" stroke="#a87b4f" strokeWidth={2} />
          <text x={X(t.x)} y={Y(t.z) + 4} textAnchor="middle" fontSize={12} fill="#f5e6d3" fontWeight={700}>{t.table_id}</text>
          <circle cx={X(t.moderator.x)} cy={Y(t.moderator.z)} r={11} fill="#94a3b8" stroke={st.speaker[t.table_id] === "moderator" ? "#2dd4bf" : "none"} strokeWidth={3} />
          <text x={X(t.moderator.x)} y={Y(t.moderator.z) - 15} textAnchor="middle" fontSize={9} fill="#cbd5e1">moderator</text>
        </g>
      ))}
      {L.seats.map((s) => {
        const a = agents[s.agent];
        const speaking = st.speaker[s.table] === s.agent;
        const done = ballot && st.ballots.has(s.agent);
        return (
          <g key={s.agent} style={{ cursor: "pointer" }} onClick={() => onSelect(s.agent)}>
            <circle cx={X(s.x)} cy={Y(s.z)} r={12} fill={a?.color ?? "#64748b"} stroke={selected === s.agent ? "#fff" : speaking ? "#2dd4bf" : "#0b0f15"} strokeWidth={speaking || selected === s.agent ? 3 : 1.5} />
            <text x={X(s.x)} y={Y(s.z) + 24} textAnchor="middle" fontSize={9} fill="#e2e8f0">{a?.name.split(" ")[0] ?? s.agent}</text>
            {ballot && <text x={X(s.x) + 12} y={Y(s.z) - 8} fontSize={11} fill={done ? "#4ade80" : "#94a3b8"}>{done ? "✓" : "▢"}</text>}
          </g>
        );
      })}
      {L.tables.map((t) => {
        const bs = st.bubbles[t.table_id] ?? [];
        return bs.map((b, i) => {
          const seat = typeof b.speaker === "number" ? L.seats.find((s) => s.agent === b.speaker) : null;
          const x = seat ? X(seat.x) : X(t.moderator.x), y = (seat ? Y(seat.z) : Y(t.moderator.z)) - 30 - (bs.length - 1 - i) * 4;
          const text = b.text.length > 70 ? b.text.slice(0, 68) + "…" : b.text;
          return (
            <g key={b.message_id} opacity={0.55 + 0.45 * ((i + 1) / bs.length)}>
              <rect x={x - 90} y={y - 30} width={180} height={28} rx={8} fill="#f8fafc" stroke={i === bs.length - 1 ? "#2dd4bf" : "#cbd5e1"} />
              <foreignObject x={x - 86} y={y - 29} width={172} height={26}><div style={{ fontSize: 9, lineHeight: "12px", color: "#0f172a", overflow: "hidden", height: 26 }}>{text}</div></foreignObject>
            </g>
          );
        });
      })}
      {mode === "survey" && Object.entries(st.notes).slice(-6).map(([aid, note]) => {
        const s = L.seats.find((x) => x.agent === Number(aid));
        if (!s) return null;
        return <foreignObject key={aid} x={X(s.x) - 70} y={Y(s.z) - 60} width={140} height={36}><div style={{ background: "#fef3c7", color: "#422006", fontSize: 9, padding: 4, borderRadius: 4, boxShadow: "0 2px 6px rgba(0,0,0,.4)" }}>{note.slice(0, 80)}</div></foreignObject>;
      })}
      {privateText && selected != null && (() => {
        const s = L.seats.find((x) => x.agent === selected);
        if (!s) return null;
        return <foreignObject x={X(s.x) + 14} y={Y(s.z) - 10} width={190} height={60}><div style={{ border: "1.5px dashed var(--private)", background: "rgba(30,20,45,.92)", color: "#e9d5ff", fontSize: 9, padding: 5, borderRadius: 8 }}><b style={{ fontSize: 8, letterSpacing: ".05em" }}>PRIVATE THOUGHT</b><br />{privateText.slice(0, 120)}</div></foreignObject>;
      })()}
    </svg>
  );
}
