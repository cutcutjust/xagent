"""桌面级 X 调研 Agent — 纯视觉闭环：ComputerAgent 控制一切。"""
from __future__ import annotations

import asyncio
import json
import random

from app.core.config import load_yaml
from app.core.logger import logger
from app.desktop.computer_agent import ComputerAgent
from app.desktop.observer import observe_desktop
from app.llm.client import chat, vision_chat
from app.memory.sqlite_repo import save_content, save_reference
from app.schemas.content import CollectedContent, Comment
from rich.console import Console

console = Console()


class DesktopXResearcher:
    """全屏视觉调研 X — 深度采集：看帖子、点图片、读评论。"""

    def __init__(self):
        self._collected_urls: set[str] = set()
        self.agent = ComputerAgent(max_cycles=20)

    # ── 主流程 ────────────────────────────────────────────────────────

    async def discover(self, topics: list[str] | None = None) -> list[dict]:
        """搜索 X 并返回帖子来源列表。"""
        cfg = load_yaml("configs/app.yaml")
        r = cfg["research"]
        topics_per_run = r.get("topics_per_run", 10)
        posts_per_topic = r.get("posts_per_topic", 30)

        topic_cfg = load_yaml("configs/topics.yaml")
        if topics is None:
            topics = topic_cfg.get("keywords", [])

        all_posts: list[dict] = []

        # 1. 打开浏览器并导航到 X
        console.print("[cyan]打开浏览器，导航到 x.com...[/cyan]")
        try:
            await self.agent.run(
                "Focus Safari with Cmd+Tab. If Safari isn't visible, use Cmd+Space to open it. Then Cmd+L to focus address bar, type x.com, press Enter.",
                context={"target_url": "x.com", "browser": "Safari"},
                plan_context={
                    "overall_goal": f"调研 {len(topics)} 个主题的相关帖子",
                    "current_step": "Step 1/4: 打开浏览器导航到 x.com",
                    "completed_steps": [],
                    "next_steps": [
                        f"Step 2: 搜索主题 ({', '.join(topics[:3])}{'...' if len(topics) > 3 else ''})",
                        "Step 3: 逐一点开帖子 → 正文/图片/评论/指标",
                        "Step 4: Notion 同步保存",
                    ],
                },
            )
        except Exception as e:
            console.print(f"[yellow]导航到 X 时遇到问题: {e}[/yellow]")
            return []

        # 2. 搜索每个主题
        for topic in topics[:topics_per_run]:
            console.print(f"[cyan]搜索: {topic}[/cyan]")

            # 用 ComputerAgent 执行搜索
            try:
                await self.agent.run(
                    f"On X (Twitter), find the search box, type '{topic}', press Enter, and wait for search results to load.",
                    context={"search_query": topic},
                    plan_context={
                        "overall_goal": f"调研 {len(topics)} 个主题的相关帖子",
                        "current_step": f"Step 2/4: 搜索 '{topic}'",
                        "completed_steps": ["Step 1: 打开浏览器导航到 x.com ✓"],
                        "next_steps": [
                            f"Step 3: 搜索 '{topic}' 的结果中逐一点开帖子深度采集",
                            "Step 4: Notion 同步保存",
                        ],
                    },
                )
            except Exception as e:
                console.print(f"    [yellow]搜索失败: {e}[/yellow]")
                continue

            # 深度滚动并提取帖子
            batch = await self._scroll_and_extract_posts(topic, max_posts=posts_per_topic)
            all_posts.extend(batch)
            console.print(f"  [dim]找到 {len(batch)} 个帖子来源[/dim]")
            await asyncio.sleep(random.uniform(1, 3))

        # 去重
        seen = set()
        unique = []
        for p in all_posts:
            key = f"{p.get('author', '')}:{p.get('text_preview', '')[:30]}"
            if key not in seen:
                seen.add(key)
                unique.append(p)

        logger.info(f"发现 {len(unique)} 个唯一帖子")
        return unique

    async def collect(self, post_info: dict) -> CollectedContent | None:
        """深度采集单个帖子 — 正文、图片、评论全部打开看。"""
        return await self._deep_collect(post_info, topic="")

    # ── 滚动提取帖子 ──────────────────────────────────────────────────

    async def _scroll_and_extract_posts(self, topic: str, max_posts: int = 20) -> list[dict]:
        """边滚动边深度采集：每看到一个帖子就点进去完整分析（正文、图片、评论、指标），然后返回继续。"""
        console.print("[cyan]深度调研开始 — 逐一点开分析...[/cyan]")
        posts_found: list[dict] = []
        posts_deep: set[str] = set()  # track deep-collected posts
        no_new_rounds = 0

        for round_num in range(12):
            # 用视觉模型识别当前屏幕上的帖子
            obs = await observe_desktop(f"识别屏幕上的 X 帖子")
            try:
                raw = await vision_chat(
                    text_prompt=(
                        "这是 X 搜索结果页面的截图。\n"
                        "识别每条可见帖子的：\n"
                        "  - author: 用户名（不含@）\n"
                        "  - text_preview: 正文前80字\n"
                        "  - likes: 点赞数（如果可见）\n"
                        "  - views: 阅读数（如果可见）\n"
                        "  - replies: 评论数（如果可见）\n"
                        "  - has_image: 是否包含图片\n"
                        "  - post_url: 帖子URL（如果能看到）\n"
                        "返回 JSON 数组，最多10条（当前屏幕可见的）。\n"
                        "如果看不到帖子，返回 []。\n"
                        "只返回 JSON 数组，不要任何其他文字。"
                    ),
                    image_path=obs.screenshot_path,
                    max_tokens=1024,
                )
            except Exception as e:
                logger.warning(f"vision_chat 调用失败: {e}")
                await asyncio.sleep(3)
                continue

            try:
                data = _safe_parse_json_array(raw)
                if isinstance(data, dict) and "posts" in data:
                    data = data["posts"]
                if not isinstance(data, list):
                    data = []
            except Exception as e:
                logger.warning(f"帖子识别失败: {e}")
                data = []

            # 对当前屏幕可见的每个帖子，逐一点开深度采集
            new_posts = [p for p in data if p.get("author")]
            for p in new_posts:
                if len(posts_found) >= max_posts:
                    break
                key = f"{p['author']}:{p.get('text_preview', '')[:40]}"
                if key in posts_deep:
                    continue
                posts_deep.add(key)
                posts_found.append(p)
                console.print(f"    [dim]发现: @{p['author']} — {p.get('text_preview', '')[:50]}[/dim]")

                # ★ 深度采集这个帖子
                p["topic"] = topic
                try:
                    result = await self._deep_collect_from_search(p)
                    if result:
                        console.print(
                            f"    [green]✓ @{p['author']} 已保存 "
                            f"❤{result.metrics.likes} 🔁{result.metrics.reposts} "
                            f"💬{len(result.comments)} 👁{result.metrics.views} "
                            f"🖼{len(result.images)}[/green]"
                        )
                except Exception as e:
                    logger.warning(f"深度采集 @{p['author']} 失败: {e}")
                    # 确保回到搜索结果
                    await self._go_back()

                await asyncio.sleep(random.uniform(1, 2))

            if len(posts_found) >= max_posts:
                break

            # 滚动加载更多
            if len(new_posts) == 0:
                no_new_rounds += 1
                if no_new_rounds >= 3:
                    console.print(f"    [yellow]连续 {no_new_rounds} 轮无新帖子[/yellow]")
                    break
            else:
                no_new_rounds = 0

            try:
                await self.agent.run(
                    "Scroll down the X search results page to load more posts. Use Space or PageDown.",
                    max_cycles=3,
                )
            except Exception:
                from app.desktop.executor import execute_desktop
                from app.schemas.action import ActionType, PlannedAction
                await execute_desktop(PlannedAction(
                    action=ActionType.HOTKEY, keys=["space"],
                    reason=f"翻页加载 (第 {round_num + 1} 轮)"
                ))

            await asyncio.sleep(2)

        console.print(f"  [dim]共发现 {len(posts_found)} 个帖子，已深度采集[/dim]")
        return posts_found[:max_posts]

    async def _deep_collect_from_search(self, post_info: dict) -> CollectedContent | None:
        """从搜索结果页点进帖子，深度采集正文、图片、评论、指标，然后返回。"""
        author = post_info.get("author", "")
        preview = post_info.get("text_preview", "")
        topic = post_info.get("topic", "")
        threshold = load_yaml("configs/app.yaml")["research"].get("relevance_threshold", 3.0)

        # Step 1: 聚焦浏览器窗口
        await self._focus_browser()

        # Step 2: 点击帖子
        try:
            await self.agent.run(
                f"Click on the visible post by @{author} to open its detail page.",
                context={"target_author": author, "text_preview": preview[:40]},
                plan_context={
                    "overall_goal": "深度采集帖子内容",
                    "current_step": f"点开 @{author} 的帖子",
                    "completed_steps": ["聚焦浏览器窗口 ✓"],
                    "next_steps": [
                        "提取帖子正文和指标",
                        "复制帖子链接",
                        "分析图片（如有）",
                        "读取评论",
                        "相关性打分 → 保存 → Notion 同步",
                    ],
                },
            )
        except Exception:
            console.print(f"    [yellow]点击 @{author} 帖子失败[/yellow]")
            return None

        await asyncio.sleep(2)

        # Step 3: 提取帖子内容
        obs = await observe_desktop(f"提取帖子内容")
        post_data = await self._extract_post_content(obs.screenshot_path, author)
        if not post_data:
            console.print(f"    [yellow]无法提取 @{author} 内容，滚动再试[/yellow]")
            try:
                await self.agent.run(
                    "Scroll down slightly to see more of the post content.",
                    max_cycles=2,
                    plan_context={
                        "overall_goal": "深度采集帖子内容",
                        "current_step": "滚动查找帖子正文",
                        "completed_steps": ["聚焦浏览器 ✓", "点击帖子 ✓"],
                        "next_steps": ["提取帖子内容", "复制链接", "分析图片", "读取评论", "保存"],
                    },
                )
            except Exception:
                pass
            await asyncio.sleep(1)
            obs = await observe_desktop(f"重新提取帖子内容")
            post_data = await self._extract_post_content(obs.screenshot_path, author)

        if not post_data:
            console.print(f"    [yellow]仍无法提取，跳过 @{author}[/yellow]")
            await self._go_back()
            return None

        content_id = f"x:{author}:{preview[:40]}"
        source_url = post_data.get("source_url", f"https://x.com/{author}")

        # Step 4: 通过分享按钮获取帖子链接
        console.print(f"      [cyan]复制帖子链接...[/cyan]")
        post_url = await self._copy_post_url()
        if post_url:
            source_url = post_url
        else:
            # 兜底：从地址栏复制
            source_url = await self._copy_url_from_address_bar() or source_url

        content = CollectedContent(
            content_id=content_id,
            platform="x",
            source_url=source_url,
            author=author,
            title=post_data.get("title", ""),
            body_text=post_data.get("body_text", preview),
            external_links=post_data.get("external_links", []),
            images=[],
        )
        content.metrics.likes = post_data.get("likes", 0) or 0
        content.metrics.reposts = post_data.get("reposts", 0) or 0
        content.metrics.replies = post_data.get("replies", 0) or 0
        content.metrics.views = post_data.get("views", 0) or 0
        content.metrics.bookmarks = post_data.get("bookmarks", 0) or 0

        console.print(
            f"      [dim]正文: {len(content.body_text)} 字 | "
            f"❤{content.metrics.likes} 🔁{content.metrics.reposts} "
            f"💬{content.metrics.replies} 👁{content.metrics.views}[/dim]"
        )

        # Step 5: 图片分析
        if post_data.get("has_image") and post_data.get("images"):
            console.print(f"      [cyan]检测到 {len(post_data['images'])} 张图片，分析...[/cyan]")
            await self._analyze_images(content, post_data["images"])

        # Step 6: 读取评论
        console.print(f"      [cyan]读取评论...[/cyan]")
        content.comments = await self._read_comments()

        # Step 7: 如果指标缺失，滚动查找
        if not content.metrics.likes and not content.metrics.views:
            console.print(f"      [cyan]指标不可见，滚动查找...[/cyan]")
            await self._find_metrics(content)

        # Step 6: 相关性打分
        score = await self._score_relevance(content)
        content.relevance_score = score
        if score < threshold:
            console.print(f"      [dim]跳过 (score={score:.1f})[/dim]")
            save_reference(content.source_url, "x", source="search", was_collected=False)
            await self._go_back()
            return None

        # Step 7: 摘要 + 标签
        content.summary = await self._summarize(content)
        content.tags = await self._extract_tags(content)

        # ★ 保存
        save_content(content)

        save_reference(
            content.source_url, "x",
            content_id=content.content_id,
            title=f"@{content.author}: {content.body_text[:80]}",
            was_collected=True,
            source="search",
        )

        # 同步 Notion
        await self._sync_to_notion(content)

        # 返回搜索结果
        await self._go_back()
        return content

    # ── 深度采集帖子详情 ──────────────────────────────────────────────

    async def _deep_collect(self, post_info: dict, topic: str) -> CollectedContent | None:
        """深度采集：正文、图片、评论、互动指标，像人一样探索。"""
        author = post_info.get("author", "")
        preview = post_info.get("text_preview", "")
        threshold = load_yaml("configs/app.yaml")["research"].get("relevance_threshold", 3.0)

        console.print(f"    [cyan]深度采集 @{author}...[/cyan]")

        # Step 1: 点开帖子
        try:
            await self.agent.run(
                f"On the X search results page, find and click the post by @{author} to open its detail page.",
                context={"target_author": author},
                plan_context={
                    "overall_goal": f"调研 {topic} 相关帖子",
                    "current_step": f"点开 @{author} 的帖子深度采集",
                    "completed_steps": ["导航到 X ✓", "搜索 ✓", "滚动识别帖子 ✓"],
                    "next_steps": [
                        "提取帖子正文和指标",
                        "分析图片（如有）",
                        "读取评论",
                        "相关性打分 → 保存 → Notion 同步",
                    ],
                },
            )
        except Exception:
            console.print(f"    [yellow]定位帖子失败，跳过[/yellow]")
            return None

        await asyncio.sleep(2)

        # Step 2: 提取帖子内容
        obs = await observe_desktop(f"提取帖子内容")
        post_data = await self._extract_post_content(obs.screenshot_path, author)
        if not post_data:
            console.print(f"    [yellow]无法提取帖子内容，滚动再试[/yellow]")
            # 帖子可能不在屏幕中间，先滚动
            try:
                await self.agent.run(
                    "Scroll down slightly to center the post content.",
                    max_cycles=2,
                    plan_context={
                        "overall_goal": "深度采集帖子内容",
                        "current_step": "滚动查找帖子正文",
                        "completed_steps": ["点击帖子 ✓"],
                        "next_steps": ["提取帖子内容", "分析图片", "读取评论", "保存"],
                    },
                )
            except Exception:
                pass
            await asyncio.sleep(1)
            obs = await observe_desktop(f"重新提取帖子内容")
            post_data = await self._extract_post_content(obs.screenshot_path, author)
            if not post_data:
                await self._go_back()
                return None

        content_id = f"x:{author}:{preview[:40]}"
        source_url = post_data.get("source_url", f"https://x.com/{author}")

        content = CollectedContent(
            content_id=content_id,
            platform="x",
            source_url=source_url,
            author=author,
            title=post_data.get("title", ""),
            body_text=post_data.get("body_text", preview),
            external_links=post_data.get("external_links", []),
            images=[],
        )
        content.metrics.likes = post_data.get("likes", 0) or 0
        content.metrics.reposts = post_data.get("reposts", 0) or 0
        content.metrics.replies = post_data.get("replies", 0) or 0
        content.metrics.views = post_data.get("views", 0) or 0
        content.metrics.bookmarks = post_data.get("bookmarks", 0) or 0

        console.print(
            f"      [dim]正文: {len(content.body_text)} 字 | "
            f"❤{content.metrics.likes} 🔁{content.metrics.reposts} "
            f"💬{content.metrics.replies} 👁{content.metrics.views}[/dim]"
        )

        # Step 3: 如果指标缺失，滚动查找
        if not content.metrics.likes and not content.metrics.views:
            console.print(f"    [cyan]  指标不可见，滚动查找...[/cyan]")
            await self._find_metrics(content)

        # Step 4: 处理图片
        if post_data.get("has_image") and post_data.get("images"):
            console.print(f"    [cyan]  检测到 {len(post_data['images'])} 张图片，分析...[/cyan]")
            await self._analyze_images(content, post_data["images"])

        # Step 5: 读取评论
        console.print(f"    [cyan]  读取评论...[/cyan]")
        content.comments = await self._read_comments()

        # Step 6: 相关性打分
        score = await self._score_relevance(content)
        content.relevance_score = score
        if score < threshold:
            console.print(f"    [dim]跳过 (score={score:.1f})[/dim]")
            save_reference(content.source_url, "x", source="search", was_collected=False)
            await self._go_back()
            return None

        # Step 7: 摘要 + 标签
        content.summary = await self._summarize(content)
        content.tags = await self._extract_tags(content)

        # ★ 实时保存
        save_content(content)
        console.print(
            f"    [green]✓ 已保存[/green] @{content.author} "
            f"score={score:.1f} ❤{content.metrics.likes} 👁{content.metrics.views} "
            f"💬{len(content.comments)} 🖼{len(content.images)}"
        )

        save_reference(
            content.source_url, "x",
            content_id=content.content_id,
            title=f"@{content.author}: {content.body_text[:80]}",
            was_collected=True,
            source="search",
        )

        # 同步 Notion
        await self._sync_to_notion(content)

        # 返回搜索页
        await self._go_back()
        return content

    async def _find_metrics(self, content: CollectedContent) -> None:
        """滚动帖子页面查找隐藏的互动指标。"""
        for _ in range(4):
            obs = await observe_desktop("查找互动指标")
            raw = await vision_chat(
                text_prompt=(
                    "这是 X 帖子详情页的截图。\n"
                    "请在截图中找到以下数据（如果可见）：\n"
                    "  - likes/reposts/replies/views/bookmarks 数字\n"
                    "  - 发布时间\n"
                    "  - 图片/链接/视频\n"
                    "返回 JSON:\n"
                    '{"likes":数字,"reposts":数字,"replies":数字,"views":数字,"bookmarks":数字,"published":"时间","has_media":true/false}\n'
                    "如果都不可见，在 JSON 中加 needs_scroll:true。"
                ),
                image_path=obs.screenshot_path,
                max_tokens=512,
            )
            try:
                data = json.loads(_safe_extract_json(raw))
                if isinstance(data, dict):
                    content.metrics.likes = data.get("likes") or content.metrics.likes or 0
                    content.metrics.reposts = data.get("reposts") or content.metrics.reposts or 0
                    content.metrics.replies = data.get("replies") or content.metrics.replies or 0
                    content.metrics.views = data.get("views") or content.metrics.views or 0
                    content.metrics.bookmarks = data.get("bookmarks") or content.metrics.bookmarks or 0

                    if data.get("needs_scroll"):
                        # 滚动再找
                        from app.desktop.executor import execute_desktop
                        from app.schemas.action import ActionType, PlannedAction
                        await execute_desktop(PlannedAction(
                            action=ActionType.SCROLL, direction="down", amount=8,
                            reason="滚动查找指标"
                        ))
                        await asyncio.sleep(1.5)
                        continue
                    else:
                        console.print(
                            f"      [dim]指标: ❤{content.metrics.likes} 🔁{content.metrics.reposts} "
                            f"💬{content.metrics.replies} 👁{content.metrics.views}[/dim]"
                        )
                        return
            except Exception:
                logger.debug(f"指标提取失败: {raw[:200]}")
                break

    async def _analyze_images(self, content: CollectedContent, image_descs: list[str]) -> None:
        """分析帖子中的图片。"""
        for i, desc in enumerate(image_descs[:3]):
            # 尝试点开图片
            if i == 0:
                try:
                    await self.agent.run(
                        "Click on the image in the post to view it full-size.",
                        max_cycles=3,
                    )
                except Exception:
                    pass
                await asyncio.sleep(1)

            # 视觉分析
            obs = await observe_desktop(f"分析图片 {i+1}")
            raw = await vision_chat(
                text_prompt=(
                    "这是 X 帖子中的图片。请：\n"
                    "1. 详细描述图片内容（中文）\n"
                    "2. 如果是数据图表，提取关键数据\n"
                    "3. 如果是产品截图，描述功能\n"
                    "4. 给出调研价值（1-5分）\n"
                    '返回: {"description":"...","insights":["..."],"value":1-5}\n'
                    "如果截图中没有明显图片，返回 null。"
                ),
                image_path=obs.screenshot_path,
                max_tokens=1024,
            )
            try:
                data = json.loads(_safe_extract_json(raw))
                if isinstance(data, dict) and data.get("description"):
                    content.images.append(
                        f"[图片{i+1}] {desc} | {data['description'][:200]}"
                    )
                    if data.get("insights"):
                        content.images.append(f"[洞察] {'; '.join(data['insights'])}")
                    console.print(f"      [green]图片分析: {data['description'][:60]}...[/green]")

                # 返回帖子
                try:
                    await self.agent.run("Press Escape or go back to return to the post.", max_cycles=2)
                except Exception:
                    pass
                await asyncio.sleep(1)
            except Exception:
                logger.debug(f"图片{i+1}分析失败: {raw[:200]}")

    async def _extract_post_content(self, screenshot_path: str, author: str) -> dict | None:
        """从帖子详情页截图提取结构化内容。"""
        extract = await vision_chat(
            text_prompt=(
                "这是一个 X (Twitter) 帖子的详情页截图。\n"
                "仔细阅读截图中所有文字，提取以下信息:\n"
                '{\n'
                '  "author": "用户名(不含@)",\n'
                '  "title": "帖子第一行或标题（没有则空）",\n'
                '  "body_text": "帖子完整正文（包含换行）",\n'
                '  "external_links": ["帖子中的外链URL，没有则[]"],\n'
                '  "images": ["图片描述，如: 数据图表/产品截图/表情包"],\n'
                '  "has_image": true或false,\n'
                '  "likes": 数字,\n'
                '  "reposts": 数字,\n'
                '  "replies": 数字,\n'
                '  "views": 数字,\n'
                '  "source_url": "完整的 x.com/... URL",\n'
                '  "published_at": "发布时间（如: 2小时前、Apr 8, 2026）"\n'
                '}\n'
                "如果页面不是帖子详情页，返回 null。\n"
                "只返回 JSON，不要任何其他文字。"
            ),
            image_path=screenshot_path,
            max_tokens=1024,
        )
        logger.info(f"帖子内容: {extract[:300]}")
        try:
            data = json.loads(_safe_extract_json(extract))
            if data is None:
                return None
            return data
        except Exception as e:
            logger.warning(f"帖子内容提取失败: {e}")
            return None

    async def _read_comments(self) -> list[Comment]:
        """滚动帖子评论区，视觉提取评论。"""
        comments: list[Comment] = []

        # 先尝试滚动到评论区域
        try:
            await self.agent.run(
                "Scroll down to see the comments/replies section of this post.",
                max_cycles=3,
                plan_context={
                    "overall_goal": "深度采集帖子内容",
                    "current_step": "读取评论区",
                    "completed_steps": ["提取帖子正文 ✓", "复制链接 ✓"],
                    "next_steps": ["提取评论", "相关性打分", "保存 → Notion 同步"],
                },
            )
        except Exception:
            pass

        # 视觉识别评论
        for scroll_round in range(3):
            obs = await observe_desktop("识别评论区")
            raw = await vision_chat(
                text_prompt=(
                    "这是 X 帖子的评论区截图。\n"
                    "识别每条可见评论：\n"
                    "  - author: 用户名\n"
                    "  - text: 评论正文（前100字）\n"
                    "  - likes: 点赞数\n"
                    "返回 JSON 数组，最多5条（当前屏幕可见的）。\n"
                    "如果看不到评论，返回 []。\n"
                    "只返回 JSON 数组。"
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
                logger.debug(f"评论识别失败: {raw[:200]}")

            # 再往下滚
            try:
                await self.agent.run(
                    "Scroll down a bit more to see additional comments.",
                    max_cycles=2,
                )
            except Exception:
                break

            await asyncio.sleep(1)

        console.print(f"    [dim]  读取到 {len(comments)} 条评论[/dim]")
        return comments[:15]  # 最多保存15条

    async def _go_back(self) -> CollectedContent | None:
        """返回上一页（回到搜索结果）。返回 None 表示继续采集流程。"""
        from app.desktop.executor import execute_desktop
        from app.schemas.action import ActionType, PlannedAction
        try:
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["command", "["],
                reason="返回搜索结果"
            ))
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"返回失败: {e}")
        return None

    async def _focus_browser(self) -> None:
        """聚焦浏览器窗口 — 先点击浏览器空白处确保后续点击有效。"""
        from app.desktop.executor import execute_desktop
        from app.schemas.action import ActionType, PlannedAction

        console.print(f"      [dim]聚焦浏览器窗口...[/dim]")
        try:
            # 截图找浏览器内容区域
            obs = await observe_desktop("定位浏览器窗口")
            # 点击浏览器顶部地址栏区域（大致位置）确保聚焦
            # 用 LLM 识别浏览器窗口的安全点击位置
            raw = await vision_chat(
                text_prompt=(
                    "这是当前桌面截图。请识别浏览器（Safari）窗口的位置。\n"
                    '返回 JSON: {"browser_x": 500, "browser_y": 130, "focused": true/false}\n'
                    "browser_x, browser_y 是浏览器地址栏区域的一个安全点击坐标（归一化 1000x1000）。\n"
                    "只返回 JSON。"
                ),
                image_path=obs.screenshot_path,
                max_tokens=200,
            )
            try:
                data = json.loads(_safe_extract_json(raw))
                if isinstance(data, dict) and data.get("browser_x"):
                    await execute_desktop(PlannedAction(
                        action=ActionType.CLICK_AT,
                        x=int(data["browser_x"]),
                        y=int(data["browser_y"]),
                        reason="聚焦浏览器窗口"
                    ))
                    await asyncio.sleep(0.5)
                    console.print(f"      [green]已点击浏览器地址栏区域[/green]")
                else:
                    console.print(f"      [dim]无法识别浏览器坐标，跳过聚焦[/dim]")
            except Exception:
                # 兜底：点击屏幕中央偏上区域（通常是浏览器位置）
                await execute_desktop(PlannedAction(
                    action=ActionType.CLICK_AT,
                    x=500, y=150,
                    reason="聚焦浏览器（兜底点击屏幕中央）"
                ))
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"浏览器聚焦失败: {e}")

    async def _copy_post_url(self) -> str | None:
        """通过分享按钮复制帖子链接：点击分享图标 → 点击"Copy link"。"""
        from app.desktop.executor import execute_desktop
        from app.schemas.action import ActionType, PlannedAction

        obs = await observe_desktop("定位分享按钮")
        try:
            raw = await vision_chat(
                text_prompt=(
                    "这是 X 帖子详情页的截图。\n"
                    "找到帖子底部的分享按钮（在评论、转发、点赞、收藏按钮右边），\n"
                    "以及 'Copy link' 或 '复制链接' 菜单项。\n"
                    '返回 JSON: {"share_button_x": 800, "share_button_y": 600, "copy_link_x": 700, "copy_link_y": 650}\n'
                    "坐标归一化 1000x1000。如果找不到分享按钮，返回 null。\n"
                    "只返回 JSON。"
                ),
                image_path=obs.screenshot_path,
                max_tokens=200,
            )
            data = json.loads(_safe_extract_json(raw))
            if isinstance(data, dict) and data.get("share_button_x"):
                # 点击分享按钮
                await execute_desktop(PlannedAction(
                    action=ActionType.CLICK_AT,
                    x=int(data["share_button_x"]),
                    y=int(data["share_button_y"]),
                    reason="点击分享按钮"
                ))
                await asyncio.sleep(0.5)

                # 点击 Copy Link
                if data.get("copy_link_x") and data.get("copy_link_y"):
                    await execute_desktop(PlannedAction(
                        action=ActionType.CLICK_AT,
                        x=int(data["copy_link_x"]),
                        y=int(data["copy_link_y"]),
                        reason="点击 Copy Link"
                    ))
                    await asyncio.sleep(0.5)

                # 从剪贴板获取 URL
                import subprocess
                pbpaste = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
                url = pbpaste.stdout.strip()
                if url and ("x.com/" in url or "twitter.com/" in url):
                    console.print(f"      [green]帖子链接: {url}[/green]")
                    return url
        except Exception as e:
            logger.debug(f"复制帖子链接失败: {e}")
        return None

    async def _copy_url_from_address_bar(self) -> str | None:
        """从地址栏复制 URL：Cmd+L 全选 → Cmd+C 复制。"""
        from app.desktop.executor import execute_desktop
        from app.schemas.action import ActionType, PlannedAction

        try:
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["command", "l"],
                reason="聚焦地址栏"
            ))
            await asyncio.sleep(0.3)
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["command", "c"],
                reason="复制地址栏URL"
            ))
            await asyncio.sleep(0.3)

            import subprocess
            pbpaste = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
            url = pbpaste.stdout.strip()
            if url and ("x.com/" in url or "twitter.com/" in url):
                console.print(f"      [green]地址栏URL: {url}[/green]")
                return url
            # 恢复焦点（按 Escape 取消地址栏选中）
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["escape"],
                reason="取消地址栏选中"
            ))
        except Exception as e:
            logger.debug(f"地址栏复制URL失败: {e}")
        return None

    async def _sync_to_notion(self, content: CollectedContent) -> None:
        """同步到 Notion。"""
        try:
            from app.integrations.notion_client import save_research
            page_id = await save_research(content)
            if page_id:
                content.notion_page_id = page_id
                save_content(content)
                console.print(f"    [green]✓ Notion 已同步[/green]")
            else:
                console.print(f"    [yellow]Notion 未配置（跳过）[/yellow]")
        except Exception as e:
            console.print(f"    [yellow]Notion 同步失败: {e}[/yellow]")

    # ── LLM 辅助 ──────────────────────────────────────────────────────

    async def _score_relevance(self, c: CollectedContent) -> float:
        prompt = (
            "对这条帖子与 AI/创业/科技/内容创作的相关性打 1-5 分。\n"
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

    async def _summarize(self, c: CollectedContent) -> str:
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

    async def _extract_tags(self, c: CollectedContent) -> list[str]:
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


# ── JSON 提取工具函数 ─────────────────────────────────────────────

def _safe_extract_json(text: str) -> str:
    """Robust JSON extraction from LLM response."""
    text = text.strip()
    # Strip markdown code blocks
    if "```json" in text:
        text = text.split("```json", 1)[1]
        text = text.split("```", 1)[0] if "```" in text else text
    elif text.startswith("```"):
        text = text.split("```", 1)[1]
        parts = text.rsplit("```", 1)
        text = parts[0] if len(parts) > 1 else text
    text = text.strip()

    # Try to find complete JSON object or array
    if not text:
        return ""

    # Find the FIRST JSON delimiter
    first_obj = text.find("{")
    first_arr = text.find("[")

    if first_obj == -1 and first_arr == -1:
        if "null" in text.lower():
            return "null"
        return text

    # Start from whichever comes first
    start = first_arr if (first_arr != -1 and (first_obj == -1 or first_arr < first_obj)) else first_obj
    bracket = "[" if start == first_arr else "{"
    close = "]" if bracket == "[" else "}"

    # Count brackets to find the real end
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

    # Fallback: simple last-close
    end = text.rfind(close) + 1
    if end > 0:
        return text[start:end]
    return text


def _safe_parse_json_array(text: str) -> list | dict:
    """Parse JSON from LLM text, expecting an array (but fallback to dict)."""
    raw = _safe_extract_json(text)
    if not raw:
        return []
    return json.loads(raw)
