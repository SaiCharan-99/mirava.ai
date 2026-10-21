# Insights and simulation reliability — 21 October 2026

Reviewed README, architecture v3 and the existing development commits (ICA provider, concurrency and survey fallbacks). Preserved the existing uncommitted Ask time-budget changes.

## Causes and changes

- Ask chart components defaulted to `%`, even for raw counts. Charts now carry explicit count/fraction/percent/value metadata; old charts default to count. HTML labels are escaped.
- Starter questions use fixed, tested query plans, with normal language composition and a grounded template fallback. Repeated identical tool calls are skipped and planning reserves time to write the answer. Query errors are not shown as prose; tool steps are collapsed.
- Production logs showed interview failures in memory backfill because OpenRouter embedding credit was exhausted. Reads no longer backfill all memories. Vector outages fall back to the same person's stored text; writes retain memories without a vector. Repeated embedding failures cool down for 60 seconds. `k=0` makes no embedding request. BigQuery text search has a keyword fallback retaining all filters.
- Interviews have bounded model calls, a retryable 503 instead of a raw provider 500, and browser-session-specific histories. Selection is held while a reply is pending.
- Conversation cards expand in place. Unrendered historical interactions explicitly say no transcript exists; no dialogue is fabricated.
- The world queue no longer waits up to a fresh timeout per due job. The deadline starts at submission, including queue time. Each tick allows a shared 20ms grace period and defers unfinished jobs; completed results apply in stable order. This deliberately relaxes the old exact-application-time contract to keep the world moving during provider latency.
- Live public conversation events now carry subsequent spoken lines, spaced two simulation minutes apart. Exact repeated turns end the conversation; the prompt asks speakers to answer before introducing another question.
- ICA concurrency is configurable (engine default 4; API 2 per instance). API scaling is capped at 3 instances with request concurrency 8, limiting aggregate provider pressure. This is backpressure for the existing 1,000-agent product, not a claim of unlimited scale.
- Empty focus reports show no recorded answers, rather than implying no opinion change.

## Operational limits

Embedding credit remains exhausted until the provider account is topped up; lexical fallback is less precise than vector search. Existing unrendered conversations and missing survey ballots cannot be reconstructed. The engine remains a single writer using its existing lease and checkpoint handoff. Public speech playback is ephemeral across restarts; persisted transcripts remain available.

## Verification

Regression tests cover count/percentage formatting, HTML escaping, all starter questions with the model unavailable, keyword search, memory isolation during embedding outages, interview outage responses, and queued jobs that expire without freezing the world. A Chromium check exercised the Ask button and verified the 163 count visually without a percent sign. Final test and deployed smoke-check outcomes are recorded in the delivery message.
