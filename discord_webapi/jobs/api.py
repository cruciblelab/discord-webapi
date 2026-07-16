from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from discord_webapi.authz.dependencies import GuildContext, require_guild_permission
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter
from discord_webapi.dashboard_ratelimit_dependency import rate_limit_dependency
from discord_webapi.jobs.base import JobQueue, JobStatus

_DEFAULT_ENQUEUE_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)


class EnqueueJobRequest(BaseModel):
    payload: dict[str, Any] = {}


def _get_job_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.discord_webapi_job_queue
    return queue


def build_jobs_router(*, enqueue_rate_limiter: TokenBucketLimiter | None = None) -> APIRouter:
    """Dashboard-facing API for background jobs (see `jobs.base.JobQueue`):
    enqueue a long-running operation and poll its status, instead of
    blocking a request/response cycle on it.
    """
    limiter = enqueue_rate_limiter or _DEFAULT_ENQUEUE_LIMITER
    router = APIRouter(prefix="/api/guilds/{guild_id}/jobs", tags=["jobs"])

    @router.post("/{job_type}", status_code=status.HTTP_202_ACCEPTED)
    async def enqueue_job(
        guild_id: int,
        job_type: str,
        body: EnqueueJobRequest,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter)),
    ) -> JobStatus:
        return await _get_job_queue(request).enqueue(job_type, body.payload, guild_id=guild_id)

    @router.get("/{job_id}")
    async def get_job(
        guild_id: int,
        job_id: str,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> JobStatus:
        job = await _get_job_queue(request).get_status(job_id)
        if job is None or job.guild_id != guild_id:
            # Same guild_id != None as "not found", not 403 -- avoids
            # confirming a job with that id exists at all in another guild.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
        return job

    return router
