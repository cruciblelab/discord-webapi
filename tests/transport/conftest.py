from collections.abc import Callable

import pytest
import pytest_asyncio

from discord_webapi.transport import InProcessTransport, Transport

# Each entry is a zero-arg factory returning a fresh, unstarted Transport.
# RedisTransport is added here once implemented (see roadmap step 6) —
# the contract tests below must not need to change, only this list grows.
TRANSPORT_FACTORIES: dict[str, Callable[[], Transport]] = {
    "inprocess": lambda: InProcessTransport(),
}


@pytest_asyncio.fixture(params=list(TRANSPORT_FACTORIES))
async def transport(request: pytest.FixtureRequest) -> Transport:
    instance = TRANSPORT_FACTORIES[request.param]()
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()
