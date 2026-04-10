"""X 调研 Agent — 纯 API 发现 + 视觉深度采集，按热度排序，实时保存。"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime

from app.core.config import load_yaml
from app.core.logger import logger
from app.desktop.computer_agent import ComputerAgent
from app.desktop.observer import observe_desktop
from app.llm.client import chat, vision_chat
from app.memory.sqlite_repo import save_content, save_reference, save_content_to_md
from app.schemas.content import CollectedContent, Comment
from rich.console import Console

console = Console()


class DesktopXResearcher:
    """X 调研 — API 搜索发现 + 视觉深度采集（正文/图片/评论/指标）。"""

    def __init__(self):
        self._collected_urls: set[str] = set()
        self.agent = ComputerAgent(max_cycles=20)
        self._total_collected = 0

    # ── 主流程 ────────────────────────────────────────────────────────

    async def discover(self, topics: list[str] | None = None, target_posts: int = 50, min_comments: int = 10) -> list[dict]:
        """API 优先调研流程。

        1. 用 X API 搜索每个主题，获取 50+ 帖子
        2. 按互动量排序
        3. 对每个帖子：视觉打开 → 提取正文/指标 → 获取评论(API) → 图片分析
        4. 每采集完一个帖子立即保存到 SQLite + 本地 MD + Notion
        """
        cfg = load_yaml("configs/app.yaml")
        r = cfg["research"]
        topics_per_run = r.get("topics_per_run", 10)

        topic_cfg = load_yaml("configs/topics.yaml")
        if topics is None:
            topics = topic_cfg.get("keywords", [])

        all_posts: list[dict] = []

        # 1. 打开浏览器
        console.print("[cyan]打开浏览器，导航到 x.com...[/cyan]")
        try:
            await self.agent.run(
                "Focus Safari with Cmd+Tab. If Safari isn't visible, use Cmd+Space to open it. Then Cmd+L to focus address bar, type x.com, press Enter. STOP once x.com is loaded.",
                context={"target_url": "x.com", "browser": "Safari"},
                plan_context={
                    "overall_goal": f"调研 {len(topics)} 个主题，目标 {target_posts} 个帖子",
                    "current_step": "Step 1: 打开浏览器导航到 x.com",
                    "completed_steps": [],
                    "next_steps": [
                        f"Step 2: API 搜索 {len(topics)} 个主题",
                        "Step 3: 逐个点开高热度帖子深度采集",
                        "Step 4: 实时保存到 MD + Notion",
                    ],
                },
            )
        except Exception as e:
            console.print(f"[yellow]导航到 X 时遇到问题: {e}[/yellow]")
            return []

        await self._focus_browser()

        # 2. 用 API 搜索 + 视觉深度采集
        posts_per_topic = max(target_posts // max(len(topics[:topics_per_run]), 1), 10)

        for topic in topics[:topics_per_run]:
            if self._total_collected >= target_posts:
                console.print(f"[dim]已达到目标 {target_posts} 个帖子，停止[/dim]")
                break

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

                # 逐个深度采集
                for tweet in tweets:
                    if self._total_collected >= target_posts:
                        break

                    post_data = await self._collect_and_save_tweet(
                        tweet, topic, min_comments=min_comments
                    )
                    if post_data:
                        all_posts.append(post_data)

                console.print(f"\n  [green]✓ {topic}: 已采集 {len([p for p in all_posts if p.get('topic') == topic])} 个帖子[/green]")
                await asyncio.sleep(random.uniform(2, 4))

            except Exception as e:
                console.print(f"    [yellow]搜索失败: {e}[/yellow]")
                continue

        logger.info(f"调研完成: 共采集 {self._total_collected} 个帖子")
        return all_posts

    # ── 单个帖子采集 + 实时保存 ──────────────────────────────────────

    async def _collect_and_save_tweet(self, tweet, topic: str, min_comments: int = 10) -> dict | None:
        """采集单个帖子（正文+评论+图片+指标），立即保存到 MD + Notion + SQLite。"""
        from app.integrations.x_api import fetch_tweet_replies, sort_comments

        author = tweet.author_username
        console.print(f"\n  [dim]▶ @{author} ❤{tweet.likes} 💬{tweet.replies} 👁{tweet.views}")
        console.print(f"    {tweet.text[:80]}...")

        # 1. 用视觉打开帖子并提取正文/指标/图片
        content = await self._collect_post_content(tweet)
        if not content:
            console.print(f"    [yellow]✗ 无法提取 @{author} 内容[/yellow]")
            return None

        # 2. 用 API 获取评论（10+ 条，按点赞量排序）
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
            # API 失败时回退到视觉评论
            content.comments = await self._read_comments()

        # 3. 相关性打分
        threshold = load_yaml("configs/app.yaml")["research"].get("relevance_threshold", 3.0)
        content.relevance_score = await self._score_relevance(content)
        if content.relevance_score < threshold:
            console.print(f"    [dim]  跳过 (相关性 {content.relevance_score:.1f} < {threshold})[/dim]")
            save_reference(content.source_url, "x", source="api", was_collected=False)
            return None

        # 4. 摘要 + 标签
        content.summary = await self._summarize(content)
        content.tags = await self._extract_tags(content)

        # 5. 计算综合权重
        content.engagement_score = (
            content.metrics.likes
            + content.metrics.reposts * 1.5
            + len(content.comments) * 2
            + content.metrics.views * 0.01
        )

        # ★ 实时保存
        save_content(content)
        md_path = save_content_to_md(content)
        console.print(
            f"    [green]✓ 已保存[/green] @{content.author} "
            f"| ❤{content.metrics.likes} 🔁{content.metrics.reposts} "
            f"| 💬{len(content.comments)} 👁{content.metrics.views} "
            f"| ⭐权重:{content.engagement_score:.0f} "
            f"| MD:{md_path.split('/')[-1]}"
        )

        save_reference(
            content.source_url, "x",
            content_id=content.content_id,
            title=f"@{content.author}: {content.body_text[:80]}",
            was_collected=True,
            source="api",
        )

        await self._sync_to_notion(content)
        self._total_collected += 1

        # 返回搜索结果
        try:
            await self._go_back()
        except Exception:
            pass
        await asyncio.sleep(random.uniform(1, 3))

        return {
            "author": author,
            "text_preview": tweet.text[:80],
            "topic": topic,
            "likes": content.metrics.likes,
            "views": content.metrics.views,
            "reposts": content.metrics.reposts,
            "replies": len(content.comments),
            "engagement_score": content.engagement_score,
        }

    async def _collect_post_content(self, tweet) -> CollectedContent | None:
        """用视觉打开帖子，提取正文和指标。"""
        author = tweet.author_username

        try:
            await self.agent.run(
                f"Use Cmd+L to focus address bar, then type or paste this URL and press Enter: {tweet.url}",
                context={"tweet_url": tweet.url, "author": author},
                plan_context={
                    "overall_goal": f"采集高热度帖子 (API 发现)",
                    "current_step": f"导航到 @{author} 的帖子",
                    "completed_steps": [f"API 搜索到 {author} 的帖子 (❤{tweet.likes} 💬{tweet.replies})"],
                    "next_steps": ["提取正文和指标", "获取评论", "保存"],
                },
                max_cycles=8,
            )
        except Exception as e:
            logger.warning(f"导航到 @{author} 失败: {e}")
            return None

        await asyncio.sleep(2)

        # 提取帖子内容
        obs = await observe_desktop("提取帖子内容")
        post_data = await self._extract_post_content(obs.screenshot_path, author)
        if not post_data:
            await self.agent.run("Scroll down slightly to see more content.", max_cycles=2)
            await asyncio.sleep(1)
            obs = await observe_desktop("重新提取帖子内容")
            post_data = await self._extract_post_content(obs.screenshot_path, author)

        if not post_data:
            return None

        source_url = tweet.url
        content_id = f"x:{author}:{tweet.id}"

        content = CollectedContent(
            content_id=content_id,
            platform="x",
            source_url=source_url,
            author=author,
            title=post_data.get("title", ""),
            body_text=post_data.get("body_text", tweet.text),
            external_links=post_data.get("external_links", []),
            images=[],
        )
        content.metrics.likes = post_data.get("likes", tweet.likes) or tweet.likes
        content.metrics.reposts = post_data.get("reposts", tweet.reposts) or tweet.reposts
        content.metrics.replies = post_data.get("replies", tweet.replies) or tweet.replies
        content.metrics.views = post_data.get("views", tweet.views) or tweet.views
        content.metrics.bookmarks = post_data.get("bookmarks", 0) or 0

        console.print(
            f"      [dim]正文: {len(content.body_text)} 字 | "
            f"❤{content.metrics.likes} 🔁{content.metrics.reposts} "
            f"💬{content.metrics.replies} 👁{content.metrics.views}[/dim]"
        )

        # 图片分析
        if post_data.get("has_image") and post_data.get("images"):
            console.print(f"      [cyan]分析 {len(post_data['images'])} 张图片...[/cyan]")
            await self._analyze_images(content, post_data["images"])

        return content

    # ── 视觉精读高权重帖子 ──────────────────────────────────────────

    async def deep_read_posts(self, posts: list[dict]) -> list[dict]:
        """API 调研后，用视觉精读高权重帖子，提取图片/视频/完整正文。

        posts: _research_async 返回的帖子摘要列表，含 source_url / content_id
        返回: 更新后的帖子列表
        """
        if not posts:
            return posts

        console.print(f"\n[bold cyan]🔍 视觉精读 Top {len(posts)} 高权重帖子...[/bold cyan]")

        # 先打开浏览器
        console.print("[dim]打开浏览器...[/dim]")
        try:
            await self.agent.run(
                "Focus Safari with Cmd+Tab. If Safari isn't visible, use Cmd+Space to open it. Then Cmd+L to focus address bar, type x.com, press Enter. STOP once x.com is loaded.",
                context={"target_url": "x.com", "browser": "Safari"},
                plan_context={
                    "overall_goal": f"视觉精读 {len(posts)} 个高权重帖子",
                    "current_step": "打开浏览器",
                    "completed_steps": [],
                    "next_steps": ["逐个打开帖子", "提取图片/视频信息"],
                },
            )
        except Exception as e:
            console.print(f"[yellow]浏览器打开失败: {e}[/yellow]")
            return posts

        await self._focus_browser()

        from app.memory.sqlite_repo import save_content, save_content_to_md

        updated = []
        for i, post in enumerate(posts, 1):
            url = post.get("source_url", "")
            content_id = post.get("content_id", "")

            if not url:
                continue

            console.print(f"\n  [{BRAND}]精读 {i}/{len(posts)}[/] @{post.get('author', '')} ⭐{post.get('final_score', 0):.1f}")

            # 导航到帖子
            try:
                await self.agent.run(
                    f"Use Cmd+L to focus address bar, then type or paste this URL and press Enter: {url}",
                    context={"tweet_url": url},
                    plan_context={
                        "overall_goal": f"视觉精读帖子 ({i}/{len(posts)})",
                        "current_step": f"导航到帖子",
                        "completed_steps": [],
                        "next_steps": ["提取图片和视频信息"],
                    },
                    max_cycles=6,
                )
            except Exception as e:
                console.print(f"    [yellow]导航失败: {e}[/yellow]")
                continue

            await asyncio.sleep(2)

            # 截图记录
            obs = await observe_desktop(f"精读帖子 {i}")

            # 视觉提取完整信息
            post_data = await self._extract_post_content(obs.screenshot_path, post.get("author", ""))

            # 从数据库加载已有 content 并更新
            from app.memory.sqlite_repo import load_collected_content_by_id
            content = load_collected_content_by_id(content_id) if content_id else None

            if content:
                # 更新图片信息
                if post_data and post_data.get("has_image") and post_data.get("images"):
                    console.print(f"    [cyan]📸 分析 {len(post_data['images'])} 张图片...[/cyan]")
                    content.images = []  # 重新填充
                    await self._analyze_images(content, post_data["images"])

                # 更新截图
                content.screenshots.append(obs.screenshot_path)

                # 视觉补充正文（如果 API 文本被截断）
                if post_data and post_data.get("body_text") and len(post_data["body_text"]) > len(content.body_text):
                    content.body_text = post_data["body_text"]
                    console.print(f"    [dim]正文已更新: {len(content.body_text)} 字[/dim]")

                # 检测视频
                if post_data and post_data.get("has_video"):
                    content.images.append("[视频] 帖子包含视频内容")
                    console.print(f"    [cyan]🎬 检测到视频内容[/cyan]")

                # 保存更新
                save_content(content)
                save_content_to_md(content)
                await sync_to_notion(content)
                console.print(f"    [green]✓ 已更新图片/视频信息[/green]")

            post["deep_read"] = True
            updated.append(post)

            # 返回
            try:
                await self._go_back()
            except Exception:
                pass
            await asyncio.sleep(random.uniform(1, 2))

        logger.info(f"视觉精读完成: {len(updated)} 个帖子")
        return updated

    # ── 视觉辅助方法 ──────────────────────────────────────────────────

    async def _go_back(self) -> None:
        from app.desktop.executor import execute_desktop
        from app.schemas.action import ActionType, PlannedAction
        try:
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["command", "["],
                reason="返回"
            ))
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"返回失败: {e}")

    async def _focus_browser(self) -> None:
        from app.desktop.executor import execute_desktop
        from app.schemas.action import ActionType, PlannedAction

        console.print(f"      [dim]聚焦浏览器窗口...[/dim]")
        try:
            obs = await observe_desktop("定位浏览器窗口")
            raw = await vision_chat(
                text_prompt=(
                    "这是当前桌面截图。请识别浏览器（Safari）窗口的位置。\n"
                    '返回 JSON: {"browser_x": 500, "browser_y": 130, "focused": true/false}\n'
                    "坐标归一化 1000x1000。\n只返回 JSON。"
                ),
                image_path=obs.screenshot_path,
                max_tokens=200,
            )
            try:
                data = _safe_extract_json(raw)
                import json
                data = json.loads(data)
                if isinstance(data, dict) and data.get("browser_x"):
                    await execute_desktop(PlannedAction(
                        action=ActionType.CLICK_AT,
                        x=int(data["browser_x"]),
                        y=int(data["browser_y"]),
                        reason="聚焦浏览器窗口"
                    ))
                    await asyncio.sleep(0.5)
            except Exception:
                await execute_desktop(PlannedAction(
                    action=ActionType.CLICK_AT, x=500, y=150,
                    reason="聚焦浏览器（兜底）"
                ))
        except Exception as e:
            logger.debug(f"浏览器聚焦失败: {e}")

    async def _read_comments(self) -> list[Comment]:
        """视觉识别评论（API 失败时回退）。"""
        comments: list[Comment] = []
        try:
            await self.agent.run(
                "Scroll down to see the comments/replies section.",
                max_cycles=3,
            )
        except Exception:
            pass

        for _ in range(3):
            obs = await observe_desktop("识别评论区")
            raw = await vision_chat(
                text_prompt=(
                    "这是 X 帖子的评论区截图。\n"
                    "识别每条可见评论：\n"
                    "  - author: 用户名\n"
                    "  - text: 评论正文（前100字）\n"
                    "  - likes: 点赞数\n"
                    "返回 JSON 数组，最多5条。\n只返回 JSON 数组。"
                ),
                image_path=obs.screenshot_path,
                max_tokens=1024,
            )
            try:
                data = _safe_parse_json_array(raw)
                if isinstance(data, list):
                    for c in data:
                        if c.get("author") or c.get("text"):
                            comments.append(Comment(
                                author=c.get("author", "unknown"),
                                text=c.get("text", ""),
                                likes=int(c.get("likes", 0) or 0),
                            ))
            except Exception:
                pass

            try:
                await self.agent.run("Scroll down to see more comments.", max_cycles=2)
            except Exception:
                break
            await asyncio.sleep(1)

        return sorted(comments, key=lambda c: c.likes, reverse=True)[:15]

    async def _analyze_images(self, content: CollectedContent, image_descs: list[str]) -> None:
        for i, desc in enumerate(image_descs[:3]):
            if i == 0:
                try:
                    await self.agent.run("Click on the image to view full-size.", max_cycles=3)
                except Exception:
                    pass
                await asyncio.sleep(1)

            obs = await observe_desktop(f"分析图片 {i+1}")
            raw = await vision_chat(
                text_prompt=(
                    "这是 X 帖子中的图片。请：\n"
                    "1. 详细描述图片内容（中文）\n"
                    "2. 如果是数据图表，提取关键数据\n"
                    "3. 给出调研价值（1-5分）\n"
                    '返回: {"description":"...","insights":["..."],"value":1-5}\n'
                    "如果没有图片，返回 null。"
                ),
                image_path=obs.screenshot_path,
                max_tokens=1024,
            )
            try:
                import json
                data = json.loads(_safe_extract_json(raw))
                if isinstance(data, dict) and data.get("description"):
                    content.images.append(f"[图片{i+1}] {desc} | {data['description'][:200]}")
                    if data.get("insights"):
                        content.images.append(f"[洞察] {'; '.join(data['insights'])}")
                    console.print(f"      [green]图片: {data['description'][:60]}...[/green]")
                try:
                    await self.agent.run("Press Escape to return to post.", max_cycles=2)
                except Exception:
                    pass
                await asyncio.sleep(1)
            except Exception:
                pass

    async def _extract_post_content(self, screenshot_path: str, author: str) -> dict | None:
        extract = await vision_chat(
            text_prompt=(
                "这是一个 X (Twitter) 帖子的详情页截图。\n"
                "仔细阅读所有文字，提取:\n"
                '{\n'
                '  "author": "用户名(不含@)",\n'
                '  "title": "帖子第一行或标题（没有则空）",\n'
                '  "body_text": "帖子完整正文",\n'
                '  "external_links": ["外链URL，没有则[]"],\n'
                '  "images": ["图片描述"],\n'
                '  "has_image": true或false,\n'
                '  "likes": 数字,\n'
                '  "reposts": 数字,\n'
                '  "replies": 数字,\n'
                '  "views": 数字,\n'
                '  "published_at": "发布时间"\n'
                '}\n'
                "如果页面不是帖子详情页，返回 null。\n只返回 JSON。"
            ),
            image_path=screenshot_path,
            max_tokens=1024,
        )
        logger.info(f"帖子内容: {extract[:300]}")
        try:
            data = json.loads(_safe_extract_json(extract))
            return data if data else None
        except Exception:
            return None

    # ── LLM 辅助（委托给模块级函数）───────────────────────────────────

    async def _score_relevance(self, c: CollectedContent, research_context: str = "") -> float:
        return await score_relevance(c, research_context)

    async def _summarize(self, c: CollectedContent) -> str:
        return await summarize_content(c)

    async def _extract_tags(self, c: CollectedContent) -> list[str]:
        return await extract_tags(c)

    async def _sync_to_notion(self, content: CollectedContent) -> None:
        await sync_to_notion(content)


# ── 公共 LLM 辅助函数（供 APIXResearcher 复用）────────────────────

async def score_relevance(c: CollectedContent, research_context: str = "") -> float:
    """根据用户确认的调研方向对帖子做相关性打分。"""
    context_part = ""
    if research_context:
        context_part = f"用户的具体调研方向：\n{research_context}\n\n"
    prompt = (
        f"{context_part}"
        "对这条帖子与上述调研方向的相关性打 1-5 分。\n"
        "5=高度相关（直接讨论该方向的核心理念/产品/趋势），\n"
        "3=间接相关（涉及相关领域但未直击要点），\n"
        "1=不相关。\n\n"
        f"@{c.author} ({c.metrics.likes} 赞):\n{c.body_text[:600]}\n\n"
        '只返回 JSON: {"score": 1-5, "reason": "简短原因"}'
    )
    raw = await chat(
        [{"role": "user", "content": prompt}],
        json_mode=True, temperature=0.2,
    )
    try:
        return float(json.loads(_safe_extract_json(raw)).get("score", 3.0))
    except Exception:
        return 3.0


async def summarize_content(c: CollectedContent) -> str:
    comment_summary = ""
    if c.comments:
        comment_summary = f"\n热门评论 ({len(c.comments)}条):\n"
        for cm in c.comments[:3]:
            comment_summary += f"  - @{cm.author}: {cm.text[:100]}\n"

    prompt = (
        f"用 2-3 句话总结这条帖子，关注核心洞察。\n"
        f"同时考虑评论中的高价值观点。\n\n"
        f"@{c.author} ({c.metrics.likes} 赞):\n{c.body_text[:800]}\n"
        f"{comment_summary}\n"
        "总结:"
    )
    return (await chat([{"role": "user", "content": prompt}], max_tokens=300, temperature=0.3)).strip()


async def extract_tags(c: CollectedContent) -> list[str]:
    prompt = (
        f"提取 3-5 个主题标签，返回 JSON 数组。\n"
        f"帖子: {c.body_text[:400]}\n标签:"
    )
    raw = await chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=60)
    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception:
        pass
    return []


async def sync_to_notion(content: CollectedContent) -> None:
    try:
        from app.integrations.notion_client import save_research
        page_id = await save_research(content)
        if page_id:
            content.notion_page_id = page_id
            save_content(content)
            console.print(f"    [green]✓ Notion 已同步[/green]")
        else:
            console.print(f"    [dim]Notion 未配置（跳过）[/dim]")
    except Exception as e:
        console.print(f"    [yellow]Notion 失败: {e}[/yellow]")


# ── JSON 提取 ─────────────────────────────────────────────────────

import json


def _safe_extract_json(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0] if "```" in text else text.split("```json", 1)[1]
    elif text.startswith("```"):
        text = text.split("```", 1)[1]
        parts = text.rsplit("```", 1)
        text = parts[0] if len(parts) > 1 else text
    text = text.strip()
    if not text:
        return ""
    first_obj = text.find("{")
    first_arr = text.find("[")
    if first_obj == -1 and first_arr == -1:
        return "null" if "null" in text.lower() else text
    start = first_arr if (first_arr != -1 and (first_obj == -1 or first_arr < first_obj)) else first_obj
    bracket = "[" if start == first_arr else "{"
    close = "]" if bracket == "[" else "}"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == bracket:
            depth += 1
        elif ch == close:
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    end = text.rfind(close) + 1
    return text[start:end] if end > 0 else text


def _safe_parse_json_array(text: str) -> list | dict:
    raw = _safe_extract_json(text)
    return json.loads(raw) if raw else []
