# Launch Lens — Tech Stack v3 (Always-on Agent World)

*Version 3.0 · 17 Oct 2026 · Companion to `docs/architecture.md` v3. If anything here conflicts with architecture.md, architecture.md wins.*

## 0. Setting up accounts
Every Google Cloud service, OpenRouter and the OpenStreetMap extract has a step-by-step guide in `docs/setup/` (index: `docs/setup/README.md`). The first time a phase needs a service, Claude Code walks you through it with `/gcp-setup <guide>`.

## 1. At a glance

| Layer | Choice | Used for | Phase |
|---|---|---|---|
| Web app | React 18 + Vite + TypeScript, React Router, TanStack Query, Zustand, Tailwind | All pages | 1 |
| Globe intro | **`cobe`** (MIT, WebGL dotted globe) | First-visit intro and fly-in | 1 |
| World rendering | **Phaser 3** (WebGL) inside React; map generated into **Tiled** (`.tmj`) from **OpenStreetMap** | Live Indiranagar city, sprites, lenses, cones, firework launch | 1–4 |
| Map generation | Python `tools/mapgen` (Overpass API → projection → raster tiles → road graph, places, sites) | Real streets, hoarding sites | 1 |
| Charts | Apache ECharts | Insights dashboards, assistant charts | 5 |
| Graph view | **d3-force + canvas** (`react-force-graph-2d`), Obsidian-style | Product knowledge graph | 4 |
| Fonts | Inter + JetBrains Mono via `@fontsource` | Pixel-stable UI | 1 |
| Backend | Python 3.12, FastAPI, pydantic v2, `uv` | `api` and `world-engine` | 1 |
| World engine | asyncio + NumPy; A* on road graph; msgpack + zstd checkpoints | Always-on world loop, `/live` WebSocket | 2 |
| Agents framework | **Google ADK** | Insights assistant, salesperson, interviewer, understanding | 4–5 |
| LLMs | **Gemini 3 via OpenRouter** (default, team key) or **Vertex AI** (`LLM_BACKEND=vertex`) | See §2 | 1–6 |
| Decision model | Gemini 3.5 Flash-Lite via OpenRouter (typed, batched) | talk?, share?, speak?, post?, consider, purchase, poll | 3–5 |
| Always-on compute | **Cloud Run service** `world-engine`: min = max = 1, CPU always allocated, session affinity | The world never stops | 2 |
| API | **Cloud Run service** `api` (scales 0–5) | REST, uploads, commands, Insights | 1 |
| Watchdog | **Cloud Scheduler** → `GET /healthz` every 5 min | Restart if the loop stalls | 2 |
| Events | **Pub/Sub** `world-events`, `world-texts` → **BigQuery subscriptions** | Raw log without custom ingestion code | 2–3 |
| Operational DB | **Firestore** (Native) incl. **vector search** | Agents, episodic memories, beliefs, products, sites, stores, community, lease | 2–5 |
| Analytics | **BigQuery** (+ `VECTOR_SEARCH`, views) | Raw log, texts, Insights SQL, hoarding metrics, likely-buyer scoring | 2–5 |
| Files | **Cloud Storage** | Creatives, map assets, checkpoints, highlights, exports | 1–4 |
| Safety | **Model Armor** | Uploaded content and Insights questions | 4–5 |
| Hosting | **Firebase Hosting** (web, `/api/**` rewrite to Cloud Run) | Public demo URL | 1 |
| Ops | Secret Manager, IAM, Cloud Logging, Monitoring, Trace, Error Reporting, Budgets | Least privilege & observability | 1, 6 |
| Delivery | Cloud Build → Artifact Registry | CI/CD | 1 |
| Local dev | DuckDB (BigQuery shim), Firestore emulator, local disk (GCS shim), FakeGemini, fast clock | Fast, free, deterministic | 1 |
| UI verification | Playwright + pixelmatch (`tools/visual`), Playwright MCP, Claude in Chrome | Pixel-level match to the mockup | 1–6 |
| Scale (V1) | Area-sharded engines, Memorystore, GKE Autopilot, Bigtable, Agent Engine Memory Bank (evaluate) | 10k → 100k agents | V1 |

## 2. Gemini models (Gemini 3 only; never `gemini-2.5-*`)

Accessed through **OpenRouter** with the team's API key (default) or Vertex AI. Ids live **only** in `shared/models.py` (overridable by env) and are verified at startup.

| Constant | OpenRouter id | Standard price per M tokens (in / out) | Used for |
|---|---|---|---|
| `MODEL_PRO` | `google/gemini-3.1-pro-preview` | $2.00 / $12.00 | Insights assistant, claim risk, likely-buyer explanations |
| `MODEL_FLASH` | `google/gemini-3.6-flash` | $0.75 / $3.75 | Product dialogues, creative understanding (images), personas, reviews, interviews, plan reasons |
| `MODEL_LITE` | `google/gemini-3.5-flash-lite` | $0.30 / $2.50 | Ad thoughts, private prep/debrief, social dialogues, store turns, decisions, reflection, community |
| `MODEL_EMBED` | `google/gemini-embedding-001` | low | Episodic memory + texts (768-d) |

*Prices were checked on OpenRouter on 17 Oct 2026. Flex endpoints are about half price. Re-check before launch.*

**Endpoints:**
- chat: `https://openrouter.ai/api/v1/chat/completions`. Structured output via `response_format` json_schema + `provider.require_parameters=true`; `reasoning.effort` low for engine calls; `usage.include=true` for cost.
- embeddings: `https://openrouter.ai/api/v1/embeddings`
- model list: `https://openrouter.ai/api/v1/models`

ADK uses them via LiteLLM (`openrouter/<id>`). The key is in `.env` locally and in Secret Manager (`openrouter-api-key`) in the cloud. Setup: `docs/setup/00-openrouter.md`.

## 3. Cost levers
- Budget governor ($15/day world + $5/day interactive) with priority classes and time slow-down.
- Attention model before any model call; thoughts only on notice.
- 3-step chats: cheap private steps, one dialogue call; Flash only for product talk.
- Decisions batched 32 per call.
- Persona-card prompt caching; result cache by input hash.
- Low reasoning effort and tight `max_tokens`.
- Flex endpoints when available.
- Unrendered fallbacks keep the world coherent at zero model cost.

## 4. Verify before building
- OpenRouter ids still listed, structured output supported, prices.
- Cloud Run always-on settings (`--no-cpu-throttling`, min/max instances 1) and WebSocket timeout (set `--timeout=3600`; clients reconnect).
- Firestore vector index limits (768-d OK).
- BigQuery subscription JSON → `ARRAY<FLOAT64>` mapping for embeddings (else send embeddings via the BigQuery Storage Write API).
- BigQuery `VECTOR_SEARCH` availability in the dataset region.
- Overpass API reachable (else the manual OSM export guide).
- Model Armor location.
