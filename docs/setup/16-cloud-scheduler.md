# 16 · Cloud Scheduler watchdog for the world engine

**Needed from:** phase 2 (after `world-engine` is deployed).

**What and why:** Cloud Scheduler calls the engine's `/healthz` every 5 minutes. If the world loop hasn't ticked for 2 minutes, `/healthz` returns 500 and Cloud Run restarts the container, which resumes from the last checkpoint. It also gives you a clear "is the world alive?" history. **Cost:** a few cents a month; the first jobs per billing account are free.

## Console
1. ☰ **Cloud Scheduler → Create job**.
2. Fill in the job:
   - Name: `world-engine-watchdog`
   - Region: `asia-south1` (if it isn't offered, use `asia-southeast1`)
   - Frequency: `*/5 * * * *`
   - Timezone: Asia/Kolkata
3. Target type **HTTP**:
   - URL: `ENGINE_URL/healthz`
   - Method: GET
4. Optionally, under **Auth header**, add an OIDC token with service account `ll-scheduler@PROJECT_ID.iam.gserviceaccount.com` and audience `ENGINE_URL`.
5. Retry config: max retries 1.

## CLI
```bash
ENGINE=$(gcloud run services describe world-engine --region=asia-south1 --format='value(status.url)')
gcloud scheduler jobs create http world-engine-watchdog --location=asia-south1 \
  --schedule="*/5 * * * *" --time-zone="Asia/Kolkata" --uri="$ENGINE/healthz" --http-method=GET \
  --oidc-service-account-email=ll-scheduler@PROJECT_ID.iam.gserviceaccount.com --oidc-token-audience="$ENGINE"
```
## Verify
```bash
gcloud scheduler jobs run world-engine-watchdog --location=asia-south1
gcloud scheduler jobs describe world-engine-watchdog --location=asia-south1 --format='value(lastAttemptTime,status)'
```
In ☰ **Cloud Scheduler**, the job shows "Success". Record it in PROGRESS.md §5b.
