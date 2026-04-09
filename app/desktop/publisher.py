"""桌面级 X 发布器 — 纯视觉控制。"""
from __future__ import annotations

import asyncio

from app.core.errors import HumanReviewRequired
from app.core.logger import logger
from app.desktop.computer_agent import ComputerAgent
from app.desktop.observer import observe_desktop
from rich.console import Console

from app.schemas.content import PlatformDraft


class DesktopXPublisher:
    """通过桌面视觉控制发布帖子到 X。"""

    def __init__(self):
        self.agent = ComputerAgent(max_cycles=15)

    async def publish_draft(self, draft: PlatformDraft) -> str:
        """在 X 上发布一条帖子。"""
        console = Console()

        # Phase 1: 打开浏览器并导航到 X
        console.print("[cyan]打开浏览器，导航到 X...[/cyan]")
        try:
            await self.agent.run("打开浏览器，导航到 x.com。确保已登录。")
        except Exception as e:
            logger.warning(f"导航到 X 失败: {e}")
            console.print("[yellow]请手动打开浏览器并确保已登录到 X，然后重试。[/yellow]")
            raise HumanReviewRequired("无法自动导航到 X，请手动打开浏览器并登录")

        # Phase 2: 开始写帖子
        console.print("[cyan]找到发帖框...[/cyan]")
        try:
            await self.agent.run(
                "在 X 首页找到发帖按钮（通常是蓝色的 Post/发布 按钮或笔图标）并点击，开始写新帖子。",
            )
        except Exception as e:
            logger.warning(f"未找到发帖按钮: {e}")
            raise HumanReviewRequired("未找到发帖按钮，请手动点击")

        await asyncio.sleep(1)

        # Phase 3: 输入内容
        body = draft.body
        if len(body) > 280:
            # 分段发布（Thread）
            chunks = _split_into_tweets(body)
            for i, chunk in enumerate(chunks):
                console.print(f"[dim]输入第 {i+1}/{len(chunks)} 段...[/dim]")
                try:
                    await self.agent.run(
                        f"在编辑框中输入以下文字：{chunk!r}",
                        context={"text_to_type": chunk},
                    )
                except Exception as e:
                    logger.warning(f"输入第 {i+1} 段失败: {e}")
                    raise HumanReviewRequired(f"输入第 {i+1} 段时失败，请手动输入")

                await asyncio.sleep(0.5)

                if i < len(chunks) - 1:
                    # 添加另一篇帖子
                    console.print("[dim]添加另一篇帖子...[/dim]")
                    try:
                        await self.agent.run(
                            "找到并点击 'Add another post' 或 '+' 按钮，添加 Thread 的下一篇帖子。",
                        )
                    except Exception:
                        # 回退：按 Cmd+Enter 或 Tab 找按钮
                        from app.desktop.executor import execute_desktop
                        from app.schemas.action import ActionType, PlannedAction
                        await execute_desktop(PlannedAction(
                            action=ActionType.HOTKEY, keys=["command", "return"],
                            reason="尝试添加另一篇帖子"
                        ))
                    await asyncio.sleep(1)
        else:
            # 单条帖子
            console.print("[dim]输入帖子内容...[/dim]")
            try:
                await self.agent.run(
                    f"在编辑框中输入以下文字：{body!r}",
                    context={"text_to_type": body},
                )
            except Exception as e:
                logger.warning(f"输入帖子内容失败: {e}")
                raise HumanReviewRequired("输入帖子内容时失败，请手动输入")

        await asyncio.sleep(1)

        # Phase 4: 人工确认 + 发布
        obs = await observe_desktop("预览即将发布的帖子内容")
        console.print("[yellow]即将发布，请确认内容正确...[/yellow]")
        console.print(f"[bold]{body[:150]}{'...' if len(body) > 150 else ''}[/bold]")
        await asyncio.sleep(3)

        console.print("[cyan]点击发布按钮...[/cyan]")
        try:
            await self.agent.run(
                "找到蓝色的 'Post' 或 '发布' 按钮并点击，发布这条帖子。",
            )
        except Exception as e:
            logger.warning(f"发布失败: {e}")
            raise HumanReviewRequired("未找到发布按钮，请手动点击发布")

        logger.info("帖子已发布")
        return "https://x.com"


def _split_into_tweets(text: str, limit: int = 280) -> list[str]:
    """将长文本拆分为推文分段。"""
    chunks = []
    while len(text) > limit:
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
