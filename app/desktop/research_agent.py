"""桌面级 X 调研 Agent — 纯视觉闭环：截图 → 分析 → 执行 → 循环。"""
from __future__ import annotations

import asyncio
import json
import random
import subprocess
import time
from datetime import datetime

import pyautogui

from app.assets.downloader import download_images
from app.core.config import load_yaml
from app.core.errors import HumanReviewRequired
from app.core.logger import logger
from app.desktop.action_planner import plan_desktop_actions
from app.desktop.executor import execute_desktop
from app.desktop.observer import observe_desktop
from app.llm.client import chat, vision_chat
from app.memory.sqlite_repo import save_content, save_reference
from app.schemas.action import ActionType, ActionPlan, PlannedAction
from app.schemas.content import CollectedContent
from rich.console import Console

console = Console()


# ── 视觉循环 ───────────────────────────────────────────────────────────

async def vision_loop(
    task: str,
    *,
    max_cycles: int = 30,
    done_when: str = "DONE",
) -> list[PlannedAction]:
    """通用视觉操作循环：截图 → 分析 → 执行 → 循环。"""
    screen_w, screen_h = pyautogui.size()
    history: list[str] = []
    actions_done: list[PlannedAction] = []

    for cycle in range(1, max_cycles + 1):
        # 1. 截图
        obs = await observe_desktop(
            task_description=task,
            previous_action_summary=" | ".join(history[-3:]) if history else "",
        )

        # 2. 分析 + 计划
        prompt = (
            f"TASK: {task}\n"
            f"SCREEN: {obs.screen_width}x{obs.screen_height}\n"
            f"PREVIOUS: {' | '.join(history[-3:]) if history else 'Start'}\n"
            f"\nLook at the screenshot. What should I do next?\n"
            f'If the task is done, return action "done".\n'
            f'If stuck, return action "human" with a message.\n'
            f"Return a plan with 1-3 steps."
        )

        raw = await vision_chat(
            text_prompt=prompt,
            image_path=obs.screenshot_path,
            max_tokens=1024,
        )

        try:
            data = json.loads(_extract_json(raw))
            plan = ActionPlan(**data)
        except Exception as e:
            logger.warning(f"解析计划失败: {e}")
            plan = ActionPlan(steps=[], confidence=0.0, notes=f"parse error: {e}")

        if not plan.steps:
            console.print(f"    [yellow]Cycle {cycle}: 无动作计划[/yellow]")
            if "done" in raw.lower() or "完成" in raw:
                break
            plan.steps = [PlannedAction(action=ActionType.DONE, reason="无更多动作")]

        # 3. 执行
        for step in plan.steps:
            if step.action in (ActionType.DONE,):
                console.print(f"    [green]Cycle {cycle}: 任务完成[/green]")
                actions_done.extend(plan.steps)
                return actions_done
            if step.action == ActionType.HUMAN:
                msg = step.message or step.reason
                console.print(f"    [bold yellow]需要人工: {msg}[/bold yellow]")
                raise HumanReviewRequired(msg)

            console.print(
                f"    [dim]Cycle {cycle}: {step.action.value} — {step.reason or ''}[/dim]"
            )
            try:
                await execute_desktop(step)
                actions_done.append(step)
                history.append(f"{step.action.value}: {step.reason or ''}")
            except Exception as e:
                logger.warning(f"执行失败: {e}")
                history.append(f"FAIL: {step.action.value} - {e}")

    return actions_done


# ── 研究流程 ───────────────────────────────────────────────────────────

class DesktopXResearcher:
    """全屏视觉调研 X — 每条帖子实时记录。"""

    def __init__(self):
        self._collected_urls: set[str] = set()

    # ── 启动 Safari 到 X ─────────────────────────────────────────────

    async def _launch_safari(self) -> None:
        """用视觉循环打开 Safari 并导航到 X。"""
        console.print("[cyan]打开 Safari...[/cyan]")

        # 激活 Safari（osascript）
        subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to activate'],
            capture_output=True,
        )
        await asyncio.sleep(1)

        # 检查 Safari 有没有窗口，没有就打开
        result = subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to count windows'],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or result.stdout.strip() == "0":
            subprocess.run(["open", "-a", "Safari"], capture_output=True)
            await asyncio.sleep(2)

    async def _go_to_x_home(self) -> bool:
        """用视觉循环导航到 x.com。"""
        console.print("[cyan]导航到 x.com...[/cyan]")

        # 截图，识别当前状态
        obs = await observe_desktop("识别当前应用，准备导航到 x.com")
        screen = await vision_chat(
            text_prompt=(
                "这是什么应用？如果是 Safari，地址栏的 URL 是什么？\n"
                '返回 JSON: {"app": "应用名", "is_safari": true/false, "current_url": "如果可见"}'
            ),
            image_path=obs.screenshot_path,
            max_tokens=128,
        )
        logger.debug(f"Safari 状态: {screen[:200]}")

        # Cmd+L 聚焦地址栏
        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["command", "l"],
            reason="聚焦地址栏"
        ))
        await asyncio.sleep(0.3)

        # Cmd+A 全选
        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["command", "a"],
            reason="全选地址"
        ))
        await asyncio.sleep(0.3)

        # 输入 x.com
        await execute_desktop(PlannedAction(
            action=ActionType.TYPE_TEXT, text="https://x.com",
            reason="输入 X 地址"
        ))
        await asyncio.sleep(0.3)

        # Enter
        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["return"],
            reason="跳转"
        ))

        # 等待页面渲染
        await asyncio.sleep(5)

        # 检查是否登录墙
        obs2 = await observe_desktop("检查 X 登录墙")
        login_check = await vision_chat(
            text_prompt=(
                "这是 x.com 页面的截图。\n"
                "是否有登录墙/登录表单/要求登录的提示？\n"
                '返回 JSON: {"login_required": true/false, "is_x_home": true/false, "note": "说明"}'
            ),
            image_path=obs2.screenshot_path,
            max_tokens=128,
        )
        logger.debug(f"登录检查: {login_check[:200]}")
        try:
            data = json.loads(_extract_json(login_check))
            if data.get("login_required", False):
                console.print("[bold yellow]⚠ X 需要登录！请在浏览器中完成登录。[/bold yellow]")
                return False
        except Exception:
            pass

        return True

    # ── 搜索 ──────────────────────────────────────────────────────────

    async def _search_topic(self, topic: str) -> None:
        """在 X 上搜索一个主题 — 视觉驱动。"""
        console.print(f"[cyan]搜索: {topic}[/cyan]")

        # 截图，找到搜索框
        obs = await observe_desktop("找到 X 的搜索框位置")
        find_search = await vision_chat(
            text_prompt=(
                "这是 X (Twitter) 首页的截图。\n"
                "找到搜索框的位置，返回它的中心坐标。\n"
                '返回 JSON: {"found_search_box": true/false, "x": 数字, "y": 数字, "note": "说明"}'
            ),
            image_path=obs.screenshot_path,
            max_tokens=128,
        )
        logger.debug(f"搜索框定位: {find_search[:200]}")

        try:
            data = json.loads(_extract_json(find_search))
            if data.get("found_search_box"):
                # 点击搜索框
                await execute_desktop(PlannedAction(
                    action=ActionType.CLICK_AT,
                    x=data["x"], y=data["y"],
                    reason="点击搜索框"
                ))
                await asyncio.sleep(0.5)

                # 输入搜索词
                await execute_desktop(PlannedAction(
                    action=ActionType.TYPE_TEXT, text=topic,
                    reason=f"搜索 {topic}"
                ))
                await asyncio.sleep(0.3)

                # Enter
                await execute_desktop(PlannedAction(
                    action=ActionType.HOTKEY, keys=["return"],
                    reason="执行搜索"
                ))
                await asyncio.sleep(3)
            else:
                # 找不到搜索框，用 Cmd+F 或直接用 Cmd+L 导航到搜索 URL
                console.print("    [yellow]未找到搜索框，使用 URL 导航[/yellow]")
                await self._go_to_search_url(topic)
        except Exception:
            console.print("    [yellow]搜索框定位失败，使用 URL 导航[/yellow]")
            await self._go_to_search_url(topic)

    async def _go_to_search_url(self, topic: str) -> None:
        """回退：用 URL 直接导航到搜索结果。"""
        from urllib.parse import quote_plus
        url = f"https://x.com/search?q={quote_plus(topic)}&src=typed_query&f=top"

        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["command", "l"],
            reason="聚焦地址栏"
        ))
        await asyncio.sleep(0.3)
        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["command", "a"],
            reason="全选"
        ))
        await asyncio.sleep(0.3)
        await execute_desktop(PlannedAction(
            action=ActionType.TYPE_TEXT, text=url,
            reason="输入搜索 URL"
        ))
        await asyncio.sleep(0.3)
        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["return"],
            reason="跳转"
        ))
        await asyncio.sleep(5)

    # ── 滚动加载 ──────────────────────────────────────────────────────

    async def _scroll_and_extract_posts(self, topic: str, max_posts: int = 20) -> list[dict]:
        """视觉驱动：滚动 + 识别帖子。"""
        console.print("[cyan]滚动加载帖子...[/cyan]")
        posts_found: list[dict] = []
        prev_post_count = 0
        no_new_rounds = 0

        for round_num in range(12):
            # 滚动
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["space"],
                reason=f"翻页加载 (第 {round_num + 1} 轮)"
            ))
            await asyncio.sleep(2)

            # 截图识别帖子
            obs = await observe_desktop("识别屏幕上的帖子")
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
                    # 去重（基于 author+preview）
                    for p in new_posts:
                        key = f"{p['author']}:{p.get('text_preview', '')[:30]}"
                        if key not in {f"{x['author']}:{x.get('text_preview', '')[:30]}" for x in posts_found}:
                            posts_found.append(p)
                            console.print(
                                f"    [dim]发现: @{p['author']} — {p.get('text_preview', '')[:40]}[/dim]"
                            )
                    if len(posts_found) >= max_posts:
                        break

                    # 检查是否有新帖子
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

            await asyncio.sleep(1)

        console.print(f"  [dim]共识别 {len(posts_found)} 个帖子[/dim]")
        return posts_found[:max_posts]

    # ── 逐个采集帖子详情 ──────────────────────────────────────────────

    async def _collect_post_detail(self, post_info: dict, topic: str) -> CollectedContent | None:
        """点开帖子详情页，视觉提取内容，立即保存。"""
        author = post_info.get("author", "")
        preview = post_info.get("text_preview", "")
        threshold = load_yaml("configs/app.yaml")["research"].get("relevance_threshold", 3.0)

        console.print(f"    [cyan]采集 @{author}...[/cyan]")

        # 用视觉循环点开帖子
        obs = await observe_desktop(f"找到 @{author} 的帖子并点开")
        find_post = await vision_chat(
            text_prompt=(
                f"这是 X 搜索结果页面。找到用户名为 '{author}' 的帖子。\n"
                "找到帖子正文的区域，返回它的中心坐标。\n"
                "这个坐标用于点击打开帖子详情。\n"
                '返回 JSON: {"found": true/false, "x": 数字, "y": 数字, "note": "说明"}'
            ),
            image_path=obs.screenshot_path,
            max_tokens=128,
        )

        try:
            data = json.loads(_extract_json(find_post))
            if data.get("found"):
                await execute_desktop(PlannedAction(
                    action=ActionType.CLICK_AT,
                    x=data["x"], y=data["y"],
                    reason=f"点击 @{author} 的帖子"
                ))
                await asyncio.sleep(4)  # 等待页面加载
            else:
                console.print(f"    [yellow]未找到帖子，跳过[/yellow]")
                return None
        except Exception:
            console.print(f"    [yellow]定位帖子失败，跳过[/yellow]")
            return None

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
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["command", "["],
                reason="返回搜索结果"
            ))
            await asyncio.sleep(2)

            return content
        except Exception as e:
            logger.warning(f"帖子处理失败: {e}")
            # 尝试返回
            await execute_desktop(PlannedAction(
                action=ActionType.HOTKEY, keys=["command", "["],
                reason="返回搜索结果"
            ))
            await asyncio.sleep(2)
            return None

    # ── 主流程 ────────────────────────────────────────────────────────

    async def discover(self, topics: list[str] | None = None) -> list[str]:
        """搜索 X 并返回帖子来源列表。"""
        cfg = load_yaml("configs/app.yaml")
        r = cfg["research"]
        topics_per_run = r.get("topics_per_run", 10)
        posts_per_topic = r.get("posts_per_topic", 30)

        topic_cfg = load_yaml("configs/topics.yaml")
        if topics is None:
            topics = topic_cfg.get("keywords", [])

        all_posts: list[dict] = []

        # 1. 打开 Safari
        await self._launch_safari()

        # 2. 导航到 X
        ok = await self._go_to_x_home()
        if not ok:
            return []

        # 3. 搜索每个主题
        for topic in topics[:topics_per_run]:
            await self._search_topic(topic)
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
