# 08 · Cloud Storage

**Needed from:** phase 2 (genesis, checkpoints, highlights), phase 4 (creative uploads), phase 6 (exports, demo snapshot).

Bucket names are **globally unique**, so prefix them with the project id and put the names in `.env`.
```bash
P=PROJECT_ID
for b in uploads worlds exports; do
  gcloud storage buckets create gs://$P-ll-$b --location=asia-south1 --uniform-bucket-level-access; done
gcloud storage buckets update gs://$P-ll-worlds --versioning        # keep old checkpoints/genesis recoverable
```
`.env`: `GCS_BUCKET_UPLOADS=$P-ll-uploads`, `GCS_BUCKET_WORLDS=$P-ll-worlds`, `GCS_BUCKET_EXPORTS=$P-ll-exports`.

## Browser uploads (signed URLs) need CORS
```bash
cat > /tmp/cors.json <<'J'
[{"origin":["http://localhost:5173","https://PROJECT_ID.web.app"],"method":["GET","PUT"],"responseHeader":["Content-Type"],"maxAgeSeconds":3600}]
J
gcloud storage buckets update gs://$P-ll-uploads --cors-file=/tmp/cors.json
gcloud storage buckets update gs://$P-ll-worlds --cors-file=/tmp/cors.json   # highlights files are fetched by the browser
```
Signing URLs from Cloud Run uses the service account and needs `roles/iam.serviceAccountTokenCreator` (granted in guide 02).

## Verify
`gcloud storage ls` lists the three buckets; after `make genesis` (cloud mode) `gcloud storage ls gs://$P-ll-worlds/genesis/` shows `v1/`, and `checkpoints/` fills up once the engine runs.

## Lifecycle (keep costs low)
Keep the last 48 checkpoints plus one per sim day: the engine deletes older ones itself. Optionally add a bucket lifecycle rule that deletes `checkpoints/` objects older than 14 days.
