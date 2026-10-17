# 10 · Pub/Sub topics + BigQuery subscriptions (the raw log)

**Needed from:** phase 2. The engine publishes events and texts. Two BigQuery subscriptions write them into **two tables** (one subscription writes to exactly one table):
- `world-events` → `launch_lens.events`
- `world-texts` → `launch_lens.texts`

## 1. Topics
```bash
gcloud pubsub topics create world-events
gcloud pubsub topics create world-texts
```
## 2. Let Pub/Sub write to BigQuery
```bash
PN=$(gcloud projects describe PROJECT_ID --format='value(projectNumber)')
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:service-$PN@gcp-sa-pubsub.iam.gserviceaccount.com" --role=roles/bigquery.dataEditor --condition=None
```
## 3. Subscriptions
The tables must exist first (guide 09). Message JSON fields map to columns by name (INTERFACES §9).
```bash
gcloud pubsub subscriptions create world-events-to-bq --topic=world-events \
  --bigquery-table=PROJECT_ID:launch_lens.events --use-table-schema
gcloud pubsub subscriptions create world-texts-to-bq --topic=world-texts \
  --bigquery-table=PROJECT_ID:launch_lens.texts --use-table-schema
```
If the command is rejected, check the flag names with `gcloud pubsub subscriptions create --help`. Console alternative: ☰ **Pub/Sub → Subscriptions → Create** → Delivery type **Write to BigQuery** → choose the table → **Use table schema**.

**Embeddings:** the `embedding` column is `ARRAY<FLOAT64>`; the engine sends it as a JSON array of numbers. If the subscription rejects arrays in your project, switch `texts` to the BigQuery Storage Write API in `engine/events.py` (setting `TEXT_SINK=bq_write_api`) and keep `world-events` on Pub/Sub.
## 4. Verify with a test message
```bash
gcloud pubsub topics publish world-events --message='{"event_id":"ping:0:0:0","t":0,"day":1,"t_real":"2026-10-17T00:00:00Z","kind":"ping","agent_id":0,"rendered":true,"private":false,"payload":{"ok":true}}'
bq query --use_legacy_sql=false 'SELECT * FROM `PROJECT_ID.launch_lens.events` WHERE kind="ping"'
```
If the row doesn't appear within a minute, open ☰ **Pub/Sub → Subscriptions → world-events-to-bq**; it shows the error (schema mismatch or permission).
