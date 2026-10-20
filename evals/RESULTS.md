# Eval results

## Phase 5 evals · 2026-10-18 15:28 · backend FakeGemini · {'agents': 200, 'days': 1.0}

### Insights benchmark (evals/insights_questions.yaml)
- Faithfulness: **100%** (target ≥ 95%) — PASS
- Quotes verbatim: **100%** · structure pass rate 80%

| id | pass | checks | s | $ |
|---|---|---|---|---|
| old_phones | PASS | faithful=True, numbers=True, quotes=True, sql=True, chart=True | 0.45 | 0.0 |
| hoarding_facing | PASS | faithful=True, numbers=True, sql=True | 0.28 | 0.0 |
| private_pulse | PASS | faithful=True, quotes=True, private_labelled=True | 0.6 | 0.0 |
| focus_group_changers | PASS | faithful=True, numbers=True | 0.16 | 0.0 |
| first_heard | FAIL | faithful=True, numbers=True, sql=False | 0.08 | 0.0 |
| purchases | FAIL | faithful=True, numbers=False | 0.01 | 0.0 |
| store_inquiries | PASS | faithful=True, numbers=True | 0.02 | 0.0 |
| segments | PASS | faithful=True, numbers=True | 0.08 | 0.0 |
| funnel | PASS | faithful=True, numbers=True | 0.07 | 0.0 |
| unanswerable | PASS | faithful=True, declined=True | 0.0 | 0.0 |

### Survey realism (evals/run.py · addendum B14)
- Attended: 39
- Extraversion ↔ messages: r = 0.648 (target > 0.3) — PASS
- Conformity toward majority: high-A 0.128 (n=39) vs low-A 0.05 (n=20) — PASS
- Experience dominance: 0.6666666666666666 (n=3, target ≥ 0.8) — FAIL
- Shift realism: 0.154 changed (band [0.1, 0.4]) · every change cited: True — PASS
- Wave changes explained by own events: 0.8571428571428571 of 28 — FAIL
- Satisficing: late 0.179 vs first 0.0; low-C 0.667 vs high-C 0.0 — PASS

## Evals · 2026-10-18 17:49 · backend FakeGemini · {'agents': 200, 'days': 2.0}

### Insights benchmark (evals/insights_questions.yaml)
- Faithfulness: **100%** (target ≥ 95%) — PASS
- Quotes verbatim: **100%** · structure pass rate 90%

| id | pass | checks | s | $ |
|---|---|---|---|---|
| old_phones | PASS | faithful=True, numbers=True, quotes=True, sql=True, chart=True | 0.52 | 0.0 |
| hoarding_facing | PASS | faithful=True, numbers=True, sql=True | 0.33 | 0.0 |
| private_pulse | PASS | faithful=True, quotes=True, private_labelled=True | 0.68 | 0.0 |
| focus_group_changers | PASS | faithful=True, numbers=True | 0.18 | 0.0 |
| first_heard | FAIL | faithful=True, numbers=True, sql=False | 0.1 | 0.0 |
| purchases | PASS | faithful=True, numbers=True | 0.01 | 0.0 |
| store_inquiries | PASS | faithful=True, numbers=True | 0.02 | 0.0 |
| segments | PASS | faithful=True, numbers=True | 0.1 | 0.0 |
| funnel | PASS | faithful=True, numbers=True | 0.12 | 0.0 |
| unanswerable | PASS | faithful=True, declined=True | 0.0 | 0.0 |

### Survey realism (evals/run.py · addendum B14)
- Attended: 40
- Extraversion ↔ messages: r = 0.531 (target > 0.3) — PASS
- Conformity toward majority: high-A 0.064 (n=47) vs low-A 0.0 (n=27) — PASS
- Experience dominance: 0.8333333333333334 (n=18, target ≥ 0.8) — PASS
- Shift realism: 0.117 changed (band [0.1, 0.4]) · every change cited: True — PASS
- Wave changes explained by own events (or 'no clear cause' when none, n=3): 1.0 of 26 — PASS
- Satisficing: late 0.175 vs first 0.0; low-C 0.667 vs high-C 0.0 — PASS
- Note (phase 6): `first_heard` failed only because the planner keyword was "first heard" while the question says "first hear"; fixed in `agents/insights_assistant.py` and pinned by `tests/test_insights.py::test_offline_planner_routes_benchmark_questions` (routes to `run_sql` on `v_first_heard`). All other routes unchanged. Full re-run at phase close.

## Evals · 2026-10-18 20:19 · backend FakeGemini · {'agents': 200, 'days': 2.0}

### Insights benchmark (evals/insights_questions.yaml)
- Faithfulness: **100%** (target ≥ 95%) — PASS
- Quotes verbatim: **100%** · structure pass rate 100%

| id | pass | checks | s | $ |
|---|---|---|---|---|
| old_phones | PASS | faithful=True, numbers=True, quotes=True, sql=True, chart=True | 0.76 | 0.0 |
| hoarding_facing | PASS | faithful=True, numbers=True, sql=True | 0.46 | 0.0 |
| private_pulse | PASS | faithful=True, quotes=True, private_labelled=True | 0.95 | 0.0 |
| focus_group_changers | PASS | faithful=True, numbers=True | 0.24 | 0.0 |
| first_heard | PASS | faithful=True, numbers=True, sql=True | 0.08 | 0.0 |
| purchases | PASS | faithful=True, numbers=True | 0.02 | 0.0 |
| store_inquiries | PASS | faithful=True, numbers=True | 0.03 | 0.0 |
| segments | PASS | faithful=True, numbers=True | 0.1 | 0.0 |
| funnel | PASS | faithful=True, numbers=True | 0.13 | 0.0 |
| unanswerable | PASS | faithful=True, declined=True | 0.0 | 0.0 |

### Survey realism (evals/run.py · addendum B14)
- Attended: 40
- Extraversion ↔ messages: r = 0.531 (target > 0.3) — PASS
- Conformity toward majority: high-A 0.064 (n=47) vs low-A 0.0 (n=27) — PASS
- Experience dominance: 0.8333333333333334 (n=18, target ≥ 0.8) — PASS
- Shift realism: 0.117 changed (band [0.1, 0.4]) · every change cited: True — PASS
- Wave changes explained by own events (or 'no clear cause' when none, n=3): 1.0 of 26 — PASS
- Satisficing: late 0.175 vs first 0.0; low-C 0.667 vs high-C 0.0 — PASS

## Evals · 2026-10-20 15:34 · backend FakeGemini · {'agents': 300, 'days': 2.0}

### Insights benchmark (evals/insights_questions.yaml)
- Faithfulness: **100%** (target ≥ 95%) — PASS
- Quotes verbatim: **100%** · structure pass rate 100%

| id | pass | checks | s | $ |
|---|---|---|---|---|
| old_phones | PASS | faithful=True, numbers=True, quotes=True, sql=True, chart=True | 0.11 | 0.0 |
| hoarding_facing | PASS | faithful=True, numbers=True, sql=True | 0.06 | 0.0 |
| private_pulse | PASS | faithful=True, quotes=True, private_labelled=True | 0.18 | 0.0 |
| focus_group_changers | PASS | faithful=True, numbers=True | 0.02 | 0.0 |
| first_heard | PASS | faithful=True, numbers=True, sql=True | 0.01 | 0.0 |
| purchases | PASS | faithful=True, numbers=True | 0.0 | 0.0 |
| store_inquiries | PASS | faithful=True, numbers=True | 0.01 | 0.0 |
| segments | PASS | faithful=True, numbers=True | 0.01 | 0.0 |
| funnel | PASS | faithful=True, numbers=True | 0.02 | 0.0 |
| unanswerable | PASS | faithful=True, declined=True | 0.0 | 0.0 |

### Survey realism (evals/run.py · addendum B14)
- Attended: 39
- Extraversion ↔ messages: r = 0.429 (target > 0.3) — PASS
- Conformity toward majority: high-A 0.122 (n=49) vs low-A 0.029 (n=34) — PASS
- Experience dominance: 0.8888888888888888 (n=9, target ≥ 0.8) — PASS
- Shift realism: 0.171 changed (band [0.1, 0.4]) · every change cited: True — PASS
- Wave changes explained by own events (or 'no clear cause' when none, n=5): 1.0 of 7 — PASS
- Satisficing: late 0.051 vs first 0.0; low-C 0.667 vs high-C 0.0 — PASS

### Opinion engine (evals/run.py · phase 1)
- Attitude spread across 281 residents (std): 0.348 (target ≥ 0.2) — PASS
- Phone they would buy (only what they can pay for, by liking), by income band: {'1-2L': 'lumen-pro', '25-50k': 'pulse-5', '50k-1L': 'lumen-pro', '<25k': 'pulse-5', '>2L': 'lumen-pro'} (target: not the same everywhere) — PASS
- Low-income residents who talk down an unaffordable premium phone: 18% (band 5–25%) — PASS
- Attitude to the first phone after a better one appears, for people who care about display: -0.215 (target < 0) — PASS
