"""LLM client — wraps OpenAI-compatible Qwen3.6-Plus API."""
from __future__ import annotations

import base64
from pathlib import Path

from openai import AsyncOpenAI, OpenAI

from app.core.config import get_settings
from app.core.logger import logger


def _make_client() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)


def _make_sync_client() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)


_client: AsyncOpenAI | None = None
_sync_client: OpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = _make_client()
    return _client


def _get_sync_client() -> OpenAI:
    global _sync_client
    if _sync_client is None:
        _sync_client = _make_sync_client()
    return _sync_client


async def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> str:
    """Simple chat completion — returns the assistant message text."""
    s = get_settings()
    kwargs: dict = dict(
        model=model or s.llm_model,
        messages=messages,
        temperature=temperature if temperature is not None else s.llm_temperature,
        max_tokens=max_tokens or s.llm_max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    client = get_client()
    logger.debug(f"LLM call model={kwargs['model']} msgs={len(messages)}")
    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


async def vision_chat(
    text_prompt: str,
    image_path: str | Path,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Send a screenshot + text prompt to the vision model."""
    s = get_settings()
    img_bytes = Path(image_path).read_bytes()
    b64 = base64.b64encode(img_bytes).decode()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
                {"type": "text", "text": text_prompt},
            ],
        }
    ]
    client = get_client()
    m = model or s.llm_vision_model
    logger.debug(f"Vision call model={m} image={Path(image_path).name}")
    resp = await client.chat.completions.create(
        model=m,
        messages=messages,
        max_tokens=max_tokens or s.llm_max_tokens,
    )
    return resp.choices[0].message.content or ""


def _sync_vision_chat(text_prompt: str, image_path: str | Path, *, model: str | None = None, max_tokens: int | None = None) -> str:
    """Sync version of vision_chat for non-async contexts (e.g. viewer thread)."""
    s = get_settings()
    img_bytes = Path(image_path).read_bytes()
    b64 = base64.b64encode(img_bytes).decode()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": text_prompt},
            ],
        }
    ]
    client = _get_sync_client()
    m = model or s.llm_vision_model
    resp = client.chat.completions.create(model=m, messages=messages, max_tokens=max_tokens or s.llm_max_tokens)
    return resp.choices[0].message.content or ""
