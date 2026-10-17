# Phase 4 — Launch Studio, channels and attention

**Time box:** ~3 h · **Depends on:** Phase 3 · **Specs:** L-01 … L-08, A-01 … A-06, C-01 … C-06, C-08, P-07 (stretch), U-06, X-03 (Model Armor) · **Visual screens:** `11-world-products`, `18-launch-list`, `19-launch-details`, `20-launch-content`, `21-launch-understand`, `22-launch-plan`, `23-launch-ready`; review `15-world-lens-aware`, `16-world-lens-hoardings`, `17-world-launch-fx`, `21b-launch-graph`

## Goal
Product teams can create **several products**:
- **details and target personas**
- **content**: posters, reel transcripts, posts, newspaper ad, store display, reviewer kit
- **understanding**: claim risk, creative salience, Obsidian-style knowledge graph
- an **automatic plan**: hoarding sites + facing with reasons, reel audience, newspaper, reviewers, community, stores

Ready products appear on the World dock and are **launched one at a time** with the firework drop.

In the live world:
- hoardings are seen through **exposure geometry + the attention model** (pass / glance / notice), and only noticed ads produce **private thoughts**
- reels reach interested agents' feeds; the newspaper carries print ads
- reviewers form private opinions and publish reviews
- the community gets threads, posts and comments
- stores show displays; baseline ads keep the world realistic

## Accounts & cloud setup needed
Walk me through these with `/gcp-setup` before the first step that needs them, unless they're already ✅ in `PROGRESS.md` §5b:
- `/gcp-setup 12` — Model Armor template (local: fake screener)
- `/gcp-setup 08` — uploads bucket CORS includes the Hosting URL (signed-URL uploads)

## Prompt
```
You are starting Phase 4 of Launch Lens in a fresh session.
Read CLAUDE.md, PROGRESS.md, docs/DECISIONS.md and docs/phases/phase-04-launch-channels.md.
Then read: docs/architecture.md §9 (attention), §10 (channels), §13 (Launch Studio), §15; docs/INTERFACES.md §2 (product.py,
community.py, events exposure/thought/launch/review/thread/comment), §3 (attend, ots, plan_product), §4.4 (launch evt),
§5 (products endpoints), §6.3, §6.6; docs/specs.md L-01…L-08, A-01…A-06, C-01…C-06, C-08, P-07.
Look at docs/ui-reference/11, 15–23 (+ 21b) and the live mockup: Launch Studio and the Launch button on the World dock.

Goal: Launch Studio end-to-end + launch moment + attention-driven exposures and private thoughts + all channels.
Run make test first. Finish with make test, make lint, acceptance checks, /visual-check 4, /end-phase. Do not start Phase 5.
```

## Read first
Architecture §9.2 (geometry + attention formulas), §10.2 (channel table), §13.2 (planner algorithm, launch moment). INTERFACES §6.6 (GraphView).

## Build checklist
### Launch Studio backend (L-01 … L-07)
- [ ] Products CRUD (Firestore `products/*`); statuses draft / ready / live / ended; product colours from `--p1…--p6` in order
- [ ] Uploads via signed URLs; **Model Armor** on all text and extracted text; content wrapped as data in prompts
- [ ] Understanding agent (ADK, Flash, multimodal) → product profile with claims linked to sources; claim risk scanner (Pro) → red/amber/green + reason; creative understanding → `StimulusRecord` per creative (salience, clarity, hook, claims carried, tone, readable at distance, 2-sentence description)
- [ ] Knowledge graph build (nodes/edges per INTERFACES §6.6) with node embeddings (for later mention links)
- [ ] Personas → audience rules (Gemini compiles chips + free text into filters) → live counts from agents
- [ ] **Auto planner** (`media/planner.py`): traffic model from the last 7 sim days of movement (OTS per site × facing × hour × segment) → score → greedy max-coverage (k by intensity 4/8/12, 150 m diversity penalty, exclude sites held by live products) → Gemini reason per site; reel audience + impressions/day, newspaper days, reviewers, community seed, stores; deterministic for (product, world day)
- [ ] `POST /products/{id}/ready`, `POST /products/{id}/launch` → engine command

### Engine (A-01 … A-06, C-01 … C-06, C-08)
- [ ] Launch command: activate plan at the next tick, stamp `launched_at_t`, `launch` event, `/live` launch evt with sites/stores/audience ids
- [ ] `media/attention.py`: `ots()` (front, cone, range, heading ≤ 55°, dwell, lit at night) + `attend()` (logistic glance and notice-given-glance from `config/attention.yaml`); novelty / wear-out; every exposure logged (pass / glance / notice)
- [ ] Thought on notice (Flash-Lite, own AgentContext, creative description) → private `thought` event + text + L2 memory + L3 belief update (first_heard) + intents; over-cap → rule nudge + template memory (`rendered=false`)
- [ ] Feed ranker (sessions from media diet; friends' posts, reviewer content, campaign reels for audience rules with freq cap 3/day, baseline ads) → scroll / partial / full → notice → thought
- [ ] Newspaper edition (print ads on insertion days + news desk item) → readers' exposures
- [ ] Reviewers: unit at launch → private opinion (Flash) over 1–3 sim days → published review → followers' feeds + community
- [ ] Community: threads (news desk, reviewers, agents), browsing in sessions → private thought → decision post/comment/upvote → public text (Flash-Lite)
- [ ] Store displays in stocking stores; baseline ads on unused sites and in feeds
- [ ] `v_exposures`, `v_site_daily` views (BigQuery + DuckDB)
- [ ] STRETCH P-07: category bootstrap for a new category (schema → per-agent state, batched)

### Web
- [ ] **Launch Studio** list (`products-grid`, `product-card`, `new-product-card`) and editor (`studio-steps` + 5 steps) exactly like the mockup
- [ ] **GraphView** (`react-force-graph-2d`) with every interaction in INTERFACES §6.6; visual-test: run to rest with fixed seed, `__ll.graphSelect/graphHover`
- [ ] Plan step: `plan-canvas` (map with numbered sites, cones, stores), `plan-sites` (facing arrow, reason, est target OTS/day), `plan-channels`
- [ ] World: `launch-dock` items with **Launch** buttons; **firework drop** (orb → burst → particles to sites and stores → sparkles over audience → sites flip to the creative); ticker summary; `side-tab-products`; lenses **Product awareness**, **Sentiment**, **Hoardings** (cones coloured by notice rate); `__ll.launchFx(pid, progress)`; 👀 notice icons and thought bubbles

## Tests
- Geometry: in front / behind / outside cone / out of range / heading away / unlit at night
- Attention calibration on the demo world: glance 30–40%, notice 4–10% of OTS (labelled assumptions)
- Planner determinism; no site held by two live products; reasons present for every site
- Reels: ≥ 70% of reel exposures go to the audience; interested agents get a higher notice rate
- Injection suite on uploads (instructions inside a poster's text are neutralised)
- Launch: exposures begin within 1 sim hour; every rendered notice has a thought, a memory and a belief update

## Visual check
`/visual-check 4` → gated `11`, `18`–`23` (+ earlier) PASS; review `15`, `16`, `17`, `21b` by eye (cones, firework, graph highlight).

## Acceptance checks
1. `make seed-demo` → Nova X1 ready, Pulse 5 and Orbit S live (placeholder content). Launch Nova X1 from the dock → firework on two browsers at once; its 8 sites flip.
2. Within 2 sim hours: notices with private thoughts on Nova X1 appear in the ticker and profiles; `v_site_daily` has OTS/glance/notice for its sites.
3. A reviewer publishes a review within 3 sim days; a community thread about it has comments.
4. The knowledge graph supports drag, zoom, hover, search, Local mode and the details panel.

## Out of scope
Store inquiries and purchases (phase 5), Insights pages (phase 5).

## Handoff
Product ids, plan outputs, notice rates by site class, thoughts per sim day and cost, reviewer and community activity, any planner edge cases.
