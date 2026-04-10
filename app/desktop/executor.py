"""PyAutoGUI 全局动作执行器 — 人类行为模拟。"""
from __future__ import annotations

import asyncio
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor

import pyautogui

from app.core.errors import ActionFailed
from app.core.logger import logger
from app.schemas.action import ActionType, PlannedAction

_executor = ThreadPoolExecutor(max_workers=1)

# 人类行为参数
_MOVE_JITTER = 3       # 鼠标移动随机偏移 ±3px
_TYPE_INTERVAL = (0.02, 0.10)  # 打字间隔范围（秒）


async def _run_sync(fn, *args, **kwargs):
    """在后台线程运行阻塞的 PyAutoGUI 调用。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))


async def execute_desktop(action: PlannedAction) -> str | None:
    """执行一条桌面动作。"""
    atype = action.action
    reason = (action.reason or "")[:60]
    logger.debug(f"[桌面] 执行 {atype.value}: {reason}")

    if atype == ActionType.MOVE_TO:
        x, y = _resolve_coords(action)
        await _run_sync(_move_human_like, x, y)
        await _human_pause(0.2, 0.5)

    elif atype in (ActionType.CLICK_AT, ActionType.DOUBLE_CLICK_AT,
                   ActionType.RIGHT_CLICK_AT, ActionType.TRIPLE_CLICK_AT):
        x, y = _resolve_coords(action)
        await _run_sync(_move_human_like, x, y)
        await _human_pause(0.1, 0.2)
        if atype == ActionType.DOUBLE_CLICK_AT:
            clicks = 2
        elif atype == ActionType.TRIPLE_CLICK_AT:
            clicks = 3
        else:
            clicks = action.click_count or 1
        button = "right" if atype == ActionType.RIGHT_CLICK_AT else "left"
        await _run_sync(pyautogui.click, x, y, clicks=clicks, button=button)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.TYPE_TEXT:
        text = action.text or ""
        if not text:
            raise ActionFailed("type_text 需要 text 参数")
        for ch in text:
            interval = random.uniform(*_TYPE_INTERVAL)
            # 偶尔插入更长停顿（模拟思考）
            if random.random() < 0.03:
                interval += random.uniform(0.2, 0.5)
            await _run_sync(pyautogui.typewrite, ch, interval=interval)
        await _human_pause(0.2, 0.6)

    elif atype == ActionType.HOTKEY:
        keys = action.keys or []
        if not keys:
            raise ActionFailed("hotkey 需要 keys 参数")
        await _run_sync(pyautogui.hotkey, *keys)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.DRAG_TO:
        x, y = _resolve_coords(action)
        duration = action.seconds or action.dx or 0.5
        sx, sy = pyautogui.position()
        await _run_sync(pyautogui.drag, x - sx, y - sy, duration=duration)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.DRAG_BY:
        dx = action.dx or 0
        dy = action.dy or 0
        duration = action.seconds or 0.5
        await _run_sync(pyautogui.drag, dx, dy, duration=duration)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.SCROLL:
        amount = action.amount or 5
        if action.direction == "up":
            amount = abs(amount)
        elif action.direction == "down":
            amount = -abs(amount)
        await _run_sync(pyautogui.scroll, amount)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.SCROLL_AT:
        x, y = _resolve_coords(action)
        amount = action.amount or 5
        if action.direction == "up":
            amount = abs(amount)
        elif action.direction == "down":
            amount = -abs(amount)
        await _run_sync(pyautogui.moveTo, x, y, duration=0.2)
        await _human_pause(0.1, 0.2)
        await _run_sync(pyautogui.scroll, amount)
        await _human_pause(0.3, 0.8)

    elif atype == ActionType.WAIT:
        secs = action.seconds or 1.0
        await asyncio.sleep(secs)

    elif atype == ActionType.SCREENSHOT:
        pass  # handled by the agent loop

    elif atype in (ActionType.DONE, ActionType.HUMAN):
        pass

    return None


def _move_human_like(x: int, y: int, duration: float | None = None) -> None:
    """带贝塞尔曲线 + 随机抖动的拟人鼠标移动。"""
    # 自适应速度：远距离移动更慢
    cx, cy = pyautogui.position()
    dist = math.hypot(x - cx, y - cy)
    if duration is None:
        duration = max(0.15, min(0.6, dist / 2000))  # 0.15-0.6s 自适应

    # 随机抖动
    tx = x + random.randint(-_MOVE_JITTER, _MOVE_JITTER)
    ty = y + random.randint(-_MOVE_JITTER, _MOVE_JITTER)

    # 随机中间点模拟人类非直线路径
    mid_x = (cx + tx) / 2 + random.randint(-20, 20)
    mid_y = (cy + ty) / 2 + random.randint(-20, 20)

    # 二次贝塞尔曲线插值
    steps = max(10, int(duration * 60))
    for i in range(steps + 1):
        t = i / steps
        # 二次贝塞尔: (1-t)²*P0 + 2(1-t)t*P1 + t²*P2
        px = (1-t)**2 * cx + 2*(1-t)*t * mid_x + t**2 * tx
        py = (1-t)**2 * cy + 2*(1-t)*t * mid_y + t**2 * ty
        pyautogui.moveTo(px + random.uniform(-1, 1), py + random.uniform(-1, 1))
        time.sleep(duration / steps)


def _resolve_coords(action: PlannedAction) -> tuple[int, int]:
    """将 1000x1000 归一化坐标映射到实际屏幕像素坐标。"""
    if action.x is None or action.y is None:
        raise ActionFailed(f"动作 {action.action.value} 需要 x 和 y 坐标")
    screen_w, screen_h = pyautogui.size()
    x = max(0, min(int(action.x / 1000 * screen_w), screen_w - 1))
    y = max(0, min(int(action.y / 1000 * screen_h), screen_h - 1))
    return x, y


async def _human_pause(lo: float, hi: float) -> None:
    await asyncio.sleep(random.uniform(lo, hi))
