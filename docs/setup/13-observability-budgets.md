# 13 · Logging, Monitoring, Trace and budget controls

**Needed from:** phase 1 (budget, done in guide 01), phase 6 (dashboards and alerts).

- **Logs:** ☰ **Logging → Logs Explorer**. Filter with `resource.labels.service_name="world-engine"` and `jsonPayload.agent_id=7`. The engine logs structured JSON with `t`, `agent_id` and `session_id`.
- **Traces:** ☰ **Trace → Trace explorer** (the LLM gateway emits a span per call, with cost).
- **Errors:** ☰ **Error Reporting** groups exceptions from both services.
- **Dashboard (phase 6):** ☰ **Monitoring → Dashboards → Create**, with these custom metrics written by the engine:
  - `tick_lag_seconds`
  - `events_per_minute`
  - `llm_calls{class}`
  - `spend_usd_per_hour`
  - `rendered_ratio`
  - `live_viewers`

  Add Cloud Run instance count and CPU for `world-engine`.
- **Alerts:** ☰ **Monitoring → Alerting → Create policy**:
  - `tick_lag_seconds` > 120 for 5 min (world stalled)
  - api 5xx rate > 5%
  - `spend_usd_per_hour` above twice the plan
- **Spend:**
  - the GCP budget from guide 01
  - the OpenRouter key's credit limit (guide 00)
  - the in-app governor: `DAILY_CAP_USD=15`, `INTERACTIVE_CAP_USD=5`
- **After the hackathon:** pause the world (`/commands` `pause`) or set `world-engine` min instances to 0, and keep the budget alert.
