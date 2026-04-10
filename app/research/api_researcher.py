"""X 纯 API 调研器 — 无需浏览器/桌面权限，直接从 X API 获取所有数据。"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime

from app.core.config import load_yaml
from app.core.logger import logger
from app.llm.client import chat
from app.memory.sqlite_repo import save_content, save_reference, save_content_to_md
from app.desktop.research_agent import score_relevance, summarize_content, extract_tags, sync_to_notion
from app.research.scorer import score_batch
from app.schemas.content import CollectedContent, Comment
from rich.console import Console
from rich.text import Text

console = Console()

# ── 视觉常量 ─────────────────────────────────────────────────────────

C_DIM = "dim"
C_BRAND = "#6C63FF"
C_ACCENT = "#00D4AA"
C_WARN = "#FF6B6B"


def _fmt_num(n: int) -> str:
    """紧凑数字格式: 1234 → 1.2K, 1234567 → 1.2M"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _print_tweet_card(author: str, text: str, likes: int, replies: int, views: int, reposts: int, relevance: float | None = None, comments: int = 0, saved: bool = False) -> None:
    """两行紧凑输出一条帖子：第一行正文，第二行指标。"""
    # 正文行
    rel_style = C_ACCENT if relevance and relevance >= 4 else (C_WARN if relevance and relevance < 3 else "")
    rel_str = f"  R{relevance:.0f}" if relevance else ""
    body_line = Text()
    body_line.append(f"  @{author}", style="bold" if saved else "")
    if rel_str:
        body_line.append(rel_str, style=rel_style)
    body_line.append(f"  {text}")
    console.print(body_line)

    # 指标行
    metrics_line = Text()
    metrics_line.append("    ", style="")
    metrics_line.append(f"{_fmt_num(likes)}", style="dim")
    metrics_line.append(" likes  ", style="dim")
    metrics_line.append(f"{_fmt_num(reposts)}", style="dim")
    metrics_line.append(" reposts  ", style="dim")
    metrics_line.append(f"{_fmt_num(comments)}", style="dim")
    metrics_line.append(" comments  ", style="dim")
    metrics_line.append(f"{_fmt_num(views)}", style="dim")
    metrics_line.append(" views", style="dim")
    console.print(metrics_line)


class APIXResearcher:
    """X 调研 — 纯 API，无需 DesktopAgent / 浏览器 / macOS 权限。"""

    def __init__(self):
        self._collected_ids: set[str] = set()
        self._total_collected = 0

    # ── 主流程 ────────────────────────────────────────────────────────

    async def discover(
        self,
        topics: list[str] | None = None,
        target_posts: int = 50,
        min_comments: int = 10,
        research_context: str = "",
        min_valid_refs: int = 40,
    ) -> list[dict]:
        """纯 API 调研流程，循环搜索直到有效引用达标。

        1. 用 X API 搜索每个主题
        2. 按互动量排序
        3. 逐帖采集：API 正文/评论 → LLM 相关性打分（按 research_context）
        4. 综合评分筛选，低权重舍弃
        5. 有效引用不足 min_valid_refs 时，扩展搜索词继续搜索
        """
        cfg = load_yaml("configs/app.yaml")
        r = cfg["research"]
        topics_per_run = r.get("topics_per_run", 10)
        threshold = r.get("relevance_threshold", 2.0)

        topic_cfg = load_yaml("configs/topics.yaml")
        if topics is None:
            topics = topic_cfg.get("keywords", [])

        saved: list[dict] = []
        all_contents: list[CollectedContent] = []
        searched_keywords: set[str] = set()
        search_round = 0
        max_rounds = 5  # 最多扩展 5 轮搜索

        while len(saved) < min_valid_refs and search_round < max_rounds:
            search_round += 1
            new_topics = [t for t in topics if t not in searched_keywords]

            if not new_topics and search_round > 1:
                # 所有关键词都搜过了，用 LLM 生成扩展搜索词
                new_topics = await self._expand_keywords(topics, research_context, searched_keywords)
                if not new_topics:
                    console.print(f"    [{C_DIM}]无法生成更多搜索词，停止扩展[/{C_DIM}]")
                    break

            topics_to_search = new_topics[:topics_per_run]
            posts_per_topic = max(target_posts // max(len(topics_to_search), 1), 10)

            console.print(f"\n[{C_BRAND}]Round {search_round}[/{C_BRAND}]  [bold]{len(saved)}/{min_valid_refs}[/bold] saved  |  searching {len(topics_to_search)} keywords")

            round_contents: list[CollectedContent] = []

            for topic in topics_to_search:
                searched_keywords.add(topic)
                console.print(f"\n  [{C_BRAND}]search[/{C_BRAND}] [bold]{topic}[/bold]")

                try:
                    from app.integrations.x_api import search_tweets, sort_by_engagement

                    tweets = search_tweets(topic, max_results=posts_per_topic, sort_order="relevancy")
                    if not tweets:
                        console.print(f"    [{C_DIM}]no results[/{C_DIM}]")
                        continue

                    tweets = sort_by_engagement(tweets)
                    console.print(f"    [{C_DIM}]{len(tweets)} tweets found[/{C_DIM}]")

                    for tweet in tweets:
                        # 去重
                        if tweet.id in self._collected_ids:
                            continue
                        self._collected_ids.add(tweet.id)

                        content = await self._collect_tweet(tweet, topic, min_comments=min_comments, research_context=research_context)
                        if content:
                            round_contents.append(content)

                    await asyncio.sleep(random.uniform(2, 4))

                except Exception as e:
                    console.print(Text(f"    search failed: {e}", style=C_WARN))
                    continue

            if not round_contents:
                if search_round >= max_rounds:
                    break
                continue

            # 综合评分 + 筛选
            all_contents.extend(round_contents)
            console.print(f"\n  [{C_BRAND}]scoring[/{C_BRAND}] batch of {len(all_contents)}...")
            scored = score_batch(all_contents)

            # 筛选有效引用
            for content in scored:
                # 已经保存过的跳过
                if any(s.get("content_id") == content.content_id for s in saved):
                    continue

                if content.final_score < threshold:
                    save_reference(content.source_url, "x", source="api", was_collected=False)
                    continue

                # 摘要 + 标签（仅对通过筛选的帖子做，省 API 调用）
                if not content.summary:
                    content.summary = await summarize_content(content)
                if not content.tags:
                    content.tags = await extract_tags(content)

                # 保存
                save_content(content)
                md_path = save_content_to_md(content)

                score_style = C_ACCENT if content.final_score >= 3.5 else "bold"
                saved_line = Text()
                saved_line.append("  saved ", style=C_ACCENT)
                saved_line.append(f"@{content.author}  ", style="")
                saved_line.append(f"{content.final_score:.1f}  ", style=score_style)
                saved_line.append(content.body_text[:80], style="dim")
                console.print(saved_line)

                save_reference(
                    content.source_url, "x",
                    content_id=content.content_id,
                    title=f"@{content.author}: {content.body_text[:80]}",
                    was_collected=True,
                    source="api",
                )

                await sync_to_notion(content)
                self._total_collected += 1

                saved.append({
                    "content_id": content.content_id,
                    "author": content.author,
                    "text_preview": content.body_text[:80],
                    "topic": content.raw_metadata.get("topic", ""),
                    "likes": content.metrics.likes,
                    "views": content.metrics.views,
                    "reposts": content.metrics.reposts,
                    "replies": len(content.comments),
                    "engagement_score": content.engagement_score,
                    "final_score": content.final_score,
                    "relevance_score": content.relevance_score,
                })

            console.print(f"\n  [bold]{len(saved)}/{min_valid_refs}[/bold] refs")

        logger.info(f"API 调研完成: 采集 {len(all_contents)} 条，有效保存 {len(saved)} 条（{search_round} 轮搜索）")
        return saved

    # ── 扩展搜索词 ─────────────────────────────────────────────────

    async def _expand_keywords(self, original_topics: list[str], research_context: str, already_searched: set[str]) -> list[str]:
        """有效引用不足时，用 LLM 生成新的搜索关键词。"""
        from app.llm.client import chat
        from app.desktop.research_agent import _safe_extract_json

        searched_str = ", ".join(sorted(already_searched)[:20])
        prompt = (
            f"调研方向：{research_context}\n\n"
            f"已搜索过的关键词：{searched_str}\n\n"
            "已搜索的词都未能找到足够多的相关内容。请生成 5-8 个新的英文搜索关键词，"
            "从不同角度覆盖这个调研方向（如：子话题、竞品名、行业术语、趋势词）。\n"
            '返回 JSON 数组，只返回关键词字符串数组。'
        )
        raw = await chat(
            [{"role": "user", "content": prompt}],
            json_mode=True, temperature=0.6, max_tokens=300,
        )
        try:
            keywords = json.loads(_safe_extract_json(raw))
            if isinstance(keywords, list):
                new_kws = [str(k) for k in keywords if str(k) not in already_searched]
                if new_kws:
                    console.print(f"    [{C_DIM}]expanded: {', '.join(new_kws[:6])}[/{C_DIM}]")
                return new_kws
        except Exception:
            pass
        return []

    # ── 单帖采集（不筛选，不保存）────────────────────────────────────

    async def _collect_tweet(self, tweet, topic: str, min_comments: int = 10, research_context: str = "") -> CollectedContent | None:
        """采集单个帖子数据（正文+评论+相关性），不做筛选和保存。"""
        from app.integrations.x_api import fetch_tweet_replies, sort_comments

        author = tweet.author_username

        # 1. 构建 CollectedContent
        content_id = f"x:{author}:{tweet.id}"
        content = CollectedContent(
            content_id=content_id,
            platform="x",
            source_url=tweet.url,
            author=author,
            title="",
            body_text=tweet.text,
            external_links=self._extract_links(tweet.text),
            images=tweet.media if tweet.media else [],
            raw_metadata={"topic": topic},
        )
        content.metrics.likes = tweet.likes
        content.metrics.reposts = tweet.reposts
        content.metrics.replies = tweet.replies
        content.metrics.views = tweet.views

        if tweet.created_at:
            try:
                content.published_at = datetime.fromisoformat(tweet.created_at.replace("Z", "+00:00"))
            except Exception:
                pass

        # 2. 获取评论
        comments = fetch_tweet_replies(tweet.id, max_results=max(min_comments, 15))
        if comments:
            comments = sort_comments(comments)
            content.comments = [
                Comment(author=c.author_username, text=c.text, likes=c.likes, url=c.url)
                for c in comments[:min_comments]
            ]

        # 3. 计算互动分
        content.engagement_score = (
            content.metrics.likes
            + content.metrics.reposts * 1.5
            + len(content.comments) * 2
            + content.metrics.views * 0.01
        )

        # 4. LLM 相关性打分（按用户确认的调研方向）
        content.relevance_score = await score_relevance(content, research_context=research_context)

        # 两行输出
        _print_tweet_card(
            author, tweet.text,
            content.metrics.likes, len(content.comments),
            content.metrics.views, content.metrics.reposts,
            relevance=content.relevance_score,
            comments=len(content.comments),
        )

        return content

    # ── 辅助 ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_links(text: str) -> list[str]:
        """从推文文本中提取 URL。"""
        import re
        urls = re.findall(r'https?://[^\s]+', text)
        return urls
