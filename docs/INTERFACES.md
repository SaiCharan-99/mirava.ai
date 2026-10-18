# INTERFACES.md — shared contracts across build phases (v3)

*These names and shapes are the contract between phases, services and the UI. Precedence: this file > architecture.md > specs.md > techstack.md > mockup. If you must change a contract: update this file, add a `docs/DECISIONS.md` row, and list it in `PROGRESS.md` §7.*

---

## 1. Conventions
- **Python 3.12, pydantic v2.** All schemas live in `shared/schemas/`. TypeScript types are generated with `make types` → `web/src/types/generated.ts`.
- **Sim time** `t`: int, sim minutes since world epoch (day 1 = Monday). `day = t // 1440 + 1`, `minute_of_day = t % 1440`. Helper `shared.time.fmt(t) → "Day 23 · Tue 08:40"`.
- **Space**: float metres from the map's north-west corner, `x` east and `y` south. 8 m tiles. Heading in degrees, 0 = north, clockwise.
- **Money**: int rupees. **Probabilities**: floats 0–1. **Attitude**: float −1…+1.
- **IDs**:
  - `agent_id` int 0–999
  - `product_id` slug, e.g. `nova-x1`
  - `site_id`, e.g. `S-100FT-07`
  - `place_id`, e.g. `P-0412`
  - `store_id`, e.g. `ST-DIGITAL-BAZAAR`
  - `session_id` uuid4 hex
  - `event_id` = `"{kind}:{t}:{agent_id}:{seq}"` (deterministic, idempotent)
  - `mid` (memory id) = `"{agent_id}:{t}:{seq}"`
- **Privacy flag**: any record carrying an agent's private content has `private: true` and an `agent_id` owner. It may only be loaded into prompts *for that owner*.
- **Rendered flag**: `rendered: false` marks work done by rules/templates because of the budget.

---

## 2. Core schemas (`shared/schemas/`)

```python
# world.py
class Place(BaseModel):
    place_id: str; kind: Literal["home","office","techpark","shop","cafe","restaurant","store","school","college","gym","park","metro","bus_stop","news_vendor","mall"]
    name: str; polygon: list[tuple[float,float]]; entrances: list[tuple[float,float]]
    capacity: int; opening_hours: dict[str, tuple[int,int]] | None = None; tags: dict[str,str] = {}
class Site(BaseModel):
    site_id: str; kind: Literal["billboard","unipole","bus_shelter","metro_panel","facade_screen"]
    x: float; y: float; facings: list[float]            # degrees the face points to (towards its audience)
    width_m: float; height_m: float; lit: bool
    cone_half_angle_deg: float; max_distance_m: float; rate_card_inr_week: int; area_label: str
class Store(BaseModel):
    store_id: str; name: str; kind: Literal["multi_brand","phone_shop","brand_store","online"]
    place_id: str | None; staff: list[int]; opening_hours: tuple[int,int]
    stock: dict[str, int]                                # product_id or baseline id → units

# agent.py
class PersonaCore(BaseModel):
    bio_first_person: str; big5: dict[Literal["O","C","E","A","N"], float]
    values: list[str]; lifestyle: str; interests: list[str]; brand_attitudes: dict[str, float]
    speaking_style: str; disclosure: dict[Literal["opinions","money","feelings","plans"], float]   # 0 private … 1 open
class MediaDiet(BaseModel):
    feed_sessions: list[tuple[int,int,str]]              # (start_minute_of_day, minutes, app)
    community: bool; newspaper: bool; news_app: bool; follows: list[int]   # reviewer agent ids
class MoneyProfile(BaseModel):
    monthly_income_inr: int; pay_cycle: Literal["monthly","weekly"]; payday: int
    fixed_costs_inr: int; savings_inr: int; credit_card_limit_inr: int; emi_eligible: bool
class Phone(BaseModel):
    brand: str; tier: Literal["budget","mid","premium","flagship"]; model_label: str
    bought_t: int; condition: Literal["ok","cracked","slow","battery_weak","lost"]
    battery_health: float; satisfaction: float; history: list[dict] = []
class AgentProfile(BaseModel):
    agent_id: int; name: str; age: int; gender: str; household_id: str; role_in_household: str
    education: str; occupation: str; workplace_place_id: str | None; home_place_id: str
    income_band: Literal["<25k","25-50k","50k-1L","1-2L",">2L"]
    commute_mode: Literal["walk","two_wheeler","car","auto","bus","metro"]
    special_role: Literal["none","reviewer","salesperson","news_desk"] = "none"
    persona: PersonaCore; persona_card: str              # ≤150 tokens, fixed
    routine_id: str; media: MediaDiet; money: MoneyProfile
    possessions: dict[str, dict]                         # "phone": Phone.model_dump(), later "clothing": {...}
    assumed_fields: list[str] = []
class AgentState(BaseModel):
    agent_id: int; t: int; x: float; y: float; heading: float; mode: str
    place_id: str | None; activity: str
    needs: dict[Literal["energy","hunger","social","fatigue","stimulation"], float]
    mood: float; plan: list[dict]; session_id: str | None = None; watched: bool = False
class Relationship(BaseModel):
    a: int; b: int; kind: Literal["family","partner","friend","colleague","neighbour","follower"]
    closeness: float; channel: Literal["in_person","online","both"]; last_t: int | None = None

# memory.py
class MemoryEntry(BaseModel):
    mid: str; agent_id: int; t: int
    kind: Literal["seed","ad_thought","conversation","inquiry","post","review","purchase","life_event","reflection","observation"]
    text: str                                            # first person
    importance: int                                      # 1–10
    source: dict                                         # {channel, site_id?, person_id?, session_id?, product_id?}
    entities: list[str]; event_refs: list[str]; embedding: list[float] | None = None   # 768-d
class Belief(BaseModel):
    agent_id: int; subject: str                          # "product:nova-x1" | "brand:arcline" | "category:phone"
    awareness: Literal["unaware","heard","aware","familiar"]
    attitude: float; confidence: float
    reasons_for: list[str]; reasons_against: list[str]; open_questions: list[str]
    first_heard: dict | None                             # {channel, t, ref, person_id?}; never changes once set
    sources_seen: dict[str, int]
    stage: Literal["unaware","aware","curious","researching","inquiring","deciding","purchased","postponed","rejected"]
    updated_t: int

# product.py
class StimulusRecord(BaseModel):
    creative_id: str; salience: float; clarity: float; hook: str; claims_carried: list[str]
    tone: str; readable_at_distance: bool; description: str   # 2 sentences, used in agent prompts
class Creative(BaseModel):
    creative_id: str; product_id: str
    kind: Literal["hoarding","bus_shelter","reel","social_post","newspaper","store_display","reviewer_kit"]
    title: str; text: str | None = None; transcript: str | None = None; scenes: list[str] = []
    image_uri: str | None = None; stimulus: StimulusRecord | None = None; screened: bool = False
class AudienceRule(BaseModel):
    description: str; filter: dict                       # e.g. {"interests_any":["tech","photography"],"age":[22,40]}
    count: int
class PlannedSite(BaseModel):
    site_id: str; facing: float; creative_id: str; est_target_ots_day: int; reason: str
class Plan(BaseModel):
    sites: list[PlannedSite]; reel: dict                 # {creative_id, audience_rule_ids, impressions_day, freq_cap}
    newspaper_days: list[int]; reviewers: list[int]; community_seed: dict; stores: list[str]
    # reel adds audience_size; newspaper_days are day offsets from the launch day; community_seed = {forum, author, title, day_offset} (DECISIONS #77)
    flight_days: int; generated_day: int
class Product(BaseModel):
    product_id: str; name: str; brand: str; category: str; price_inr: int
    launch_offer: str | None; features: list[str]; claims: list[str]
    target_personas: list[str]; audience: list[AudienceRule]
    strategy: dict                                       # {goal, key_message, channels, flight_days, intensity}
    creatives: list[Creative]; plan: Plan | None
    status: Literal["draft","ready","live","ended"]; color: str; launched_at_t: int | None = None
    understanding: dict | None = None                    # profile + claim risk
    graph: dict | None = None                            # knowledge graph (§6.6)

# social.py
class SharePlan(BaseModel):                              # the ONLY per-agent input to a shared dialogue prompt
    session_id: str; agent_id: int; opening: str
    points_to_share: list[str]; questions_to_ask: list[str]; tone: str
    withheld_count: int                                  # how many candidate thoughts were kept private (count only)
class Message(BaseModel):
    session_id: str; seq: int; speaker: int; listener: int; text: str; t: int
class Conversation(BaseModel):
    session_id: str; participants: list[int]; place_id: str | None
    kind: Literal["social","stranger","store","interview"]; t_start: int; t_end: int
    topics: list[str]; product_mentions: list[str]; n_messages: int; rendered: bool; model: str | None
class Inquiry(BaseModel):
    session_id: str; agent_id: int; store_id: str; product_id: str | None
    questions: list[str]; topics: list[str]; answered: list[bool]
    satisfaction: float; outcome: Literal["left","think_about_it","buy","referred_online"]

# community.py
class Thread(BaseModel):
    thread_id: str; forum: Literal["r/IndiranagarLife","r/BangaloreTech","r/BangaloreStyle"]
    author: int; title: str; body: str; t: int; product_id: str | None; upvotes: int
class Post(BaseModel):                                   # comment on a thread
    post_id: str; thread_id: str; author: int; text: str; t: int; upvotes: int
class Review(BaseModel):
    review_id: str; reviewer: int; product_id: str; private_opinion: str
    title: str; summary: str; rating: float; pros: list[str]; cons: list[str]
    t_private: int; t_published: int
```

### 2.1 Events (`shared/schemas/events.py`)
```python
class Event(BaseModel):
    event_id: str; t: int; day: int; t_real: datetime
    kind: str; agent_id: int | None; other_id: int | None = None
    product_id: str | None = None; site_id: str | None = None; session_id: str | None = None
    rendered: bool = True; private: bool = False
    payload: dict
```
| kind | payload (main fields) | private |
|---|---|---|
| `agent_snapshot` | daily: profile summary, needs, money summary, phone (brand, tier, age_years, condition) | no |
| `activity` / `arrive` | activity, place_id | no |
| `payday`, `life_event` | amount / {type: lost\|broken\|slow, category} | no |
| `exposure` | channel (hoarding\|bus_shelter\|metro_panel\|reel\|newspaper\|store_display\|community\|review), creative_id, outcome (pass\|glance\|notice\|scroll\|partial\|full), distance_m, angle_deg, dwell_s, facing, mode, lit | no |
| `thought` | trigger_event_id, text, why_noticed, attitude_delta, reasons_for/against, open_questions, intent_change, wants_to_tell, importance | **yes** |
| `belief_change` | subject, before, after, cause_event_id | no (derived values) |
| `memory_write` | mid, kind, importance | yes |
| `gate` | pair, talk, topics, reason, priority | no |
| `share_plan` | SharePlan + candidate thoughts | **yes** |
| `message` | seq, speaker, listener, text, conv_kind | no |
| `conversation` | Conversation | no |
| `debrief` | reaction, belief_deltas, summary, intents | **yes** |
| `interaction` | topic, minutes (unrendered chat) | no |
| `store_thought` | store visit: customer private thought per turn, decision (speak/hold, what) | **yes** |
| `salesperson_thought` | salesperson private note per turn | **yes** |
| `inquiry` | Inquiry | no |
| `consideration` | subject, from, to, cause_event_id | no |
| `purchase` | option (product_id or baseline id), store_id, price_inr, method (cash\|card\|emi) | no |
| `launch` | product_id, plan summary, launched_at_t | no |
| `review_private` / `review_published` | Review parts | yes / no |
| `thread` / `comment` / `upvote` | Thread / Post / {target} | no |
| `community_thought` | thread_id, text, decided_action | **yes** |
| `poll_answer` | poll_id, option, reason | no |
| `reflection` | text, belief_updates, pruned_count | **yes** |
| `budget` | hour spend, caps by class, speed | no |
| `checkpoint`, `engine_start`, `lease` | technical | no |

`private: true` events are stored in BigQuery like all others (the raw log is complete), but are **only** loaded into model prompts for their owner agent. Insights may read and quote them, always labelled "private thought".

**Texts** (`texts` table): every event with natural-language text is also published to `world-texts` as `{text_id, event_id, t, day, kind, agent_id, product_id, session_id, private, text, embedding}`, where kind is `thought|message|share_plan|debrief|post|comment|review|episode|reflection|store_thought`.

---

## 3. Module interfaces (Python `Protocol`s)

```python
# shared/llm.py
class LLMClient(Protocol):
    async def generate(self, model: str, prompt: str | list, schema: type[BaseModel] | None = None, *,
                       purpose: str, reasoning: Literal["minimal","low","medium","high"] = "low",
                       max_tokens: int = 600, images: list[str] = [], priority_class: str = "P5") -> LLMResult
    async def embed(self, texts: list[str], dim: int = 768) -> list[list[float]]
# LLMResult: {data, text, usage{prompt_tokens, completion_tokens, cost_usd}, model, cached: bool}
# implementations: OpenRouterClient (default), VertexClient, FakeGemini (deterministic by input hash)
# OpenRouter: POST {OPENROUTER_BASE_URL}/chat/completions with response_format json_schema (strict),
#   provider.require_parameters=true, reasoning.effort, usage.include=true (cost); embeddings POST /embeddings.

# mind/decision.py
class DecisionAdapter(Protocol):
    async def decide(self, req: DecisionRequest) -> DecisionResult
    async def decide_batch(self, reqs: list[DecisionRequest]) -> list[DecisionResult]   # ≤32 per model call
# DecisionRequest: {agent_id, kind: talk|share|speak|post|consider|purchase|poll|plan, context: AgentContext | dict,
#                   options: list[str] | None, schema_name}
# DecisionResult: {choice, scores: dict[str,float], reason, engine: "openrouter"|"fake"|"laya", rendered}

# mind/memory.py
class MemoryStore(Protocol):            # constructed per agent: MemoryStore(agent_id, store, llm=None, on_event=None); cannot touch other agents
    agent_id: int
    async def add(self, entry: MemoryEntry) -> None
    async def retrieve(self, query: str, k: int = 6, kinds: list[str] | None = None) -> list[MemoryEntry]
    async def beliefs(self, subjects: list[str] | None = None) -> list[Belief]
    async def update_belief(self, subject: str, delta: dict, cause_event_id: str) -> Belief
    async def prune(self, keep: int = 300) -> int

# mind/context.py
class AgentContext(BaseModel):          # everything a prompt may know about ONE agent
    agent_id: int; persona_card: str; now: str; beliefs: list[Belief]; memories: list[MemoryEntry]; stimulus: str
async def build(agent_id: int, purpose: str, query: str, stimulus: str = "", *, store: DocStore,
                llm: LLMClient | None, now: str = "", now_t: int | None = None, k: int = 6) -> AgentContext   # ≤900 tokens
# DocStore.nearest(collection, field, vector, k, filter_field, filter_value) — find_nearest with equality pre-filter

# social/sessions.py
class SessionRegistry(Protocol):
    def open(self, participants: list[int], kind: str) -> str | None   # None if anyone is busy
    def close(self, session_id: str) -> None
    def busy(self, agent_id: int) -> bool

# social/dialogue.py — the shared prompt accepts ONLY public inputs
async def write_dialogue(a: SharePlan, b: SharePlan, styles: dict[int,str], relationship: str, place: str,
                         max_per_person: int = 10) -> list[Message]

# engine/events.py
class EventBus(Protocol):
    def emit(self, event: Event) -> None
    def emit_text(self, text_row: dict) -> None
    async def flush(self) -> None        # Pub/Sub batch (cloud) or DuckDB (local)

# engine/governor.py
class BudgetGovernor(Protocol):
    def allow(self, priority_class: Literal["P0","P1","P2","P3","P4","P5"], est_cost_usd: float) -> bool
    def record(self, cost_usd: float, priority_class: str) -> None
    def on_sim_hour(self, t: int) -> GovernorState     # recompute caps; may change speed
# GovernorState: {spent_today_usd, cap_usd, caps: dict[class,int], used: dict[class,int], speed_factor}

# media/attention.py
def ots(site: Site, facing: float, x: float, y: float, heading: float) -> OTS | None   # distance, angle, in_cone
def attend(agent: AgentState, profile: AgentProfile, stim: StimulusRecord, ots: OTS, ctx: AttentionCtx,
           rng: Generator) -> Literal["pass","glance","notice"]
# phase 4 (DECISIONS #80): implemented as attend(site, ots, stim, ctx: AttentionCtx, rng); agent/profile features are
#   precomputed into AttentionCtx (mode, dwell_s, lit_night, clutter, on_phone, fatigue, relevance, attitude,
#   familiarity, need, n_seen, n_noticed); ots(..., still=False, minute_of_day=None) adds the lit-at-night rule.
#   Also attend_feed → scroll|partial|full and attend_print(size, page, …). Coefficients: config/attention.yaml.

# media/planner.py
def plan_product(product: Product, world_day: int) -> Plan          # deterministic for (product, world_day)

# insights/tools.py — tool signatures exposed to the ADK Insights agent
def describe_data() -> dict
def run_sql(sql: str) -> {"columns": [...], "rows": [...], "bytes": int, "ref": str}
def semantic_search(text: str, filters: dict, k: int = 20) -> list[{"text_id","agent_id","name","kind","t","text","private","score"}]
def cohort(filter_expr: str) -> {"agent_ids": list[int], "size": int, "ref": str}
def likely_buyers(product_id: str, group_by: list[str]) -> {"rows": [...], "ref": str}
def poll(question: str, options: list[str], cohort_ref: str | None) -> {"poll_id": str, "estimate_usd": float}
def interview(agent_id: int, question: str) -> {"answer": str, "memories_used": list[str]}
def chart(spec: dict) -> dict          # ECharts option
```

---

## 4. File formats

### 4.1 Map assets (`assets/`)
- `assets/osm/indiranagar.osm.json`: Overpass JSON, committed, ODbL.
- `assets/maps/indiranagar.tmj`: Tiled JSON, 8 m tiles (16 px; 2 px per metre), tile layers `ground`, `landuse`, `roads`, `rail`, `buildings`, `decor`; object layers `labels` (text objects, `type` = `road_label` or `place_label:<kind>`) and `lights` (points, `type` = `street|shopfront|window|site`, property `radius_m`; DECISIONS #60). Custom tile properties: `name`, `walkable`, `road_class`.
- `assets/maps/roadgraph.json`: `{nodes:[{id,x,y}], edges:[{a,b,len_m,class,modes:[...]}]}`.
- `assets/maps/places.json`: `[Place]`. `assets/maps/sites.json`: `[Site]`. `assets/maps/stores.json`: `[Store]`.
- Tileset: `assets/tiles/city.png`, 16 px per tile, palette from the mockup.

### 4.2 Checkpoint — `gs://{bucket-worlds}/checkpoints/{t}.msgpack.zst` (local `.data/checkpoints/`)
`{version, t, world_seed, rng_states, agents: [AgentState], segments, sessions, plans, governor, pending_tasks, products_live}`. Pointer in Firestore `world/state.last_checkpoint`; `world/state.last_flushed_t` marks the last published minute (events ≤ it are not re-emitted on replay). In Firestore `agents/{id}.profile.media.feed_sessions` is stored as `[{start, minutes, app}]` (no nested arrays; DECISIONS #67). Genesis: `genesis/v1/` (profiles, relationships, seed memories).

### 4.3 Highlights — `gs://{bucket-worlds}/highlights/day-{n}.json`
`{day, moments: [{t, kind, agent_ids, x, y, title, text, ref_event_id, session_id?}], samples: {t0, step_min: 10, positions: [[x,y]×1000] per sample}}`.

### 4.4 Live protocol — `wss://{world-engine}/live`
```jsonc
{"type":"hello","t":31720,"scale":{"sim_min_per_real_s":0.4},"slowed":false,
 "agents":[{"id":0,"x":812.4,"y":1210.0,"h":90,"mode":"walk","act":"commute"}],
 "segments":[{"a":0,"x0":812,"y0":1210,"x1":840,"y1":1210,"t0":31720.0,"t1":31720.6,"mode":"walk"}],
 "bubbles":[{"session_id":"…","a":12,"b":40,"text":"Hey! Long time!","product":null}],
 "products":[{"id":"pulse-5","name":"Pulse 5","color":"#22c55e","launched_at_t":28800}],
 "sites":[{"site_id":"S-100FT-07","creative_id":"pulse-5-hoarding","product_id":"pulse-5"}],
 "stats":{…}}
{"type":"seg","items":[…segments…]}
{"type":"evt","items":[{"k":"bubble","session_id":"…","a":12,"b":40,"text":"…","product":"nova-x1"},
                        {"k":"notice","a":77,"site_id":"S-CMH-03","product":"nova-x1","thought":"…"},
                        {"k":"launch","product":"nova-x1","sites":[…],"stores":[…],"audience":[…ids…]},
                        {"k":"purchase","a":301,"product":"pulse-5","method":"emi"},
                        {"k":"post","a":512,"thread_id":"…","title":"…"}]}
{"type":"stats","t":31725,"counts":{"agents":1000,"households":412,"relationships":6830,"conversations_today":41,
  "conversations_total":2214,"thoughts_today":288,"products_live":2},"budget":{"used_usd":6.4,"cap_usd":15},
  "awareness":{"nova-x1":0.34,"pulse-5":0.52}}
{"type":"clock","t":31726,"speed":1.0}
```
Agent `mode` values: `walk|two_wheeler|car|auto|bus|metro|idle|offmap` (`offmap` = outside the map, not drawn). `act` values: `sleep|home|commute|work|school|college|eat|cafe|gym|park|shop|store_shift|offmap_work|metro|roam`. Phase-2 `evt` items also include `{"k":"activity","a","act","place"(name or null)}`, `{"k":"life_event","a","type"}`, `{"k":"payday","a","amount"}` (DECISIONS #66). Phase 3 adds `{"k":"talk","a","b","session_id","topic","rendered","place"}` when a pair starts talking (they stop for ~6 sim min) and `bubble` gains `n` (message count) when the transcript is applied (DECISIONS #74).
Notice and thought texts in `evt` are truncated to 140 characters. Full private texts are only served by the API to the profile drawer and Insights.

---

## 5. API shapes (selected; base `/api`)
| Method & path | Request → Response |
|---|---|
| `GET /world/state` | → `{t, day, label, scale, slowed, status, budget}` |
| `GET /world/stats` | → stats object (as in `/live`) |
| `GET /world/highlights?day=` | → highlights JSON (§4.3) |
| `GET /agents?q=&age=&job=&income=&phone_age_gt=&product=&stage=&watched=&sort=&page=` | → `{rows:[{agent_id,name,age,occupation,income_band,phone:{brand,age_years,condition},stages:{product_id:stage},watched,activity}], total, phone_old_count, watched_count}`; `age=min-max`, `page_size` ≤ 1000, `sort=-phone_age` |
| `GET /agents/{id}` | → `{profile, state, relationships, beliefs, watched}`; extras (DECISIONS #66): `profile.household_size`, `profile.workplace_name`, `profile.possessions.phone.age_years`, `state.place_name`, `relationships[].other {agent_id,name,age,occupation}` |
| `GET /agents/{id}/thoughts?limit=` | → `[{t, label, trigger:{channel,site_id?,creative_id?,session_id?}, text, attitude_delta, product_id}]` |
| `GET /agents/{id}/conversations` | → `[{session_id, with, kind, t, topics, n_messages, rendered}]` |
| `GET /conversations/{session_id}?as_agent={id}` | → `{conversation, messages, share_plan (only as_agent's), debrief (only as_agent's), store_thoughts (only as_agent's)}` |
| `GET /agents/{id}/memories?q=` | → `[MemoryEntry]` (no embeddings) |
| `PUT /watchlist` | `{agent_ids}` |
| `GET/POST /products`, `GET/PATCH /products/{id}` | Product |
| `POST /products/{id}/uploads` | `{kind, filename}` → `{upload_url, creative_id}` |
| `POST /products/{id}/creatives` | `{kind, title, text?, transcript?, scenes?, image_uri?}` → `{creative, flagged}` (screened + neutralised; 422 for political content) — DECISIONS #77 |
| `POST /products/{id}/audience` | `{personas?}` → `{audience:[AudienceRule], total}` (live counts) · `DELETE /products/{id}` (drafts only) — DECISIONS #77 |
| `PUT /uploads/{key}` | local-only twin of the signed URL (dev) |
| `POST /products/{id}/understand` | → `{understanding, creatives:[StimulusRecord], graph}` |
| `POST /products/{id}/plan` | → Plan (reasons included) |
| `POST /products/{id}/ready` · `POST /products/{id}/launch` | → Product (status) |
| `POST /insights/ask` | `{session_id?, question}` → SSE stream of `{step}` then `AskAnswer {answer_md, numbers, charts, quotes, sql, caveats}` |
| `GET /insights/{overview\|sources\|hoardings\|segments\|conversations}?product=&from_day=&to_day=` | dashboard data |
| `POST /insights/poll` | `{question, options, cohort?}` → `{poll_id, estimate_usd}`; `GET /insights/poll/{id}` → result |
| `POST /insights/interview` | `{agent_id, question, session_id?}` → `{answer, memories_used}` |
| engine `POST /commands` (IAM) | `{type: launch\|poll\|pause\|resume\|set_speed\|restore, …}` |
| engine `GET /health` (alias `/healthz`, `/api/healthz`) | 200 if a tick happened < 120 s ago, else 500. Cloud Run answers `/healthz` itself on run.app URLs, so the watchdog uses **`/health`** (DECISIONS #65) |
| engine `GET /state` · `GET /stats` · `GET /agents/{id}/state` | world state (+ `engine` diagnostics) · stats frame · live AgentState + current phone |

---

## 6. Frontend contracts

### 6.1 Routes
`/` (redirects to `/globe` on the first visit of a browser session, else `/world`), `/globe` (intro; always available), `/world`, `/launch`, `/launch/:productId/:step` (`details|content|understand|plan|ready`), `/insights/:tab` (`ask|overview|sources|hoardings|segments|conversations|polls|interview`), `/people`, `/guide`. The mockup uses the same paths as hash routes (`#world`, `#launch/nova-x1/plan`, `#insights/hoardings`…).

### 6.2 Design tokens
Copy the CSS variables at the top of `docs/ui-mockup.html` (dark default + `[data-theme="light"]`) into `web/src/styles/tokens.css`. Fonts: Inter (UI) and JetBrains Mono (numbers/IDs), self-hosted. Radius 12 px cards, 8 px controls. Sidebar 232 px, header 56 px, World side panel 340 px, profile drawer 420 px. Product colours come from the product (`color`), assigned in order from `--p1 … --p6`. **Do not invent new colours or spacing.**

### 6.3 Required `data-testid` regions (geometry-checked against the mockup)
| Screen | testids |
|---|---|
| all | `app-header`, `app-sidebar`, `app-main`, `theme-toggle`, `header-clock`, `budget-meter`, `world-status`, `nav-world`, `nav-launch`, `nav-insights`, `nav-people`, `nav-guide` |
| standard pages | `page-header`, `page-title`, `page-actions` |
| globe | `globe-intro`, `globe-canvas`, `globe-card`, `globe-enter`, `globe-skip` |
| world | `world-stage`, `world-canvas`, `world-stats`, `lens-switch` (buttons carry `data-lens="activity\|aware\|sentiment\|hoardings"`), `new-product`, `launch-dock` (items `launch-dock-item` with `data-product`), `world-side`, `side-tab-now`, `side-tab-watching`, `side-tab-products`, `event-ticker`, `day-timeline`, `minimap`, `agent-hovercard`, `profile-drawer` (**always mounted**, off-canvas when closed), `launch-fx` (overlay canvas) |
| profile | `profile-tabs`, `profile-tab-{overview,relations,possessions,thoughts,conversations,memory}`, `profile-body`, `watch-toggle` |
| launch list | `products-grid`, `product-card` (`data-product`), `new-product-card` |
| launch editor | `studio-steps`, `studio-step-{details,content,understand,plan,ready}`, `studio-body`; details: `details-form`, `personas-card`, `strategy-card`; content: `content-grid`, `upload-zone`; understand: `claims-card`, `creatives-card`, `knowledge-graph`, `graph-toolbar`, `graph-search`, `graph-mode`, `graph-canvas`, `graph-legend`, `graph-details`; plan: `plan-map-card`, `plan-canvas`, `plan-sites`, `plan-channels`; ready: `ready-summary`, `mark-ready` |
| insights | `insights-tabs`, `insights-tab-{ask,overview,sources,hoardings,segments,conversations,polls,interview}`, `insights-body`; ask: `ask-thread`, `ask-input`, `ask-suggestions`; hoardings: `sites-table`, `sites-map` |
| people | `people-filters`, `people-table` |
| guide | `guide-body` |
Exact boxes per screen: `docs/ui-reference/<screen>.boxes.json`.

### 6.4 Visual-test mode (`?visualTest=1`)
When present the app must:
1. Load **fixtures** from `web/src/visual-fixtures/` that reproduce the mockup's demo content exactly: world stats, ticker items, products (Nova X1 ready, Pulse 5 live, Orbit S draft), agents shown in drawers/tables, thoughts, the featured conversation transcript, beliefs, insights answers and charts, the hoardings table, segments, people rows. Extract them from `docs/ui-mockup.html`.
2. Freeze animations and the clock at **Day 23 · Tue 08:40** (night screen: 21:30). Use the same seeded agent layout as the mockup's freeze mode.
3. Show the globe intro only on the `/globe` route (static frame, focused on Bengaluru); `/` goes straight to `/world`.
   Fixtures: generate `web/src/visual-fixtures/mockup-fixtures.json` with `cd tools/visual && node extract-fixtures.mjs` (never hand-edit).
4. Expose:
```ts
window.__ll = {
  featured(): number,                                // id of the featured agent (Meera in fixtures)
  focus(id: number): void,                           // centre camera on agent, zoom 3
  hoverAgent(id: number): void,                      // show the hover card
  openAgent(id: number, tab: "overview"|"relations"|"possessions"|"thoughts"|"conversations"|"memory"): void,
  lens(name: "activity"|"aware"|"sentiment"|"hoardings"): void,
  setTime(hour: number): void,                       // jump within the current day and re-freeze
  overview(): void,                                  // fit the whole map
  highlights(day: number): void,                     // open the highlights view for a past sim day (1-based)
  launchFx(productId: string, progress: number): void, // render the launch animation frozen at progress 0–1
  graphSelect(nodeId: string): void,                 // knowledge graph: select + focus a node
  graphHover(nodeId: string): void
}
```
5. Not render anything with `data-testid="mockup-only"` (it only exists in the mockup).
6. Knowledge graph: run the force layout to rest synchronously (≈420 ticks, fixed seed) and skip animation.

### 6.5 World rendering contract
- Phaser scene `WorldScene` renders `indiranagar.tmj`. Agent sprites are 16 px layered (skin, hair, shirt), with an activity icon.
- A speech bubble appears above talkers (white; teal border when the product is mentioned) and a dashed link joins the two talkers.
- 👀 marks a notice, with a small thought bubble when a thought exists.
- Lenses: **activity** (default colours by activity), **aware** (agents coloured by the selected product's stage, sites of that product highlighted), **sentiment** (red→green by attitude to the selected product), **hoardings** (cones drawn per site/facing, coloured by notice rate; heat overlay).
- Night: darkness overlay; lit sites, shop fronts and street lights glow.
- The camera supports drag, wheel zoom (0.6×–6×), double-click to focus, follow agent, and minimap click-to-move.

### 6.6 Knowledge graph view (Obsidian-style) — `GraphView`
- Data: `GET /products/{id}` → `graph: {nodes:[{id,label,type,desc,source,risk?,degree,mentions?}], edges:[{source,target,rel}]}`. Types: `product|feature|claim|concern|competitor|segment|creative|entity`. Claims are coloured by risk; other colours follow the mockup's `KG_TYPES`.
- Rendering: canvas + d3-force (`react-force-graph-2d`). Node radius by degree; the product node is largest.
- Interactions (all required):
  - live physics
  - drag a node (neighbours follow, the simulation reheats)
  - wheel zoom around the cursor (0.3×–4×)
  - drag the background to pan
  - hover highlights the node and its neighbours and shows relation labels; others fade to ~12%
  - labels appear when zoomed in (> 1.7×), on hover/selection, or for high-degree nodes
  - click selects (details panel); double-click focuses
  - search highlights matches and focuses the first
  - legend toggles types
  - Global/Local (2 hops) mode, Re-layout, Fit, tooltip
- Details panel: type (or "Claim · red risk"), label, description, source, mention count (after launch), linked nodes (clickable) with relation names, Clear selection.

---

## 7. Config files (`config/`)
| File | Contents |
|---|---|
| `markets/indiranagar.yaml` | Demographic targets, income bands, occupations, household mix (assumed values flagged) |
| `phones_market.yaml` | Brand shares by price band, tier price ranges, age distribution, hazards (lost/broken/slow per day), baseline market models |
| `routines.yaml` | Routine templates by occupation and lifestyle |
| `media.yaml` | Media diet distributions, feed ranker weights, reel frequency cap, newspaper habits, forums |
| `attention.yaml` | Glance/notice coefficients, cone defaults by size class, wear-out, calibration targets |
| `consideration.yaml` | Stage thresholds, need formula weights, purchase rules (θ_need, δ), stage weights for likely-buyer score |
| `conversation.yaml` | Gate probabilities, stranger places, cool-downs, message limits (10/person, strangers 4), topic rules |
| `stores.yaml` | Fictional stores, locations, hours, staff count, default stock rules |
| `baseline_ads.yaml` | Ambient fictional brands and their creatives |
| `budget.yaml` | `daily_cap_usd: 15`, `interactive_cap_usd: 5`, class caps per sim day, slow-down steps |
| `world.yaml` | `world_seed`, `seconds_per_sim_day: 3600`, checkpoint interval, highlight count |
| `places_overrides.yaml` | Store lots, tech park, newspaper vendor, names |
| `demo/products/*.yaml` | Placeholder products (Nova X1, Pulse 5, Orbit S) for fixtures/tests |

## 8. Model providers and ids
`shared/models.py` is the only place model ids appear, and they are overridable by env:

| Constant | Env override | Default (OpenRouter) |
|---|---|---|
| `MODEL_PRO` | `MODEL_PRO_ID` | `google/gemini-3.1-pro-preview` |
| `MODEL_FLASH` | `MODEL_FLASH_ID` | `google/gemini-3.6-flash` |
| `MODEL_LITE` | `MODEL_LITE_ID` | `google/gemini-3.5-flash-lite` |
| `MODEL_EMBED` | `MODEL_EMBED_ID` | `google/gemini-embedding-001` |

Startup check: with `LLM_BACKEND=openrouter`, `GET /api/v1/models` must list every id, otherwise startup fails fast. Any `gemini-2.5` string anywhere fails the guard test.

## 9. BigQuery schemas (`infra/bigquery/`)
- **`events`**: `event_id STRING, t INT64, day INT64, t_real TIMESTAMP, kind STRING, agent_id INT64, other_id INT64, product_id STRING, site_id STRING, session_id STRING, rendered BOOL, private BOOL, payload JSON`. Partitioning: `RANGE_BUCKET(day, GENERATE_ARRAY(1, 4001, 1))`. Clustering: `kind, product_id, agent_id`. Written by Pub/Sub subscription `world-events-to-bq` (use table schema).
- **`texts`**: `text_id STRING, event_id STRING, t INT64, day INT64, kind STRING, agent_id INT64, product_id STRING, session_id STRING, private BOOL, text STRING, embedding ARRAY<FLOAT64>`. Same partitioning, clustered by `kind, product_id`. Written by subscription `world-texts-to-bq`. Vector index (`IVF`, cosine) once the table has more than 5,000 rows; `VECTOR_SEARCH` works without the index before then.
- **Views** (`infra/bigquery/views/*.sql`): `agents_latest`, `beliefs_daily`, `beliefs_latest`, `v_exposures`, `v_site_daily`, `v_thoughts`, `v_messages`, `v_conversations`, `v_inquiries`, `v_purchases`, `v_posts`, `v_reviews`, `v_first_heard`, `v_paths`, `v_funnel_daily`. Each view's columns are documented in `insights/dictionary.yaml`.
