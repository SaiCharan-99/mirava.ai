"""Knowledge graph (L-04): product, features, claims, concerns, competitors, segments, creatives, brand and stores."""

from __future__ import annotations

import re

from shared.llm import LLMClient
from shared.schemas.product import Product


def _slug(s: str, n: int = 24) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n] or "x"


def build_graph(p: Product, understanding: dict, store_names: list[str]) -> dict:
    """Nodes/edges per INTERFACES §6.6 (degree filled in)."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid: str, label: str, typ: str, desc: str = "", source: str = "", **kw: object) -> str:
        nodes.setdefault(nid, {"id": nid, "label": label, "type": typ, "desc": desc, "source": source, **kw})
        return nid

    def edge(a: str, b: str, rel: str) -> None:
        if a != b and not any(e["source"] == a and e["target"] == b for e in edges):
            edges.append({"source": a, "target": b, "rel": rel})

    root = node(p.product_id, p.name, "product", f"{p.brand} {p.category} · ₹{p.price_inr:,}", "details")
    brand = node(f"brand-{_slug(p.brand)}", p.brand, "entity", "Brand", "details")
    edge(root, brand, "made by")
    feats = {}
    for f in p.features:
        feats[f] = node(f"feat-{_slug(f)}", f, "feature", f, "details")
        edge(root, feats[f], "has feature")
    for c in understanding.get("claims", []):
        cid = node(f"claim-{_slug(c['text'])}", c["text"], "claim", c.get("reason", ""), c.get("source", ""),
                   risk=c.get("risk", "amber"))
        edge(root, cid, "claims")
        words = {w.lower() for w in re.findall(r"[A-Za-z0-9]{4,}", c["text"])}
        for f, fid in feats.items():
            if words & {w.lower() for w in re.findall(r"[A-Za-z0-9]{4,}", f)}:
                edge(cid, fid, "about")
    for x in understanding.get("concerns", []):
        edge(node(f"concern-{_slug(x)}", x, "concern", x, "understanding"), root, "concern about")
    for x in understanding.get("competitors", []):
        edge(root, node(f"comp-{_slug(x)}", x, "competitor", x, "understanding"), "competes with")
    for a in p.audience or []:
        edge(root, node(f"seg-{_slug(a.description)}", a.description, "segment",
                        f"~{a.count} simulated agents", "personas"), "targets")
    for persona in p.target_personas if not p.audience else []:
        edge(root, node(f"seg-{_slug(persona)}", persona, "segment", "", "personas"), "targets")
    claim_ids = [n for n in nodes.values() if n["type"] == "claim"]
    for cr in p.creatives:
        cid = node(f"cre-{cr.creative_id}", cr.title or cr.kind, "creative", cr.kind.replace("_", " "), cr.creative_id)
        edge(cid, root, "promotes")
        carried = cr.stimulus.claims_carried if cr.stimulus else []
        for cl in claim_ids:
            if cl["label"] in carried:
                edge(cid, cl["id"], "carries")
    for s in store_names:
        edge(root, node(f"store-{_slug(s)}", s, "entity", "Fictional store (simulated)", "plan"), "sold at")
    deg: dict[str, int] = {k: 0 for k in nodes}
    for e in edges:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    for k, n in nodes.items():
        n["degree"] = deg[k]
    return {"nodes": list(nodes.values()), "edges": edges}


async def embed_nodes(graph: dict, llm: LLMClient) -> dict[str, list[float]]:
    """Node embeddings (label + desc) for later mention links; stored apart from the graph doc."""
    nodes = graph["nodes"]
    vecs = await llm.embed([f"{n['label']}. {n['desc']}" for n in nodes]) if nodes else []
    return {n["id"]: v for n, v in zip(nodes, vecs, strict=True)}
