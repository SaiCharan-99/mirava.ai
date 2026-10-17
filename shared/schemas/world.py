"""World schemas: places, hoarding sites, stores (INTERFACES §2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PlaceKind = Literal["home", "office", "techpark", "shop", "cafe", "restaurant", "store", "school", "college", "gym",
                    "park", "metro", "bus_stop", "news_vendor", "mall"]


class Place(BaseModel):
    """A place agents can be at (from OSM tags + overrides)."""

    place_id: str
    kind: PlaceKind
    name: str
    polygon: list[tuple[float, float]]
    entrances: list[tuple[float, float]]
    capacity: int
    opening_hours: dict[str, tuple[int, int]] | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class Site(BaseModel):
    """An out-of-home ad site; `facings` are the degrees each face points to (towards its audience)."""

    site_id: str
    kind: Literal["billboard", "unipole", "bus_shelter", "metro_panel", "facade_screen"]
    x: float
    y: float
    facings: list[float]
    width_m: float
    height_m: float
    lit: bool
    cone_half_angle_deg: float
    max_distance_m: float
    rate_card_inr_week: int
    area_label: str


class Store(BaseModel):
    """A fictional store (never a real retailer)."""

    store_id: str
    name: str
    kind: Literal["multi_brand", "phone_shop", "brand_store", "online"]
    place_id: str | None
    staff: list[int]
    opening_hours: tuple[int, int]
    stock: dict[str, int]
