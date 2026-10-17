# PROGRESS.md — mirava.ai build log (v3 · always-on agent world)

Living document. Every Claude Code session reads it first and updates it last (`/end-phase`). Keep it accurate and short. Rows 28+ of `docs/DECISIONS.md` describe the current (v3) design.

## 1. Current status
| Field | Value |
|---|---|
| Current phase | 2 — Population & the always-on world engine (not started) |
| Phase status | Phase 1 ✅ done · phase 2 ⬜ |
| Repo green (`make test` + `make lint`) | ✅ 2026-10-18 (29 py + 5 web tests; ruff, mypy, eslint, tsc, gitleaks clean) |
| Last session | 2026-10-17 · phase 1 |
| Builder | Sai Charan (Claude Code) |
| Deadline | 18 Oct 2026 |

## 2. Phase tracker
| # | Phase | Status | Date | Visual check | Notes |
|---|---|---|---|---|---|
| 1 | Foundation, globe, Indiranagar map, app shell | ✅ | 2026-10-18 | 01/02/33 PASS | hello deploy live |
| 2 | Population & the always-on world engine | ⬜ | | | |
| 3 | Memory, think/speak conversations, governor, highlights | ⬜ | | | |
| 4 | Launch Studio, channels and attention | ⬜ | | | |
| 5 | Stores, buying and Insights | ⬜ | | | |
| 6 | Hardening, deploy, demo, submission | ⬜ | | | |
Legend: ⬜ not started · 🟨 in progress · ✅ done · ⚠️ done with open issues

## 3. Spec coverage (DEMO + STRETCH; tick only when "done when" is met)
| Group | Phase | Specs |
|---|---|---|
| World & time | 1, 2, 3 | ☑ W-01 ☑ W-02 ☑ W-03 ☑ W-04 ☐ W-05 ☐ W-06 ☐ W-07 ☐ W-08 ☐ W-09 ☑ W-10 |
| Population | 2, 4 | ☐ P-01 ☐ P-02 ☐ P-03 ☐ P-04 ☐ P-05 ☐ P-06 ☐ P-07 (stretch) ☐ P-08 |
| Engine | 2, 3 | ☐ E-01 ☐ E-02 ☐ E-03 ☐ E-04 ☐ E-05 ☐ E-06 ☐ E-07 |
| Memory | 3 | ☐ M-01 ☐ M-02 ☐ M-03 ☐ M-04 ☐ M-05 ☐ M-06 ☐ M-07 |
| Attention | 4 | ☐ A-01 ☐ A-02 ☐ A-03 ☐ A-04 ☐ A-05 ☐ A-06 |
| Channels | 3, 4 | ☐ C-01 ☐ C-02 ☐ C-03 ☐ C-04 ☐ C-05 ☐ C-06 ☐ C-07 ☐ C-08 |
| Talk | 3, 5 | ☐ T-01 ☐ T-02 ☐ T-03 ☐ T-04 ☐ T-05 ☐ T-06 ☐ T-07 |
| Shopping | 5 | ☐ S-01 ☐ S-02 ☐ S-03 ☐ S-04 ☐ S-05 ☐ S-06 |
| Launch Studio | 4 | ☐ L-01 ☐ L-02 ☐ L-03 ☐ L-04 ☐ L-05 ☐ L-06 ☐ L-07 ☐ L-08 |
| Insights | 5 | ☐ I-01 ☐ I-02 ☐ I-03 ☐ I-04 ☐ I-05 ☐ I-06 ☐ I-07 ☐ I-08 ☐ I-09 |
| UI | 1, 1, 6, 1–4, 1–6, 2, 2–3, 4, 5 | ☑ U-01 ☐ U-02 ☐ U-03 ☐ U-04 ☐ U-05 ☐ U-06 ☐ U-07 ☑ U-08 ☐ U-09 |
| Platform | 1, 1–2, 4, 6, 6 | ☑ X-01 ☐ X-02 ☐ X-03 ☐ X-04 ☐ X-05 ☐ X-06 |

## 4. Visual check status (`tools/visual`, latest run)
| Screen | Phase | Layout | Edges | Geometry | Result |
|---|---|---|---|---|---|
| 01-globe | 1 | 0.5% | 0.1% | ok | PASS |
| 02-world | 1 | 1.5% | 0.2% | ok | PASS |
| 03-world-hover | 2 |  | | | |
| 04-profile-overview | 2 |  | | | |
| 05-profile-relations | 2 |  | | | |
| 06-profile-possessions | 2 |  | | | |
| 07-profile-thoughts | 3 |  | | | |
| 08-profile-conversations | 3 |  | | | |
| 09-profile-memory | 3 |  | | | |
| 10-world-watching | 2 |  | | | |
| 11-world-products | 4 |  | | | |
| 12-world-highlights | 3 |  | | | |
| 13-world-look | 2 | review | | | |
| 14-world-night | 2 | review | | | |
| 15-world-lens-aware | 4 | review | | | |
| 16-world-lens-hoardings | 4 | review | | | |
| 17-world-launch-fx | 4 | review | | | |
| 18-launch-list | 4 |  | | | |
| 19-launch-details | 4 |  | | | |
| 20-launch-content | 4 |  | | | |
| 21-launch-understand | 4 |  | | | |
| 21b-launch-graph | 4 | review | | | |
| 22-launch-plan | 4 |  | | | |
| 23-launch-ready | 4 |  | | | |
| 24-insights-ask | 5 |  | | | |
| 25-insights-overview | 5 |  | | | |
| 26-insights-sources | 5 |  | | | |
| 27-insights-hoardings | 5 |  | | | |
| 28-insights-segments | 5 |  | | | |
| 29-insights-conversations | 5 |  | | | |
| 30-insights-polls | 5 |  | | | |
| 31-insights-interview | 5 |  | | | |
| 32-people | 2 |  | | | |
| 33-guide | 1 | 1.8% | 0.2% | ok | PASS |
| 34-people-light | 6 |  | | | |

## 5. Environment
| Item | Value |
|---|---|
| GCP project / region | mirava-ai-hack (760833706192) / asia-south1 |
| Web URL (Firebase Hosting) | https://mirava-ai-hack.web.app |
| API URL (Cloud Run `mirava-api`) | https://mirava-api-kfh7v3hvjq-el.a.run.app (public path: https://mirava-ai-hack.web.app/api/healthz) |
| world-engine URL / revision | _phase 2_ |
| OSM extract date / map stats | Overpass 2026-10-17T17:07Z · 299×305 tiles (8 m) · 3,501 nodes / 4,455 edges (all reachable) · 12,179 places · 60 sites · 4 stores |
| Genesis version / seed | _phase 2_ |
| Live products (ids, launched at) | _phase 4+_ |
| Demo snapshot name | _phase 6_ |

## 5b. Accounts & cloud setup status
Filled in by `/gcp-setup` (guides in `docs/setup/`). Never paste keys or secrets here — only names and ✅.
| # | Item | Needed by phase | Status | Date | Notes (names, region — no secrets) |
|---|---|---|---|---|---|
| 00 | OpenRouter account, API key in `.env`, models verified, credit limit | 1 | ✅ | 2026-10-17 | key in .env only; 4 model ids listed; llm-smoke OK (structured + 768-d embedding) |
| 15 | OpenStreetMap extract for Indiranagar (only if Overpass is blocked) | 1 | not needed | 2026-10-17 | Overpass reachable; extract committed |
| 01 | GCP project, billing, budget alert, gcloud + ADC | 1 | ✅ | 2026-10-17 | project mirava-ai-hack (#760833706192), free trial, billing ✅, ADC ✅ (saicharangobburu@gmail.com); budget alert set in console by user |
| 02 | APIs enabled, service accounts + roles | 1 | ✅ | 2026-10-17 | 19 APIs (+billingbudgets); SAs mirava-api, mirava-engine, mirava-analyst-ro, mirava-scheduler; roles per guide 02 (run.invoker on world-engine in phase 2) |
| 03 | Secret Manager `openrouter-api-key` | 1 | ✅ | 2026-10-17 | version 1 = dev key from .env (rotate to a prod key in phase 6); accessor: mirava-api, mirava-engine |
| 04 | Artifact Registry `mirava`, Cloud Build permissions | 1 | ✅ | 2026-10-17 | repo asia-south1/mirava; builds run as 760833706192-compute SA (deploy roles granted, also to legacy cloudbuild SA) |
| 05 | Cloud Run `mirava-api` | 1 | ✅ | 2026-10-18 | asia-south1, SA mirava-api, secret mounted, min 0 / max 5; deployed by Cloud Build 2098a98e (SUCCESS) |
| 06 | Firebase Hosting | 1 | ✅ | 2026-10-18 | Firebase added to mirava-ai-hack (Blaze/free trial); site mirava-ai-hack.web.app; .firebaserc committed |
| 07 | Firestore emulator (local) | 1 | ✅ | 2026-10-17 | 127.0.0.1:8080; needs Java 21+ (Temurin 25 JRE installed) |
| 07 | Firestore database `asia-south1` | 2 | ⬜ | | |
| 08 | Cloud Storage buckets + CORS | 2 | ⬜ | | |
| 09 | BigQuery dataset `launch_lens` (+ public data priors) | 2 | ⬜ | | |
| 10 | Pub/Sub `world-events`, `world-texts` + BigQuery subscriptions | 2 | ⬜ | | |
| 05 | Cloud Run `world-engine` (always-on, min=max=1) | 2 | ⬜ | | |
| 16 | Cloud Scheduler watchdog | 2 | ⬜ | | |
| 07 | Firestore vector index `memories` | 3 | ⬜ | | |
| 12 | Model Armor template | 4 | ⬜ | | |
| 09 | BigQuery views + `ll-analyst-ro` + VECTOR_SEARCH check | 5 | ⬜ | | |
| 13 | Monitoring dashboard + alerts | 6 | ⬜ | | |
| 14 | Vertex AI (only if `LLM_BACKEND=vertex`) | — | skipped | | |

## 6. How to run (keep current — copy-paste ready)
```bash
# Windows: Git Bash. One-time: source .devpath.sh   (adds make + gitleaks to PATH in this shell)
uv sync && (cd web && npm install) && (cd tools/visual && npm ci && npx playwright install chromium)
# npm install must run from PowerShell on this PC (stray quote in Windows PATH breaks cmd.exe from Git Bash)
make dev          # Firestore emulator (Java 21+ on PATH) + api :8000 + web :5173
make test && make lint
make map          # regenerate map assets (deterministic)
LLM_BACKEND=openrouter make llm-smoke
make visual PHASE=1   # app must be running on :5173
make deploy       # Cloud Build → Cloud Run mirava-api + Firebase Hosting (project mirava-ai-hack)
```
Visual-test URL: http://localhost:5173/world?visualTest=1 · Live: https://mirava-ai-hack.web.app

## 7. Contract changes (to docs/INTERFACES.md)
- [phase 1] `indiranagar.tmj` gains object layer `lights` and documents `labels` object types (INTERFACES §4.1) — needed for night lighting — DECISIONS #60.

## 8. Known issues / tech debt
- [phase 1] [minor] Cloud Run's front end answers `GET /healthz` itself with 404 on the direct run.app URL; `/api/healthz` works. **world-engine (phase 2) needs a different health path** (e.g. `/health` or `/api/healthz`) or the Scheduler watchdog will 404 — api/main.py, INTERFACES §5 — suggested fix: add `/health` and update the contract.

## 9. Handoff notes for the next session
**Phase 1 handoff**
- GCP project `mirava-ai-hack` (760833706192), region asia-south1. Web https://mirava-ai-hack.web.app · API https://mirava-api-kfh7v3hvjq-el.a.run.app (use `/api/healthz` via Hosting — direct `/healthz` is 404 on run.app, see §8).
- Map stats: §5. OSM extract 2026-10-17, committed (`assets/osm/indiranagar.osm.json`).
- `__ll` hooks: real = featured, lens, setTime, overview. **Stubs** = focus (centres on metro), hoverAgent, openAgent, highlights, launchFx, graphSelect, graphHover.
- World page shows mockup fixtures (stats, ticker, products, dock) in every mode until `/live` exists (DECISIONS #63).
- Map vs mockup style: real OSM streets (organic, not a grid); boards drawn 3× life size; buildings are tile-raster (no shadows); Old Airport Road outside bbox (no label); night glow from tmj `lights` layer.
- Names: everything new uses mirava-* (DECISIONS #55–56); setup guides still say launch-lens.
- Local: Firestore emulator on 127.0.0.1:8080 needs Java 25 JRE (installed at C:\Program Files\Eclipse Adoptium\jre-25…) first on PATH.

**Next session (phase 2) must:**
1. `/start-phase 2`; run `make test`/`make lint` first.
2. Pick a health path for world-engine that Cloud Run doesn't intercept (§8) and update INTERFACES §5.
3. Walk through `/gcp-setup` 07 (cloud Firestore), 08, 09, 10, 05 (world-engine), 16 before deploying the engine.

## 10. Session log (newest first)
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
