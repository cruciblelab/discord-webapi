"""RedisTransport's whole reason to exist is cross-process delivery — these
tests use two independent instances (simulating a bot process and a web
process) talking only through the shared Redis server, unlike the
same-instance contract suite in tests/transport/test_contract.py.
"""

import asyncio
import contextlib
import os

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
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


async def test_command_named_reply_prefixed_is_not_misclassified(two_transports) -> None:
    """Regression: the request-channel prefix ("{ns}:rpc:") used to be a
    literal string-prefix of the reply-channel prefix ("{ns}:rpc:reply:"),
    so a command named "reply:something" produced a request channel that
    _read_loop_once's `startswith` checks misclassified as a reply channel
    -- the request was silently dropped (handed to _resolve_reply, which
    no-ops on an unknown channel) and the caller just timed out with no
    indication why. The prefixes no longer nest, so this must now work."""
    bot_side, web_side = two_transports

    async def handle_it(payload: dict) -> dict:
        return {"ok": True}

    bot_side.register_handler("reply:something", handle_it)
    await asyncio.sleep(0.1)

    response = await web_side.request("reply:something", {})

    assert response == {"ok": True}


async def test_create_tracked_task_logs_instead_of_silently_swallowing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A fire-and-forget task (e.g. handling an incoming RPC request) whose
    coroutine raises must not vanish as a bare "Task exception was never
    retrieved" warning at GC time -- it should be logged clearly, with
    enough context to know what failed."""
    transport = RedisTransport("redis://unused")

    async def _boom() -> None:
        raise ValueError("boom")

    with caplog.at_level("ERROR", logger="discord_webapi.transport.redis"):
        transport._create_tracked_task(_boom(), description="test task")
        for _ in range(50):
            await asyncio.sleep(0.01)
            if caplog.records:
                break

    assert any("test task" in r.message for r in caplog.records)


async def test_many_concurrent_requests_never_cross_wires(two_transports) -> None:
    """`request()`'s subscribe/publish/unsubscribe on the shared `PubSub`
    object runs concurrently with the background reader's `listen()` loop
    on that same object whenever more than one request() call is in
    flight -- the ordinary case under real dashboard load, not an edge
    case. Empirically verified here rather than just reasoned about: many
    concurrent in-flight requests, each with a distinct payload, must each
    get back exactly its own reply, never another call's."""
    bot_side, web_side = two_transports

    async def handler(payload: dict) -> dict:
        await asyncio.sleep(0.01)
        return {"echo": payload["n"]}

    bot_side.register_handler("echo", handler)
    await asyncio.sleep(0.1)

    async def one(n: int) -> int:
        response = await web_side.request("echo", {"n": n}, timeout=5.0)
        assert response["echo"] == n
        return n

    for _ in range(3):
        results = await asyncio.gather(*(one(n) for n in range(20)))
        assert sorted(results) == list(range(20))


async def test_reader_loop_reconnects_after_a_dropped_connection() -> None:
    """Regression test: a dropped Redis connection used to kill the
    reader task forever -- no more events/RPC replies would ever be
    delivered again without a full process restart. Uses a fake pubsub
    (no real Redis needed) so the connection drop is fully deterministic.
    """
    transport = RedisTransport("redis://unused")

    class _FakePubSub:
        def __init__(self) -> None:
            self.subscribe_calls: list[tuple[str, ...]] = []
            self._first_listen = True

        async def subscribe(self, *channels: str) -> None:
            self.subscribe_calls.append(channels)

        async def listen(self):
            if self._first_listen:
                self._first_listen = False
                raise RedisConnectionError("Connection lost")
            yield {
                "type": "message",
                "channel": "discord_webapi:events",
                "data": '{"type": "ping", "payload": {}, "source": null}',
            }
            await asyncio.sleep(3600)  # keep the generator alive; test cancels the task

        async def aclose(self) -> None:
            pass

    fake_pubsub = _FakePubSub()
    transport._pubsub = fake_pubsub  # type: ignore[assignment]

    received: list[str] = []

    async def on_ping(event: Event) -> None:
        received.append(event.type)

    transport.subscribe("ping", on_ping)

    reader_task = asyncio.create_task(transport._read_loop())
    try:
        for _ in range(80):
            await asyncio.sleep(0.05)
            if received:
                break
    finally:
        reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader_task

    assert received == ["ping"]
    # The reconnect resubscribed to the events channel (at least once,
    # beyond whatever initial subscribe start() would have done).
    assert any("discord_webapi:events" in calls for calls in fake_pubsub.subscribe_calls)
