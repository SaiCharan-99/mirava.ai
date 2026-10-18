# Demo script — 3 minutes

Open https://mirava-ai-hack.web.app at 1440×900 before you start. Say "simulated" whenever you show numbers.

| Time | Screen | Click | Say |
|---|---|---|---|
| 0:00–0:15 | **Globe** (`/globe`) | Let it fly into Bengaluru | "This is mirava.ai: 1,000 AI agents living in Indiranagar, built from OpenStreetMap. It runs on Cloud Run all the time, one sim day per real hour." |
| 0:15–0:35 | **World** | Hover a walking agent, then click to open the profile drawer | "Each person has a persona, a routine, money, relationships, a media diet and a phone. This one's phone is over five years old." |
| 0:35–1:00 | Profile → **Thoughts**, then **Conversations** | Open a full conversation; expand the private prep and debrief | "They noticed a hoarding, and only noticed ads produce a private thought. Here is a full chat: private prep, what they chose to share, the exact transcript, then a private debrief. Memory is private per agent; the dialogue sees only share plans." |
| 1:00–1:35 | **Launch Studio** (`/launch`) → Nova X1 | Content → Understanding (drag a graph node, hover to show neighbours) → Plan | "The studio reads the creatives, flags claim risk and salience, builds this knowledge graph and plans hoardings automatically. Every site comes with a reason." |
| 1:35–1:55 | **World** → Ready to launch dock | Click **Launch** on Nova X1 | "Launch." (firework) "Sites flip, reels reach interested feeds, reviewers will publish and threads will grow." |
| 1:55–2:35 | **Insights → Ask** | Ask: *"phones older than 5 years — interested in which of our phones, and why?"* | "Gemini answers over the exact BigQuery log: the SQL, a chart and verbatim quotes from private thoughts, labelled private." |
| 2:35–2:50 | **Insights → Hoardings** | Sort the leaderboard; point at a site and facing | "Out-of-home by site and facing: passes, glances and notices, measured rather than guessed." |
| 2:50–3:00 | **Insights → Segments** | One look | "Interest by segment. Everything is simulated, the stores are fictional, it's Gemini 3 on Google Cloud, and it runs under a $15/day governor. Thank you." |

## Fallbacks
- **Engine down or live stream empty:** World → **Highlights** → **Replay** plays the recorded top moments. Say "replaying the last hour's highlights".
- **Cloud demo state broken:** run `make restore-demo` to restore the pre-warmed demo snapshot. Or run locally with `make dev && make seed-demo` and demo on http://localhost:5173.
- **Ask is slow:** reuse the answer already in the Ask history. The Hoardings tab needs no model call.
- **Nova X1 already launched:** use a local seed (`make seed-demo` leaves Nova X1 ready in the dock).
