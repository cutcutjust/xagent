"""Vision-based action planner — outputs screen coordinates for desktop control."""
from __future__ import annotations

import json

from app.llm.client import vision_chat
from app.schemas.action import ActionPlan, ObservationResult

_SYSTEM = """You are controlling a macOS desktop by looking at screenshots.
Given a full-screen screenshot and a task, output a JSON action plan.

Available actions:
  move_to, click_at, double_click_at, right_click_at, type_text, hotkey, drag_to, scroll, wait, done, human

IMPORTANT: All coordinates (x, y) are in pixels.
  - (0,0) = top-left corner
  - x increases right, y increases down
  - Use the center of the target element as the coordinate
  - Screen dimensions are provided — stay within bounds

Return ONLY valid JSON:
{
  "steps": [
    {
      "action": "<action_type>",
      "reason": "<why>",
      "x": <int or null>,
      "y": <int or null>,
      "description": "<target element description>",
      "text": "<for type_text>",
      "keys": ["<for hotkey>"],
      "direction": "<scroll: up|down>",
      "amount": <scroll amount>,
      "seconds": <wait seconds>
    }
  ],
  "confidence": 0.9,
  "notes": ""
}"""


async def plan_desktop_actions(obs: ObservationResult) -> ActionPlan:
    """Get next action plan from vision model."""
    prompt = _build_prompt(obs)
    raw = await vision_chat(
        text_prompt=prompt,
        image_path=obs.screenshot_path,
        max_tokens=1024,
    )

    try:
        data = json.loads(_extract_json(raw))
        return ActionPlan(**data)
    except Exception as e:
        return ActionPlan(
            steps=[],
            confidence=0.0,
            notes=f"parse error: {e}\n{raw[:200]}",
        )


def _build_prompt(obs: ObservationResult) -> str:
    parts = [
        f"TASK: {obs.task_description}",
        f"SCREEN: {obs.screen_width}x{obs.screen_height}",
    ]
    if obs.previous_action_summary:
        parts.append(f"PREVIOUS: {obs.previous_action_summary}")
    parts.append("\nLook at the screenshot. Plan the next 1-3 steps.")
    return _SYSTEM + "\n\n" + "\n".join(parts)


def _extract_json(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    start = text.find("{")
    end = text.rfind("}") + 1
    return text[start:end] if start != -1 else text
