"""纯视觉桌面控制 Agent — see → think → act → verify 循环。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pyautogui

from app.core.errors import HumanReviewRequired
from app.core.logger import logger
from app.desktop.executor import execute_desktop
from app.desktop.observer import observe_desktop
from app.llm.client import vision_chat
from app.schemas.action import ActionPlan, ActionType, ExecutionResult, PlannedAction

# ── 系统提示词 ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are controlling a macOS desktop by looking at screenshots. You operate exactly like a human would: look at the screen, identify what application and page is visible, find the UI element you need, and use mouse clicks + keyboard to interact.

## Available Actions
| Action | Parameters | When to use |
|--------|-----------|-------------|
| move_to | x, y, description | Move mouse to element |
| click_at | x, y, description | Click a button/link/field |
| double_click_at | x, y, description | Double-click a file/folder |
| triple_click_at | x, y, description | Triple-click to select paragraph |
| right_click_at | x, y, description | Right-click for context menu |
| type_text | text | Type text into a focused field |
| hotkey | keys: ["cmd","l"] | Keyboard shortcut |
| drag_to | x, y, reason | Drag from current position |
| drag_by | dx, dy, reason | Drag by offset (e.g. scroll bar) |
| scroll | direction: up/down, amount | Scroll at current position |
| scroll_at | x, y, direction, amount | Scroll at specific position |
| wait | seconds: 2.0 | Wait for page load |
| done | - | Task is complete |
| human | message | Need human help |

## macOS Keyboard Shortcuts Reference
- Cmd+Space: Spotlight search
- Cmd+Tab: Switch applications
- Cmd+L: Focus browser address bar
- Cmd+A: Select all text
- Cmd+C/V/X: Copy/Paste/Cut
- Cmd+W: Close current tab/window
- Cmd+T: New browser tab
- Cmd+R: Refresh page
- Cmd+[: Go back in browser history
- Cmd+]: Go forward in browser history
- Page Down / Page Up / Space: Scroll page
- Escape: Close dialog / cancel
- Enter/Return: Confirm / submit
- Tab: Focus next field
- Arrow keys: Navigate

## Rules
1. Look at the screenshot FIRST. Identify what app is focused and what page/state it shows.
2. Output coordinates in pixels. (0,0) = top-left. x increases right, y increases down.
3. Stay within screen bounds. Use element centers as click targets.
4. Be human-like: natural timing, don't rush between steps.
5. If the page is loading, use "wait" action.
6. If stuck (pop-ups, dialogs you can't handle), use "human" action.
7. If the task is done, use "done" action.
8. NEVER generate more than 3 steps at once.
9. Output ONLY valid JSON.

## Output Format
{
  "observation": {
    "app_name": "Safari",
    "page_type": "x_search_results",
    "visible_elements": ["search_box", "post_1", "post_2"],
    "url_visible": "x.com/search?q=AI",
    "errors_or_dialogs": [],
    "is_loading": false,
    "confidence": 0.9
  },
  "steps": [
    {
      "action": "click_at",
      "reason": "Click the search box to focus it",
      "x": 900,
      "y": 120,
      "description": "Search box in top-right area"
    }
  ],
  "confidence": 0.9,
  "notes": ""
}"""


# ── ComputerAgent ────────────────────────────────────────────────────────

class ComputerAgent:
    """Pure vision-based desktop controller: see -> think -> act -> verify -> repeat."""

    def __init__(
        self,
        *,
        max_cycles: int = 30,
        max_stuck_cycles: int = 5,
        stop_event: object = None,
    ):
        self.max_cycles = max_cycles
        self.max_stuck_cycles = max_stuck_cycles
        self._stop_event = stop_event
        self._history: list[str] = []
        self._actions_executed: list[PlannedAction] = []
        self._last_actions: list[str] = []  # for stuck detection

    async def run(
        self,
        task: str,
        *,
        context: dict | None = None,
    ) -> ExecutionResult:
        """
        Main entry point. Runs the full see-think-act-verify loop.

        Args:
            task: Human-language description of what to accomplish
            context: Optional domain-specific guidance

        Returns:
            ExecutionResult with status and actions taken
        """
        logger.info(f"[ComputerAgent] Starting task: {task}")

        for cycle in range(1, self.max_cycles + 1):
            # Check stop event (for external cancellation)
            if self._stop_event and self._stop_event.is_set():
                logger.info("[ComputerAgent] Stop event triggered")
                return ExecutionResult(
                    status="cancelled",
                    actions=self._actions_executed,
                    notes="Stopped by external event",
                )

            # ── PHASE 1: SEE ──
            obs = await observe_desktop(
                task_description=task,
                previous_action_summary=" | ".join(self._history[-5:]) if self._history else "Start",
            )

            # ── PHASE 2: THINK ──
            plan = await self._observe_and_decide(obs, task, context)

            # Check terminal states
            if self._has_done_action(plan):
                logger.info(f"[ComputerAgent] Task done after {cycle} cycles")
                return ExecutionResult(
                    status="done",
                    actions=self._actions_executed,
                    notes=plan.notes,
                )

            if self._has_human_action(plan):
                msg = self._get_human_message(plan)
                logger.warning(f"[ComputerAgent] Human required: {msg}")
                raise HumanReviewRequired(msg)

            # Stuck detection
            if self._is_stuck(plan):
                logger.warning(f"[ComputerAgent] Stuck after {cycle} cycles")
                raise HumanReviewRequired(
                    f"Stuck after {cycle} cycles. Last actions: {self._last_actions[-3:]}. "
                    f"Notes: {plan.notes}"
                )

            if not plan.steps:
                logger.warning(f"[ComputerAgent] Cycle {cycle}: empty plan")
                if "done" in plan.notes.lower() or "完成" in plan.notes.lower():
                    return ExecutionResult(
                        status="done",
                        actions=self._actions_executed,
                        notes=plan.notes,
                    )
                # Add a scroll to explore
                plan.steps = [PlannedAction(
                    action=ActionType.SCROLL,
                    direction="down",
                    amount=10,
                    reason="No action planned, scrolling to explore",
                )]

            # ── PHASE 3: ACT ──
            for step in plan.steps:
                if step.action in (ActionType.DONE,):
                    return ExecutionResult(
                        status="done",
                        actions=self._actions_executed,
                        notes=step.reason or plan.notes,
                    )
                if step.action == ActionType.HUMAN:
                    raise HumanReviewRequired(step.message or step.reason)
                if step.action == ActionType.SCREENSHOT:
                    continue  # Already captured in SEE phase

                try:
                    await execute_desktop(step)
                    self._actions_executed.append(step)
                    action_desc = f"{step.action.value}: {step.reason or ''}"
                    self._history.append(action_desc)
                    self._last_actions.append(action_desc)
                    # Keep last N actions for stuck detection
                    if len(self._last_actions) > 10:
                        self._last_actions = self._last_actions[-10:]
                except Exception as e:
                    logger.warning(f"[ComputerAgent] Execution failed: {e}")
                    self._history.append(f"FAIL: {step.action.value} - {e}")

            # ── PHASE 4: VERIFY ── (implicit in next cycle's SEE)
            # The next cycle will take a new screenshot and the model will
            # naturally verify by comparing expected vs actual state.
            # Add a small delay for page rendering
            await asyncio.sleep(0.5)

        logger.warning(f"[ComputerAgent] Max cycles ({self.max_cycles}) reached")
        return ExecutionResult(
            status="max_cycles",
            actions=self._actions_executed,
            notes=f"Reached max cycles ({self.max_cycles})",
        )

    async def _observe_and_decide(
        self,
        obs,
        task: str,
        context: dict | None = None,
    ) -> ActionPlan:
        """Single LLM call: observe page state + decide next actions."""
        prompt_parts = [
            f"TASK: {task}",
            f"SCREEN: {obs.screen_width}x{obs.screen_height}",
        ]
        if context:
            parts = [f"{k}: {v}" for k, v in context.items()]
            prompt_parts.append("CONTEXT: " + " | ".join(parts))
        if self._history:
            prompt_parts.append(f"HISTORY: {' | '.join(self._history[-5:])}")
        prompt_parts.append("\nLook at the screenshot. Analyze the current state and decide the next 1-3 steps.")

        full_prompt = _SYSTEM_PROMPT + "\n\n" + "\n".join(prompt_parts)

        raw = await vision_chat(
            text_prompt=full_prompt,
            image_path=obs.screenshot_path,
            max_tokens=1024,
        )

        try:
            data = json.loads(_extract_json(raw))
            # Handle nested observation + plan structure
            if "steps" in data:
                return ActionPlan(**data)
            # Handle combined observation + plan structure
            if "plan" in data:
                return ActionPlan(**data["plan"])
            return ActionPlan(
                steps=[],
                confidence=data.get("confidence", 0.0),
                notes=json.dumps(data, ensure_ascii=False)[:500],
            )
        except Exception as e:
            logger.warning(f"[ComputerAgent] Plan parse error: {e}")
            return ActionPlan(
                steps=[],
                confidence=0.0,
                notes=f"parse error: {e}\n{raw[:200]}",
            )

    def _has_done_action(self, plan: ActionPlan) -> bool:
        """Check if the plan contains a 'done' action."""
        if not plan.steps:
            return False
        return any(s.action == ActionType.DONE for s in plan.steps)

    def _has_human_action(self, plan: ActionPlan) -> bool:
        """Check if the plan requires human intervention."""
        if not plan.steps:
            return False
        return any(s.action == ActionType.HUMAN for s in plan.steps)

    def _get_human_message(self, plan: ActionPlan) -> str:
        """Extract the human help message from the plan."""
        for s in plan.steps:
            if s.action == ActionType.HUMAN:
                return s.message or s.reason
        return plan.notes or "Human intervention required"

    def _is_stuck(self, plan: ActionPlan) -> bool:
        """Detect if the agent is stuck (repeating same actions)."""
        if not plan.steps:
            return False
        current = f"{plan.steps[0].action.value}:{plan.steps[0].description or ''}"
        # Check if the same action has been repeated too many times
        if self._last_actions.count(current) >= self.max_stuck_cycles:
            return True
        # Check low confidence repeatedly
        if plan.confidence < 0.3 and len(self._history) > 10:
            recent_fails = sum(1 for h in self._history[-10:] if "FAIL" in h)
            if recent_fails >= 3:
                return True
        return False


# ── Helpers ───────────────────────────────────────────────────────────────

def _extract_json(text: str) -> str:
    """Extract JSON from LLM response."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1:
        return text[start:end]
    return text
