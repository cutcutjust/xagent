"""Core data models — platform-agnostic."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Comment(BaseModel):
    author: str | None = None
    text: str
    likes: int = 0
    url: str | None = None


class Metrics(BaseModel):
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    views: int = 0
    bookmarks: int = 0


class CollectedContent(BaseModel):
    """Raw research unit — what we collected from a platform page."""

    content_id: str
    platform: str
    source_url: str
    author: str | None = None
    title: str | None = None
    body_text: str = ""
    comments: list[Comment] = []
    metrics: Metrics = Field(default_factory=Metrics)
    images: list[str] = []           # local paths after download
    screenshots: list[str] = []      # local paths
    summary: str = ""
    relevance_score: float = 0.0     # 1-5
    tags: list[str] = []
    external_links: list[str] = []    # external URLs extracted from post body
    comment_links: list[str] = []     # X /status/ URLs of reply posts
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    notion_page_id: str | None = None
    raw_metadata: dict[str, Any] = {}


class StylePattern(BaseModel):
    """Extracted style pattern from a viral post."""

    source_content_id: str
    hook_type: str = ""            # question / stat / story / bold claim
    opening_pattern: str = ""
    narrative_structure: str = ""  # problem-solution / story / list / data
    insight_density: str = ""      # high / medium / low
    cta_style: str = ""
    emoji_usage: str = ""          # none / light / heavy
    link_usage: str = ""
    code_usage: bool = False
    image_usage: str = ""
    quote_style: str = ""
    title_formula: str = ""
    high_freq_words: list[str] = []


class UniversalDraft(BaseModel):
    """Platform-agnostic content draft produced by the writing module."""

    draft_id: str
    topic: str
    angle: str
    title: str
    summary: str
    body_markdown: str
    key_points: list[str] = []
    references: list[str] = []           # source URLs
    suggested_assets: list[str] = []     # local image paths
    source_content_ids: list[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "draft"                # draft | reviewed | published


class PlatformDraft(BaseModel):
    """Platform-formatted draft ready for publishing."""

    draft_id: str
    universal_draft_id: str
    platform: str
    post_type: str = "short_post"        # short_post | thread | article
    title: str | None = None
    body: str = ""
    thread_posts: list[str] = []         # for threads
    images: list[str] = []              # local paths
    links: list[str] = []
    tags: list[str] = []
    metadata: dict[str, Any] = {}
    status: str = "pending"             # pending | approved | published | failed
    published_url: str | None = None
    published_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
