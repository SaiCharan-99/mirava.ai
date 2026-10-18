import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { RoomState, SurveyAgent, TableDef } from "../../lib/survey";
import { layout, reducedMotion, TABLE_R } from "./roomLayout";

interface Props {
  tables: TableDef[]; agents: Record<number, SurveyAgent>; st: RoomState; selected: number | null;
  onSelect: (id: number) => void; focusTable: string | null; onFocusTable: (t: string | null) => void;
  privateText: string | null; mode: string; frozen: boolean;
}

/** Instanced seated avatars: capsule bodies + sphere heads coloured from the agent palette (100 avatars stay smooth). */
function Avatars({ seats, agents, speaking, onSelect }: { seats: ReturnType<typeof layout>["seats"]; agents: Props["agents"]; speaking: Set<number>; onSelect: (id: number) => void }) {
  const body = useRef<THREE.InstancedMesh>(null);
  const head = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const m = new THREE.Matrix4(), c = new THREE.Color();
    seats.forEach((s, i) => {
      m.makeTranslation(s.x, 0.62, s.z);
      body.current?.setMatrixAt(i, m);
      m.makeTranslation(s.x, 1.18, s.z);
      head.current?.setMatrixAt(i, m);
      c.set(agents[s.agent]?.color ?? "#64748b");
      body.current?.setColorAt(i, c);
      c.set(speaking.has(s.agent) ? "#fde68a" : "#e8b98f");
      head.current?.setColorAt(i, c);
    });
    for (const r of [body, head]) {
      if (!r.current) continue;
      r.current.instanceMatrix.needsUpdate = true;
      if (r.current.instanceColor) r.current.instanceColor.needsUpdate = true;
    }
  }, [seats, agents, speaking]);
  const pick = (e: { instanceId?: number; stopPropagation: () => void }) => {
    e.stopPropagation();
    if (e.instanceId !== undefined && seats[e.instanceId]) onSelect(seats[e.instanceId].agent);
  };
  return (
    <>
      <instancedMesh ref={body} args={[undefined, undefined, Math.max(1, seats.length)]} onClick={pick} castShadow>
        <capsuleGeometry args={[0.2, 0.5, 4, 10]} /><meshStandardMaterial roughness={0.7} />
      </instancedMesh>
      <instancedMesh ref={head} args={[undefined, undefined, Math.max(1, seats.length)]} onClick={pick} castShadow>
        <sphereGeometry args={[0.17, 14, 12]} /><meshStandardMaterial roughness={0.6} />
      </instancedMesh>
    </>
  );
}

/** The glowing question card travels from the moderator to the seat currently responding. */
function QuestionCard({ from, to, frozen }: { from: [number, number]; to: [number, number] | null; frozen: boolean }) {
  const ref = useRef<THREE.Mesh>(null);
  const target = to ?? from;
  useFrame((_, dt) => {
    const m = ref.current;
    if (!m) return;
    const k = frozen || reducedMotion() ? 1 : Math.min(1, dt * 3);
    m.position.x += (target[0] - m.position.x) * k;
    m.position.z += (target[1] - m.position.z) * k;
    if (!frozen && !reducedMotion()) m.rotation.y += dt * 0.8;
  });
  return (
    <mesh ref={ref} position={[target[0], 0.95, target[1]]}>
      <boxGeometry args={[0.34, 0.02, 0.24]} />
      <meshStandardMaterial color="#2dd4bf" emissive="#2dd4bf" emissiveIntensity={1.6} />
    </mesh>
  );
}

export function Room3D(p: Props) {
  const L = useMemo(() => layout(p.tables), [p.tables]);
  const speaking = useMemo(() => new Set(Object.values(p.st.speaker).filter((x): x is number => typeof x === "number")), [p.st.speaker]);
  const ballot = p.st.phase === "ballot" || p.st.phase === "results";
  const focus = L.tables.find((t) => t.table_id === p.focusTable);
  const cam: [number, number, number] = focus ? [focus.x + 3.6, 4.2, focus.z + 4.6] : [0, L.radius * 1.55, L.radius * 1.75];
  return (
    <Canvas shadows camera={{ position: cam, fov: 42 }} dpr={[1, 2]} gl={{ preserveDrawingBuffer: true }} frameloop={p.frozen ? "demand" : "always"}
      onPointerMissed={() => p.onFocusTable(null)} key={p.focusTable ?? "all"}>
      <color attach="background" args={["#17120d"]} />
      <hemisphereLight args={["#ffe9c7", "#3b2a1a", 0.65]} />
      <directionalLight position={[6, 12, 4]} intensity={1.1} castShadow />
      <pointLight position={[0, 6, 0]} intensity={18} distance={30} color="#ffcf8a" />
      <mesh rotation-x={-Math.PI / 2} receiveShadow><circleGeometry args={[L.radius + 2, 48]} /><meshStandardMaterial color="#3a2a1d" roughness={0.9} /></mesh>
      {L.tables.map((t) => (
        <group key={t.table_id} onClick={(e) => { e.stopPropagation(); p.onFocusTable(t.table_id); }}>
          <mesh position={[t.x, 0.72, t.z]} castShadow receiveShadow><cylinderGeometry args={[TABLE_R, TABLE_R, 0.08, 36]} /><meshStandardMaterial color="#8a6340" roughness={0.5} /></mesh>
          <mesh position={[t.x, 0.36, t.z]}><cylinderGeometry args={[0.12, 0.2, 0.72, 12]} /><meshStandardMaterial color="#5b4129" /></mesh>
          <mesh position={[t.moderator.x, 0.62, t.moderator.z]}><capsuleGeometry args={[0.2, 0.5, 4, 10]} /><meshStandardMaterial color={p.st.speaker[t.table_id] === "moderator" ? "#2dd4bf" : "#94a3b8"} /></mesh>
          <Html position={[t.x, 0.8, t.z]} center distanceFactor={9}><div style={{ color: "#f5e6d3", fontWeight: 700, fontSize: 12, pointerEvents: "none" }}>{t.table_id}</div></Html>
          <QuestionCard frozen={p.frozen} from={[t.moderator.x, t.moderator.z]} to={(() => { const k = p.st.cardSeat[t.table_id]; const s = L.seats.filter((x) => x.table === t.table_id)[k]; return s ? [s.x * 0.62 + t.x * 0.38, s.z * 0.62 + t.z * 0.38] : null; })()} />
        </group>
      ))}
      <Avatars seats={L.seats} agents={p.agents} speaking={speaking} onSelect={p.onSelect} />
      {L.seats.map((s) => (
        <Html key={s.agent} position={[s.x, 1.5, s.z]} center distanceFactor={9} zIndexRange={[10, 0]}>
          <div style={{ pointerEvents: "none", textAlign: "center", whiteSpace: "nowrap" }}>
            <div style={{ fontSize: 10, color: p.selected === s.agent ? "#fff" : "#e2e8f0", fontWeight: speaking.has(s.agent) ? 700 : 500, textShadow: "0 1px 2px #000" }}>
              {p.agents[s.agent]?.name.split(" ")[0]}{ballot ? (p.st.ballots.has(s.agent) ? " ✓" : " ⧗") : ""}
            </div>
            {ballot && !p.st.ballots.has(s.agent) && <div title="tablet" style={{ margin: "2px auto 0", width: 14, height: 10, borderRadius: 2, background: "#0f172a", border: "1.5px solid #2dd4bf" }} />}
          </div>
        </Html>
      ))}
      {L.tables.map((t) => (p.st.bubbles[t.table_id] ?? []).map((b, i, arr) => {
        const seat = typeof b.speaker === "number" ? L.seats.find((s) => s.agent === b.speaker) : null;
        const pos: [number, number, number] = seat ? [seat.x, 2.05 + (arr.length - 1 - i) * 0.05, seat.z] : [t.moderator.x, 2.05, t.moderator.z];
        return (
          <Html key={b.message_id} position={pos} center distanceFactor={9} zIndexRange={[20, 10]}>
            <div className="survey-bubble" style={{ opacity: 0.5 + 0.5 * ((i + 1) / arr.length), width: 190, whiteSpace: "normal", background: "#f8fafc", color: "#0f172a", border: `1.5px solid ${i === arr.length - 1 ? "#2dd4bf" : "#cbd5e1"}`, borderRadius: 10, padding: "5px 8px", fontSize: 11, lineHeight: 1.3, boxShadow: "0 3px 10px rgba(0,0,0,.35)" }}>
              {b.text.length > 120 ? b.text.slice(0, 118) + "…" : b.text}
            </div>
          </Html>
        );
      }))}
      {p.mode === "survey" && Object.entries(p.st.notes).slice(-8).map(([aid, note]) => {
        const s = L.seats.find((x) => x.agent === Number(aid));
        return s ? <Html key={`n${aid}`} position={[s.x, 2.1, s.z]} center distanceFactor={9}><div style={{ background: "#fef3c7", color: "#422006", fontSize: 10, padding: "4px 6px", borderRadius: 4, width: 160, whiteSpace: "normal", boxShadow: "0 2px 8px rgba(0,0,0,.4)" }}>📝 {note.slice(0, 90)}</div></Html> : null;
      })}
      {p.privateText && p.selected != null && (() => {
        const s = L.seats.find((x) => x.agent === p.selected);
        return s ? <Html position={[s.x, 2.6, s.z]} center distanceFactor={9} zIndexRange={[30, 20]}><div style={{ border: "1.5px dashed var(--private)", background: "rgba(30,20,45,.94)", color: "#e9d5ff", fontSize: 11, padding: "6px 8px", borderRadius: 10, width: 220, whiteSpace: "normal" }}><b style={{ fontSize: 9, letterSpacing: ".05em" }}>PRIVATE THOUGHT</b><br />{p.privateText.slice(0, 160)}</div></Html> : null;
      })()}
      <OrbitControls makeDefault target={focus ? [focus.x, 0.8, focus.z] : [0, 0.6, 0]} maxPolarAngle={Math.PI / 2.2} enableDamping={!p.frozen} />
    </Canvas>
  );
}
