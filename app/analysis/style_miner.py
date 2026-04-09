"""Extract style patterns from collected content."""
from __future__ import annotations

import json

from app.llm.client import chat
from app.schemas.content import CollectedContent, StylePattern


async def mine_style(content: CollectedContent) -> StylePattern:
    """Ask the LLM to extract a structured style pattern from a viral post."""
    comments_text = "\n".join(f"- {c.text[:100]}" for c in content.comments[:3])
    prompt = (
        "Analyse this viral social media post and extract its style pattern.\n\n"
        f"Post by @{content.author} ({content.metrics.likes} likes, {content.metrics.reposts} reposts):\n"
        f"{content.body_text[:800]}\n\n"
        f"Top comments:\n{comments_text}\n\n"
        "Return a JSON object with these keys:\n"
        "hook_type (question/stat/story/bold_claim/list),\n"
        "opening_pattern (first sentence pattern),\n"
        "narrative_structure (problem-solution/story/list/data/opinion),\n"
        "insight_density (high/medium/low),\n"
        "cta_style (question/directive/implicit/none),\n"
        "emoji_usage (none/light/heavy),\n"
        "link_usage (none/light/heavy),\n"
        "code_usage (true/false),\n"
        "image_usage (none/decorative/data-driven),\n"
        "title_formula (if applicable, the title pattern),\n"
        "high_freq_words (array of 5 notable words)\n"
    )
    raw = await chat(
        [{"role": "user", "content": prompt}],
        json_mode=True,
        temperature=0.2,
        max_tokens=600,
    )
    try:
        data = json.loads(raw)
        return StylePattern(source_content_id=content.content_id, **data)
    except Exception:
        return StylePattern(source_content_id=content.content_id)
