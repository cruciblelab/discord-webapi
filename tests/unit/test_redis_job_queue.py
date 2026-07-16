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
