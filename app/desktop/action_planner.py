"""Vision-based action planner — loads prompt from template file."""
from __future__ import annotations

import json
from pathlib import Path

from app.llm.client import vision_chat
from app.schemas.action import ActionPlan, ObservationResult

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _load_prompt(name: str, **variables) -> str:
    """Load a prompt template and interpolate variables."""
    path = PROMPTS_DIR / "vision" / f"{name}.md"
    template = path.read_text()
    for key, value in variables.items():
        template = template.replace(f"${key}", str(value))
    return template


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
        if "steps" in data:
            return ActionPlan(**data)
        return ActionPlan(
            steps=[],
            confidence=data.get("confidence", 0.0),
            notes=json.dumps(data, ensure_ascii=False)[:500],
        )
    except Exception as e:
        return ActionPlan(
            steps=[],
            confidence=0.0,
            notes=f"parse error: {e}\n{raw[:200]}",
        )


def _build_prompt(obs: ObservationResult) -> str:
    system = _load_prompt(
        "decide_next_action",
        task_description=obs.task_description,
        screen_size=f"{obs.screen_width}x{obs.screen_height}",
        screen_width=obs.screen_width,
        screen_height=obs.screen_height,
        previous_action_summary=obs.previous_action_summary or "Start",
    )
    parts = [
        f"TASK: {obs.task_description}",
        f"SCREEN: {obs.screen_width}x{obs.screen_height}",
    ]
    if obs.previous_action_summary:
        parts.append(f"PREVIOUS: {obs.previous_action_summary}")
    parts.append("\nLook at the screenshot. Plan the next 1-3 steps.")
    return system + "\n\n" + "\n".join(parts)


def _extract_json(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    start = text.find("{")
    end = text.rfind("}") + 1
    return text[start:end] if start != -1 else text
