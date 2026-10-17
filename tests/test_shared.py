"""Settings, model-id guard, time helpers, schemas, DuckDB shim, local files."""

import subprocess
from pathlib import Path

import pytest
from pydantic import SecretStr

from shared import models
from shared import time as simtime
from shared.bq import DuckDBShim
from shared.files import LocalFiles
from shared.schemas import ALL_MODELS, Event
from shared.schemas.events import make_event_id
from shared.settings import Settings
from shared.store import MemoryStoreBackend

ROOT = Path(__file__).resolve().parents[1]


def test_settings_mask_key():
    s = Settings(openrouter_api_key=SecretStr("sk-or-SECRET123"), _env_file=None)
    assert "SECRET123" not in repr(s) and "SECRET123" not in str(s.model_dump())
    assert s.has_openrouter_key


def test_settings_defaults():
    s = Settings(_env_file=None, llm_backend="fake")
    assert s.gcp_region == "asia-south1" and s.daily_cap_usd == 15 and s.world_agents == 1000


def test_model_ids_are_gemini3():
    assert models.MODEL_PRO == "google/gemini-3.1-pro-preview"
    assert all("gemini-3" in m for m in models.CHAT_MODELS)


def test_no_gemini25_anywhere():
    """Guard: no `gemini-2.5` model string in any code/config file (docs may state the rule itself)."""
    banned = "gemini-" + "2.5"
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    code = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".yaml", ".yml", ".toml", ".sh"}
    hits = []
    for f in files:
        p = ROOT / f
        if f == "tests/test_shared.py" or p.suffix not in code or not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        if banned in p.read_text(encoding="utf-8", errors="ignore"):
            hits.append(f)
    assert hits == []


def test_time_fmt():
    t = simtime.at(23, 8 + 40 / 60)
    assert simtime.fmt(t) == "Day 23 · Tue 08:40"
    assert simtime.fmt(0) == "Day 1 · Mon 00:00"
    assert simtime.day_of(1440) == 2


def test_all_schemas_build_json_schema():
    for m in ALL_MODELS:
        assert m.model_json_schema()["title"] == m.__name__


def test_event_id_deterministic():
    assert make_event_id("thought", 31720, 7, 0) == "thought:31720:7:0"
    assert make_event_id("budget", 60, None, 1) == "budget:60::1"


def test_duckdb_shim_roundtrip():
    db = DuckDBShim(":memory:", dataset="mirava")
    e = Event(event_id="activity:1:7:0", t=1, day=1, t_real="2026-10-17T00:00:00Z", kind="activity", agent_id=7,
              payload={"activity": "commute"})
    row = e.model_dump()
    assert db.insert("events", [row]) == 1
    db.insert("events", [row])  # idempotent
    rows = db.query("SELECT kind, count(*) AS n FROM `proj.mirava.events` WHERE agent_id = @a GROUP BY kind",
                    {"a": 7})
    assert rows == [{"kind": "activity", "n": 1}]


def test_memory_store_and_files(tmp_path):
    st = MemoryStoreBackend()
    st.set("agents", "7", {"name": "Meera"})
    st.set("agents", "7", {"age": 29}, merge=True)
    assert st.get("agents", "7") == {"name": "Meera", "age": 29}
    f = LocalFiles(str(tmp_path))
    f.write("worlds", "a/b.json", b"{}")
    assert f.exists("worlds", "a/b.json") and f.read("worlds", "a/b.json") == b"{}"
    with pytest.raises(ValueError):
        f.write("worlds", "../../evil", b"x")
