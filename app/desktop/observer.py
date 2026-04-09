"""Full-screen screenshot via macOS screencapture."""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pyautogui

from app.core.config import get_settings
from app.schemas.action import ObservationResult


async def observe_desktop(
    task_description: str = "",
    previous_action_summary: str = "",
) -> ObservationResult:
    """全屏截图并返回观察结果。"""
    s = get_settings()
    shot_dir = s.data_path / "desktop_screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    shot_path = shot_dir / f"obs_{ts}.png"

    subprocess.run(
        ["screencapture", "-x", str(shot_path)],
        check=True, capture_output=True,
    )

    screen_w, screen_h = pyautogui.size()

    return ObservationResult(
        screenshot_path=str(shot_path),
        screen_width=screen_w,
        screen_height=screen_h,
        task_description=task_description,
        previous_action_summary=previous_action_summary,
    )
