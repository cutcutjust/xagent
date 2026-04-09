"""Task / run tracking schemas."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


class TaskKind(str, Enum):
    RESEARCH = "research"
    ANALYSIS = "analysis"
    WRITING = "writing"
    PUBLISHING = "publishing"


class TaskRecord(BaseModel):
    task_id: str
    kind: TaskKind
    platform: str = "x"
    status: TaskStatus = TaskStatus.PENDING
    params: dict[str, Any] = {}
    result: dict[str, Any] = {}
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
