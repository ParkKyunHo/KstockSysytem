"""In-process async task registry (09_API_SPEC §5.4 + §9.6 + §9.7).

This is intentionally a tiny in-memory placeholder; P5.4.6 swaps it for
the real trading-engine task bus. The shape matches PRD §9.6 so the
frontend already works against this stub.
"""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


class TaskType(str, enum.Enum):
    RECONCILIATION = "RECONCILIATION"
    BOX_ENTRY_MISS_AUDIT = "BOX_ENTRY_MISS_AUDIT"
    REPORT_GENERATION = "REPORT_GENERATION"


class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class TaskRecord:
    id: UUID
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class TaskRegistry:
    def __init__(self) -> None:
        self._items: dict[UUID, TaskRecord] = {}
        self._lock = asyncio.Lock()

    def create(
        self,
        task_type: TaskType,
        *,
        status: TaskStatus = TaskStatus.RUNNING,
    ) -> TaskRecord:
        rec = TaskRecord(
            id=uuid4(),
            type=task_type,
            status=status,
            started_at=datetime.now(timezone.utc),
        )
        self._items[rec.id] = rec
        return rec

    def get(self, task_id: UUID) -> TaskRecord | None:
        return self._items.get(task_id)

    async def update(
        self,
        task_id: UUID,
        *,
        status: TaskStatus | None = None,
        progress: int | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> TaskRecord | None:
        async with self._lock:
            rec = self._items.get(task_id)
            if rec is None:
                return None
            if status is not None:
                rec.status = status
                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    rec.completed_at = datetime.now(timezone.utc)
            if progress is not None:
                rec.progress = progress
            if result is not None:
                rec.result = result
            if error is not None:
                rec.error = error
            return rec


task_registry = TaskRegistry()
