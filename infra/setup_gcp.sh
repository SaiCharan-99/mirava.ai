#!/usr/bin/env bash
# PRINTS (never runs) the gcloud commands of docs/setup/02–10 with names filled in.
#   bash infra/setup_gcp.sh PROJECT_ID [REGION]  > setup-commands.sh   # review, then run step by step
# Names follow the mirava.ai rename (DECISIONS #56): service accounts mirava-*, repo `mirava`, dataset `mirava`.
set -euo pipefail
P="${1:?usage: setup_gcp.sh PROJECT_ID [REGION]}"
R="${2:-asia-south1}"
cat <<EOF
# ---------- 02 · APIs ----------
gcloud config set project $P
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \\
  firestore.googleapis.com bigquery.googleapis.com bigquerystorage.googleapis.com storage.googleapis.com \\
  pubsub.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com iam.googleapis.com \\
  iamcredentials.googleapis.com logging.googleapis.com monitoring.googleapis.com cloudtrace.googleapis.com \\
  firebase.googleapis.com firebasehosting.googleapis.com modelarmor.googleapis.com

# ---------- 02 · service accounts ----------
gcloud iam service-accounts create mirava-api --display-name="mirava.ai api"
gcloud iam service-accounts create mirava-engine --display-name="mirava.ai world-engine"
gcloud iam service-accounts create mirava-analyst-ro --display-name="mirava.ai analyst (read-only)"
gcloud iam service-accounts create mirava-scheduler --display-name="mirava.ai scheduler"
EOF
grant() { echo "gcloud projects add-iam-policy-binding $P --member=serviceAccount:$1@$P.iam.gserviceaccount.com --role=$2 --condition=None"; }
echo "# ---------- 02 · roles ----------"
for r in roles/datastore.user roles/storage.objectAdmin roles/bigquery.jobUser roles/secretmanager.secretAccessor \
         roles/iam.serviceAccountTokenCreator roles/modelarmor.user roles/logging.logWriter roles/cloudtrace.agent; do
  grant mirava-api "$r"; done
for r in roles/datastore.user roles/storage.objectAdmin roles/pubsub.publisher roles/bigquery.dataEditor \
         roles/bigquery.jobUser roles/secretmanager.secretAccessor roles/logging.logWriter roles/cloudtrace.agent \
         roles/monitoring.metricWriter; do
  grant mirava-engine "$r"; done
for r in roles/bigquery.dataViewer roles/bigquery.jobUser; do grant mirava-analyst-ro "$r"; done
cat <<EOF

# ---------- 03 · Secret Manager (key typed into a temp file, never on the command line) ----------
gcloud secrets create openrouter-api-key --replication-policy=automatic
gcloud secrets versions add openrouter-api-key --data-file=KEYFILE   # then delete KEYFILE
gcloud secrets add-iam-policy-binding openrouter-api-key --member=serviceAccount:mirava-api@$P.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding openrouter-api-key --member=serviceAccount:mirava-engine@$P.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor

# ---------- 04 · Artifact Registry + Cloud Build ----------
gcloud artifacts repositories create mirava --repository-format=docker --location=$R --description="mirava.ai images"
EOF
PN_CMD="\$(gcloud projects describe $P --format='value(projectNumber)')"
for r in roles/run.admin roles/iam.serviceAccountUser roles/artifactregistry.writer roles/firebasehosting.admin \
         roles/secretmanager.secretAccessor roles/logging.logWriter; do
  echo "gcloud projects add-iam-policy-binding $P --member=serviceAccount:${PN_CMD}-compute@developer.gserviceaccount.com --role=$r --condition=None"
done
cat <<EOF

# ---------- 05 · Cloud Run api (normally via: make deploy) ----------
gcloud builds submit --config infra/cloudbuild.yaml --region $R --substitutions _REGION=$R .

# ---------- 06 · Firebase Hosting ----------
# console: https://console.firebase.google.com → Add project → existing GCP project $P → Hosting → Get started
npx firebase-tools login && npx firebase-tools use --add $P

# ---------- 07 · Firestore (phase 2: cloud database; phase 1 uses the emulator) ----------
gcloud components install cloud-firestore-emulator
gcloud firestore databases create --location=$R --type=firestore-native        # phase 2

# ---------- 08 · Cloud Storage (phase 2) ----------
gcloud storage buckets create gs://$P-mirava-uploads gs://$P-mirava-worlds gs://$P-mirava-exports --location=$R --uniform-bucket-level-access

# ---------- 09 · BigQuery (phase 2) ----------
bq --location=$R mk --dataset $P:mirava

# ---------- 10 · Pub/Sub (phase 2) ----------
gcloud pubsub topics create world-events world-texts
EOF
