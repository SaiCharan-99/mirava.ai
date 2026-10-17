# 15 · OpenStreetMap extract for Indiranagar

**Needed from:** phase 1, **only if** `tools/mapgen/fetch_osm.py` can't reach the Overpass API from your machine (corporate proxy, firewall). The extract is committed to the repo, so this is done once.

**What and why:** the city map is generated from real OpenStreetMap streets, buildings and points of interest for Indiranagar, Bengaluru (bbox **south 12.962, west 77.630, north 12.984, east 77.652**). OSM data is © OpenStreetMap contributors, licensed under ODbL. The app shows this attribution on the map and in the Guide.

## Option A — Overpass Turbo (browser, 2 minutes)
1. Open **https://overpass-turbo.eu**.
2. Paste the query below and click **Run**:
```
[out:json][timeout:60];
(
  way["highway"](12.962,77.630,12.984,77.652);
  way["railway"](12.962,77.630,12.984,77.652);
  way["building"](12.962,77.630,12.984,77.652);
  way["landuse"](12.962,77.630,12.984,77.652);
  way["leisure"](12.962,77.630,12.984,77.652);
  node["amenity"](12.962,77.630,12.984,77.652);
  node["shop"](12.962,77.630,12.984,77.652);
  node["public_transport"](12.962,77.630,12.984,77.652);
  node["highway"="bus_stop"](12.962,77.630,12.984,77.652);
);
out body; >; out skel qt;
```
3. **Export → raw OSM data** (JSON). Save it as `assets/osm/indiranagar.osm.json` in the repo.

## Option B — openstreetmap.org export
openstreetmap.org → **Export** → **Manually select a different area** → enter the bbox → **Export** gives an `.osm` (XML) file. Save it as `assets/osm/indiranagar.osm`; mapgen accepts XML too.

## Verify
```bash
make map        # should print counts: road nodes/edges, buildings, places, sites (≈ 60), stores (3)
```
Record the extract date in PROGRESS.md §5. Commit the file. Never edit it by hand; re-export if needed.
