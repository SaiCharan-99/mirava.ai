import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { useWorld } from "../state/world";
import { fmt, fmtInt } from "../lib/time";
import { withMode } from "../lib/visualTest";

const THEME_KEY = "mirava_theme";

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem(THEME_KEY) || "dark";
    } catch {
      return "dark";
    }
  });
  useEffect(() => {
    if (theme === "light") document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* private mode */
    }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "light" ? "dark" : "light"))];
}

/** Top bar (56 px): logo, crumbs, LIVE + SIMULATED DATA pills, world clock, budget meter, theme toggle. */
export function Header() {
  const t = useWorld((s) => s.t);
  const agents = useWorld((s) => s.stats.agents);
  const budget = useWorld((s) => s.budget);
  const [, toggle] = useTheme();
  const pct = Math.min(100, (budget.used_usd / budget.cap_usd) * 100);
  return (
    <header data-testid="app-header">
      <div className="logo"><div className="logo-mark"><i /></div>mirava.ai</div>
      <div className="crumbs"><span>Agent World</span><span>/</span><b>Indiranagar, Bengaluru</b></div>
      <span className="chip"><span className="dotlive" />Live · {fmtInt(agents || 1000)} agents</span>
      <span className="sim-badge">SIMULATED DATA</span>
      <div className="hspace" />
      {budget.slowed && <span className="chip amber" data-testid="slowed-chip" style={{ whiteSpace: "nowrap" }}
        title="Background model spend would exceed the daily budget, so sim time runs slower">Slowed to save budget</span>}
      <div className="row" data-testid="header-clock" style={{ gap: 8 }} title="1 sim day = 1 real hour">
        <span className="clock" style={{ fontSize: 14, whiteSpace: "nowrap" }}>{fmt(t)}</span>
      </div>
      <div data-testid="budget-meter" style={{ width: 140, whiteSpace: "nowrap" }} title="Background model budget used today">
        <div className="row between xs"><span className="muted">Budget today</span>
          <span className="mono">${budget.used_usd.toFixed(2)} / ${budget.cap_usd}</span></div>
        <div className="bar" style={{ height: 5, marginTop: 3 }}><i style={{ width: `${pct}%` }} /></div>
      </div>
      <button className="btn sm ghost" data-testid="theme-toggle" title="Toggle theme" onClick={toggle}>◐ Theme</button>
      {/* keeps header geometry identical to the reference, where the mockup-only "Mockup" chip occupies this slot */}
      <span aria-hidden style={{ width: 64, flex: "none" }} />
      <div className="avatar" style={{ background: "#a78bfa" }}>UN</div>
    </header>
  );
}

const NAV: [string, string, string, string][] = [
  ["/world", "world", "◉", "World"],
  ["/launch", "launch", "↑", "Launch Studio"],
  ["/insights/ask", "insights", "✦", "Insights"],
  ["/people", "people", "☺", "People"],
];

/** Left sidebar (232 px): navigation + always-on world status card. */
export function Sidebar() {
  const loc = useLocation();
  const t = useWorld((s) => s.t);
  const products = useWorld((s) => s.products);
  const live = products.filter((p) => p.status === "live");
  const section = loc.pathname.split("/")[1] || "world";
  const active = section === "globe" ? "world" : section;
  const link = (to: string, key: string, ic: string, label: string) => (
    <NavLink key={key} to={withMode(to)} data-testid={`nav-${key}`} className={() => (active === key ? "active" : "")}>
      <span className="ic">{ic}</span>{label}
    </NavLink>
  );
  const days = Math.floor(t / 1440);
  const hours = Math.floor((t % 1440) / 60);
  return (
    <aside data-testid="app-sidebar">
      <nav className="nav">
        {NAV.map(([to, key, ic, label]) => link(to, key, ic, label))}
        <div className="navsec">Help</div>
        {link("/guide", "guide", "?", "Guide")}
      </nav>
      <div className="worldcard" data-testid="world-status">
        <div className="row between small"><b>Indiranagar world</b>
          <span className="chip green" style={{ padding: "1px 7px" }}><span className="dotlive" />always on</span></div>
        <div className="small muted" style={{ marginTop: 6 }}>
          Living since Day 1 · <span className="mono">{days} d {hours} h</span> of sim time · 1 sim day = 1 real hour</div>
        <div className="small muted" style={{ marginTop: 8 }}>Products live</div>
        <div className="row wrap" style={{ gap: 6, marginTop: 4 }}>
          {live.map((p) => (
            <span key={p.id} className="chip" style={{ padding: "1px 8px" }}>
              <span className="pdot" style={{ background: p.hex, width: 8, height: 8 }} />{p.name}</span>
          ))}
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>
          Runs on Cloud Run whether or not anyone is watching. Memories and conversations keep accumulating.</div>
      </div>
    </aside>
  );
}

/** Standard page title block (`page-header`, `page-title`, `page-actions`). */
export function PageTitle({ title, sub, right }: { title: ReactNode; sub: ReactNode; right?: ReactNode }) {
  return (
    <div className="ptitle" data-testid="page-header">
      <div><h1 data-testid="page-title">{title}</h1><p className="sub">{sub}</p></div>
      <div className="row" data-testid="page-actions">{right}</div>
    </div>
  );
}
