"""Shared behavior contract every Transport implementation must satisfy.

Both InProcessTransport and RedisTransport run against this exact suite —
this is the concrete mechanism guaranteeing the rest of the library (auth,
authz, command registry) never accidentally depends on in-process-only
behavior.
"""

import asyncio

import pytest

from discord_webapi.exceptions import TransportError, TransportTimeoutError
from discord_webapi.transport import Event, Transport


async def test_publish_delivers_to_matching_subscriber(transport: Transport) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    transport.subscribe("guild_updated", handler)
    await transport.publish(Event(type="guild_updated", payload={"guild_id": 1}))
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].payload == {"guild_id": 1}


async def test_unsubscribe_stops_delivery(transport: Transport) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    transport.subscribe("guild_updated", handler)
    transport.unsubscribe("guild_updated", handler)
    await transport.publish(Event(type="guild_updated", payload={}))
    await asyncio.sleep(0.05)

    assert received == []


async def test_unsubscribe_only_removes_the_given_handler(transport: Transport) -> None:
    received: list[str] = []

    async def handler_a(event: Event) -> None:
        received.append("a")

    async def handler_b(event: Event) -> None:
        received.append("b")

    transport.subscribe("guild_updated", handler_a)
    transport.subscribe("guild_updated", handler_b)
    transport.unsubscribe("guild_updated", handler_a)
    await transport.publish(Event(type="guild_updated", payload={}))
    await asyncio.sleep(0.05)

    assert received == ["b"]


async def test_unsubscribe_of_unknown_handler_is_a_no_op(transport: Transport) -> None:
    async def handler(event: Event) -> None:
        pass

    transport.unsubscribe("never_subscribed", handler)  # must not raise


async def test_publish_does_not_deliver_to_other_event_types(transport: Transport) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    transport.subscribe("guild_updated", handler)
    await transport.publish(Event(type="member_updated", payload={}))
    await asyncio.sleep(0.05)

    assert received == []


async def test_catch_all_subscriber_receives_every_event(transport: Transport) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    transport.subscribe("*", handler)
    await transport.publish(Event(type="guild_updated", payload={}))
    await transport.publish(Event(type="member_updated", payload={}))
    await asyncio.sleep(0.05)

    assert [e.type for e in received] == ["guild_updated", "member_updated"]


async def test_one_bad_subscriber_does_not_break_others(transport: Transport) -> None:
    received: list[Event] = []

    async def bad_handler(event: Event) -> None:
        raise RuntimeError("boom")

    async def good_handler(event: Event) -> None:
        received.append(event)

    transport.subscribe("guild_updated", bad_handler)
    transport.subscribe("guild_updated", good_handler)
    await transport.publish(Event(type="guild_updated", payload={}))
    await asyncio.sleep(0.05)

    assert len(received) == 1


async def test_request_returns_handler_response(transport: Transport) -> None:
    async def handler(payload: dict) -> dict:
        return {"member_id": payload["member_id"], "roles": [1, 2, 3]}

    transport.register_handler("get_member", handler)
    response = await transport.request("get_member", {"member_id": 42})

    assert response == {"member_id": 42, "roles": [1, 2, 3]}


async def test_request_with_no_handler_raises_transport_error(transport: Transport) -> None:
    # InProcessTransport knows synchronously there's no local handler and
    # raises immediately; RedisTransport can only ever time out (it has no
    # way to know whether some other process might answer) — both outcomes
    # satisfy TransportError since TransportTimeoutError subclasses it. A
    # short timeout keeps this fast under either implementation.
    with pytest.raises(TransportError):
        await transport.request("nonexistent_command", {}, timeout=0.2)


async def test_request_timeout_raises_transport_timeout_error(transport: Transport) -> None:
    async def slow_handler(payload: dict) -> dict:
        await asyncio.sleep(10)
        return {}

    transport.register_handler("slow_command", slow_handler)

    with pytest.raises(TransportTimeoutError):
        await transport.request("slow_command", {}, timeout=0.05)


async def test_non_serializable_event_payload_is_rejected(transport: Transport) -> None:
    class NotSerializable:
        pass

    with pytest.raises(TransportError):
        await transport.publish(Event(type="x", payload={"obj": NotSerializable()}))


async def test_non_serializable_request_payload_is_rejected(transport: Transport) -> None:
    class NotSerializable:
        pass

    async def handler(payload: dict) -> dict:
        return {}

    transport.register_handler("cmd", handler)
    with pytest.raises(TransportError):
        await transport.request("cmd", {"obj": NotSerializable()})
