---
name: gcp-setup
description: Walk the user step by step through creating an account or Google Cloud service for Launch Lens (OpenRouter, OpenStreetMap extract, project/billing, IAM, Secret Manager, Cloud Run incl. the always-on world-engine, Cloud Scheduler, Firebase, Firestore, Storage, BigQuery, Pub/Sub, Model Armor). Usage /gcp-setup 07 or /gcp-setup firestore or /gcp-setup phase 5
argument-hint: "[guide number | service name | phase N]"
---
Guide the user through setting up **$ARGUMENTS** for Launch Lens.

1. Open `docs/setup/README.md`. Resolve the argument:
   - a number (`00`–`16`) or service name → that guide in `docs/setup/`
   - `phase N` → every guide whose "Needed from" includes phase N and that is not ✅ in `PROGRESS.md` §5b, in README order
   - empty → list §5b items that are not ✅ for the current phase and ask which to start.
2. Read `PROGRESS.md` §5 and §5b. Skip anything already ✅ (say so). If the project id / region aren't recorded yet, ask the user for the project id (suggest one) and use `asia-south1`.
3. For each guide, in order:
   a. In 2–3 sentences say **what the service is, why Launch Lens needs it, and rough cost** (free tier / pay-per-use, any always-on cost).
   b. Give the **console steps** as a numbered list with exact menu names and values to enter, filled in with their real project id, region and names. Ask the user to say "done" (or paste any error) before continuing. Never ask them to paste API keys or secrets into the chat — keys go in `.env` or into Secret Manager via a file they create.
   c. Show the **gcloud / bq / firebase commands** from the guide with placeholders replaced. Explain what each does in one line. Run them only after the user approves; if they prefer, they run them and paste the output. For Windows users, give the PowerShell variant when it differs (no bash loops; `curl.exe`).
   d. Run the guide's **Verify** commands and show the result. If something fails, use the guide's Troubleshooting section, check `gcloud ... --help`, and fix before moving on.
   e. Explain **how the code uses it** (env vars to set in `.env` / Cloud Run, which module reads it) and update `.env.example` if a new non-secret variable appears.
   f. Mark the row ✅ in `PROGRESS.md` §5b with date and non-secret notes (names, region, URLs). Record new URLs/ids in §5.
4. Rules: ask before creating, changing or deleting any real cloud resource; never print or log secret values; prefer least-privilege roles from guide 02; keep everything in the regions in `docs/DECISIONS.md` #27; never use `gemini-2.5-*` models; if a console screen differs from the guide, describe what to look for and use the console search bar.
5. Finish with a short summary: what is now set up, what it costs while idle, and the next setup item needed (and in which phase).
