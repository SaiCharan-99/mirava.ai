# Phase 3 — Memory, think/speak conversations, budget governor, highlights

**Time box:** ~3 h · **Depends on:** Phase 2 · **Specs:** M-01 … M-07, E-03, E-05, T-01, T-02, T-04, T-05, T-06, T-07, C-07, W-08, U-04 (thoughts, conversations, memory) · **Visual screens:** `07-profile-thoughts`, `08-profile-conversations`, `09-profile-memory`, `12-world-highlights`

## Goal
Agents get minds:
- **Layered private memory** with retrieval, beliefs, nightly reflection and pruning.
- **Encounters** go through the gate into **3-step conversations**:
  1. private prep → share plan
  2. one dialogue of up to 10 messages per person, greeting first, natural end
  3. private debrief
- Exact transcripts are logged; each participant keeps its own episodic summary.
- Strangers have short exchanges; over-budget chats are logged as unrendered interactions.
- The **budget governor** keeps background spend within $15/day.
- Day highlights are written and replayable.
- Profiles show **Thoughts, Conversations (with this agent's private prep/debrief) and Memory**.

## Accounts & cloud setup needed
Walk me through these with `/gcp-setup` before the first step that needs them, unless they're already ✅ in `PROGRESS.md` §5b:
- `/gcp-setup 07` (vector index section) — Firestore vector index on `memories` (768-d, pre-filter `agent_id`)
- `/gcp-setup 10` — confirm the `world-texts` → `texts` subscription (embedding column)
- OpenRouter key (phase 1) is now used for real by the engine: set the key's **credit limit** before deploying

## Prompt
```
You are starting Phase 3 of Launch Lens in a fresh session.
Read CLAUDE.md, PROGRESS.md, docs/DECISIONS.md and docs/phases/phase-03-memory-conversations.md.
Then read: docs/architecture.md §8 (memory), §11 (conversations, both flows), §17 (governor + cost model), §18 (isolation);
docs/INTERFACES.md §2 (memory.py, social.py, events), §3 (MemoryStore, AgentContext, DecisionAdapter, SessionRegistry,
write_dialogue, BudgetGovernor), §4.3, §5 (agent thoughts/conversations/memories endpoints);
docs/specs.md M-01…M-07, E-03, E-05, T-01, T-02, T-04…T-07, C-07, W-08.
Look at docs/ui-reference/07, 08, 09, 12 and the live mockup's profile drawer.

Goal: private layered memory + gated 3-step conversations with exact transcripts + governor + highlights + profile tabs 4–6.
Privacy is a hard requirement: build the marker-fact tests first. Run make test first. Finish with make test, make lint,
acceptance checks, /visual-check 3, /end-phase. Do not start Phase 4.
```

## Read first
Architecture §8.2–8.8 (layers, retrieval, context, reflection, isolation), §11.2–11.3, §17. INTERFACES §3 (all mind/social protocols).

## Build checklist
### Memory (M-01 … M-07)
- [ ] `mind/memory.py`: `MemoryStore(agent_id)` on Firestore (`agents/{id}/memories`, `beliefs/{subject}`); `add`, `retrieve` (find_nearest with an `agent_id` pre-filter → re-rank 0.35·recency + 0.25·importance + 0.40·relevance → top 6), `beliefs`, `update_belief` (first_heard immutable; logs `belief_change`), `prune(300)`; in-RAM embedding LRU
- [ ] `mind/context.py`: `build(agent_id, purpose, query, stimulus)` → `AgentContext` (persona card + now + ≤ 3 beliefs + top-k memories + stimulus, ≤ 900 tokens); **lint test: every agent prompt goes through it**
- [ ] `mind/reflect.py`: nightly at 03:00 sim for agents with daily importance ≥ 12 (governor cap) → reflections + belief updates + prune; `reflection` events (private)
- [ ] Working memory in the engine (today's buffer), rolled over at night
- [ ] Every text event also published to `world-texts` with an embedding (`texts` table)

### Decisions
- [ ] `mind/decision.py`: `DecisionAdapter` with `OpenRouterDecisionBackend` (Flash-Lite, typed, **batched 32/call**), `FakeLaya`; kinds `talk`, `share`, `speak`, `post`, `plan`; dedup cache

### Conversations (T-01 … T-07, E-03, C-07)
- [ ] `engine/encounters.py`: 16 m spatial hash, co-located ≥ 2 sim min, available, cool-down per pair
- [ ] `social/gate.py`: known people (closeness × free time) vs strangers (store/queue/bus stop/café only) → decision model `{talk, topic_candidates}` (topics = shared interests ∩ salient memories; **product talk only when one side has it salient and the other is interested or shares the interest**) → priority → governor → rendered / unrendered (`interaction` event + template memory)
- [ ] `social/sessions.py`: SessionRegistry (locks, timeouts); talkers stop and face each other; bubble events on `/live`
- [ ] `social/prep.py`: per agent, own context → candidate thoughts (sensitive/personal/opinion/question) → decision model picks what to share by closeness × disclosure style × sensitivity → `SharePlan` (+ private `share_plan` event)
- [ ] `social/dialogue.py`: `write_dialogue(planA, planB, styles, relationship, place)` — **signature accepts only public inputs**; ≤ 10 messages per person; greeting first; natural end; Flash for product talk, Flash-Lite otherwise; `message` events + `conversation` event + texts
- [ ] `social/debrief.py`: per agent, own context + transcript → private reaction, belief deltas, episodic summary, intents (`debrief` event)
- [ ] Stranger sessions ≤ 4 messages per person, low disclosure

### Governor (E-05)
- [ ] `engine/governor.py`: priority classes P0–P5; caps per sim hour from `config/budget.yaml`; actual cost from usage accounting; slow-down steps (1 → 1.5 → 2 → 3 h per sim day) with `slowed` flag on `/live` and in the header; `budget` events; interactive cap separate

### Highlights (W-08)
- [ ] `engine/highlights.py`: end of sim day → top ~40 moments + 10-min samples → `highlights/day-{n}.json`; API `GET /world/highlights?day=`

### Web
- [ ] Profile tabs **Thoughts** (private tag, trigger, product, attitude delta), **Conversations** (list → full transcript; this agent's private prep **before** and debrief **after**, visually separate in purple; the other participant's private parts never shown), **Memory** (belief cards with stage bar + episodic list)
- [ ] Ticker: conversations (topic, first line), thoughts (with PRIVATE tag), life events; `side-tab-now`
- [ ] Day timeline: past days clickable → highlights mode (banner + moment list + camera jumps); `__ll.highlights(day)`
- [ ] Header budget meter live; "Slowed to save budget" state

## Tests
- **Marker-fact isolation:** plant "A's cousin is named Zubin" in A's private memory → run 200 conversations involving A → "Zubin" appears in B's outputs only if A's transcript contains it. 0 leaks
- `write_dialogue` rejects anything that is not a SharePlan (type test)
- Retrieval returns the planted relevant memory in the top 6; never another agent's
- Transcripts ≤ 20 messages, greeting first; stranger sessions ≤ 8 total
- Governor simulation: $15/day target over 3 simulated real days within ±10%; priorities respected; slow-down only when P0–P2 exceed
- No agent is ever in two sessions (property test)

## Visual check
`/visual-check 3` → gated `07`, `08`, `09`, `12` (+ earlier) PASS.

## Acceptance checks
1. Watch Meera-like agents for 2 sim days: at least one full rendered conversation with greeting, ≤ 20 messages, private prep/debrief visible in her profile only.
2. BigQuery: `v_messages` reconstructs that conversation exactly; `texts` has embeddings.
3. Governor dashboard (logs): spend per sim hour stays within plan; rendered/unrendered ratio logged.
4. Highlights for the previous day replay with camera jumps.

## Out of scope
Products, ads, stores, Insights.

## Handoff
Rendered chats per sim day, average cost per chat, retrieval latency, reflection count, isolation eval result, governor caps in use.
