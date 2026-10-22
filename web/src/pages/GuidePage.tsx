import { PageTitle } from "../components/Shell";

const CARDS: [string, string][] = [
  ["The world", "A pixel-art Indiranagar generated from OpenStreetMap streets (© OpenStreetMap contributors, ODbL). 1,000 agents live there all the time: one sim day passes every real hour, on Google Cloud, whether or not anyone is watching."],
  ["Agents", "Each agent is sampled from public statistics (Census, World Bank) plus labelled assumptions, then given a persona by Gemini: personality, values, lifestyle, interests, speaking style and how openly they share. They own a phone of a certain age and condition, and have money, a routine and relationships."],
  ["Memory", "Five layers: an exact raw log of everything (BigQuery), today's working memory, episodic memories they can recall (Firestore vector search), beliefs about each product, and a nightly reflection. Agents only ever recall their own memories."],
  ["Private thoughts vs speech", "Before a chat each agent privately decides what it is willing to share; the dialogue sees only those share plans; afterwards each agent privately reflects. In stores, customers think, decide and speak turn by turn. Other agents only hear what is said."],
  ["Attention to ads", "An agent can only see a hoarding when it is in the board's cone, in front of it and looking towards it. A cheap attention model decides pass-by, glance or notice (≈30–40% glance, 4–10% notice — labelled assumptions). Only noticed ads produce a Gemini thought."],
  ["Launching products", "Launch Studio understands your content, flags risky claims and plans hoardings automatically from the world's own foot traffic. Launch drops the product into the live world; its hoardings, reels, newspaper ads, reviewers, community posts and store displays go live at once."],
  ["Buying", "Agents move from aware to curious, researching, inquiring and deciding. They buy only when need (e.g. an old or broken phone), affordability and preference line up. We never predict whether one person will buy; Insights shows which segments are likely to and why."],
  ["Budget and honesty", "A budget governor keeps model spend within $15/day. Some small talk is logged as topics instead of full transcripts when the budget is tight; Insights says so."],
];

/** Guide (U-08): how the world works, privacy, attention, budget, data sources and attribution. */
export function GuidePage() {
  return (
    <div className="page">
      <PageTitle title="Guide" sub="How the world works, what is real, what is assumed, and the limits." />
      <div className="grid g2" data-testid="guide-body">
        {CARDS.map(([h, t]) => (
          <div className="card" key={h}><h2>{h}</h2><p className="small muted" style={{ margin: "6px 0 0" }}>{t}</p></div>
        ))}
        <div className="card" style={{ gridColumn: "span 2" }}>
          <h2>Data sources &amp; attribution</h2>
          <p className="small muted">Map data © OpenStreetMap contributors (ODbL). Population priors: U.S. Census Bureau
            International Database and World Bank WDI via BigQuery public datasets. Models: Gemini 3 via OpenRouter.
            Brands, stores and products shown are fictional placeholders except phone brands that agents already own,
            which are shown as owned possessions only.</p>
        </div>
      </div>
    </div>
  );
}
