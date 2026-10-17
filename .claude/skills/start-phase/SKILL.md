---
name: start-phase
description: Start a Launch Lens build phase in a fresh Claude Code session. Usage /start-phase 3
argument-hint: "[phase number 1-6]"
disable-model-invocation: true
---
Start **Phase $ARGUMENTS** of Launch Lens.

1. Read `CLAUDE.md` (whole file), then `PROGRESS.md` (whole file), then `docs/DECISIONS.md` (rows 28+ are the current v3 design).
2. Open the phase file `docs/phases/phase-0$ARGUMENTS-*.md` and follow its **Prompt** section as your instructions. Read only the doc sections it lists (architecture, INTERFACES, specs).
3. Check prerequisites: every earlier phase in `PROGRESS.md` §2 must be ✅ or ⚠️. If an earlier phase is ⬜ or 🟨, stop and tell me what is missing.
4. Read `PROGRESS.md` §6 (how to run), §7 (contract changes), §8 (known issues) and §9 (handoff notes). Apply any "next session must" steps first.
5. Run `make test` (and `make lint`). If anything is red, fix it before new work and note it in the session log.
6. Read the phase file's **Accounts & cloud setup needed** section and `PROGRESS.md` §5b. List the items not yet ✅ and tell me which ones you'll walk me through with `/gcp-setup` (and when — just before the first step that needs them). Do local work with fakes meanwhile.
7. Create a task list from the phase checklist (use the task tool). Mark phase $ARGUMENTS as 🟨 in `PROGRESS.md` §1 and §2.
8. Summarise in 5 bullets: what exists, what you will build this session, and which visual-check screens apply. Then start building.
