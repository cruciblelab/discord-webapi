"""RedisTransport's whole reason to exist is cross-process delivery — these
tests use two independent instances (simulating a bot process and a web
process) talking only through the shared Redis server, unlike the
same-instance contract suite in tests/transport/test_contract.py.
"""

import asyncio
import os

import pytest
from redis.exceptions import RedisError

from discord_webapi.exceptions import TransportError
from discord_webapi.transport import Event, RedisTransport

REDIS_URL = os.environ.get("DWA_TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture
async def two_transports():
    bot_side = RedisTransport(REDIS_URL)
    web_side = RedisTransport(REDIS_URL)
    try:
        await bot_side.start()
        await web_side.start()
    except RedisError:
        pytest.skip(f"No Redis reachable at {REDIS_URL} (set DWA_TEST_REDIS_URL)")
    try:
        yield bot_side, web_side
    finally:
        await bot_side.stop()
        await web_side.stop()


async def test_cross_instance_rpc(two_transports) -> None:
    bot_side, web_side = two_transports

    async def handle_get_member(payload: dict) -> dict:
        return {"member_id": payload["member_id"], "roles": [1, 2, 3]}

    bot_side.register_handler("get_member", handle_get_member)
    await asyncio.sleep(0.1)  # let the subscribe land before the request is sent

    response = await web_side.request("get_member", {"member_id": 7})

    assert response == {"member_id": 7, "roles": [1, 2, 3]}


async def test_cross_instance_pub_sub(two_transports) -> None:
    bot_side, web_side = two_transports
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    web_side.subscribe("member_updated", handler)
    await asyncio.sleep(0.1)

    await bot_side.publish(Event(type="member_updated", payload={"guild_id": 1, "user_id": 2}))
    await asyncio.sleep(0.2)

    assert len(received) == 1
    assert received[0].payload == {"guild_id": 1, "user_id": 2}


async def test_register_handler_after_start_is_still_reachable(two_transports) -> None:
    bot_side, web_side = two_transports

    async def handle_ping(payload: dict) -> dict:
        return {"pong": True}

    # Registered after both sides already called start().
    bot_side.register_handler("ping", handle_ping)
    await asyncio.sleep(0.1)

    response = await web_side.request("ping", {})

    assert response == {"pong": True}


async def test_duplicate_handler_registration_raises() -> None:
    transport = RedisTransport(REDIS_URL)
    try:
        await transport.start()
    except RedisError:
        pytest.skip(f"No Redis reachable at {REDIS_URL} (set DWA_TEST_REDIS_URL)")

    async def handler(payload: dict) -> dict:
        return {}

    try:
        transport.register_handler("dup", handler)
        with pytest.raises(TransportError):
            transport.register_handler("dup", handler)
    finally:
        await transport.stop()


async def test_remote_handler_exception_is_relayed_as_transport_error(two_transports) -> None:
    bot_side, web_side = two_transports

    async def broken_handler(payload: dict) -> dict:
        raise ValueError("boom")

    bot_side.register_handler("broken", broken_handler)
    await asyncio.sleep(0.1)

    with pytest.raises(TransportError, match="boom"):
        await web_side.request("broken", {})
