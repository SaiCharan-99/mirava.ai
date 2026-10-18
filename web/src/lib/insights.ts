import { getJSON } from "./api";
import type { LineEvent, LineSeries } from "../components/charts";

/** Insights API shapes (api/insights.py) — dashboards return UI-ready rows. */
export type KpiRow = [string, string, string];
export interface OverviewData {
  kpis: KpiRow[]; labels: string[]; series: LineSeries[]; events: LineEvent[]; ymax: number;
  funnel: { cols: string[]; rows: (string | number)[][] }; note: string;
}
export interface SourcesData { labels: string[]; cols: string[]; stacks: { label: string; parts: number[] }[]; paths: [string, number][]; note: string }
export type SiteRow = [string, string, string, string, number, number, number, number | string, string];
export interface HoardingsData {
  kpis: KpiRow[]; rows: SiteRow[]; heat: { rows: string[]; cols: string[]; vals: number[][] }; themes: [string, number][];
  sites?: { site_id: string; x: number; y: number }[]; facing?: { site_id: string; hi: string; lo: string; ratio: number } | null;
}
export interface SegmentsData {
  products: { id: string; name: string }[]; product?: string;
  heat: { rows: string[]; cols: string[]; vals: number[][]; n?: number[][] } | null; lifestyles: [string, string, string, string][];
}
export interface ConversationsData {
  topics: [string, number, string][]; topics_note: string; gap: [string, string, string, string][];
  reviewers: [string, string, string, string][]; threads: (string)[][];
}
export interface QuoteView { agent_id: number | null; name?: string | null; age?: number; text: string; kind: string; private: boolean }
export interface AskAnswerView {
  steps: [string, string][]; html: string; bars?: [string, number, string][]; ymax?: number; barsNote?: string; sideHtml?: string;
  quotes: QuoteView[]; sqlLabel?: string; sql?: string[]; caveats?: string; suggestions?: string[];
}
export interface PollResultView {
  question: string; optionsText: string; title: string; estimate: string; bars: [string, number, string][]; max: number;
  heat: { rows: string[]; cols: string[]; vals: number[][] }; quote: QuoteView | null; cohorts: string[];
}
export interface AskAnswer {
  answer_md: string; numbers: { label: string; value: number; source_ref: string }[];
  charts: Record<string, unknown>[]; quotes: { agent_id: number | null; name: string | null; kind: string | null; t: number | null; text: string; private: boolean }[];
  sql: string[]; caveats: string[]; suggestions: string[]; faithful?: boolean;
}

export const getOverview = () => getJSON<OverviewData>("/insights/overview");
export const getSources = () => getJSON<SourcesData>("/insights/sources");
export const getHoardings = () => getJSON<HoardingsData>("/insights/hoardings");
export const getSegments = (p = "") => getJSON<SegmentsData>(`/insights/segments${p ? `?product=${encodeURIComponent(p)}` : ""}`);
export const getConversations = () => getJSON<ConversationsData>("/insights/conversations");

/** Minimal markdown → HTML for answers (bold, code, links stripped of scripts). */
export function mdToHtml(md: string): string {
  const esc = md.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\n\n/g, "<br/><br/>");
}

/** POST /insights/ask as SSE; calls onStep for each step, resolves with the answer. */
export async function ask(question: string, onStep: (s: string) => void): Promise<AskAnswer> {
  const r = await fetch("/api/insights/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
  if (!r.ok || !r.body) throw new Error(`ask: ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let answer: AskAnswer | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i).replace(/^data: /, "");
      buf = buf.slice(i + 2);
      if (!chunk.trim()) continue;
      const item = JSON.parse(chunk) as { step?: string; answer?: AskAnswer };
      if (item.step) onStep(item.step);
      if (item.answer) answer = item.answer;
    }
  }
  if (!answer) throw new Error("no answer");
  return answer;
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

export function initials(n: string): string {
  return n.split(" ").map((s) => s[0]).join("").slice(0, 2);
}
