"""RedisJobQueue-specific behavior not covered by the shared JobQueue
contract suite (tests/jobs/) -- things that only apply to this backend,
like the "register workers before start()" constraint and the TTL policy
that keeps a queued-but-not-yet-picked-up job's status from expiring.
"""

import asyncio
import os

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from discord_webapi.jobs import RedisJobQueue

REDIS_URL = os.environ.get("DWA_TEST_REDIS_URL", "redis://localhost:6379/15")


async def _skip_if_unreachable() -> None:
    probe = Redis.from_url(REDIS_URL)
    try:
        await probe.ping()
    except RedisError:
        pytest.skip(f"No Redis reachable at {REDIS_URL} (set DWA_TEST_REDIS_URL)")
    finally:
        await probe.aclose()


async def test_register_worker_after_start_raises() -> None:
    await _skip_if_unreachable()
    queue = RedisJobQueue(REDIS_URL)

    async def handler(payload: dict) -> dict:
        return {}

    queue.register_worker("known_before_start", handler)
    await queue.start()
    try:
        with pytest.raises(RuntimeError, match="register_worker"):
            queue.register_worker("registered_too_late", handler)
    finally:
        await queue.stop()


async def test_pending_job_status_has_no_ttl() -> None:
    """A job sitting in the queue (no worker has picked it up yet) must
    not have its status key expire out from under it -- only a
    succeeded/failed (terminal) status should carry result_ttl_seconds.
    """
    await _skip_if_unreachable()
    queue = RedisJobQueue(REDIS_URL, result_ttl_seconds=1)
    await queue.start()
    try:
        status = await queue.enqueue("never_processed", {})

        assert queue._redis is not None
        ttl = await queue._redis.ttl(f"discord_webapi:jobs:job:{status.job_id}")
        # -1 means "no expiry set" (redis-py's ttl() convention)
        assert ttl == -1
    finally:
        await queue.stop()


async def test_succeeded_job_status_has_a_ttl() -> None:
    await _skip_if_unreachable()
    queue = RedisJobQueue(REDIS_URL, result_ttl_seconds=60)

    async def handler(payload: dict) -> dict:
        return {"ok": True}

    queue.register_worker("quick", handler)
    await queue.start()
    try:
        status = await queue.enqueue("quick", {})

        for _ in range(50):
            current = await queue.get_status(status.job_id)
            if current is not None and current.state == "succeeded":
                break
            await asyncio.sleep(0.02)

        assert queue._redis is not None
        ttl = await queue._redis.ttl(f"discord_webapi:jobs:job:{status.job_id}")
        assert 0 < ttl <= 60
    finally:
        await queue.stop()


async def test_reclaim_stale_jobs_marks_a_stuck_running_job_as_failed() -> None:
    """Simulates a worker that crashed mid-job: BLPOP already atomically
    removed the job from the queue, so nothing else will ever pick it up
    -- without reclaim_stale_jobs it would stay "running" forever.

    Uses its own namespace: this Redis instance/db is shared across test
    runs (not flushed between them), and a leftover "running" entry from
    a differently-scoped test (or a previous run) would otherwise get
    reclaimed too, making the assertion below flaky/wrong.
    """
    await _skip_if_unreachable()
    queue = RedisJobQueue(REDIS_URL, namespace="reclaim-test-crash")
    await queue.start()
    try:
        status = await queue.enqueue("crash_test", {})
        await queue._save(status.model_copy(update={"state": "running"}))
        assert queue._redis is not None
        await queue._redis.sadd(queue._running_set_key, status.job_id)

        reclaimed = await queue.reclaim_stale_jobs(max_age_seconds=0)

        assert reclaimed == [status.job_id]
        final = await queue.get_status(status.job_id)
        assert final is not None
        assert final.state == "failed"
        assert "crashed" in (final.error or "")
        assert not await queue._redis.sismember(queue._running_set_key, status.job_id)
    finally:
        await queue.stop()


async def test_reclaim_stale_jobs_leaves_a_recently_updated_running_job_alone() -> None:
    """A job that's genuinely still running (not crashed) must not be
    reclaimed just because it's slow -- only jobs older than
    max_age_seconds are touched."""
    await _skip_if_unreachable()
    queue = RedisJobQueue(REDIS_URL, namespace="reclaim-test-still-running")
    await queue.start()
    try:
        status = await queue.enqueue("still_running", {})
        await queue._save(status.model_copy(update={"state": "running"}))
        assert queue._redis is not None
        await queue._redis.sadd(queue._running_set_key, status.job_id)

        reclaimed = await queue.reclaim_stale_jobs(max_age_seconds=3600)

        assert reclaimed == []
        final = await queue.get_status(status.job_id)
        assert final is not None
        assert final.state == "running"
    finally:
        # Clean up -- this job is deliberately left "running" forever by
        # this test, and would otherwise pollute reclaim_stale_jobs() in a
        # later run against this same (not flushed between runs) Redis.
        assert queue._redis is not None
        await queue._redis.srem(queue._running_set_key, status.job_id)
        await queue._redis.delete(queue._status_key(status.job_id))
        await queue.stop()


async def test_real_job_execution_removes_it_from_the_running_set() -> None:
    """A job that completes normally (success or failure) must not linger
    in the running-set forever -- otherwise reclaim_stale_jobs would
    eventually misfire on an already-finished job."""
    await _skip_if_unreachable()
    queue = RedisJobQueue(REDIS_URL, namespace="reclaim-test-cleans-up")

    async def handler(payload: dict) -> dict:
        return {"ok": True}

    queue.register_worker("cleans_up", handler)
    await queue.start()
    try:
        status = await queue.enqueue("cleans_up", {})
        for _ in range(50):
            current = await queue.get_status(status.job_id)
            if current is not None and current.state == "succeeded":
                break
            await asyncio.sleep(0.02)

        assert queue._redis is not None
        assert not await queue._redis.sismember(queue._running_set_key, status.job_id)
    finally:
        await queue.stop()


async def test_different_namespaces_dont_see_each_others_jobs() -> None:
    """Multi-tenant Redis: two RedisJobQueues with different namespaces,
    pointed at the same Redis instance, must not cross-talk."""
    await _skip_if_unreachable()
    tenant_a = RedisJobQueue(REDIS_URL, namespace="tenant-a")
    tenant_b = RedisJobQueue(REDIS_URL, namespace="tenant-b")

    a_seen = []
    b_seen = []

    async def handle_a(payload: dict) -> dict:
        a_seen.append(payload)
        return {}

    async def handle_b(payload: dict) -> dict:
        b_seen.append(payload)
        return {}

    tenant_a.register_worker("shared_job_type", handle_a)
    tenant_b.register_worker("shared_job_type", handle_b)
    await tenant_a.start()
    await tenant_b.start()
    try:
        status = await tenant_a.enqueue("shared_job_type", {"tenant": "a"})

        for _ in range(50):
            current = await tenant_a.get_status(status.job_id)
            if current is not None and current.state == "succeeded":
                break
            await asyncio.sleep(0.02)

        assert a_seen == [{"tenant": "a"}]
        assert b_seen == []
        # tenant_b's Redis connection has no visibility into tenant_a's key at all
        assert await tenant_b.get_status(status.job_id) is None
    finally:
        await tenant_a.stop()
        await tenant_b.stop()
