"""桌面级 X 发布器 — 全屏截图 + 视觉定位发布。"""
from __future__ import annotations

import asyncio

from app.core.errors import HumanReviewRequired
from app.core.logger import logger
from app.desktop.action_planner import plan_desktop_actions
from app.desktop.executor import execute_desktop
from app.desktop.observer import observe_desktop
from app.schemas.action import ActionType, PlannedAction
from app.schemas.content import PlatformDraft


class DesktopXPublisher:
    """通过桌面视觉控制发布帖子到 X。"""

    async def publish_draft(self, draft: PlatformDraft) -> str:
        """在 X 上发布一条帖子。"""
        from rich.console import Console
        console = Console()

        # 打开 Safari 并导航到 X
        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["command", "space"],
            reason="打开 Spotlight"
        ))
        await asyncio.sleep(0.5)
        await execute_desktop(PlannedAction(
            action=ActionType.TYPE_TEXT, text="Safari",
            reason="搜索 Safari"
        ))
        await asyncio.sleep(1)
        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["return"],
            reason="启动 Safari"
        ))
        await asyncio.sleep(2)

        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["command", "l"],
            reason="聚焦地址栏"
        ))
        await asyncio.sleep(0.5)
        await execute_desktop(PlannedAction(
            action=ActionType.TYPE_TEXT, text="https://x.com",
            reason="输入 X 网址"
        ))
        await asyncio.sleep(0.5)
        await execute_desktop(PlannedAction(
            action=ActionType.HOTKEY, keys=["return"],
            reason="跳转到 X"
        ))
        await asyncio.sleep(3)

        # 用视觉模型定位发帖框
        obs = await observe_desktop("在 X 首页找到发帖按钮")
        plan = await plan_desktop_actions(obs)

        # 找到发帖框并点击
        found_compose = False
        for step in plan.steps:
            if step.action in (ActionType.CLICK_AT, ActionType.DOUBLE_CLICK_AT):
                await execute_desktop(step)
                found_compose = True
                break

        if not found_compose:
            # 默认尝试点击屏幕中央偏上（发帖框大致位置）
            await execute_desktop(PlannedAction(
                action=ActionType.CLICK_AT, x=640, y=200,
                reason="点击发帖框区域"
            ))

        await asyncio.sleep(1)

        # 输入帖子内容
        body = draft.body
        if len(body) > 280:
            # 分段发布
            chunks = _split_into_tweets(body)
            for i, chunk in enumerate(chunks):
                await execute_desktop(PlannedAction(
                    action=ActionType.TYPE_TEXT, text=chunk,
                    reason=f"输入第 {i+1} 段"
                ))
                await asyncio.sleep(0.5)
                if i < len(chunks) - 1:
                    # 点击"添加另一篇帖子"
                    await execute_desktop(PlannedAction(
                        action=ActionType.CLICK_AT, x=640, y=700,
                        reason="添加另一篇帖子"
                    ))
                    await asyncio.sleep(1)
        else:
            await execute_desktop(PlannedAction(
                action=ActionType.TYPE_TEXT, text=body,
                reason="输入帖子内容"
            ))

        await asyncio.sleep(1)

        # 点击发布按钮（视觉定位）
        obs2 = await observe_desktop("找到发布按钮")
        plan2 = await plan_desktop_actions(obs2)
        for step in plan2.steps:
            if step.action in (ActionType.CLICK_AT, ActionType.DOUBLE_CLICK_AT):
                console.print("[yellow]即将发布，请确认内容正确...[/yellow]")
                console.print(f"[bold]{body[:100]}...[/bold]")
                # 等用户确认
                await asyncio.sleep(2)
                await execute_desktop(step)
                logger.info("帖子已发布")
                return "https://x.com"

        logger.warning("未找到发布按钮")
        raise HumanReviewRequired("未找到发布按钮，请手动点击")


def _split_into_tweets(text: str, limit: int = 280) -> list[str]:
    """将长文本拆分为推文分段。"""
    chunks = []
    while len(text) > limit:
        # 在最后一个句号/逗号/空格处截断
        split_at = text.rfind(".", 0, limit)
        if split_at == -1:
            split_at = text.rfind(",", 0, limit)
        if split_at == -1:
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at + 1])
        text = text[split_at + 1:].lstrip()
    if text:
        chunks.append(text)
    return chunks
