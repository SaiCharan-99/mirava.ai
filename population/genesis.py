"""World genesis: sample 1,000 agents, households, relationships, possessions, personas; persist (`make genesis`)."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import time
from typing import Any

import msgpack
import zstandard

from engine.events import EventBus, Sink, make_sink
from engine.rng import stream
from mind.memory import MemoryStore
from population.config import market
from population.households import form_households, place_homes
from population.persona import base_persona, card_tokens, persona_card, write_bios
from population.possessions import media_diet, money_profile, phone, phone_age_years
from population.relationships import build_relationships, degrees
from population.routine import assign_workplaces
from population.sampler import ASSUMED_FIELDS, sample_people
from population.special_agents import assign_special
from shared import time as simtime
from shared.files import Files, get_files
from shared.llm import LLMClient, get_llm
from shared.schemas.agent import AgentProfile, AgentState, Relationship
from shared.schemas.memory import MemoryEntry
from shared.settings import Settings, get_settings
from shared.store import DocStore, get_store
from world.map import WorldMap, get_map

log = logging.getLogger("genesis")
OFFMAP_AREAS = ["Whitefield", "Koramangala", "MG Road", "Electronic City", "Manyata", "Bellandur", "Domlur"]
NEEDS0 = {"energy": 0.35, "hunger": 0.3, "social": 0.5, "fatigue": 0.6, "stimulation": 0.3}


def _names(people: list[dict[str, Any]], households: list[dict[str, Any]], seed: int) -> None:
    """Indian names; families share a surname, full names unique."""
    rng = stream(seed, "names")
    m = market()["names"]
    by = {p["i"]: p for p in people}
    used: set[str] = set()
    for h in households:
        fam_surname = str(m["surnames"][int(rng.integers(len(m["surnames"])))])
        for i, _role in h["members"]:
            p = by[i]
            surname = fam_surname if h["kind"] != "flatmates" else str(m["surnames"][int(rng.integers(len(m["surnames"])))])
            pool = m["female"] if p["gender"] == "female" else m["male"]
            for _ in range(200):
                name = f"{pool[int(rng.integers(len(pool)))]} {surname}"
                if name not in used:
                    break
                surname = str(m["surnames"][int(rng.integers(len(m["surnames"])))])
            used.add(name)
            p["name"] = name


def _work_phrases(p: dict[str, Any], wm: WorldMap, seed: int) -> None:
    """Short work descriptions for the bio (`work_phrase`) and card (`work_card`)."""
    rng = stream(seed, "work_phrase", p["i"])
    label = p["label"]
    art = "an" if label[0].lower() in "aeiou" else "a"
    wp = wm.place_by_id.get(p["workplace_place_id"] or "")
    if p["occupation"] == "school_student":
        p["work_phrase"], p["work_card"] = f"in school ({wp.name if wp else 'nearby'})", f" at {wp.name}" if wp else ""
    elif p["occupation"] in ("homemaker", "retired", "job_seeker"):
        p["work_phrase"], p["work_card"] = label.lower() if p["occupation"] != "job_seeker" else "looking for work", ""
    elif p["offmap"]:
        area = OFFMAP_AREAS[int(rng.integers(len(OFFMAP_AREAS)))]
        p["offmap_area"] = area
        p["work_phrase"], p["work_card"] = f"{art} {label.lower()} working in {area}", f", works in {area}"
    elif wp is not None:
        p["work_phrase"], p["work_card"] = f"{art} {label.lower()} at {wp.name}", f" at {wp.name}"
    else:
        p["work_phrase"], p["work_card"] = f"{art} {label.lower()} around Indiranagar", ""


def _seed_memories(p: dict[str, Any], profile: AgentProfile) -> list[MemoryEntry]:
    """3–6 first-person seed memories: job, family, phone, a recent event, an interest."""
    ph = profile.possessions["phone"]
    age_y = p["phone_age"]
    texts = [
        (f"I'm {p['work_phrase']}.", 6),
        (f"I live in Indiranagar in a household of {p['household_size']}.", 5),
        (f"My phone is a {ph['brand']} {ph['tier']} I bought about {age_y:.1f} years ago; it's "
         f"{ph['condition'].replace('_', ' ')} now.", 5 if ph["condition"] == "ok" else 7),
        (f"I spend my free time on {', '.join(profile.persona.interests[:2])}.", 4),
    ]
    if ph["condition"] in ("cracked", "battery_weak", "slow"):
        texts.append(("Lately my phone has been annoying me and I've wondered about replacing it.", 6))
    if profile.money.pay_cycle == "weekly":
        texts.append(("I get paid every week, so I keep a close eye on cash.", 4))
    out = []
    for k, (txt, imp) in enumerate(texts[:6]):
        out.append(MemoryEntry(mid=f"{profile.agent_id}:0:{k}", agent_id=profile.agent_id, t=0, kind="seed", text=txt,
                               importance=imp, source={"channel": "genesis"}, entities=[], event_refs=[]))
    return out


def build_world(n: int, seed: int, wm: WorldMap | None = None) -> dict[str, Any]:
    """Pure, deterministic genesis without model calls: people, households, edges, profiles (template bios)."""
    wm = wm or get_map()
    people = sample_people(n, seed)
    assign_special(people, seed)
    households = form_households(people, seed)
    place_homes(households, wm, seed)
    by = {p["i"]: p for p in people}
    for h in households:
        for i, role in h["members"]:
            by[i].update(household_id=h["household_id"], role=role, home_place_id=h["home_place_id"],
                         home_xy=h["home_xy"], household_size=len(h["members"]))
    _names(people, households, seed)
    assign_workplaces(people, {p["i"]: p["home_xy"] for p in people}, wm, seed)
    for p in people:
        p["money"] = money_profile(p, seed).model_dump()
        p["phone"] = phone(p, seed).model_dump()
        p["phone_age"] = phone_age_years(p["phone"], 0)
        _work_phrases(p, wm, seed)
    reviewers = [p for p in people if p["special_role"] == "reviewer"]
    for p in people:
        p["media"] = media_diet(p, reviewers, seed).model_dump()
        p["follows"] = p["media"]["follows"]
    edges = build_relationships(people, households, seed)
    cores = {p["i"]: base_persona(p, seed) for p in people}
    for p in people:
        p["persona_card"] = persona_card(p, cores[p["i"]])
    return {"people": people, "households": households, "edges": edges, "cores": cores}


def profiles_of(world: dict[str, Any]) -> list[AgentProfile]:
    """AgentProfile models from a built world."""
    out = []
    for p in world["people"]:
        poss_phone = dict(p["phone"])
        out.append(AgentProfile(
            agent_id=p["i"], name=p["name"], age=p["age"], gender=p["gender"], household_id=p["household_id"],
            role_in_household=p["role"], education=p["education"], occupation=p["label"],
            workplace_place_id=p["workplace_place_id"], home_place_id=p["home_place_id"], income_band=p["income_band"],
            commute_mode=p["commute_mode"], special_role=p["special_role"], persona=world["cores"][p["i"]],
            persona_card=p["persona_card"], routine_id=p["routine_id"], media=p["media"], money=p["money"],
            possessions={"phone": poss_phone}, assumed_fields=list(ASSUMED_FIELDS)))
    return out


def metas_of(world: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Engine-only per-agent meta: haunts, wake jitter, special role details, work kind, household size."""
    keys = ("special", "work_kind", "haunts", "wake_jitter", "household_size", "label", "offmap_area")
    return {p["i"]: {k: p.get(k) for k in keys} for p in world["people"]}


def initial_state(profile: AgentProfile, wm: WorldMap) -> AgentState:
    """Everyone starts asleep at home at t=0."""
    x, y = home_spot(profile, wm)
    return AgentState(agent_id=profile.agent_id, t=0, x=x, y=y, heading=0.0, mode="idle",
                      place_id=profile.home_place_id, activity="sleep", needs=dict(NEEDS0), mood=0.6, plan=[])  # type: ignore[arg-type]


def home_spot(profile: AgentProfile, wm: WorldMap) -> tuple[float, float]:
    """Deterministic standing point near the home entrance."""
    ex, ey = wm.place_by_id[profile.home_place_id].entrances[0]
    j = (profile.agent_id * 7919) % 100
    return round(ex + (j % 10 - 4.5) * 0.6, 1), round(ey + (j // 10 - 4.5) * 0.6, 1)


def pack(obj: Any) -> bytes:
    """msgpack + zstd."""
    return zstandard.ZstdCompressor(level=9).compress(msgpack.packb(obj, use_bin_type=True))


def unpack(data: bytes) -> Any:
    """Inverse of `pack`."""
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as r:
        return msgpack.unpackb(r.read(), raw=False, strict_map_key=False)


def snapshot_payload(profile: AgentProfile, state: AgentState, t: int) -> dict[str, Any]:
    """Daily `agent_snapshot` payload (INTERFACES §2.1)."""
    ph = profile.possessions["phone"]
    return {"name": profile.name, "age": profile.age, "gender": profile.gender, "occupation": profile.occupation,
            "income_band": profile.income_band, "household_id": profile.household_id,
            "special_role": profile.special_role, "commute_mode": profile.commute_mode,
            "interests": profile.persona.interests, "lifestyle": profile.persona.lifestyle,
            "needs": {k: round(v, 3) for k, v in state.needs.items()}, "activity": state.activity,
            "money": {"monthly_income_inr": profile.money.monthly_income_inr, "savings_inr": profile.money.savings_inr,
                      "credit_card": profile.money.credit_card_limit_inr > 0, "emi_eligible": profile.money.emi_eligible},
            "phone": {"brand": ph["brand"], "tier": ph["tier"], "condition": ph["condition"],
                      "age_years": round(phone_age_years(ph, t), 2), "battery_health": ph["battery_health"]}}


def genesis_bucket(s: Settings) -> str:
    """Bucket for world files (local dir name when ENV=local)."""
    return s.gcs_bucket_worlds or "worlds"


async def run_genesis(n: int, seed: int, *, store: DocStore, files: Files, sink: Sink, llm: LLMClient | None,
                      version: str = "v1", settings: Settings | None = None) -> dict[str, Any]:
    """Full genesis: build, write model bios, persist profiles/relationships/memories/checkpoint, emit snapshots."""
    s = settings or get_settings()
    t0 = time.time()
    wm = get_map()
    world = build_world(n, seed, wm)
    bio_stats = {"batches": 0, "model_bios": 0, "fallback": n, "cost_usd": 0.0}
    if llm is not None:
        bio_stats = await write_bios(world["people"], world["cores"], llm)
    profiles = profiles_of(world)
    metas = metas_of(world)
    too_long = [p.agent_id for p in profiles if card_tokens(p.persona_card) > 150]
    if too_long:
        raise ValueError(f"persona cards over 150 tokens: {too_long[:5]}")
    states = [initial_state(p, wm) for p in profiles]
    edges: list[Relationship] = world["edges"]
    deg = degrees(edges, n)
    manifest = {"version": version, "world_seed": seed, "n": n, "created_unix": int(time.time()),
                "households": len(world["households"]), "relationships": len(edges),
                "avg_degree": round(float(deg.mean()), 2), "isolated": int((deg == 0).sum()),
                "persona": bio_stats, "llm_backend": s.llm_backend}
    bucket = genesis_bucket(s)
    files.write(bucket, f"genesis/{version}/profiles.msgpack.zst", pack([p.model_dump() for p in profiles]))
    files.write(bucket, f"genesis/{version}/relationships.msgpack.zst", pack([e.model_dump() for e in edges]))
    files.write(bucket, f"genesis/{version}/households.msgpack.zst",
                pack([{k: h[k] for k in ("household_id", "kind", "members", "home_place_id")} for h in world["households"]]))
    files.write(bucket, f"genesis/{version}/meta.msgpack.zst", pack({str(k): v for k, v in metas.items()}))
    files.write(bucket, f"genesis/{version}/states.msgpack.zst", pack([st.model_dump() for st in states]))
    seeds = {p.agent_id: _seed_memories(next(x for x in world["people"] if x["i"] == p.agent_id), p) for p in profiles}
    files.write(bucket, f"genesis/{version}/seed_memories.msgpack.zst",
                pack({str(k): [m.model_dump() for m in v] for k, v in seeds.items()}))
    files.write(bucket, f"genesis/{version}/manifest.json", json.dumps(manifest, indent=2).encode())

    store.set_many("agents", {str(p.agent_id): agent_doc(p, st, metas[p.agent_id])
                                for p, st in zip(profiles, states, strict=True)})
    store.set_many("relationships", {f"{e.a}_{e.b}" + ("_f" if e.kind == "follower" else ""): e.model_dump() for e in edges})
    for aid, mems in seeds.items():
        MemoryStore(aid, store).add_many(mems)
    store.set("world", "genesis", manifest)
    store.set("world", "state", {"t": 0, "status": "genesis", "genesis_version": version, "last_checkpoint": None,
                                 "last_flushed_t": -1, "world_seed": seed})
    bus = EventBus(sink)
    for p, st in zip(profiles, states, strict=True):
        bus.new("agent_snapshot", 0, p.agent_id, snapshot_payload(p, st, 0))
    bus.flush_sync()
    manifest["seconds"] = round(time.time() - t0, 1)
    log.info("genesis done: %s", manifest)
    return manifest


def agent_doc(p: AgentProfile, st: AgentState, meta: dict[str, Any]) -> dict[str, Any]:
    """Firestore `agents/{id}` document: profile + state summary + list fields for the People table."""
    ph = p.possessions["phone"]
    return {"agent_id": p.agent_id, "profile": fs_profile(p.model_dump()), "state": st.model_dump(), "watched": False,
            "meta": {"household_size": meta["household_size"], "special": meta["special"],
                     "offmap_area": meta.get("offmap_area")},
            "row": {"agent_id": p.agent_id, "name": p.name, "age": p.age, "occupation": p.occupation,
                    "income_band": p.income_band, "special_role": p.special_role,
                    "phone": {"brand": ph["brand"], "tier": ph["tier"], "bought_t": ph["bought_t"],
                              "condition": ph["condition"]}}}


def fs_profile(d: dict[str, Any]) -> dict[str, Any]:
    """Firestore cannot store arrays of arrays: feed sessions become objects."""
    d = dict(d)
    d["media"] = {**d["media"], "feed_sessions": [{"start": a, "minutes": b, "app": c}
                                                  for a, b, c in d["media"]["feed_sessions"]]}
    return d


def from_fs_profile(d: dict[str, Any]) -> dict[str, Any]:
    """Inverse of `fs_profile`."""
    d = dict(d)
    fs = d["media"]["feed_sessions"]
    if fs and isinstance(fs[0], dict):
        d["media"] = {**d["media"], "feed_sessions": [[x["start"], x["minutes"], x["app"]] for x in fs]}
    return d


def main() -> None:
    """CLI: `make genesis` (N agents, seed from settings; --memory for an offline dry run)."""
    ap = argparse.ArgumentParser()
    s = get_settings()
    ap.add_argument("--n", type=int, default=s.world_agents)
    ap.add_argument("--seed", type=int, default=s.world_seed)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--no-llm", action="store_true", help="template bios only")
    ap.add_argument("--memory", action="store_true", help="in-memory store (dry run)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    store = get_store(memory=a.memory)
    llm = None if a.no_llm else get_llm()
    manifest = asyncio.run(run_genesis(a.n, a.seed, store=store, files=get_files(), sink=make_sink(), llm=llm,
                                       version=a.version))
    print(json.dumps(manifest, indent=2))
    print("start:", simtime.fmt(0))


if __name__ == "__main__":
    main()
