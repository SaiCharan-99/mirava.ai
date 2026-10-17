# 02 · Enable APIs and create service accounts (IAM)

**Needed from:** phase 1. Each service gets its own identity with only the roles it needs.

## 1. Enable APIs
Console: ☰ **APIs & Services → Library** → search each and **Enable**. Or:
```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com bigquery.googleapis.com bigquerystorage.googleapis.com storage.googleapis.com \
  pubsub.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com logging.googleapis.com monitoring.googleapis.com \
  cloudtrace.googleapis.com firebase.googleapis.com firebasehosting.googleapis.com modelarmor.googleapis.com
# optional, only for LLM_BACKEND=vertex:
gcloud services enable aiplatform.googleapis.com
```
Verify: `gcloud services list --enabled | grep -E "run|firestore|bigquery|pubsub|scheduler|secretmanager"`.

## 2. Service accounts
Console: ☰ **IAM & Admin → Service accounts → Create service account**. Or:
```bash
for sa in ll-api ll-engine ll-analyst-ro ll-scheduler; do
  gcloud iam service-accounts create $sa --display-name="Launch Lens $sa"; done
```
| Account | Used by |
|---|---|
| `ll-api` | Cloud Run `launch-lens-api` (REST, uploads, commands, Insights tools except SQL) |
| `ll-engine` | Cloud Run `world-engine` (the only writer of world state) |
| `ll-analyst-ro` | Insights `run_sql` / `semantic_search` (read-only on views) — impersonated by `ll-api` |
| `ll-scheduler` | Cloud Scheduler watchdog (optional identity) |

## 3. Roles (project level for the hackathon; tighten to resource level later)
```bash
P=PROJECT_ID
grant(){ gcloud projects add-iam-policy-binding $P --member="serviceAccount:$1@$P.iam.gserviceaccount.com" --role="$2" --condition=None >/dev/null; }
# api: reads Firestore/BigQuery, writes uploads, signs URLs, calls Model Armor, impersonates analyst
for r in roles/datastore.user roles/storage.objectAdmin roles/bigquery.jobUser roles/secretmanager.secretAccessor roles/iam.serviceAccountTokenCreator roles/modelarmor.user roles/logging.logWriter roles/cloudtrace.agent; do grant ll-api $r; done
# engine: the world's single writer
for r in roles/datastore.user roles/storage.objectAdmin roles/pubsub.publisher roles/bigquery.dataEditor roles/bigquery.jobUser roles/secretmanager.secretAccessor roles/logging.logWriter roles/cloudtrace.agent roles/monitoring.metricWriter; do grant ll-engine $r; done
# analyst (read-only)
for r in roles/bigquery.dataViewer roles/bigquery.jobUser; do grant ll-analyst-ro $r; done
# api may call the engine's /commands with an identity token
gcloud run services add-iam-policy-binding world-engine --region=asia-south1 \
  --member="serviceAccount:ll-api@$P.iam.gserviceaccount.com" --role=roles/run.invoker   # run after world-engine exists (phase 2)
```
PowerShell: run the commands one by one (no bash loops), or use Git Bash.

The engine is public for `/live` and `/healthz`. `/commands` verifies the Google identity token of `ll-api` inside the app.

## 4. Verify
```bash
gcloud projects get-iam-policy PROJECT_ID --flatten="bindings[].members" \
  --filter="bindings.members:ll-" --format="table(bindings.role,bindings.members)"
```
## 5. Record
PROGRESS.md §5b: APIs ✅, service accounts ✅ (list).
