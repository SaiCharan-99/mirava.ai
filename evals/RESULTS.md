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
