"""Demo snapshot (X-05): save the pre-warmed world, restore it in place in under a minute.

  uv run python -m tools.demo_snapshot save --name demo-v1      # copy the latest checkpoint + product docs
  uv run python -m tools.demo_snapshot restore --name demo-v1   # products back, engine reboots from the snapshot
  make restore-demo                                             # restore SNAPSHOT (default demo-v1)

Uses the configured backends (ENV=cloud → GCS + Firestore; local → disk + emulator). The engine is told to reload via
`POST /commands {"type": "reload"}`; in the cloud the ID token is minted for the mirava-api service account
(`gcloud auth print-identity-token --impersonate-service-account`), the only caller world-engine accepts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import httpx

from population.genesis import genesis_bucket
from shared.files import get_files
from shared.settings import get_settings
from shared.store import get_store

PRODUCTS = "products"


def _prefix(name: str) -> str:
    return f"snapshots/{name}"


def save(name: str) -> dict:
    """Copy the checkpoint named by `world/state` and every product doc under snapshots/<name>/."""
    s = get_settings()
    files, store, bucket = get_files(s), get_store(), genesis_bucket(s)
    st = store.get("world", "state") or {}
    key = st.get("last_checkpoint")
    if not key:
        raise SystemExit("no checkpoint yet — let the engine run a sim hour first")
    files.write(bucket, f"{_prefix(name)}/checkpoint.msgpack.zst", files.read(bucket, key))
    products = store.list(PRODUCTS)
    meta = {"name": name, "from_checkpoint": key, "t": st.get("checkpoint_t"), "saved_at": time.time(),
            "products": products}
    files.write(bucket, f"{_prefix(name)}/meta.json", json.dumps(meta, default=str).encode())
    return {"name": name, "t": meta["t"], "products": [p.get("product_id") for p in products]}


def _engine_headers(url: str, env: str) -> dict[str, str]:
    if env != "cloud":
        return {}
    sa = f"mirava-api@{get_settings().gcp_project_id}.iam.gserviceaccount.com"
    tok = subprocess.run(["gcloud", "auth", "print-identity-token", f"--impersonate-service-account={sa}",
                          f"--audiences={url}"], capture_output=True, text=True, shell=sys.platform == "win32")
    if tok.returncode != 0:
        raise SystemExit(f"could not mint an ID token for {sa}: {tok.stderr.strip()[:300]}")
    return {"Authorization": f"Bearer {tok.stdout.strip()}"}


def restore(name: str, engine_url: str | None = None, wait_s: float = 120) -> dict:
    """Write the snapshot's product docs back, then make the engine reboot from the snapshot checkpoint."""
    s = get_settings()
    files, store, bucket = get_files(s), get_store(), genesis_bucket(s)
    meta = json.loads(files.read(bucket, f"{_prefix(name)}/meta.json"))
    keep = {p["product_id"] for p in meta["products"]}
    for p in store.list(PRODUCTS):
        if p.get("product_id") not in keep:
            store.delete(PRODUCTS, p["product_id"])
    for p in meta["products"]:
        store.set(PRODUCTS, p["product_id"], p)
    url = (engine_url or s.engine_url).rstrip("/")
    r = httpx.post(f"{url}/commands", json={"type": "reload", "checkpoint": f"{_prefix(name)}/checkpoint.msgpack.zst"},
                   headers=_engine_headers(url, s.env), timeout=15)
    if r.status_code != 200 or not r.json().get("ok", True):
        raise SystemExit(f"engine refused the reload: {r.status_code} {r.text[:300]}")
    t0 = time.time()
    while time.time() - t0 < wait_s:
        st = httpx.get(f"{url}/state", timeout=10).json()
        if st.get("status") == "running" and abs(int(st.get("t", -1)) - int(meta["t"])) <= 30:
            return {"name": name, "t": st["t"], "label": st.get("label"), "seconds": round(time.time() - t0, 1)}
        time.sleep(2)
    raise SystemExit("engine did not come back at the snapshot time in time; check GET /state")


def main() -> None:
    """CLI."""
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["save", "restore"])
    ap.add_argument("--name", default="demo-v1")
    ap.add_argument("--engine", default=None, help="world-engine URL (default ENGINE_URL)")
    a = ap.parse_args()
    out = save(a.name) if a.action == "save" else restore(a.name, a.engine)
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
