"""All shared pydantic schemas (INTERFACES §2)."""

from pydantic import BaseModel

from shared.schemas.agent import AgentProfile, AgentState, MediaDiet, MoneyProfile, PersonaCore, Phone, Relationship
from shared.schemas.community import Post, Review, Thread
from shared.schemas.events import Event
from shared.schemas.memory import Belief, MemoryEntry
from shared.schemas.product import AudienceRule, Creative, Plan, PlannedSite, Product, StimulusRecord
from shared.schemas.social import Conversation, Inquiry, Message, SharePlan
from shared.schemas.world import Place, Site, Store

ALL_MODELS: list[type[BaseModel]] = [Place, Site, Store, PersonaCore, MediaDiet, MoneyProfile, Phone, AgentProfile, AgentState, Relationship,
              MemoryEntry, Belief, StimulusRecord, Creative, AudienceRule, PlannedSite, Plan, Product, SharePlan,
              Message, Conversation, Inquiry, Thread, Post, Review, Event]

__all__ = [
    "ALL_MODELS", "AgentProfile", "AgentState", "AudienceRule", "Belief", "Conversation", "Creative", "Event",
    "Inquiry", "MediaDiet", "MemoryEntry", "Message", "MoneyProfile", "PersonaCore", "Phone", "Place", "Plan",
    "PlannedSite", "Post", "Product", "Relationship", "Review", "SharePlan", "Site", "StimulusRecord", "Store",
    "Thread",
]
