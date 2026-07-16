import os
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from redis.exceptions import RedisError

from discord_webapi.jobs import InProcessJobQueue, JobQueue, RedisJobQueue

REDIS_URL = os.environ.get("DWA_TEST_REDIS_URL", "redis://localhost:6379/15")

# Each entry is a zero-arg factory returning a fresh, unstarted JobQueue.
# Both implementations run through the exact same tests below -- register
# workers first, then call `queue.start()` yourself inside the test (both
# implementations require workers to be registered before starting).
JOB_QUEUE_FACTORIES: dict[str, Callable[[], JobQueue]] = {
    "inprocess": lambda: InProcessJobQueue(),
    "redis": lambda: RedisJobQueue(REDIS_URL),
}


@pytest_asyncio.fixture(params=list(JOB_QUEUE_FACTORIES))
async def job_queue(request: pytest.FixtureRequest) -> AsyncIterator[JobQueue]:
    if request.param == "redis":
        probe = Redis.from_url(REDIS_URL)
        try:
            await probe.ping()
        except RedisError:
            pytest.skip(f"No Redis reachable at {REDIS_URL} (set DWA_TEST_REDIS_URL)")
        finally:
            await probe.aclose()

    instance = JOB_QUEUE_FACTORIES[request.param]()
    try:
        yield instance
    finally:
        await instance.stop()
