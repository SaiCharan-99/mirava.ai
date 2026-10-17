"""Map assets: determinism, road-graph connectivity, places/sites/stores validation, site geometry."""

import hashlib
import json
from pathlib import Path

import pytest

from shared.schemas.world import Site
from tools.mapgen import build
from world.map import load_map
from world.sites import best_ots, ots

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "assets" / "maps"
OUTS = ["maps/indiranagar.tmj", "maps/roadgraph.json", "maps/places.json", "maps/sites.json", "maps/stores.json",
        "tiles/city.png"]


def digest(root: Path) -> dict[str, str]:
    return {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in OUTS}


@pytest.fixture(scope="module")
def wm():
    return load_map(MAPS)


@pytest.mark.slow
def test_mapgen_deterministic_and_matches_committed(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    build.build(tmp_path / "a")
    build.build(tmp_path / "b")
    a, b = digest(tmp_path / "a"), digest(tmp_path / "b")
    assert a == b
    assert a == digest(ROOT / "assets"), "committed map assets are stale: run `make map`"


def test_roadgraph_fully_connected(wm):
    assert len(wm.nodes) > 1000
    assert wm.reachable(0) == len(wm.nodes)


def test_shortest_path_walk(wm):
    a, b = wm.nearest_node(100, 100), wm.nearest_node(2200, 2300)
    path = wm.shortest_path(a, b)
    assert path[0] == a and path[-1] == b and len(path) > 10


def test_places_valid_and_complete(wm):
    kinds = {p.kind for p in wm.places}
    assert {"home", "office", "techpark", "shop", "cafe", "restaurant", "store", "school", "gym", "park", "metro",
            "bus_stop", "news_vendor", "mall"} <= kinds
    assert len({p.place_id for p in wm.places}) == len(wm.places)
    assert all(p.entrances and p.capacity >= 2 for p in wm.places)
    stores = {s.name: s for s in wm.stores}
    assert {"Digital Bazaar", "ElectroHub", "PhoneWorld", "ShopKart"} <= set(stores)
    for name in ("Digital Bazaar", "ElectroHub", "PhoneWorld"):
        assert wm.place_by_id[stores[name].place_id].kind == "store"


def test_no_real_business_names_in_commercial_places(wm):
    raw = json.loads((ROOT / "assets/osm/indiranagar.osm.json").read_text(encoding="utf-8"))
    real = {e["tags"]["name"] for e in raw["elements"] if e.get("tags", {}).get("name")
            and ("shop" in e["tags"] or e["tags"].get("amenity") in ("cafe", "restaurant", "fast_food"))}
    assert not [p.name for p in wm.places if p.kind in ("shop", "cafe", "restaurant", "office") and p.name in real]


def test_sites_inventory(wm):
    assert 50 <= len(wm.sites) <= 70
    assert len({s.site_id for s in wm.sites}) == len(wm.sites)
    assert {"billboard", "unipole", "bus_shelter", "metro_panel", "facade_screen"} <= {s.kind for s in wm.sites}
    assert "S-100FT-07" in wm.site_by_id


SITE = Site(site_id="S-T-01", kind="billboard", x=0, y=0, facings=[0.0], width_m=12.2, height_m=6.1, lit=True,
            cone_half_angle_deg=40, max_distance_m=120, rate_card_inr_week=60000, area_label="test")


def test_ots_in_front_and_looking():
    o = ots(SITE, 0.0, 0.0, -50.0, 180.0)  # 50 m north of a north-facing board, walking south towards it
    assert o is not None and o.in_cone and o.distance_m == 50


def test_ots_behind_board():
    assert ots(SITE, 0.0, 0.0, 50.0, 0.0) is None  # south of a north-facing board


def test_ots_out_of_range():
    assert ots(SITE, 0.0, 0.0, -130.0, 180.0) is None


def test_ots_heading_away():
    assert ots(SITE, 0.0, 0.0, -50.0, 0.0) is None  # in the cone but walking north, away from it


def test_ots_cone_edge_and_two_faces():
    assert ots(SITE, 0.0, 30.0, -40.0, 216.0) is not None   # ~37° off the face axis
    assert ots(SITE, 0.0, 60.0, -30.0, 243.0) is None        # ~63° off: outside the 40° cone
    two = SITE.model_copy(update={"facings": [0.0, 180.0]})
    f, o = best_ots(two, 0.0, 60.0, 0.0)
    assert f == 180.0 and o.distance_m == 60
