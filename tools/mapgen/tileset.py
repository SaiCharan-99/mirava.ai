"""Pixel-art tileset `assets/tiles/city.png` (16 px tiles) in the mockup's map palette — deterministic."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw

TILE = 16
COLS = 8
ROWS = 8

# tile id (0-based local id; gid = id + 1) → name. Order is part of the map contract; append only.
TILES: list[str] = [
    "grass", "lot", "lot_commercial", "park", "water", "pitch", "sidewalk", "road_primary",
    "road_secondary", "road_residential", "lane_pri_h", "lane_pri_v", "lane_sec_h", "lane_sec_v", "footway",
    "viaduct", "station",
    "roof_res_0", "roof_res_1", "roof_res_2", "roof_res_3", "roof_res_4", "roof_res_5", "roof_res_6", "roof_res_7",
    "roof_shop", "roof_retail", "roof_office", "roof_school", "roof_hospital", "roof_mall", "roof_temple",
    "roof_construction", "roof_cafe", "roof_store", "roof_generic", "roof_techpark",
    "tree_a", "tree_b", "bus_stop", "kiosk", "zebra_h", "zebra_v", "service_road", "lot_civic",
]
GID = {name: i + 1 for i, name in enumerate(TILES)}

ROAD_CLASS = {"road_primary": "primary", "road_secondary": "secondary", "road_residential": "residential",
              "lane_pri_h": "primary", "lane_pri_v": "primary", "lane_sec_h": "secondary", "lane_sec_v": "secondary",
              "footway": "footway", "sidewalk": "sidewalk", "service_road": "service", "zebra_h": "crossing",
              "zebra_v": "crossing", "viaduct": "rail"}
WALKABLE = {"grass", "lot", "lot_commercial", "park", "pitch", "sidewalk", "road_primary", "road_secondary",
            "road_residential", "lane_pri_h", "lane_pri_v", "lane_sec_h", "lane_sec_v", "footway", "station",
            "bus_stop", "kiosk", "zebra_h", "zebra_v", "service_road", "lot_civic"}

RES_ROOFS = ["#b4543f", "#a0623d", "#8f7a5a", "#6d7f8f", "#9b8f7e", "#c0786a", "#7c8b6a", "#b08968"]


def _rng(name: str):
    """Deterministic byte stream per tile name."""
    i = 0
    while True:
        yield from hashlib.sha256(f"{name}:{i}".encode()).digest()
        i += 1


def _speckle(d: ImageDraw.ImageDraw, ox: int, oy: int, name: str, light: str, dark: str, n: int = 10) -> None:
    r = _rng(name)
    for _ in range(n):
        x, y, c = next(r) % TILE, next(r) % TILE, next(r)
        d.point((ox + x, oy + y), fill=light if c % 2 else dark)


def _roof(d: ImageDraw.ImageDraw, ox: int, oy: int, col: str, name: str) -> None:
    d.rectangle([ox, oy, ox + 15, oy + 15], fill=col)
    d.line([ox, oy, ox + 15, oy], fill=_shade(col, 1.18))
    d.line([ox, oy + 15, ox + 15, oy + 15], fill=_shade(col, 0.78))
    _speckle(d, ox, oy, name, _shade(col, 1.08), _shade(col, 0.9), 6)


def _shade(hexcol: str, k: float) -> str:
    h = hexcol.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(*tuple(max(0, min(255, round(v * k))) for v in (r, g, b)))


def draw_tile(d: ImageDraw.ImageDraw, ox: int, oy: int, name: str) -> None:
    """Paint one 16×16 tile."""
    sq = [ox, oy, ox + 15, oy + 15]
    flat = {"grass": "#26321f", "lot": "#3a3631", "lot_commercial": "#3d3a37", "park": "#2f5a2c", "water": "#4f86a8",
            "sidewalk": "#5a5d63", "road_primary": "#3a3f47", "road_secondary": "#363b43",
            "road_residential": "#31353b", "footway": "#8a7f63", "service_road": "#34383e", "lot_civic": "#4b5a3a"}
    if name in flat:
        d.rectangle(sq, fill=flat[name])
        if name in ("grass", "park", "lot", "lot_commercial", "lot_civic"):
            _speckle(d, ox, oy, name, _shade(flat[name], 1.15), _shade(flat[name], 0.85), 12)
        if name == "sidewalk":
            d.line([ox, oy + 7, ox + 15, oy + 7], fill="#54575d")
            d.line([ox + 7, oy, ox + 7, oy + 15], fill="#54575d")
        if name == "water":
            d.line([ox + 3, oy + 5, ox + 8, oy + 5], fill="#6aa0c0")
            d.line([ox + 8, oy + 11, ox + 13, oy + 11], fill="#6aa0c0")
        return
    if name == "pitch":
        d.rectangle(sq, fill="#3b6b35")
        d.line([ox + 7, oy, ox + 7, oy + 15], fill="#9fc79a")
        return
    if name.startswith("lane_"):
        base = "#3a3f47" if "pri" in name else "#363b43"
        d.rectangle(sq, fill=base)
        if name.endswith("_h"):
            d.rectangle([ox + 2, oy + 7, ox + 9, oy + 8], fill="#c9c38a")
        else:
            d.rectangle([ox + 7, oy + 2, ox + 8, oy + 9], fill="#c9c38a")
        return
    if name.startswith("zebra_"):
        d.rectangle(sq, fill="#3a3f47")
        for k in range(1, 16, 4):
            if name.endswith("_h"):
                d.rectangle([ox + k, oy + 3, ox + k + 1, oy + 12], fill="#cfd2d4")
            else:
                d.rectangle([ox + 3, oy + k, ox + 12, oy + k + 1], fill="#cfd2d4")
        return
    if name == "viaduct":
        d.rectangle(sq, fill="#9aa3ad")
        d.line([ox, oy + 1, ox + 15, oy + 1], fill="#c7cdd4")
        d.line([ox, oy + 8, ox + 15, oy + 8], fill="#6b7280")
        d.line([ox + 1, oy, ox + 1, oy + 15], fill="#c7cdd4")
        return
    if name == "station":
        d.rectangle(sq, fill="#b9c0c8")
        d.rectangle([ox, oy + 3, ox + 15, oy + 5], fill="#7c3aed")
        return
    if name.startswith("roof_res_"):
        _roof(d, ox, oy, RES_ROOFS[int(name[-1])], name)
        if int(name[-1]) % 3 == 0:
            d.rectangle([ox + 10, oy + 3, ox + 13, oy + 6], fill="#cbd5e1")  # water tank
        return
    roofs = {"roof_shop": "#55606d", "roof_retail": "#5b6472", "roof_office": "#46607e", "roof_school": "#c2703d",
             "roof_hospital": "#d7dbe0", "roof_mall": "#5a5f6b", "roof_temple": "#c9a24a",
             "roof_construction": "#6b6b5a", "roof_cafe": "#6b4f3a", "roof_store": "#2b3442",
             "roof_generic": "#76808c", "roof_techpark": "#3e5a7a"}
    if name in roofs:
        _roof(d, ox, oy, roofs[name], name)
        if name in ("roof_office", "roof_techpark"):
            for wy in range(3, 14, 5):
                for wx in range(3, 14, 4):
                    d.rectangle([ox + wx, oy + wy, ox + wx + 1, oy + wy + 1], fill="#6d8fb3")
        elif name == "roof_hospital":
            d.rectangle([ox + 7, oy + 3, ox + 8, oy + 12], fill="#ef4444")
            d.rectangle([ox + 3, oy + 7, ox + 12, oy + 8], fill="#ef4444")
        elif name == "roof_store":
            d.rectangle([ox + 1, oy + 1, ox + 14, oy + 4], fill="#0ea5e9")
        elif name in ("roof_shop", "roof_retail"):
            d.rectangle([ox + 1, oy + 1, ox + 14, oy + 3], fill="#f59e0b" if name == "roof_shop" else "#ef4444")
        elif name == "roof_mall":
            d.rectangle([ox + 2, oy + 2, ox + 13, oy + 13], fill="#666c79")
        return
    if name in ("tree_a", "tree_b"):
        col = "#2d5a27" if name == "tree_a" else "#356b2d"
        d.ellipse([ox + 3, oy + 4, ox + 14, oy + 15], fill=(0, 0, 0, 64))
        d.ellipse([ox + 2, oy + 2, ox + 13, oy + 13], fill=col)
        d.ellipse([ox + 4, oy + 4, ox + 7, oy + 7], fill=_shade(col, 1.35))
        return
    if name == "bus_stop":
        d.rectangle([ox + 1, oy + 5, ox + 14, oy + 10], fill="#64748b")
        d.rectangle([ox + 1, oy + 5, ox + 14, oy + 6], fill="#facc15")
        return
    if name == "kiosk":
        d.rectangle([ox + 3, oy + 3, ox + 12, oy + 12], fill="#78350f")
        d.rectangle([ox + 3, oy + 3, ox + 12, oy + 5], fill="#f5b041")
        return
    raise ValueError(name)


def render(path: Path) -> None:
    """Write the tileset PNG."""
    img = Image.new("RGBA", (COLS * TILE, ROWS * TILE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    for i, name in enumerate(TILES):
        draw_tile(d, (i % COLS) * TILE, (i // COLS) * TILE, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=False)


def tiled_tileset(image_rel: str) -> dict:
    """Embedded Tiled tileset with `walkable` / `road_class` tile properties."""
    tiles = []
    for i, name in enumerate(TILES):
        props = [{"name": "name", "type": "string", "value": name},
                 {"name": "walkable", "type": "bool", "value": name in WALKABLE}]
        if name in ROAD_CLASS:
            props.append({"name": "road_class", "type": "string", "value": ROAD_CLASS[name]})
        tiles.append({"id": i, "properties": props})
    return {"columns": COLS, "firstgid": 1, "image": image_rel, "imageheight": ROWS * TILE, "imagewidth": COLS * TILE,
            "margin": 0, "name": "city", "spacing": 0, "tilecount": COLS * ROWS, "tileheight": TILE,
            "tilewidth": TILE, "tiles": tiles}
