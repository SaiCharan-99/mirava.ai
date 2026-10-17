# CLAUDE.md — Launch Lens (Always-on Agent World)

Read this file in full at the start of every session. It explains what we are building, how to work in this repo, and how to hand over to the next session. *Launch Lens is a working name.*

## 1. What we are building
An **always-on world of 1,000 AI agents** living in a pixel-art **Indiranagar, Bengaluru**, generated from OpenStreetMap. The world runs on Google Cloud all the time (**1 sim day = 1 real hour**), whether or not anyone has the app open. Each agent has:
- a persona and **private, layered memory**
- needs and a routine
- money and credit
- relationships
- a media diet (feeds, newspaper, Reddit-style community)
- a phone of a certain age and condition

Agents walk, ride, take the metro, work, scroll, meet people they know and talk (up to 10 messages each).

Opening the app shows a **globe** that flies into the city. **World** is the home page: the live city, world stats, a **New product** button and a small **Ready to launch** dock — no other campaign controls.

In **Launch Studio** a team adds several products (details, target personas, posters, reel transcripts, posts, newspaper ads, store displays). The studio understands the content (claim risk, creative salience, an Obsidian-style knowledge graph) and **plans hoardings automatically**. Back on the World, each product is **launched one at a time** with a firework drop.

From then on:
- Agents pass by, glance at or **notice** hoardings. Only noticed ads produce a logged **private thought**.
- Reels reach interested agents' feeds.
- Reviewer agents publish reviews; community threads grow.
- Agents talk, sharing only what they choose to say.
- Agents question salespeople in fictional stores.
- Agents buy only when need, budget and intent line up.

Everything is logged exactly (BigQuery). **Insights** has a Gemini assistant that answers any question over the data (e.g. "phones older than 5 years — interested in which of our phones, and why?"), plus dashboards including a **Hoardings** (out-of-home) view by site and facing.

Hackathon: Google Cloud AI Builder Cup 2026 (Retail & Commerce). **Deadline 18 Oct 2026.** Build only specs tagged `DEMO` (and `STRETCH` if time allows).

## 2. Documents — read before coding
| File | Use |
|---|---|
| `PROGRESS.md` | **Start here every session.** Current phase, what exists, how to run, cloud setup status, handoff notes, contract changes, known issues |
| `docs/phases/phase-0N-*.md` | Your instructions for this session |
| `docs/architecture.md` | System design (authoritative), feature by feature with Mermaid flows. Each phase file says which sections to read |
| `docs/INTERFACES.md` | **Contracts**: schemas, event kinds, live protocol, API shapes, `data-testid`s, visual-test hooks, BigQuery schemas |
| `docs/specs.md` | Feature specs (W-, P-, E-, M-, A-, C-, T-, S-, L-, I-, U-, X-) with "done when" criteria |
| `docs/techstack.md` | Services, models, prices, cost levers |
| `docs/setup/*.md` | **Step-by-step account and Google Cloud setup guides**, used by `/gcp-setup` |
| `docs/DECISIONS.md` | Decisions log (append only; rows 28+ are v3) |
| `docs/ui-mockup.html` | **Visual and interaction reference** for every screen (see §6). Open it without `?freeze=1` to see it live |
| `docs/ui-reference/*.png` | Reference screenshots of the mockup, used by the visual check |

When documents disagree, this order wins: `INTERFACES.md` (names/shapes) > `architecture.md` > `specs.md` > `techstack.md` > mockup (look only). If you must break a contract:
1. update `INTERFACES.md`
2. add a `DECISIONS.md` row
3. list it under "Contract changes" in `PROGRESS.md`

## 3. Session protocol (every phase is a fresh Claude Code session)
1. Run `/start-phase N` (or follow the "Prompt" in `docs/phases/phase-0N-*.md`). The skills are `/start-phase N`, `/end-phase`, `/visual-check N` and `/gcp-setup <guide>`.
2. Read `PROGRESS.md`, the phase file, and the doc sections it lists. Don't read the whole repo; trust `PROGRESS.md` for what exists.
3. Check that the previous phase is ✅/⚠️ and `make test` is green. If not, fix that first and record it.
4. Create a task list from the phase checklist, and mark the phase 🟨 in `PROGRESS.md`.
5. Build in small steps and commit often: `phase-N: <what>`.
6. Before ending:
   - run `make test`, `make lint` and the phase acceptance checks
   - run **`/visual-check N`** for every phase that touched UI
   - run **`/end-phase`**, which updates `PROGRESS.md` (status, how to run, setup status, contract changes, handoff notes, session log) and `docs/DECISIONS.md`
7. Never start the next phase in the same session. If you run out of time, stop at a green state, mark ⚠️ and write precise handoff notes: what's done, what's half-done, and the next 3 steps.

## 4. Repository layout
```
launch-lens/
├── web/            React + Vite + TS + Phaser + cobe (src/pages, src/world, src/globe, src/components, src/visual-fixtures, src/styles)
├── api/            FastAPI service (REST, uploads, commands to the engine, Insights)
├── engine/         always-on world-engine: clock, loop, lease, needs, routine, planner, movement, spatial, encounters,
│                   events (EventBus), checkpoint, highlights, live (WebSocket hub), governor, rng, tasks
├── world/          map, places, sites, stores loaders; geometry helpers
├── population/     sampler, households, relationships, persona, routine, media_diet, money, possessions, life_events,
│                   special_agents, bootstrap_category
├── mind/           memory (MemoryStore), context (AgentContext / persona card), beliefs, reflect, decision (DecisionAdapter)
├── social/         gate, sessions, prep (share plans), dialogue, debrief, store_inquiry, community
├── media/          attention, channels (hoardings, feed, newspaper, reviewers, store displays, baseline ads), planner (auto placement)
├── commerce/       need, consideration, stores, purchase
├── insights/       views SQL, dictionary.yaml, tools, likely_buyers, polls
├── agents/         ADK agents: insights_assistant, interviewer, salesperson, understanding
├── shared/         settings, models, llm gateway, store, bq, files, schemas, prompts, time
├── config/         markets, phones_market, routines, media, attention, consideration, conversation, stores,
│                   baseline_ads, budget, world, places_overrides, demo/products
├── assets/         osm (committed extract), maps (.tmj, roadgraph, places, sites, stores), tiles, sprites
├── tools/mapgen/   OSM → Tiled map, road graph, places, hoarding sites (phase 1)
├── tools/visual/   pixel-level UI verification + extract-fixtures (provided)
├── infra/  evals/  tests/  docs/  artifacts/ (git-ignored outputs)
```

## 5. Tech stack and coding rules
- **Stack:**
  - Backend: Python 3.12, FastAPI, pydantic v2, `uv`, pytest, ruff, mypy (lenient)
  - Engine: asyncio + NumPy
  - Agents: Google ADK
  - Frontend: React 18 + Vite + TS, Phaser 3, `cobe` (globe), `react-force-graph-2d` (graph), ECharts, Tailwind, TanStack Query, Zustand
  - Cloud: see `docs/techstack.md`
- **Gemini 3 only.** Model strings live only in `shared/models.py` (`MODEL_PRO`, `MODEL_FLASH`, `MODEL_LITE`, `MODEL_EMBED`). Never any `gemini-2.5-*` string anywhere.
- **Model access is OpenRouter by default:**
  - `LLM_BACKEND=openrouter` uses `OpenRouterClient`, `vertex` uses `VertexClient` (optional), `fake` uses `FakeGemini` (tests).
  - `DECISION_BACKEND=openrouter` (Flash-Lite, batched) or `fake`.
  - Engine calls use **low reasoning effort**, tight `max_tokens` and **usage accounting**; every call reports its cost to the budget governor.
  - ADK agents use `LiteLlm(model="openrouter/<id>")`.
- **Secrets:** the team's `OPENROUTER_API_KEY` lives only in `.env` (git-ignored) locally and in the Secret Manager secret `openrouter-api-key` in the cloud. Never print, log or commit it, and never paste it into docs, prompts, fixtures or test snapshots. `gitleaks` must stay clean.
- **All model calls** go through `shared.llm` or `mind.decision`. Prompts live in `shared/prompts/*.md`. Use **structured output** (pydantic schema) for every call that returns data. Never regex-parse model text.
- **One writer.** Only `world-engine` changes world state. It holds the Firestore lease; everything else reads, or sends commands (`POST /commands`). Never write agent state from `api`.
- **Private by construction (M-07):**
  - `MemoryStore(agent_id)` reads and writes only that agent's memories and beliefs.
  - Every agent prompt is built by `mind.context.build` for **one** agent.
  - Shared prompts (dialogue) accept **only `SharePlan` objects** and public text. The salesperson sees only the spoken transcript.
  - Private events carry `private: true` and are never loaded into another agent's prompt.
  - Marker-fact tests prove there is no leakage.
- **Think vs speak:**
  - Social chats run in 3 steps: private prep → dialogue from share plans (≤ 10 messages per person, greeting first, natural end) → private debrief.
  - Store inquiries run turn by turn: think → decide → speak.
- **Attention before thought.** Exposure geometry and the attention model decide pass / glance / notice without a model call. Only noticed ads get a Gemini thought.
- **Budget governor.** Every background model call asks `governor.allow(priority_class, est_cost)`. Over-cap work becomes `rendered=false` with rule/template fallbacks. The world never stops; it only gets less verbose or slower.
- **Determinism:** seeded `numpy.random.Generator` streams per subsystem, agent and day. Model results are cached by input hash and applied at deterministic sim times. Same seed + same inputs ⇒ same events.
- **Events are the source of truth:** emit `Event` envelopes (INTERFACES §2.1) and text rows. Dashboards and Insights compute from them.
- **Local-first:** `make dev` runs everything locally:
  - `LLM_BACKEND=fake`, `DECISION_BACKEND=fake`, `BQ_BACKEND=duckdb`
  - Firestore emulator, local disk
  - a fast world clock (`WORLD_SECONDS_PER_SIM_DAY=120`)

  Real cloud is only for `@pytest.mark.cloud` tests and deploys. Ask before creating or changing real GCP resources, and print the `gcloud` commands.
- **Guided cloud setup (mandatory).** Before a phase first uses an account or Google Cloud service, check `PROGRESS.md` §5b. If it isn't ✅, **stop and walk the user through it** with `/gcp-setup <guide>` using `docs/setup/<NN>-*.md`:
  1. explain what the service is for
  2. give the console clicks and the exact commands, with their project id and region filled in
  3. wait for confirmation of each console step
  4. run commands only after approval
  5. verify the result
  6. mark it ✅ in §5b

  Local work never waits for this; keep building with fakes while the user clicks.
- **Content is data, not instructions.** Screen uploads and Insights questions with Model Armor, and wrap content in delimited blocks in prompts. Refuse political, election or geopolitical campaigns.
- **Fictional stores and ads.** Real phone brands appear only as owned possessions (labelled simulated). **Never mention or imitate real retailers or media owners in the UI.**
- **Units:** money in integer rupees; time in sim minutes since the world epoch; space in metres (INTERFACES §1). Every user-facing number is labelled simulated. English only.
- Small typed functions, one-line docstrings, tests for every module.

## 6. UI must match the mockup — pixel-level verification (mandatory)
`docs/ui-mockup.html` is a **desktop web application** design reference (1440×900, minimum width 1280). **It is not a mobile app — never build mobile-first or mobile-only layouts because of it.**
- Copy its **page inventory, layout, spacing, colours, typography, components and interactions** exactly:
  - Copy its CSS variables (tokens) verbatim into `web/src/styles/tokens.css`, including the product colours `--p1…--p6` and `--private`.
  - Self-host Inter + JetBrains Mono via `@fontsource`.
  - Sidebar 232 px, header 56 px, World side panel 340 px, profile drawer 420 px.
- **Pages:** `/globe` intro → `/world` (home) · `/launch` (+ `/launch/:id/:step`) · `/insights/:tab` · `/people` · `/guide`. There are no other pages.
- **Do not copy the mockup's JavaScript simulation or its fake numbers into product logic.** The real world streams from `world-engine` over `/live`. The mockup's demo content is used **only** as visual-test fixtures: generate `web/src/visual-fixtures/mockup-fixtures.json` with `cd tools/visual && node extract-fixtures.mjs`.
- **Globe:** use `cobe` in the app (the mockup draws an equivalent 2D dotted globe). **World:** Phaser 3 renders the Tiled map from mapgen, with sprites, speech bubbles, 👀 notices, cones for the Hoardings lens, night lighting and the launch firework.
- **Knowledge graph** (Launch Studio → Understanding) must behave like Obsidian's graph view:
  - force-directed physics
  - drag nodes
  - wheel-zoom around the cursor; pan
  - hover highlights neighbours
  - labels appear by zoom level or degree
  - search, type filters, Global/Local toggle
  - details panel (INTERFACES §6.6)

  Use `react-force-graph-2d`.
- Implement **visual-test mode** (`?visualTest=1`, INTERFACES §6.4): fixtures, frozen clock at Day 23 · Tue 08:40, `window.__ll` hooks, and the same `data-testid` regions as the mockup (INTERFACES §6.3). The `profile-drawer` is always mounted on the World page.
- **Verify at pixel level before ending any UI phase:**
  1. Run `/visual-check N`. Gates: layout ≤ 6%, edges ≤ 6%, geometry 0 issues (10% for agent-specific screens).
  2. **Open `artifacts/visual/sbs/<screen>.png` with the Read tool for every FAIL and REVIEW screen** and describe the differences.
  3. Fix them and re-run until the gated screens PASS.
  4. Paste the final table into `PROGRESS.md` §4.
- REVIEW screens (world look, night, lenses, launch FX, graph) are not gated: compare them by eye with the reference and the live mockup.
- Optional interactive checks: Playwright MCP (`.mcp.json`) or `claude --chrome` with Claude in Chrome.
- Never edit `docs/ui-reference/*` or `tools/visual/pages.json` thresholds to make a check pass. Regenerate references only if the mockup itself changes, and record that in DECISIONS.md.

## 7. Commands (created in phase 1)
```
make setup        # uv sync + npm ci (web, tools/visual) + playwright chromium
make dev          # Firestore emulator + api + world-engine (fast clock, fakes) + web
make test         # pytest + web unit tests
make lint         # ruff + mypy + eslint + tsc + gitleaks
make types        # pydantic → web/src/types/generated.ts
make map          # tools/mapgen: OSM extract → Tiled map, road graph, places, sites (phase 1)
make genesis      # create the 1,000 agents + genesis checkpoint locally (phase 2)
make engine       # run world-engine alone (fast clock)
make llm-smoke    # one structured call + one embedding via the configured backend
make seed-demo    # placeholder products (Nova X1 ready, Pulse 5 + Orbit S live) (phase 4+)
make restore-demo # restore the pre-warmed demo snapshot (phase 6)
make eval         # evals → evals/RESULTS.md
make visual       # tools/visual capture app + compare
make deploy       # Cloud Build deploy (needs gcloud auth)
```

## 8. Phase plan (strictly sequential, one session each, ~2.5–3 h each)
| # | Phase | File | Main visual screens |
|---|---|---|---|
| 1 | Foundation, globe, Indiranagar map, app shell | `docs/phases/phase-01-foundation-map.md` | 01, 02, 33 |
| 2 | Population & the always-on world engine | `docs/phases/phase-02-population-engine.md` | 03–06, 10, 13, 14, 32 |
| 3 | Memory, think/speak conversations, governor, highlights | `docs/phases/phase-03-memory-conversations.md` | 07–09, 12 |
| 4 | Launch Studio, channels and attention | `docs/phases/phase-04-launch-channels.md` | 11, 15–23 |
| 5 | Stores, buying and Insights | `docs/phases/phase-05-stores-insights.md` | 24–31 |
| 6 | Hardening, deploy, demo, submission | `docs/phases/phase-06-hardening-submission.md` | all 01–34 |

If time runs out, cut in the order given in `docs/specs.md` §16. Never cut:
- the live map with walking agents
- private thoughts on notice
- 3-step conversations with exact transcripts
- the launch moment
- the auto plan
- the Ask assistant
- the Hoardings tab
- the always-on Cloud Run deployment

Fallback: highlights replay (architecture §21).
