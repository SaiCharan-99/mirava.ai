"""Genesis: marginals, determinism, households, relationships, phones, personas, special agents."""

from collections import Counter

import numpy as np
import pytest

from population.genesis import build_world, profiles_of
from population.persona import card_tokens
from population.possessions import affordability
from population.relationships import degrees
from population.sampler import expected_marginals, sample_people


@pytest.fixture(scope="module")
def world():
    return build_world(1000, 4271)


def test_marginals_within_3pp():
    people = sample_people(1000, 4271)
    exp = expected_marginals(1000)
    for attr, col in (("age_band", "band"), ("gender", "gender"), ("occupation", "occupation"),
                      ("income_band", "income_band")):
        got = Counter(p[col] for p in people)
        for k, share in exp[attr].items():
            assert abs(got.get(k, 0) / 1000 - share) <= 0.03, (attr, k)


def test_same_seed_same_agents():
    a = sample_people(300, 7)
    b = sample_people(300, 7)
    assert a == b
    assert a != sample_people(300, 8)


def test_households_and_graph(world):
    hh = world["households"]
    members = [m for h in hh for m, _ in h["members"]]
    assert sorted(members) == list(range(1000))
    assert 330 <= len(hh) <= 500
    d = degrees(world["edges"], 1000)
    assert (d == 0).sum() == 0
    assert 11 <= d.mean() <= 16
    undirected = [e for e in world["edges"] if e.kind != "follower"]
    assert all(e.a < e.b for e in undirected)
    assert len({(e.a, e.b) for e in undirected}) == len(undirected)


def test_phone_age_distribution(world):
    ages = np.array([p["phone_age"] for p in world["people"]])
    assert 2.0 <= float(np.median(ages)) <= 3.0
    assert 0.15 <= float((ages > 5).mean()) <= 0.20


def test_special_agents(world):
    roles = Counter(p["special_role"] for p in world["people"])
    assert roles["reviewer"] == 10 and roles["salesperson"] == 8 and roles["news_desk"] == 1
    sellers = [p for p in world["people"] if p["special_role"] == "salesperson"]
    assert all(p["workplace_place_id"] for p in sellers)


def test_personas_and_routines(world):
    profs = profiles_of(world)
    for p in profs:
        assert card_tokens(p.persona_card) <= 150
        assert p.name.split()[0] in p.persona.bio_first_person and str(p.age) in p.persona.bio_first_person
        assert p.routine_id
    assert all(affordability(p.money.model_dump(), 20000)["share_of_income"] >= 0 for p in profs)


async def test_agents_latest_view_counts_old_phones(tmp_path):
    from pathlib import Path

    from engine.events import DuckDBSink
    from population.genesis import run_genesis
    from shared.bq import DuckDBShim
    from shared.files import LocalFiles
    from shared.settings import Settings
    from shared.store import MemoryStoreBackend

    s = Settings(duckdb_path=str(tmp_path / "a.duckdb"), gcs_bucket_worlds="w")
    sink = DuckDBSink(s)
    await run_genesis(1000, 4271, store=MemoryStoreBackend(), files=LocalFiles(str(tmp_path)), sink=sink, llm=None,
                      settings=s)
    db: DuckDBShim = sink.db
    db.con.execute(db.translate(Path("infra/bigquery/views/agents_latest.sql").read_text(), "mirava"))
    n = db.query("SELECT COUNT(*) AS n FROM agents_latest WHERE phone_age_years > 5")[0]["n"]
    w = build_world(1000, 4271)
    assert n == sum(1 for p in w["people"] if round(p["phone_age"], 2) > 5)
