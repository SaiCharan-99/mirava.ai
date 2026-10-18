# mirava.ai — Brief Description of the Solution

**Team:** ONE 77 · **Leader:** Sai Charan Gobburu · **Track:** Retail & Commerce · **Live:** https://mirava-ai-hack.web.app

## The problem
Brands spend crores launching a product on hoardings, reels, newspapers and store displays, and only find out what worked after the money is spent. Surveys measure what people *say* they will do. They miss what actually drives a purchase: whether anyone noticed the ad, what they privately thought, what they told their friends, and whether their budget and need allowed them to buy.

## Our solution
**mirava.ai is a wind tunnel for product launches.** It is an always-on, pixel-art Indiranagar (Bengaluru), generated from OpenStreetMap, where **1,000 Gemini-powered AI agents** live around the clock (1 sim day = 1 real hour). Each agent has a persona, private layered memory, needs and a daily routine, money and credit, 7,000+ relationships across 435 households, a media diet and a phone of a certain age and condition. They walk, ride, take the metro, work, scroll their feeds, meet people they know and talk.

A marketing team adds products and creatives in **Launch Studio** (posters, reel transcripts, posts, newspaper ads, store displays). Gemini reads the content, flags risky claims, scores creative salience, builds an Obsidian-style knowledge graph and **plans hoardings automatically** from simulated footfall, with a reason for every site and facing. The team then launches the product into the live city.

From that moment:
- **Attention before thought.** Exposure geometry decides whether an agent passes, glances at or *notices* a hoarding, with no model call. Only noticed ads produce a logged private thought, which keeps it realistic and cheap.
- **Think vs speak.** Conversations run in three steps: private prep, a dialogue built only from what each agent chooses to share (up to 10 messages each), then a private debrief. Agents question fictional salespeople, who see only the spoken words.
- **Real purchase logic.** Agents buy only when need, budget and intent line up.
- **Ask why.** Every event is logged exactly. In **Insights**, a Gemini assistant answers any question ("people with phones older than 5 years: interested in which of our phones, and why?") with the SQL, a chart and verbatim quotes. Dashboards include a **Hoardings** out-of-home view by site and facing, plus segments, funnel and a survey room with focus groups and interviews.

## How we use Google
| Google service | What it does in mirava.ai |
|---|---|
| **Gemini 3** (Pro, Flash, Flash-Lite, Embedding) | Pro: Insights assistant and claim-risk review. Flash: product dialogues, understanding the creatives, personas, reviews. Flash-Lite: private thoughts, conversations, store turns and batched decisions. Embeddings: 768-d memory and text search |
| **Google ADK** | Insights assistant, salesperson, interviewer and creative-understanding agents |
| **Cloud Run** | `world-engine`: always-on, single writer (min = max = 1, CPU always on, WebSockets). `mirava-api`: REST, uploads, Insights; scales to zero |
| **Firestore** | Live world state, the engine lease, per-agent private memories with a vector index |
| **Pub/Sub → BigQuery subscriptions** | Every event and text row streams into BigQuery with no glue code |
| **BigQuery** | Exact event log, curated views (exposures, site-daily, first-heard, funnel) and `VECTOR_SEARCH` over thoughts and chats, queried by Gemini through a read-only service account |
| **Cloud Storage** | Genesis world, versioned checkpoints, creative uploads |
| **Model Armor** | Screens uploaded content and Insights questions for prompt injection and jailbreaks |
| **Firebase Hosting** | The web app (React, Phaser, cobe globe) |
| **Secret Manager, Cloud Scheduler, Cloud Build, Artifact Registry, Cloud Monitoring** | Key storage, a 5-minute health watchdog, CI/CD, uptime checks, spend and tick-lag alerts |

## Why it stands out
- **The world is always on.** It is a living city, not a one-off survey run. Memories, relationships and word of mouth build up over time.
- **Private by construction.** Each agent's memory is only reachable through that agent's own store, and marker-fact tests prove there is no leakage between agents.
- **Built to a budget.** A governor caps background spend at $15/day. Over the cap, work falls back to rules and templates, so the world gets quieter but never stops. A rendered chat costs about $0.003.
- **Measured.** Insights faithfulness is 100% and quotes are 100% verbatim. All 6 survey-realism checks pass. 29 UI screens match the design at pixel level.

*All people, numbers, stores and ads are simulated. Stores and media are fictional.*
