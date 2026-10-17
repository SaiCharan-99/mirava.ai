# Phase 5 — Stores, buying and Insights

**Time box:** ~3 h · **Depends on:** Phase 4 · **Specs:** S-01 … S-06, T-03, I-01 … I-09, U-07 · **Visual screens:** `24-insights-ask`, `25-insights-overview`, `26-insights-sources`, `27-insights-hoardings`, `28-insights-segments`, `29-insights-conversations`, `30-insights-polls`, `31-insights-interview`

## Goal
Agents now act on what they've seen:
- **need × interest × opportunity** move them through consideration
- they **research** (reviews, community) and **visit fictional stores**, where they question salesperson agents **turn by turn** (think → decide → speak)
- the customer's private evaluation never reaches the salesperson
- they buy only when need, affordability and preference line up

**Insights** answers any question over the accumulated data, using a Gemini 3.1 Pro assistant with tools (SQL on curated views, vector search, cohorts, likely-buyer profiles, polls, interviews). It also offers dashboards: Overview, Sources, **Hoardings**, Segments, Conversations, Polls and Interview.

## Accounts & cloud setup needed
Walk me through these with `/gcp-setup` before the first step that needs them, unless they're already ✅ in `PROGRESS.md` §5b:
- `/gcp-setup 09` (views + analyst section) — create the curated views; `ll-analyst-ro` service account for Insights SQL; check that `VECTOR_SEARCH` works on `texts`
- Interactive budget: set `INTERACTIVE_CAP_USD=5` in Cloud Run env

## Prompt
```
You are starting Phase 5 of Launch Lens in a fresh session.
Read CLAUDE.md, PROGRESS.md, docs/DECISIONS.md and docs/phases/phase-05-stores-insights.md.
Then read: docs/architecture.md §11.2 + §11.4 (store inquiry), §12 (buying), §14 (Insights), §16.4, §18 (SQL safety);
docs/INTERFACES.md §2 (Inquiry, Belief, events consideration/purchase/inquiry/store_thought), §3 (insights tools), §5 (insights endpoints), §9 (views);
docs/specs.md S-01…S-06, T-03, I-01…I-09, U-07.
Look at docs/ui-reference/24–31 and the live mockup's Insights tabs.

Goal: consideration + store inquiries + purchases, curated BigQuery views, the Insights assistant with faithfulness checks, and all Insights tabs.
Run make test first. Finish with make test, make lint, make eval (insights subset), acceptance checks, /visual-check 5, /end-phase.
Do not start Phase 6.
```

## Read first
Architecture §12 (state diagram), §14.2 (tools, output schema, example), §11.4 (sequence). INTERFACES §3 (`insights/tools.py`), §9.

## Build checklist
### Buying (S-01 … S-06)
- [ ] `commerce/need.py` (phone: age, condition, battery, lost/broken, satisfaction, job dependence; life events spike need)
- [ ] `commerce/consideration.py`: state machine per agent × product (`config/consideration.yaml`), transitions on wake-up planning and belief updates, `consideration` events with cause
- [ ] Planner: researching → review/community reading in feed sessions; inquiring → store visit planned (nearest stocking store or ShopKart online) with open questions as the agenda
- [ ] `commerce/stores.py`: hours, stock (launched products + baseline market), salesperson shifts
- [ ] **Store inquiry (T-03)** `social/store_inquiry.py`:
  - customer turn: private thought (Flash-Lite) → decision (speak/hold, which question, what to withhold) → utterance (Flash-Lite)
  - salesperson: ADK agent with `product_facts`, `stock`, `offers` tools, seeing **only the spoken transcript**
  - ≤ 10 messages each
  - logged as `store_thought` (private), `salesperson_thought` (private), `message`, `inquiry`
  - customer debrief
- [ ] `commerce/purchase.py`: need ≥ θ, affordability (cash/card/EMI), preference margin ≥ δ → decision model typed choice incl. **baseline market** options → `purchase` event; possessions and money update (new phone, age 0)

### Insights data + assistant (I-01, I-09)
- [ ] `infra/bigquery/views/*.sql` for all views in INTERFACES §9 (+ DuckDB equivalents); `insights/dictionary.yaml`
- [ ] `insights/tools.py`:
  - `describe_data`
  - `run_sql`: read-only on views only; sqlglot parse rejects DML/DDL and non-view tables; dry-run; `maximum_bytes_billed`; 5,000 rows; runs as `ll-analyst-ro`
  - `semantic_search`: BigQuery `VECTOR_SEARCH` on `texts` with filters
  - `cohort`, `likely_buyers` (score `need × interest × affordability × stage_weight`, grouped)
  - `poll`: engine command, estimate first, interactive budget
  - `interview`: interviewer agent grounded in that agent's memory only
  - `chart`
- [ ] ADK Insights assistant (Gemini 3.1 Pro): output schema `AskAnswer`; streaming steps over SSE; **faithfulness check** (numbers ↔ tool results by `source_ref`, verbatim quotes, private thoughts labelled) → regenerate once or drop the claim; Model Armor on questions
- [ ] `evals/insights_questions.yaml` with 10 benchmark questions incl. "phones older than 5 years — interested in which product, and why?", "which hoarding gets noticed most and does facing matter?", "what do people privately think but not say about Pulse 5?"

### Web (U-07)
- [ ] Insights page with `insights-tabs` and the 8 tabs exactly like the mockup:
  - **Ask**: thread with tool steps, answer, chart, quotes linking to profiles, "Show SQL", caveats, suggestions
  - **Overview**: KPIs + awareness/curious+ lines with launch markers + funnel
  - **Sources**: first-heard stacks + top paths
  - **Hoardings**: KPIs, `sites-table`, `sites-map`, hour heat, notice themes
  - **Segments**: product switch + age × income heat + lifestyles
  - **Conversations**: topics, said vs privately thought, reviewers private vs published, community threads
  - **Polls**: form + cost estimate + result
  - **Interview**: agent list + chat with memories used
- [ ] Profile Conversations tab shows store visits with the customer's private thoughts interleaved (customer's profile only)

## Tests
- The salesperson context never contains `store_thought` content (test via a marker fact)
- Consideration transitions always have a cause event; no purchase without need ≥ θ unless a life event happened
- `run_sql` rejects `DELETE`, `CREATE`, raw tables, and cross-dataset queries
- Faithfulness eval ≥ 95% on the benchmark; quotes are verbatim
- Poll determinism (same question, same sim day ⇒ same answers)

## Visual check
`/visual-check 5` → gated `24`–`31` (+ earlier) PASS.

## Acceptance checks
1. Within 3 sim days of launch, at least 5 store inquiries with full turn-by-turn transcripts; at least 1 need-driven purchase.
2. Ask "People whose phones are older than 5 years — are they interested in any of our phones? Why?" → numbers match SQL, chart, ≥ 3 verbatim quotes (private ones labelled), SQL shown, caveats.
3. The Hoardings tab ranks sites by notice rate and shows a facing comparison for a two-sided board.
4. A poll of 1,000 agents finishes in < 90 s and shows its cost.

## Out of scope
New features beyond the specs, multi-city, forks.

## Handoff
Inquiries/purchases per sim day, Insights latency and cost per answer, benchmark results, views list, known gaps in the data dictionary.
