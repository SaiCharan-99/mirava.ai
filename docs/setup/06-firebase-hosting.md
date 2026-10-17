# 06 · Firebase Hosting (public web URL)

**Needed from:** phase 1.

## 1. Add Firebase to the GCP project
1. Open **https://console.firebase.google.com** → **Create a project / Add project** → choose **"Add Firebase to an existing Google Cloud project"** and select `PROJECT_ID`. Google Analytics: not needed.
2. In the Firebase console: **Build → Hosting → Get started** (just click through; we deploy from the CLI).

## 2. CLI
```bash
npm install -g firebase-tools
firebase login
firebase use --add PROJECT_ID          # from the repo root
```
## 3. Config (`firebase.json`, created in phase 1)
```json
{
  "hosting": {
    "public": "web/dist",
    "ignore": ["**/.*", "**/node_modules/**"],
    "rewrites": [
      { "source": "/api/**", "run": { "serviceId": "launch-lens-api", "region": "asia-south1" } },
      { "source": "**", "destination": "/index.html" }
    ]
  }
}
```
## 4. Deploy
```bash
npm --prefix web run build
firebase deploy --only hosting
```
The CLI prints `https://PROJECT_ID.web.app`.
## 5. Verify
Open the URL in a private window: the app shell loads logged-out (demo mode), `/api/healthz` returns OK.
