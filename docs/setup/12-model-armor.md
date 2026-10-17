# 12 · Model Armor (prompt-injection screening)

**Needed from:** phase 4 (Launch Studio uploads) and phase 5 (Insights questions, interviews). Locally `MODEL_ARMOR_ENABLED=false` uses a fake screener.

## 1. Enable and permissions
```bash
gcloud services enable modelarmor.googleapis.com
# your user needs Model Armor Admin to create templates:
gcloud projects add-iam-policy-binding PROJECT_ID --member="user:YOUR_EMAIL" --role=roles/modelarmor.admin --condition=None
# the API service account needs to call it:
gcloud projects add-iam-policy-binding PROJECT_ID --member="serviceAccount:ll-api@PROJECT_ID.iam.gserviceaccount.com" --role=roles/modelarmor.user --condition=None
```
## 2. Template
Model Armor uses **regional endpoints** (`modelarmor.LOCATION.rep.googleapis.com`); the global endpoint can't manage templates or sanitise. Pick a supported location from the Model Armor "Locations" docs page — prefer `asia-south1` if it is listed there, otherwise `us-central1`. The commands below use `LOCATION`.
```bash
gcloud model-armor templates create launch-lens-screen --project=PROJECT_ID --location=LOCATION \
  --rai-settings-filters='[{"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"HARASSMENT","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"SEXUALLY_EXPLICIT","confidenceLevel":"MEDIUM_AND_ABOVE"}]' \
  --pi-and-jailbreak-filter-settings-enforcement=enabled \
  --pi-and-jailbreak-filter-settings-confidence-level=HIGH
```
`.env` / Cloud Run: `MODEL_ARMOR_ENABLED=true`, `MODEL_ARMOR_TEMPLATE=projects/PROJECT_ID/locations/LOCATION/templates/launch-lens-screen`.
## 3. How the app calls it
`shared/safety.py` sends extracted text to the template's **sanitize user prompt** method on the regional endpoint and blocks/flags on a match. Check the "Sanitize prompts and responses" page of the Model Armor docs for the exact request body when implementing.
## 4. Verify
Phase 4's injection suite runs against the real template with `@pytest.mark.cloud`.
