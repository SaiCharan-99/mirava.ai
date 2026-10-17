"""Product, creative and plan schemas (INTERFACES §2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StimulusRecord(BaseModel):
    """What a creative is, as perceived (used in agent prompts)."""

    creative_id: str
    salience: float
    clarity: float
    hook: str
    claims_carried: list[str]
    tone: str
    readable_at_distance: bool
    description: str


class Creative(BaseModel):
    """One piece of marketing content."""

    creative_id: str
    product_id: str
    kind: Literal["hoarding", "bus_shelter", "reel", "social_post", "newspaper", "store_display", "reviewer_kit"]
    title: str
    text: str | None = None
    transcript: str | None = None
    scenes: list[str] = Field(default_factory=list)
    image_uri: str | None = None
    stimulus: StimulusRecord | None = None
    screened: bool = False


class AudienceRule(BaseModel):
    """A target audience filter."""

    description: str
    filter: dict
    count: int


class PlannedSite(BaseModel):
    """One site chosen by the auto planner, with its reason."""

    site_id: str
    facing: float
    creative_id: str
    est_target_ots_day: int
    reason: str


class Plan(BaseModel):
    """The automatic media plan for a product."""

    sites: list[PlannedSite]
    reel: dict
    newspaper_days: list[int]
    reviewers: list[int]
    community_seed: dict
    stores: list[str]
    flight_days: int
    generated_day: int


class Product(BaseModel):
    """A product launched into the world (products are data)."""

    product_id: str
    name: str
    brand: str
    category: str
    price_inr: int
    launch_offer: str | None
    features: list[str]
    claims: list[str]
    target_personas: list[str]
    audience: list[AudienceRule]
    strategy: dict
    creatives: list[Creative]
    plan: Plan | None
    status: Literal["draft", "ready", "live", "ended"]
    color: str
    launched_at_t: int | None = None
    understanding: dict | None = None
    graph: dict | None = None
