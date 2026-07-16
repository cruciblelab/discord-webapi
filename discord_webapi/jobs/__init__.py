from typing import TYPE_CHECKING

from discord_webapi.jobs.api import EnqueueJobRequest, build_jobs_router
from discord_webapi.jobs.base import JobHandler, JobQueue, JobState, JobStatus
from discord_webapi.jobs.memory import InProcessJobQueue
from discord_webapi.jobs.worker import run_worker

if TYPE_CHECKING:
    from discord_webapi.jobs.redis import RedisJobQueue

__all__ = [
    "EnqueueJobRequest",
    "InProcessJobQueue",
    "JobHandler",
    "JobQueue",
    "JobState",
    "JobStatus",
    "RedisJobQueue",
    "build_jobs_router",
    "run_worker",
]


def __getattr__(name: str) -> object:
    # RedisJobQueue needs the optional `redis` extra (`discord-webapi[redis]`)
    # -- imported lazily so the base package never requires it.
    if name == "RedisJobQueue":
        from discord_webapi.jobs.redis import RedisJobQueue

        return RedisJobQueue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
