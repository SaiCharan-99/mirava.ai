"""`make seed-demo`: three fictional placeholder phones through the products API — Nova X1 ready, Pulse 5 and Orbit S live.

Needs api (:8000) and world-engine (:8100) running with a genesis world. Idempotent: existing products are kept.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

PRODUCTS = [
    {"name": "Nova X1", "brand": "Arcline", "price_inr": 89999, "launch_offer": "No-cost EMI from ₹7,500/month",
     "features": ["200MP main camera with multi-frame night mode", "5,000 mAh battery · 45 W charging", "6.7\" 120 Hz LTPO display", "7 years of OS updates · titanium frame"],
     "claims": ["The best camera ever put in a phone.", "All-day battery, guaranteed.", "7 years of OS updates."],
     "target_personas": ["Mobile photographers", "Young tech professionals", "Upgraders with phones > 4 yrs"],
     "strategy": {"key_message": "See the night.", "intensity": "medium", "flight_days": 21},
     "content": {"hoarding": "SEE THE NIGHT.", "bus_shelter": "Night shots that don't need a flash.",
                 "reel": ("After dark, Bengaluru changes. Most phones give up here. Nova X1 doesn't. 200MP. Night mode built in.",
                          ["Wide shot: 100 Feet Road at dusk", "A hand raises Nova X1 at a street-food stall", "Photo appears: crisp, no flash", "Montage: metro, rooftop, rain on glass", "Product + price card"]),
                 "newspaper": "The best camera ever put in a phone.", "store_display": "Try night mode here →",
                 "reviewer_kit": "Spec sheet: 200MP sensor, 5,000 mAh, 9–11 h mixed use, 7 years of updates. Embargo: launch day."},
     "launch": False},
    {"name": "Pulse 5", "brand": "Kestrel", "price_inr": 24999, "launch_offer": "Exchange bonus ₹3,000",
     "features": ["6,000 mAh battery · two-day life", "50MP camera", "6.5\" 90 Hz display"],
     "claims": ["Two days on one charge.", "The fastest phone in its class."],
     "target_personas": ["Students and budget buyers", "Upgraders with phones > 4 yrs"],
     "strategy": {"key_message": "Two days. One charge.", "intensity": "medium", "flight_days": 21},
     "content": {"hoarding": "TWO DAYS. ONE CHARGE.", "bus_shelter": "Pulse 5 · from ₹24,999",
                 "reel": ("Morning to midnight, then the next day too. Pulse 5 keeps going.", ["Alarm at 6 am", "Metro commute", "Late-night gaming", "Next morning: 38% left"]),
                 "newspaper": "The fastest phone in its class.", "store_display": "Feel the battery — try it here"},
     "launch": True},
    {"name": "Orbit S", "brand": "Lumen", "price_inr": 49999, "launch_offer": "Free earbuds at launch",
     "features": ["6.9 mm thin", "AMOLED 120 Hz", "32MP selfie camera"],
     "claims": ["Thin is the new smart.", "Never needs a case."],
     "target_personas": ["Style-conscious young professionals", "Fashion and design lovers"],
     "strategy": {"key_message": "Thin is the new smart.", "intensity": "low", "flight_days": 21},
     "content": {"hoarding": "THIN IS THE NEW SMART.", "reel": ("Slide it in a pocket and forget it's there.", ["Rooftop café", "Jacket pocket", "Mirror selfie"]),
                 "store_display": "Hold the thinnest Orbit yet"},
     "launch": True},
]
TITLES = {"hoarding": "Hoarding poster", "bus_shelter": "Bus-shelter poster", "reel": "Reel", "newspaper": "Newspaper ad",
          "store_display": "Store display", "reviewer_kit": "Reviewer kit"}


def ok(r: httpx.Response) -> dict:
    """Raise with the API's detail on errors."""
    if r.status_code >= 400:
        raise SystemExit(f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:200]}")
    return r.json()


def seed(api: str) -> None:
    """Create (Nova X1 first → --p1), understand, plan and ready each product; launch the live ones one at a time."""
    c = httpx.Client(base_url=api, timeout=120)
    existing = {p["product_id"]: p for p in ok(c.get("/api/products"))}
    for spec in PRODUCTS:
        pid = spec["name"].lower().replace(" ", "-")
        if pid in existing:
            print(f"· {spec['name']}: exists ({existing[pid]['status']})")
            continue
        body = {k: spec[k] for k in ("name", "brand", "price_inr", "launch_offer", "features", "claims", "target_personas", "strategy")}
        ok(c.post("/api/products", json={**body, "category": "Smartphone"}))
        for kind, val in spec["content"].items():
            item = {"kind": kind, "title": TITLES[kind]}
            if kind == "reel":
                item.update(transcript=val[0], scenes=val[1])
            else:
                item["text"] = val
            ok(c.post(f"/api/products/{pid}/creatives", json=item))
        ok(c.post(f"/api/products/{pid}/audience", json={}))
        ok(c.post(f"/api/products/{pid}/understand"))
        plan = ok(c.post(f"/api/products/{pid}/plan"))
        ok(c.post(f"/api/products/{pid}/ready"))
        print(f"✓ {spec['name']}: ready · {len(plan['sites'])} sites · reel audience {plan['reel'].get('audience_size')}")
        if spec["launch"]:
            ok(c.post(f"/api/products/{pid}/launch"))
            for _ in range(60):                      # one at a time: wait for the engine to stamp launched_at_t
                if ok(c.get(f"/api/products/{pid}")).get("launched_at_t") is not None:
                    break
                time.sleep(1)
            print(f"  🚀 launched {spec['name']}")


def main() -> None:
    """CLI."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default="http://localhost:8000")
    a = ap.parse_args()
    try:
        seed(a.api)
    except httpx.HTTPError as e:
        sys.exit(f"api not reachable at {a.api}: {e} — start make dev first")


if __name__ == "__main__":
    main()
