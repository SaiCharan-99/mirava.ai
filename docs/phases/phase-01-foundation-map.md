# Phase 1 — Foundation, globe, Indiranagar map, app shell

**Time box:** ~2.5 h · **Depends on:** nothing · **Specs:** X-01, X-02 (hello deploy), U-01, U-08 (static guide), U-09, W-01, W-02, W-03, W-04, W-10 · **Visual screens:** `01-globe`, `02-world` (shell + panels; canvas hidden), `33-guide`

## Goal
A deployable skeleton:
- The UI shell already matches the mockup at pixel level.
- The **globe intro** flies into a **pixel-art Indiranagar generated from OpenStreetMap**, rendered by Phaser with day/night lighting and the hoarding sites.
- Visual-test mode works.
- The OpenRouter LLM gateway works (fake in tests).
- A hello-world version is deployed (Firebase Hosting + Cloud Run `api`).

## Accounts & cloud setup needed
Before the first step that needs each item, walk me through it with `/gcp-setup` (guides are in `docs/setup/`), unless `PROGRESS.md` §5b already shows it ✅. Keep building locally with fakes while I do the console steps.
- `/gcp-setup 00` — **OpenRouter**: team key into `.env`, models verified
- `/gcp-setup 15` — **OpenStreetMap** extract for Indiranagar (only if the Overpass API is blocked on this machine)
- `/gcp-setup 01` — Google Cloud project, billing, **budget alert**, gcloud + ADC
- `/gcp-setup 02` — APIs, service accounts, roles
- `/gcp-setup 03` — Secret Manager `openrouter-api-key`
- `/gcp-setup 04` — Artifact Registry + Cloud Build
- `/gcp-setup 05` (api section) — Cloud Run `launch-lens-api`
- `/gcp-setup 06` — Firebase Hosting
- `/gcp-setup 07` (emulator section) — Firestore emulator (Java 11+)

## Prompt
```
You are starting Phase 1 of Launch Lens in a fresh session.
Read CLAUDE.md fully, then PROGRESS.md, docs/DECISIONS.md (rows 28+ are the current design) and this file.
Then read: docs/architecture.md §1–§5, §15, §16.6–16.7, §21; docs/INTERFACES.md §1, §2 (world.py), §4.1, §6 (all), §8;
docs/specs.md W-01…W-04, W-10, U-01, U-08, U-09, X-01, X-02; tools/visual/README.md.
Open docs/ui-mockup.html in a browser (live, without ?freeze=1) and look at docs/ui-reference/01-globe.png, 02-world.png, 33-guide.png.

Goal: shell + globe + OSM-generated Indiranagar map + visual-test mode + OpenRouter gateway + hello deploy.
Work through the checklist in order. Walk me through cloud setup with /gcp-setup when needed (see "Accounts & cloud
setup needed"); never create cloud resources without my approval.
Finish with: make test, make lint, acceptance checks, /visual-check 1, then /end-phase. Do not start Phase 2.
```

## Read first
Architecture §3 (principles, Google Cloud usage, model access), §4 (F1), §5 (F2 world), §15 (UI), §21 (repo/build order). INTERFACES §4.1 (map assets), §6. The mockup's map style (`20-map` section of its script: road widths, colours, buildings, metro viaduct, labels) — **look only**.

## Build checklist
### Repo & tooling
- [ ] Monorepo per CLAUDE.md §4; `uv` project, `web/` Vite React TS, Makefile with all targets (stubs where later)
- [ ] `.env.example` → `.env` (git-ignored); `shared/settings.py` (pydantic-settings; `OPENROUTER_API_KEY` masked in repr)
- [ ] `make lint` includes ruff, mypy, eslint, tsc, **gitleaks**

### Shared
- [ ] `shared/models.py`: `MODEL_PRO/FLASH/LITE/EMBED`, overridable via `MODEL_*_ID`; guard test that greps the repo for `gemini-2.5`
- [ ] `shared/llm.py`:
  - `LLMClient` protocol
  - **`OpenRouterClient`** (default): httpx to `OPENROUTER_BASE_URL/chat/completions`; structured output (`response_format` json_schema strict + `provider.require_parameters`); `reasoning.effort`; `usage.include=true` (cost); image parts; `/embeddings` (768-d); retries on 429/5xx; cache by input hash; per-call cost record
  - `VertexClient` (optional)
  - `FakeGemini` (deterministic)
  - `get_llm()`
- [ ] `make llm-smoke` (skips with a message if there's no key); startup check that every `MODEL_*_ID` is listed by `GET /models`
- [ ] `shared/schemas/` — **all** models of INTERFACES §2 and the `Event` envelope (define now, use later); `make types`
- [ ] `shared/time.py` (`fmt(t)` → "Day 23 · Tue 08:40"); `shared/store.py` (Firestore/emulator), `shared/bq.py` (BigQuery/DuckDB), `shared/files.py` (GCS/local)

### Map (W-02 … W-04)
- [ ] `tools/mapgen/fetch_osm.py`: Overpass query for bbox 12.962,77.630,12.984,77.652 (highways, railway, buildings, landuse, amenity, shop, leisure, public_transport). Save to `assets/osm/indiranagar.osm.json` and **commit it**. If Overpass is unreachable, follow `docs/setup/15-openstreetmap.md`
- [ ] `tools/mapgen/build.py`:
  - projection to local metres
  - 8 m tile raster with layers ground / landuse / roads (width by class) / rail (metro viaduct along CMH Road) / buildings (roof styles by type) / decor / labels
  - `roadgraph.json`
  - `places.json` (OSM tags + `config/places_overrides.yaml`: the fictional stores Digital Bazaar, ElectroHub, PhoneWorld, plus the tech park, newspaper stand, bus stops, metro)
  - `sites.json` (~60 hoarding/bus-shelter/metro-panel/façade sites with facings, size, lit, cone, range, rate card)
  - `stores.json`
  - deterministic; `make map`
- [ ] Tileset `assets/tiles/city.png` in the mockup's palette (asphalt, sidewalks, lane marks, roofs, parks, viaduct)
- [ ] `world/map.py`, `world/sites.py` (`ots()` geometry + unit tests: in front / behind / out of range / heading away)
- [ ] OSM attribution string shown on the map and in the Guide

### Web
- [ ] Tokens copied verbatim from the mockup (incl. `--p1…--p6`, `--private`, light theme); fonts via `@fontsource`
- [ ] Shell: header (logo, crumbs, LIVE chip, SIMULATED DATA badge, `header-clock`, `budget-meter`, theme toggle, avatar), sidebar (nav World / Launch Studio / Insights / People / Guide + `world-status` card), routes per INTERFACES §6.1
- [ ] **Globe intro** (`/globe`, first session visit from `/`): `cobe` dotted globe rotating to Bengaluru, pulsing marker, card with stats, **Enter world** (zoom + cross-fade into `/world`), **Skip intro**; no WebGL → straight to World
- [ ] **World page layout** with all regions from the mockup:
  - `world-stage`
  - `world-canvas` (Phaser rendering the Tiled map: camera drag/zoom/fit, minimap, day/night overlay with lit sites and street lights, road and place labels, site boards with facing marks)
  - `world-stats` (static fixture numbers for now)
  - `lens-switch`, `new-product`, `launch-dock` (fixture)
  - `world-side` with the 3 tabs (fixture content)
  - `day-timeline`, `minimap`, `launch-fx` (empty canvas), `profile-drawer` (mounted, closed)
- [ ] Guide page (static, final text from the mockup)
- [ ] Visual-test mode: `node tools/visual/extract-fixtures.mjs` → `web/src/visual-fixtures/mockup-fixtures.json`; freeze at Day 23 · Tue 08:40; `window.__ll` (stubs OK where marked in PROGRESS); hide nothing that is not `mockup-only`

### Infra & deploy
- [ ] `infra/cloudbuild.yaml` (api image → Artifact Registry → Cloud Run with `--set-secrets=OPENROUTER_API_KEY=openrouter-api-key:latest`; web → Firebase Hosting); `firebase.json` with the `/api/**` rewrite
- [ ] `infra/setup_gcp.sh` mirrors `docs/setup/02`–`10` (**print, don't run**)
- [ ] Deployed hello: Hosting serves the shell; `/api/healthz` OK (after my approval)

## Tests
Unit: settings, models guard, FakeGemini determinism, OpenRouterClient request shape (mocked httpx), DuckDB shim, mapgen determinism (same hash twice), road graph connectivity, site geometry, places validation.

## Visual check
`/visual-check 1` → gated `01-globe`, `02-world`, `33-guide` PASS.

## Acceptance checks
1. `make map` twice → identical outputs. Every road node is reachable.
2. Globe → Enter world → the Indiranagar map is visible with labels for 100 Feet Road and CMH Road. Night lighting works with `__ll.setTime(21.5)`.
3. `grep -r "gemini-2.5" --include=*.py --include=*.ts .` finds nothing outside the guard test.
4. `make llm-smoke` passes with the real key (or is skipped with a clear message if the key is missing).
5. The deployed URL shows the shell; `/api/healthz` is 200.

## Out of scope
Agents, engine, memory, products (later phases).

## Handoff (fill in PROGRESS.md §5, §5b, §6, §9)
GCP project/region; URLs; map stats (tiles, nodes, edges, #places, #sites, #stores); OSM extract date; which `__ll` hooks are stubs; any style differences in the map versus the mockup.
