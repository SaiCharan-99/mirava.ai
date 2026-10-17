---
name: end-phase
description: Close the current Launch Lens phase - tests, acceptance checks, visual check, and full handoff in PROGRESS.md and DECISIONS.md
disable-model-invocation: true
---
Close the current phase so the next fresh session can continue without any other context.

1. Run `make test` and `make lint`; fix failures.
2. Run every **Acceptance check** in the current phase file; report pass/fail for each with evidence (command output, file path, screenshot).
3. If this phase touched UI: run the `/visual-check` steps for this phase's screens until gated screens PASS (or document why not). Copy the result table into `PROGRESS.md` §4.
4. Update `PROGRESS.md`:
   - §1 current status and §2 phase row (✅ or ⚠️ + visual-check summary)
   - §3 tick spec IDs whose "done when" is met (only those)
   - §5 environment values discovered (URLs, versions, branch IDs)
   - §5b accounts & cloud setup status (✅ rows, names, regions — never secrets); list setup items the next phase will need
   - §6 how to run (exact commands that work now)
   - §7 contract changes (also update `docs/INTERFACES.md`)
   - §8 known issues (blocking vs minor, where, suggested fix)
   - §9 handoff notes: copy the phase file's **Handoff** items and fill them in; list the next session's first 3 steps
   - §10 add a session log entry at the top
5. Append any non-obvious choices to `docs/DECISIONS.md` (new rows only).
6. Run `git status` and confirm `.env` and any key files are not staged (gitleaks clean).
7. Commit: `phase-N: complete` (or `phase-N: partial` if ⚠️).
8. Print a 6-line summary: done, not done, visual status, contract changes, risks, first step for next session.
