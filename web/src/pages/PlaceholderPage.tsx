import { PageTitle } from "../components/Shell";

/** Route stub for pages built in later phases (keeps the shell and navigation complete). */
export function PlaceholderPage({ title, sub, phase }: { title: string; sub: string; phase: number }) {
  return (
    <div className="page">
      <PageTitle title={title} sub={sub} />
      <div className="card"><h3>Coming in phase {phase}</h3>
        <p className="small muted" style={{ margin: 0 }}>This page is part of the build plan and arrives in phase {phase}.</p></div>
    </div>
  );
}
