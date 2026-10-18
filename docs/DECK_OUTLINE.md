# Deck outline — mirava.ai

All figures are simulated. Stores and media are fictional.

## 1. Problem
- Phone launches spend heavily on hoardings, reels and print, with little insight into *why* people notice, talk or buy.
- Surveys capture stated intent, not attention, word of mouth or budget reality.
- Notes: "Marketers find out what worked after the money is spent."

## 2. Solution
- An always-on city of 1,000 AI agents (Indiranagar, built from OpenStreetMap) to rehearse a launch.
- Agents notice ads, think privately, talk, visit stores and buy only when need, budget and intent line up.
- Notes: "A wind tunnel for product launches."

## 3. Demo
- Globe → World → profile and conversation → Launch Studio graph and auto plan → Launch → Insights Ask / Hoardings / Segments.
- Notes: live at mirava-ai-hack.web.app; script in `docs/DEMO_SCRIPT.md`.

## 4. Architecture
- Firebase Hosting → `mirava-api` (Cloud Run) → `world-engine` (Cloud Run, always-on, single writer holding a Firestore lease).
- Events → Pub/Sub → BigQuery; checkpoints in Cloud Storage; Cloud Scheduler watchdog.
- Notes: deterministic seeded engine; resumes from its checkpoint after a restart.

## 5. Google Cloud usage
- Cloud Run ×2, Firebase Hosting, Firestore (+ vector index), Cloud Storage, Pub/Sub BigQuery subscriptions, BigQuery views + VECTOR_SEARCH, Secret Manager, Model Armor, Cloud Scheduler, Cloud Build, Artifact Registry.
- Gemini 3 Pro / Flash / Flash-Lite / Embedding via OpenRouter.
- Notes: each service has one clear job.

## 6. Privacy model
- Private memory per agent (`MemoryStore(agent_id)`); every prompt is built for one agent.
- Think vs speak: private prep → dialogue from typed SharePlans → private debrief.
- The salesperson sees only the transcript; marker-fact tests prove no leakage.
- Notes: "Agents share only what they choose to say."

## 7. Cost and the budget governor
- $15/day background cap, $5/day interactive cap; priority classes with per-day and per-hour caps.
- Over cap → `rendered=false` with rule/template fallbacks; the clock can slow, but the world never stops.
- The attention model gates thoughts (no model call for pass/glance); low reasoning effort; results cached by input hash.
- Notes: hourly pacing stops a morning commute from spending the whole day's thoughts.

## 8. OOH (hoardings) insight
- Exposure geometry per site and facing: passes → glances → notices.
- Auto hoarding plan with reasons from simulated footfall; Hoardings leaderboard in Insights.
- Notes: "Which wall, which direction, which audience — measured."

## 9. Evals (200 agents · 2 sim days · fake backend)
- Insights faithfulness 100%, quotes verbatim 100%, 9/10 benchmark questions pass (the remaining routing miss has since been fixed).
- Survey realism 6/6: extraversion ↔ messages r = 0.53; experience dominance 0.83; 11.7% opinion shift, every change cited.
- Notes: full tables in `evals/RESULTS.md`.

## 10. Roadmap
- More cities and categories (category bootstrap); what-if forks of a world.
- Richer feeds (friends' posts), monitoring dashboards, eval runs on real models.
- Notes: same engine, new map and population config.

## 11. Team
- Sai Charan Gobburu — builder (with Claude Code).
- Notes: thank the judges and invite them to open the live world.
