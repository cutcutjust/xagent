"""Load and render Markdown prompt templates."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template

ROOT = Path(__file__).parent.parent.parent
PROMPTS_DIR = ROOT / "prompts"


@lru_cache(maxsize=64)
def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_prompt(relative_path: str, **kwargs: str) -> str:
    """Load a prompt file and interpolate {variable} placeholders."""
    full = PROMPTS_DIR / relative_path
    raw = _load(full)
    if kwargs:
        raw = Template(raw).safe_substitute(**kwargs)
    return raw
