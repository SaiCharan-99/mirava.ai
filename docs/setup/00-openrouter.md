# 00 · OpenRouter account and API key

**Used for:** every Gemini call (`LLM_BACKEND=openrouter`) and typed decisions (`DECISION_BACKEND=openrouter`). **Needed from:** phase 1 (key in `.env`), real calls from phase 2.

## 1. Create the account / key
1. Go to **https://openrouter.ai** → **Sign in** (Google or GitHub login is fine). If the team already has an account, ask the owner to create a key for this project instead.
2. Open **Keys** (https://openrouter.ai/keys) → **Create Key**.
   - Name: `launch-lens-dev` (make a second one `launch-lens-prod` later for Cloud Run).
   - **Credit limit:** set one (e.g. $20 for dev) so a runaway loop can't drain the account.
3. Copy the key once (starts with `sk-or-`). Store it in your password manager.
4. **Credits:** open **Credits** (https://openrouter.ai/credits) and confirm there is a balance; add credits if needed.
5. Optional: **Settings → Privacy** — choose whether providers may train on prompts; for client briefs, keep training **off**.

## 2. Put it in the project
```bash
# .env (never commit)
OPENROUTER_API_KEY=sk-or-...
LLM_BACKEND=openrouter
DECISION_BACKEND=openrouter
```
Keep `LLM_BACKEND=fake` for unit tests (the test runner forces it).

## 3. Verify (Claude Code runs these with your approval)
```bash
# list the Gemini models we use (must all appear)
curl -s https://openrouter.ai/api/v1/models | python -c "import sys,json;ids={m['id'] for m in json.load(sys.stdin)['data']};print([i for i in ['google/gemini-3.1-pro-preview','google/gemini-3.6-flash','google/gemini-3.5-flash-lite'] if i not in ids] or 'all present')"

# structured-output smoke test
curl -s https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"google/gemini-3.5-flash-lite","messages":[{"role":"user","content":"Say hi as JSON"}],
       "response_format":{"type":"json_schema","json_schema":{"name":"hi","strict":true,"schema":{"type":"object","properties":{"hi":{"type":"string"}},"required":["hi"],"additionalProperties":false}}},
       "provider":{"require_parameters":true}}'

# embeddings smoke test
curl -s https://openrouter.ai/api/v1/embeddings -H "Authorization: Bearer $OPENROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"google/gemini-embedding-001","input":"hello"}' | head -c 300
```
Windows PowerShell: use `curl.exe` and put the JSON body in a file (`-d "@body.json"`).

## 4. For Cloud Run (phase 1 deploy onwards)
Store the prod key in Secret Manager as `openrouter-api-key` → see [03-secret-manager.md](03-secret-manager.md).

## 5. Record in PROGRESS.md §5b
OpenRouter: ✅ key created (name, credit limit), models verified, date. **Never paste the key.**

## Troubleshooting
- `401` → wrong/missing key; `402` → out of credits; `404 model` → id changed, check the models list and update `MODEL_*_ID` in `.env`.
- Structured output errors → keep `provider.require_parameters=true`; if a model loses support, switch to another listed Gemini 3 id.
