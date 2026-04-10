"""综合评分 — 相关性 × 互动权重 × 时效性。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.content import CollectedContent

# 权重配置
W_RELEVANCE = 0.3   # LLM 相关性
W_ENGAGEMENT = 0.4  # 互动热度
W_FRESHNESS = 0.3   # 时效性


def _engagement_raw(c: CollectedContent) -> float:
    """计算互动原始分。"""
    return (
        c.metrics.likes
        + c.metrics.reposts * 1.5
        + len(c.comments) * 2
        + c.metrics.views * 0.01
    )


def _normalize(values: list[float], default: float = 3.0) -> list[float]:
    """将一组值归一化到 0-5 区间。"""
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [default] * len(values)
    return [5.0 * (v - mn) / (mx - mn) for v in values]


def _freshness(c: CollectedContent) -> float:
    """时效性评分：7天内=5，30天内=3，更久=1。"""
    if not c.published_at:
        return 2.0
    now = datetime.now(timezone.utc)
    try:
        published = c.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        days = (now - published).days
    except Exception:
        return 2.0

    if days <= 7:
        return 5.0
    elif days <= 30:
        return 3.0
    else:
        return 1.0


def compute_final_score(content: CollectedContent, batch: list[CollectedContent]) -> float:
    """计算综合评分。

    final_score = relevance * 0.3 + engagement_normalized * 0.4 + freshness * 0.3
    """
    relevance = content.relevance_score  # 0-5

    # 批次内归一化互动分
    engagement_scores = [_engagement_raw(c) for c in batch]
    raw = _engagement_raw(content)
    normalized = _normalize(engagement_scores)
    idx = batch.index(content)
    engagement = normalized[idx]

    fresh = _freshness(content)

    return round(relevance * W_RELEVANCE + engagement * W_ENGAGEMENT + fresh * W_FRESHNESS, 2)


def score_batch(items: list[CollectedContent]) -> list[CollectedContent]:
    """对一批内容统一评分，按 final_score 降序排序。"""
    for item in items:
        item.final_score = compute_final_score(item, items)
    return sorted(items, key=lambda c: c.final_score, reverse=True)
