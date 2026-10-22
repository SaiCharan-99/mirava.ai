"""Every ready-made poll preset in the builder produces a survey body POST /surveys accepts."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shared.store import MemoryStoreBackend

PRESETS = json.loads((Path(__file__).parent.parent / "web/src/lib/pollPresets.json").read_text(encoding="utf-8"))
PRODUCTS = ["Pulse 5", "Orbit S"]


def _body(p: dict) -> dict:
    """Mirror web/src/lib/presets.ts applyPreset with two live products."""
    qs = []
    for q in p["questions"]:
        q = dict(q)
        if q.get("option_source") == "products":
            q["options"] = PRODUCTS[:4]
            if q["type"] == "multi":
                q["max_select"] = min(q.get("max_select") or 2, len(q["options"]))
        qs.append(q)
    return {"title": p["title"], "topic": p["topic"], "mode": "focus_group", "questions": qs,
            "product_ids": ["pulse-5", "orbit-s"] if p["use_products"] else []}


@pytest.mark.parametrize("p", PRESETS, ids=[p["id"] for p in PRESETS])
def test_preset_is_valid_survey(p, monkeypatch):
    import api.main as m
    import api.surveys as sv

    store = MemoryStoreBackend()
    monkeypatch.setattr(sv, "store", lambda: store)
    monkeypatch.setattr(sv, "_eligible", lambda c, i: 300)
    monkeypatch.setattr(sv, "_engine_state", lambda: {"t": 1})
    assert 4 <= len(p["questions"]) <= 5
    r = TestClient(m.app).post("/api/surveys", json=_body(p))
    assert r.status_code == 200, r.text
    assert len(store.get("surveys", r.json()["survey_id"])["questions"]) == len(p["questions"])
