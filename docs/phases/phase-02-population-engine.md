# Phase 2 — Population and the always-on world engine

**Time box:** ~3 h · **Depends on:** Phase 1 · **Specs:** P-01 … P-06, P-08, W-05, W-06, W-07, W-09, E-01, E-02, E-04, E-06, E-07, U-02 (live), U-03, U-04 (overview, relations, possessions), U-05, X-02 (engine) · **Visual screens:** `03-world-hover`, `04-profile-overview`, `05-profile-relations`, `06-profile-possessions`, `10-world-watching`, `32-people`; review `13-world-look`, `14-world-night`

## Goal
The world comes alive and stays alive:
- 1,000 agents with personas, households, relationships, routines, media diets, money and phones (with age, condition and life events).
- The **always-on `world-engine`** on Cloud Run advances 1 sim day per real hour. It holds a single-writer lease, checkpoints every sim hour, resumes after restarts, and publishes events.
- The browser shows the live city over `/live`: walking and riding agents, hover cards, profiles (overview / relations / possessions), the People page and the watchlist.

## Accounts & cloud setup needed
Walk me through these with `/gcp-setup` before the first step that needs them, unless they're already ✅ in `PROGRESS.md` §5b:
- `/gcp-setup 07` — Firestore database in `asia-south1` (cloud)
- `/gcp-setup 08` — Cloud Storage buckets (worlds: genesis, checkpoints, highlights)
- `/gcp-setup 09` — BigQuery dataset `launch_lens` + public datasets for priors
- `/gcp-setup 10` — Pub/Sub `world-events` (+ `world-texts`) with BigQuery subscriptions
- `/gcp-setup 05` (world-engine section) — Cloud Run `world-engine` always-on
- `/gcp-setup 16` — Cloud Scheduler watchdog

## Prompt
```
You are starting Phase 2 of Launch Lens in a fresh session.
Read CLAUDE.md, PROGRESS.md, docs/DECISIONS.md and docs/phases/phase-02-population-engine.md.
Then read: docs/architecture.md §6 (population), §7 (engine), §16.3–16.5, §18; docs/INTERFACES.md §2 (agent.py, events),
§3 (EventBus, SessionRegistry signature only), §4.2–4.4, §5 (world/agents endpoints), §6.4–6.5, §9;
docs/specs.md P-01…P-06, P-08, W-05…W-07, W-09, E-01, E-02, E-04, E-06, E-07, U-02…U-05.
Look at docs/ui-reference/03–06, 10, 13, 14, 32 and the live mockup.

Goal: genesis of 1,000 agents + always-on engine with lease/checkpoints/live stream + live UI (hover, profile tabs 1–3, People).
Run make test first. Walk me through cloud setup with /gcp-setup when needed. Finish with make test, make lint,
acceptance checks, /visual-check 2, /end-phase. Do not start Phase 3.
```

## Read first
Architecture §6, §7 (both flows), §16.4 (data), §18 (reliability). INTERFACES §4.2 checkpoint, §4.3 highlights (format only), §4.4 live protocol.

## Build checklist
### Genesis (P-01 … P-06, P-08)
- [ ] `population/sampler.py` (seeded; priors from `config/markets/indiranagar.yaml` + BigQuery public data cached in `config/`; `assumed_fields`)
- [ ] Households in residential places; relationship graph (family, partner, friends, colleagues, neighbours, followers) with closeness; average degree ≈ 13
- [ ] Routines (weekday/weekend by occupation and lifestyle), media diet, money profile, **phone possession** (brand by simulated market share, tier, `bought_t`, condition, battery, satisfaction), life-event hazards
- [ ] Special agents: ~10 reviewers (+ followers), ~8 salespeople (shifts at the 3 stores), 1 news desk
- [ ] Persona core via Gemini Flash in batches (`FakeGemini` locally); persona card ≤ 150 tokens; validation against attributes
- [ ] Seed memories (3–6 per agent) written through `MemoryStore` stub (full memory in phase 3)
- [ ] `make genesis` → Firestore `agents/*`, `relationships/*`, genesis checkpoint `genesis/v1/`, `agent_snapshot` events

### Engine (W-05 … W-07, E-01, E-02, E-04, E-06, E-07)
- [ ] `engine/clock.py` (sim minutes; `WORLD_SECONDS_PER_SIM_DAY`, default 3600; pause/slow)
- [ ] `engine/lease.py` (Firestore `world/lease`, 60 s expiry, 20 s renew; read-only follower mode)
- [ ] `engine/loop.py`: 1 tick = 1 sim minute; needs drift; routine/planner; activity events
- [ ] `engine/movement.py`: A* on the road graph; modes walk / two-wheeler / car / auto / bus / metro; **segments with heading**; no walking through buildings
- [ ] `engine/events.py`: EventBus → Pub/Sub batches (cloud) / DuckDB (local); deterministic idempotent `event_id`; `texts` stream API ready
- [ ] `engine/checkpoint.py`: msgpack+zstd every sim hour to GCS/local; resume; `world/state` pointer
- [ ] `engine/live.py`: `/live` WebSocket (`hello`, `seg`, `evt`, `stats`, `clock`) per INTERFACES §4.4; `/healthz` (500 if no tick for 120 s); `/commands` (IAM auth in cloud; pause/resume/set_speed now)
- [ ] `engine/tasks.py` (async model task queue with a concurrency limit; results applied at deterministic sim times)
- [ ] `make engine` (fast clock); deployed `world-engine` (`--min-instances=1 --max-instances=1 --no-cpu-throttling --timeout=3600 --session-affinity`) + Cloud Scheduler watchdog (after my approval)

### API
- [ ] `GET /world/state`, `/world/stats`, `GET /agents` (filters incl. `phone_age_gt`, product stage), `GET /agents/{id}`, `PUT /watchlist`

### Web
- [ ] Live client: WebSocket with reconnect; per-agent segment queues; 60 fps interpolation; sprites like the mockup (layered walker; rider and car sprites)
- [ ] `world-stats` live; `side-tab-watching` (watchlist); ticker with real events (activity, life events)
- [ ] Hover card (U-03) exactly like the mockup; profile drawer (U-04) tabs **Overview, Relations, Possessions** (others show "available in phase 3")
- [ ] People page (U-05): filters (search, age, income, product stage placeholder, **phone older than 5 years**), table, star to watch, row → World + profile
- [ ] Visual-test mode: agents placed from fixtures (`agents[].x/y`), `__ll.featured/focus/hoverAgent/openAgent/setTime/overview` working

## Tests
- Sampler marginals within 3 pp; same seed ⇒ same agents
- Lease: two engines → only one writes
- Determinism: 2 sim days locally twice ⇒ identical event hash
- Checkpoint/resume: kill at random tick, restart ⇒ no duplicate `event_id`s, same final state hash
- Movement: every route stays on the road graph; heading matches segment direction
- Live protocol: schema tests for every message type

## Visual check
`/visual-check 2` → gated `03`, `04`, `05`, `06`, `10`, `32` (+ phase 1 screens) PASS; review `13-world-look`, `14-world-night` by eye.

## Acceptance checks
1. Close all browsers for 10 minutes; reopen → sim time advanced by ~4 sim hours (at 1 day/h).
2. Kill the Cloud Run instance (deploy a new revision) → world resumes from the last checkpoint; `/healthz` green within 2 minutes.
3. Two browsers show the same agents at the same places (≤ 1 s apart).
4. People filter "phone older than 5 years" count equals `SELECT COUNT(*) … phone_age_years > 5` on `agents_latest`.

## Out of scope
Memory beyond seeds, conversations, products and ads, buying, Insights.

## Handoff
Engine URL, revision, lease behaviour, checkpoint sizes/times, tick p95, events/min, live bandwidth, persona generation cost, any agents with invalid routines.
