"""`make seed-demo`: five demo phones through the products API — Pixel 10 Pro ready; Pixel 10a, Galaxy S26 Ultra, Galaxy A57 and iPhone 17 live.

Needs api (:8000) and world-engine (:8100) running with a genesis world. Idempotent: existing products are kept.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

PRODUCTS = [
    {"name": "Pixel 10 Pro", "brand": "Google", "price_inr": 109999, "launch_offer": "No-cost EMI from ₹9,167/month",
     "features": ["Tensor G5 with on-device Gemini", "50MP main + 48MP 5× telephoto", "6.3\" 120 Hz LTPO display", "7 years of OS updates"],
     "claims": ["The most helpful Pixel yet.", "Night photos without a flash.", "7 years of updates."],
     "target_personas": ["Mobile photographers", "Young tech professionals", "Upgraders with phones > 4 yrs"],
     "strategy": {"key_message": "Ask more of your phone.", "intensity": "medium", "flight_days": 21},
     "content": {"hoarding": "ASK MORE OF YOUR PHONE.", "bus_shelter": "Pixel 10 Pro · night photos, no flash.",
                 "reel": ("After dark, Indiranagar changes. Pixel 10 Pro sees it all. Tap, shoot, ask Gemini.",
                          ["100 Feet Road at dusk", "A street-food stall at night", "Photo appears: crisp, no flash", "Gemini answers a question on screen", "Product + price card"]),
                 "newspaper": "The most helpful Pixel yet.", "store_display": "Try the night camera here →",
                 "reviewer_kit": "Spec sheet: Tensor G5, 50MP + 48MP 5× tele, 6.3\" LTPO, 7 years of updates. Embargo: launch day."},
     "launch": False},
    {"name": "Pixel 10a", "brand": "Google", "price_inr": 49999, "launch_offer": "Exchange bonus ₹4,000",
     "features": ["Tensor G4", "48MP camera with Night Sight", "6.3\" 120 Hz display", "5,100 mAh battery"],
     "claims": ["Pixel smarts, a-series price.", "All-day battery."],
     "target_personas": ["Students and budget buyers", "Upgraders with phones > 4 yrs"],
     "strategy": {"key_message": "Pixel smarts. Friendly price.", "intensity": "medium", "flight_days": 21},
     "content": {"hoarding": "PIXEL SMARTS. FRIENDLY PRICE.", "bus_shelter": "Pixel 10a · from ₹49,999",
                 "reel": ("Night Sight, Gemini and all-day battery, without the flagship price.", ["Metro commute", "Late-night photo", "Battery at 9 pm: 41%"]),
                 "newspaper": "Pixel smarts, a-series price.", "store_display": "Try Night Sight on the Pixel 10a"},
     "launch": True},
    {"name": "Galaxy S26 Ultra", "brand": "Samsung", "price_inr": 129999, "launch_offer": "Free storage upgrade at launch",
     "features": ["200MP main camera, 5× telephoto", "Built-in S Pen", "6.9\" 120 Hz AMOLED", "Galaxy AI features"],
     "claims": ["Zoom in on the night.", "The S Pen, built in."],
     "target_personas": ["Business professionals", "Mobile photographers", "Premium upgraders"],
     "strategy": {"key_message": "Zoom in on the night.", "intensity": "high", "flight_days": 21},
     "content": {"hoarding": "ZOOM IN ON THE NIGHT.", "reel": ("200MP, 5× zoom and an S Pen that lives inside.", ["Rooftop skyline zoom", "S Pen note in a meeting", "Product + price card"]),
                 "newspaper": "The S Pen, built in.", "store_display": "Try the 5× zoom here"},
     "launch": True},
    {"name": "Galaxy A57", "brand": "Samsung", "price_inr": 42999, "launch_offer": "Bank offer ₹3,000 off",
     "features": ["50MP OIS camera", "6.7\" 120 Hz Super AMOLED", "5,000 mAh battery", "6 years of OS updates"],
     "claims": ["Awesome, every day.", "Six years of updates."],
     "target_personas": ["Students and young workers", "Families on a budget"],
     "strategy": {"key_message": "Awesome, every day.", "intensity": "medium", "flight_days": 21},
     "content": {"hoarding": "AWESOME, EVERY DAY.", "bus_shelter": "Galaxy A57 · from ₹42,999",
                 "reel": ("A big bright screen and a camera that keeps up with your day.", ["College canteen", "Bus ride", "Evening selfie"]),
                 "store_display": "Feel the Galaxy A57 screen"},
     "launch": True},
    {"name": "iPhone 17", "brand": "Apple", "price_inr": 82900, "launch_offer": "Instant cashback ₹5,000 on cards",
     "features": ["A19 chip", "48MP Fusion camera", "6.3\" ProMotion display", "Centre Stage front camera"],
     "claims": ["Brighter, smoother, faster.", "Selfies that frame themselves."],
     "target_personas": ["Style-conscious young professionals", "Upgraders with phones > 4 yrs"],
     "strategy": {"key_message": "Brighter. Smoother. Faster.", "intensity": "medium", "flight_days": 21},
     "content": {"hoarding": "BRIGHTER. SMOOTHER. FASTER.", "reel": ("ProMotion, a 48MP camera and selfies that frame themselves.", ["Café table", "Group selfie widens", "Product + price card"]),
                 "newspaper": "Brighter, smoother, faster.", "store_display": "Try Centre Stage selfies here"},
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
    """Create (Pixel 10 Pro first → --p1), understand, plan and ready each product; launch the live ones one at a time."""
    c = httpx.Client(base_url=api, timeout=120)
    existing = {p["product_id"]: p for p in ok(c.get("/api/products"))}
    for spec in PRODUCTS:
        pid = spec["name"].lower().replace(" ", "-")
        if pid in existing:
            print(f"· {spec['name']}: exists ({existing[pid]['status']})")
            if spec["launch"] and existing[pid]["status"] == "ready":
                ok(c.post(f"/api/products/{pid}/plan"))     # re-plan: sites may now be held by live products
                ok(c.post(f"/api/products/{pid}/ready"))
                _launch(c, pid, spec["name"])
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
            _launch(c, pid, spec["name"])


def _launch(c: httpx.Client, pid: str, name: str) -> None:
    """Launch one product; waits while another launch holds the lock, then for the engine's launched_at_t."""
    for _ in range(90):
        r = c.post(f"/api/products/{pid}/launch")
        if r.status_code != 409:
            ok(r)
            break
        time.sleep(2)
    for _ in range(60):                              # one at a time: wait for the engine to stamp launched_at_t
        if ok(c.get(f"/api/products/{pid}")).get("launched_at_t") is not None:
            break
        time.sleep(1)
    print(f"  🚀 launched {name}")


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
