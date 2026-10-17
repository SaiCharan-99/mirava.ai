"""Agent schemas: persona, media diet, money, phone, profile, state, relationships (INTERFACES §2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PersonaCore(BaseModel):
    """Fixed persona core (L4 memory)."""

    bio_first_person: str
    big5: dict[Literal["O", "C", "E", "A", "N"], float]
    values: list[str]
    lifestyle: str
    interests: list[str]
    brand_attitudes: dict[str, float]
    speaking_style: str
    disclosure: dict[Literal["opinions", "money", "feelings", "plans"], float]


class MediaDiet(BaseModel):
    """Feeds, community, newspaper habits."""

    feed_sessions: list[tuple[int, int, str]]
    community: bool
    newspaper: bool
    news_app: bool
    follows: list[int]


class MoneyProfile(BaseModel):
    """Income, costs and credit in integer rupees."""

    monthly_income_inr: int
    pay_cycle: Literal["monthly", "weekly"]
    payday: int
    fixed_costs_inr: int
    savings_inr: int
    credit_card_limit_inr: int
    emi_eligible: bool


class Phone(BaseModel):
    """The phone an agent owns (real brands allowed, labelled simulated)."""

    brand: str
    tier: Literal["budget", "mid", "premium", "flagship"]
    model_label: str
    bought_t: int
    condition: Literal["ok", "cracked", "slow", "battery_weak", "lost"]
    battery_health: float
    satisfaction: float
    history: list[dict] = Field(default_factory=list)


class AgentProfile(BaseModel):
    """Static profile of one agent."""

    agent_id: int
    name: str
    age: int
    gender: str
    household_id: str
    role_in_household: str
    education: str
    occupation: str
    workplace_place_id: str | None
    home_place_id: str
    income_band: Literal["<25k", "25-50k", "50k-1L", "1-2L", ">2L"]
    commute_mode: Literal["walk", "two_wheeler", "car", "auto", "bus", "metro"]
    special_role: Literal["none", "reviewer", "salesperson", "news_desk"] = "none"
    persona: PersonaCore
    persona_card: str
    routine_id: str
    media: MediaDiet
    money: MoneyProfile
    possessions: dict[str, dict]
    assumed_fields: list[str] = Field(default_factory=list)


class AgentState(BaseModel):
    """Live, changing state of one agent."""

    agent_id: int
    t: int
    x: float
    y: float
    heading: float
    mode: str
    place_id: str | None
    activity: str
    needs: dict[Literal["energy", "hunger", "social", "fatigue", "stimulation"], float]
    mood: float
    plan: list[dict]
    session_id: str | None = None
    watched: bool = False


class Relationship(BaseModel):
    """An undirected tie between two agents."""

    a: int
    b: int
    kind: Literal["family", "partner", "friend", "colleague", "neighbour", "follower"]
    closeness: float
    channel: Literal["in_person", "online", "both"]
    last_t: int | None = None
