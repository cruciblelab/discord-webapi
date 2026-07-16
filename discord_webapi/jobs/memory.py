from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from discord_webapi.jobs.base import JobHandler, JobState, JobStatus

logger = logging.getLogger("discord_webapi.jobs.memory")


class InProcessJobQueue:
    """Default JobQueue: zero extra infrastructure, jobs run as asyncio
    tasks in this same process. `concurrency` worker "loops" pull job ids
    off one shared `asyncio.Queue`, so this already gives the same
    competing-consumer behavior `RedisJobQueue` gives across processes --
    just bounded to this one process instead of scaled across machines.
    """

    def __init__(self, *, concurrency: int = 4) -> None:
        self._concurrency = concurrency
        self._handlers: dict[str, JobHandler] = {}
        self._statuses: dict[str, JobStatus] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._worker_loop()) for _ in range(self._concurrency)
        ]

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._workers = []

    def register_worker(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def enqueue(
        self, job_type: str, payload: dict[str, Any], *, guild_id: int | None = None
    ) -> JobStatus:
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        status = JobStatus(
            job_id=job_id,
            job_type=job_type,
            guild_id=guild_id,
            state="pending",
            payload=payload,
            created_at=now,
            updated_at=now,
        )
        self._statuses[job_id] = status
        await self._queue.put(job_id)
        return status

    async def get_status(self, job_id: str) -> JobStatus | None:
        return self._statuses.get(job_id)

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            await self._run_job(job_id)

    async def _run_job(self, job_id: str) -> None:
        status = self._statuses.get(job_id)
        if status is None:
            return  # pragma: no cover -- can't happen, enqueue always sets this first

        handler = self._handlers.get(status.job_type)
        if handler is None:
            error = f"No worker registered for job_type {status.job_type!r}"
            self._update(job_id, state="failed", error=error)
            return

        self._update(job_id, state="running")
        try:
            result = await handler(status.payload)
        except Exception as exc:
            logger.exception("Job %s (%s) failed", job_id, status.job_type)
            self._update(job_id, state="failed", error=str(exc))
        else:
            self._update(job_id, state="succeeded", result=result)

    def _update(
        self,
        job_id: str,
        *,
        state: JobState,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        current = self._statuses[job_id]
        self._statuses[job_id] = current.model_copy(
            update={
                "state": state,
                "result": result,
                "error": error,
                "updated_at": datetime.now(UTC),
            }
        )
