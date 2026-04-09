"""Notion API integration — stream research content into a Notion database."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from notion_client import AsyncClient

from app.core.config import get_settings
from app.core.errors import NotionError
from app.core.logger import logger
from app.schemas.content import CollectedContent, PlatformDraft, UniversalDraft

_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    global _client
    if _client is None:
        s = get_settings()
        if not s.notion_token:
            raise NotionError("NOTION_TOKEN not configured")
        _client = AsyncClient(auth=s.notion_token)
    return _client


async def save_research(content: CollectedContent) -> str:
    """Create a Notion page for collected research. Returns the page ID."""
    s = get_settings()
    db_id = s.notion_research_db_id
    if not db_id:
        logger.warning("NOTION_RESEARCH_DB_ID not set — skipping Notion save")
        return ""

    client = _get_client()
    props: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": content.title or content.source_url[:80]}}]},
        "Platform": {"select": {"name": content.platform}},
        "URL": {"url": content.source_url},
        "Relevance": {"number": content.relevance_score},
        "Likes": {"number": content.metrics.likes},
        "Tags": {"multi_select": [{"name": t} for t in content.tags[:10]]},
        "Collected": {"date": {"start": content.collected_at.isoformat()}},
        "Status": {"select": {"name": "collected"}},
    }
    if content.author:
        props["Author"] = {"rich_text": [{"text": {"content": content.author}}]}

    children = _build_content_blocks(content)

    try:
        resp = await client.pages.create(
            parent={"database_id": db_id},
            properties=props,
            children=children,
        )
        page_id = resp["id"]
        logger.info(f"Notion page created: {page_id}")
        return page_id
    except Exception as e:
        raise NotionError(f"Failed to create Notion page: {e}") from e


async def save_draft(draft: UniversalDraft, platform_draft: PlatformDraft) -> str:
    """Save a publishing draft to Notion for human review."""
    s = get_settings()
    db_id = s.notion_draft_db_id
    if not db_id:
        logger.warning("NOTION_DRAFT_DB_ID not set — skipping Notion draft save")
        return ""

    client = _get_client()
    props: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": draft.title}}]},
        "Platform": {"select": {"name": platform_draft.platform}},
        "Type": {"select": {"name": platform_draft.post_type}},
        "Status": {"select": {"name": "pending_review"}},
        "Topic": {"rich_text": [{"text": {"content": draft.topic}}]},
        "Created": {"date": {"start": draft.created_at.isoformat()}},
    }
    body_block = {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": platform_draft.body[:2000]}}]
        },
    }
    try:
        resp = await client.pages.create(
            parent={"database_id": db_id},
            properties=props,
            children=[body_block],
        )
        return resp["id"]
    except Exception as e:
        raise NotionError(f"Failed to save draft to Notion: {e}") from e


async def update_status(page_id: str, status: str, url: str | None = None) -> None:
    """Update the Status field of a Notion page."""
    if not page_id:
        return
    client = _get_client()
    props: dict[str, Any] = {"Status": {"select": {"name": status}}}
    if url:
        props["Published URL"] = {"url": url}
    try:
        await client.pages.update(page_id=page_id, properties=props)
    except Exception as e:
        logger.warning(f"Failed to update Notion status: {e}")


def _build_content_blocks(c: CollectedContent) -> list[dict]:
    blocks: list[dict] = []

    def heading(text: str, level: int = 2) -> dict:
        return {
            "object": "block",
            "type": f"heading_{level}",
            f"heading_{level}": {"rich_text": [{"text": {"content": text}}]},
        }

    def paragraph(text: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": text[:2000]}}]},
        }

    if c.summary:
        blocks.append(heading("Summary"))
        blocks.append(paragraph(c.summary))

    if c.body_text:
        blocks.append(heading("Body"))
        # split into 2000-char chunks (Notion limit per block)
        body = c.body_text
        while body:
            blocks.append(paragraph(body[:2000]))
            body = body[2000:]

    if c.comments:
        blocks.append(heading("Top Comments"))
        for cm in c.comments[:5]:
            blocks.append(paragraph(f"@{cm.author or '?'}: {cm.text[:500]}"))

    if c.images:
        blocks.append(heading("Images (local paths)"))
        for img in c.images[:5]:
            blocks.append(paragraph(img))

    return blocks
