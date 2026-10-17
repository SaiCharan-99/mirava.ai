"""Download the Indiranagar OSM extract via Overpass → assets/osm/indiranagar.osm.json (committed, ODbL)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BBOX = (12.962, 77.630, 12.984, 77.652)  # south, west, north, east
OUT = Path("assets/osm/indiranagar.osm.json")
ENDPOINTS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter")


def query(bbox: tuple[float, float, float, float] = BBOX) -> str:
    """Overpass QL for highways, rail, buildings, landuse, amenities, shops, leisure, transit."""
    b = ",".join(str(v) for v in bbox)
    keys = ["highway", "railway", "building", "landuse", "amenity", "shop", "leisure", "public_transport", "natural",
            "office", "tourism"]
    body = "\n".join(f'  nwr["{k}"]({b});' for k in keys)
    return f"[out:json][timeout:120];\n(\n{body}\n);\nout body;\n>;\nout skel qt;"


def fetch(q: str) -> dict:
    """POST the query to the first Overpass mirror that answers."""
    last = ""
    for url in ENDPOINTS:
        for attempt in range(2):
            try:
                r = httpx.post(url, data={"data": q}, timeout=180, headers={"User-Agent": "mirava.ai-mapgen/0.1"})
                if r.status_code == 200:
                    return r.json()
                last = f"{url} HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last = f"{url} {type(e).__name__}"
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"Overpass unreachable ({last}). Follow docs/setup/15-openstreetmap.md for a manual export.")


def main() -> int:
    """Fetch and save with stable key order (elements sorted by type, id)."""
    data = fetch(query())
    els = sorted(data.get("elements", []), key=lambda e: (e["type"], e["id"]))
    out = {"version": data.get("version"), "generator": data.get("generator"),
           "osm3s": data.get("osm3s", {}), "bbox": BBOX,
           "attribution": "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
           "elements": els}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"saved {OUT} · {len(els)} elements · {OUT.stat().st_size / 1e6:.1f} MB · "
          f"timestamp {out['osm3s'].get('timestamp_osm_base')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
