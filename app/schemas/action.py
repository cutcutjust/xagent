"""Vision action types — the whitelist the AI can plan."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ActionType(str, Enum):
    MOVE_TO = "move_to"
    CLICK_AT = "click_at"
    DOUBLE_CLICK_AT = "double_click_at"
    RIGHT_CLICK_AT = "right_click_at"
    TRIPLE_CLICK_AT = "triple_click_at"
    TYPE_TEXT = "type_text"
    HOTKEY = "hotkey"
    DRAG_TO = "drag_to"
    DRAG_BY = "drag_by"
    SCROLL = "scroll"
    SCROLL_AT = "scroll_at"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    DONE = "done"
    HUMAN = "human"


class PlannedAction(BaseModel):
    """A single action step output by the planner."""

    action: ActionType
    reason: str = ""
    x: float | None = None
    y: float | None = None
    dx: float | None = None
    dy: float | None = None
    description: str | None = None
    text: str | None = None
    keys: list[str] | None = None
    direction: str | None = None
    amount: int | None = None
    seconds: float | None = None
    message: str | None = None
    click_count: int | None = None


class ActionPlan(BaseModel):
    """Full plan returned by the action planner."""

    steps: list[PlannedAction]
    confidence: float = 1.0
    notes: str = ""


class PageState(BaseModel):
    """Understanding of the current screen state."""
    app_name: str = ""
    page_type: str = ""
    visible_elements: list[str] = []
    url_visible: str = ""
    errors_or_dialogs: list[str] = []
    is_loading: bool = False
    confidence: float = 1.0


class VerificationResult(BaseModel):
    """Result of action verification."""
    success: bool
    explanation: str = ""
    retry_suggested: bool = False


class ExecutionResult(BaseModel):
    """Final result of a ComputerAgent.run() call."""
    status: str
    actions: list[PlannedAction]
    notes: str = ""


class ObservationResult(BaseModel):
    """Full-screen observation data fed to the action planner."""

    screenshot_path: str
    screen_width: int = 0
    screen_height: int = 0
    task_description: str = ""
    previous_action_summary: str = ""
    extra: dict[str, Any] = {}
