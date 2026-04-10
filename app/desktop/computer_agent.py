"""纯视觉桌面控制 Agent — see → think → act → verify 循环。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pyautogui
from rich.console import Console

from app.core.errors import HumanReviewRequired
from app.core.logger import logger
from app.desktop.executor import execute_desktop
from app.desktop.observer import observe_desktop
from app.llm.client import vision_chat
from app.schemas.action import ActionPlan, ActionType, ExecutionResult, PlannedAction

_console = Console()

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
| drag_to | x, y, duration, reason | Drag from current position to x,y |
| drag_by | dx, dy, duration, reason | Drag by offset |
| scroll | direction: up/down, amount | Scroll at current position |
| scroll_at | x, y, direction, amount | Scroll at specific position |
| wait | seconds: 2.0 | Wait for page load |
| done | - | Task is complete |
| human | message | Need human help |

## Coordinate System
- Output coordinates in a 1000x1000 normalized space as integers.
- (0,0) = top-left corner, (1000,1000) = bottom-right corner.
- The system maps these to actual screen pixels automatically.
- x and y MUST be separate numeric fields (not text in description).
- Example: "x": 520, "y": 140 — NOT "description": "(520, 140)"

## Planning Strategy
Think like a researcher, not a robot. Don't follow a rigid script.
1. **Assess the current state** — what page, what's visible, what's hidden.
2. **Plan adaptively** — if metrics aren't visible, scroll to find them. If a comment section is collapsed, click to expand. If an image is present, click to view full size.
3. **Verify after each action** — did the page change as expected? If not, try a different approach.
4. **Explore thoroughly** — for X posts: check replies count, scroll through comments, click images, check retweets/quotes, note view counts.
5. **Be persistent but not stuck** — if something doesn't work after 2 tries, try a different method.

## X Search Rules
- When searching for a user's posts, do NOT use "from:username" — just type the username directly (e.g., "Ox_Miko")
- When searching for topics, just type the keyword (e.g., "mythos")
- After searching, look for the target post in the results. If not visible, scroll down to find it
- When asked to find a specific post by @username, look for posts matching that author in the visible results
- Only return "done" when you have ACTUALLY completed the task (e.g., clicked and opened the target post). Do NOT return "done" just because you searched — the post must be visible and opened

## Opening Applications — ALWAYS Use Spotlight
To open or switch to an application, use Cmd+Space then type the app name:
1. hotkey: keys=["command", "space"] — open Spotlight
2. wait: seconds=0.5
3. type_text: text="Safari"
4. hotkey: keys=["return"]
5. wait: seconds=2.0

Do NOT click dock icons — Spotlight is more reliable.

## Navigating to a URL — ALWAYS Use Address Bar
1. hotkey: keys=["command", "l"] — focus address bar
2. wait: seconds=0.3
3. type_text: text="https://x.com"
4. hotkey: keys=["return"]
5. wait: seconds=3.0

## X (Twitter) Specific Tips
- **Metrics**: Post engagement (likes, reposts, views) are usually visible at the bottom of a post detail page. If not visible, scroll down slightly.
- **Comments/Replies**: Scroll down on a post detail page to see replies. Click "Show more replies" if collapsed.
- **Images**: Click on images in a post to view them full-size. Use back button to return.
- **Search**: If a search shows wrong results, clear the search box and try again with exact username (e.g., "from:AnthropicAI mythos").
- **Author matching**: X usernames may differ from display names. @AnthropicAI is the official account, not @anthropic.com.
- **URL format**: Post URLs are like https://x.com/username/status/1234567890

## macOS Keyboard Shortcuts Reference
- Cmd+Space: Spotlight
- Cmd+Tab: Switch apps
- Cmd+L: Focus address bar
- Cmd+A/C/V/X: Select/Copy/Paste/Cut
- Cmd+W: Close tab
- Cmd+T: New tab
- Cmd+R: Refresh
- Cmd+[: Go back
- Cmd+]: Go forward
- Space/PageDown/PageUp: Scroll
- Escape: Close dialog
- Tab: Focus next element

## Output Format
Output ONLY valid JSON matching this structure:
{
  "observation": {
    "app_name": "Safari",
    "page_type": "x_post_detail",
    "visible_elements": ["post_body", "likes:1858", "views:69K", "comments_section"],
    "url_visible": "x.com/user/status/123",
    "errors_or_dialogs": [],
    "is_loading": false,
    "confidence": 0.9
  },
  "steps": [
    {
      "action": "scroll",
      "reason": "Scroll down to see engagement metrics",
      "direction": "down",
      "amount": 10
    }
  ],
  "confidence": 0.9,
  "notes": ""
}

IMPORTANT:
- Each step's x and y must be integers between 0 and 1000
- Use clear, actionable descriptions
- Plan 1-3 steps that make sense for the current state
- If metrics/data aren't visible, scroll or click to reveal them"""


# ── ComputerAgent ────────────────────────────────────────────────────────

class ComputerAgent:
    """Pure vision-based desktop controller: see -> think -> act -> verify -> repeat."""

    def __init__(
        self,
        *,
        max_cycles: int = 30,
        max_stuck_cycles: int = 3,
        stop_event: object = None,
        verbose: bool = True,
    ):
        self.max_cycles = max_cycles
        self.max_stuck_cycles = max_stuck_cycles
        self._stop_event = stop_event
        self._verbose = verbose
        self._history: list[str] = []
        self._actions_executed: list[PlannedAction] = []
        self._last_actions: list[str] = []
        self._llm_failures: int = 0
        # Full conversation history with screenshot context (like qwen_autogui)
        self._conversation_history: list[dict] = []

    def _log(self, msg: str, style: str = "") -> None:
        """Print to console if verbose."""
        if self._verbose:
            if style:
                _console.print(f"    [{style}]{msg}[/{style}]")
            else:
                _console.print(f"    {msg}")

    def _print_plan(self, plan: ActionPlan) -> None:
        """Print LLM observation and action plan details."""
        # Print observation summary from notes
        if plan.notes and plan.notes.strip():
            # Try to extract observation part (before any step details)
            notes = plan.notes.strip()
            # Only print if it's not too long
            if len(notes) > 200:
                notes = notes[:200] + "..."
            self._log(f"  识别: {notes}", "cyan")

        # Print each planned action with details
        if plan.steps:
            for i, step in enumerate(plan.steps, 1):
                detail = f"[{step.action.value}]"
                # Coords from x/y fields
                if step.x is not None and step.y is not None:
                    detail += f" ({int(step.x)}, {int(step.y)})"
                # Coords from description field (LLM sometimes writes "(x, y)" there)
                elif step.description and step.description.startswith("("):
                    detail += f" {step.description[:20]}"
                if step.text:
                    detail += f" \"{step.text[:40]}{'...' if len(step.text) > 40 else ''}\""
                if step.keys:
                    detail += f" {'+'.join(step.keys)}"
                if step.direction:
                    detail += f" {step.direction}x{step.amount or 5}"
                # Reason (not description) for the reason field
                if step.reason:
                    desc = step.reason[:60] + "..." if len(step.reason) > 60 else step.reason
                    detail += f" — {desc}"
                self._log(f"  计划 {i}: {detail}", "bold yellow")

        if plan.confidence < 1.0:
            self._log(f"  置信度: {plan.confidence:.0%}", "dim")

    async def run(
        self,
        task: str,
        *,
        context: dict | None = None,
        plan_context: dict | None = None,
    ) -> ExecutionResult:
        """
        Main entry point. Runs the full see-think-act-verify loop.

        Args:
            task: The current micro-task description.
            context: Additional context for the LLM (key-value pairs).
            plan_context: Overall research plan awareness. Structure:
                - overall_goal: The end goal of this research session
                - current_step: Which step we're on (e.g., "Step 2/5: Search mythos")
                - completed_steps: List of completed step descriptions
                - next_steps: List of upcoming steps
        """
        logger.info(f"[ComputerAgent] Starting task: {task}")
        self._log(f"[Agent] 任务: {task}", "dim")
        if plan_context:
            self._log(f"[Agent] 计划: {plan_context.get('overall_goal', '')}", "dim")
            self._log(f"[Agent] 当前: {plan_context.get('current_step', '')}", "dim")

        # Reset per-task state (agent is reused across collect calls)
        self._history = []
        self._conversation_history = []
        self._last_actions = []
        self._llm_failures = 0
        self._done_loop_count = 0  # Track consecutive "done without action" cycles

        for cycle in range(1, self.max_cycles + 1):
            # Check stop event
            if self._stop_event and self._stop_event.is_set():
                return ExecutionResult(status="cancelled", actions=self._actions_executed, notes="Stopped")

            # ── PHASE 1: SEE ──
            self._log(f"Cycle {cycle}/{self.max_cycles} — 截图分析...", "dim")
            try:
                obs = await observe_desktop(
                    task_description=task,
                    previous_action_summary=" | ".join(self._history[-5:]) if self._history else "Start",
                )
            except Exception as e:
                self._log(f"截图失败: {e}", "red")
                await asyncio.sleep(2)
                continue

            # ── PHASE 2: THINK ──
            self._log("  LLM 分析中...", "dim")
            plan = None
            max_retries = 2
            for retry in range(max_retries):
                try:
                    plan = await self._observe_and_decide(obs, task, context, plan_context)
                    if plan and plan.steps:
                        break
                    if plan and plan.confidence == 0.0:
                        self._log(f"  LLM 返回空动作计划 (重试 {retry+1}/{max_retries})", "yellow")
                        await asyncio.sleep(1)
                except asyncio.TimeoutError:
                    self._log(f"  LLM 调用超时 (重试 {retry+1}/{max_retries})", "red")
                    await asyncio.sleep(1)
                except Exception as e:
                    self._log(f"  LLM 调用失败: {type(e).__name__}: {e} (重试 {retry+1}/{max_retries})", "red")
                    await asyncio.sleep(1)

            if not plan or (not plan.steps and not plan.notes):
                self._log("  LLM 多次失败，等待后跳过此轮", "red")
                self._llm_failures += 1
                if self._llm_failures >= 3:
                    self._log(f"LLM 连续失败 {self._llm_failures} 次，终止", "red")
                    raise HumanReviewRequired(f"LLM 连续失败 {self._llm_failures} 次，API 可能有问题")
                await asyncio.sleep(2)
                continue

            self._llm_failures = 0  # reset on success

            # ── 输出 LLM 识别和分析计划详情 ──
            self._print_plan(plan)

            # Check terminal states
            if self._has_done_action(plan):
                self._log("  任务完成", "green")
                return ExecutionResult(status="done", actions=self._actions_executed, notes=plan.notes)

            if self._has_human_action(plan):
                msg = self._get_human_message(plan)
                self._log(f"  需要人工: {msg}", "yellow")
                raise HumanReviewRequired(msg)

            if self._is_stuck(plan):
                self._log(f"  卡住了（连续重复动作）", "red")
                raise HumanReviewRequired(
                    f"Stuck after {cycle} cycles. Last actions: {self._last_actions[-3:]}. "
                    f"Notes: {plan.notes}"
                )

            if not plan.steps:
                # Detect "done" loop: LLM keeps saying "task completed" without actual actions
                notes_lower = plan.notes.lower()
                if any(kw in notes_lower for kw in ["done", "completed", "success", "完成", "成功"]):
                    self._done_loop_count += 1
                    if self._done_loop_count >= 2:
                        self._log(f"  LLM 连续 {self._done_loop_count} 次报告完成但无动作，主动退出", "yellow")
                        return ExecutionResult(status="done", actions=self._actions_executed, notes=plan.notes)
                    self._log(f"  无动作计划但报告完成 (计数 {self._done_loop_count}/2)，再等一回合", "yellow")
                    await asyncio.sleep(2)
                    continue
                else:
                    self._done_loop_count = 0  # reset if LLM is actually doing something

                self._log("  无动作计划，滚动尝试", "yellow")
                plan.steps = [PlannedAction(
                    action=ActionType.SCROLL, direction="down", amount=10,
                    reason="No action planned, scrolling to explore",
                )]

            # Print observation
            if plan.notes and plan.notes.strip():
                self._log(f"  识别: {plan.notes[:120]}", "dim")

            # ── PHASE 3: ACT ──
            for step in plan.steps:
                if step.action == ActionType.DONE:
                    self._log(f"  {step.action.value}: {step.reason or ''}", "green")
                    return ExecutionResult(status="done", actions=self._actions_executed, notes=step.reason or plan.notes)
                if step.action == ActionType.HUMAN:
                    raise HumanReviewRequired(step.message or step.reason)
                if step.action == ActionType.SCREENSHOT:
                    continue

                self._log(f"  {step.action.value}: {step.reason or ''}", "dim")
                try:
                    await execute_desktop(step)
                    self._actions_executed.append(step)
                    action_desc = f"{step.action.value}: {step.reason or ''}"
                    self._history.append(action_desc)
                    self._last_actions.append(action_desc)
                    if len(self._last_actions) > 10:
                        self._last_actions = self._last_actions[-10:]
                except Exception as e:
                    self._log(f"  执行失败: {e}", "red")
                    logger.warning(f"[ComputerAgent] Execution failed: {e}")
                    self._history.append(f"FAIL: {step.action.value} - {e}")

            await asyncio.sleep(1)

        self._log(f"达到最大循环次数 ({self.max_cycles})", "yellow")
        return ExecutionResult(status="max_cycles", actions=self._actions_executed, notes=f"Reached max cycles ({self.max_cycles})")

    async def _observe_and_decide(
        self,
        obs,
        task: str,
        context: dict | None = None,
        plan_context: dict | None = None,
    ) -> ActionPlan:
        """Single LLM call with timeout: observe page state + decide next actions.

        Builds a multi-turn conversation with the full screenshot history,
        so the model can see how the screen changed after each action.
        """
        prompt_parts = [
            f"TASK: {task}",
            f"SCREEN: {obs.screen_width}x{obs.screen_height}",
        ]
        if context:
            parts = [f"{k}: {v}" for k, v in context.items()]
            prompt_parts.append("CONTEXT: " + " | ".join(parts))
        if self._history:
            prompt_parts.append(f"EXECUTION HISTORY: {' | '.join(self._history[-5:])}")
        if plan_context:
            goal = plan_context.get("overall_goal", "")
            current = plan_context.get("current_step", "")
            completed = plan_context.get("completed_steps", [])
            next_steps = plan_context.get("next_steps", [])
            plan_lines = ["", "OVERALL PLAN:"]
            for s in completed:
                plan_lines.append(f"  ✓ {s}")
            plan_lines.append(f"→ {current} (CURRENT)")
            for s in next_steps:
                plan_lines.append(f"  → {s}")
            prompt_parts.append("\n".join(plan_lines))
        prompt_parts.append("\nLook at the screenshot. Analyze the current state and decide the next 1-3 steps.")

        full_prompt = "\n".join(prompt_parts)

        # Build conversation history with system prompt + previous turns
        system_msg = {"role": "system", "content": _SYSTEM_PROMPT}
        history = [system_msg] + self._conversation_history

        # Timeout-protected LLM call (60s — normal calls complete in ~8s, but occasional ones take 30s+)
        raw = await asyncio.wait_for(
            vision_chat(text_prompt=full_prompt, image_path=obs.screenshot_path, max_tokens=1024, history_messages=history),
            timeout=60,
        )

        # Append this turn to conversation history (without the image to save tokens)
        self._conversation_history.append({"role": "user", "content": full_prompt})
        self._conversation_history.append({"role": "assistant", "content": raw})
        # Keep last 10 turns to avoid token explosion
        if len(self._conversation_history) > 20:
            self._conversation_history = self._conversation_history[-20:]

        try:
            data = json.loads(_extract_json(raw))
            if "steps" in data:
                plan = ActionPlan(**data)
            elif "plan" in data:
                plan = ActionPlan(**data["plan"])
            else:
                return ActionPlan(
                    steps=[], confidence=data.get("confidence", 0.0),
                    notes=json.dumps(data, ensure_ascii=False)[:500],
                )
            # Normalize steps: fix LLM putting coords in description instead of x/y
            for step in plan.steps:
                _normalize_step(step)
            return plan
        except Exception as e:
            logger.warning(f"[ComputerAgent] Plan parse error: {e}")
            return ActionPlan(
                steps=[], confidence=0.0,
                notes=f"parse error: {e}\n{raw[:200]}",
            )

    def _has_done_action(self, plan: ActionPlan) -> bool:
        if not plan.steps:
            return False
        return any(s.action == ActionType.DONE for s in plan.steps)

    def _has_human_action(self, plan: ActionPlan) -> bool:
        if not plan.steps:
            return False
        return any(s.action == ActionType.HUMAN for s in plan.steps)

    def _get_human_message(self, plan: ActionPlan) -> str:
        for s in plan.steps:
            if s.action == ActionType.HUMAN:
                return s.message or s.reason
        return plan.notes or "Human intervention required"

    def _is_stuck(self, plan: ActionPlan) -> bool:
        """Detect stuck by repeated action type or same description."""
        if not plan.steps:
            return False
        current_action = plan.steps[0].action.value
        # Scroll and wait are exploration actions, don't count as stuck
        if current_action in ("scroll", "wait"):
            return False
        current_desc = plan.steps[0].description or ''
        # Count how many times this action type appeared in history
        type_count = sum(1 for a in self._last_actions if a.startswith(f"{current_action}:"))
        # Need at least 8 repeated same action type to be considered stuck
        if type_count >= max(self.max_stuck_cycles, 8):
            return True
        # Also check if confidence is low AND recent failures are high
        if plan.confidence < 0.3 and len(self._history) > 10:
            recent_fails = sum(1 for h in self._history[-10:] if "FAIL" in h)
            if recent_fails >= 4:
                return True
        return False


# ── Helpers ───────────────────────────────────────────────────────────────

import re as _re


def _normalize_step(step: PlannedAction) -> None:
    """Fix common LLM output issues: coords in description, text in wrong field."""
    desc = step.description or ''
    # Fix 1: Extract coords from description like "(476, 133)" or "(476,133)"
    if step.x is None and step.y is None and desc:
        m = _re.search(r'\((\d+)\s*,\s*(\d+)\)', desc)
        if m:
            step.x = int(m.group(1))
            step.y = int(m.group(2))
    # Fix 2: Extract text for type_text — quoted, instruction, or raw
    if step.action == ActionType.TYPE_TEXT and not step.text and desc:
        # Try double/single quotes first
        m = _re.search(r'"([^"]+)"', desc)
        if not m:
            m = _re.search(r"'([^']+)'", desc)
        if m:
            step.text = m.group(1)
        # Try instruction pattern: "Type X into/in/press..."
        elif _re.match(r'(?i)type\s+', desc):
            # Extract text between "Type" and prepositions
            m2 = _re.search(r'(?i)type\s+(.+?)(?:\s+into|\s+in\s+|\s+to\s+|\s+press|\s+then|$)', desc)
            if m2:
                step.text = m2.group(1).strip().strip('"\'')
            else:
                step.text = desc.strip()
        else:
            step.text = desc.strip()
    # Fix 3: Extract keys from description for hotkey
    if step.action == ActionType.HOTKEY and not step.keys:
        dl = desc.lower().strip()
        # Map common descriptions to actual keys
        for kw, keys in [
            ('command+l', ['command', 'l']),
            ('cmd+l', ['command', 'l']),
            ('address bar', ['command', 'l']),
            ('navigate', ['return']),
            ('press enter', ['return']),
            ('enter', ['return']),
            ('return', ['return']),
            ('escape', ['escape']),
            ('esc', ['escape']),
            ('close', ['escape']),
            ('scroll down', ['down']),
            ('down', ['down']),
            ('scroll up', ['up']),
            ('up', ['up']),
            ('scroll left', ['left']),
            ('left', ['left']),
            ('scroll right', ['right']),
            ('right', ['right']),
            ('tab', ['tab']),
            ('space', ['space']),
            ('page down', ['pagedown']),
            ('page up', ['pageup']),
            ('delete', ['delete']),
            ('backspace', ['backspace']),
        ]:
            if kw in dl:
                step.keys = keys
                break
        # Fallback: if still no keys, use return (most common LLM intent)
        if not step.keys and desc:
            step.keys = ['return']


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
