# START HERE — Launch Lens build kit (v3 · always-on agent world)

Hi Charan 👋 This kit has everything Claude Code needs to build Launch Lens, phase by phase. You run **6 Claude Code sessions**, one per phase, in order. Each session starts fresh, reads the handoff files, builds, verifies (including a pixel-level UI check), and writes the handoff for the next one.

**What changed in v3** (see `docs/DECISIONS.md` rows 28+): the product is now an **always-on world** of 1,000 agents in a real-street Indiranagar (OpenStreetMap). The changes, in short:
- a globe intro, and the World as the home page
- Launch Studio with multiple products and automatic hoarding placement, launched with a firework drop
- private thoughts vs public speech (3-step chats, turn-by-turn store visits)
- exact transcripts in BigQuery
- an Insights assistant that answers any question
- a Hoardings (out-of-home) analytics view

**Delete any older copy of the kit (v1/v2) before unzipping this one.** The phase files and pages changed.

## 1. What's in the kit
| Path | What it is |
|---|---|
| `CLAUDE.md` | Rules Claude Code loads automatically every session |
| `PROGRESS.md` | Living build log + handoff between sessions (+ cloud setup status §5b) |
| `docs/phases/phase-01…06-*.md` | The prompt and checklist for each session |
| `docs/architecture.md` | System design: 12 features, each with its own Mermaid flow, plus the end-to-end diagram |
| `docs/INTERFACES.md` | Contracts: schemas, events, live protocol, API, UI test ids, visual-test hooks, BigQuery |
| `docs/specs.md` | 91 demo specs with "done when" criteria |
| `docs/techstack.md` | Google Cloud services, models and prices |
| `docs/setup/` | **Step-by-step setup guides** for OpenRouter, OpenStreetMap and every Google Cloud service |
| `docs/DECISIONS.md` | Every decision so far (append-only) |
| `docs/ui-mockup.html` | Interactive desktop UI mockup. Open it in Chrome; it's live without `?freeze=1` |
| `docs/ui-reference/` | 35 reference screenshots + region geometry for the visual check |
| `tools/visual/` | Pixel-level UI verification + `extract-fixtures.mjs` |
| `.claude/skills/` | `/start-phase`, `/end-phase`, `/visual-check`, `/gcp-setup` |
| `.mcp.json` | Playwright MCP server for Claude Code (browser + screenshots) |
| `.env.example` | Local settings (fakes by default) |

## 2. One-time setup on your machine
1. **Install:** Claude Code (latest), Node.js 20+, Python 3.12 + uv, Git, Google Cloud SDK (gcloud), Docker, Java 11+ (Firestore emulator).
2. **Optional:** Google Chrome + the Claude in Chrome extension (start with `claude --chrome`).
3. **Unzip** this kit into the root of an empty folder (e.g. `C:\Users\gobbu\Documents\aibuildercup\launch-lens`), then:
   ```bash
   git init && git add . && git commit -m "kit v3: specs, architecture, phases, mockup, visual check, setup guides"
   cp .env.example .env
   cd tools/visual && npm install && npx playwright install chromium && cd ../..
   ```
4. **Self-test the visual tool.** It should print PASS/REVIEW at 0.0% for all 35 screens:
   ```bash
   cd tools/visual && node capture.mjs --target selftest && node compare.mjs && cd ../..
   ```
5. **OpenRouter key:** put the team's key into `.env` as `OPENROUTER_API_KEY=...` and set a **credit limit** on the key (`docs/setup/00-openrouter.md`). `.env` is git-ignored, so never commit the key or paste it anywhere else. Tests always use fakes.
6. **Google Cloud:** nothing to prepare in advance. Whenever a phase first needs a service, Claude Code stops and walks you through it with `/gcp-setup`:
   - it explains what the service is for
   - it gives the console clicks and the exact commands, and waits for your OK
   - it verifies the result and ticks it in `PROGRESS.md` §5b

   You can also run a guide yourself at any time, e.g. `/gcp-setup 01` or `/gcp-setup firestore`.

## 3. Running a phase
```bash
cd launch-lens
claude            # or: claude --chrome
```
In Claude Code:
```
/start-phase 1
```
Let it work through the checklist. When it reports the phase is done (tests green, acceptance checks pass, visual check PASS), run:
```
/end-phase
```
Then **exit** and start a **new** session for the next phase (`claude`, then `/start-phase 2`). Never continue to the next phase in the same session.

Tips:
- **Phase 1:** Claude Code fetches the OpenStreetMap extract for Indiranagar and commits it. If the Overpass API is blocked on your network, it walks you through `/gcp-setup 15` (manual export).
- **Phase 2:** this deploys the **always-on** `world-engine`. From then on the world lives even when your laptop is closed. Watch the budget meter in the header.
- If a session runs long, ask Claude Code to stop at a green state and run `/end-phase` (it marks ⚠️ with handoff notes).
- `/visual-check 3` re-runs the UI comparison for the screens up to phase 3.

## 4. Phase map
| # | Phase | Rough time |
|---|---|---|
| 1 | Foundation, globe, Indiranagar map, app shell | 2.5 h |
| 2 | Population & the always-on world engine | 3 h |
| 3 | Memory, think/speak conversations, governor, highlights | 3 h |
| 4 | Launch Studio, channels and attention | 3 h |
| 5 | Stores, buying and Insights | 3 h |
| 6 | Hardening, deploy, demo, submission | 2 h |

If time runs short, follow the cut order in `docs/specs.md` §16. Never cut:
- the live city with walking agents
- private thoughts on notice
- 3-step conversations
- the launch moment
- the Ask assistant
- the Hoardings tab
- the always-on Cloud Run deployment
