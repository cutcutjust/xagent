"""Generate UniversalDraft from research + style patterns."""
from __future__ import annotations

import uuid

from app.llm.client import chat
from app.schemas.content import CollectedContent, StylePattern, UniversalDraft


async def create_draft(
    sources: list[CollectedContent],
    styles: list[StylePattern],
    topic_hint: str = "",
) -> UniversalDraft:
    """Generate a platform-agnostic draft from collected sources."""
    sources_text = "\n\n".join(
        f"[Source {i+1} from @{s.author or '?'} — {s.metrics.likes} likes]\n{s.body_text[:600]}"
        for i, s in enumerate(sources[:5])
    )

    style_summary = ""
    if styles:
        style_summary = (
            "Common patterns in successful posts:\n"
            + "\n".join(
                f"- Hook: {p.hook_type}, Structure: {p.narrative_structure}, "
                f"Density: {p.insight_density}, CTA: {p.cta_style}"
                for p in styles[:3]
            )
        )

    refs = [s.source_url for s in sources if s.source_url]
    assets = [img for s in sources for img in s.images[:2]]

    # Step 1: decide angle + topic
    angle_prompt = (
        f"You are a content strategist. Given these source posts about AI/startup topics:\n\n"
        f"{sources_text}\n\n"
        f"{style_summary}\n\n"
        f"Topic hint: {topic_hint}\n\n"
        "Identify the most compelling angle for a new original article. "
        "Return JSON: {\"topic\": \"...\", \"angle\": \"...\", \"title\": \"...\", \"key_points\": [\"...\",\"...\",\"...\"]}"
    )
    angle_raw = await chat(
        [{"role": "user", "content": angle_prompt}],
        json_mode=True,
        temperature=0.7,
        max_tokens=400,
    )
    import json
    try:
        meta = json.loads(angle_raw)
    except Exception:
        meta = {"topic": topic_hint or "AI trends", "angle": "analysis", "title": "Untitled", "key_points": []}

    # Step 2: write the body
    body_prompt = (
        f"Write a comprehensive, insightful article draft.\n\n"
        f"Topic: {meta.get('topic','')}\n"
        f"Angle: {meta.get('angle','')}\n"
        f"Title: {meta.get('title','')}\n"
        f"Key points to cover: {', '.join(meta.get('key_points', []))}\n\n"
        f"Source material:\n{sources_text}\n\n"
        "Write in Markdown. Be direct, insightful, and include specific examples. "
        "Target 800-1200 words."
    )
    body = (
        await chat(
            [{"role": "user", "content": body_prompt}],
            temperature=0.75,
            max_tokens=2500,
        )
    ).strip()

    # Step 3: summary
    summary_prompt = (
        f"Summarize this article in 2 sentences:\n\nTitle: {meta.get('title','')}\n\n{body[:1000]}"
    )
    summary = (
        await chat([{"role": "user", "content": summary_prompt}], max_tokens=120, temperature=0.3)
    ).strip()

    return UniversalDraft(
        draft_id=uuid.uuid4().hex,
        topic=meta.get("topic", ""),
        angle=meta.get("angle", ""),
        title=meta.get("title", "Untitled"),
        summary=summary,
        body_markdown=body,
        key_points=meta.get("key_points", []),
        references=refs,
        suggested_assets=assets,
        source_content_ids=[s.content_id for s in sources],
    )
