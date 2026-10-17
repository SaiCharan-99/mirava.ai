# 05 · Cloud Run — `api` and the always-on `world-engine`

**Needed from:** phase 1 (`launch-lens-api`), phase 2 (`world-engine`).

## 1. API service (phase 1)
```bash
gcloud run deploy launch-lens-api \
  --image=asia-south1-docker.pkg.dev/PROJECT_ID/launch-lens/api:latest \
  --region=asia-south1 --service-account=ll-api@PROJECT_ID.iam.gserviceaccount.com \
  --set-secrets=OPENROUTER_API_KEY=openrouter-api-key:latest \
  --set-env-vars=ENV=cloud,LLM_BACKEND=openrouter,DECISION_BACKEND=openrouter,BQ_BACKEND=bigquery,GCP_PROJECT_ID=PROJECT_ID,INTERACTIVE_CAP_USD=5 \
  --allow-unauthenticated --min-instances=0 --max-instances=5
curl $(gcloud run services describe launch-lens-api --region=asia-south1 --format='value(status.url)')/healthz
```
The service uses `--allow-unauthenticated` because the demo is public. Firebase Hosting proxies `/api/**` to it (guide 06).

## 2. The always-on world engine (phase 2)
This is the service that **is** the world. It must run all the time, even with no visitors:
- **exactly one instance**: min = max = 1
- **CPU always allocated** (`--no-cpu-throttling`), so the background loop keeps running between requests
- **long timeout and session affinity**, for the `/live` WebSocket (clients reconnect after the 60-minute limit)
```bash
gcloud run deploy world-engine \
  --image=asia-south1-docker.pkg.dev/PROJECT_ID/launch-lens/world-engine:latest \
  --region=asia-south1 --service-account=ll-engine@PROJECT_ID.iam.gserviceaccount.com \
  --set-secrets=OPENROUTER_API_KEY=openrouter-api-key:latest \
  --set-env-vars=ENV=cloud,LLM_BACKEND=openrouter,DECISION_BACKEND=openrouter,EVENT_SINK=pubsub,GCP_PROJECT_ID=PROJECT_ID,WORLD_SECONDS_PER_SIM_DAY=3600,DAILY_CAP_USD=15 \
  --min-instances=1 --max-instances=1 --no-cpu-throttling --cpu=2 --memory=4Gi \
  --timeout=3600 --session-affinity --allow-unauthenticated
ENGINE=$(gcloud run services describe world-engine --region=asia-south1 --format='value(status.url)')
curl $ENGINE/healthz
```
Then give `ll-api` permission to send commands (guide 02 §3, last command), and set `ENGINE_URL=$ENGINE` on `launch-lens-api`:
```bash
gcloud run services update launch-lens-api --region=asia-south1 --update-env-vars=ENGINE_URL=$ENGINE
```
**Why it's safe to restart:**
- The engine checkpoints every sim hour (2.5 real minutes) and resumes from the last checkpoint.
- A Firestore lease guarantees a single writer, even when a new revision overlaps the old one.
- Cloud Scheduler (guide 16) pings `/healthz`.

**Cost:** one instance with CPU always allocated (2 vCPU, 4 GiB) runs all month. Check the current Cloud Run pricing page; free-trial or hackathon credits cover it. After the event, pause the world with `curl -X POST $ENGINE/commands -d '{"type":"pause"}'` (with an identity token), or set `--min-instances=0`.

## 3. Verify & record
- `gcloud run services list --region=asia-south1` shows both services.
- `gcloud run services describe world-engine --region=asia-south1 --format='value(spec.template.metadata.annotations)'` shows `minScale: 1`, `maxScale: 1` and the CPU throttling annotation set to false.
- Leave the browser closed for 10 minutes, then check that `GET $ENGINE/healthz` reports a sim time that has moved on by ~4 sim hours.
- Record both URLs in PROGRESS.md §5.
