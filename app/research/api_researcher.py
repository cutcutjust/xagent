"""X 纯 API 调研器 — 无需浏览器/桌面权限，直接从 X API 获取所有数据。"""
from __future__ import annotations

import asyncio
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

console = Console()


class APIXResearcher:
    """X 调研 — 纯 API，无需 DesktopAgent / 浏览器 / macOS 权限。"""

    def __init__(self):
        self._collected_ids: set[str] = set()
        self._total_collected = 0

    # ── 主流程 ────────────────────────────────────────────────────────

    async def discover(self, topics: list[str] | None = None, target_posts: int = 50, min_comments: int = 10) -> list[dict]:
        """纯 API 调研流程。

        1. 用 X API 搜索每个主题
        2. 按互动量排序
        3. 逐帖采集：API 正文/评论 → LLM 相关性打分/摘要
        4. 全部采集后综合评分（相关性 + 互动 + 时效），筛选保存
        """
        cfg = load_yaml("configs/app.yaml")
        r = cfg["research"]
        topics_per_run = r.get("topics_per_run", 10)

        topic_cfg = load_yaml("configs/topics.yaml")
        if topics is None:
            topics = topic_cfg.get("keywords", [])

        # Phase 1: 采集所有帖子（不做筛选）
        all_contents: list[CollectedContent] = []
        posts_per_topic = max(target_posts // max(len(topics[:topics_per_run]), 1), 10)

        for topic in topics[:topics_per_run]:
            console.print(f"\n[cyan]{'='*50}[/cyan]")
            console.print(f"[bold cyan]📡 API 搜索: {topic}[/bold cyan] (目标 {posts_per_topic} 帖)")
            console.print(f"[cyan]{'='*50}[/cyan]")

            try:
                from app.integrations.x_api import search_tweets, sort_by_engagement

                tweets = search_tweets(topic, max_results=posts_per_topic, sort_order="relevancy")
                if not tweets:
                    console.print(f"    [yellow]API 未返回结果[/yellow]")
                    continue

                tweets = sort_by_engagement(tweets)
                console.print(f"    [dim]API 返回 {len(tweets)} 条，按互动量排序[/dim]")

                for tweet in tweets:
                    if len(all_contents) >= target_posts:
                        break

                    # 去重
                    if tweet.id in self._collected_ids:
                        continue
                    self._collected_ids.add(tweet.id)

                    content = await self._collect_tweet(tweet, topic, min_comments=min_comments)
                    if content:
                        all_contents.append(content)

                console.print(f"\n  [green]✓ {topic}: 已采集 {len([c for c in all_contents if 'topic' not in c.raw_metadata or c.raw_metadata.get('topic') == topic])} 条[/green]")
                await asyncio.sleep(random.uniform(2, 4))

            except Exception as e:
                console.print(f"    [yellow]搜索失败: {e}[/yellow]")
                continue

        if not all_contents:
            logger.info("API 调研完成: 未采集到帖子")
            return []

        # Phase 2: 综合评分 + 筛选 + 保存
        console.print(f"\n[bold]📊 综合评分（相关性×0.3 + 互动×0.4 + 时效×0.3）...[/bold]")
        scored = score_batch(all_contents)

        threshold = cfg["research"].get("relevance_threshold", 2.0)
        saved: list[dict] = []

        for content in scored:
            if content.final_score < threshold:
                console.print(
                    f"  [dim]跳过 @{content.author} "
                    f"(综合 {content.final_score:.1f} < {threshold})[/dim]"
                )
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
            console.print(
                f"  [green]✓[/green] @{content.author} "
                f"| ❤{content.metrics.likes} 🔁{content.metrics.reposts} "
                f"| 💬{len(content.comments)} 👁{content.metrics.views} "
                f"| ⭐{content.final_score:.1f} "
                f"| MD:{md_path.split('/')[-1]}"
            )

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

        logger.info(f"API 调研完成: 采集 {len(all_contents)} 条，保存 {self._total_collected} 条")
        return saved

    # ── 单帖采集（不筛选，不保存）────────────────────────────────────

    async def _collect_tweet(self, tweet, topic: str, min_comments: int = 10) -> CollectedContent | None:
        """采集单个帖子数据（正文+评论+相关性），不做筛选和保存。"""
        from app.integrations.x_api import fetch_tweet_replies, sort_comments

        author = tweet.author_username
        console.print(f"\n  [dim]▶ @{author} ❤{tweet.likes} 💬{tweet.replies} 👁{tweet.views}")
        console.print(f"    {tweet.text[:80]}...")

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
        console.print(f"    [cyan]📥 获取评论...[/cyan]")
        comments = fetch_tweet_replies(tweet.id, max_results=max(min_comments, 15))
        if comments:
            comments = sort_comments(comments)
            content.comments = [
                Comment(author=c.author_username, text=c.text, likes=c.likes, url=c.url)
                for c in comments[:min_comments]
            ]
            console.print(f"    [dim]  获取到 {len(comments)} 条评论，取 Top {min_comments}[/dim]")
        else:
            console.print(f"    [dim]  无评论[/dim]")

        # 3. 计算互动分
        content.engagement_score = (
            content.metrics.likes
            + content.metrics.reposts * 1.5
            + len(content.comments) * 2
            + content.metrics.views * 0.01
        )

        # 4. LLM 相关性打分
        content.relevance_score = await score_relevance(content)
        console.print(
            f"    [dim]相关性 {content.relevance_score:.1f} | "
            f"❤{content.metrics.likes} 🔁{content.metrics.reposts} "
            f"💬{len(content.comments)} 👁{content.metrics.views}[/dim]"
        )

        return content

    # ── 辅助 ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_links(text: str) -> list[str]:
        """从推文文本中提取 URL。"""
        import re
        urls = re.findall(r'https?://[^\s]+', text)
        return urls
