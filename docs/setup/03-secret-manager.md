# 03 · Secret Manager

**Needed from:** phase 1 (before the first Cloud Run deploy). **Stores:** `openrouter-api-key`.

## 1. Create the secret
Console: ☰ **Security → Secret Manager → Create secret** → name `openrouter-api-key` → paste the **prod** OpenRouter key as the value → Create.

CLI: type the key into a temp file you delete afterwards, so it never lands in shell history:
```bash
gcloud secrets create openrouter-api-key --replication-policy=automatic
gcloud secrets versions add openrouter-api-key --data-file=/path/to/key.txt   # file contains only the key, no newline
rm /path/to/key.txt
```
## 2. Allow services to read it
```bash
for sa in ll-api ll-engine; do
  gcloud secrets add-iam-policy-binding openrouter-api-key \
    --member="serviceAccount:$sa@PROJECT_ID.iam.gserviceaccount.com" --role=roles/secretmanager.secretAccessor; done
```
## 3. Use it on Cloud Run
Add `--set-secrets=OPENROUTER_API_KEY=openrouter-api-key:latest` to `gcloud run deploy` for both services (this is already in `infra/cloudbuild.yaml`).
## 4. Verify (shows metadata, not the value)
```bash
gcloud secrets describe openrouter-api-key
gcloud secrets versions list openrouter-api-key
```
## 5. Rotate
1. Create a new key in OpenRouter.
2. Run `gcloud secrets versions add ...`.
3. Redeploy.
4. Disable the old key in OpenRouter.

Rotate the key used during development before submission (phase 6).
