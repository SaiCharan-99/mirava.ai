import createGlobe from "cobe";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWorld } from "../state/world";
import { dayOf, fmtInt } from "../lib/time";
import { isVisualTest, withMode } from "../lib/visualTest";

const INTRO_KEY = "mirava_intro";
export const BENGALURU: [number, number] = [12.9719, 77.6412];

/** True once the intro was seen (or skipped) in this browser session. */
export function introSeen(): boolean {
  try {
    return sessionStorage.getItem(INTRO_KEY) === "1";
  } catch {
    return false;
  }
}

/** WebGL availability (no WebGL → straight to the World). */
export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

/** cobe angles that put a lat/lon at the centre of the globe. */
export function anglesFor([lat, lon]: [number, number]): [number, number] {
  return [Math.PI - ((lon * Math.PI) / 180 - Math.PI / 2), (lat * Math.PI) / 180];
}

/** One frame of the fly-to rotation: ease towards the target longitude angle, then hold. */
export function stepPhi(phi: number, target: number): number {
  const d = ((((target - phi + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) - Math.PI;
  return Math.abs(d) > 0.002 ? phi + d * 0.02 + Math.sign(d) * 0.0015 : phi;
}

/** Globe intro (W-01): rotating dotted globe → Bengaluru, stats card, Enter world (zoom + cross-fade) / Skip. */
export function GlobeIntro() {
  const cv = useRef<HTMLCanvasElement>(null);
  const nav = useNavigate();
  const [leaving, setLeaving] = useState(false);
  const t = useWorld((s) => s.t);
  const stats = useWorld((s) => s.stats);

  useEffect(() => {
    if (!cv.current || !hasWebGL()) return;
    const [targetPhi, targetTheta] = anglesFor(BENGALURU);
    let phi = isVisualTest ? targetPhi : targetPhi - 2.4;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const globe = createGlobe(cv.current, {
      devicePixelRatio: dpr, width: 720 * dpr, height: 720 * dpr, phi, theta: targetTheta * 0.9, dark: 1,
      diffuse: 1.2, mapSamples: 16000, mapBrightness: 5.5, baseColor: [0.07, 0.12, 0.17],
      markerColor: [45 / 255, 212 / 255, 191 / 255], glowColor: [0.1, 0.28, 0.3], scale: 1,
      markers: [{ location: BENGALURU, size: 0.06 }],
      onRender: (state) => {
        if (!isVisualTest) phi = stepPhi(phi, targetPhi);
        state.phi = phi;
      },
    });
    return () => globe.destroy();
  }, []);

  const enter = (skip: boolean) => {
    try {
      sessionStorage.setItem(INTRO_KEY, "1");
    } catch {
      /* private mode */
    }
    if (skip || isVisualTest) return nav(withMode("/world"));
    setLeaving(true);
    window.setTimeout(() => {
      nav(withMode("/world"));
      useWorld.getState().camera({ kind: "focus", z: 1.6 });
    }, 850);
  };

  return (
    <div className={`globe${leaving ? " leaving" : ""}`} data-testid="globe-intro">
      <div style={{ position: "relative", display: "grid", placeItems: "center" }}>
        <canvas ref={cv} data-testid="globe-canvas" style={{ width: 720, height: 720 }} onClick={() => enter(false)} />
        <div className="gpin" style={{ left: "50%", top: "50%", transform: "translate(-50%,26px)" }}>
          <span className="chip teal" style={{ background: "rgba(10,13,18,.8)" }}>
            <span className="dotlive" />Indiranagar · {fmtInt(stats.agents)} agents · live</span>
        </div>
      </div>
      <div className="gcard" data-testid="globe-card">
        <div className="kick"><span className="dotlive" />Agent world · always on</div>
        <h1>A city of 1,000 AI people, living right now.</h1>
        <p className="muted" style={{ fontSize: 15, margin: 0 }}>Indiranagar, Bengaluru. They work, commute, scroll, talk
          to each other and remember. Launch your product into their world and see what they notice, think, say — and
          why they would buy.</p>
        <div className="gstats">
          <div><b>{stats.agents ? `Day ${dayOf(t)}` : "—"}</b><span>of world time</span></div>
          <div><b>{stats.agents ? fmtInt(stats.conversations_total) : "—"}</b><span>conversations so far</span></div>
          <div><b>{stats.agents ? stats.products_live : "—"}</b><span>products live</span></div>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <button className="btn primary" data-testid="globe-enter" style={{ padding: "11px 20px", fontSize: 14 }}
            onClick={() => enter(false)}>Enter world →</button>
          <button className="btn ghost" data-testid="globe-skip" onClick={() => enter(true)}>Skip intro</button>
        </div>
        <p className="xs muted" style={{ marginTop: 18 }}>1 sim day = 1 real hour · runs on Google Cloud</p>
      </div>
    </div>
  );
}
