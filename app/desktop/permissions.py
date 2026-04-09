"""Check macOS permissions required for desktop automation."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console

console = Console()


def check_screen_recording() -> bool:
    """Verify Screen Recording permission."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            test_path = f.name
        result = subprocess.run(
            ["screencapture", "-x", test_path],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            return False
        size = Path(test_path).stat().st_size
        Path(test_path).unlink(missing_ok=True)
        return size > 0
    except Exception:
        return False


def check_accessibility() -> bool:
    """Verify Accessibility permission."""
    try:
        import pyautogui
        pos = pyautogui.position()
        return pos.x >= 0 and pos.y >= 0
    except Exception:
        return False


def check_all_permissions() -> bool:
    all_ok = True

    if not check_screen_recording():
        all_ok = False
        console.print("\n[bold red]✗ Screen Recording 权限未授予[/bold red]")
        console.print(
            "[yellow]前往: 系统设置 > 隐私与安全性 > 屏幕录制 > 启用 终端/Terminal[/yellow]\n"
        )

    if not check_accessibility():
        all_ok = False
        console.print("\n[bold red]✗ Accessibility 权限未授予[/bold red]")
        console.print(
            "[yellow]前往: 系统设置 > 隐私与安全性 > 辅助功能 > 启用 终端/Terminal[/yellow]\n"
        )

    if not all_ok:
        console.print("[dim]授予权限后，需退出并重新打开 Terminal 才能生效。[/dim]")
        sys.exit(1)

    console.print("[bold green]✓ 所有权限检查通过[/bold green]")
    return True
