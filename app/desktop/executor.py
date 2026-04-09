"""PyAutoGUI 全局动作执行器。"""
from __future__ import annotations

import asyncio
import random
from concurrent.futures import ThreadPoolExecutor

import pyautogui

from app.core.errors import ActionFailed
from app.core.logger import logger
from app.schemas.action import ActionType, PlannedAction

_executor = ThreadPoolExecutor(max_workers=1)


async def _run_sync(fn, *args, **kwargs):
    """在后台线程运行阻塞的 PyAutoGUI 调用。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))


async def execute_desktop(action: PlannedAction) -> str | None:
    """执行一条桌面动作。"""
    atype = action.action
    logger.debug(f"[桌面] 执行 {atype.value}: {action.reason[:60]}")

    if atype == ActionType.MOVE_TO:
        x, y = _resolve_coords(action)
        await _run_sync(pyautogui.moveTo, x, y, duration=0.3)
        await _human_pause(0.2, 0.5)

    elif atype in (ActionType.CLICK_AT, ActionType.DOUBLE_CLICK_AT,
                   ActionType.RIGHT_CLICK_AT):
        x, y = _resolve_coords(action)
        await _run_sync(pyautogui.moveTo, x, y, duration=0.2)
        await _human_pause(0.1, 0.2)
        clicks = 2 if atype == ActionType.DOUBLE_CLICK_AT else (action.x or 1)
        button = "right" if atype == ActionType.RIGHT_CLICK_AT else "left"
        await _run_sync(pyautogui.click, x, y, clicks=clicks, button=button)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.TYPE_TEXT:
        text = action.text or ""
        if not text:
            raise ActionFailed("type_text 需要 text 参数")
        for ch in text:
            await _run_sync(pyautogui.typewrite, ch, interval=random.uniform(0.03, 0.08))
        await _human_pause(0.2, 0.6)

    elif atype == ActionType.HOTKEY:
        keys = action.keys or []
        if not keys:
            raise ActionFailed("hotkey 需要 keys 参数")
        await _run_sync(pyautogui.hotkey, *keys)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.DRAG_TO:
        x, y = _resolve_coords(action)
        duration = action.y or 0.5
        await _run_sync(pyautogui.dragTo, x, y, duration=duration)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.SCROLL:
        amount = action.amount or 5
        if action.direction == "up":
            amount = abs(amount)
        elif action.direction == "down":
            amount = -abs(amount)
        await _run_sync(pyautogui.scroll, amount)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.WAIT:
        secs = action.seconds or 1.0
        await asyncio.sleep(secs)

    elif atype in (ActionType.DONE, ActionType.HUMAN):
        pass

    return None


def _resolve_coords(action: PlannedAction) -> tuple[int, int]:
    """获取 x,y 坐标，裁剪到屏幕范围内。"""
    if action.x is None or action.y is None:
        raise ActionFailed("动作需要 x 和 y 坐标")
    screen_w, screen_h = pyautogui.size()
    x = max(0, min(int(action.x), screen_w - 1))
    y = max(0, min(int(action.y), screen_h - 1))
    return x, y


async def _human_pause(lo: float, hi: float) -> None:
    await asyncio.sleep(random.uniform(lo, hi))
