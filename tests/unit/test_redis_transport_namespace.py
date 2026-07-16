"""RedisTransport-specific: multi-tenant namespace isolation. Not part of
the shared Transport contract suite (tests/transport/) since this only
applies to the Redis backend -- InProcessTransport has no shared-infra
cross-talk concern to isolate against.
"""

import asyncio
import os

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from discord_webapi.transport import Event, RedisTransport

REDIS_URL = os.environ.get("DWA_TEST_REDIS_URL", "redis://localhost:6379/15")


async def _skip_if_unreachable() -> None:
    probe = Redis.from_url(REDIS_URL)
    try:
        await probe.ping()
    except RedisError:
        pytest.skip(f"No Redis reachable at {REDIS_URL} (set DWA_TEST_REDIS_URL)")
    finally:
        await probe.aclose()


async def test_different_namespaces_dont_see_each_others_events() -> None:
    await _skip_if_unreachable()
    tenant_a = RedisTransport(REDIS_URL, namespace="tenant-a")
    tenant_b = RedisTransport(REDIS_URL, namespace="tenant-b")
    await tenant_a.start()
    await tenant_b.start()
    try:
        b_received: list[Event] = []

        async def handler(event: Event) -> None:
            b_received.append(event)

        tenant_b.subscribe("guild_updated", handler)
        await tenant_a.publish(Event(type="guild_updated", payload={"guild_id": 1}))
        await asyncio.sleep(0.1)

        assert b_received == []
    finally:
        await tenant_a.stop()
        await tenant_b.stop()


async def test_different_namespaces_dont_share_rpc_commands() -> None:
    await _skip_if_unreachable()
    tenant_a = RedisTransport(REDIS_URL, namespace="tenant-a")
    tenant_b = RedisTransport(REDIS_URL, namespace="tenant-b")

    async def handle_get_member(payload: dict) -> dict:
        return {"found": True}

    tenant_b.register_handler("get_member", handle_get_member)
    await tenant_a.start()
    await tenant_b.start()
    try:
        with pytest.raises(Exception):  # noqa: B017 - TransportTimeoutError, just verifying no cross-talk
            await tenant_a.request("get_member", {}, timeout=0.3)
    finally:
        await tenant_a.stop()
        await tenant_b.stop()
