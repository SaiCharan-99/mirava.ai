# 01 · Google Cloud account, project, billing and gcloud

**Needed from:** phase 1. **Time:** ~15 min.

## 1. Google account and Cloud console
1. Use a Google account you control (personal Gmail works). Open **https://console.cloud.google.com** and accept the terms.
2. If you have hackathon credits (coupon code from the organisers), keep the code ready for step 3.

## 2. Create the project
1. Top bar → project picker → **New project**.
2. Name: `launch-lens` · Project ID: e.g. `launch-lens-hack` (globally unique, can't change later) → **Create**.
3. Select the new project in the picker.

## 3. Billing (required for Cloud Run, BigQuery storage, etc.)
1. ☰ **Billing** → **Link a billing account** (or **Manage billing accounts → Create account**). Enter payment details. New accounts may be eligible for a free trial with credits — check the current offer shown on the sign-up page.
2. To redeem hackathon credits: **Billing → Credits** (or the coupon link from the organisers) → enter the code → link it to the billing account used by this project.
3. Confirm: **Billing → Overview** shows the project linked.

## 4. Budget alert (do this now)
**Billing → Budgets & alerts → Create budget**: scope = this project, amount e.g. $50, alerts at 50% / 90% / 100% → email. (Or CLI:)
```bash
gcloud billing budgets create --billing-account=BILLING_ACCOUNT_ID \
  --display-name="launch-lens" --budget-amount=50USD \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
```
Find `BILLING_ACCOUNT_ID` with `gcloud billing accounts list`.

## 5. Install and initialise gcloud
- **Windows:** download and run the installer from https://cloud.google.com/sdk/docs/install (Google Cloud SDK installer), tick "Run gcloud init". Use the "Google Cloud SDK Shell" or a new PowerShell.
- **macOS:** `brew install --cask google-cloud-sdk` (or the installer from the same page).
```bash
gcloud init                                   # sign in, choose PROJECT_ID
gcloud auth login
gcloud auth application-default login         # credentials for local Python/Node SDKs
gcloud config set project PROJECT_ID
gcloud config set run/region asia-south1
gcloud components install beta bq             # bq is usually included
```

## 6. Verify
```bash
gcloud config list
gcloud projects describe PROJECT_ID --format='value(projectNumber,lifecycleState)'
gcloud billing projects describe PROJECT_ID --format='value(billingEnabled)'   # → True
```

## 7. Record in PROGRESS.md §5 / §5b
Project id, project number, region, billing linked ✅, budget ✅.
