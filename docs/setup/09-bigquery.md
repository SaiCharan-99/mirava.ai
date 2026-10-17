# 09 · BigQuery

**Needed from:** phase 2 (dataset, `events`, `texts`), phase 5 (views, analyst account, vector search).

## 1. Dataset (same region as the app)
Console: ☰ **BigQuery → Studio** → your project ⋮ → **Create dataset** → id `launch_lens`, location **asia-south1**.
```bash
bq --location=asia-south1 mk --dataset PROJECT_ID:launch_lens
```
## 2. Tables (phase 2)
`make bq-init` creates them from `infra/bigquery/*.json` (INTERFACES §9):
- **`events`**: every event, integer-range partitioned on `day`, clustered by `kind, product_id, agent_id`
- **`texts`**: every thought, message, post, review and summary, with an `embedding` column

Pub/Sub writes into both (guide 10).
## 3. Public datasets (population priors, phase 2)
1. In BigQuery Studio, click **+ Add → Star a project by name** → `bigquery-public-data`.
2. Find the World Bank WDI and the Census Bureau International Database tables.
3. Copy the exact table names into `config/markets/indiranagar.yaml` sources. Claude Code caches the values it needs.
## 4. Views + analyst account (phase 5)
```bash
make bq-views         # creates agents_latest, beliefs_latest, v_site_daily, v_messages, … (infra/bigquery/views/*.sql)
# let ll-api act as the read-only analyst for Insights SQL
gcloud iam service-accounts add-iam-policy-binding ll-analyst-ro@PROJECT_ID.iam.gserviceaccount.com \
  --member="serviceAccount:ll-api@PROJECT_ID.iam.gserviceaccount.com" --role=roles/iam.serviceAccountTokenCreator
```
## 5. Vector search check (phase 5)
```sql
SELECT base.text, distance
FROM VECTOR_SEARCH(TABLE `PROJECT_ID.launch_lens.texts`, 'embedding',
  (SELECT embedding FROM `PROJECT_ID.launch_lens.texts` WHERE kind='thought' LIMIT 1), top_k => 5, distance_type => 'COSINE');
```
Create a vector index once `texts` has more than 5,000 rows:
```sql
CREATE VECTOR INDEX texts_embedding_idx ON `PROJECT_ID.launch_lens.texts`(embedding)
OPTIONS(index_type='IVF', distance_type='COSINE');
```
## 6. Costs
Queries are billed by bytes scanned, so Insights always filters on `day` (the partition) and sets `maximum_bytes_billed`.
## 7. Verify
```bash
bq ls PROJECT_ID:launch_lens
bq query --use_legacy_sql=false 'SELECT kind, COUNT(*) n FROM `PROJECT_ID.launch_lens.events` GROUP BY kind ORDER BY n DESC'
```
