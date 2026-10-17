"""`make map`: OSM extract → Tiled map (8 m tiles), road graph, places, hoarding sites, stores, tileset.

Deterministic: same extract + config ⇒ byte-identical outputs. Coordinates are metres from the bbox's north-west
corner (x east, y south); Tiled pixels are 2 px per metre (16 px tiles of 8 m).
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from shared.schemas.world import Place, Site, Store
from tools.mapgen import tileset
from tools.mapgen.tileset import GID

SRC = Path("assets/osm/indiranagar.osm.json")
OVERRIDES = Path("config/places_overrides.yaml")
TILE_M = 8.0
PX_PER_M = tileset.TILE / TILE_M
ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"

# road classes → half-width (m) of asphalt, sidewalk extra, allowed modes
ROADS: dict[str, tuple[float, float, list[str]]] = {
    "trunk": (11.0, 3.0, ["walk", "two_wheeler", "car", "auto", "bus"]),
    "primary": (11.0, 3.0, ["walk", "two_wheeler", "car", "auto", "bus"]),
    "secondary": (7.5, 3.0, ["walk", "two_wheeler", "car", "auto", "bus"]),
    "tertiary": (6.0, 2.5, ["walk", "two_wheeler", "car", "auto", "bus"]),
    "residential": (4.2, 0.0, ["walk", "two_wheeler", "car", "auto"]),
    "living_street": (4.0, 0.0, ["walk", "two_wheeler", "car", "auto"]),
    "unclassified": (4.2, 0.0, ["walk", "two_wheeler", "car", "auto"]),
    "service": (3.6, 0.0, ["walk", "two_wheeler", "car"]),
    "footway": (2.0, 0.0, ["walk"]),
    "path": (2.0, 0.0, ["walk"]),
    "pedestrian": (3.0, 0.0, ["walk"]),
    "steps": (1.5, 0.0, ["walk"]),
}
LINK = {"primary_link": "primary", "secondary_link": "secondary", "tertiary_link": "tertiary", "trunk_link": "trunk"}
ARTERIAL = {"trunk", "primary", "secondary", "tertiary"}
LABELS = {"100 Feet Road": "100 Feet Road", "Chinmaya Mission Hospital Road": "CMH Road",
          "12th Main Road": "12th Main", "Indiranagar Double Road": "Double Road", "80 Feet Road": "80 Feet Road",
          "Swamy Vivekananda Road": "Swamy Vivekananda Road", "Old Airport Road": "Old Airport Road"}
AREA = {"100 Feet Road": "100FT", "Chinmaya Mission Hospital Road": "CMH", "12th Main Road": "12M",
        "Indiranagar Double Road": "DBL", "80 Feet Road": "80FT", "Swamy Vivekananda Road": "SVR",
        "Old Airport Road": "OAR"}
SITE_SPEC = {  # kind → width_m, height_m, cone half-angle, max distance, base ₹/week
    "billboard": (12.2, 6.1, 40.0, 120.0, 60000),
    "unipole": (18.3, 6.1, 45.0, 150.0, 90000),
    "bus_shelter": (1.8, 1.2, 60.0, 40.0, 18000),
    "metro_panel": (3.0, 2.0, 55.0, 55.0, 35000),
    "facade_screen": (9.0, 5.0, 50.0, 90.0, 120000),
}
HOURS = {"shop": (600, 1290), "cafe": (480, 1380), "restaurant": (690, 1380), "office": (540, 1140),
         "techpark": (480, 1260), "store": (630, 1290), "school": (480, 930), "college": (480, 1020),
         "gym": (330, 1320), "park": (330, 1260), "metro": (300, 1380), "news_vendor": (330, 660),
         "mall": (600, 1320)}
WEEK = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SHOP_NAMES = ["Masala Corner", "Bake Studio", "Opticals", "Pharmacy", "Juice Bar", "Tailor", "Book Nook", "Sweets",
              "Florist", "Salon", "Hardware", "Bakery", "Sports Hub", "Chaat Point", "Mobile Repair", "Kirana"]
CAFE_NAMES = ["Brew & Byte", "Filter Kaapi House", "Café Bloom", "Tea Trails", "Bean Lane", "Kaapi Kone"]
FOOD_NAMES = ["Dosa Lane", "Noodle Bar", "Biryani House", "Hoppers", "Thali Point", "Momo Stop", "Grill Yard"]


def h01(*parts: object) -> float:
    """Deterministic pseudo-random float in [0, 1) from parts."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16) / 16**12


def r1(v: float) -> float:
    """Round to 0.1 m for compact, stable output."""
    return round(float(v), 1)


# ---------------------------------------------------------------- loading & projection

@dataclass
class Osm:
    """Parsed extract in local metres."""

    bbox: tuple[float, float, float, float]
    width_m: float
    height_m: float
    nodes: dict[int, tuple[float, float]]
    node_tags: dict[int, dict[str, str]]
    ways: list[dict]
    rings: list[tuple[dict, list[tuple[float, float]]]] = field(default_factory=list)  # (tags, polygon) areas


def load(src: Path = SRC) -> Osm:
    """Read the Overpass JSON and project to metres from the NW corner."""
    raw = json.loads(src.read_text(encoding="utf-8"))
    south, west, north, east = raw["bbox"]
    lat0 = math.radians((south + north) / 2)
    kx, ky = 111320.0 * math.cos(lat0), 110574.0

    def proj(lat: float, lon: float) -> tuple[float, float]:
        return ((lon - west) * kx, (north - lat) * ky)

    nodes: dict[int, tuple[float, float]] = {}
    node_tags: dict[int, dict[str, str]] = {}
    ways: list[dict] = []
    rels: list[dict] = []
    for e in raw["elements"]:
        if e["type"] == "node":
            nodes[e["id"]] = proj(e["lat"], e["lon"])
            if e.get("tags"):
                node_tags[e["id"]] = e["tags"]
        elif e["type"] == "way":
            ways.append(e)
        elif e["type"] == "relation":
            rels.append(e)
    osm = Osm((south, west, north, east), (east - west) * kx, (north - south) * ky, nodes, node_tags, [])
    way_by_id = {w["id"]: w for w in ways}
    for w in sorted(ways, key=lambda w: w["id"]):
        pts = [nodes[n] for n in w.get("nodes", []) if n in nodes]
        if len(pts) < 2:
            continue
        osm.ways.append({"id": w["id"], "tags": w.get("tags", {}), "nodes": [n for n in w["nodes"] if n in nodes],
                         "pts": pts})
        if w.get("tags") and len(pts) >= 4 and w["nodes"][0] == w["nodes"][-1]:
            osm.rings.append((w["tags"], pts))
    for r in sorted(rels, key=lambda r: r["id"]):
        tags = r.get("tags", {})
        if tags.get("type") != "multipolygon":
            continue
        outer = [way_by_id[m["ref"]] for m in r.get("members", []) if m["type"] == "way" and m.get("role") == "outer"
                 and m["ref"] in way_by_id]
        for ring in _join_rings([w["nodes"] for w in outer]):
            pts = [nodes[n] for n in ring if n in nodes]
            if len(pts) >= 4:
                osm.rings.append((tags, pts))
    return osm


def _join_rings(parts: list[list[int]]) -> list[list[int]]:
    """Join open way segments into closed rings by matching endpoints."""
    parts = [list(p) for p in parts if len(p) >= 2]
    rings = []
    while parts:
        cur = parts.pop(0)
        changed = True
        while cur[0] != cur[-1] and changed:
            changed = False
            for i, p in enumerate(parts):
                if p[0] == cur[-1]:
                    cur += p[1:]
                elif p[-1] == cur[-1]:
                    cur += p[::-1][1:]
                elif p[-1] == cur[0]:
                    cur = p[:-1] + cur
                elif p[0] == cur[0]:
                    cur = p[::-1][:-1] + cur
                else:
                    continue
                parts.pop(i)
                changed = True
                break
        if cur[0] == cur[-1]:
            rings.append(cur)
    return rings


# ---------------------------------------------------------------- geometry helpers

def area(poly: list[tuple[float, float]]) -> float:
    """Polygon area (m²)."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def centroid(poly: list[tuple[float, float]]) -> tuple[float, float]:
    """Vertex-mean centroid (good enough for small footprints)."""
    pts = poly[:-1] if poly[0] == poly[-1] else poly
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def inside(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    """Even-odd point-in-polygon."""
    x, y = pt
    res = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            res = not res
    return res


def bearing(dx: float, dy: float) -> float:
    """Compass bearing of a vector in map space (0 = north, clockwise; y points south)."""
    return math.degrees(math.atan2(dx, -dy)) % 360


def seg_point(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float, float]:
    """Closest point on segment ab to p → (x, y, distance)."""
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    cx, cy = ax + t * vx, ay + t * vy
    return cx, cy, math.hypot(px - cx, py - cy)


# ---------------------------------------------------------------- raster

class Raster:
    """Tile grid helpers over the map extent."""

    def __init__(self, width_m: float, height_m: float) -> None:
        self.w = math.ceil(width_m / TILE_M)
        self.h = math.ceil(height_m / TILE_M)
        self.cx = (np.arange(self.w) + 0.5) * TILE_M
        self.cy = (np.arange(self.h) + 0.5) * TILE_M

    def layer(self, fill: int = 0) -> np.ndarray:
        """Empty uint16 layer."""
        return np.full((self.h, self.w), fill, dtype=np.uint16)

    def fill_polygon(self, poly: list[tuple[float, float]]) -> list[tuple[int, int]]:
        """Tiles whose centre lies inside the polygon (scanline); always at least the centroid tile."""
        ys = [p[1] for p in poly]
        j0, j1 = max(0, int(min(ys) // TILE_M)), min(self.h - 1, int(max(ys) // TILE_M))
        out: list[tuple[int, int]] = []
        edges = list(zip(poly, poly[1:] + poly[:1], strict=True))
        for j in range(j0, j1 + 1):
            y = self.cy[j]
            xs = sorted((x1 + (y - y1) * (x2 - x1) / (y2 - y1)) for (x1, y1), (x2, y2) in edges
                        if (y1 > y) != (y2 > y))
            for k in range(0, len(xs) - 1, 2):
                i0 = max(0, math.ceil(xs[k] / TILE_M - 0.5))
                i1 = min(self.w - 1, math.floor(xs[k + 1] / TILE_M - 0.5))
                out += [(j, i) for i in range(i0, i1 + 1)]
        if not out:
            cx, cy = centroid(poly)
            i, j = int(cx // TILE_M), int(cy // TILE_M)
            if 0 <= i < self.w and 0 <= j < self.h:
                out.append((j, i))
        return out

    def stroke(self, pts: list[tuple[float, float]], half: float) -> np.ndarray:
        """Boolean mask of tiles whose centre is within `half` m of the polyline."""
        mask = np.zeros((self.h, self.w), dtype=bool)
        for a, b in zip(pts, pts[1:], strict=False):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            i0, i1 = max(0, int((x0 - half) // TILE_M)), min(self.w - 1, int((x1 + half) // TILE_M))
            j0, j1 = max(0, int((y0 - half) // TILE_M)), min(self.h - 1, int((y1 + half) // TILE_M))
            if i0 > i1 or j0 > j1:
                continue
            X, Y = np.meshgrid(self.cx[i0:i1 + 1], self.cy[j0:j1 + 1])
            vx, vy = b[0] - a[0], b[1] - a[1]
            L2 = vx * vx + vy * vy
            t = np.zeros_like(X) if L2 == 0 else np.clip(((X - a[0]) * vx + (Y - a[1]) * vy) / L2, 0, 1)
            d = np.hypot(X - (a[0] + t * vx), Y - (a[1] + t * vy))
            mask[j0:j1 + 1, i0:i1 + 1] |= d <= half
        return mask


# ---------------------------------------------------------------- road graph

def road_class(tags: dict) -> str | None:
    """Normalised road class, or None when the way is not a usable road/path."""
    hw = tags.get("highway")
    if not hw:
        return None
    hw = LINK.get(hw, hw)
    if hw not in ROADS or tags.get("access") in ("private", "no") or tags.get("area") == "yes":
        return None
    return hw


def build_graph(osm: Osm) -> tuple[dict, dict[int, int], int]:
    """Undirected road graph inside the bbox, restricted to its largest connected component."""
    inb = {nid for nid, (x, y) in osm.nodes.items() if 0 <= x <= osm.width_m and 0 <= y <= osm.height_m}
    edges: dict[tuple[int, int], dict] = {}
    for w in osm.ways:
        cls = road_class(w["tags"])
        if cls is None:
            continue
        for a, b in zip(w["nodes"], w["nodes"][1:], strict=False):
            if a == b or a not in inb or b not in inb:
                continue
            key = (min(a, b), max(a, b))
            (xa, ya), (xb, yb) = osm.nodes[a], osm.nodes[b]
            cur = edges.get(key)
            if cur is None or list(ROADS).index(cls) < list(ROADS).index(cur["class"]):
                edges[key] = {"class": cls, "len_m": round(math.hypot(xb - xa, yb - ya), 2),
                              "modes": ROADS[cls][2], "name": w["tags"].get("name")}
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    comp: dict[int, int] = defaultdict(int)
    for n in parent:
        comp[find(n)] += 1
    main = max(sorted(comp), key=lambda r: comp[r])
    keep = sorted(n for n in parent if find(n) == main)
    idx = {osm_id: i for i, osm_id in enumerate(keep)}
    dropped = len(parent) - len(keep)
    graph = {
        "nodes": [{"id": idx[n], "x": r1(osm.nodes[n][0]), "y": r1(osm.nodes[n][1])} for n in keep],
        "edges": [{"a": idx[a], "b": idx[b], "len_m": e["len_m"], "class": e["class"], "modes": e["modes"],
                   **({"name": e["name"]} if e["name"] else {})}
                  for (a, b), e in sorted(edges.items()) if a in idx and b in idx],
    }
    return graph, idx, dropped


class EdgeIndex:
    """Grid-bucket index of graph edges for nearest-point queries."""

    def __init__(self, graph: dict, cell: float = 50.0) -> None:
        self.cell = cell
        self.n = [(n["x"], n["y"]) for n in graph["nodes"]]
        self.e = graph["edges"]
        self.b: dict[tuple[int, int], list[int]] = defaultdict(list)
        for k, e in enumerate(self.e):
            (xa, ya), (xb, yb) = self.n[e["a"]], self.n[e["b"]]
            for gx in range(int(min(xa, xb) // cell), int(max(xa, xb) // cell) + 1):
                for gy in range(int(min(ya, yb) // cell), int(max(ya, yb) // cell) + 1):
                    self.b[(gx, gy)].append(k)

    def nearest(self, x: float, y: float, classes: set[str] | None = None,
                radius: int = 3) -> tuple[float, float, float, dict] | None:
        """Closest point on any (optionally class-filtered) edge → (x, y, dist, edge)."""
        best = None
        gx, gy = int(x // self.cell), int(y // self.cell)
        for r in range(radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    for k in self.b.get((gx + dx, gy + dy), []):
                        e = self.e[k]
                        if classes and e["class"] not in classes:
                            continue
                        cx, cy, d = seg_point(x, y, self.n[e["a"]], self.n[e["b"]])
                        if best is None or d < best[2]:
                            best = (cx, cy, d, e)
            if best is not None and best[2] <= r * self.cell:
                return best
        return best


# ---------------------------------------------------------------- named roads

def named_polylines(osm: Osm) -> dict[str, list[list[tuple[float, float]]]]:
    """Arterial ways grouped by name, joined into continuous polylines (longest first)."""
    by_name: dict[str, list[list[int]]] = defaultdict(list)
    for w in osm.ways:
        cls = road_class(w["tags"])
        name = w["tags"].get("name")
        if cls in ARTERIAL and name:
            by_name[name].append(list(w["nodes"]))
    out: dict[str, list[list[tuple[float, float]]]] = {}
    for name, parts in sorted(by_name.items()):
        chains: list[list[int]] = []
        for p in parts:
            for c in chains:
                if c[-1] == p[0]:
                    c += p[1:]
                    break
                if c[0] == p[-1]:
                    c[:0] = p[:-1]
                    break
            else:
                chains.append(list(p))
        merged = True
        while merged:
            merged = False
            for i in range(len(chains)):
                for j in range(len(chains)):
                    if i != j and chains[i][-1] == chains[j][0]:
                        chains[i] += chains[j][1:]
                        chains.pop(j)
                        merged = True
                        break
                if merged:
                    break
        lines = [[osm.nodes[n] for n in c] for c in chains]
        out[name] = sorted(lines, key=lambda ln: -polyline_len(ln))
    return out


def polyline_len(pts: list[tuple[float, float]]) -> float:
    """Length of a polyline (m)."""
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:], strict=False))


def along(pts: list[tuple[float, float]], s: float) -> tuple[float, float, float]:
    """Point and bearing at distance s along a polyline."""
    acc = 0.0
    for a, b in zip(pts, pts[1:], strict=False):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if acc + L >= s and L > 0:
            t = (s - acc) / L
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), bearing(b[0] - a[0], b[1] - a[1])
        acc += L
    a, b = pts[-2], pts[-1]
    return b[0], b[1], bearing(b[0] - a[0], b[1] - a[1])


def clip_inside(osm: Osm, pts: list[tuple[float, float]], margin: float = 0.0) -> list[tuple[float, float]]:
    """Keep the longest run of polyline points inside the map."""
    runs, cur = [], []
    for x, y in pts:
        if margin <= x <= osm.width_m - margin and margin <= y <= osm.height_m - margin:
            cur.append((x, y))
        else:
            if len(cur) > 1:
                runs.append(cur)
            cur = []
    if len(cur) > 1:
        runs.append(cur)
    return max(runs, key=polyline_len) if runs else []


# ---------------------------------------------------------------- places

@dataclass
class Bld:
    """A building footprint with its classification."""

    osm_id: int
    poly: list[tuple[float, float]]
    btype: str
    tags: dict
    kind: str | None = None
    roof: str = "roof_generic"
    name: str | None = None
    pois: list[dict] = field(default_factory=list)


POI_KIND = {"cafe": "cafe", "restaurant": "restaurant", "fast_food": "restaurant", "school": "school",
            "college": "college", "university": "college", "kindergarten": "school"}


def poi_kind(tags: dict) -> str | None:
    """Place kind implied by a POI's tags."""
    if tags.get("shop") == "mall":
        return "mall"
    if tags.get("amenity") in POI_KIND:
        return POI_KIND[tags["amenity"]]
    if tags.get("leisure") in ("fitness_centre", "sports_centre"):
        return "gym"
    if "shop" in tags:
        return "shop"
    if "office" in tags:
        return "office"
    return None


def classify_buildings(osm: Osm) -> list[Bld]:
    """Buildings with kind (home/shop/office/…) and roof tile, using contained POIs and landuse."""
    landuse = [(t.get("landuse"), p) for t, p in osm.rings if t.get("landuse")]
    blds = [Bld(i, p, t.get("building", "yes"), t) for i, (t, p) in enumerate(osm.rings)
            if "building" in t and t.get("building") not in ("roof", "no")]
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for k, b in enumerate(blds):
        xs, ys = [p[0] for p in b.poly], [p[1] for p in b.poly]
        for gx in range(int(min(xs) // 40), int(max(xs) // 40) + 1):
            for gy in range(int(min(ys) // 40), int(max(ys) // 40) + 1):
                grid[(gx, gy)].append(k)
    for nid, tags in sorted(osm.node_tags.items()):
        if poi_kind(tags) is None:
            continue
        x, y = osm.nodes[nid]
        for k in grid.get((int(x // 40), int(y // 40)), []):
            if inside((x, y), blds[k].poly):
                blds[k].pois.append({"id": nid, **tags})
                break
    for b in blds:
        t, bt = b.tags, b.btype
        k = poi_kind(t) or next((poi_kind(p) for p in b.pois if poi_kind(p)), None)
        if bt in ("school",):
            k = "school"
        elif bt in ("college", "university"):
            k = "college"
        elif bt == "office" and k is None:
            k = "office"
        elif bt in ("retail", "commercial") and k is None:
            k = "shop" if bt == "retail" else "office"
        if k is None and bt in ("residential", "apartments", "house", "detached", "yes", "semidetached_house",
                                "terrace", "dormitory"):
            c = centroid(b.poly)
            lu = next((u for u, p in landuse if inside(c, p)), None)
            k = "home" if lu in (None, "residential") or bt != "yes" else None
            if k is None and lu in ("commercial", "retail"):
                k = "office" if area(b.poly) > 400 else "shop"
        b.kind = k
        b.roof = {"home": f"roof_res_{int(h01('roof', b.osm_id) * 8)}", "shop": "roof_shop", "cafe": "roof_cafe",
                  "restaurant": "roof_cafe", "office": "roof_office", "school": "roof_school",
                  "college": "roof_school", "gym": "roof_generic", "mall": "roof_mall"}.get(k or "", "roof_generic")
        if bt == "hospital" or t.get("amenity") == "hospital":
            b.roof = "roof_hospital"
        elif bt in ("temple", "church", "mosque") or t.get("amenity") == "place_of_worship":
            b.roof = "roof_temple"
        elif bt == "construction":
            b.roof, b.kind = "roof_construction", None
        elif bt == "retail" and b.kind == "shop":
            b.roof = "roof_retail"
    return blds


def place_name(kind: str, key: object, counters: dict[str, int]) -> str:
    """Fictional, generic names for commercial places (never real businesses)."""
    i = counters[kind] = counters.get(kind, 0) + 1
    if kind == "shop":
        return SHOP_NAMES[int(h01("shop", key) * len(SHOP_NAMES))]
    if kind == "cafe":
        return CAFE_NAMES[int(h01("cafe", key) * len(CAFE_NAMES))]
    if kind == "restaurant":
        return FOOD_NAMES[int(h01("food", key) * len(FOOD_NAMES))]
    return {"home": "Home", "office": f"Office {i}", "school": f"School {i}", "college": f"College {i}",
            "gym": f"Gym {i}", "bus_stop": "Bus stop", "park": "Park"}.get(kind, kind.title())


def capacity(kind: str, a: float) -> int:
    """Rough occupancy by kind and footprint area."""
    per = {"home": 30, "shop": 15, "cafe": 4, "restaurant": 4, "office": 10, "techpark": 8, "store": 12,
           "school": 6, "college": 6, "gym": 8, "park": 40, "mall": 6, "metro": 3}.get(kind)
    if per is None:
        return 6
    return max(2, min(3000, int(a / per)))


def hours(kind: str) -> dict[str, tuple[int, int]] | None:
    """Opening hours per weekday (sim minutes of day)."""
    if kind not in HOURS:
        return None
    o, c = HOURS[kind]
    days = WEEK[:6] if kind in ("office", "school", "college") else WEEK
    return {d: (o, c) for d in days}


def square(x: float, y: float, half: float) -> list[tuple[float, float]]:
    """Axis-aligned square polygon."""
    return [(r1(x - half), r1(y - half)), (r1(x + half), r1(y - half)), (r1(x + half), r1(y + half)),
            (r1(x - half), r1(y + half))]


def build_places(osm: Osm, blds: list[Bld], eidx: EdgeIndex, roads: dict, overrides: dict) -> tuple[list[Place],
                                                                                                    list[Store]]:
    """Places from OSM + overrides; entrances are the nearest point on the road graph."""
    W, H = osm.width_m, osm.height_m
    raw: list[dict] = []
    station = next(((osm.nodes[n], t) for n, t in sorted(osm.node_tags.items())
                    if t.get("railway") == "station" and t.get("name") == "Indiranagar"), None)
    used: set[int] = set()
    for ov in overrides.get("overrides", []):
        kind = ov["kind"]
        if "station" in ov["anchor"]:
            if station is None:
                continue
            (sx, sy), _ = station
            dx, dy = ov["anchor"].get("offset_m", [15, 15])
            raw.append({"kind": kind, "name": ov["name"], "poly": square(sx + dx, sy + dy, ov.get("kiosk_m", 4) / 2),
                        "tags": {"fictional": "yes"}, "ov": ov})
            continue
        line = clip_inside(osm, roads.get(ov["anchor"]["road"], [[]])[0] if roads.get(ov["anchor"]["road"]) else [])
        if not line:
            continue
        ax, ay, _ = along(line, polyline_len(line) * ov["anchor"]["at"])
        okb = set(ov.get("building", ["yes"]))
        cands = [b for b in blds if b.osm_id not in used and b.btype in okb and area(b.poly) > 120]
        if not cands:
            continue
        if ov.get("largest_within_m"):
            near = [b for b in cands if math.dist(centroid(b.poly), (ax, ay)) <= ov["largest_within_m"]]
            pick = max(near or cands, key=lambda b: (area(b.poly), -b.osm_id))
        else:
            pick = min(cands, key=lambda b: (math.dist(centroid(b.poly), (ax, ay)), b.osm_id))
        used.add(pick.osm_id)
        pick.roof = {"store": "roof_store", "techpark": "roof_techpark", "mall": "roof_mall"}.get(kind, pick.roof)
        tags = {"fictional": "yes", **({"store_id": ov["store_id"], "format": ov["format"]} if "store_id" in ov else {})}
        raw.append({"kind": kind, "name": ov["name"], "poly": pick.poly, "tags": tags, "ov": ov})
    in_map = [b for b in blds if b.osm_id not in used and b.kind]
    for b in in_map:
        c = centroid(b.poly)
        if 0 <= c[0] <= W and 0 <= c[1] <= H:
            raw.append({"kind": b.kind, "name": None, "poly": b.poly, "tags": {"building": b.btype}, "key": b.osm_id})
    in_bld = {p["id"] for b in blds for p in b.pois}
    for nid, tags in sorted(osm.node_tags.items()):
        x, y = osm.nodes[nid]
        if not (0 <= x <= W and 0 <= y <= H):
            continue
        if tags.get("highway") == "bus_stop":
            raw.append({"kind": "bus_stop", "name": "Bus stop", "poly": square(x, y, 3), "tags": {}, "key": nid})
        elif tags.get("railway") == "station" and tags.get("name"):
            raw.append({"kind": "metro", "name": f"{tags['name']} Metro", "poly": square(x, y, 20),
                        "tags": {"station": tags["name"]}, "key": nid})
        elif nid not in in_bld and poi_kind(tags):
            raw.append({"kind": poi_kind(tags), "name": None, "poly": square(x, y, 5), "tags": {}, "key": nid})
    for t, p in osm.rings:
        if t.get("leisure") in ("park", "garden") or t.get("landuse") == "recreation_ground":
            c = centroid(p)
            if 0 <= c[0] <= W and 0 <= c[1] <= H and area(p) > 600:
                raw.append({"kind": "park", "name": t.get("name") or None, "poly": p, "tags": {"leisure": "park"},
                            "key": round(c[0] * 10 + c[1])})
    order = {k: i for i, k in enumerate(["store", "techpark", "mall", "metro", "news_vendor", "bus_stop", "office",
                                         "shop", "cafe", "restaurant", "school", "college", "gym", "park", "home"])}
    raw.sort(key=lambda r: (order[r["kind"]], round(centroid(r["poly"])[1]), round(centroid(r["poly"])[0])))
    counters: dict[str, int] = {}
    places: list[Place] = []
    stores: list[Store] = []
    for i, r in enumerate(raw):
        poly = [(r1(x), r1(y)) for x, y in (r["poly"][:-1] if r["poly"][0] == r["poly"][-1] else r["poly"])]
        cx, cy = centroid(poly)
        ent = eidx.nearest(cx, cy)
        entrances = [(r1(ent[0]), r1(ent[1]))] if ent else [(r1(cx), r1(cy))]
        pid = f"P-{i:04d}"
        name = r["name"] or place_name(r["kind"], r.get("key", i), counters)
        places.append(Place(place_id=pid, kind=r["kind"], name=name, polygon=poly, entrances=entrances,
                            capacity=capacity(r["kind"], area(poly)), opening_hours=hours(r["kind"]),
                            tags={k: str(v) for k, v in r["tags"].items()}))
        ov = r.get("ov") or {}
        if ov.get("store_id"):
            stores.append(Store(store_id=ov["store_id"], name=ov["name"], kind=ov["store_kind"], place_id=pid,
                                staff=[], opening_hours=tuple(overrides.get("store_hours", [630, 1290])), stock={}))
    for o in overrides.get("online_stores", []):
        stores.append(Store(store_id=o["store_id"], name=o["name"], kind=o["store_kind"], place_id=None, staff=[],
                            opening_hours=(0, 1440), stock={}))
    return places, stores


# ---------------------------------------------------------------- hoarding sites

def build_sites(osm: Osm, graph: dict, roads: dict, places: list[Place], target: int = 60) -> list[Site]:
    """~60 deterministic OOH sites: junctions, arterial runs, metro, bus shelters, façades."""
    cands: list[tuple[int, str, float, float, list[float], str, str, bool]] = []  # prio, kind, x, y, facings, road, label, primary
    lines = {n: clip_inside(osm, ls[0], 15) for n, ls in roads.items() if n in AREA and ls}
    lines = {n: ln for n, ln in lines.items() if ln and polyline_len(ln) > 200}
    names = sorted(lines)
    # 1) junctions between two named arterials
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            best = None
            for p in lines[a][::2]:
                for q in lines[b][::2]:
                    d = math.dist(p, q)
                    if best is None or d < best[0]:
                        best = (d, p)
            if best and best[0] < 25:
                x, y, brg = nearest_on(lines[a], best[1])
                ox, oy = offset(x, y, brg, 16)
                cands.append((0, "billboard", ox, oy, [round(brg) % 360, round(brg + 180) % 360], a,
                              f"{LABELS[a]} × {LABELS[b]}", a in ("100 Feet Road",)))
    # 2) metro station panels (pillars either side, along CMH Road)
    for p in places:
        if p.kind == "metro":
            cx, cy = centroid(p.polygon)
            line = lines.get("Chinmaya Mission Hospital Road")
            x, y, brg = nearest_on(line, (cx, cy)) if line else (cx, cy, 90.0)
            for side, f in ((-1, brg), (1, brg + 180)):
                ox, oy = offset(x, y, brg + 90, 7 * side)
                ox, oy = ox + 25 * side * math.sin(math.radians(brg)), oy - 25 * side * math.cos(math.radians(brg))
                cands.append((1, "metro_panel", ox, oy, [round(f) % 360], "Chinmaya Mission Hospital Road",
                              f"{p.name} · pillar {'W' if side < 0 else 'E'}", True))
    # 3) façade screens on big commercial buildings next to an arterial
    big = sorted((p for p in places if p.kind in ("mall", "office", "shop", "store", "techpark")),
                 key=lambda p: (-area(p.polygon), p.place_id))
    n_fac = 0
    for p in big:
        if n_fac >= 6:
            break
        c = centroid(p.polygon)
        road, (x, y, brg), d = closest_road(lines, c)
        if road and d < 45:
            face = bearing(x - c[0], y - c[1])
            cands.append((1, "facade_screen", r1(c[0] + (x - c[0]) * 0.55), r1(c[1] + (y - c[1]) * 0.55),
                          [round(face) % 360], road, f"{LABELS[road]} · {p.name} façade", True))
            n_fac += 1
    # 4) bus shelters on arterials
    for p in places:
        if p.kind == "bus_stop":
            c = centroid(p.polygon)
            road, (x, y, brg), d = closest_road(lines, c)
            if road and d < 30:
                face = bearing(x - c[0], y - c[1]) if d > 1 else brg + 90
                cands.append((2, "bus_shelter", c[0], c[1], [round(face) % 360], road, f"{LABELS[road]} bus stop",
                              road == "100 Feet Road"))
    # 5) arterial runs every ~150 m, alternating sides, facing oncoming (left-hand) traffic
    for name in names:
        ln = lines[name]
        L = polyline_len(ln)
        k = 0
        s = 75.0
        while s < L - 40:
            x, y, brg = along(ln, s)
            side = 1 if k % 2 == 0 else -1  # +1 = left of travel direction `brg`
            half = ROADS["primary" if name == "100 Feet Road" else "secondary"][0]
            ox, oy = offset(x, y, brg - 90 * side, half + 5)
            travel = brg if side == 1 else brg + 180  # near-lane traffic on that side (drive on the left)
            kind = "unipole" if name in ("100 Feet Road", "Swamy Vivekananda Road") and k % 3 == 2 else "billboard"
            cands.append((3, kind, ox, oy, [round(travel + 180) % 360], name, f"{LABELS[name]} · {int(s)} m",
                          name == "100 Feet Road"))
            s += 150.0
            k += 1
    # select with spacing: fixed quotas per kind, then arterial runs round-robin across roads
    chosen: list[tuple] = []
    quota = {"metro_panel": 4, "facade_screen": 6, "bus_shelter": 8}

    def take(c: tuple) -> bool:
        if not (5 <= c[2] <= osm.width_m - 5 and 5 <= c[3] <= osm.height_m - 5) or len(chosen) >= target:
            return False
        gap = 22 if c[1] in ("metro_panel", "bus_shelter") else 60
        if any(math.dist((c[2], c[3]), (o[2], o[3])) < gap for o in chosen):
            return False
        chosen.append(c)
        return True

    for c in sorted((c for c in cands if c[0] < 3), key=lambda c: (c[0], round(c[3]), round(c[2]))):
        if c[1] in quota:
            if sum(1 for o in chosen if o[1] == c[1]) < quota[c[1]]:
                take(c)
        else:
            take(c)
    runs = {n: [c for c in cands if c[0] == 3 and c[5] == n] for n in names}
    weight = {"100 Feet Road": 3, "Chinmaya Mission Hospital Road": 2, "12th Main Road": 2}
    while len(chosen) < target and any(runs.values()):
        for n in names:
            for _ in range(weight.get(n, 1)):
                if runs[n]:
                    take(runs[n].pop(0))
    # ids per area, ordered north→south then west→east
    sites: list[Site] = []
    per: dict[str, int] = defaultdict(int)
    for c in sorted(chosen, key=lambda c: (AREA[c[5]], round(c[3]), round(c[2]))):
        prio, kind, x, y, facings, road, label, primary = c
        area_code = AREA[road]
        per[area_code] += 1
        w, h, half, dist, base = SITE_SPEC[kind]
        rate = int(round(base * (1.3 if primary else 1.0) * (0.85 + 0.3 * h01("rate", x, y)) / 500) * 500)
        sites.append(Site(site_id=f"S-{area_code}-{per[area_code]:02d}", kind=kind, x=r1(x), y=r1(y),
                          facings=[float(f) for f in facings], width_m=w, height_m=h, lit=True,
                          cone_half_angle_deg=half, max_distance_m=dist, rate_card_inr_week=rate, area_label=label))
    return sites


def nearest_on(line: list[tuple[float, float]], p: tuple[float, float]) -> tuple[float, float, float]:
    """Closest point on a polyline and the road bearing there."""
    best = None
    for a, b in zip(line, line[1:], strict=False):
        x, y, d = seg_point(p[0], p[1], a, b)
        if best is None or d < best[2]:
            best = (x, y, d, bearing(b[0] - a[0], b[1] - a[1]))
    assert best is not None
    return best[0], best[1], best[3]


def closest_road(lines: dict, p: tuple[float, float]) -> tuple[str | None, tuple[float, float, float], float]:
    """Nearest named arterial to p."""
    best: tuple[str | None, tuple[float, float, float], float] = (None, (p[0], p[1], 0.0), 1e9)
    for name, ln in sorted(lines.items()):
        x, y, brg = nearest_on(ln, p)
        d = math.dist((x, y), p)
        if d < best[2]:
            best = (name, (x, y, brg), d)
    return best


def offset(x: float, y: float, brg: float, dist: float) -> tuple[float, float]:
    """Move `dist` m along compass bearing `brg`."""
    r = math.radians(brg)
    return x + dist * math.sin(r), y - dist * math.cos(r)


# ---------------------------------------------------------------- tiled map

def build_tiles(osm: Osm, blds: list[Bld], places: list[Place], sites: list[Site], graph: dict,
                roads: dict) -> dict:
    """Rasterise all layers and assemble the Tiled JSON."""
    R = Raster(osm.width_m, osm.height_m)
    ground = R.layer(GID["grass"])
    landuse = R.layer()
    for t, p in osm.rings:
        lu, le, nat = t.get("landuse"), t.get("leisure"), t.get("natural")
        gid = None
        if lu in ("residential",):
            gid = GID["lot"]
        elif lu in ("commercial", "retail", "industrial", "construction"):
            gid = GID["lot_commercial"]
        elif lu in ("religious", "education") or t.get("amenity") in ("school", "hospital", "college"):
            gid = GID["lot_civic"]
        elif le in ("park", "garden", "playground") or lu in ("grass", "recreation_ground", "village_green"):
            gid = GID["park"]
        elif le == "pitch":
            gid = GID["pitch"]
        elif nat == "water" or lu in ("reservoir", "basin"):
            gid = GID["water"]
        if gid:
            for j, i in R.fill_polygon(p):
                if gid in (GID["park"], GID["pitch"], GID["water"]) or landuse[j, i] == 0:
                    landuse[j, i] = gid
    roads_l = R.layer()
    asphalt = np.zeros((R.h, R.w), dtype=bool)
    way_cls = [(w, road_class(w["tags"])) for w in osm.ways]
    order = ["footway", "path", "steps", "pedestrian", "service", "living_street", "residential", "unclassified",
             "tertiary", "secondary", "primary", "trunk"]
    for cls in order:
        half, side, _ = ROADS[cls]
        for w, c in way_cls:
            if c != cls or w["tags"].get("bridge") == "yes" and cls in ("footway", "path"):
                continue
            if side:
                sw = R.stroke(w["pts"], half + side) & ~asphalt
                roads_l[sw & (roads_l == 0)] = GID["sidewalk"]
            m = R.stroke(w["pts"], max(half, 2.0 if cls in ("footway", "path", "steps") else 4.0))
            gid = {"primary": "road_primary", "trunk": "road_primary", "secondary": "road_secondary",
                   "tertiary": "road_secondary", "service": "service_road", "footway": "footway", "path": "footway",
                   "steps": "footway", "pedestrian": "footway"}.get(cls, "road_residential")
            if cls in ("footway", "path", "steps"):
                m &= ~asphalt
            roads_l[m] = GID[gid]
            if cls not in ("footway", "path", "steps"):
                asphalt |= m
    # centre-line dashes on primary/secondary
    for w, c in way_cls:
        if c not in ("primary", "trunk", "secondary"):
            continue
        for a, b in zip(w["pts"], w["pts"][1:], strict=False):
            brg = bearing(b[0] - a[0], b[1] - a[1]) % 180
            horiz = 45 <= brg < 135
            m = R.stroke([a, b], 2.9) & asphalt
            jj, ii = np.nonzero(m)
            for j, i in zip(jj, ii, strict=True):
                if (i if horiz else j) % 2 == 0:
                    pri = c in ("primary", "trunk")
                    roads_l[j, i] = GID[("lane_pri_" if pri else "lane_sec_") + ("h" if horiz else "v")]
    rail = R.layer()
    for w in osm.ways:
        t = w["tags"]
        if t.get("railway") in ("subway", "light_rail", "rail") and t.get("bridge") in ("viaduct", "yes"):
            rail[R.stroke(w["pts"], 4.5)] = GID["viaduct"]
    for t, p in osm.rings:
        if t.get("railway") == "platform" or (t.get("public_transport") == "station" and "building" in t):
            for j, i in R.fill_polygon(p):
                rail[j, i] = GID["station"]
    buildings = R.layer()
    for b in sorted(blds, key=lambda b: area(b.poly), reverse=True):
        for j, i in R.fill_polygon(b.poly):
            if not asphalt[j, i]:
                buildings[j, i] = GID[b.roof]
    decor = R.layer()
    for w, c in way_cls:
        if c not in ("primary", "secondary", "trunk"):
            continue
        half, side, _ = ROADS[c]
        edge = R.stroke(w["pts"], half + side) & ~R.stroke(w["pts"], half + side - 3.5)
        jj, ii = np.nonzero(edge & (roads_l == GID["sidewalk"]) & (buildings == 0) & (rail == 0))
        for j, i in zip(jj, ii, strict=True):
            if (i + 2 * j) % 3 == 0:
                decor[j, i] = GID["tree_a" if (i * 7 + j) % 2 else "tree_b"]
    pj, pi = np.nonzero(landuse == GID["park"])
    for j, i in zip(pj, pi, strict=True):
        if buildings[j, i] == 0 and roads_l[j, i] == 0 and h01("tree", i, j) < 0.28:
            decor[j, i] = GID["tree_a" if h01("tv", i, j) < 0.5 else "tree_b"]
    for p in places:
        if p.kind in ("bus_stop", "news_vendor"):
            cx, cy = centroid(p.polygon)
            i, j = int(cx // TILE_M), int(cy // TILE_M)
            if 0 <= i < R.w and 0 <= j < R.h:
                decor[j, i] = GID["bus_stop" if p.kind == "bus_stop" else "kiosk"]
    # labels: one per named road (the longest in-map stretch), rotated along the road, clear of place labels
    labels, oid = [], 1
    busy = [centroid(p.polygon) for p in places if p.kind in ("metro", "store", "techpark", "mall")]
    for name, disp in LABELS.items():
        if name not in roads:
            continue
        ln = clip_inside(osm, roads[name][0], 40)
        if not ln or polyline_len(ln) < 150:
            continue
        L = polyline_len(ln)
        spots = [along(ln, L * f) for f in (0.5, 0.38, 0.62, 0.28, 0.72)]
        x, y, brg = next((s for s in spots if all(math.dist(s[:2], b) > 140 for b in busy)), spots[0])
        busy.append((x, y))
        rot = (brg - 90) % 180
        rot = rot - 180 if rot > 90 else rot
        labels.append({"id": oid, "name": disp, "type": "road_label", "x": r1(x * PX_PER_M), "y": r1(y * PX_PER_M),
                       "rotation": round(rot, 1), "width": 0, "height": 0, "visible": True,
                       "properties": [{"name": "osm_name", "type": "string", "value": name}],
                       "text": {"text": disp, "fontfamily": "Inter", "pixelsize": 14, "color": "#e7edf5",
                                "halign": "center", "valign": "center", "wrap": False}})
        oid += 1
    for p in places:
        if p.kind in ("metro", "store", "techpark", "mall") or (p.kind == "park" and p.name and area(p.polygon) > 3000):
            cx, cy = centroid(p.polygon)
            labels.append({"id": oid, "name": p.name, "type": f"place_label:{p.kind}", "x": r1(cx * PX_PER_M),
                           "y": r1(cy * PX_PER_M), "rotation": 0, "width": 0, "height": 0, "visible": True,
                           "properties": [{"name": "place_id", "type": "string", "value": p.place_id}],
                           "text": {"text": p.name, "fontfamily": "Inter", "pixelsize": 11, "color": "#b3c0d0",
                                    "halign": "center", "valign": "center", "wrap": False}})
            oid += 1
    # lights (night): street lights at junctions of non-footway roads, shop fronts, offices, lit sites
    deg: dict[int, int] = defaultdict(int)
    for e in graph["edges"]:
        if e["class"] not in ("footway", "path", "steps"):
            deg[e["a"]] += 1
            deg[e["b"]] += 1
    lights = []
    for n in graph["nodes"]:
        if deg[n["id"]] >= 3:
            lights.append(("street", n["x"], n["y"], 22.0))
    for p in places:
        if p.kind in ("shop", "cafe", "restaurant", "store", "mall", "office", "techpark", "metro", "gym"):
            (ex, ey), (cx, cy) = p.entrances[0], centroid(p.polygon)
            fx, fy = cx + (ex - cx) * 0.6, cy + (ey - cy) * 0.6
            lights.append(({"office": "window", "techpark": "window"}.get(p.kind, "shopfront"), r1(fx), r1(fy),
                           14.0 if p.kind not in ("mall", "store", "metro") else 26.0))
    for s in sites:
        if s.lit:
            lights.append(("site", s.x, s.y, 18.0))
    light_objs = [{"id": oid + k, "name": "", "type": kind, "x": r1(x * PX_PER_M), "y": r1(y * PX_PER_M),
                   "point": True, "rotation": 0, "width": 0, "height": 0, "visible": True,
                   "properties": [{"name": "radius_m", "type": "float", "value": rad}]}
                  for k, (kind, x, y, rad) in enumerate(sorted(lights, key=lambda v: (v[2], v[1], v[0])))]
    oid += len(light_objs)

    def tl(lid: int, name: str, arr: np.ndarray) -> dict:
        return {"data": arr.ravel().tolist(), "height": R.h, "id": lid, "name": name, "opacity": 1, "type": "tilelayer",
                "visible": True, "width": R.w, "x": 0, "y": 0}

    s, w_, n_, e_ = osm.bbox
    return {
        "compressionlevel": -1, "height": R.h, "width": R.w, "infinite": False, "orientation": "orthogonal",
        "renderorder": "right-down", "tiledversion": "1.10.2", "type": "map", "version": "1.10",
        "tilewidth": tileset.TILE, "tileheight": tileset.TILE, "nextlayerid": 9, "nextobjectid": oid,
        "properties": [
            {"name": "attribution", "type": "string", "value": ATTRIBUTION},
            {"name": "bbox", "type": "string", "value": f"{s},{w_},{n_},{e_}"},
            {"name": "meters_per_tile", "type": "float", "value": TILE_M},
            {"name": "width_m", "type": "float", "value": r1(osm.width_m)},
            {"name": "height_m", "type": "float", "value": r1(osm.height_m)},
        ],
        "tilesets": [tileset.tiled_tileset("../tiles/city.png")],
        "layers": [tl(1, "ground", ground), tl(2, "landuse", landuse), tl(3, "roads", roads_l), tl(4, "rail", rail),
                   tl(5, "buildings", buildings), tl(6, "decor", decor),
                   {"draworder": "topdown", "id": 7, "name": "labels", "objects": labels, "opacity": 1,
                    "type": "objectgroup", "visible": True, "x": 0, "y": 0},
                   {"draworder": "topdown", "id": 8, "name": "lights", "objects": light_objs, "opacity": 1,
                    "type": "objectgroup", "visible": True, "x": 0, "y": 0}],
    }


# ---------------------------------------------------------------- main

def dump(path: Path, obj: object) -> None:
    """Stable compact JSON (LF, UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


def reachable(graph: dict) -> int:
    """Number of nodes reachable from node 0 (Dijkstra-free BFS)."""
    adj: dict[int, list[int]] = defaultdict(list)
    for e in graph["edges"]:
        adj[e["a"]].append(e["b"])
        adj[e["b"]].append(e["a"])
    seen = {0}
    q = [0]
    while q:
        u = heapq.heappop(q)
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                heapq.heappush(q, v)
    return len(seen)


def build(out_root: Path = Path("assets"), src: Path = SRC) -> dict:
    """Run the whole pipeline; returns stats."""
    osm = load(src)
    overrides = yaml.safe_load(OVERRIDES.read_text(encoding="utf-8"))
    graph, _, dropped = build_graph(osm)
    eidx = EdgeIndex(graph)
    roads = named_polylines(osm)
    blds = classify_buildings(osm)
    places, stores = build_places(osm, blds, eidx, roads, overrides)
    sites = build_sites(osm, graph, roads, places)
    tmj = build_tiles(osm, blds, places, sites, graph, roads)
    tileset.render(out_root / "tiles" / "city.png")
    maps = out_root / "maps"
    dump(maps / "indiranagar.tmj", tmj)
    dump(maps / "roadgraph.json", graph)
    dump(maps / "places.json", [p.model_dump(mode="json") for p in places])
    dump(maps / "sites.json", [s.model_dump(mode="json") for s in sites])
    dump(maps / "stores.json", [s.model_dump(mode="json") for s in stores])
    kinds: dict[str, int] = defaultdict(int)
    for p in places:
        kinds[p.kind] += 1
    stats = {"tiles": f"{tmj['width']}x{tmj['height']}", "width_m": r1(osm.width_m), "height_m": r1(osm.height_m),
             "nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "dropped_disconnected_nodes": dropped,
             "reachable_from_0": reachable(graph), "places": len(places), "place_kinds": dict(sorted(kinds.items())),
             "sites": len(sites), "stores": len(stores), "labels": [o["name"] for o in tmj["layers"][6]["objects"]
                                                                   if o["type"] == "road_label"]}
    dump(maps / "mapgen-stats.json", stats)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="assets", help="output root (maps/, tiles/)")
    a = ap.parse_args()
    print(json.dumps(build(Path(a.out)), indent=1, ensure_ascii=False))
