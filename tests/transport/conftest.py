import os
from collections.abc import Callable

import pytest
import pytest_asyncio
from redis.exceptions import RedisError

from discord_webapi.transport import InProcessTransport, RedisTransport, Transport

REDIS_URL = os.environ.get("DWA_TEST_REDIS_URL", "redis://localhost:6379/15")

# Each entry is a zero-arg factory returning a fresh, unstarted Transport.
# Both implementations run through the exact same tests below — this is the
# concrete guard against the rest of the library (auth, authz, commands)
# accidentally depending on in-process-only behavior.
TRANSPORT_FACTORIES: dict[str, Callable[[], Transport]] = {
    "inprocess": lambda: InProcessTransport(),
    "redis": lambda: RedisTransport(REDIS_URL),
}


@pytest_asyncio.fixture(params=list(TRANSPORT_FACTORIES))
async def transport(request: pytest.FixtureRequest) -> Transport:
    instance = TRANSPORT_FACTORIES[request.param]()
    try:
        await instance.start()
    except RedisError:
        pytest.skip(f"No Redis reachable at {REDIS_URL} (set DWA_TEST_REDIS_URL)")
    try:
        yield instance
    finally:
        await instance.stop()
