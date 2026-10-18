# Phase 5 addendum — Survey Room: surveys and focus groups (additive)

Added in phase 5 (2026-10-18). This file copies Part B of the phase-5 session prompt verbatim. It is ADDITIVE to the frozen design docs (`architecture.md`, `specs.md`, `INTERFACES.md`, `techstack.md`, mockup, references): nothing here renames or reshapes an existing contract. Decisions: `docs/DECISIONS.md` rows 86+. Progress: `PROGRESS.md` §7 "Contract changes".

## Contract additions (final names, phase 5)
| Kind | Name(s) | Where |
|---|---|---|
| Schemas | Question (+Scale), Survey, InterestFilter, Participant (rsvp adds `waitlist`), Table, PreStance, SurveyMessage, HeardItem, SurveyAnswer, QuestionResult, SurveyResult; `MAX_PARTICIPANTS = 100` | `shared/schemas/survey.py` |
| Config | `config/survey.yaml` — venue `P-0186` shown as "Research Lounge", timings, floor/absorption/conformity weights, token sizes for the estimate | config |
| Session kind | `focus_group` (one session per table, held from selection to the end) | SessionRegistry |
| Event kinds | survey_created, survey_invite, survey_rsvp*, survey_prestance*, survey_thought*, survey_decision*, survey_heard*, survey_answer, survey_summary, survey_completed (* in `PRIVATE_KINDS`) | `shared/schemas/events.py` |
| Reused kinds | `arrive` (place_id = venue), `message` (conv_kind="focus_group", speaker = agent id or "moderator", message_id, question_id, table_id) | EventBus |
| Text kinds | survey_thought (private), survey_answer, survey_summary (+ `message`) | `texts` |
| Views | v_surveys, v_survey_participants, v_survey_messages, v_survey_answers, v_survey_shift, v_survey_waves | `infra/bigquery/views/` (+ DuckDB), `insights/dictionary.yaml` |
| API | POST /surveys · POST /surveys/lint · POST /surveys/{id}/launch (402 over budget, 422 none eligible) · GET /surveys · GET /surveys/{id}?include_private=1 · GET /surveys/{id}/transcript?table= · GET /surveys/{id}/agents/{agent_id} · POST /surveys/{id}/rerun · POST /surveys/{id}/cancel · POST /surveys/{id}/explain ("why it changed") | `api/surveys.py` |
| API extras | `GET /conversations/{sid}?as_agent=` adds `store_thoughts`, `survey_items`, `survey_id`, `inquiry` (own private items only) | `api/main.py` |
| Engine | commands `survey_launch`, `survey_cancel`; `GET /state` adds `surveys` and `interactive {used_usd, cap_usd}`; local-only `POST /analytics/query` | `engine/loop.py`, `engine/app.py` |
| Live | evt `{"k":"survey", survey_id, status, venue, arrived, expected, name, x, y}`, evt `{"k":"survey_trip","a"}`; client → server `{"type":"sub"|"unsub","survey_id"}`; frames `survey`, `survey_msg`, `survey_ballot` (+`note` in survey mode), `survey_result` | `engine/live.py`, `engine/survey/runtime.py` |
| Routes | /insights/polls/survey/new, /insights/polls/survey/:surveyId | `web/src/App.tsx` |
| testids | survey-builder, survey-questions, survey-audience, survey-estimate, survey-launch, survey-room, survey-canvas, survey-tables, survey-transcript, survey-results, survey-playback, survey-agent-card (+ survey-entry, survey-room-button, survey-pin) | web |
| `__ll` hook | `surveyRoom(surveyId, phase, progress)` | `web/src/hooks/ll.ts` |
| Fixture | `web/src/visual-fixtures/survey-fixture.json` ← `uv run python -m tools.survey_fixture` | tools |
| Insights tool | `survey_results(survey_ref, question_id?)` | `insights/tools.py`, `insights/surveys.py` |
| Web deps | three 0.169.0, @react-three/fiber 8.17.10, @react-three/drei 9.114.0, @types/three 0.169.0 (exact) | `web/package.json` |

---|---|---|---|
| Schemas | Question, Survey, Participant, Table, PreStance, SurveyMessage, HeardItem, SurveyAnswer, SurveyResult | `shared/schemas/survey.py` | planned |
| Config | `config/survey.yaml` (venue, timings, weights) | config | planned |
| Session kind | `focus_group` | SessionRegistry | planned |
| Event kinds | survey_created, survey_invite, survey_rsvp*, survey_prestance*, survey_thought*, survey_decision*, survey_heard*, survey_answer, survey_summary, survey_completed (* private) | EventBus | planned |
| Reused kinds | `arrive` (venue), `message` (conv_kind=focus_group) | EventBus | planned |
| Text kinds | survey_thought, survey_answer, survey_summary | `texts` | planned |
| Views | v_surveys, v_survey_participants, v_survey_messages, v_survey_answers, v_survey_shift, v_survey_waves | `infra/bigquery/views/` + DuckDB | planned |
| API | POST /surveys, POST /surveys/{id}/launch, GET /surveys, GET /surveys/{id}, GET /surveys/{id}/transcript, GET /surveys/{id}/agents/{agent_id}, POST /surveys/{id}/rerun, POST /surveys/{id}/cancel, POST /surveys/lint | api | planned |
| Engine commands | survey_launch, survey_cancel | POST /commands | planned |
| Live | evt `k:"survey"`; types survey, survey_msg, survey_ballot, survey_result; client `{"type":"sub","survey_id"}` | /live | planned |
| Routes | /insights/polls/survey/new, /insights/polls/survey/:surveyId | web | planned |
| testids | survey-builder, survey-questions, survey-audience, survey-estimate, survey-launch, survey-room, survey-canvas, survey-tables, survey-transcript, survey-results, survey-playback, survey-agent-card | web | planned |
| `__ll` hook | surveyRoom(surveyId, phase, progress) | visual-test mode | planned |
| Insights tool | survey_results(survey_ref, question_id?) | insights/tools.py | planned |
| Web deps | three, @react-three/fiber v8, @react-three/drei v9 (exact pins) | web/package.json | planned |

---

## PART B — SURVEY ROOM: SURVEYS AND FOCUS GROUPS (new, additive)

B0 What it is
A researcher chooses a group of agents and runs a real-world-style SURVEY or FOCUS GROUP.

The event happens IN the world:
- invited agents decide whether to come
- the ones who accept walk to the Survey Room venue on the map
- they sit at round tables in a 3D room

The session:
- A moderator circulates the questions.
- In a focus group, participants discuss, each in their own nature, with speech bubbles above their heads.
- Then every participant answers each question INDIVIDUALLY and PRIVATELY on their phone/tablet,
  using the Gemini 3.5 Flash-Lite decision model (MODEL_LITE via DecisionAdapter).
- Each answer reflects the agent's experiences, memories and beliefs, plus what they personally absorbed from the discussion.

Over time:
- Every message and answer goes to Pub/Sub → BigQuery.
- Agents remember the session.
- The same panel can be re-run later (waves). Answers change as the agents' lives change, and each change is explained.

B1 Modes and question types
- mode = "focus_group": discussion per question, then private ballot.
  - Per question, `discuss: bool` (default true).
- mode = "survey": no discussion.
  - Each agent "writes" answers + reasoning on their tablet.
  - Their reason appears as a note card above their head.
- Question types (2–8 options where relevant):
  - single
  - multi (max_select)
  - scale (1–5 or 1–10 with anchor labels)
  - open (free text ≤ 60 words)
- Limits: ≤ 10 questions per survey.
- Participants: max 100 (hard cap, enforced in API AND engine); min 1, any number.
  - With 1 participant, discussion is skipped and it runs like a written survey.
  - With 2+, discussion is allowed.
- Tables: participants are split into round tables of size table_size (6–10, default 8).
  - Each table has its own moderator.
  - Seating is stratified, so each table mixes age/income/stance (quota-style, like a real recruiter).
- One active survey at a time in the world. Others queue.

B2 Schemas (shared/schemas/survey.py) — additive pydantic models
- Question:
  - question_id, text
  - type: single|multi|scale|open
  - options: list[str] | None
  - max_select, scale: {min, max, low_label, high_label} | None
  - discuss: bool
- Survey:
  - survey_id, title, mode, product_id | None, topic
  - questions: list[Question]
  - cohort_filter (same filter language as People / the `cohort` tool)
  - interest_filter: {product_id?, min_stage?} | None
  - max_participants ≤ 100, table_size, incentive_inr
  - start_at_t | None (None = next available slot)
  - wave: int, panel_id | None, parent_survey_id | None
  - status: draft|recruiting|gathering|in_session|balloting|completed|cancelled
  - estimate_usd, actual_usd
- Participant:
  - agent_id, table_id, seat
  - rsvp: accepted|declined|no_show|attended
  - rsvp_reason (private)
  - arrived_t
- Table: table_id, survey_id, session_id (SessionRegistry kind "focus_group"), seats: list[agent_id], moderator_id
- PreStance (private): agent_id, question_id, answer, confidence 0–1, gut_reason
- SurveyMessage: message_id, survey_id, table_id, question_id, seq, speaker (agent_id | "moderator"), text, addressed_to | None, reply_to | None
- HeardItem (private, per listener): message_id, salience 0–1, why: [relevance|credibility|emotion|novelty|agreement|disagreement|primacy|recency]
- SurveyAnswer:
  - agent_id, question_id, answer (option(s) | scale value | text), confidence 0–1
  - reason (first person, ≤ 40 words)
  - changed_from_prestance: bool
  - influence_type: persuaded|conformed|reinforced|unchanged|reacted_against
  - influenced_by: list[message_id]
  - public_private_gap: bool (what they said in the room ≠ what they answered privately)
  - effort: careful|satisficed
- SurveyResult: per question:
  - distribution
  - prestance vs final (shift matrix)
  - by-segment table
  - top quotes (public and private labelled)
  - moderator summary
- Config: config/survey.yaml (new file):
  - venue: place_id of ONE existing place from assets/maps/places.json (prefer kind cafe|office|mall near 100 Ft Road)
  - display name "Research Lounge" (fictional)
  - default table_size, sim-minute timings
  - floor-model weights, absorption weights, conformity weights
  - per-person message cap: reuse conversation.yaml's 10/person per session
  - Do NOT regenerate the map.

B3 Recruitment and arrival (engine/survey/recruit.py) — the action begins in the world
1. Eligible = cohort_filter ∩ interest_filter (e.g. phones > 5 years and curious+ about Pulse 5).
   - Show the eligible count and the expected attendance before launch.
2. Invite: each eligible agent receives an invitation on their phone (event `survey_invite`).
3. RSVP decision: DecisionAdapter.decide_batch (Flash-Lite, ≤ 32 per call), typed accept/decline + private reason. Inputs:
   - interest in the topic/product (beliefs, consideration stage)
   - free time in their routine at start_at
   - distance to the venue
   - incentive
   - Big Five E and O
   - survey fatigue (attended one in the last 3 sim days)
   - job dependence
4. Selection:
   - accept up to max_participants in RSVP order, with stratified quotas so the mix matches the eligible pool
   - surplus acceptances go on a waitlist (realistic over-recruiting)
   - a small seeded no-show probability
5. Scheduling:
   - start_at defaults to the next slot ≥ 60 sim min ahead (travel time)
   - the planner inserts activity "survey" at the venue for accepted agents
   - they travel on the road graph like any trip (walk/bike/metro)
6. World: the venue shows a pin "Research Lounge · n/N arrived" while recruiting/gathering/in session.
   - Agents en route carry a small 📋 marker.
7. Participants are `busy` in SessionRegistry for the whole session: no other chats. Their routine resumes afterwards.
8. Session start: when ≥ 90% have arrived or 20 sim min after start_at, whichever is first. Late arrivals join the next question.
9. The world clock does NOT slow down for the survey; the UI handles readability with playback (B9).

B4 Session runner (engine/survey/session.py)
Per table, per question:
1. Moderator reads the question and options.
   - Moderator = a role model on Flash-Lite with a neutral moderator guide: no leading, invite quiet people, probe disagreements.
   - The moderator NEVER sees private data.
2. PRE-STANCE: each seated participant privately forms an initial answer
   (DecisionAdapter batch, Flash-Lite) → `survey_prestance` (private). This is the "before" measure.
3. DISCUSSION (if mode=focus_group and discuss=true and table size ≥ 2):
   a. Floor model (rules, NO model call). Each round, every participant gets a speak propensity:
      f(E, confidence, stake [personal experience with the product/topic], disagreement with the last speaker,
        being addressed by name, moderator invitation, messages already spoken, fatigue) + seeded noise.
      Pick the next speaker. Caps: ≤ 10 messages per person per session; 8–16 turns per question per table.
      Stop on convergence, no new information, or the moderator wrapping up.
   b. Speaker turn = think → decide → speak (the same pattern as store inquiries T-03):
      - private thought (Flash-Lite) from AgentContext.build(agent, purpose="survey_discuss", query=question)
        + the speaker's OWN heard buffer (not the full transcript) → `survey_thought` (private)
      - decision: speak/hold, stance to express, what to withhold, address_to, tone → `survey_decision` (private)
      - utterance (Flash-Lite, ≤ 40 words, in the agent's speech style; may agree, disagree, ask, joke or share an experience)
        → `message` event with conv_kind="focus_group" + text row
      - What they say may differ from what they privately think (social desirability). Log both.
   c. Moderator probes after interesting disagreements and invites quiet participants (Flash-Lite), as `message` with speaker="moderator".
   d. Every utterance is streamed live (B8) and shown as a bubble above the speaker's head.
4. ABSORPTION — how each listener takes in the discussion (rules + embeddings, NO per-listener model call).
   For every message a listener hears, compute salience =
     w1·relevance (embedding similarity to the listener's own concerns/open questions/beliefs)
   + w2·credibility (speaker similarity: age/occupation/income homophily; expertise: owns that brand, recent store visit, reviewer)
   + w3·emotional intensity
   + w4·novelty (not already in their memory)
   + w5·stance consistency (confirmation bias: agreeing points stick more; strong credible counter-evidence can still land)
   + w6·primacy/recency
   Then:
   - Each listener keeps a heard buffer of the top-k messages (k = 4–8, from Conscientiousness and fatigue)
     plus a one-line gist → `survey_heard` (private).
     Low-attention agents (low C, late questions) retain less.
   - Social signal per listener:
     - majority share per option, from public statements at their table
     - conformity susceptibility = f(A↑, N↑, prestance confidence↓, being in the minority, O↓)
5. PRIVATE BALLOT on their phone/tablet (DecisionAdapter, Gemini 3.5 Flash-Lite, typed schema SurveyAnswer). One per agent per question.
   a. Context, for this agent only:
      - persona card + Big Five
      - needs, money, possessions (e.g. phone age/condition)
      - beliefs on the subject
      - top-6 memories retrieved for the question: their real experiences, such as ads noticed, conversations, store visits, purchases, reviews read
      - their pre-stance
      - their heard buffer, with speaker names
      - majority signal and conformity susceptibility
      - question position (fatigue)
   b. Option order is shuffled per agent (seeded) to avoid order bias. Scale questions show the anchors.
   c. Behave like a human:
      - Lived experience outweighs persuasion. Someone with a bad store visit or a strong purchase rarely flips.
      - Credible, relevant arguments can persuade. Agreeable/anxious, low-confidence people in the minority may conform.
      - Contrarians may react against.
      - Private ballots reveal the true view more than public talk (set public_private_gap).
      - Low-engagement agents and late questions → satisficing: middle/first options, short reasons.
      - Reasons are first person and grounded in specific memories or messages (cite influenced_by).
   d. Output must validate against the schema (answer must be one of the options) → `survey_answer`.
   e. UI: a tablet appears in each avatar's hands, with a progress ring, then ✓ when submitted.
6. survey mode (no discussion):
   - skip step 3
   - pre-stance and ballot collapse into one written answer per question
   - the reason note card pops above the head in sequence
7. AFTER the session:
   a. Debrief per participant:
      - MemoryStore(agent).add(kind="conversation", importance from engagement)
      - "I went to a focus group about …, I said …, X's point about … stuck with me, I answered …"
      - small belief updates with cause_event_id
      - Participation itself can change people; flag this as "participation effect" in the results.
   b. Moderator summary per table and overall (Flash), from PUBLIC messages and the answers only → `survey_summary`.
   c. Close the sessions; agents resume their routine and walk out of the venue.
   d. `survey_completed` with actual_usd.

B5 Waves and panels (evolution over time)
- "Save as panel" stores the participant list.
- "Run again" (POST /surveys/{id}/rerun) creates wave n+1 with the same questions and re-invites the same panel.
  Attendance is decided again; drop-outs are realistic.
- Wave comparison:
  - per-question distribution change
  - per-agent change table (wave n → n+1)
  - "why it changed": Flash explains each changed answer ONLY from that agent's own events between the two waves
    (exposures noticed, thoughts, conversations, store visits, purchases, life events), citing event ids
  - a longitudinal chart across waves

B6 Events, Pub/Sub and BigQuery (all through EventBus.emit / emit_text → world-events / world-texts → BigQuery subscriptions)

New event kinds (additive):
| kind | payload | private |
|---|---|---|
| survey_created | survey_id, title, mode, n_questions, cohort | no |
| survey_invite | survey_id | no |
| survey_rsvp | rsvp, reason | **yes** |
| survey_prestance | PreStance | **yes** |
| survey_thought | question_id, text | **yes** |
| survey_decision | speak/hold, stance, withheld | **yes** |
| survey_heard | HeardItem[] + gist | **yes** |
| survey_answer | SurveyAnswer | no |
| survey_summary | table_id, summary | no |
| survey_completed | counts, actual_usd | no |

Reused kinds:
- `arrive` (place_id = venue)
- `message` (conv_kind="focus_group", session_id = table session; moderator messages included)

Every event carries survey_id in its payload and session_id where it applies.

New text kinds in `texts` (with embeddings): survey_thought, survey_answer (reason + open answers), survey_summary.
`message` texts are already covered.

New views (new files only; DuckDB equivalents; added to insights/dictionary.yaml):
- v_surveys
- v_survey_participants
- v_survey_messages
- v_survey_answers
- v_survey_shift (prestance → final, per agent/question)
- v_survey_waves (answer per agent per wave)
All are readable by ll-analyst-ro.

B7 API (additive; base /api) + engine commands
| Method & path | Request → Response |
|---|---|
| POST /surveys | {title, mode, product_id?, topic, questions[], cohort_filter?, interest_filter?, max_participants (1–100), table_size?, start_at_t?, incentive_inr?} → {survey_id, eligible, expected_attendance, estimate_usd, lint[]} |
| POST /surveys/{id}/launch | → status recruiting (refused if estimate > remaining interactive budget) |
| GET /surveys | list with status, wave, panel |
| GET /surveys/{id} | definition, status, participants (rsvp reasons only when ?include_private=1, labelled), tables, results |
| GET /surveys/{id}/transcript?table= | public messages, ordered |
| GET /surveys/{id}/agents/{agent_id} | that agent's prestance, thoughts, decisions, heard buffer, answers (private labelled) |
| POST /surveys/{id}/rerun | → new survey_id (wave n+1) |
| POST /surveys/{id}/cancel | → cancelled; participants released |
| POST /surveys/lint | {questions[]} → warnings (leading, double-barrelled, loaded, overlapping options); Flash; warns, never blocks |

- Engine POST /commands (IAM): types survey_launch, survey_cancel.
- The api never writes world state.

B8 Live protocol (additive message types on the existing /live socket; old clients ignore them)
- In `evt` items: {"k":"survey","survey_id","status","venue":place_id,"arrived":n,"expected":N} for the World pin.
- New type "survey", sent to clients that subscribed with {"type":"sub","survey_id":…}:
  - {"type":"survey","survey_id","phase":"gathering|question|discussion|ballot|results","question_id","tables":[{table_id,seats:[agent_id]}]}
  - {"type":"survey_msg","survey_id","table_id","message_id","speaker","text","seq","t"}
  - {"type":"survey_ballot","survey_id","agent_id","question_id","done":true}
  - {"type":"survey_result","survey_id","question_id","distribution":{…}}
- Bubble text is public only. Private items are served only by the API.

B9 UI (React; tokens from web/src/styles/tokens.css; dark and light themes; desktop 1440×900, min 1280)

Entry point:
- Keep the Insights → Polls tab exactly as in the mockup. Add the entry ONLY inside the existing `page-actions` area:
  - a "Survey Room" button
  - a small "Past surveys" menu
- Do not move existing regions. 30-insights-polls must still PASS.
- If it fails only because of this button:
  - do not touch thresholds or references
  - record it as an approved deviation in DECISIONS.md and PROGRESS.md §4

Routes (sub-routes of the existing tab, no new top-level page):
- /insights/polls/survey/new — the builder
- /insights/polls/survey/:surveyId — the room

Builder (testids: survey-builder, survey-questions, survey-audience, survey-estimate, survey-launch):
- title, mode toggle (Focus group / Survey), product/topic
- question editor:
  - add up to 10 questions; type picker; options editor
  - scale anchors; "discuss" toggle; reorder
  - live lint warnings
- audience:
  - cohort filters (age, income, occupation, phone age, product stage, lifestyle, watched)
  - "interested in" product
  - max participants slider 1–100
  - table size 6–10
  - start time (next slot / pick a sim time)
  - incentive
- estimate card:
  - eligible count, expected attendance, number of tables
  - estimated model cost
  - remaining interactive budget
- Launch button

Recruiting / gathering view:
- RSVP list with private reasons (labelled "private")
- arrival counter
- "Watch them arrive" → /world, focused on the venue

Room (testids: survey-room, survey-canvas, survey-tables, survey-transcript, survey-results, survey-playback, survey-agent-card):
- Engine: three.js via @react-three/fiber v8 + @react-three/drei v9 (React 18 compatible; pin exact versions).
- Scene:
  - a warm lounge with round tables arranged in a ring
  - seated low-poly avatars (capsule body + sphere head, colour from the agent palette, name tag)
  - a moderator seat at each table
  - instanced meshes, so 100 avatars stay smooth
  - orbit camera; click a table to focus it
- Question circulation: a glowing question card travels from the moderator to each seat in turn as people respond.
  This is the "circulate the question among the group" moment.
- Speech bubbles: drei <Html> above heads.
  - typing reveal; max 3 visible per table; fade out
  - the active speaker glows
- Private toggle: clicking an avatar shows their private thought in a dashed bubble (--private colour, labelled "private thought").
- Ballot phase: tablets in hands, a progress ring per avatar, ✓ when done.
  - In survey mode, reason note cards pop above heads.
- Side panels:
  - transcript for the selected table (the accessible alternative to the 3D view)
  - live results: per-question bars, prestance → final shift chart, quotes tagged persuaded/conformed/reinforced/reacted_against, moderator summary
- Agent card: persona, phone age, prestance → answer, heard buffer, influence type, "Open profile" (profile drawer).
- Playback bar: Live / Replay, 1× 2× 4×, scrub.
  Sim time is fast (1 sim min = 2.5 real s), so the UI paces bubbles at reading speed from the timestamped stream.
- Fallbacks: no WebGL → a 2D top-down SVG table view with the same bubbles. prefers-reduced-motion is respected.
- Waves tab inside results: wave comparison + "why it changed".

World page:
- the venue pin "Research Lounge · n/N" while a survey is active
- 📋 on agents walking there
- no street bubbles from inside the room

Profile drawer → Conversations tab: focus groups attended, with that agent's own private thoughts and decisions interleaved
(own profile only), plus their answers.

Visual-test hook (additive):
- window.__ll.surveyRoom(surveyId, phase: "recruiting"|"discussion"|"ballot"|"results", progress 0–1)
  freezes the room for screenshots.
- Fixture: a small seeded demo survey in web/src/visual-fixtures/survey-fixture.json, generated by a script from a local
  fake-backend run. It is NOT extracted from the mockup, because the mockup has no survey screen.

B10 Insights integration
- New assistant tool `survey_results(survey_ref, question_id?)` → distributions, shift, waves, quotes with source_refs.
  Faithfulness rules apply.
- describe_data includes the survey views.
- The Ask assistant may answer:
  - "In the Pulse 5 focus group, who changed their mind and why?"
  - "How did the panel's view of Nova X1 change between wave 1 and wave 2?"
- It never launches a survey itself. It may suggest one with a link that opens the builder pre-filled.
- The existing I-07 poll stays as is: a fast, one-question poll of everyone.

B11 Models and budget
- Gemini 3.5 Flash-Lite (MODEL_LITE, DecisionAdapter or shared.llm; low reasoning effort; tight max_tokens):
  - RSVP
  - pre-stance
  - speaker thought/decision/utterance
  - moderator turns
  - ballots
  - written answers
- Gemini 3.6 Flash (MODEL_FLASH):
  - question lint
  - moderator summaries
  - wave "why it changed"
- MODEL_EMBED: message embeddings for absorption relevance + texts.
- Pro: only via the Ask assistant.
- Surveys are user-triggered, so they count against INTERACTIVE_CAP_USD ($5/day), recorded with governor.record.
- The estimate before launch = calls × tokens × current prices from shared/models. Show it. Refuse launch if it exceeds
  the remaining interactive budget, and suggest fewer participants, fewer questions or survey mode.
- If money runs out mid-session:
  - finish all ballots (they matter most)
  - skip the remaining discussion turns (rendered=false)
  - say so in the results
- Record actual_usd. The estimate must be within ±25% of actual.

B12 Privacy and isolation
- These never enter another agent's prompt or the moderator's prompt:
  - private items: rsvp reason, prestance, survey_thought, survey_decision, heard buffer
- Each speaker prompt gets:
  - its own AgentContext
  - its own heard buffer
  - the public question
- Each ballot prompt gets that agent's own context only. It includes only messages from THEIR table that they retained.
- Insights may read and quote private items, always labelled "private thought".

B13 Tests (Part B)
[ ] Marker-fact isolation: a marker in agent X's prestance/thought never appears in any other prompt, the moderator's prompt, or a public message
[ ] Max 100 participants enforced in API and engine. 1 participant works (no discussion). 0 eligible → a clear message.
[ ] RSVP + travel: accepted agents get a "survey" activity at the venue and actually arrive (arrive events)
[ ] Every SurveyAnswer validates; answers are always within the options; each agent has exactly one answer per question
[ ] Ballot context contains only messages from the agent's own table that are in their heard buffer
[ ] Every public utterance is emitted as a `message` event and a text row (Pub/Sub locally via the DuckDB sink; in cloud, verify rows land in BigQuery)
[ ] Determinism: same survey, same seed, same sim time ⇒ identical messages and answers (cache)
[ ] Budget: launch is refused when the estimate exceeds the remaining interactive cap; estimate within ±25% of actual
[ ] Live protocol: old clients ignore the new types; the room receives survey/survey_msg/survey_ballot

B14 Evals (evals/survey_realism.py → appended to evals/RESULTS.md)
[ ] Extraversion correlates positively with message count (r > 0.3)
[ ] Conformity: high-A, low-confidence minority members change toward the majority more often than low-A members
[ ] Experience dominance: agents with a purchase or store visit about the product keep an experience-consistent answer ≥ 80% of the time
[ ] Shift realism: 10–40% of answers change from prestance (configurable target band); each change has influenced_by or a cited memory
[ ] Wave change explained: every changed wave answer cites ≥ 1 of that agent's own events between waves
[ ] Satisficing appears more in late questions and low-C agents

B15 Acceptance (Part B)
1. Create a focus group "Pulse 5 — price and battery" with 3 questions:
   - single
   - scale 1–5
   - open
   for cohort "phone age > 5 years", max 40.
   → eligible count, expected attendance, tables and estimate are shown.
2. Launch:
   - agents RSVP with private reasons
   - accepted agents walk to the Research Lounge on the World map
   - the pin counts arrivals
3. The room shows the attendees seated at ⌈N/8⌉ round tables.
   - The question card circulates.
   - Bubbles appear above speakers' heads.
   - The transcript equals the `message` rows in BigQuery/DuckDB for that survey.
4. Every attendee answers every question privately on a tablet. Results show:
   - distributions
   - prestance → final shift
   - segment table
   - quotes with influence tags
   - moderator summary
   Some agents change their mind, with influenced_by set.
5. Survey mode with 100 participants and 5 questions completes within the interactive budget and shows reason cards.
6. After ≥ 1 sim day with new experiences, "Run again" → wave 2. Some answers change, each explained by that agent's own events.
7. Ask: "In the Pulse 5 focus group, who changed their mind and why?" → numbers match v_survey_shift, with labelled quotes.
8. A survey with 1 participant runs end to end, without discussion.

### Build order and cut order (from the session prompt §4)
Build: B2 schemas + config → B3 recruitment + travel + World pin → B4 survey (written) mode + ballots + B6 events/views (CHECKPOINT 2) → B4 discussion → B7 API + B8 live → B9 builder, 2D room, 3D room, results, agent card, playback → B5 waves + B10 Ask tool → B13 tests, B14 evals (CHECKPOINT 3).

Cut order (cut from the top; never cut the last line):
1. 3D polish (keep the 2D room view)
2. automatic wave comparison text (keep rerun + side-by-side numbers)
3. moderator probes
4. lint
NEVER CUT: recruitment + walking to the venue, discussion with bubbles, private individual ballots on Flash-Lite, Pub/Sub/BigQuery logging, results with shift.
