# 04 · Artifact Registry and Cloud Build

**Needed from:** phase 1 (first deploy).

## 1. Docker repository
```bash
gcloud artifacts repositories create launch-lens --repository-format=docker --location=asia-south1 --description="Launch Lens images"
gcloud auth configure-docker asia-south1-docker.pkg.dev
```
Image names: `asia-south1-docker.pkg.dev/PROJECT_ID/launch-lens/<service>:<tag>` (api, world-engine).

## 2. Let Cloud Build deploy
```bash
PN=$(gcloud projects describe PROJECT_ID --format='value(projectNumber)')
for r in roles/run.admin roles/iam.serviceAccountUser roles/artifactregistry.writer roles/firebasehosting.admin; do
  gcloud projects add-iam-policy-binding PROJECT_ID --member="serviceAccount:$PN@cloudbuild.gserviceaccount.com" --role=$r --condition=None; done
```
(If your project uses the Compute Engine default service account for builds, grant the same roles to `$PN-compute@developer.gserviceaccount.com`; the build log tells you which identity ran.)

## 3. Build & deploy manually
```bash
gcloud builds submit --config infra/cloudbuild.yaml --substitutions=_REGION=asia-south1
```
## 4. Optional: deploy on every push
Console: ☰ **Cloud Build → Triggers → Connect repository** → GitHub → authorise → choose the repo → **Create trigger** (event: push to `main`, config: `infra/cloudbuild.yaml`).
## 5. Verify
`gcloud artifacts docker images list asia-south1-docker.pkg.dev/PROJECT_ID/launch-lens` and the build shows SUCCESS in ☰ **Cloud Build → History**.
