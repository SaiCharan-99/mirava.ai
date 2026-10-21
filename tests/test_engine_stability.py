"""fix-E: tick-path I/O timeouts, hung-tick watchdog, governor counters in checkpoints, retired-product view filter."""

import asyncio
import time
from pathlib import Path

import pytest

import engine.loop as loop
from engine.events import DuckDBSink, NullSink
from engine.loop import Engine, io
from population.genesis import run_genesis
from shared.files import LocalFiles
from shared.settings import Settings
from shared.store import MemoryStoreBackend

N = 30


async def _engine(tmp_path) -> Engine:
    s = Settings(world_agents=N, world_seed=7, checkpoint_every_sim_minutes=60, gcs_bucket_worlds="w",
                 local_files_dir=str(tmp_path))
    store, files = MemoryStoreBackend(), LocalFiles(str(tmp_path))
    await run_genesis(N, 7, store=store, files=files, sink=NullSink(), llm=None, settings=s)
    e = Engine(s, store, files, NullSink(), social=False)
    e.boot()
    return e


async def test_io_times_out_on_a_hung_call():
    with pytest.raises(asyncio.TimeoutError):
        await io(time.sleep, 2, timeout=0.05)
    assert await io(lambda a, b: a + b, 1, 2) == 3


async def test_watchdog_skips_a_hung_tick_and_logs_stacks(tmp_path, monkeypatch, caplog):
    e = await _engine(tmp_path)
    monkeypatch.setattr(loop, "TICK_TIMEOUT_S", 0.05)

    async def hang() -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(e, "tick", hang)
    await e.guarded_tick()
    assert e.hung_ticks == 1 and "tick hung" in caplog.text and "--- task" in caplog.text
    assert e.state()["engine"]["hung_ticks"] == 1
    monkeypatch.undo()
    t = e.world.t
    await e.guarded_tick()              # the next tick runs normally
    assert e.world.t == t + 1


async def test_watchdog_survives_a_failing_tick(tmp_path, monkeypatch):
    e = await _engine(tmp_path)

    async def boom() -> None:
        raise RuntimeError("firestore down")

    monkeypatch.setattr(e, "tick", boom)
    await e.guarded_tick()
    assert e.hung_ticks == 1



async def test_governor_counters_survive_a_restart(tmp_path):
    e = await _engine(tmp_path)
    e.gov.record(0.25, "P1")
    e.gov.allow("P1", 0.0)
    e.gov.interactive_today = 0.5
    await e.save_checkpoint()
    before = e.gov.to_dict()
    e2 = Engine(e.s, e.store, e.files, NullSink(), social=False)
    e2.boot()
    after = e2.gov.to_dict()
    assert after["spent_today"] == before["spent_today"] > 0
    assert after["used"] == before["used"] and after["rendered"] + after["unrendered"] == before["rendered"] + before["unrendered"] >= 1
    assert after["interactive_today"] == 0.5


def test_default_views_retire_nothing(tmp_path):
    db = DuckDBSink(Settings(duckdb_path=str(tmp_path / "v.duckdb"))).db
    for v in sorted(Path("infra/bigquery/views").glob("*.sql")):
        db.con.execute(db.translate(v.read_text(encoding="utf-8"), "mirava"))
    assert db.query("SELECT COUNT(*) AS n FROM retired_products")[0]["n"] == 0


def test_views_drop_retired_products(tmp_path):
    db = DuckDBSink(Settings(duckdb_path=str(tmp_path / "v.duckdb"))).db

    def ev(i: int, kind: str, pid: str | None, payload: dict) -> dict:
        return {"event_id": f"e{i}", "t": i, "day": 1, "kind": kind, "agent_id": i, "other_id": None,
                "product_id": pid, "site_id": None, "rendered": True, "payload": payload,
                "t_real": f"2026-10-21T00:00:{i:02d}+00:00"}

    db.insert("events", [
        ev(1, "thought", "pixel-10a", {"text": "nice"}),
        ev(2, "thought", "pulse-5", {"text": "old"}),
        ev(3, "thought", "nova-x1", {"text": "old"}),
        ev(4, "purchase", None, {"option": "orbit-s"}),
        ev(5, "purchase", None, {"option": "pixel-10a"}),
        ev(6, "conversation", None, {"product_mentions": ["nova-x1"], "kind": "social"}),
        ev(7, "conversation", None, {"product_mentions": ["Nova X1"], "kind": "social"}),
        ev(8, "conversation", None, {"product_mentions": ["pixel-10a"], "kind": "social"}),
        ev(9, "launch", "pixel-10a", {}),
        ev(10, "launch", "nova-x1", {}),
    ])
    from infra.bigquery.init import RETIRED_VIEW, retired_ids, retired_sql

    assert {"pulse-5", "orbit-s", "nova-x1"} <= set(retired_ids())
    for v in sorted(Path("infra/bigquery/views").glob("*.sql")):
        sql = retired_sql(["pulse-5", "orbit-s", "nova-x1"]) if v.name == RETIRED_VIEW else v.read_text(encoding="utf-8")
        db.con.execute(db.translate(sql, "mirava"))
    assert [r["product_id"] for r in db.query("SELECT product_id FROM v_thoughts")] == ["pixel-10a"]
    assert [r["option"] for r in db.query("SELECT option FROM v_purchases")] == ["pixel-10a"]
    fh = db.query("SELECT product_id FROM v_first_heard")
    assert [r["product_id"] for r in fh] == ["pixel-10a"]


def test_book_cost_forwards_only_real_spend(monkeypatch):
    import api.main as m
    import api.products as p

    sent = []
    monkeypatch.setattr(p, "_engine_command", lambda cmd: sent.append(cmd))

    import threading

    monkeypatch.setattr(threading, "Thread", lambda target, args, daemon: type("X", (), {"start": lambda s: target(*args)})())
    from shared.llm import CostRecord, Usage

    m.book_cost(CostRecord("ask", "m", "interactive", Usage(cost_usd=0.002), False))
    m.book_cost(CostRecord("ask", "m", "interactive", Usage(cost_usd=0.0), False))
    m.book_cost(CostRecord("ask", "m", "interactive", Usage(cost_usd=0.5), True))
    assert sent == [{"type": "record_spend", "usd": 0.002, "purpose": "ask"}]
