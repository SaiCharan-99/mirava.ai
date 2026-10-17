# 14 · Vertex AI (optional backend)

Only if you decide to run Gemini on Google Cloud credits instead of OpenRouter (`LLM_BACKEND=vertex`).
```bash
gcloud services enable aiplatform.googleapis.com
gcloud projects add-iam-policy-binding PROJECT_ID --member="serviceAccount:ll-api@PROJECT_ID.iam.gserviceaccount.com" --role=roles/aiplatform.user --condition=None
gcloud projects add-iam-policy-binding PROJECT_ID --member="serviceAccount:ll-engine@PROJECT_ID.iam.gserviceaccount.com" --role=roles/aiplatform.user --condition=None
```
1. Console ☰ **Vertex AI → Model Garden** → search "Gemini 3" → note the exact model ids for Pro, Flash, Flash-Lite and the embedding model, and the locations (use `global` if offered).
2. `.env`: `LLM_BACKEND=vertex`, `VERTEX_LOCATION=global`, `MODEL_*_ID=` the Vertex ids.
3. ☰ **IAM & Admin → Quotas**: filter "Vertex AI" + the model to see requests-per-minute; request increases before large runs.
4. Verify with the gateway's smoke test (`make llm-smoke`).
