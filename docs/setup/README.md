# Setup guides — accounts, data and Google Cloud services

Claude Code must **walk you through these guides** (`/gcp-setup <guide>`) the first time a phase needs a service. For each one it:
1. explains each step
2. waits for you to finish the console steps
3. runs `gcloud` commands only after you approve them
4. verifies the result
5. records it in `PROGRESS.md` §5b

Secrets are never printed or committed.

Consoles change. If a menu name differs, look for the same words in the left navigation, or press "/" to use the console search bar and type the service name.

## Order and when each is needed
| # | Guide | Needed from | What it's for in Launch Lens |
|---|---|---|---|
| 00 | [OpenRouter account & API key](00-openrouter.md) | Phase 1 | All Gemini calls + decision model |
| 15 | [OpenStreetMap extract (Indiranagar)](15-openstreetmap.md) | Phase 1 (only if Overpass is blocked) | Real streets for the city map |
| 01 | [Google Cloud account, project, billing, gcloud](01-gcp-account-project-billing.md) | Phase 1 | Everything on Google Cloud |
| 02 | [Enable APIs & IAM service accounts](02-apis-and-iam.md) | Phase 1 | Least-privilege identities |
| 03 | [Secret Manager](03-secret-manager.md) | Phase 1 | `openrouter-api-key` for Cloud Run |
| 04 | [Artifact Registry & Cloud Build](04-artifact-registry-cloud-build.md) | Phase 1 | Container images, CI/CD |
| 05 | [Cloud Run: api + always-on world-engine](05-cloud-run.md) | Phase 1 (api) · 2 (world-engine) | REST API; the world that never stops |
| 06 | [Firebase Hosting](06-firebase-hosting.md) | Phase 1 | Public web app URL |
| 07 | [Firestore (+ emulator, vector index)](07-firestore.md) | Phase 1 (emulator) · 2 (cloud) · 3 (vector index) | Agents, memories, beliefs, products, lease |
| 08 | [Cloud Storage](08-cloud-storage.md) | Phase 2 | Genesis, checkpoints, highlights, creatives |
| 09 | [BigQuery](09-bigquery.md) | Phase 2 (dataset) · 5 (views, analyst account) | Raw log, texts, Insights SQL + vector search |
| 10 | [Pub/Sub + BigQuery subscriptions](10-pubsub-bigquery.md) | Phase 2 | `world-events` → `events`, `world-texts` → `texts` |
| 16 | [Cloud Scheduler watchdog](16-cloud-scheduler.md) | Phase 2 | Pings the engine every 5 min |
| 12 | [Model Armor](12-model-armor.md) | Phase 4 | Prompt-injection screening |
| 13 | [Logging, Monitoring, budgets](13-observability-budgets.md) | Phase 1 (budget) · 6 (dashboards) | Health, cost control |
| 14 | [Vertex AI (optional)](14-vertex-ai-optional.md) | Only if `LLM_BACKEND=vertex` | Gemini on Google Cloud credits |

(Guide 11 from v2, Cloud Workflows, is no longer used: the world runs continuously instead of as batch runs.)

## Conventions used in all guides
- `PROJECT_ID` is your GCP project id (e.g. `launch-lens-hack`). Get `PROJECT_NUMBER` with `gcloud projects describe PROJECT_ID --format='value(projectNumber)'`.
- `REGION=asia-south1` (Mumbai) for everything.
- Commands are written for bash (macOS/Linux/Git Bash). Windows PowerShell notes are given where different.
