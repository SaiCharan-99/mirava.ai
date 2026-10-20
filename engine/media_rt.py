"""Engine-side media runtime: launches, hoardings, feeds, print, store displays, reviewers, community, baseline ads."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from engine.events import EventBus
from engine.governor import BudgetGovernor
from engine.rng import stream
from engine.tasks import TaskQueue
from engine.world import World
from media.attention import AttentionCtx, attend, attend_feed, attend_print, dwell_seconds, is_night, ots
from media.audience import audience_ids
from mind.ad_thought import apply_thought, rule_thought, think_on_notice
from mind.memory import embed_cached
from mind.opinion import attrs_in
from population.possessions import phone_age_years
from shared import time as simtime
from shared.llm import LLMClient
from shared.schemas.product import Product, StimulusRecord
from shared.store import DocStore
from social import community

log = logging.getLogger("engine.media")
BASELINE = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "baseline_ads.yaml")
                          .read_text(encoding="utf-8"))
REFRESH_EVERY = 30          # sim minutes between product reloads
THOUGHT_DELAY = 2           # sim minutes until a rendered thought is applied
REVIEW_PUBLISH_AFTER = 240  # private opinion → published review
EST = {"P1": 0.0006, "P5": 0.0012}
PHONE_CATS = {"smartphone", "phone", "phones"}


def baseline_stim(b: dict[str, Any]) -> StimulusRecord:
    """StimulusRecord for a baseline brand."""
    return StimulusRecord(creative_id=f"baseline-{b['id']}", salience=b["salience"], clarity=b["clarity"],
                          hook=b["hook"], claims_carried=[], tone="ambient", readable_at_distance=True,
                          description=b["description"])


class LiveProduct:
    """A launched product as the engine sees it."""

    def __init__(self, p: Product, audience: set[int], interests: set[str]) -> None:
        self.p = p
        self.audience = audience
        self.interests = interests
        self.stim = {c.creative_id: c.stimulus for c in p.creatives if c.stimulus is not None}
        self.by_kind: dict[str, str] = {str(c.kind): c.creative_id for c in p.creatives}
        self.launch_day = simtime.day_of(p.launched_at_t or 0)

    def stimulus(self, kind: str) -> StimulusRecord | None:
        """StimulusRecord of the creative of one kind, if any."""
        cid = self.by_kind.get(kind)
        return self.stim.get(cid) if cid else None

    def in_flight(self, t: int) -> bool:
        """Within the plan's flight."""
        flight = self.p.plan.flight_days if self.p.plan else 21
        return self.p.launched_at_t is not None and t < self.p.launched_at_t + flight * 1440


class MediaRuntime:
    """Runs after World.step() (and the social runtime) every sim minute."""

    def __init__(self, store: DocStore, llm: LLMClient, governor: BudgetGovernor, w: World, *,
                 social: Any = None, embed_texts: bool = True, opinion: Any = None) -> None:
        self.store, self.llm, self.gov, self.social = store, llm, governor, social
        self.opinion = opinion                        # OpinionEngine (None: legacy summed attitudes)
        self.embed_texts = embed_texts
        self.sites = list(w.wm.sites)
        self.site_xy = np.array([[s.x, s.y] for s in self.sites]) if self.sites else np.zeros((0, 2))
        self.max_r = max((s.max_distance_m for s in self.sites), default=0.0)
        self.clutter = {s.site_id: int(sum(1 for o in self.sites if o is not s and
                                          math.hypot(o.x - s.x, o.y - s.y) < 100)) for s in self.sites}
        self.store_by_place = {st.place_id: st for st in w.wm.stores if st.place_id}
        self.profiles = [p.model_dump() for p in w.profiles]
        self.followers: dict[int, list[int]] = {}
        for p in w.profiles:
            for r in p.media.follows:
                self.followers.setdefault(r, []).append(p.agent_id)
        self.news_desk = next((p.agent_id for p in w.profiles if p.special_role == "news_desk"), None)
        self.baseline = [dict(b) for b in BASELINE["brands"]]
        self.baseline_stims = {b["id"]: baseline_stim(b) for b in self.baseline}
        self.live: dict[str, LiveProduct] = {}
        self.pending: list[str] = []
        self.site_map: dict[str, dict[str, Any]] = {}
        self.site_day = -1
        self.last_pass: dict[tuple[int, str], int] = {}
        self.seen: dict[str, list[int]] = {}          # "aid|creative" → [n_seen, n_noticed]
        self.attitude: dict[str, float] = {}          # "aid|pid" → in-memory attitude (rule features only)
        self.aware: dict[str, set[int]] = {}
        self.reel_today: dict[str, int] = {}
        self.reel_impr: dict[str, int] = {}
        self.visited: set[str] = set()
        self.campaign_over: set[str] = set()          # products whose paid flight has ended (event emitted)
        self.commerce: Any = None                     # set by the engine once the commerce runtime exists
        self.reviews: list[dict[str, Any]] = []       # schedule + published reviews
        self.threads: list[dict[str, Any]] = []       # recent threads (≤ 60)
        self.queue = TaskQueue(concurrency=16)
        self._meta: dict[str, dict[str, Any]] = {}
        self._bg: set[asyncio.Future] = set()
        self._last_refresh = -REFRESH_EVERY
        self.stats = {"exposures": 0, "notices": 0, "thoughts_rendered": 0, "thoughts_unrendered": 0,
                      "reviews": 0, "comments": 0, "threads": 0, "cost_usd": 0.0}

    # ------------------------------------------------------------------ launches / products
    def request_launch(self, pid: str) -> None:
        """Command: activate this product's plan at the next tick."""
        if pid not in self.pending and pid not in self.live:
            self.pending.append(pid)

    def _refresh(self, w: World, bus: EventBus, docs: list[dict[str, Any]]) -> None:
        self._drop_removed(w, {d["product_id"] for d in docs})
        for d in sorted(docs, key=lambda d: d["product_id"]):
            pid = d["product_id"]
            if d.get("status") == "live" and d.get("launched_at_t") is None:
                self.request_launch(pid)
            elif d.get("status") == "live" and pid not in self.live and d.get("plan"):
                self._activate(w, Product.model_validate(d))
        for pid in list(self.pending):
            d = next((x for x in docs if x["product_id"] == pid), None)
            self.pending.remove(pid)
            if d is None or not d.get("plan") or (pid in self.live):
                continue
            self._launch(w, bus, Product.model_validate(d))
        self._wire(w)

    def _drop_removed(self, w: World, valid: set[str]) -> None:
        """Products deleted in Launch Studio stop counting (awareness, attitudes, live sites, commerce pairs)."""
        gone = [pid for pid in self.live if pid not in valid]
        for pid in gone:
            self.live.pop(pid, None)
            self.aware.pop(pid, None)
            self.campaign_over.discard(pid)
            for k in [k for k in self.attitude if k.endswith(f"|{pid}")]:
                del self.attitude[k]
        for pid in [x for x in self.aware if x not in valid]:       # stale checkpoint entries (demo products)
            self.aware.pop(pid, None)
        if gone:
            self.site_day = -1                                      # re-assign boards without them
        if self.commerce is not None:
            self.commerce.prune_products(valid)

    def campaigns(self, t: int) -> dict[str, dict[str, Any]]:
        """{product_id: {ends_t, active}} for live products (paid flight window)."""
        out: dict[str, dict[str, Any]] = {}
        for pid, lp in self.live.items():
            flight = lp.p.plan.flight_days if lp.p.plan else 21
            ends = int((lp.p.launched_at_t or 0) + flight * 1440)
            out[pid] = {"ends_t": ends, "active": lp.in_flight(t)}
        return out

    def _campaign_end_events(self, w: World, bus: EventBus, t: int) -> None:
        for pid, c in self.campaigns(t).items():
            if not c["active"] and pid not in self.campaign_over:
                self.campaign_over.add(pid)
                bus.new("campaign_ended", t, None, {"product_id": pid, "ends_t": c["ends_t"]}, product_id=pid)
                w.live_evts.append({"k": "campaign_ended", "product": pid, "name": self.live[pid].p.name})

    def _activate(self, w: World, p: Product) -> LiveProduct:
        aud = set(audience_ids(p.audience, self.profiles, w.t))
        ints = {i for a in p.audience for i in a.filter.get("interests_any", [])}
        lp = LiveProduct(p, aud, ints)
        self.live[p.product_id] = lp
        self._sync_catalog()
        self.aware.setdefault(p.product_id, set())
        self.site_day = -1
        return lp

    def _launch(self, w: World, bus: EventBus, p: Product) -> None:
        """Stamp launched_at_t, emit `launch`, schedule reviewers and the news-desk thread."""
        t = w.t
        p.launched_at_t = t
        p.status = "live"
        self._background(asyncio.to_thread(self.store.set, "products", p.product_id,
                                           {"status": "live", "launched_at_t": t}, True))
        lp = self._activate(w, p)
        plan = p.plan
        assert plan is not None
        summary = {"sites": len(plan.sites), "stores": len(plan.stores), "reel_audience": len(lp.audience),
                   "reviewers": len(plan.reviewers), "newspaper_days": plan.newspaper_days}
        bus.new("launch", t, None, {"product_id": p.product_id, "plan": summary, "launched_at_t": t},
                product_id=p.product_id)
        w.live_evts.append({"k": "launch", "product": p.product_id, "name": p.name, "color": p.color,
                            "sites": [{"site_id": s.site_id, "facing": s.facing, "creative_id": s.creative_id}
                                      for s in plan.sites],
                            "stores": plan.stores, "audience": sorted(lp.audience)[:400],
                            "summary": summary})
        rng = stream(w.seed, "reviews", p.product_id)
        for i, r in enumerate(plan.reviewers):
            t_priv = t + int(1440 * (0.4 + (i % 3) * 0.7) + rng.integers(0, 180))
            self.reviews.append({"reviewer": r, "product_id": p.product_id, "t_private": t_priv,
                                 "t_publish": t_priv + REVIEW_PUBLISH_AFTER, "state": "due"})
        seed = plan.community_seed or {}
        if seed.get("author") is not None:
            body = (f"{p.brand} has launched the {p.name} at ₹{p.price_inr:,}"
                    f"{' with ' + p.launch_offer if p.launch_offer else ''}. Key features: {', '.join(p.features[:4])}.")
            self._new_thread(w, bus, int(seed["author"]), seed.get("forum", "r/BangaloreTech"),
                             seed.get("title", f"{p.name} launches"), body, p.product_id)

    def _sync_catalog(self) -> None:
        if self.opinion is not None:
            self.opinion.set_catalog(lp.p for lp in self.live.values())

    def _wire(self, w: World) -> None:
        self._sync_catalog()
        w.products_live = [{"id": lp.p.product_id, "name": lp.p.name, "color": lp.p.color,
                            "launched_at_t": lp.p.launched_at_t} for lp in self.live.values()]
        w.awareness = {pid: round(len(s) / max(1, len(w.agents)), 3) for pid, s in self.aware.items()}

    def _assign_sites(self, w: World) -> None:
        """Daily: planned sites show live creatives; a share of the rest shows baseline ads (C-08)."""
        day = simtime.day_of(w.t)
        self.site_map = {}
        for lp in self.live.values():
            if not lp.in_flight(w.t) or lp.p.plan is None:
                continue
            for s in lp.p.plan.sites:
                self.site_map.setdefault(s.site_id, {"product_id": lp.p.product_id, "creative_id": s.creative_id,
                                                     "facing": s.facing})
        for s in self.sites:
            if s.site_id in self.site_map:
                continue
            rng = stream(w.seed, "baseline_site", day, s.site_id)
            if rng.random() < float(BASELINE["site_share"]):
                b = self.baseline[int(rng.integers(0, len(self.baseline)))]
                self.site_map[s.site_id] = {"product_id": f"baseline:{b['id']}", "creative_id": f"baseline-{b['id']}",
                                            "facing": None}
        w.sites_live = [{"site_id": k, "creative_id": v["creative_id"], "product_id": v["product_id"]}
                        for k, v in sorted(self.site_map.items())]
        self.site_day = day

    # ------------------------------------------------------------------ per tick
    async def tick(self, w: World, bus: EventBus) -> None:
        """Apply finished thoughts, reload products, then run every channel for this minute."""
        t = w.t
        await self._apply(w, bus, t)
        if self.pending or t - self._last_refresh >= REFRESH_EVERY:
            self._last_refresh = t
            docs = await asyncio.to_thread(self.store.list, "products", 200)
            self._refresh(w, bus, docs)
        m = simtime.minute_of_day(t)
        if m == 0:
            self.reel_today.clear()
            self.reel_impr.clear()
            self.visited.clear()
        if self.site_day != simtime.day_of(t):
            self._assign_sites(w)
        if m % 30 == 0:
            self._campaign_end_events(w, bus, t)
        self._hoardings(w, bus, t, m)
        self._feeds_and_print(w, bus, t, m)
        self._store_displays(w, bus, t)
        self._reviewers(w, bus, t)
        self.last_pass = {k: v for k, v in self.last_pass.items() if t - v < 30} if m % 30 == 0 else self.last_pass

    # ------------------------------------------------------------------ features
    def _relevance(self, aid: int, pid: str, interests: set[str], in_audience: bool) -> float:
        mine = set(self.profiles[aid]["persona"]["interests"])
        overlap = min(1.0, len(mine & interests) / 2) if interests else 0.0
        return round(min(1.0, (0.45 if in_audience else 0.0) + 0.55 * overlap), 3)

    def _need(self, w: World, aid: int, lp: LiveProduct | None) -> float:
        if lp is None or lp.p.category.lower() not in PHONE_CATS:
            return 0.0
        ph = w.phones[aid]
        age = phone_age_years(ph, w.t) if "bought_t" in ph else 0.0
        return min(1.0, max(0.0, (age - 2) / 4) + (0.5 if ph.get("condition") not in ("ok", None) else 0.0))

    def _ctx(self, w: World, aid: int, pid: str, cid: str, *, mode: str, dwell: float, lit_night: bool,
             clutter: int, on_phone: bool) -> tuple[AttentionCtx, LiveProduct | None]:
        lp = self.live.get(pid)
        if lp is not None:
            rel = self._relevance(aid, pid, lp.interests, aid in lp.audience)
        else:
            b = self.baseline[[x["id"] for x in self.baseline].index(pid.split(":", 1)[1])]
            rel = self._relevance(aid, pid, set(b["interests"]), False)
        n = self.seen.get(f"{aid}|{cid}", [0, 0])
        fatigue = float(w.needs[aid, 3]) if w.needs.shape[1] > 3 else 0.0
        return AttentionCtx(mode=mode, dwell_s=dwell, lit_night=lit_night, clutter=clutter, on_phone=on_phone,
                            fatigue=min(1.0, fatigue), relevance=rel, attitude=self._attitude(aid, pid),
                            familiarity=1.0 if aid in self.aware.get(pid, set()) else 0.0,
                            need=self._need(w, aid, lp), n_seen=n[0], n_noticed=n[1]), lp

    def _attitude(self, aid: int, pid: str) -> float:
        """Current attitude of one agent to one product: computed by the opinion engine when it is on."""
        if self.opinion is not None:
            return float(self.opinion.attitude(aid, pid)) if pid in self.live else 0.0
        return self.attitude.get(f"{aid}|{pid}", 0.0)

    @staticmethod
    def _source_of(channel: str) -> str:
        return {"review": "review", "community": "community"}.get(channel, "ad")

    def _observe(self, aid: int, pid: str, channel: str, stim: StimulusRecord, strength: float = 1.0) -> None:
        """A noticed creative becomes evidence about the attributes it talks about (generic ads: the brand only)."""
        if self.opinion is None:
            return
        text = " ".join([*stim.claims_carried, stim.hook, stim.description])
        covered = attrs_in(text) or ["brand"]
        self.opinion.evidence(aid, pid, covered, self._source_of(channel), strength=strength)

    def _stim(self, pid: str, cid: str) -> StimulusRecord | None:
        if pid.startswith("baseline:"):
            return self.baseline_stims.get(pid.split(":", 1)[1])
        lp = self.live.get(pid)
        return lp.stim.get(cid) if lp else None

    def _on_phone(self, w: World, aid: int, m: int) -> bool:
        return any(s[0] <= m < s[0] + s[1] for s in self.profiles[aid]["media"]["feed_sessions"])

    # ------------------------------------------------------------------ hoardings (C-01, A-01/02)
    def _hoardings(self, w: World, bus: EventBus, t: int, m: int) -> None:
        if not self.site_map:
            return
        night = is_night(m)
        moving = [a for a in w.agents if a.route and not a.offmap and a.mode not in ("metro", "offmap")]
        if not moving:
            return
        pts = []
        for a in moving:
            for k in (0.75, 0.5, 0.25, 0.0):
                x, y, h = w.position(a, t - k)
                pts.append((a.id, x, y, h))
        arr = np.array([[p[1], p[2]] for p in pts])
        d = np.hypot(arr[:, None, 0] - self.site_xy[None, :, 0], arr[:, None, 1] - self.site_xy[None, :, 1])
        hits = np.argwhere(d <= self.max_r)
        done: set[tuple[int, str]] = set()
        for pi, si in hits.tolist():
            aid, x, y, h = pts[pi]
            s = self.sites[si]
            asg = self.site_map.get(s.site_id)
            key = (aid, s.site_id)
            if asg is None or key in done:
                continue
            last = self.last_pass.get(key)
            if last is not None and t - last < 4:
                self.last_pass[key] = t
                done.add(key)
                continue
            faces = [asg["facing"]] if asg["facing"] is not None else list(s.facings)
            got = next(((f, o) for f in faces if (o := ots(s, f, x, y, h, minute_of_day=m)) is not None), None)
            if got is None:
                continue
            done.add(key)
            self.last_pass[key] = t
            f, o = got
            a = w.agents[aid]
            stim = self._stim(asg["product_id"], asg["creative_id"])
            if stim is None:
                continue
            ctx, lp = self._ctx(w, aid, asg["product_id"], asg["creative_id"], mode=a.mode,
                                dwell=dwell_seconds(s, a.mode, False), lit_night=night and s.lit,
                                clutter=self.clutter[s.site_id], on_phone=self._on_phone(w, aid, m))
            out = attend(s, o, stim, ctx, stream(w.seed, "attend", t, aid, s.site_id))
            ch = "bus_shelter" if s.kind == "bus_shelter" else ("metro_panel" if s.kind == "metro_panel" else "hoarding")
            self._exposure(w, bus, t, aid, asg["product_id"], asg["creative_id"], ch, out, stim, ctx,
                           site_id=s.site_id, place=s.area_label,
                           extra={"distance_m": o.distance_m, "angle_deg": o.angle_deg, "dwell_s": round(ctx.dwell_s, 1),
                                  "facing": f, "mode": a.mode, "lit": s.lit,
                                  "target": bool(lp is not None and aid in lp.audience),
                                  "rate_inr_day": round(s.rate_card_inr_week / 7)})

    # ------------------------------------------------------------------ exposure → thought
    def _exposure(self, w: World, bus: EventBus, t: int, aid: int, pid: str, cid: str, channel: str, outcome: str,
                  stim: StimulusRecord, ctx: AttentionCtx, *, site_id: str | None = None, place: str | None = None,
                  extra: dict[str, Any] | None = None) -> None:
        payload = {"channel": channel, "creative_id": cid, "outcome": outcome, **(extra or {})}
        ev = bus.new("exposure", t, aid, payload, product_id=pid, site_id=site_id)
        self.stats["exposures"] += 1
        k = f"{aid}|{cid}"
        n = self.seen.setdefault(k, [0, 0])
        n[0] += 1
        noticed = outcome in ("notice", "partial", "full")
        if not noticed:
            return
        n[1] += 1
        self.stats["notices"] += 1
        if pid.startswith("baseline:"):
            if stream(w.seed, "baseline_thought", t, aid).random() < float(BASELINE["thought_sample"]):
                b = self.baseline_stims[pid.split(":", 1)[1]]
                bus.new("thought", t, aid, {"trigger_event_id": ev.event_id, "text": f"Saw the ad: {b.hook}.",
                                            "why_noticed": "ambient ad", "attitude_delta": 0.0, "importance": 1,
                                            "channel": channel}, product_id=pid, site_id=site_id, rendered=False)
            return
        lp = self.live[pid]
        self.aware[pid].add(aid)
        self._observe(aid, pid, channel, stim, 0.6 if outcome == "partial" else 1.0)
        meta = {"aid": aid, "pid": pid, "cid": cid, "channel": channel, "site_id": site_id, "place": place,
                "trigger": ev.event_id, "rel": ctx.relevance, "stim": stim,
                "opinions": self.opinion.brief(aid, pid) if self.opinion is not None else ""}
        if self.gov.allow("P1", EST["P1"]):
            key = f"th:{ev.event_id}"
            self._meta[key] = meta
            self.queue.submit(key, self._think(meta, t), t, THOUGHT_DELAY, lambda: None)
        else:
            out = rule_thought(stim, ctx.relevance, channel, lp.p.name, place)
            self._emit_thought(w, bus, t, meta, out, rendered=False)
            self._background(apply_thought(aid, pid, out, t=t, channel=channel, event_ref=ev.event_id, store=self.store,
                                           llm=None, on_event=None, product_name=lp.p.name, place=place,
                                           set_attitude=self.opinion is None))

    def _think(self, meta: dict[str, Any], t: int) -> Any:
        lp = self.live[meta["pid"]]
        return lambda: think_on_notice(meta["aid"], meta["pid"], lp.p.name, meta["stim"], meta["channel"],
                                       meta["place"], t, store=self.store, llm=self.llm, now=simtime.fmt(t),
                                       event_ref=meta["trigger"], on_event=self._hook(meta["aid"], t),
                                       opinions=meta.get("opinions", ""), set_attitude=self.opinion is None)

    def _hook(self, aid: int, t: int) -> Any:
        bus = self._bus

        def on_event(kind: str, payload: dict[str, Any]) -> None:
            if bus is not None:
                bus.new(kind, t, aid, payload)
        return on_event

    _bus: EventBus | None = None

    def _emit_thought(self, w: World, bus: EventBus, t: int, meta: dict[str, Any], out: dict[str, Any],
                      rendered: bool) -> None:
        aid, pid = meta["aid"], meta["pid"]
        lp = self.live[pid]
        payload = {"trigger_event_id": meta["trigger"], "channel": meta["channel"], "creative_id": meta["cid"],
                   "text": out["thought"], "why_noticed": out["why_noticed"], "attitude_delta": out["attitude_delta"],
                   "reasons_for": out["reasons_for"], "reasons_against": out["reasons_against"],
                   "open_questions": out["open_questions"], "intent_change": out["intent_change"],
                   "wants_to_tell": out["wants_to_tell"], "importance": out["importance"]}
        ev = bus.new("thought", t, aid, payload, product_id=pid, site_id=meta["site_id"], rendered=rendered)
        key = f"{aid}|{pid}"
        if self.opinion is not None:                   # the model's reaction is a small nudge on a computed attitude
            self.opinion.add_reaction(aid, pid, float(out["attitude_delta"]))
            self.attitude[key] = self.opinion.attitude(aid, pid)
        else:
            self.attitude[key] = max(-1.0, min(1.0, self.attitude.get(key, 0.0) + float(out["attitude_delta"])))
        w.counters["thoughts_today"] += 1
        self.stats["thoughts_rendered" if rendered else "thoughts_unrendered"] += 1
        w.live_evts.append({"k": "notice", "a": aid, "site_id": meta["site_id"], "product": pid,
                            "channel": meta["channel"], "thought": out["thought"] if rendered else ""})
        if self.social is not None:
            self.social.remember(aid, out["thought"], int(out["importance"]), "ad_thought", t, tag=lp.p.name)
            self.social.salient_products.setdefault(aid, [])
            sp = self.social.salient_products[aid]
            if pid not in sp:
                sp.append(pid)
                del sp[:-3]
        doc = {"t": t, "label": simtime.fmt(t), "kind": "ad_thought", "agent_id": aid,
               "trigger": {"channel": meta["channel"], "site_id": meta["site_id"], "creative_id": meta["cid"]},
               "text": out["thought"], "product_id": pid, "attitude_delta": out["attitude_delta"],
               "rendered": rendered}
        self._background(asyncio.to_thread(self.store.set, f"agents/{aid}/thoughts", ev.event_id, doc))
        if rendered:
            self._background(self._texts(bus, [("thought", aid, ev.event_id, out["thought"], t, pid)]))

    async def _apply(self, w: World, bus: EventBus, t: int) -> None:
        self._bus = bus
        for key, res in await self.queue.collect(t):
            if key.startswith("th:"):
                meta = self._meta.pop(key, None)
                if meta is None:
                    continue
                if res is None:
                    lp = self.live[meta["pid"]]
                    out = rule_thought(meta["stim"], meta["rel"], meta["channel"], lp.p.name, meta["place"])
                    self._emit_thought(w, bus, t, meta, out, rendered=False)
                    self._background(apply_thought(meta["aid"], meta["pid"], out, t=t, channel=meta["channel"],
                                                   event_ref=meta["trigger"], store=self.store, llm=None,
                                                   on_event=None, product_name=lp.p.name, place=meta["place"],
                                                   set_attitude=self.opinion is None))
                    continue
                out, cost = res
                self._cost(cost, "P1")
                self._emit_thought(w, bus, t, meta, out, rendered=True)
            elif key.startswith("rev:"):
                self._apply_review(w, bus, t, key, res)
            elif key.startswith("com:"):
                self._apply_reply(w, bus, t, key, res)

    def _cost(self, cost: float, pc: str) -> None:
        if cost:
            self.gov.record(cost, pc)
            self.stats["cost_usd"] += cost

    # ------------------------------------------------------------------ feeds, community, print (C-02/03/05, A-04)
    def _feeds_and_print(self, w: World, bus: EventBus, t: int, m: int) -> None:
        day = simtime.day_of(t)
        for prof in self.profiles:
            aid = prof["agent_id"]
            a = w.agents[aid]
            if a.activity == "sleep":
                continue
            md = prof["media"]
            if md.get("newspaper") and m == 400 + (aid * 37) % 80:
                self._newspaper(w, bus, t, aid, day)
            for start, minutes, app in md["feed_sessions"]:
                if start != m:
                    continue
                if app == "community":
                    self._community_session(w, bus, t, aid)
                else:
                    self._feed_session(w, bus, t, aid, int(minutes), app)

    def _feed_session(self, w: World, bus: EventBus, t: int, aid: int, minutes: int, app: str) -> None:
        rng = stream(w.seed, "feed", t, aid)
        n_items = max(2, min(8, minutes // 4))
        items: list[tuple[str, str, str, StimulusRecord, float]] = []   # (pid, cid, channel, stim, interest)
        for pid, lp in sorted(self.live.items()):
            if not lp.in_flight(t) or lp.p.plan is None:
                continue
            reel = lp.p.plan.reel or {}
            cid = str(reel.get("creative_id") or "")
            stim = lp.stim.get(cid) if cid else None
            if stim is None:
                continue
            k = f"{aid}|{pid}"
            if self.reel_today.get(k, 0) >= int(reel.get("freq_cap", 3)):
                continue
            if self.reel_impr.get(pid, 0) >= int(reel.get("impressions_day", 0) or 0):
                continue
            inter = self._relevance(aid, pid, lp.interests, aid in lp.audience)
            p_show = 0.85 if aid in lp.audience else 0.04 + 0.1 * inter
            if rng.random() < p_show:
                items.append((pid, cid, "reel", stim, inter))
        follows = set(self.profiles[aid]["media"]["follows"])
        for r in self.reviews:
            if r["state"] == "published" and r["reviewer"] in follows and t - r["t_publish"] < 3 * 1440 \
                    and f"{aid}|review-{r['review_id']}" not in self.seen:
                lp = self.live.get(r["product_id"])
                if lp is not None:
                    stim = StimulusRecord(creative_id=f"review-{r['review_id']}", salience=0.7, clarity=0.8,
                                          hook=r["title"], claims_carried=[], tone="review", readable_at_distance=True,
                                          description=f"A video review by a reviewer you follow: “{r['title']}”. "
                                                      f"{r['summary'][:200]}")
                    items.append((r["product_id"], stim.creative_id, "review", stim,
                                  self._relevance(aid, r["product_id"], lp.interests, aid in lp.audience)))
        while len(items) < n_items and rng.random() < float(BASELINE["feed_share"]) * 2:
            b = self.baseline[int(rng.integers(0, len(self.baseline)))]
            items.append((f"baseline:{b['id']}", f"baseline-{b['id']}", "reel", self.baseline_stims[b["id"]],
                          self._relevance(aid, "", set(b["interests"]), False)))
        items = items[:n_items]
        order: list[int] = [int(x) for x in rng.permutation(len(items))] if items else []
        for idx, j in enumerate(order):
            pid, cid, ch, stim, inter = items[int(j)]
            ctx, _ = self._ctx(w, aid, pid, cid, mode="idle", dwell=15, lit_night=False, clutter=0, on_phone=True)
            out = attend_feed(stim, inter, idx, ctx, stream(w.seed, "feed_item", t, aid, cid))
            if ch == "reel" and not pid.startswith("baseline:"):
                self.reel_today[f"{aid}|{pid}"] = self.reel_today.get(f"{aid}|{pid}", 0) + 1
                self.reel_impr[pid] = self.reel_impr.get(pid, 0) + 1
            self._exposure(w, bus, t, aid, pid, cid, ch, out, stim, ctx, place=app,
                           extra={"app": app, "position": idx, "mode": "idle"})

    def _newspaper(self, w: World, bus: EventBus, t: int, aid: int, day: int) -> None:
        for pid, lp in sorted(self.live.items()):
            if lp.p.plan is None or (day - lp.launch_day) not in lp.p.plan.newspaper_days:
                continue
            stim = lp.stimulus("newspaper")
            if stim is None:
                continue
            cid = lp.by_kind["newspaper"]
            ctx, _ = self._ctx(w, aid, pid, cid, mode="idle", dwell=20, lit_night=False, clutter=0, on_phone=False)
            out = attend_print("half", "p3", ctx.relevance, ctx, stim, stream(w.seed, "print", day, aid, pid))
            self._exposure(w, bus, t, aid, pid, cid, "newspaper", out, stim, ctx, place="the morning paper",
                           extra={"size": "half", "page": "p3", "mode": "idle"})

    def _store_displays(self, w: World, bus: EventBus, t: int) -> None:
        if not self.live:
            return
        day = simtime.day_of(t)
        for a in w.agents:
            st = self.store_by_place.get(a.place_id or "")
            if st is None or a.route or a.activity == "store_shift" or f"{a.id}|{st.store_id}|{day}" in self.visited:
                continue
            self.visited.add(f"{a.id}|{st.store_id}|{day}")
            for pid, lp in sorted(self.live.items()):
                if lp.p.plan is None or st.store_id not in lp.p.plan.stores:
                    continue
                stim = lp.stimulus("store_display")
                if stim is None:
                    continue
                cid = lp.by_kind["store_display"]
                ctx, _ = self._ctx(w, a.id, pid, cid, mode="idle", dwell=40, lit_night=False, clutter=2,
                                   on_phone=False)
                out = attend_print("full", "front", ctx.relevance, ctx, stim, stream(w.seed, "display", day, a.id, pid))
                self._exposure(w, bus, t, a.id, pid, cid, "store_display", out, stim, ctx, place=st.name,
                               extra={"store_id": st.store_id, "mode": "idle"})

    # ------------------------------------------------------------------ reviewers (C-04)
    def _reviewers(self, w: World, bus: EventBus, t: int) -> None:
        for r in self.reviews:
            lp = self.live.get(r["product_id"])
            if lp is None:
                continue
            if r["state"] == "due" and t >= r["t_private"]:
                r["state"] = "writing"
                key = f"rev:{r['reviewer']}:{r['product_id']}"
                if self.gov.allow("P5", EST["P5"]) or self.gov.allow("P2", EST["P5"]):
                    rid, p = r["reviewer"], lp.p
                    self.queue.submit(key, self._review_call(rid, p, t), t, 5, lambda: None)
                else:
                    self.queue.submit(key, self._none, t, 1, lambda: None)
            elif r["state"] == "private" and t >= r["t_publish"]:
                self._publish(w, bus, t, r)

    def _review_call(self, rid: int, p: Product, t: int) -> Callable[[], Awaitable[Any]]:
        return lambda: community.write_review(rid, p, t, store=self.store, llm=self.llm, now=simtime.fmt(t))

    def _reply_call(self, aid: int, th: dict[str, Any], t: int) -> Callable[[], Awaitable[Any]]:
        return lambda: community.reply(aid, th, [c["text"] for c in th["comments"]], t, store=self.store,
                                       llm=self.llm, now=simtime.fmt(t))

    async def _none(self) -> None:
        return None

    def _apply_review(self, w: World, bus: EventBus, t: int, key: str, res: Any) -> None:
        _, rid, pid = key.split(":", 2)
        r = next((x for x in self.reviews if x["reviewer"] == int(rid) and x["product_id"] == pid), None)
        lp = self.live.get(pid)
        if r is None or lp is None:
            return
        rendered = res is not None
        out, cost = res if rendered else (community.template_review(lp.p, int(rid)), 0.0)
        self._cost(cost, "P5")
        r.update({"state": "private", "review_id": f"{pid}-{rid}", "rendered": rendered, **out})
        r["t_publish"] = max(r["t_publish"], t + 30)
        ev = bus.new("review_private", t, int(rid), {"review_id": r["review_id"], "private_opinion": out["private_opinion"],
                                                     "rating": out["rating"]}, product_id=pid, rendered=rendered)
        r["private_event_id"] = ev.event_id
        if rendered:
            self._background(self._texts(bus, [("thought", int(rid), ev.event_id, out["private_opinion"], t, pid)]))

    def _publish(self, w: World, bus: EventBus, t: int, r: dict[str, Any]) -> None:
        r["state"] = "published"
        pid, rid = r["product_id"], int(r["reviewer"])
        review = {"review_id": r["review_id"], "reviewer": rid, "product_id": pid,
                  "private_opinion": r["private_opinion"], "title": r["title"], "summary": r["summary"],
                  "rating": r["rating"], "pros": r["pros"], "cons": r["cons"], "t_private": r["t_private"],
                  "t_published": t}
        pub = {k: v for k, v in review.items() if k != "private_opinion"}
        ev = bus.new("review_published", t, rid, {**pub, "private_event_id": r.get("private_event_id")},
                     product_id=pid, rendered=bool(r.get("rendered")))
        r["t_publish"] = t
        self.stats["reviews"] += 1
        self._background(asyncio.to_thread(self.store.set, "reviews", r["review_id"],
                                           {**pub, "event_id": ev.event_id, "followers": len(self.followers.get(rid, []))}))
        self._background(self._texts(bus, [("review", rid, ev.event_id, f"{r['title']}. {r['summary']}", t, pid)]))
        lp = self.live[pid]
        forum = "r/BangaloreTech" if lp.p.category.lower() in PHONE_CATS else "r/BangaloreStyle"
        body = f"{r['summary']}\nRating: {r['rating']:.0f}/10 · Pros: {', '.join(r['pros'])} · Cons: {', '.join(r['cons'])}"
        self._new_thread(w, bus, rid, forum, f"Review: {r['title']}", body, pid)
        w.live_evts.append({"k": "review", "a": rid, "product": pid, "title": r["title"]})

    # ------------------------------------------------------------------ community (C-05)
    def _new_thread(self, w: World, bus: EventBus, author: int, forum: str, title: str, body: str,
                    pid: str | None) -> dict[str, Any]:
        t = w.t
        th = {"thread_id": f"th-{t}-{author}", "forum": forum, "author": author, "title": title[:160],
              "body": body[:1200], "t": t, "product_id": pid, "upvotes": 0, "comments": []}
        ev = bus.new("thread", t, author, {k: v for k, v in th.items() if k != "comments"}, product_id=pid)
        self.threads.append(th)
        del self.threads[:-60]
        self.stats["threads"] += 1
        self._background(asyncio.to_thread(self.store.set, "threads", str(th["thread_id"]),
                                           {**{k: v for k, v in th.items() if k != "comments"}, "n_comments": 0,
                                            "event_id": ev.event_id}))
        w.live_evts.append({"k": "post", "a": author, "thread_id": th["thread_id"], "title": th["title"]})
        return th

    def _community_session(self, w: World, bus: EventBus, t: int, aid: int) -> None:
        recent = [th for th in self.threads if t - th["t"] < 3 * 1440 and th["author"] != aid]
        top = sorted(recent, key=lambda th: (-(th["upvotes"] + 3 * len(th["comments"])), -th["t"]))[:3]
        rng = stream(w.seed, "community", t, aid)
        for idx, th in enumerate(top):
            pid = th.get("product_id")
            lp = self.live.get(pid or "")
            if lp is None:
                continue
            stim = StimulusRecord(creative_id=th["thread_id"], salience=0.55, clarity=0.8, hook=th["title"],
                                  claims_carried=[], tone="discussion", readable_at_distance=True,
                                  description=f"A forum thread in {th['forum']}: “{th['title']}”. {th['body'][:160]}")
            ctx, _ = self._ctx(w, aid, lp.p.product_id, th["thread_id"], mode="idle", dwell=30, lit_night=False,
                               clutter=0, on_phone=True)
            out = attend_feed(stim, ctx.relevance, idx, ctx, stream(w.seed, "thread", t, aid, th["thread_id"]))
            bus.new("exposure", t, aid, {"channel": "community", "creative_id": th["thread_id"], "outcome": out,
                                         "forum": th["forum"], "mode": "idle"}, product_id=lp.p.product_id)
            self.stats["exposures"] += 1
            if out == "scroll":
                continue
            self.aware[lp.p.product_id].add(aid)
            self._observe(aid, lp.p.product_id, "community", stim, 1.0 if out == "full" else 0.6)
            opin = float(self.profiles[aid]["persona"]["disclosure"].get("opinions", 0.5))
            wants_comment = rng.random() < 0.10 + 0.25 * opin
            key = f"com:{aid}:{th['thread_id']}"
            if wants_comment and self.gov.allow("P5", EST["P5"]):
                self._meta[key] = {"aid": aid, "thread": th}
                self.queue.submit(key, self._reply_call(aid, th, t), t, 3, lambda: None)
            else:
                act = "upvote" if rng.random() < 0.3 else "none"
                bus.new("community_thought", t, aid, {"thread_id": th["thread_id"], "text": f"Read “{th['title']}”.",
                                                      "decided_action": act}, product_id=pid, rendered=False)
                if act == "upvote":
                    self._upvote(bus, t, aid, th)

    def _upvote(self, bus: EventBus, t: int, aid: int, th: dict[str, Any]) -> None:
        th["upvotes"] += 1
        bus.new("upvote", t, aid, {"target": th["thread_id"]}, product_id=th.get("product_id"))
        self._background(asyncio.to_thread(self.store.set, "threads", th["thread_id"], {"upvotes": th["upvotes"]},
                                           True))

    def _apply_reply(self, w: World, bus: EventBus, t: int, key: str, res: Any) -> None:
        meta = self._meta.pop(key, None)
        if meta is None:
            return
        aid, th = meta["aid"], meta["thread"]
        if res is None:
            bus.new("community_thought", t, aid, {"thread_id": th["thread_id"], "text": f"Read “{th['title']}”.",
                                                  "decided_action": "none"}, product_id=th.get("product_id"),
                    rendered=False)
            return
        out, cost = res
        self._cost(cost, "P5")
        tev = bus.new("community_thought", t, aid, {"thread_id": th["thread_id"], "text": out["thought"],
                                                    "decided_action": out["action"],
                                                    "attitude_delta": out["attitude_delta"]},
                      product_id=th.get("product_id"))
        texts: list[tuple[str, int, str | None, str, int, str | None]] = [
            ("thought", aid, tev.event_id, out["thought"], t, th.get("product_id"))]
        if out["action"] == "upvote":
            self._upvote(bus, t, aid, th)
        elif out["action"] == "comment" and out["comment"].strip():
            post = {"post_id": f"c-{t}-{aid}", "thread_id": th["thread_id"], "author": aid, "text": out["comment"],
                    "t": t, "upvotes": 0}
            cev = bus.new("comment", t, aid, {**post, "thought_event_id": tev.event_id}, product_id=th.get("product_id"))
            th["comments"].append(post)
            self.stats["comments"] += 1
            self._background(asyncio.to_thread(self.store.set, f"threads/{th['thread_id']}/comments", post["post_id"],
                                               {**post, "event_id": cev.event_id}))
            self._background(asyncio.to_thread(self.store.set, "threads", th["thread_id"],
                                               {"n_comments": len(th["comments"])}, True))
            texts.append(("comment", aid, cev.event_id, out["comment"], t, th.get("product_id")))
            w.live_evts.append({"k": "comment", "a": aid, "thread_id": th["thread_id"], "text": out["comment"]})
        self._background(self._texts(bus, texts))

    # ------------------------------------------------------------------ plumbing
    def _background(self, coro: Awaitable[Any]) -> None:
        fut = asyncio.ensure_future(coro)
        self._bg.add(fut)
        fut.add_done_callback(self._bg.discard)

    async def _texts(self, bus: EventBus, rows: list[tuple[str, int, str | None, str, int, str | None]]) -> None:
        vecs: list[list[float] | None] = [None] * len(rows)
        if self.embed_texts:
            try:
                vecs = list(await embed_cached(self.llm, [r[3][:2000] for r in rows]))
            except Exception:  # noqa: BLE001
                log.warning("text embedding failed", exc_info=True)
        for (kind, aid, eid, text, t, pid), v in zip(rows, vecs, strict=True):
            bus.emit_text({"text_id": f"{eid or kind}:{aid}:{t}", "event_id": eid, "t": t, "day": simtime.day_of(t),
                           "kind": kind, "agent_id": aid, "product_id": pid, "session_id": None,
                           "private": kind == "thought", "text": text, "embedding": v or []})

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form (in-flight model calls are dropped)."""
        return {"seen": self.seen, "attitude": self.attitude, "aware": {k: sorted(v) for k, v in self.aware.items()},
                "reel_today": self.reel_today, "reel_impr": self.reel_impr, "visited": sorted(self.visited),
                "reviews": [{**r, "state": "due" if r["state"] == "writing" else r["state"]} for r in self.reviews],
                "threads": self.threads, "stats": self.stats, "pending": self.pending,
                "campaign_over": sorted(self.campaign_over)}

    def load(self, d: dict[str, Any]) -> None:
        """Restore from to_dict."""
        self.seen = {k: list(v) for k, v in (d.get("seen") or {}).items()}
        self.attitude = dict(d.get("attitude") or {})
        self.aware = {k: set(v) for k, v in (d.get("aware") or {}).items()}
        self.reel_today = dict(d.get("reel_today") or {})
        self.reel_impr = dict(d.get("reel_impr") or {})
        self.visited = set(d.get("visited") or [])
        self.reviews = list(d.get("reviews") or [])
        self.threads = list(d.get("threads") or [])
        self.stats.update(d.get("stats") or {})
        self.pending = list(d.get("pending") or [])
        self.campaign_over = set(d.get("campaign_over") or [])
