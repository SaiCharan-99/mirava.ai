# Launch Lens: Product Specification v3 — Always-on Agent World

*Version 3.0 · 17 Oct 2026 · Google Cloud AI Builder Cup 2026 · Theme: Retail & Commerce*
*Working name. Replaces specs v2 (branch-based campaign tests). Architecture: `docs/architecture.md` v3. Contracts: `docs/INTERFACES.md` v3.*

---

## 0. How to read this document

| Tag | Meaning |
|---|---|
| `DEMO` | Built for the hackathon prototype (due 18 Oct 2026) |
| `STRETCH` | Build if time allows in its phase; the demo works without it |
| `V1` | First product release after the hackathon |

- §1 What we are building. §2 Core concepts (read first).
- §3 Spec index with build phase.
- §4–§15 Specs by group, each with *what*, *example* and *done when*.
- §16 Demo scope and cut order. §17 Technical challenges. §18 Out of scope. §19 Open decisions.

**Placeholder demo content.** Three fictional phones are used only for fixtures and tests. The team enters its real marketing content in Launch Studio.
- **Arcline Nova X1**: ₹89,999 flagship, camera-led claims, no-cost EMI
- **Kestrel Pulse 5**: ₹24,999 mid-range, battery-led claims
- **Lumen Orbit S**: ₹49,999 slim design, AI features

The platform is product-agnostic. A clothing brand can be launched later into the same world.

---

## 1. Product overview

**One sentence.** An always-on world of 1,000 AI agents living in a pixel-art Indiranagar (Bengaluru). Each agent has a personality, private memory, routine, money, relationships and a phone of a certain age. Product teams launch their products and marketing into this world, then ask what people noticed, thought, said to each other, asked in stores and bought, and **why**.

**Two layers.**
1. **The World** is the product. It runs continuously on Google Cloud (1 sim day = 1 real hour) whether anyone is watching or not, and keeps accumulating memories, conversations and opinions.
2. **Launch Lens** is the first use case. Launch Studio defines products and their content. Each product is launched into the world, and Insights answers questions about perception, attention, word of mouth, store inquiries and likely-buyer segments.

**What changed from v2.**
- There is one live world instead of per-test branches.
- The World page is the home page.
- Placement is automatic.
- Agents keep private thoughts separate from public speech.
- Every conversation that is rendered is logged exactly.
- A Gemini assistant answers any question over the accumulated data.
- A Hoardings view measures out-of-home attention by site and facing.

---

## 2. Core concepts

| Term | Meaning |
|---|---|
| **World** | The single live simulation: map, 1,000 agents, clock, products. Never reset during the demo |
| **Sim day** | One day of world time; by default lasts 1 real hour |
| **Agent** | A simulated person with persona, memory, needs, routine, money, possessions and relationships |
| **Special agents** | Reviewers/influencers (~10), salespeople (~8), news desk (1); all part of the 1,000 |
| **Persona card** | The short, fixed self-description included in every model call for that agent |
| **Private thought** | Something an agent thinks; stored only in its own memory and in the raw log; never given to another agent |
| **Public speech** | Messages actually spoken, posts actually published, reviews actually released; the only things other agents can receive |
| **Share plan** | What an agent has decided to say in a conversation, chosen privately before it starts |
| **Episodic memory** | A first-person summary of an episode the agent can recall later |
| **Belief** | What an agent currently believes about a product, brand or category: awareness, attitude, reasons, first-heard source, consideration stage |
| **Exposure** | An agent's opportunity to see an ad; outcome pass / glance / notice |
| **OTS** | Opportunity to see: agent in a hoarding's cone, in front of it and looking towards it |
| **Product** | Something launched into the world with content and an automatic plan |
| **Plan** | Sites + facings, reel audience, newspaper insertions, reviewers, community seeding, stores |
| **Launch** | The moment a ready product enters the live world (stamped time) |
| **Consideration stage** | unaware → aware → curious → researching → inquiring → deciding → purchased / postponed / rejected |
| **Highlights** | The most important moments of a sim day, replayable on the timeline |
| **Budget governor** | Keeps background model spend within $15/day by capping work and, if needed, slowing time |
| **Rendered / unrendered** | Rendered work used a model call; unrendered work used rules/templates because of the budget (flagged in data) |

---

## 3. Spec index

| ID | Feature | Tag | Phase |
|---|---|---|---|
| **W — World & time** | | | |
| W-01 | Globe intro and fly-in | DEMO | 1 |
| W-02 | Indiranagar map from OpenStreetMap | DEMO | 1 |
| W-03 | Places, lots and points of interest | DEMO | 1 |
| W-04 | Hoarding site inventory (facing, size, lit, cone) | DEMO | 1 |
| W-05 | World clock and time scale | DEMO | 2 |
| W-06 | Always-on world engine service | DEMO | 2 |
| W-07 | Live viewing stream | DEMO | 2 |
| W-08 | Day highlights and highlight replay | DEMO | 3 |
| W-09 | World stats bar | DEMO | 2 |
| W-10 | Day/night lighting | DEMO | 1 |
| **P — Population** | | | |
| P-01 | 1,000 agents sampled from priors | DEMO | 2 |
| P-02 | Persona core | DEMO | 2 |
| P-03 | Households and relationship graph | DEMO | 2 |
| P-04 | Routines and media diet | DEMO | 2 |
| P-05 | Money and affordability | DEMO | 2 |
| P-06 | Phone possessions and life events | DEMO | 2 |
| P-07 | On-demand category bootstrap (e.g. clothing) | STRETCH | 4 |
| P-08 | Special agents: reviewers, salespeople, news desk | DEMO | 2 |
| P-09 | Population audit and assumptions view | V1 | — |
| **E — Engine** | | | |
| E-01 | Day loop: needs, routine, plans | DEMO | 2 |
| E-02 | Movement on the road graph with modes and headings | DEMO | 2 |
| E-03 | Encounter detection | DEMO | 3 |
| E-04 | Event log (Pub/Sub → BigQuery events, texts) | DEMO | 2 |
| E-05 | Budget governor and cost meter | DEMO | 3 |
| E-06 | Determinism and seeds | DEMO | 2 |
| E-07 | Checkpoint, resume, single-writer lease, watchdog | DEMO | 2 |
| **M — Memory** | | | |
| M-01 | Raw log (exact) | DEMO | 3 |
| M-02 | Working memory | DEMO | 3 |
| M-03 | Episodic memory, embeddings and retrieval | DEMO | 3 |
| M-04 | Beliefs per product, brand and category | DEMO | 3 |
| M-05 | Nightly reflection and pruning | DEMO | 3 |
| M-06 | Persona card and context assembly | DEMO | 3 |
| M-07 | Isolation: private vs public channels | DEMO | 3 |
| **A — Attention** | | | |
| A-01 | Exposure geometry | DEMO | 4 |
| A-02 | Attention model (pass / glance / notice) | DEMO | 4 |
| A-03 | Private thought on notice + belief update | DEMO | 4 |
| A-04 | Feed and print attention | DEMO | 4 |
| A-05 | Repetition: novelty, wear-out, frequency caps | DEMO | 4 |
| A-06 | Hoarding metrics | DEMO | 4 |
| **C — Channels** | | | |
| C-01 | Hoardings and bus shelters | DEMO | 4 |
| C-02 | Reels / video feed to interested agents | DEMO | 4 |
| C-03 | Newspaper | DEMO | 4 |
| C-04 | Reviewer agents (private opinion vs published review) | DEMO | 4 |
| C-05 | Reddit-style community (read, post, comment) | DEMO | 4 |
| C-06 | Store displays | DEMO | 4 |
| C-07 | Word of mouth | DEMO | 3 |
| C-08 | Baseline ads of other brands | DEMO | 4 |
| **T — Talk** | | | |
| T-01 | Encounter gate and priority | DEMO | 3 |
| T-02 | Three-step conversation (private prep → dialogue → private debrief) | DEMO | 3 |
| T-03 | Store inquiry, turn by turn (think → decide → speak) | DEMO | 5 |
| T-04 | Exact transcripts and episodic summaries | DEMO | 3 |
| T-05 | Short stranger exchanges | DEMO | 3 |
| T-06 | Sessions and participant locks | DEMO | 3 |
| T-07 | Unrendered interactions under budget | DEMO | 3 |
| **S — Shopping** | | | |
| S-01 | Need state | DEMO | 5 |
| S-02 | Consideration state machine | DEMO | 5 |
| S-03 | Research and store-visit planning | DEMO | 5 |
| S-04 | Stores, stock and salespeople | DEMO | 5 |
| S-05 | Purchases (cash / card / EMI) | DEMO | 5 |
| S-06 | Baseline market products | DEMO | 5 |
| **L — Launch Studio** | | | |
| L-01 | Products list and editor (multiple products) | DEMO | 4 |
| L-02 | Content upload and screening | DEMO | 4 |
| L-03 | Understanding: profile, claim risk, creative salience | DEMO | 4 |
| L-04 | Interactive knowledge graph (Obsidian-style) | DEMO | 4 |
| L-05 | Target personas → audience rules | DEMO | 4 |
| L-06 | Automatic placement with reasons | DEMO | 4 |
| L-07 | Ready queue and launch dock | DEMO | 4 |
| L-08 | Launch moment (firework drop) | DEMO | 4 |
| **I — Insights** | | | |
| I-01 | Ask assistant | DEMO | 5 |
| I-02 | Overview: product comparison over time | DEMO | 5 |
| I-03 | Sources and paths | DEMO | 5 |
| I-04 | Hoardings (out-of-home) | DEMO | 5 |
| I-05 | Segments and likely-buyer profiles | DEMO | 5 |
| I-06 | Conversations: topics, sentiment, public vs private | DEMO | 5 |
| I-07 | Poll all agents | DEMO | 5 |
| I-08 | Interview one agent | DEMO | 5 |
| I-09 | Faithfulness and citations | DEMO | 5 |
| **U — UI** | | | |
| U-01 | App shell and theme | DEMO | 1 |
| U-02 | World page | DEMO | 1–4 |
| U-03 | Hover card | DEMO | 2 |
| U-04 | Profile drawer | DEMO | 2–3 |
| U-05 | People directory and watchlist | DEMO | 2 |
| U-06 | Launch Studio pages | DEMO | 4 |
| U-07 | Insights pages | DEMO | 5 |
| U-08 | Guide | DEMO | 1, 6 |
| U-09 | Visual-test mode and pixel parity | DEMO | 1–6 |
| **X — Platform** | | | |
| X-01 | LLM gateway (OpenRouter default, Vertex switch) | DEMO | 1 |
| X-02 | Deploy: Hosting, api, world-engine | DEMO | 1–2 |
| X-03 | Security: secrets, IAM, Model Armor | DEMO | 4, 6 |
| X-04 | Observability and budget alerts | DEMO | 6 |
| X-05 | Demo seed, pre-warm and fallback | DEMO | 6 |
| X-06 | Evals | DEMO | 6 |

---

## 4. W — World & time

### W-01 Globe intro and fly-in `DEMO`
**What.** The first visit in a browser session opens on a dark page with a slowly rotating 3D dotted globe (`cobe`). A pulsing marker sits at Bengaluru with the label "Indiranagar · 1,000 agents · live", and a small stats line shows sim day and conversations today. **Enter world** (or a click on the marker) zooms the globe towards the marker and cross-fades into the World page centred on Indiranagar metro. **Skip** goes straight to the World, and later visits in the same session skip the globe.
**Example.** A judge opens the URL: the globe turns to India, the marker pulses, they click *Enter world* and land on 100 Feet Road at 08:40 with commuters walking to the metro.
**Done when.** The intro plays at 60 fps on a laptop. Without WebGL the app goes straight to the World. The visual-test route shows the intro frame with the globe canvas hidden.

### W-02 Indiranagar map from OpenStreetMap `DEMO`
**What.** `tools/mapgen` builds the city from OSM data for bbox 12.962–12.984 N, 77.630–77.652 E: landuse, roads by class and width, metro viaduct and station, buildings with roof styles by type, parks, labels for main roads, and the attribution "© OpenStreetMap contributors". The output is a Tiled map (8 m tiles), a road graph and a tileset in the mockup's pixel style.
**Example.** 100 Feet Road appears as a wide arterial with shops on both sides, CMH Road carries the metro line, and the residential grid of HAL 2nd Stage fills the blocks between.
**Done when.** `make map` regenerates the map deterministically from the committed OSM extract. Every road segment in the graph is reachable. The map renders in Phaser with lighting. Attribution is visible.

### W-03 Places, lots and points of interest `DEMO`
**What.** Places derived from OSM tags plus overrides: homes (split into ~400 households), offices and a tech park, shops, cafés and restaurants, three fictional electronics stores and an online store, schools and a college, gyms, parks, the metro station, bus stops, and a newspaper vendor. Each place has entrances, capacity and opening hours.
**Done when.** `places.json` validates. Every agent's home and work places exist. The stores exist at their configured lots.

### W-04 Hoarding site inventory `DEMO`
**What.** About 60 candidate sites at major junctions, along arterials, at metro pillars and exits, at bus shelters and on façades. Each has position, one or two facing directions towards oncoming traffic, size class, width/height, lit flag, cone half-angle, max distance, a simulated weekly rate card and an area label.
**Example.** `S-100FT-07`: a 40×20 ft lit billboard at 100 Feet Road × 12th Main, facing north (towards southbound traffic) and south.
**Done when.** `sites.json` validates. Cones render in the Hoardings lens. The geometry function passes unit tests (in front / behind / out of range / heading away).

### W-05 World clock and time scale `DEMO`
**What.** Sim time in minutes since the world epoch. The default scale is 1 sim day = 1 real hour, configurable (`WORLD_SECONDS_PER_SIM_DAY`). The clock can be paused for maintenance and slowed by the budget governor. The header shows "Day 23 · Tue 18:40 · 1 day = 1 h".
**Done when.** The clock is monotonic across restarts (from the checkpoint). The scale change takes effect within one tick. A slowed state is shown in the header.

### W-06 Always-on world engine service `DEMO`
**What.** The `world-engine` Cloud Run service runs the world loop continuously (exactly one instance, CPU always allocated). It holds a single-writer lease in Firestore, serves `/live` and `/healthz`, and receives commands from `api` on an IAM-authenticated `/commands` endpoint.
**Done when.** With no browser open, sim time advances by ~24 sim days per real day. Two instances never write at once (lease test). A forced restart resumes from the last checkpoint with no duplicate events.

### W-07 Live viewing stream `DEMO`
**What.** A WebSocket `/live` sends a `hello` snapshot, then movement segments, events (bubbles, notices, launches, purchases, posts), stats and clock frames. The browser interpolates movement at 60 fps.
**Done when.** Two browsers see the same agents in the same places (within 1 s). Reconnecting after a network drop resumes without reloading. Bandwidth is < 10 KB/s for 1,000 agents.

### W-08 Day highlights and highlight replay `DEMO`
**What.** At the end of each sim day the engine writes the ~40 most important moments, plus 10-minute position samples. The timeline lists past days, and clicking a day plays a highlight reel in which the camera moves between moments with their bubbles and thoughts.
**Done when.** Highlights exist for every completed sim day. The replay plays the moments in order. Clicking a moment opens the agent's profile at that conversation or thought.

### W-09 World stats bar `DEMO`
**What.** Agents, households, relationships, conversations today and total, thoughts today, products live, and budget used today.
**Done when.** The numbers match the BigQuery counts for the same sim day within a minute.

### W-10 Day/night lighting `DEMO`
**What.** Lighting follows the clock. Lit hoardings, shop fronts and street lights glow at night.
**Done when.** The night review screen matches the mockup by eye.

---

## 5. P — Population

### P-01 1,000 agents sampled from priors `DEMO`
**What.** A seeded sampler produces age, gender, household role, education, occupation, workplace, income band, commute mode and home location. Priors come from BigQuery public datasets (Census IDB, World Bank WDI) and `config/markets/indiranagar.yaml`. Assumed values are flagged.
**Done when.** Marginals match the configured targets within 3 percentage points. The same seed produces identical agents.

### P-02 Persona core `DEMO`
**What.** Gemini Flash writes, in batches, a first-person bio, Big Five, values, lifestyle cluster, interests, brand attitudes, speaking style and **disclosure style** for every agent, consistent with the sampled attributes.
**Example.** "I'm Meera, 29, a UX designer at a fintech on Old Airport Road. I shoot street photos on weekends and I'm careful with money — I compare everything before I buy." Disclosure: opinions open, money private.
**Done when.** All 1,000 personas validate against the schema and attributes (age/job/income consistent). Each persona card is ≤ 150 tokens.

### P-03 Households and relationship graph `DEMO`
**What.** Households live in residential buildings. Edges cover family, partner, friends, colleagues, neighbours and followers (of reviewers), each with a closeness from 0 to 1. The average degree is ~13.
**Done when.** The graph is symmetric (except followers) and has no isolated agents. The Relations tab shows the edges. Stats show the total.

### P-04 Routines and media diet `DEMO`
**What.** Weekday and weekend routines by occupation and lifestyle. Media diet: Instagram/YouTube feed sessions, community usage, newspaper reading, news app.
**Done when.** Every agent has a valid routine for both day types. Feed sessions and newspaper reading happen at the configured times.

### P-05 Money and affordability `DEMO`
**What.** Monthly salary (weekly for gig workers), fixed costs, savings, credit card and limit, EMI eligibility, and payday.
**Done when.** Affordability for a price can be computed for every agent. Paydays emit events.

### P-06 Phone possessions and life events `DEMO`
**What.** Every agent owns a phone: real market brand (simulated shares by price band), model tier, purchase date (age), condition, battery health, satisfaction and history. Daily hazards create lost/broken/slow events that rise with age.
**Example.** Ravi, 41, Xiaomi mid-tier bought 5.6 years ago, battery weak, satisfaction low. On day 12 his screen cracks and his need jumps.
**Done when.** The phone-age distribution looks plausible (median ~2.5 years, ~15–20% older than 5 years, labelled assumption). Life events occur at configured rates. "Phones older than 5 years" can be filtered on the People page and in SQL.

### P-07 On-demand category bootstrap `STRETCH`
**What.** When a product of a new category is launched, Gemini defines the category's possession schema from the brief and fills it for every agent in batches.
**Done when.** Launching a clothing product creates per-agent clothing state within ~2 sim hours, and Insights can filter on it.

### P-08 Special agents `DEMO`
**What.** ~10 reviewers/influencers (6 tech, 4 lifestyle) with followers, ~8 salespeople (2 per physical store, on shifts) and 1 news desk agent. All are part of the 1,000.
**Done when.** Each has its role-specific routine and tools, and appears with a role badge in the profile.


### P-09 Population audit and assumptions view `V1`
**What.** A page comparing generated marginals with targets, listing every assumed field and small-segment warnings.
**Done when.** (V1) Audit numbers match `agents_latest`; assumptions listed with sources.

---

## 6. E — Engine

### E-01 Day loop `DEMO`
**What.** Each tick (1 sim minute): needs drift, the routine or plan picks the activity, transitions emit events, and wake-up planning builds today's plan, including intents such as research, visit store and meet friend.
**Done when.** Agents sleep, commute, work, eat, shop and socialise on time, and needs stay within bounds over 7 sim days.

### E-02 Movement `DEMO`
**What.** A* on the road graph with walk / two-wheeler / car / auto / bus / metro. Agents follow segments with headings, and only metro riders "jump" between stations (shown on the viaduct).
**Done when.** No agent walks through buildings. Commute durations are plausible. Heading is available for the attention model.

### E-03 Encounter detection `DEMO`
**What.** A spatial hash finds co-located available agents (≥ 2 sim minutes) and sends them to the gate.
**Done when.** A unit test with scripted positions yields the expected pairs. There are no self-pairs or duplicates.

### E-04 Event log `DEMO`
**What.** Every change emits an `Event` envelope. Events are published in batches to Pub/Sub `world-events` → BigQuery `events`. Texts go to `world-texts` → `texts` with embeddings. DuckDB is used locally.
**Done when.** Event ids are deterministic and idempotent. Counts in BigQuery match the engine counters.

### E-05 Budget governor and cost meter `DEMO`
**What.** Tracks the actual model spend from OpenRouter usage. Caps work by priority class each sim hour, marks over-cap work `rendered=false`, and slows time in steps if needed. The header shows the budget used today.
**Done when.** In a cost-simulation test with a $15/day target, spend stays within ±10%, priorities are respected, and slowing kicks in only when P0–P2 alone exceed the budget.

### E-06 Determinism and seeds `DEMO`
**What.** Seeded RNG streams per subsystem/agent/day, model results cached by input hash, and results applied at deterministic sim times.
**Done when.** Two local runs of 2 sim days with fakes produce identical event hashes.

### E-07 Checkpoint, resume, lease, watchdog `DEMO`
**What.** A checkpoint every sim hour to GCS, a Firestore lease for a single writer, and a Cloud Scheduler watchdog on `/healthz`.
**Done when.** Killing the container mid-day and restarting continues from the checkpoint. A second engine stays read-only while the lease is held.

---

## 7. M — Memory

### M-01 Raw log `DEMO`
**What.** The exact text of every thought, message, share plan, debrief, post and review, plus every exposure, inquiry, purchase and belief change, stored immutably in BigQuery.
**Done when.** Any conversation can be reconstructed message by message from BigQuery. Any agent's thought history can be listed in time order.

### M-02 Working memory `DEMO`
**What.** In-RAM: today's activity, plan, last ~20 observations, open intents, mood and needs.
**Done when.** Working memory is included (compact) in every agent prompt and reset/rolled over at night.

### M-03 Episodic memory, embeddings and retrieval `DEMO`
**What.** First-person episode summaries with importance, kind, source, entities, event refs and a 768-d embedding, in Firestore with a vector index. Retrieval = recency × importance × relevance, filtered to one agent, top 6.
**Example.** Asked by a friend about phones, Meera recalls "the Nova X1 billboard at the metro looked stunning at night" and "Ravi complained his old phone keeps dying".
**Done when.** The retrieval test returns the planted relevant memory in the top 6 for the agent, and never another agent's memories.

### M-04 Beliefs `DEMO`
**What.** Per agent × subject (product, brand, category): awareness, attitude −1…+1, confidence, reasons for/against, first heard via, sources seen, consideration stage, open questions. Daily snapshots go to BigQuery.
**Done when.** Belief changes are logged with cause (event ref). First-heard never changes after it is set. `beliefs_latest` matches Firestore.

### M-05 Nightly reflection and pruning `DEMO`
**What.** At 03:00 sim time, agents with daily importance ≥ 12 reflect (within the governor's cap). Reflections become memories and belief updates. Episodic memory is pruned to 300 per agent (the raw log keeps everything).
**Done when.** Reflections reference real episodes of that day. Pruning never touches BigQuery.

### M-06 Persona card and context assembly `DEMO`
**What.** `mind.context.build(agent, purpose, query)` assembles the persona card + now + relevant beliefs + top-k memories + stimulus, capped at ~900 tokens.
**Done when.** Every agent prompt is built through it (lint rule/test). The persona-consistency eval scores ≥ 0.8.

### M-07 Isolation: private vs public `DEMO`
**What.** A single-agent MemoryStore, typed SharePlans for shared prompts, and a salesperson context of the public transcript only. Marker-fact tests.
**Done when.** The marker fact planted in A's private memory never appears in B's outputs unless A said it (evaluated over 200 conversations, 0 leaks).

---

## 8. A — Attention

### A-01 Exposure geometry `DEMO`
**What.** OTS when the agent is in front of the face, inside the cone, within range and looking roughly towards it. Dwell comes from the segment; night OTS counts only if the board is lit.
**Done when.** Geometry unit tests pass, and OTS counts per site are stable across identical runs.

### A-02 Attention model `DEMO`
**What.** A logistic model for glance and for notice given glance, with size/distance, dwell, lighting, salience, clutter, phone use, fatigue, driving, relevance, novelty, attitude, clarity, brand familiarity and need. The coefficients are labelled assumptions in config.
**Done when.** Default calibration gives 30–40% glance and 4–10% notice of OTS on the demo world. Changing a coefficient changes the rates in the expected direction.

### A-03 Private thought on notice `DEMO`
**What.** A Flash-Lite call with the agent's context and the creative's description returns a thought, why it was noticed, an attitude delta, reasons, open questions, an intent change, who/what it wants to tell, and importance. The thought is private.
**Example.** "That 'best camera ever' line is a bit much, but if the night shots are real I'd want to see it — my phone's camera is useless after 7 pm."
**Done when.** Every rendered notice has a thought event, a memory and a belief update. Over-cap notices are logged `rendered=false` with a rule-based update.

### A-04 Feed and print attention `DEMO`
**What.** Feed items get scroll-past / partial / full outcomes, and print ads get attention by size and page.
**Done when.** Exposures from feeds and print appear with outcomes and feed Sources and Hoardings/Overview correctly.

### A-05 Repetition `DEMO`
**What.** Novelty decays with repeats, wear-out applies after ~8 notices, and reels have a frequency cap of 3/day.
**Done when.** The notice probability for the 10th exposure is lower than for the 2nd for the same agent and creative.

### A-06 Hoarding metrics `DEMO`
**What.** Per site × facing × product × day (and by hour and segment): OTS, glance rate, notice rate, thoughts, sentiment, top themes, target share and cost per notice (simulated).
**Done when.** `v_site_daily` returns these, and the totals equal the sum of exposure events.

---

## 9. C — Channels

### C-01 Hoardings and bus shelters `DEMO`
**What.** Planned sites show the product's creative from launch for the flight (default 21 sim days), visible on the map with their facing arrows.
**Done when.** After launch the sites flip to the creative and exposures start.

### C-02 Reels / video feed `DEMO`
**What.** Reel creatives (transcript + scenes + thumbnail) are delivered to agents matching the audience rules, ranked higher for interested agents, with a daily impression budget and frequency cap.
**Example.** Agents interested in photography and tech see the Nova X1 "After dark" reel in their evening Instagram session; most scroll past and a few watch fully and think.
**Done when.** The share of reel exposures going to the target audience is ≥ 70%, and interested agents get a higher notice rate than others.

### C-03 Newspaper `DEMO`
**What.** A daily edition with print ads and news items. Newspaper readers see it at breakfast.
**Done when.** Print exposures exist only for newspaper readers on insertion days.

### C-04 Reviewer agents `DEMO`
**What.** At launch, matching reviewers form a private opinion (Flash), then publish a review (title, summary, rating, pros/cons) that reaches followers' feeds and community threads.
**Example.** A tech reviewer privately thinks "the camera is great but the battery claim is marketing", and publishes "Nova X1: the best low-light camera I've tested — battery is just okay. 8/10".
**Done when.** The private opinion and the published review are both logged and linked. Followers receive the review in their feed within 1 sim day.

### C-05 Reddit-style community `DEMO`
**What.** Forums `r/IndiranagarLife` and `r/BangaloreTech`, with threads from the news desk, reviewers and agents. Agents read, privately think, then may upvote, comment or post.
**Done when.** Threads and comments appear in the Conversations tab with authors. The private thought and the public comment of the same agent are both stored and linkable.

### C-06 Store displays `DEMO`
**What.** Stocking stores show the product display. Agents inside a store are exposed.
**Done when.** Store exposures exist after launch for agents who visit stocking stores.

### C-07 Word of mouth `DEMO`
**What.** Conversations carry product talk when it is in a share plan. First-heard can be attributed to a person.
**Done when.** Sources shows a word-of-mouth share, and the chain "A noticed → told B → B became curious" is traceable.

### C-08 Baseline ads `DEMO`
**What.** Fictional ambient brands (food delivery, bank, streaming, fashion) on some sites and in feeds before and after launches.
**Done when.** Sites show baseline creatives when not used by a launched product. Baseline exposures are counted (thoughts sampled at a low rate).

---

## 10. T — Talk

### T-01 Encounter gate and priority `DEMO`
**What.** Rules → who (known people; strangers only in specific places) → decision model `{talk, topic_candidates}` → priority (product relevance, watched agents, closeness) → the governor decides rendered vs unrendered.
**Done when.** Gate decisions are logged with reasons. Strangers never have long conversations. Product talk only happens when one side has the product salient and the other is interested in the category or shares the interest.

### T-02 Three-step conversation `DEMO`
**What.**
1. Private prep per agent: candidate thoughts → the decision model chooses what to share → SharePlan.
2. One dialogue call that sees only the two SharePlans, styles, relationship and place: a greeting first, up to 10 messages per person, ending naturally.
3. Private debrief per agent: reaction, belief deltas, episodic summary, intents.

**Example.** Meera (prep: share "billboard looked great", ask "is the battery good?", withhold "can't afford it this month") meets college friend Arjun (prep: share "reviewer says battery is just okay").
- Arjun: "Hey Meera! Long time — how's the new job?"
- … 14 messages …
- Meera: "Okay I'll check it at Digital Bazaar on Saturday."

Meera's debrief: curious → researching. Her withheld item never appears.
**Done when.** Messages ≤ 20 with a greeting first. Share plans and debriefs are private to their agent. The isolation eval passes (M-07).

### T-03 Store inquiry, turn by turn `DEMO`
**What.** For each customer turn: a private thought, then the decision model picks speak/hold and what to say, then Flash-Lite writes one utterance. The salesperson agent (ADK) answers from product facts, stock and offers, seeing only the spoken transcript. Up to 10 messages each. The customer's debrief and an `inquiry` event record the questions asked, topics, whether they were answered, satisfaction and outcome.
**Done when.** The salesperson never receives customer thoughts (test). Inquiry events list question topics. The profile shows the visit transcript with the customer's private thoughts interleaved for that agent only.

### T-04 Exact transcripts and episodic summaries `DEMO`
**What.** Each message is logged exactly (`message` events + `texts`), with a `conversation` summary event. Each participant gets its own episodic summary.
**Done when.** The Conversations tab in the profile shows the full transcript. BigQuery reconstructs it exactly.

### T-05 Short stranger exchanges `DEMO`
**What.** In stores, queues, bus stops and cafés, strangers may exchange ≤ 4 messages each, with low disclosure.
**Done when.** Stranger sessions are tagged and never exceed 4 messages per person.

### T-06 Sessions and locks `DEMO`
**What.** SessionRegistry assigns ids, locks participants and releases on end or timeout. Talkers stop and face each other on the map.
**Done when.** No agent is ever in two sessions at once (property test).

### T-07 Unrendered interactions `DEMO`
**What.** When the governor declines to render, an `interaction` event (topic, minutes, rendered=false) and a template memory are written, and relationship closeness still updates.
**Done when.** The rendered/unrendered ratio is visible in stats and Insights caveats.

---

## 11. S — Shopping

### S-01 Need state `DEMO`
**What.** A need from 0 to 1 per category. For phones it comes from age, condition, battery, lost/broken flags, satisfaction and job dependence. Life events push it up.
**Done when.** Need is visible in the profile, and a broken phone raises need above the inquiry threshold.

### S-02 Consideration state machine `DEMO`
**What.** unaware → aware → curious → researching → inquiring → deciding → purchased / postponed / rejected, with rules in config and the decision model for ties. Transitions are logged.
**Done when.** Every transition has a cause event. The People page filters by stage.

### S-03 Research and store-visit planning `DEMO`
**What.** Researching adds review/community reading to feed sessions. Inquiring adds a store visit to today's plan (nearest stocking store, or online), with open questions carried as the customer's agenda.
**Done when.** Agents with high need and interest visit a store within 3 sim days, given opportunity.

### S-04 Stores, stock and salespeople `DEMO`
**What.** Fictional stores Digital Bazaar (100 Feet Road), ElectroHub (CMH Road), PhoneWorld (12th Main) and online ShopKart, each stocking launched products and the baseline market, with 2 salespeople per physical store on shifts.
**Done when.** Stores open and close on schedule, stock reflects the Launch Studio settings, and inquiries happen only during opening hours.

### S-05 Purchases `DEMO`
**What.** A purchase happens only when need ≥ threshold, affordability holds (cash/card/EMI) and the preference margin ≥ δ. The typed choice includes baseline market options. Possessions and money update.
**Done when.** No purchases come from agents with low need unless a life event happened. The purchase methods split is reported. A new phone resets age to 0.

### S-06 Baseline market products `DEMO`
**What.** Generic current models of the real brands agents know, by tier, with price bands. These are the alternatives in every purchase decision.
**Done when.** Purchases can go to baseline options, and Insights shows our products' share versus baseline.

---

## 12. L — Launch Studio

### L-01 Products list and editor `DEMO`
**What.** Product cards with status (Draft / Ready / Live / Ended) and colour, and "New product". The editor has steps Details → Content → Understanding → Plan → Ready. Details: name, brand, category, price, launch offer, features, claims, target personas, strategy (goal, key message, channels, flight days, intensity), stores.
**Done when.** Three products can be drafted in parallel and saved. Validation errors are shown inline.

### L-02 Content upload and screening `DEMO`
**What.** Upload or enter: hoarding poster, bus-shelter poster, reel (transcript + scenes + thumbnail), social post, newspaper ad, store display, reviewer kit. Model Armor screens all text, which is treated as data.
**Done when.** Signed-URL uploads work, injected instructions are flagged and neutralised (injection suite), and assets show as tiles.

### L-03 Understanding `DEMO`
**What.** Product profile with claims linked to sources, claim risk red/amber/green with reasons, and a StimulusRecord per creative (salience, clarity, hook, claims carried, tone, distance readability, 2-sentence description).
**Done when.** All demo creatives get records. Risky claims are flagged with reasons. Descriptions are used in agent prompts.

### L-04 Interactive knowledge graph `DEMO`
**What.** An Obsidian-style graph view: force-directed physics, drag (neighbours follow), wheel zoom around the cursor, pan, hover highlights neighbours and relation labels, labels by zoom/degree, search, type filters, Global/Local (2 hops), re-layout, fit, and a details panel with linked nodes and (after launch) mention counts from conversations.
**Done when.** Every interaction works smoothly with ≥ 40 nodes, and selecting a node shows details. After launch, node mention counts come from `texts` links.

### L-05 Target personas → audience rules `DEMO`
**What.** Persona chips and free text are compiled by Gemini into audience rules over agent attributes, with live counts ("~420 agents match"). They aim the plan and never change agents.
**Done when.** The rules are shown in plain words, and the counts equal the matching agents in `agents_latest`.

### L-06 Automatic placement with reasons `DEMO`
**What.**
1. A traffic model from the last 7 sim days scores each site × facing for target OTS, glance prior, time fit and rate card.
2. A greedy max-coverage selection picks k sites by intensity; sites held by another live product are excluded.
3. Gemini writes one reason per site.
4. The plan also covers reel audience and impressions, newspaper days, reviewers, community seeding and stocking stores.

It is read-only in the UI.
**Example.** "S-CMH-03 · facing west · metro exit pillar · ~980 target OTS/day — commuters from tech offices leaving Indiranagar metro in the evening."
**Done when.** The plan is generated in < 20 s. Sites shown on the map with facing arrows and reasons match the traffic data. A re-plan is deterministic for the same world day.

### L-07 Ready queue and launch dock `DEMO`
**What.** Ready products appear in a compact dock on the World page, each with its own **Launch** button. Live products show as coloured chips.
**Done when.** The dock lists only Ready products, and launching one removes it from the dock and adds it to Live.

### L-08 Launch moment `DEMO`
**What.** The launch command activates the plan in the engine at the next tick and stamps `launched_at_t`. The browser plays a firework drop: an orb falls, bursts, and particles stream to the sites (which flip), the stores and the audience. A ticker summary follows.
**Done when.** The animation plays on every connected browser (via `/live`). Exposures start within 1 sim hour. The launch marker appears on Insights charts.

---

## 13. I — Insights

### I-01 Ask assistant `DEMO`
**What.** A chat with the Insights assistant (ADK, Gemini 3.1 Pro) with tools `describe_data`, `run_sql`, `semantic_search`, `cohort`, `likely_buyers`, `poll`, `interview` and `chart`. Answers include text, key numbers, charts, verbatim quotes (private thoughts marked as such), the SQL used and caveats, and suggested questions.
**Example.** Q: "People with phones older than 5 years — are they interested in any of our phones?" A: "187 agents (18.7%) have phones older than 5 years. 41% of them are curious or further about at least one of our phones: Pulse 5 leads (29%), mainly for battery and price; Nova X1 is admired but seen as too expensive (only 6% considering)…" + a bar chart + 4 quotes + SQL.
**Done when.** 10 benchmark questions (`evals/insights_questions.yaml`) are answered with correct numbers (verified against SQL), quotes are verbatim, and unanswerable questions are declined with a reason.

### I-02 Overview `DEMO`
**What.** Per product over sim days: awareness, positive attitude, considering+, inquiries and purchases, with launch markers and products side by side.
**Done when.** The numbers equal the view queries, and the launch markers sit at `launched_at_t`.

### I-03 Sources and paths `DEMO`
**What.** First-heard channel per product, the top paths (e.g. hoarding → friend chat → store), and the time from first exposure to inquiry.
**Done when.** Shares sum to 100% of aware agents, and the paths are computed from events.

### I-04 Hoardings (out-of-home) `DEMO`
**What.** A site leaderboard (OTS/day, glance %, notice %, thoughts, sentiment, cost per notice), a facing comparison, an hour-of-day heat, segment mix, a map with sites coloured by notice rate, and a summary of the best real junctions and facings.
**Example.** "100 Feet Road × 12th Main, facing south, gets 2.1× the notice rate of the same board facing north — evening traffic is slower and faces it longer."
**Done when.** The numbers equal `v_site_daily`. The map lens and the table agree. Rows are clickable to show sample thoughts.

### I-05 Segments and likely-buyer profiles `DEMO`
**What.** The likely-buyer score `need × interest × affordability × stage weight`, aggregated by age band × income band × lifestyle, per product, with top reasons from thoughts. There is no per-person prediction.
**Done when.** The heat table renders per product, each cell shows its count and reasons on hover, and the method is explained in the Guide.

### I-06 Conversations `DEMO`
**What.** Topics and sentiment over time, which claims people mention, the **public vs private gap** (said vs thought), community threads, and reviewers' private opinion vs published review.
**Done when.** Each element links to the source transcripts/thoughts.

### I-07 Poll all agents `DEMO`
**What.** Ask everyone (or a cohort) a new question with options. Each agent answers from its persona, beliefs and top memories via the decision model, batched. The result shows a distribution, a segment heat table and quotes, with the cost estimated before running.
**Done when.** 1,000 answers arrive in < 90 s, the same question on the same sim day is deterministic, and the cost is shown.

### I-08 Interview one agent `DEMO`
**What.** Chat with an agent in character, grounded only in its memory (recall tool filtered to that agent). Questions are screened.
**Done when.** Answers cite the agent's real memories, and the marker-fact test shows no other agent's memories.

### I-09 Faithfulness and citations `DEMO`
**What.** Every number traces to a tool result. Quotes are verbatim. On failure the answer is regenerated once, otherwise the claim is dropped. Every answer carries the "Simulated" label and the sim window.
**Done when.** The faithfulness eval passes ≥ 95% on the benchmark set.

---

## 14. U — UI

### U-01 App shell and theme `DEMO`
**What.** Sidebar (232 px): World, Launch Studio, Insights, People, Guide, and a world status card. Header (56 px): world name, LIVE pill, SIMULATED DATA pill, clock, budget meter, theme toggle. Dark theme by default, with a light theme.
**Done when.** The shell matches the mockup at pixel level (gated screens).

### U-02 World page `DEMO`
**What.** A full-bleed live map, stats bar, lenses (Activity, Product awareness, Sentiment, Hoardings), New product button, Ready-to-launch dock, right panel (Happening now / Watching / Products), day timeline with highlights, and minimap. No other campaign controls.
**Done when.** All regions match the mockup, and the lenses and timeline work with live data.

### U-03 Hover card `DEMO`
**What.** Name, age, job, current activity, phone (brand, age), belief chips for live products, and "Click for profile".
**Done when.** It appears within 100 ms of hover and matches the mockup.

### U-04 Profile drawer `DEMO`
**What.** Tabs Overview, Relations, Possessions, Thoughts, Conversations (with full transcript plus this agent's private prep and debrief), Memory (episodic + beliefs). Watch toggle.
**Done when.** All tabs render from live data and match the mockup.

### U-05 People directory and watchlist `DEMO`
**What.** A searchable, filterable, sortable table of all agents (age, job, income band, phone brand/age, awareness/stage per product). Star to watch.
**Done when.** Filtering on "phone age > 5 years" returns the same count as SQL. The watchlist persists and shows in the World panel.

### U-06 Launch Studio pages `DEMO`
**What.** Product list and editor steps as in L-01 … L-07.
**Done when.** It matches the mockup at pixel level (graph and plan-map canvases hidden in gated checks).

### U-07 Insights pages `DEMO`
**What.** Tabs Ask, Overview, Sources, Hoardings, Segments, Conversations, Polls, Interview.
**Done when.** It matches the mockup, and every chart has a data source.

### U-08 Guide `DEMO`
**What.** How the world works, the memory and privacy model, the attention model and assumptions, the budget, data sources and attribution (OSM, public datasets), and limits.
**Done when.** It is complete and matches the mockup.

### U-09 Visual-test mode and pixel parity `DEMO`
**What.** `?visualTest=1`: fixtures, frozen clock, seeded layout, `window.__ll` hooks, the mockup's `data-testid`s. `tools/visual` compares against `docs/ui-reference`.
**Done when.** All gated screens PASS in phase 6.

---

## 15. X — Platform

### X-01 LLM gateway `DEMO`
**What.** `OpenRouterClient` (default), `VertexClient`, `FakeGemini`; structured output, low reasoning effort for engine calls, retries, cache, usage cost; model ids in `shared/models.py`.
**Done when.** `make llm-smoke` passes with the real key, and switching to `vertex` needs only env changes.

### X-02 Deploy `DEMO`
**What.** Firebase Hosting (web), Cloud Run `api`, Cloud Run `world-engine` (always-on), Cloud Build pipeline.
**Done when.** The public URL works logged-out, and the world keeps running with no browser open.

### X-03 Security `DEMO`
**What.** Secrets in Secret Manager, least-privilege service accounts, IAM-authenticated engine commands, Model Armor, a read-only analyst account for Insights SQL, and gitleaks.
**Done when.** The security checklist in phase 6 is ticked.

### X-04 Observability and budget alerts `DEMO`
**What.** Structured logs, tick-lag and spend metrics, an alert on tick lag > 2 min, and GCP budget alerts.
**Done when.** The dashboard exists and the alert test fires.

### X-05 Demo seed, pre-warm and fallback `DEMO`
**What.** `make seed-demo` (3 placeholder phones, ready), a pre-warmed world, `make restore-demo`, and a highlights-replay fallback.
**Done when.** The demo can be restored in < 5 minutes.

### X-06 Evals `DEMO`
**What.** Isolation (marker facts), persona consistency, attention calibration, Insights faithfulness and benchmark, determinism, and budget simulation.
**Done when.** `make eval` writes `evals/RESULTS.md` with all evals green.

---

## 16. Demo scope and cut order

**Demo path (3 min):**
1. Globe → Indiranagar live.
2. Hover and click a person → private thoughts, a full 20-message chat with their private prep/debrief, beliefs, and a phone 5.6 years old.
3. Launch Studio: a product, its content, the graph, the auto plan with reasons.
4. World → **Launch** (firework) → sites flip, reels go out.
5. Insights: ask "phones older than 5 years…", Hoardings leaderboard, Segments.

**Cut order if time runs out** (cut from the top):
1. P-07 category bootstrap
2. W-08 highlight replay (keep the highlights list only)
3. I-08 interview
4. C-05 posting (keep reading seeded threads)
5. C-03 newspaper
6. T-03 turn-by-turn (fall back to the 3-step flow with the salesperson)
7. I-07 polls

**Never cut:**
- globe + live map with walking agents
- private thoughts on notice
- 3-step conversations with exact transcripts
- launch moment
- auto plan
- Ask assistant
- Hoardings tab
- Cloud Run always-on deployment
- public repo
- demo video

## 17. Technical challenges and mitigations
| Challenge | Mitigation |
|---|---|
| Always-on single process on serverless | Lease + checkpoints + watchdog; deterministic resume |
| Model cost of a living world | Governor, priorities, unrendered fallbacks, flex endpoints, low reasoning effort |
| Privacy between agents in shared prompts | Share plans (typed) are the only shared input; marker-fact evals |
| Realistic attention | Geometry + calibrated attention model; labelled assumptions |
| Answering arbitrary questions | Curated views + data dictionary + vector search + faithfulness checks |
| Real map complexity | Committed OSM extract; deterministic mapgen; simplified building styles |

## 18. Out of scope (demo)
- Multiple cities or worlds.
- Sandbox forks and what-if copies.
- Personal ad targeting.
- Per-person purchase prediction.
- Real retailer names.
- Audio or video generation.
- Languages other than English (agents may use common Hindi/Kannada words in speech).

## 19. Open decisions
- The final product name.
- Whether to show the budget meter publicly or only to the team.
- The flight length default (21 sim days).
- The number of hoarding sites per intensity level.
