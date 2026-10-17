"""Community (Reddit-style) and review schemas (INTERFACES §2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Thread(BaseModel):
    """A community thread."""

    thread_id: str
    forum: Literal["r/IndiranagarLife", "r/BangaloreTech", "r/BangaloreStyle"]
    author: int
    title: str
    body: str
    t: int
    product_id: str | None
    upvotes: int


class Post(BaseModel):
    """A comment on a thread."""

    post_id: str
    thread_id: str
    author: int
    text: str
    t: int
    upvotes: int


class Review(BaseModel):
    """A reviewer's private opinion and published review."""

    review_id: str
    reviewer: int
    product_id: str
    private_opinion: str
    title: str
    summary: str
    rating: float
    pros: list[str]
    cons: list[str]
    t_private: int
    t_published: int
