"""Central configuration — loads from .env and YAML files."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).parent.parent.parent  # sightops/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_api_key: str = Field(..., alias="LLM_API_KEY")
    llm_base_url: str = Field(
        "https://dashscope.aliyuncs.com/compatible-mode/v1", alias="LLM_BASE_URL"
    )
    llm_model: str = Field("qwen3.6-plus", alias="LLM_MODEL")
    llm_vision_model: str = Field("qwen3.6-plus", alias="LLM_VISION_MODEL")
    llm_max_tokens: int = Field(4096, alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(0.7, alias="LLM_TEMPERATURE")

    # Notion
    notion_token: str = Field("", alias="NOTION_TOKEN")
    notion_research_db_id: str = Field("", alias="NOTION_RESEARCH_DB_ID")
    notion_template_db_id: str = Field("", alias="NOTION_TEMPLATE_DB_ID")
    notion_draft_db_id: str = Field("", alias="NOTION_DRAFT_DB_ID")

    # Assets
    assets_dir: str = Field("~/ai-content-assets", alias="ASSETS_DIR")

    # App
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    data_dir: str = Field("./data", alias="DATA_DIR")

    # Desktop
    desktop_max_cycles: int = Field(20, alias="DESKTOP_MAX_CYCLES")

    @property
    def assets_path(self) -> Path:
        return Path(self.assets_dir).expanduser()

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = ROOT / self.data_dir
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(relative_path: str) -> dict:
    """Load a YAML file relative to the project root."""
    return yaml.safe_load((ROOT / relative_path).read_text())
