from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

JobState = Literal["pending", "running", "succeeded", "failed"]

JobHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class JobStatus(BaseModel):
    """The dashboard-facing view of a background job's current state."""

    job_id: str
    job_type: str
    guild_id: int | None = None
    state: JobState
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class JobQueue(Protocol):
    """Bridges "the dashboard asked for a long-running operation" to
    "some worker process eventually does it" -- for work that doesn't
    belong on a request/response cycle (bulk moderation actions, exports,
    scheduled cleanups), as opposed to `Transport.request()`, which is
    for cheap, synchronous, sub-second RPCs (member lookups, command
    status).

    Deliberately not conflated with `Transport`: a job can take minutes,
    should survive the enqueuing process restarting, and needs a
    queryable status a client can poll -- none of which `Transport`'s
    fire-and-forget events or short-timeout RPC model are for. Written
    only against this Protocol (never a concrete backend), the same way
    auth/authz/commands are written only against `Transport` -- so the
    same dashboard code works whether jobs run in-process
    (`InProcessJobQueue`) or are picked up by an entirely separate worker
    process/machine (`RedisJobQueue`).

    Unlike `Transport.register_handler` (exactly one handler per command,
    by design), any number of processes may `register_worker()` the same
    `job_type` here and run `start()` -- that's the whole point of a job
    queue: horizontally scale the workers, and whichever is free next
    picks up the next job. No two workers ever process the same job.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def register_worker(self, job_type: str, handler: JobHandler) -> None: ...

    async def enqueue(
        self, job_type: str, payload: dict[str, Any], *, guild_id: int | None = None
    ) -> JobStatus: ...

    async def get_status(self, job_id: str) -> JobStatus | None: ...
