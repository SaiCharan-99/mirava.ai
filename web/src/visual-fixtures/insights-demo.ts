/** Visual-test content of the Insights tabs, copied from the demo literals in docs/ui-mockup.html (insAsk … insInterview).
 * mockup-fixtures.json (extract-fixtures.mjs) only carries HO_ROWS; these strings live inline in the mockup's render
 * functions, so they are mirrored here (DECISIONS #92). Used ONLY when ?visualTest=1. */
import type { AskAnswerView, ConversationsData, HoardingsData, OverviewData, PollResultView, SegmentsData, SourcesData } from "../lib/insights";

const DAYSX = Array.from({ length: 14 }, (_, i) => "D" + (i + 10));
const pulse = DAYSX.map((_, i) => (i < 4 ? null : Math.round(6 + (i - 4) * 5.2 + Math.sin(i) * 2)));
const orbit = DAYSX.map((_, i) => (i < 9 ? null : Math.round(5 + (i - 9) * 5.5)));
const pc = pulse.map((v) => (v === null ? null : Math.round(v * 0.36)));
const oc = orbit.map((v) => (v === null ? null : Math.round(v * 0.28)));

export const DEMO_DATA_CHIP = "Data: Day 1 → Day 23 · 2 products live";

export const DEMO_ASK: { q: string; a: AskAnswerView }[] = [
  {
    q: "People whose phones are older than 5 years — are they interested in any of our phones? Why?",
    a: {
      steps: [["cohort", "phone_age_years > 5 → 187 agents"], ["run_sql", "beliefs_latest × agents_latest · 2 products"],
        ["semantic_search", "thoughts + messages · cohort · 'why / why not' · 40 hits"], ["chart", "bar · curious+ share by product"]],
      html: "<b>187 agents (18.7%)</b> have phones older than 5 years. <b>38%</b> of them are curious or further about at least one of our live phones — more than twice the rate of everyone else (17%).",
      bars: [["Pulse 5", 31, "#22c55e"], ["Orbit S", 11, "#8b5cf6"], ["Either", 38, "var(--teal)"]], ymax: 40,
      unit: "%", barsNote: "Curious, researching, inquiring, deciding or purchased · cohort n = 187",
      sideHtml: "<b>Why Pulse 5 leads</b><ul style=\"margin:6px 0 10px;padding-left:18px\"><li>Battery (“two days”) maps directly to their pain: 64% of the cohort report weak batteries.</li><li>₹24,999 + ₹3,000 exchange bonus fits; 22 of them already asked about EMI in stores.</li></ul><b>Why Orbit S lags</b><ul style=\"margin:6px 0 0;padding-left:18px\"><li>₹49,999 is seen as paying for thinness, not for what they need.</li><li>Tanvi's review (“battery is the price you pay”) reached 41 of them.</li></ul>",
      quotes: [
        { agent_id: 31, text: "Two days on one charge? My phone barely lasts till lunch. If the exchange gives me ₹3,000 for this old one, I'm in.", kind: "thought after Digital Bazaar visit", private: true },
        { agent_id: 412, text: "I'm not paying fifty thousand for a thin phone. I need one that doesn't die.", kind: "said to her son", private: false },
        { agent_id: 233, text: "Lost my phone on the bus, so the decision was easy — Pulse 5 on EMI.", kind: "debrief after purchase", private: true },
      ],
      sqlLabel: "Show SQL (2 queries · 38 MB scanned)",
      sql: ["SELECT b.product_id, COUNTIF(b.stage IN ('curious','researching','inquiring','deciding','purchased')) / COUNT(*) AS curious_plus\nFROM launch_lens.beliefs_latest b\nJOIN launch_lens.agents_latest a USING (agent_id)\nWHERE a.phone_age_years > 5 AND b.product_id IN ('pulse-5','orbit-s')\nGROUP BY b.product_id;"],
      caveats: "Caveats: Nova X1 is not launched yet. Orbit S has been live for 4 sim days only. 61% of chats in this window were written out in full; the rest are logged as topics (budget). Simulated data.",
    },
  },
  {
    q: "Which hoarding gets noticed the most, and does the facing matter?",
    a: {
      steps: [], html: "<b>S-100FT-07 facing south</b> has the highest notice rate of any site (<b>9.8%</b> of passers), 2.1× the same board facing north. Evening northbound traffic is slower and faces it for ~14 s longer. Full table in <a href=\"#/insights/hoardings\">Hoardings</a>.",
      quotes: [{ agent_id: 7, text: "Two days on one charge sounds great — but every brand says that.", kind: "thought at S-100FT-07", private: true }],
    },
  },
];
export const DEMO_SUGGESTIONS = ["Which phone do people prefer, and why?", "What do students say about Orbit S?", "Where did Pulse 5 buyers first hear about it?", "What do people privately think but not say about Pulse 5?", "Which junction should a media owner sell first?"];

export const DEMO_OVERVIEW: OverviewData = {
  kpis: [["Pulse 5 · aware", "52%", "+6 pts today"], ["Pulse 5 · curious+", "18%", "41 store inquiries · 9 bought"], ["Orbit S · aware", "27%", "live 4 days"], ["Orbit S · curious+", "7%", "12 inquiries · 2 bought"]],
  labels: DAYSX, ymax: 60,
  series: [{ n: "Pulse 5 aware", v: pulse, c: "#22c55e" }, { n: "Pulse 5 curious+", v: pc, c: "#22c55e", dash: "4 3" }, { n: "Orbit S aware", v: orbit, c: "#8b5cf6" }, { n: "Orbit S curious+", v: oc, c: "#8b5cf6", dash: "4 3" }],
  events: [{ i: 4, t: "Pulse 5 launch", c: "#22c55e" }, { i: 9, t: "Orbit S launch", c: "#8b5cf6" }],
  funnel: { cols: ["Pulse 5", "Orbit S"], rows: [["Exposed (any channel)", "812", "544"], ["Aware", "520", "270"], ["Curious", "104", "46"], ["Researching", "38", "14"], ["Inquired in store", "41", "12"], ["Purchased", "9", "2"]] },
  note: "Nova X1 is ready to launch — its line will start at launch.",
};

export const DEMO_SOURCES: SourcesData = {
  labels: ["Hoardings", "Reels", "Reviewers", "Community", "Word of mouth", "Newspaper", "Store"],
  cols: ["#f97316", "#2dd4bf", "#ec4899", "#a78bfa", "#60a5fa", "#94a3b8", "#f5b041"],
  stacks: [{ label: "Pulse 5 · 520 aware", parts: [34, 22, 12, 7, 16, 5, 4] }, { label: "Orbit S · 270 aware", parts: [24, 31, 15, 9, 13, 4, 4] }],
  paths: [["Hoarding → friend chat → store", 14], ["Reel → reviewer video → store", 9], ["Newspaper → store", 6], ["Reviewer → community thread → store", 5], ["Life event (phone broke) → store", 4]],
  note: "Pulse 5 · median 3.4 sim days from first exposure to inquiry.",
};

export const DEMO_HOARDINGS_KPIS: HoardingsData["kpis"] = [["Best site", "S-100FT-07 · faces S", "9.8% notice rate · 61 thoughts this week"], ["Facing matters", "2.1× notice", "same board: south face vs north face"], ["Best hour", "18:00–20:00", "slow evening traffic · lit boards win at night"]];
export const DEMO_HOARDINGS_HEAT: HoardingsData["heat"] = { rows: ["Lit boards", "Unlit boards"], cols: ["6–9", "9–12", "12–15", "15–18", "18–21", "21–24"], vals: [[6.1, 4.2, 3.8, 5.0, 8.9, 7.6], [5.8, 4.0, 3.6, 4.7, 4.1, 1.2]] };
export const DEMO_HOARDINGS_THEMES: HoardingsData["themes"] = [["Two days on one charge? My phone barely lasts till lunch.", 38], ["Every brand says that. Show me real numbers.", 22], ["Looks gorgeous, but ₹49,999 for thin? No.", 19]];

export const DEMO_SEGMENTS: SegmentsData = {
  products: [{ id: "pulse-5", name: "Pulse 5" }, { id: "orbit-s", name: "Orbit S" }], product: "pulse-5",
  heat: { rows: ["18–24", "25–34", "35–44", "45–59", "60+"], cols: ["< ₹25k", "₹25–50k", "₹50k–1L", "₹1–2L", "> ₹2L"], vals: [[14, 22, 18, 9, 4], [11, 31, 36, 24, 9], [8, 27, 33, 21, 7], [6, 19, 22, 12, 5], [3, 9, 11, 6, 2]] },
  lifestyles: [["Value-seeking upgraders", "25–44 · ₹25k–1L · phones > 4 yrs", "battery anxiety · exchange bonus · EMI", "41%"], ["Young tech professionals", "25–34 · ₹50k–2L", "battery for travel · reviewer trust", "33%"], ["Students on a budget", "18–24 · < ₹25k", "price fits · peer chats in community", "22%"], ["Photography hobbyists", "24–40", "put off by 'average' low-light camera", "9%"]],
};

export const DEMO_CONVERSATIONS: ConversationsData = {
  topics: [["Battery life", 34, "#22c55e"], ["Price & EMI", 27, "#f5b041"], ["Camera at night", 19, "#60a5fa"], ["Thin design", 11, "#8b5cf6"], ["Updates & support", 6, "#94a3b8"]],
  topics_note: "Share of product-related chats · last 7 sim days · 612 chats",
  gap: [["Pulse 5 camera", "“Looks decent.”", "“Average in low light — not for me.”", "more negative in private"], ["Orbit S price", "“It's premium, makes sense.”", "“Way too expensive for a thin phone.”", "more negative in private"], ["Pulse 5 battery", "“Two days, apparently.”", "“Finally something that fixes my problem.”", "more positive in private"], ["Affordability", "rarely mentioned", "“Can't spend more than ₹30k this month.”", "withheld (money)"]],
  reviewers: [["Tanvi Shah", "Orbit S", "“Gorgeous, but I'd never carry it as my only phone.”", "“Thinnest phone I've tested — battery is the price you pay.” 7.5/10"], ["Rohan Bhat", "Pulse 5", "“Camera is weak, but my followers want battery.”", "“Battery king — camera is fine for the price.” 8/10"]],
  threads: [["r/BangaloreTech", "Pulse 5 night samples, anyone?", "Meera Iyer", "14 comments · 31 ▲"], ["r/BangaloreTech", "Orbit S vs Pulse 5 for a college student?", "Kavya Nair", "22 comments · 48 ▲"], ["r/IndiranagarLife", "Digital Bazaar exchange offer is legit", "Ravi Kumar", "6 comments · 12 ▲"]],
};

export const DEMO_POLL: PollResultView = {
  question: "Would you consider switching phones in the next 3 months? Which one?", optionsText: "Pulse 5 · Orbit S · another brand · not switching",
  title: "Result · Day 23 08:20 · 1,000 agents", estimate: "$0.21",
  bars: [["Not switching", 58, "#94a3b8"], ["Another brand", 19, "#60a5fa"], ["Pulse 5", 17, "#22c55e"], ["Orbit S", 6, "#8b5cf6"]], max: 60,
  heat: { rows: ["< 2 yrs", "2–5 yrs", "> 5 yrs"], cols: ["Pulse 5", "Orbit S", "Other", "Not switching"], vals: [[6, 4, 8, 82], [16, 6, 19, 59], [34, 7, 27, 32]] },
  quote: { agent_id: 31, text: "If the exchange gives me ₹3,000 for this old one, Pulse 5 for sure.", kind: "poll answer", private: false },
  cohorts: ["Everyone (1,000 agents)", "Phones older than 5 years (187)"],
};

export const DEMO_INTERVIEW = {
  agents: [31, 7, 90, 52, 120], selected: 31, title: "Ravi Kumar, 41 · in character", note: "grounded only in Ravi's own memories",
  chat: [
    { role: "me", text: "Ravi, what did you think when you walked into Digital Bazaar on Tuesday?" },
    { role: "ai", text: "Honestly I went in for the battery. My phone is almost six years old and the screen cracked last week. The boy there, Imran, said two days is real if I don't play games — I don't. But I didn't tell him I was waiting for the 1st, when the salary comes.", mem: "memories used: inquiry at Digital Bazaar (D22 18:22) · screen cracked (D22 07:50) · payday plan" },
    { role: "me", text: "Did the Orbit S interest you at all?" },
    { role: "ai", text: "That thin one? My nephew showed me. Very nice, but ₹50,000 for a phone that's just thin — no. I need it to last the whole day at the counter.", mem: "memories used: chat with nephew (D20) · hoarding S-CMH-01 (D21)" },
  ],
  placeholder: "Ask Ravi…",
};
