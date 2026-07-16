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

DEFAULT_NAMESPACE = "discord_webapi"


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
    "wire up your handlers, then start" contract). Calling it after
    `start()` raises `RuntimeError` rather than silently never picking up
    the new job_type.

    **Multi-tenant Redis**: same consideration as `RedisTransport` -- pass
    a distinct `namespace=` per otherwise-unrelated deployment sharing one
    Redis instance/cluster, so their queue/status keys never collide. This
    is namespacing, not authentication; see `RedisTransport`'s docstring
    and `docs/GUVENLIK.md` for the actual trust boundary.

    **A worker that crashes mid-job** leaves that job's status stuck at
    "running" forever -- `BLPOP` already atomically removed it from the
    queue, so no other worker will ever pick it up again, and nothing
    times it out on its own. Call `reclaim_stale_jobs(max_age_seconds=...)`
    periodically (your own scheduled task, not something this class does
    automatically) to detect and fail those jobs instead of leaving them
    stuck silently.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        *,
        namespace: str = DEFAULT_NAMESPACE,
        concurrency: int = 4,
        poll_timeout_seconds: float = 1.0,
        result_ttl_seconds: int = 86400,
        **redis_kwargs: Any,
    ) -> None:
        self._redis_url = redis_url
        self._redis_kwargs = redis_kwargs
        self._namespace = namespace
        self._queue_prefix = f"{namespace}:jobs:queue:"
        self._status_prefix = f"{namespace}:jobs:job:"
        self._running_set_key = f"{namespace}:jobs:running"
        self._concurrency = concurrency
        self._poll_timeout_seconds = poll_timeout_seconds
        self._result_ttl_seconds = result_ttl_seconds
        self._redis: Redis | None = None
        self._handlers: dict[str, JobHandler] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._started = False

    def _queue_key(self, job_type: str) -> str:
        return f"{self._queue_prefix}{job_type}"

    def _status_key(self, job_id: str) -> str:
        return f"{self._status_prefix}{job_id}"

    def _require_redis(self) -> Redis:
        # A plain `assert` here is strippable under `python -O`/
        # `PYTHONOPTIMIZE=1`, which would degrade this into an unguarded
        # `AttributeError` on `self._redis` (or a silent no-op) instead of
        # the clear "call start() first" message every caller needs.
        if self._redis is None:
            raise RuntimeError("RedisJobQueue.start() must be called first")
        return self._redis

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
        redis = self._require_redis()
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
        await redis.rpush(self._queue_key(job_type), job_id)
        return status

    async def get_status(self, job_id: str) -> JobStatus | None:
        redis = self._require_redis()
        raw = await redis.get(self._status_key(job_id))
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
        redis = self._require_redis()
        ttl = self._result_ttl_seconds if status.state in ("succeeded", "failed") else None
        await redis.set(self._status_key(status.job_id), status.model_dump_json(), ex=ttl)

    async def _worker_loop(self) -> None:
        redis = self._require_redis()
        keys = [self._queue_key(job_type) for job_type in self._handlers]
        while True:
            popped = await redis.blpop(keys, timeout=self._poll_timeout_seconds)
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
            redis = self._require_redis()
            await redis.rpush(self._queue_key(status.job_type), job_id)
            return

        redis = self._require_redis()
        await self._save(self._with_state(status, state="running"))
        # Tracked separately from the status key itself so a crashed/killed
        # worker's abandoned job can be found later by reclaim_stale_jobs()
        # -- BLPOP already atomically removed this job_id from the queue,
        # so without this there is no record anywhere that anyone was ever
        # working on it; its status would stay "running" forever.
        await redis.sadd(self._running_set_key, job_id)
        try:
            result = await handler(status.payload)
        except Exception as exc:
            logger.exception("Job %s (%s) failed", job_id, status.job_type)
            await self._save(self._with_state(status, state="failed", error=str(exc)))
        else:
            await self._save(self._with_state(status, state="succeeded", result=result))
        finally:
            await redis.srem(self._running_set_key, job_id)

    async def reclaim_stale_jobs(self, *, max_age_seconds: float) -> list[str]:
        """Finds jobs still marked "running" whose status hasn't been
        touched in over `max_age_seconds` -- almost always a worker that
        crashed, was killed, or lost its Redis connection mid-job, since
        `_run_job` always transitions a job to "succeeded"/"failed" in a
        `finally` otherwise. Marks each as "failed" (with a clear error)
        rather than silently re-queuing it for automatic retry: many jobs
        (bulk DMs, mass bans/kicks) are not safe to blindly re-run and may
        have already had a real side effect before the worker died, so the
        decision to retry is left to whoever is watching the dashboard, not
        made silently here.

        Call this periodically yourself (e.g. from a scheduled task
        alongside your worker process) -- nothing calls it automatically.
        Pick `max_age_seconds` comfortably longer than any job you enqueue
        could reasonably take, or a merely-slow (not crashed) job gets
        marked failed while still legitimately running.

        Returns the job ids that were reclaimed.
        """
        redis = self._require_redis()
        raw_ids = await redis.smembers(self._running_set_key)
        now = datetime.now(UTC)
        reclaimed: list[str] = []
        for raw_id in raw_ids:
            job_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            status = await self.get_status(job_id)
            if status is None or status.state != "running":
                # Stale set membership (e.g. this job was already handled
                # and srem() itself is what's missing, or its status key
                # expired) -- nothing to reclaim, just stop tracking it.
                await redis.srem(self._running_set_key, job_id)
                continue
            age = (now - status.updated_at).total_seconds()
            if age <= max_age_seconds:
                continue
            await self._save(
                self._with_state(
                    status,
                    state="failed",
                    error=(
                        f"Reclaimed after {age:.0f}s with no update -- the worker "
                        "likely crashed or was killed mid-job."
                    ),
                )
            )
            await redis.srem(self._running_set_key, job_id)
            reclaimed.append(job_id)
        return reclaimed

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
