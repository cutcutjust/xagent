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
from app.schemas.content import CollectedContent
from rich.console import Console

console = Console()


class DesktopXResearcher:
    """全屏视觉调研 X — 每条帖子实时记录。"""

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
            await self.agent.run("打开浏览器，导航到 x.com。如果看到登录墙或登录页面，停下来让人工登录。")
        except Exception as e:
            console.print(f"[yellow]导航到 X 时遇到问题: {e}[/yellow]")
            return []

        # 2. 搜索每个主题
        for topic in topics[:topics_per_run]:
            console.print(f"[cyan]搜索: {topic}[/cyan]")

            # 用 ComputerAgent 执行搜索
            try:
                await self.agent.run(
                    f"在 X 上搜索 '{topic}'。找到搜索框，输入搜索词，按回车，等待搜索结果加载。",
                    context={"search_query": topic},
                )
            except Exception as e:
                console.print(f"    [yellow]搜索失败: {e}[/yellow]")
                continue

            # 滚动并提取帖子
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
        """采集单个帖子 — 视觉驱动，立即保存。"""
        return await self._collect_post_detail(post_info, topic="")

    # ── 滚动提取帖子 ──────────────────────────────────────────────────

    async def _scroll_and_extract_posts(self, topic: str, max_posts: int = 20) -> list[dict]:
        """视觉驱动：模型决定如何滚动 + 识别帖子。"""
        console.print("[cyan]滚动加载帖子...[/cyan]")
        posts_found: list[dict] = []
        prev_post_count = 0
        no_new_rounds = 0

        for round_num in range(12):
            # 用视觉模型识别当前屏幕上的帖子
            obs = await observe_desktop(f"识别屏幕上的 X 帖子")
            raw = await vision_chat(
                text_prompt=(
                    "这是 X 搜索结果页面的截图。\n"
                    "识别每条可见帖子的：\n"
                    "  - author: 用户名（不含@）\n"
                    "  - text_preview: 正文前50字\n"
                    "  - likes: 点赞数（如果可见）\n"
                    "  - engagement: 互动数（如果有）\n"
                    "返回 JSON 数组，最多10条（当前屏幕可见的）。\n"
                    "如果看不到帖子，返回 []。"
                ),
                image_path=obs.screenshot_path,
                max_tokens=1024,
            )

            try:
                data = json.loads(_extract_json(raw))
                if isinstance(data, list):
                    new_posts = [p for p in data if p.get("author")]
                    for p in new_posts:
                        key = f"{p['author']}:{p.get('text_preview', '')[:30]}"
                        if key not in {f"{x['author']}:{x.get('text_preview', '')[:30]}" for x in posts_found}:
                            posts_found.append(p)
                            console.print(
                                f"    [dim]发现: @{p['author']} — {p.get('text_preview', '')[:40]}[/dim]"
                            )
                    if len(posts_found) >= max_posts:
                        break

                    if len(posts_found) == prev_post_count:
                        no_new_rounds += 1
                        if no_new_rounds >= 3:
                            console.print(f"    [yellow]连续 {no_new_rounds} 轮无新帖子[/yellow]")
                            break
                    else:
                        no_new_rounds = 0
                    prev_post_count = len(posts_found)
            except Exception as e:
                logger.warning(f"帖子识别失败: {e}")

            # 用 ComputerAgent 控制滚动（模型决定滚动方式）
            try:
                await self.agent.run(
                    "向下滚动页面加载更多帖子。用空格键、PageDown 键，或者拖动滚动条。",
                    max_cycles=3,
                )
            except Exception:
                # 回退：直接按空格
                from app.desktop.executor import execute_desktop
                from app.schemas.action import ActionType, PlannedAction
                await execute_desktop(PlannedAction(
                    action=ActionType.HOTKEY, keys=["space"],
                    reason=f"翻页加载 (第 {round_num + 1} 轮)"
                ))

            await asyncio.sleep(2)

        console.print(f"  [dim]共识别 {len(posts_found)} 个帖子[/dim]")
        return posts_found[:max_posts]

    # ── 逐个采集帖子详情 ──────────────────────────────────────────────

    async def _collect_post_detail(self, post_info: dict, topic: str) -> CollectedContent | None:
        """点开帖子详情页，视觉提取内容，立即保存。"""
        author = post_info.get("author", "")
        preview = post_info.get("text_preview", "")
        threshold = load_yaml("configs/app.yaml")["research"].get("relevance_threshold", 3.0)

        console.print(f"    [cyan]采集 @{author}...[/cyan]")

        # 用 ComputerAgent 点开帖子
        try:
            await self.agent.run(
                f"在搜索结果中找到 @{author} 的帖子并点击打开详情页面。",
                context={"target_author": author},
            )
        except Exception:
            console.print(f"    [yellow]定位帖子失败，跳过[/yellow]")
            return None

        await asyncio.sleep(2)  # 等待页面加载

        # 截图提取帖子内容
        obs2 = await observe_desktop(f"提取 @{author} 帖子内容")
        extract = await vision_chat(
            text_prompt=(
                "这是一个 X (Twitter) 帖子的全屏截图。\n"
                "仔细阅读截图中的文字，提取以下信息:\n"
                '{\n'
                '  "author": "用户名(不含@)",\n'
                '  "body_text": "帖子正文（完整）",\n'
                '  "external_links": ["帖子中的外链URL"],\n'
                '  "images": ["图片URL"],\n'
                '  "likes": 数字,\n'
                '  "reposts": 数字,\n'
                '  "replies": 数字\n'
                '}\n'
                "如果页面不是帖子，返回 null。\n"
                "只返回 JSON，不要其他文字。"
            ),
            image_path=obs2.screenshot_path,
            max_tokens=512,
        )
        logger.info(f"帖子内容: {extract[:300]}")

        try:
            data = json.loads(_extract_json(extract))
            if data is None:
                return None

            content_id = f"{author}:{preview[:30]}"
            content = CollectedContent(
                content_id=content_id,
                platform="x",
                source_url=f"https://x.com/{author}",
                author=author,
                body_text=data.get("body_text", ""),
                external_links=data.get("external_links", []),
                images=data.get("images", []),
            )
            content.metrics.likes = data.get("likes", 0) or 0
            content.metrics.reposts = data.get("reposts", 0) or 0
            content.metrics.replies = data.get("replies", 0) or 0

            # 相关性打分
            score = await self._score_relevance(content)
            content.relevance_score = score
            if score < threshold:
                console.print(f"    [dim]跳过 (score={score:.1f})[/dim]")
                save_reference(content.source_url, "x", source="search", was_collected=False)
                return None

            # 摘要 + 标签
            content.summary = await self._summarize(content)
            content.tags = await self._extract_tags(content)

            # ★ 实时记录 — 立刻保存
            save_content(content)
            console.print(f"    [green]✓ 已保存[/green] @{content.author} score={score:.1f}")

            save_reference(
                content.source_url, "x",
                content_id=content.content_id,
                title=f"@{content.author}: {content.body_text[:80]}",
                was_collected=True,
                source="search",
            )

            # 同步 Notion（可选）
            try:
                from app.integrations.notion_client import save_research
                page_id = await save_research(content)
                if page_id:
                    content.notion_page_id = page_id
                    save_content(content)
                    console.print(f"    [green]✓ Notion 已同步[/green]")
            except Exception as e:
                console.print(f"    [yellow]Notion 同步失败: {e}[/yellow]")

            # 返回搜索结果
            from app.desktop.executor import execute_desktop
            from app.schemas.action import ActionType, PlannedAction
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["command", "["],
                reason="返回搜索结果"
            ))
            await asyncio.sleep(2)

            return content
        except Exception as e:
            logger.warning(f"帖子处理失败: {e}")
            from app.desktop.executor import execute_desktop
            from app.schemas.action import ActionType, PlannedAction
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["command", "["],
                reason="返回搜索结果"
            ))
            await asyncio.sleep(2)
            return None

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
            return float(json.loads(raw).get("score", 3.0))
        except Exception:
            return 3.0

    async def _summarize(self, c: CollectedContent) -> str:
        prompt = (
            f"用 2-3 句话总结这条帖子，关注核心洞察。\n\n"
            f"@{c.author} ({c.metrics.likes} 赞):\n{c.body_text[:800]}\n\n"
            "总结:"
        )
        return (await chat([{"role": "user", "content": prompt}], max_tokens=200, temperature=0.3)).strip()

    async def _extract_tags(self, c: CollectedContent) -> list[str]:
        prompt = (
            f"提取 3-5 个主题标签，返回 JSON 数组。\n"
            f"帖子: {c.body_text[:400]}\n标签:"
        )
        raw = await chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=60)
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            return json.loads(raw[start:end])
        except Exception:
            return []


def _extract_json(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1:
        return text[start:end]
    if "null" in text.lower():
        return "null"
    return text
