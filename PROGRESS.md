# PROGRESS.md — Launch Lens build log (v3 · always-on agent world)

Living document. Every Claude Code session reads it first and updates it last (`/end-phase`). Keep it accurate and short. Rows 28+ of `docs/DECISIONS.md` describe the current (v3) design.

## 1. Current status
| Field | Value |
|---|---|
| Current phase | 1 — Foundation, globe, Indiranagar map, app shell |
| Phase status | ⬜ Not started |
| Repo green (`make test` + `make lint`) | n/a |
| Last session | — |
| Builder | Sai Charan (Claude Code) |
| Deadline | 18 Oct 2026 |

## 2. Phase tracker
| # | Phase | Status | Date | Visual check | Notes |
|---|---|---|---|---|---|
| 1 | Foundation, globe, Indiranagar map, app shell | ⬜ | | | |
| 2 | Population & the always-on world engine | ⬜ | | | |
| 3 | Memory, think/speak conversations, governor, highlights | ⬜ | | | |
| 4 | Launch Studio, channels and attention | ⬜ | | | |
| 5 | Stores, buying and Insights | ⬜ | | | |
| 6 | Hardening, deploy, demo, submission | ⬜ | | | |
Legend: ⬜ not started · 🟨 in progress · ✅ done · ⚠️ done with open issues

## 3. Spec coverage (DEMO + STRETCH; tick only when "done when" is met)
| Group | Phase | Specs |
|---|---|---|
| World & time | 1, 2, 3 | ☐ W-01 ☐ W-02 ☐ W-03 ☐ W-04 ☐ W-05 ☐ W-06 ☐ W-07 ☐ W-08 ☐ W-09 ☐ W-10 |
| Population | 2, 4 | ☐ P-01 ☐ P-02 ☐ P-03 ☐ P-04 ☐ P-05 ☐ P-06 ☐ P-07 (stretch) ☐ P-08 |
| Engine | 2, 3 | ☐ E-01 ☐ E-02 ☐ E-03 ☐ E-04 ☐ E-05 ☐ E-06 ☐ E-07 |
| Memory | 3 | ☐ M-01 ☐ M-02 ☐ M-03 ☐ M-04 ☐ M-05 ☐ M-06 ☐ M-07 |
| Attention | 4 | ☐ A-01 ☐ A-02 ☐ A-03 ☐ A-04 ☐ A-05 ☐ A-06 |
| Channels | 3, 4 | ☐ C-01 ☐ C-02 ☐ C-03 ☐ C-04 ☐ C-05 ☐ C-06 ☐ C-07 ☐ C-08 |
| Talk | 3, 5 | ☐ T-01 ☐ T-02 ☐ T-03 ☐ T-04 ☐ T-05 ☐ T-06 ☐ T-07 |
| Shopping | 5 | ☐ S-01 ☐ S-02 ☐ S-03 ☐ S-04 ☐ S-05 ☐ S-06 |
| Launch Studio | 4 | ☐ L-01 ☐ L-02 ☐ L-03 ☐ L-04 ☐ L-05 ☐ L-06 ☐ L-07 ☐ L-08 |
| Insights | 5 | ☐ I-01 ☐ I-02 ☐ I-03 ☐ I-04 ☐ I-05 ☐ I-06 ☐ I-07 ☐ I-08 ☐ I-09 |
| UI | 1, 1, 6, 1–4, 1–6, 2, 2–3, 4, 5 | ☐ U-01 ☐ U-02 ☐ U-03 ☐ U-04 ☐ U-05 ☐ U-06 ☐ U-07 ☐ U-08 ☐ U-09 |
| Platform | 1, 1–2, 4, 6, 6 | ☐ X-01 ☐ X-02 ☐ X-03 ☐ X-04 ☐ X-05 ☐ X-06 |

## 4. Visual check status (`tools/visual`, latest run)
| Screen | Phase | Layout | Edges | Geometry | Result |
|---|---|---|---|---|---|
| 01-globe | 1 |  | | | |
| 02-world | 1 |  | | | |
| 03-world-hover | 2 |  | | | |
| 04-profile-overview | 2 |  | | | |
| 05-profile-relations | 2 |  | | | |
| 06-profile-possessions | 2 |  | | | |
| 07-profile-thoughts | 3 |  | | | |
| 08-profile-conversations | 3 |  | | | |
| 09-profile-memory | 3 |  | | | |
| 10-world-watching | 2 |  | | | |
| 11-world-products | 4 |  | | | |
| 12-world-highlights | 3 |  | | | |
| 13-world-look | 2 | review | | | |
| 14-world-night | 2 | review | | | |
| 15-world-lens-aware | 4 | review | | | |
| 16-world-lens-hoardings | 4 | review | | | |
| 17-world-launch-fx | 4 | review | | | |
| 18-launch-list | 4 |  | | | |
| 19-launch-details | 4 |  | | | |
| 20-launch-content | 4 |  | | | |
| 21-launch-understand | 4 |  | | | |
| 21b-launch-graph | 4 | review | | | |
| 22-launch-plan | 4 |  | | | |
| 23-launch-ready | 4 |  | | | |
| 24-insights-ask | 5 |  | | | |
| 25-insights-overview | 5 |  | | | |
| 26-insights-sources | 5 |  | | | |
| 27-insights-hoardings | 5 |  | | | |
| 28-insights-segments | 5 |  | | | |
| 29-insights-conversations | 5 |  | | | |
| 30-insights-polls | 5 |  | | | |
| 31-insights-interview | 5 |  | | | |
| 32-people | 2 |  | | | |
| 33-guide | 1 |  | | | |
| 34-people-light | 6 |  | | | |

## 5. Environment
| Item | Value |
|---|---|
| GCP project / region | _phase 1_ |
| Web URL (Firebase Hosting) | _phase 1_ |
| API URL (Cloud Run `launch-lens-api`) | _phase 1_ |
| world-engine URL / revision | _phase 2_ |
| OSM extract date / map stats | _phase 1_ |
| Genesis version / seed | _phase 2_ |
| Live products (ids, launched at) | _phase 4+_ |
| Demo snapshot name | _phase 6_ |

## 5b. Accounts & cloud setup status
Filled in by `/gcp-setup` (guides in `docs/setup/`). Never paste keys or secrets here — only names and ✅.
| # | Item | Needed by phase | Status | Date | Notes (names, region — no secrets) |
|---|---|---|---|---|---|
| 00 | OpenRouter account, API key in `.env`, models verified, credit limit | 1 | ⬜ | | |
| 15 | OpenStreetMap extract for Indiranagar (only if Overpass is blocked) | 1 | ⬜ / not needed | | |
| 01 | GCP project, billing, budget alert, gcloud + ADC | 1 | ⬜ | | |
| 02 | APIs enabled, service accounts + roles | 1 | ⬜ | | |
| 03 | Secret Manager `openrouter-api-key` | 1 | ⬜ | | |
| 04 | Artifact Registry `launch-lens`, Cloud Build permissions | 1 | ⬜ | | |
| 05 | Cloud Run `launch-lens-api` | 1 | ⬜ | | |
| 06 | Firebase Hosting | 1 | ⬜ | | |
| 07 | Firestore emulator (local) | 1 | ⬜ | | |
| 07 | Firestore database `asia-south1` | 2 | ⬜ | | |
| 08 | Cloud Storage buckets + CORS | 2 | ⬜ | | |
| 09 | BigQuery dataset `launch_lens` (+ public data priors) | 2 | ⬜ | | |
| 10 | Pub/Sub `world-events`, `world-texts` + BigQuery subscriptions | 2 | ⬜ | | |
| 05 | Cloud Run `world-engine` (always-on, min=max=1) | 2 | ⬜ | | |
| 16 | Cloud Scheduler watchdog | 2 | ⬜ | | |
| 07 | Firestore vector index `memories` | 3 | ⬜ | | |
| 12 | Model Armor template | 4 | ⬜ | | |
| 09 | BigQuery views + `ll-analyst-ro` + VECTOR_SEARCH check | 5 | ⬜ | | |
| 13 | Monitoring dashboard + alerts | 6 | ⬜ | | |
| 14 | Vertex AI (only if `LLM_BACKEND=vertex`) | — | skipped | | |

## 6. How to run (keep current — copy-paste ready)
_Filled in by phase 1 and updated by every phase._

## 7. Contract changes (to docs/INTERFACES.md)
_None yet. Every change: what, why, which phase, DECISIONS.md entry #._

## 8. Known issues / tech debt
_None yet. Format: `[phase N] [blocking|minor] description — where — suggested fix`._

## 9. Handoff notes for the next session
_Phase 1 has not started. Start with `/start-phase 1`._

## 10. Session log (newest first)
<!--
### YYYY-MM-DD HH:MM · Phase N · <status>
- Built: (modules, endpoints, screens)
- Tests: (counts, what's covered)
- Visual check: (table summary; screens still failing and why)
- Deployed: (what, where)
- Cloud setup: (rows ticked in §5b)
- Contract changes: (or "none")
- Open issues: (link §8)
- Next session must: (3 concrete first steps)
-->
