"""Generate web/src/visual-fixtures/survey-fixture.json from a seeded local fake-backend survey run (addendum B9).
Usage: uv run python -m tools.survey_fixture"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from engine.survey import recruit
from engine.survey.session import Budget, Person, TableRunner
from mind.decision import FakeDecision
from shared.llm import FakeGemini
from shared.schemas.survey import Question, Survey

NAMES = ["Ravi Kumar", "Meera Iyer", "Arjun Rao", "Kavya Nair", "Imran Khan", "Priya Sharma", "Rohan Bhat", "Ananya Das",
         "Vikram Shetty", "Sneha Reddy", "Farhan Ali", "Lakshmi Menon", "Karthik Gowda", "Divya Pillai", "Suresh Babu",
         "Neha Joshi"]
COLORS = ["#eab308", "#14b8a6", "#3b82f6", "#f97316", "#0ea5e9", "#ec4899", "#22c55e", "#a78bfa", "#f43f5e", "#84cc16",
          "#06b6d4", "#f59e0b", "#6366f1", "#10b981", "#ef4444", "#8b5cf6"]
QS = [{"question_id": "q1", "text": "What matters most to you in the Pulse 5?", "type": "single",
       "options": ["Battery life", "Price", "Camera", "Brand trust"]},
      {"question_id": "q2", "text": "How likely are you to buy the Pulse 5 in the next 3 months?", "type": "scale",
       "scale": {"min": 1, "max": 5, "low_label": "not at all", "high_label": "certainly"}},
      {"question_id": "q3", "text": "What would make you switch to the Pulse 5?", "type": "open"}]
MEM = ["My phone dies before lunch these days.", "I saw the Pulse 5 hoarding on 100 Feet Road.",
       "The Digital Bazaar salesman said the battery lasts two days.", "Rohan's review called it the battery king.",
       "EMI would make it easier this month.", "My cousin's camera photos look much better than mine."]


def people() -> list[Person]:
    """16 seeded participants (2 tables of 8)."""
    out = []
    for i, n in enumerate(NAMES):
        out.append(Person(agent_id=100 + i, name=n.split()[0], age=22 + (i * 3) % 34, occupation="resident",
                          income_band=["<25k", "25-50k", "50k-1L", "1-2L"][i % 4],
                          big5={"O": 0.3 + 0.04 * i % 0.6, "C": 0.25 + (i * 7 % 10) / 14, "E": 0.15 + (i * 5 % 11) / 13,
                                "A": 0.2 + (i * 3 % 9) / 11, "N": 0.3 + (i % 5) / 10},
                          style="friendly, direct", card=f"{n}, resident of Indiranagar.", phone=f"Brand mid, {2 + i % 6}.0 years, ok",
                          attitude=-0.4 + (i % 9) / 10, experience="purchased" if i == 3 else ("store_visit" if i in (0, 9) else None),
                          memories=[MEM[i % len(MEM)], MEM[(i + 2) % len(MEM)]]))
    return out


async def main() -> None:
    s = Survey(survey_id="sv-demo", title="Pulse 5 — price and battery", mode="focus_group", product_id="pulse-5",
               topic="Pulse 5", questions=[Question.model_validate(q) for q in QS], max_participants=16, table_size=8)
    ps = people()
    tables = [ps[:8], ps[8:]]
    out_tables, items, answers = [], [], []
    for k, seats in enumerate(tables):
        tid = f"T{k + 1}"
        r = TableRunner(s.model_dump(), tid, f"fg-{tid}", seats, llm=FakeGemini(), decider=FakeDecision(),
                        cfg=recruit.cfg(), seed=4271, budget=Budget(left=5.0), product_name="Pulse 5")
        await r.run()
        out_tables.append({"table_id": tid, "seats": [p.agent_id for p in seats]})
        items += [{**{k2: v for k2, v in it.items() if k2 != "text"}, "table_id": tid} for it in r.items]
        answers += [a.model_dump() for a in r.answers]
    agents = [{"agent_id": p.agent_id, "name": NAMES[i], "age": p.age, "color": COLORS[i], "phone": p.phone,
               "income_band": p.income_band, "experience": p.experience} for i, p in enumerate(ps)]
    rsvp = [{"agent_id": p.agent_id, "rsvp": "accepted", "reason": "Free in the evening and curious about the battery."
             if i % 3 else "The incentive helps, and it's close by.", "arrived": i < 13} for i, p in enumerate(ps)]
    data = {"_source": "tools/survey_fixture.py (seeded fake-backend run)", "survey": {**s.model_dump(mode="json"),
            "status": "completed", "venue_name": "Research Lounge", "start_label": "Day 23 · Tue 18:00",
            "eligible": 187, "expected_attendance": 16, "estimate_usd": recruit.estimate(s, 16)["usd"]},
            "tables": out_tables, "agents": agents, "rsvp": rsvp, "items": items, "answers": answers}
    path = Path(__file__).resolve().parents[1] / "web" / "src" / "visual-fixtures" / "survey-fixture.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"survey fixture -> {path} ({len(items)} items, {len(answers)} answers)")


if __name__ == "__main__":
    asyncio.run(main())
