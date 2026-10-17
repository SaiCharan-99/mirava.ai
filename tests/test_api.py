"""API hello endpoints."""

from fastapi.testclient import TestClient

from api.main import app


def test_healthz_both_paths():
    c = TestClient(app)
    for path in ("/healthz", "/api/healthz"):
        r = c.get(path)
        assert r.status_code == 200 and r.json()["ok"] is True


def test_world_state_label():
    assert TestClient(app).get("/api/world/state").json()["label"] == "Day 23 · Tue 08:40"
