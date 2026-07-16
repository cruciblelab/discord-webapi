"""JobQueue backed by Redis lists (RPUSH/BLPOP) + a JSON status string per
job. Requires the `discord-webapi[redis]` extra.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from discord_webapi.jobs.base import JobHandler, JobState, JobStatus

logger = logging.getLogger("discord_webapi.jobs.redis")

_QUEUE_PREFIX = "discord_webapi:jobs:queue:"
_STATUS_PREFIX = "discord_webapi:jobs:job:"


def _queue_key(job_type: str) -> str:
    return f"{_QUEUE_PREFIX}{job_type}"


def _status_key(job_id: str) -> str:
    return f"{_STATUS_PREFIX}{job_id}"


class RedisJobQueue:
    """JobQueue for a deployment where jobs are enqueued from one process
    (e.g. the web dashboard) and processed by an entirely separate worker
    process/machine -- unlike `RedisTransport`'s pub/sub RPC (exactly one
    handler may ever answer a given command), Redis lists give proper
    competing-consumer semantics for free: run as many worker processes as
    you want, calling `register_worker()` for the same `job_type` in each,
    and Redis guarantees no two of them ever pop the same job id.

    `register_worker()` must be called before `start()` -- the set of
    queue keys a worker BLPOPs from is fixed at start time (this mirrors
    the memory implementation's -- and `Transport.register_handler`'s --
    "wire up your handlers, then start" contract).
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        *,
        concurrency: int = 4,
        poll_timeout_seconds: float = 1.0,
        result_ttl_seconds: int = 86400,
        **redis_kwargs: Any,
    ) -> None:
        self._redis_url = redis_url
        self._redis_kwargs = redis_kwargs
        self._concurrency = concurrency
        self._poll_timeout_seconds = poll_timeout_seconds
        self._result_ttl_seconds = result_ttl_seconds
        self._redis: Redis | None = None
        self._handlers: dict[str, JobHandler] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._started = False

    async def start(self) -> None:
        self._redis = Redis.from_url(self._redis_url, **self._redis_kwargs)
        self._started = True
        if self._handlers:
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
        self._started = False
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def register_worker(self, job_type: str, handler: JobHandler) -> None:
        if self._started:
            raise RuntimeError(
                "register_worker() called after start() -- the set of queue keys a "
                "worker BLPOPs from is fixed when start() runs, so this handler would "
                "silently never be picked up. Call register_worker() for every "
                "job_type before start()."
            )
        self._handlers[job_type] = handler

    async def enqueue(
        self, job_type: str, payload: dict[str, Any], *, guild_id: int | None = None
    ) -> JobStatus:
        assert self._redis is not None, "call start() before enqueue()"
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
        await self._save(status)  # no TTL yet -- see _save's docstring
        await self._redis.rpush(_queue_key(job_type), job_id)
        return status

    async def get_status(self, job_id: str) -> JobStatus | None:
        assert self._redis is not None, "call start() before get_status()"
        raw = await self._redis.get(_status_key(job_id))
        if raw is None:
            return None
        return JobStatus.model_validate_json(raw)

    async def _save(self, status: JobStatus) -> None:
        """`result_ttl_seconds` only applies once a job reaches a terminal
        state (succeeded/failed) -- it's a "how long to keep the result
        around for polling" cleanup TTL, not an expiry on the job itself.
        Applying it from the very first (pending) write would mean a job
        sitting in the queue longer than the TTL (worker backlog, or all
        workers briefly down) has its status key evicted out from under
        it -- `_run_job` would then find no status for a job_id it just
        popped and silently drop the job with no error surfaced anywhere.
        """
        assert self._redis is not None
        ttl = self._result_ttl_seconds if status.state in ("succeeded", "failed") else None
        await self._redis.set(_status_key(status.job_id), status.model_dump_json(), ex=ttl)

    async def _worker_loop(self) -> None:
        assert self._redis is not None
        keys = [_queue_key(job_type) for job_type in self._handlers]
        while True:
            popped = await self._redis.blpop(keys, timeout=self._poll_timeout_seconds)
            if popped is None:
                continue
            _key, job_id_raw = popped
            job_id = job_id_raw.decode() if isinstance(job_id_raw, bytes) else job_id_raw
            await self._run_job(job_id)

    async def _run_job(self, job_id: str) -> None:
        status = await self.get_status(job_id)
        if status is None:
            # Shouldn't happen in the common case (enqueue always saves
            # status before pushing the job_id, and pending/running writes
            # no longer carry a TTL -- see _save), but Redis can still
            # evict a key under memory pressure (e.g. maxmemory-policy
            # allkeys-lru). Log it rather than silently dropping the job
            # with no trace anywhere.
            logger.warning(
                "Job %s popped from queue but has no status -- its key was likely "
                "evicted (e.g. Redis maxmemory pressure). Dropping it.",
                job_id,
            )
            return

        handler = self._handlers.get(status.job_type)
        if handler is None:
            # A different process's worker already claimed a job_type this
            # one no longer handles (e.g. redeployed with fewer handlers) --
            # put it back for someone else rather than losing it.
            assert self._redis is not None
            await self._redis.rpush(_queue_key(status.job_type), job_id)
            return

        await self._save(self._with_state(status, state="running"))
        try:
            result = await handler(status.payload)
        except Exception as exc:
            logger.exception("Job %s (%s) failed", job_id, status.job_type)
            await self._save(self._with_state(status, state="failed", error=str(exc)))
        else:
            await self._save(self._with_state(status, state="succeeded", result=result))

    @staticmethod
    def _with_state(
        status: JobStatus,
        *,
        state: JobState,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobStatus:
        return status.model_copy(
            update={
                "state": state,
                "result": result,
                "error": error,
                "updated_at": datetime.now(UTC),
            }
        )
