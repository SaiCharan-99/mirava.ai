# Phase 6 — Hardening, deploy, demo, submission

**Time box:** ~2 h · **Depends on:** Phase 5 · **Specs:** X-03 (final), X-04, X-05, X-06, U-08 (final), all DEMO specs verified · **Visual screens:** all `01`–`34` (incl. `34-people-light`)

## Goal
A reliable, judge-ready, deployed prototype:
- blocking issues fixed, evals green, security checked
- every gated screen PASSes
- the world **pre-warmed** with a few sim days of life
- Pulse 5 and Orbit S launched days apart, with the team's real content where available
- Nova X1 ready for the live demo
- the fallback ready (highlights replay + restorable snapshot)
- guide, README, demo script and deck outline written; release tagged

## Accounts & cloud setup needed
Walk me through these with `/gcp-setup` before the first step that needs them, unless they're already ✅ in `PROGRESS.md` §5b:
- `/gcp-setup 13` — Monitoring dashboard (tick lag, spend/hour, rendered ratio, live viewers) + alert on tick lag > 2 min; re-check the budget alert and the OpenRouter key's credit limit
- Re-verify every §5b row against the prod project

## Prompt
```
You are starting Phase 6 (final) of Launch Lens in a fresh session.
Read CLAUDE.md, PROGRESS.md (especially §8 known issues), docs/DECISIONS.md and docs/phases/phase-06-hardening-submission.md.
Then read docs/architecture.md §17–§22 and docs/specs.md §16–§18.

Goal: fix blocking issues first, then make everything reliable, verified, pre-warmed and deployed.
Do not add new features. Ask before any GCP change. Finish with make test, make lint, make eval,
/visual-check 6 (all screens), and /end-phase with final URLs.
```

## Build checklist
### Fix & stabilise
- [ ] Every blocking item in PROGRESS.md §8 resolved
- [ ] Empty/error/loading states on every page; no console errors (capture log shows 0)
- [ ] Engine restart drill: kill → resume from checkpoint; lease handover; watchdog

### Evals (`make eval` → `evals/RESULTS.md`)
- [ ] Isolation (marker facts in chats and store inquiries), persona consistency, attention calibration, Insights faithfulness + benchmark, determinism, budget simulation

### Security
- [ ] Secrets only in Secret Manager and local `.env`; gitleaks clean; rotate the dev OpenRouter key; credit limit set
- [ ] Least-privilege service accounts; `/commands` IAM-only; `ll-analyst-ro` for Insights SQL; Model Armor on uploads and questions
- [ ] Budget alerts on; governor cap verified in cloud

### Demo readiness (X-05)
- [ ] `make seed-demo` with the team's real product content where provided (placeholders otherwise)
- [ ] Pre-warm: deploy the world ≥ 12 real hours before the demo; launch Pulse 5 and Orbit S a few sim days apart; keep Nova X1 ready
- [ ] `make restore-demo` (snapshot of the pre-warmed world) tested end to end in < 5 minutes
- [ ] Fallback: if the engine is down, the UI plays the latest highlights and shows "Replay"
- [ ] Logged-out walkthrough on another device: Globe → World (hover, profile, a full conversation) → Launch Studio (graph, plan) → Launch → Insights (Ask: phones > 5 years; Hoardings; Segments)
- [ ] Performance numbers (architecture §19) measured → PROGRESS.md

### Docs
- [ ] Guide (U-08) final; README (pitch, screenshots from `docs/ui-reference/`, architecture diagram, Google Cloud services, local run, deploy, eval results, OSM attribution)
- [ ] `docs/DEMO_SCRIPT.md` (3 min) following specs §16; `docs/DECK_OUTLINE.md` (problem, solution, demo, architecture, Google Cloud usage, privacy model, cost/governor, OOH insight, roadmap)

### Release
- [ ] `make deploy`; tag `v1.0-submission`; public GitHub repo with licence; no secrets
- [ ] Hackathon submission checklist ticked in PROGRESS.md

## Visual check
`/visual-check 6` → **all gated screens 01–34 PASS** (light theme `34-people-light` included); review screens compared by eye. Paste the final table into PROGRESS.md §4.

## Acceptance checks
1. `make test`, `make lint`, `make eval` green.
2. The world has run unattended for ≥ 12 real hours with no stalls (tick lag < 2 min) and spend ≤ $15/day.
3. Logged-out prod walkthrough in under 10 minutes following the Guide.
4. Every DEMO spec is ticked in PROGRESS.md §3 or explicitly cut with a reason.
5. Final visual report: all gated screens PASS.

## Handoff
Final URLs, product ids, snapshot name, how to re-run the demo, known limitations for the Q&A.
