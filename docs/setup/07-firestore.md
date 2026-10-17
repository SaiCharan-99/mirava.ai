# 07 · Firestore (Native mode), emulator and vector index

**Needed from:** phase 1 (emulator), phase 2 (cloud database), phase 3 (vector index for memories).

## 1. Local emulator (phase 1)
Requires Java 11+.
```bash
gcloud components install cloud-firestore-emulator
gcloud emulators firestore start --host-port=localhost:8080
# in .env: FIRESTORE_EMULATOR_HOST=localhost:8080
```
(Alternative: `firebase emulators:start --only firestore`.) `make dev` starts it for you.

## 2. Create the cloud database (phase 2)
Console: ☰ **Firestore → Create database** → **Native mode** → location **asia-south1 (Mumbai)** → Production rules → Create.
**The location can't be changed later.**
```bash
gcloud firestore databases create --location=asia-south1 --type=firestore-native
```
## 3. Security rules
The browser never talks to Firestore directly (it uses `/api` and the engine's `/live`), so the rules deny all client access. Deploy `infra/firestore.rules` with `firebase deploy --only firestore:rules` (add `"firestore": {"rules": "infra/firestore.rules"}` to `firebase.json`).

## 4. Vector index for memories (phase 3)
Embeddings are stored as **768-dimension** vectors (Gemini embeddings truncated + re-normalised; Firestore's vector limit is 2048).
```bash
gcloud firestore indexes composite create --collection-group=memories --query-scope=COLLECTION \
  --field-config=field-path=agent_id,order=ASCENDING \
  --field-config=field-path=embedding,vector-config='{"dimension":"768","flat":"{}"}'
gcloud firestore indexes composite list
```
Index build takes a few minutes; queries fail with a link to the missing index if anything is off — follow it.

## 5. Verify & record
Console ☰ **Firestore → Data** shows `projects`, `world`… after the first run. Record database location in PROGRESS.md.
