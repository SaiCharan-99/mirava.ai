# PROGRESS.md — mirava.ai build log (v3 · always-on agent world)

Living document. Every Claude Code session reads it first and updates it last (`/end-phase`). Keep it accurate and short. Rows 28+ of `docs/DECISIONS.md` describe the current (v3) design.

## 1. Current status
| Field | Value |
|---|---|
| Current phase | 6 Hardening, deploy, demo, submission (🟨) |
| Phase status | Phase 6 🟨 in progress (2026-10-18) |
| Repo green (`make test` + `make lint`) | ✅ 2026-10-18 (134 py + 18 web tests; ruff, mypy, eslint, tsc, gitleaks clean) |
| Last session | 2026-10-18 · phase 5 |
| Builder | Sai Charan (Claude Code) |
| Deadline | 18 Oct 2026 |

## 2. Phase tracker
| # | Phase | Status | Date | Visual check | Notes |
|---|---|---|---|---|---|
| 1 | Foundation, globe, Indiranagar map, app shell | ✅ | 2026-10-18 | 01/02/33 PASS | hello deploy live |
| 2 | Population & the always-on world engine | ✅ | 2026-10-18 | 03/04/05/06/10/32 PASS; 13/14 review | world-engine live on Cloud Run |
| 3 | Memory, think/speak conversations, governor, highlights | ⚠️ | 2026-10-18 | 07/08/09/12 PASS (+ all earlier) | live in cloud; nightly reflection not yet observed live (§8) |
| 4 | Launch Studio, channels and attention | ⚠️ | 2026-10-18 | 11/18–23 PASS (+ all earlier); 15/16/17/21b review ok | live in cloud; Nova X1 review not yet seen; P-07 not built (§8) |
| 5 | Stores, buying and Insights (+ Survey Room addendum) | ⚠️ | 2026-10-18 | 24–31 PASS (+ all gated 01–33) | live in cloud; evals 4 checks FAIL (§8) |
| 6 | Hardening, deploy, demo, submission | 🟨 | 2026-10-18 | | |
Legend: ⬜ not started · 🟨 in progress · ✅ done · ⚠️ done with open issues

## 3. Spec coverage (DEMO + STRETCH; tick only when "done when" is met)
| Group | Phase | Specs |
|---|---|---|
| World & time | 1, 2, 3 | ☑ W-01 ☑ W-02 ☑ W-03 ☑ W-04 ☑ W-05 ☑ W-06 ☑ W-07 ☑ W-08 ☑ W-09 ☑ W-10 |
| Population | 2, 4 | ☑ P-01 ☑ P-02 ☑ P-03 ☑ P-04 ☑ P-05 ☑ P-06 ☐ P-07 (stretch) ☑ P-08 |
| Engine | 2, 3 | ☑ E-01 ☑ E-02 ☑ E-03 ☑ E-04 ☑ E-05 ☑ E-06 ☑ E-07 |
| Memory | 3 | ☑ M-01 ☑ M-02 ☑ M-03 ☑ M-04 ☐ M-05 (built + tested; not yet observed live) ☑ M-06 ☑ M-07 |
| Attention | 4 | ☑ A-01 ☑ A-02 ☑ A-03 ☑ A-04 ☑ A-05 ☑ A-06 |
| Channels | 3, 4 | ☑ C-01 ☑ C-02 ☑ C-03 ☑ C-04 ☑ C-05 ☑ C-06 ☑ C-07 ☑ C-08 |
| Talk | 3, 5 | ☑ T-01 ☑ T-02 ☑ T-03 ☑ T-04 ☑ T-05 ☑ T-06 ☑ T-07 |
| Shopping | 5 | ☑ S-01 ☑ S-02 ☑ S-03 ☑ S-04 ☑ S-05 ☑ S-06 |
| Launch Studio | 4 | ☑ L-01 ☑ L-02 ☑ L-03 ☑ L-04 ☑ L-05 ☑ L-06 ☑ L-07 ☑ L-08 |
| Insights | 5 | ☑ I-01 ☑ I-02 ☑ I-03 ☑ I-04 ☑ I-05 ☑ I-06 ☑ I-07 ☑ I-08 ☑ I-09 (assistant offline planner misses SQL on 1/10 benchmark Qs) |
| UI | 1, 1, 6, 1–4, 1–6, 2, 2–3, 4, 5 | ☑ U-01 ☑ U-02 ☑ U-03 ☑ U-04 ☑ U-05 ☑ U-06 ☑ U-07 ☑ U-08 ☐ U-09 |
| Platform | 1, 1–2, 4, 6, 6 | ☑ X-01 ☑ X-02 ☐ X-03 ☐ X-04 ☐ X-05 ☐ X-06 |

## 4. Visual check status (`tools/visual`, latest run)
| Screen | Phase | Layout | Edges | Geometry | Result |
|---|---|---|---|---|---|
| 01-globe | 1 | 0.5% | 0.1% | ok | PASS |
| 02-world | 1 | 1.5% | 0.2% | ok | PASS |
| 03-world-hover | 2 | 3.8% | 1.2% | ok | PASS |
| 04-profile-overview | 2 | 3.6% | 0.3% | ok | PASS |
| 05-profile-relations | 2 | 2.0% | 0.2% | ok | PASS |
| 06-profile-possessions | 2 | 2.4% | 0.2% | ok | PASS |
| 07-profile-thoughts | 3 | 3.3% | 0.2% | ok | PASS |
| 08-profile-conversations | 3 | 3.0% | 0.4% | ok | PASS |
| 09-profile-memory | 3 | 3.7% | 0.2% | ok | PASS |
| 10-world-watching | 2 | 2.1% | 0.2% | ok | PASS |
| 11-world-products | 4 | 1.7% | 0.3% | ok | PASS |
| 12-world-highlights | 3 | 3.0% | 0.2% | ok | PASS |
| 13-world-look | 2 | 27.5% | 12.3% | ok | REVIEW (real OSM mesh vs mockup grid; ok by eye) |
| 14-world-night | 2 | 25.2% | 12.1% | ok | REVIEW (dark overlay + glows on real roads; ok by eye) |
| 15-world-lens-aware | 4 | 41.5% | 3.3% | ok | REVIEW (rings + legend + product picker; ok by eye) |
| 16-world-lens-hoardings | 4 | 42.4% | 3.2% | ok | REVIEW (cones coloured by product; ok by eye) |
| 17-world-launch-fx | 4 | 43.0% | 3.7% | ok | REVIEW (orb/burst/pill/flares; ok by eye) |
| 18-launch-list | 4 | 1.7% | 0.2% | ok | PASS |
| 19-launch-details | 4 | 3.9% | 0.2% | ok | PASS |
| 20-launch-content | 4 | 4.4% | 0.3% | ok | PASS |
| 21-launch-understand | 4 | 3.2% | 0.3% | ok | PASS |
| 21b-launch-graph | 4 | 5.3% | 6.9% | ok | REVIEW (select + neighbours + details; ok by eye) |
| 22-launch-plan | 4 | 3.3% | 0.3% | ok | PASS |
| 23-launch-ready | 4 | 2.2% | 0.2% | ok | PASS |
| 24-insights-ask | 5 | 4.2% | 0.3% | ok | PASS |
| 25-insights-overview | 5 | 1.8% | 0.3% | ok | PASS |
| 26-insights-sources | 5 | 1.8% | 0.2% | ok | PASS |
| 27-insights-hoardings | 5 | 3.5% | 0.4% | ok | PASS |
| 28-insights-segments | 5 | 2.3% | 0.2% | ok | PASS |
| 29-insights-conversations | 5 | 3.8% | 0.2% | ok | PASS |
| 30-insights-polls | 5 | 2.8% | 0.4% | ok | PASS |
| 31-insights-interview | 5 | 2.5% | 0.2% | ok | PASS |
| 32-people | 2 | 4.9% | 0.4% | ok | PASS |
| 33-guide | 1 | 1.8% | 0.2% | ok | PASS |
| 34-people-light | 6 | 2.1% | 0.4% | ok | PASS |

## 5. Environment
| Item | Value |
|---|---|
| GCP project / region | mirava-ai-hack (760833706192) / asia-south1 |
| Web URL (Firebase Hosting) | https://mirava-ai-hack.web.app |
| API URL (Cloud Run `mirava-api`) | https://mirava-api-kfh7v3hvjq-el.a.run.app (public path: https://mirava-ai-hack.web.app/api/healthz) |
| world-engine URL / revision | https://world-engine-kfh7v3hvjq-el.a.run.app (wss …/live, GET /health) · world-engine-00012-fpw (phase 4) · mirava-api-00008-prw (1 GiB, Model Armor on) · phase 5: world-engine-00015-tvk, mirava-api-00012-7c9 |
| OSM extract date / map stats | Overpass 2026-10-17T17:07Z · 299×305 tiles (8 m) · 3,501 nodes / 4,455 edges (all reachable) · 12,179 places · 60 sites · 4 stores |
| Genesis version / seed | v1 / 4271 · 1,000 agents, 435 households, 7,012 relationships (avg degree 14.0, 0 isolated), 950 Gemini bios + 50 template ($0.52) · gs://mirava-ai-hack-mirava-worlds/genesis/v1/ |
| Firestore vector index | `memories` composite CICAgOjXh4EK (agent_id + embedding 768-d flat) |
| BigQuery views | agents_latest, v_messages, v_conversations, v_exposures, v_site_daily + phase 5: beliefs_daily, beliefs_latest, v_thoughts, v_inquiries, v_purchases, v_posts, v_reviews, v_first_heard, v_paths, v_funnel_daily, v_surveys, v_survey_participants, v_survey_messages, v_survey_answers, v_survey_shift, v_survey_waves (`python -m infra.bigquery.init mirava-ai-hack mirava`) |
| Live products (ids, launched at) | cloud: pulse-5 @ t=14030, orbit-s @ t=14047 (Day 10); nova-x1 ready in the dock · local emulator: all three live (Nova X1 @ t=108593) |
| Demo snapshot name | _phase 6_ |

## 5b. Accounts & cloud setup status
Filled in by `/gcp-setup` (guides in `docs/setup/`). Never paste keys or secrets here — only names and ✅.
| # | Item | Needed by phase | Status | Date | Notes (names, region — no secrets) |
|---|---|---|---|---|---|
| 00 | OpenRouter account, API key in `.env`, models verified, credit limit | 1 | ✅ | 2026-10-17 | key in .env only; 4 model ids listed; llm-smoke OK (structured + 768-d embedding); credit limit $25 set by user 2026-10-18 (engine uses the key for real from phase 3) |
| 15 | OpenStreetMap extract for Indiranagar (only if Overpass is blocked) | 1 | not needed | 2026-10-17 | Overpass reachable; extract committed |
| 01 | GCP project, billing, budget alert, gcloud + ADC | 1 | ✅ | 2026-10-17 | project mirava-ai-hack (#760833706192), free trial, billing ✅, ADC ✅ (saicharangobburu@gmail.com); budget alert set in console by user |
| 02 | APIs enabled, service accounts + roles | 1 | ✅ | 2026-10-17 | 19 APIs (+billingbudgets); SAs mirava-api, mirava-engine, mirava-analyst-ro, mirava-scheduler; roles per guide 02 (run.invoker on world-engine in phase 2) |
| 03 | Secret Manager `openrouter-api-key` | 1 | ✅ | 2026-10-17 | version 1 = dev key from .env (rotate to a prod key in phase 6); accessor: mirava-api, mirava-engine |
| 04 | Artifact Registry `mirava`, Cloud Build permissions | 1 | ✅ | 2026-10-17 | repo asia-south1/mirava; builds run as 760833706192-compute SA (deploy roles granted, also to legacy cloudbuild SA) |
| 05 | Cloud Run `mirava-api` | 1 | ✅ | 2026-10-18 | asia-south1, SA mirava-api, secret mounted, min 0 / max 5; deployed by Cloud Build 2098a98e (SUCCESS) |
| 06 | Firebase Hosting | 1 | ✅ | 2026-10-18 | Firebase added to mirava-ai-hack (Blaze/free trial); site mirava-ai-hack.web.app; .firebaserc committed |
| 07 | Firestore emulator (local) | 1 | ✅ | 2026-10-17 | 127.0.0.1:8080; needs Java 21+ (Temurin 25 JRE installed) |
| 07 | Firestore database `asia-south1` | 2 | ✅ | 2026-10-18 | (default) native, asia-south1 |
| 08 | Cloud Storage buckets + CORS | 2 | ✅ | 2026-10-18 | mirava-ai-hack-mirava-{uploads,worlds,exports}, asia-south1, worlds versioned; uploads CORS ✅ 2026-10-18 (GET/PUT from localhost:5173 + mirava-ai-hack.web.app, infra/cors.json); worlds CORS not needed (highlights via API) |
| 09 | BigQuery dataset `launch_lens` (+ public data priors) | 2 | ✅ | 2026-10-18 | dataset `mirava` (asia-south1): events, texts, view agents_latest via `python -m infra.bigquery.init`; priors cached in config |
| 10 | Pub/Sub `world-events`, `world-texts` + BigQuery subscriptions | 2 | ✅ | 2026-10-18 | world-events-to-bq / world-texts-to-bq (table schema); ping verified; phase 3: texts rows with 768-d embeddings verified in BigQuery |
| 05 | Cloud Run `world-engine` (always-on, min=max=1) | 2 | ✅ | 2026-10-18 | SA mirava-engine, 2 vCPU/4 GiB, no-cpu-throttling, session affinity, public; /commands needs ID token from mirava-api; mirava-api has ENGINE_URL |
| 16 | Cloud Scheduler watchdog | 2 | ✅ | 2026-10-18 | world-engine-watchdog, */5, GET /health, asia-south1 |
| 07 | Firestore vector index `memories` | 3 | ✅ | 2026-10-18 | composite CICAgOjXh4EK: agent_id ASC + embedding flat 768-d, scope COLLECTION, READY |
| 12 | Model Armor template | 4 | ✅ | 2026-10-18 | template `mirava-screen` in asia-south1 (RAI medium+, PI/jailbreak HIGH); roles modelarmor.admin (user), modelarmor.user (mirava-api); gcloud needs `CLOUDSDK_API_ENDPOINT_OVERRIDES_MODELARMOR=https://modelarmor.asia-south1.rep.googleapis.com/`; Cloud Run api env MODEL_ARMOR_ENABLED/TEMPLATE set at the phase-4 deploy |
| 09 | BigQuery views + `ll-analyst-ro` + VECTOR_SEARCH check | 5 | ✅ | 2026-10-18 | mirava-api has serviceAccountTokenCreator on mirava-analyst-ro (dataViewer + jobUser); VECTOR_SEARCH on `mirava.texts` verified (3,135 rows, no index until >5k); INTERACTIVE_CAP_USD=5 on mirava-api-00010-79r + world-engine-00013-gsp; all 16 phase-5 views created in `mirava` (v_first_heard 961 rows) |
| 13 | Monitoring dashboard + alerts | 6 | ✅ | 2026-10-18 | email channel (saicharangobburu@gmail.com); uptime check world-engine-health (/health, 60 s); log metrics engine_tick_p95_ms, engine_spend_today_usd, engine_rendered_ratio, engine_live_viewers (hourly `metrics` line); alerts: engine stalled (uptime fails 5 min = tick lag > 2 min), api 5xx > 10/5 min, spend > $15; dashboard "mirava world"; re-create: `uv run python -m infra.monitoring.setup mirava-ai-hack <email>` |
| 14 | Vertex AI (only if `LLM_BACKEND=vertex`) | — | skipped | | |

## 6. How to run (keep current — copy-paste ready)
```bash
# Windows: Git Bash. One-time: source .devpath.sh   (adds make + gitleaks to PATH in this shell)
uv sync && (cd web && npm install) && (cd tools/visual && npm ci && npx playwright install chromium)
# npm install must run from PowerShell on this PC (stray quote in Windows PATH breaks cmd.exe from Git Bash)
make genesis      # once, emulator running (fake LLM; LLM_BACKEND=openrouter for real bios)
make dev          # Firestore emulator (Java 21+ on PATH) + world-engine :8100 + api :8000 + web :5173 (fakes, 120 s/day)
make seed-demo    # Nova X1 ready, Pulse 5 + Orbit S live via the API (api + engine running); cloud: uv run python -m tools.seed_demo --api https://mirava-api-kfh7v3hvjq-el.a.run.app
make engine       # engine alone (fast clock 120 s/day; actually runs ~1.6 sim min/s)
make test && make lint
make map          # regenerate map assets (deterministic)
LLM_BACKEND=openrouter make llm-smoke
make visual PHASE=1   # app must be running on :5173
make deploy       # Cloud Build → Cloud Run mirava-api + Firebase Hosting (web built with VITE_ENGINE_WS)
gcloud builds submit --config infra/cloudbuild-engine.yaml --region asia-south1 .   # world-engine
uv run python -m infra.bigquery.init mirava-ai-hack mirava                          # BQ tables + views
# cloud genesis: ENV=cloud GCP_PROJECT_ID=mirava-ai-hack LLM_BACKEND=openrouter EVENT_SINK=pubsub GCS_BUCKET_WORLDS=mirava-ai-hack-mirava-worlds uv run python -m population.genesis
```
# phase 3: conversations run in the engine by default (Engine(..., social=False) disables them, used by the determinism test)
# OpenRouter key usage (never prints the key): uv run python -c "import httpx;from shared.settings import get_settings as g;print(httpx.get('https://openrouter.ai/api/v1/key',headers={'Authorization':'Bearer '+g().openrouter_api_key.get_secret_value()}).json()['data']['usage_daily'])"
# phase 4: visual capture against another port: cd tools/visual && node capture.mjs --target app --phase 4 --base http://localhost:5174
# v_site_daily locally: the engine holds .data/mirava.duckdb — stop it, query (read_only), restart (resumes from checkpoint)
# Model Armor gcloud: CLOUDSDK_API_ENDPOINT_OVERRIDES_MODELARMOR=https://modelarmor.asia-south1.rep.googleapis.com/ gcloud model-armor templates list --location=asia-south1
# phase 5: evals (fake backend, ~70 min on this PC; output only at the end): uv run python -m evals.run --agents 200 --days 1   → evals/RESULTS.md
# phase 5: run a survey locally: make dev && make seed-demo, open http://localhost:5173/insights/polls → "Survey Room" → build questions → Estimate → Launch; watch the Research Lounge pin (P-0186) on /world; the room opens at /insights/polls/survey/<id>
# phase 5: survey screenshots: cd tools/visual && node survey-shots.mjs  (→ artifacts/visual/survey-room/)
Visual-test URL: http://localhost:5173/world?visualTest=1 · Live: https://mirava-ai-hack.web.app

## 7. Contract changes (to docs/INTERFACES.md)
- [phase 5] **Survey Room** (additive): schemas, config/survey.yaml, event/text kinds, views, API, live types, routes, testids, `__ll.surveyRoom` — see `docs/phases/phase-05-addendum-survey-room.md` "Contract additions" — DECISIONS #86–91.
- [phase 4] media runtime, `attend` signature, exposure payload extras, live evts notice/launch/review/post/comment, views v_exposures/v_site_daily — DECISIONS #80–82.
- [phase 4] products API extras (`/creatives`, `/audience`, DELETE, local `PUT /uploads`), plan field notes — DECISIONS #77–79.
- [phase 3] async `mind.context.build(..., store, llm)`, `MemoryStore(agent_id, store, llm, on_event)`, `DocStore.nearest` — DECISIONS #72.
- [phase 2] engine health `/health`; engine `/state`, `/stats`, `/agents/{id}/state`; live modes/acts + phase-2 evt kinds; extra fields on `/agents` and `/agents/{id}`; Firestore feed_sessions as objects; `world/state.last_flushed_t` — DECISIONS #65–67.
- [phase 1] `indiranagar.tmj` gains object layer `lights` and documents `labels` object types (INTERFACES §4.1) — needed for night lighting — DECISIONS #60.

## 8. Known issues / tech debt
- [phase 5] [minor] Evals (evals/RESULTS.md, 200 agents · 1 day, fake backend): faithfulness 100%, verbatim 100% PASS; FAIL: `first_heard` answer has no SQL (offline rule planner skips run_sql), `purchases` has no numbers (no purchases in a 1-day world), experience dominance 2/3 (n=3 too small), wave changes explained 24/28 (4 with no own events between waves → "no clear cause"). Fix: planner route for first_heard, run evals with --days 2, treat "no events" changes as explained-by-noise or seed fewer flips.
- [phase 5] [minor] Survey late arrivals become no-shows (do not join the next question as B3.8 says).
- [phase 5] [minor] Insights assistant is an own structured tool loop, not ADK (DECISIONS #92); offline rule planner in fake mode.
- [phase 5] [minor] Ask assistant cost is not booked to the engine's interactive budget (only polls/surveys are).
- [phase 5] [minor] evals take ~70 min on this PC and print nothing until the end.
- [phase 4] [fixed] Cloud plan reasons were templates (prompt placeholder `{sites}` vs `{facts}` → KeyError swallowed); fixed + regression test, Nova X1 re-planned. Gemini reasons are repetitive in wording — tighten the prompt (phase 6).
- [phase 4] [minor] Target OTS/day in cloud plans is low (4–12) — the cloud world has ~9 days of highlight samples at 10-min resolution. Re-plan after more history.
- [phase 4] [minor] P-07 (category bootstrap, stretch) not built.
- [phase 4] [minor] GraphView is a canvas port of the mockup's force engine, not `react-force-graph-2d` (DECISIONS #83).
- [phase 4] [minor] Feed "friends' posts" are not modelled (feed = campaign reels + followed reviews + baseline ads); newspaper print ads use fixed size/page (half, p3).
- [phase 4] [minor] Store-display exposures are rare: stores are only 3 of many shop haunts (phase 5 adds intent-driven store visits).
- [phase 4] [minor] Visual-test REVIEW screens 15–17 differ from the mockup in base map (real OSM) as in 13/14.
- [phase 4] [minor] Reviewers publish 0.4–2 sim days after launch; first review in the cloud expected around Day 11 (Pulse 5).
- [phase 3] [minor] No reflections observed live yet: real importance ratings (~5–6 per chat) rarely reach the ≥ 12 threshold before ads exist, and a 03:00 inside a boot replay skips the nightly job. Fix: keep threshold (spec), re-check in phase 4; optionally run the nightly job on the first live tick after a replay that crossed 03:00.
- [phase 3] [minor] Firebase Hosting cached `/api` responses (incl. 404s) for 10 min; fixed with `Cache-Control: no-store` middleware in `api/main.py` — confirm it is deployed (§9).
- [phase 3] [minor] Embedding calls are not reported to the governor/budget meter (`shared/llm.py` embed). Fix: record a CostRecord per embed batch.
- [phase 3] [minor] Gate talk/skip is rule-based (closeness × free time) instead of a model call, to keep I/O out of the tick (DECISIONS #75); the model still chooses share plans.
- [phase 3] [minor] Day timeline in live mode shows the average for past days (no per-day conversation counts endpoint yet).
- [phase 3] [minor] Worlds-bucket CORS not set (not needed: highlights go through the API); set before phase 4 uploads.
- [phase 3] [minor] Boot replay from a checkpoint (≤ 1 sim hour) re-steps the world without the social layer, so talk pauses in that window are not reproduced (positions may differ slightly from what viewers saw; events are not re-emitted). In-flight conversations at a crash are dropped.
- [phase 3] [fixed] Paydays at 09:00 and life events were skipped for agents travelling at that minute (phase 2).
- [phase 2] [resolved in phase 3] On deploy Cloud Run kept the old revision alive >20 min. Revision handoff in `engine/lease.py` verified on 3 phase-3 engine deploys (new revision took the lease within ~1 min, no tick gap). If a new revision stays `follower`, set `world/lease.holder` to the new holder id (`GET /state` → engine.holder).
- [phase 2] [minor] Tick p95 108–220 ms in the cloud (target 150, budget 2.5 s); fast dev clock can't keep pace.
- [phase 2] [minor] BigQuery can hold a few duplicate event_ids around restarts (Pub/Sub has no dedupe): views dedupe by event_id.
- [phase 2] [minor] Live sprite look keyed by id; Export CSV placeholder; Products tab awareness from fixtures; buckets have no CORS yet.
- [phase 1] [resolved in phase 2 via /health] Cloud Run's front end answers `GET /healthz` itself with 404 on the direct run.app URL; `/api/healthz` works. **world-engine (phase 2) needs a different health path** (e.g. `/health` or `/api/healthz`) or the Scheduler watchdog will 404 — api/main.py, INTERFACES §5 — suggested fix: add `/health` and update the contract.

## 9. Handoff notes for the next session
**Phase 1 handoff**
- GCP project `mirava-ai-hack` (760833706192), region asia-south1. Web https://mirava-ai-hack.web.app · API https://mirava-api-kfh7v3hvjq-el.a.run.app (use `/api/healthz` via Hosting — direct `/healthz` is 404 on run.app, see §8).
- Map stats: §5. OSM extract 2026-10-17, committed (`assets/osm/indiranagar.osm.json`).
- `__ll` hooks: real = featured, lens, setTime, overview. **Stubs** = focus (centres on metro), hoverAgent, openAgent, highlights, launchFx, graphSelect, graphHover.
- World page shows mockup fixtures (stats, ticker, products, dock) in every mode until `/live` exists (DECISIONS #63).
- Map vs mockup style: real OSM streets (organic, not a grid); boards drawn 3× life size; buildings are tile-raster (no shadows); Old Airport Road outside bbox (no label); night glow from tmj `lights` layer.
- Names: everything new uses mirava-* (DECISIONS #55–56); setup guides still say launch-lens.
- Local: Firestore emulator on 127.0.0.1:8080 needs Java 25 JRE (installed at C:\Program Files\Eclipse Adoptium\jre-25…) first on PATH.

**Phase 2 handoff**
- Engine https://world-engine-kfh7v3hvjq-el.a.run.app, revision world-engine-00004-sjb; lease `world/lease` (60 s expiry, 20 s renew; newer revision requests takeover, old one checkpoints + releases).
- Checkpoint ~100 KB, ~4.7 s incl. 1,000-doc Firestore batch, every sim hour; tick p95 ~110 ms (cloud); ~1,000 events per sim hour by day; hello ≈ 79 KB; stream well under 10 KB/s.
- Persona generation: 38 Flash batches, $0.52, 950 valid bios / 50 template fallbacks. No invalid routines.
- Acceptance: (1) 755 sim min in 1,956 real s ≈ 0.39/s ✅ (2) new revision resumed from checkpoint 900 + replay 20 ✅ (3) two viewers 1000/1000 identical positions ✅ (4) agents_latest phone_age_years>5 = 176 = API ✅.
- Web: hover, profile Overview/Relations/Possessions live; Thoughts/Conversations/Memory show "available in phase 3".

**Phase 3 handoff**
- Live since Day 5 10:08 with real OpenRouter (Flash-Lite for prep/dialogue/debrief; Flash for product chats). Engine revision handoff verified 3×.
- Rendered chats per sim day: 60 (Day 5), 30 (Day 6; P4 cap 30/day, paced by hour) vs ~1,100–2,150 unrendered `interaction`s; stranger chats 79–130/day; avg 6 msgs, max 10.
- Average cost per rendered chat ≈ $0.003 (5 calls). OpenRouter key usage today $0.57; **key limit is $10 (user meant $25 — re-check on openrouter.ai)**.
- Retrieval latency: not measured in the cloud (Firestore find_nearest + 1 query embedding; LRU caches hot agents). Measure in phase 4.
- Reflection count: 0 so far (only 1/104 agents reached day importance ≥ 12; Day 6 03:00 fell inside a boot replay). Expected to rise once ad thoughts exist.
- Isolation: 200-chat marker-fact test with an echo model — 0 leaks; it found and fixed one real leak path (free-text `tone`).
- Governor caps in use: config/budget.yaml (daily $15, interactive $5, P0 40 · P1 220 · P2 20 · P3 120 · P4 30 · P5 15 per sim day); no slow-down so far.
- Acceptance: (1) ✅ s6551-116-569-71 greeting first, 10 msgs, private parts only for the owner (2) ✅ v_messages == transcript; texts 549/549 with 768-d embeddings (3) ✅ budget events hourly, $0.16 / ~11 sim h (4) ✅ Day 5 highlights replay + camera jumps + click → profile. Fixes for first line / hour spread verified on Day 6: 31 moments over 16 hours, 30/30 conversation moments with first line.
- Embedding calls are not reported to the governor yet (engine meter $0.18 vs OpenRouter $0.57 today).

**Phase 4 handoff**
- Product ids: nova-x1 (ready, --p1 #f97316 locally; cloud colour by creation order), pulse-5 (live, cloud t=14030), orbit-s (live, cloud t=14047). Local emulator: all three live (Nova X1 launched t=108593 from the dock, seen by two browsers).
- Plan outputs (cloud): Nova X1 8 sites (S-12M-02, S-CMH-11, S-CMH-09, S-CMH-06, S-DBL-04, S-100FT-08, S-CMH-12, S-100FT-16), 4–10 target OTS/day each, reel audience 190, 4 reviewers, 3 stores; Pulse 5 8 sites; Orbit S 4 sites (intensity low).
- Notice rates (cloud, Day 10): hoarding 4.3% notice / 31.9% glance of OTS; metro panels 3.2%; bus shelters 0/40; reels 20.4% watched (partial+full); community 24.4%. Local demo world: 35% glance / 6% notice (calibration test).
- Thoughts: 149 rendered ad thoughts in the cloud on Day 10 (from ~09:00), all rendered (P1 cap 220/day); engine spend $0.88 that real day incl. conversations. Local fake run: 369 thoughts in 1.6 sim days.
- Reviewers/community: local — 4 reviews in 1.6 days (first ~0.7 day after launch), threads from the news desk + every review, comments 6–10/day, upvotes; cloud — 2 news-desk threads, 55 community thoughts, 12 upvotes, first review expected ~Day 11.
- Planner edge cases: no highlights yet → commute-path traffic fallback (few OTS); sites held by live products excluded; Gemini reasons only when lengths match (else templates, logged).
- Bugs fixed this phase: duplicate Phaser canvas under StrictMode (visible map was a frozen frame), `clientOf` stale worldView, ticker per-agent name lookups starving the Launch POST, engine ID-token audience empty (403), api 512 MiB OOM in the planner, Dockerfiles missing media/agents/social.

**Phase 5 handoff**
- Commerce: 3-sim-day local run → 27 store inquiries (turn-by-turn, think→decide→speak), 3 need-driven purchases (≈9 inquiries/sim day).
- Survey Room: venue P-0186 "Research Lounge" (config/survey.yaml); max 100 participants, tables of 6–10; estimate calibrated at 6 think + 4 speak + 3 moderator calls per question per table + 1 ballot per participant per question (≈ $0.0015 per participant per question on Flash-Lite); eval focus group: 39 attended, 15% shifted, r(E, msgs) = 0.65.
- Insights: 8 tabs PASS visually; Ask uses run_sql (sqlglot guard, views only, analyst SA impersonation in cloud), semantic_search (VECTOR_SEARCH), likely_buyers, poll, interview; faithfulness check drops/regenerates unmatched numbers.
- Cloud: phase-5 views created; mirava-api impersonates mirava-analyst-ro; INTERACTIVE_CAP_USD=5 on both services; revisions world-engine-00015-tvk, mirava-api-00012-7c9.
- OpenRouter key: limit $10, used $4.79, remaining $5.21 (2026-10-18) — raise before the demo.

**Next session (phase 6) must:**
1. `/start-phase 6`; `make test`/`make lint`; fix the 4 failing eval checks (§8) and re-run `uv run python -m evals.run --agents 200 --days 2`.
2. Check the OpenRouter key limit (remaining ~$5) and `/gcp-setup 13` (monitoring).
3. Demo snapshot + `make restore-demo`, then the full `/visual-check` 01–34.

**(phase 4) Next session (phase 5) must:**
1. `/start-phase 5`; `make test`/`make lint`; check `GET https://world-engine-kfh7v3hvjq-el.a.run.app/state` is running on revision ≥ 00012 and that a Nova X1/Pulse 5 review appeared (`reviews` collection).
2. `/gcp-setup 09` (BigQuery views + `mirava-analyst-ro` + VECTOR_SEARCH check) before the Insights assistant.
3. Build stores/inquiries on `engine/media_rt.py` (store displays) + `commerce/`; Insights Hoardings tab reads `v_site_daily`; Sources uses `belief.first_heard` (C-07, L-08 launch markers).

**(phase 3) Next session (phase 4) must:**
1. `/start-phase 4`; run `make test`/`make lint`; check `curl -sI https://mirava-ai-hack.web.app/api/world/state | grep -i cache-control` says `no-store` (api fix committed at phase-3 close; if not, `make deploy`).
2. Report embedding cost to the governor (`shared.llm` embed → `CostRecord`), re-check the OpenRouter key limit, then `/gcp-setup 12` (Model Armor) and CORS on the uploads bucket (guide 08).
3. Build ad thoughts on top of `mind.context.build` + `MemoryStore`; product salience feeds `social.gate.Side.products_salient` (C-07 word of mouth).

**(phase 2) Next session (phase 3) must:**
1. `/start-phase 3`; run `make test`/`make lint` first.
2. `/gcp-setup 07` vector index for memories (+ CORS on the worlds bucket for highlights).
3. Build memory retrieval + conversations on `engine/world.py` (encounter hook in `World._act`) using `engine/tasks.py`.

**(phase 1) Next session (phase 2) must:**
1. `/start-phase 2`; run `make test`/`make lint` first.
2. Pick a health path for world-engine that Cloud Run doesn't intercept (§8) and update INTERFACES §5.
3. Walk through `/gcp-setup` 07 (cloud Firestore), 08, 09, 10, 05 (world-engine), 16 before deploying the engine.

## 10. Session log (newest first)
### 2026-10-18 16:30 · Phase 5 · ⚠️
- Built: commerce (need, consideration, stores, purchase) + engine/commerce_rt, store inquiry T-03, 16 BQ/DuckDB views + dictionary, insights tools/assistant/faithfulness/likely_buyers/polls, interviewer, 8 Insights tabs, profile Conversations (store visits + focus groups, own private thoughts), Survey Room (recruit, travel, tables, discussion, absorption, private ballots, waves, 3D/2D room, world pin), evals.
- Tests: test_commerce, test_insights, test_survey (+ all earlier); views on DuckDB pass.
- Visual check: 24–31 PASS + all gated 01–33; Survey Room screenshots in artifacts/visual/survey-room/.
- Deployed: world-engine-00015-tvk, mirava-api-00012-7c9, Hosting; views in BigQuery.
- Cloud setup: §5b 09 ✅.
- Contract changes: §7 → addendum (DECISIONS #86–96).
- Open issues: §8 (4 eval checks fail).
### 2026-10-18 12:00 · Phase 4 · ⚠️
- Built: products API (CRUD, screened creatives, signed uploads, audience, understanding, plan, ready, launch), media (screen/Model Armor, audience, attention, traffic, planner, graph), agents/understanding, mind/ad_thought, social/community, engine/media_rt (launch, hoardings, feeds, newspaper, store displays, reviewers, community, baseline ads), BQ views v_exposures/v_site_daily, web Launch Studio + GraphView + PlanCanvas + dock launch + firework + lenses, `make seed-demo`, `make dev` with engine.
- Tests: py (Launch Studio 14 + media 13 incl. geometry, calibration, planner determinism/exclusion, reels ≥70% audience, injection suite, launch→thought/memory/belief, review/community, view totals) + 18 vitest.
- Visual check: 11, 18–23 PASS (+ all earlier gated); 15/16/17/21b REVIEW ok by eye.
- Deployed: world-engine-00012-fpw, mirava-api-00008+ (1 GiB, Model Armor), Hosting; cloud seeded (Pulse 5, Orbit S live; Nova X1 ready).
- Cloud setup: §5b 12 Model Armor ✅, 08 uploads CORS ✅.
- Contract changes: §7 (DECISIONS #77–83).
- Open issues: §8.
- Next session must: see §9.

### 2026-10-18 06:40 · Phase 3 · ⚠️
- Built: mind (MemoryStore retrieval/beliefs/prune, context.build ≤ 900 tok, decision adapter batched 32, reflection), social (gate, sessions, prep, dialogue, debrief, conversation), engine (encounters, governor, social runtime, highlights, Firestore read models), api (thoughts, conversations, memories, highlights), web (profile tabs 4–6, highlights mode, conversation ticker, slowed state), BQ views v_messages/v_conversations.
- Tests: 72 pytest + 15 vitest (marker-fact 200 chats, retrieval isolation, SharePlan typing, transcript bounds, sessions property, governor 3-day sim, engine social day determinism, API privacy filter).
- Visual check: 07/08/09/12 PASS (all earlier gated screens still PASS).
- Deployed: world-engine (social on, real OpenRouter), mirava-api, Hosting.
- Cloud setup: §5b 07 vector index ✅, 00 credit limit (see §9), 10 texts embeddings verified; CORS deferred.
- Contract changes: §7 (DECISIONS #72–75).
- Open issues: §8 (reflection not yet seen live, embedding cost not metered, gate rule-based).
- Next session must: see §9.

### 2026-10-18 02:00 · Phase 2 · ✅
- Built: population (quota sampler, households, relationships, routines, money, phones + hazards, media diet, special agents, Gemini bios, seed memories, `make genesis`); engine (world step, planner, A* movement, events → DuckDB/Pub/Sub, checkpoints, lease + revision handoff, /live, tasks, clock, app); api world/agents/watchlist; web live client, hover card, profile tabs 1–3, People, Watching.
- Tests: 47 pytest + 14 vitest (marginals, determinism 2 days, lease, kill/resume no dup ids, movement on graph, live schemas, API, agents_latest SQL).
- Visual check: 01/02/03/04/05/06/10/32/33 PASS; 13/14 REVIEW ok by eye.
- Deployed: world-engine (always on) + api + Hosting; Scheduler watchdog.
- Cloud setup: §5b 07 db, 08, 09, 10, 05 engine, 16 ✅.
- Contract changes: §7 (DECISIONS #65–71).
- Open issues: §8.
- Next session must: see §9.

### 2026-10-18 00:20 · Phase 1 · ✅
- Built: uv/Makefile tooling, shared (settings, models, OpenRouter/Vertex/Fake gateway, schemas, store/bq/files), api hello, OSM fetch + mapgen (tmj, roadgraph, places, sites, stores, tileset), world/map + site geometry, web shell + globe + Phaser world + guide + visual-test mode, infra (cloudbuild, Dockerfile, firebase.json, setup_gcp.sh).
- Tests: 29 pytest (settings, model guard, gateway shape/retries/cache, DuckDB, mapgen determinism, connectivity, places/sites, OTS geometry) + 5 vitest.
- Visual check: 01-globe, 02-world, 33-guide PASS.
- Deployed: Cloud Run mirava-api + Firebase Hosting (Cloud Build 2098a98e).
- Cloud setup: §5b 00, 01, 02, 03, 04, 05 (api), 06, 07 (emulator) ✅; 15 not needed.
- Contract changes: tmj `lights` layer (§7).
- Open issues: §8 healthz path.
- Next session must: see §9.

<!--
### YYYY-MM-DD HH:MM · Phase N · <status>
- Built: (modules, endpoints, screens)
- Tests: (counts, what's covered)
- Visual check: (table summary; screens still failing and why)
- Deployed: (what, where)
- Cloud setup: (rows ticked in §5b)
- Contract changes: (or "none")
- Open issues: (link §8)
- Next session must: (3 concrete first steps)
-->
