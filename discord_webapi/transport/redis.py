from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from discord_webapi.exceptions import TransportError, TransportTimeoutError
from discord_webapi.transport.base import (
    CATCH_ALL_EVENT_TYPE,
    Event,
    EventHandler,
    RequestHandler,
)

logger = logging.getLogger("discord_webapi.transport.redis")

EVENTS_CHANNEL = "discord_webapi:events"
_RPC_REQUEST_PREFIX = "discord_webapi:rpc:"
_RPC_REPLY_PREFIX = "discord_webapi:rpc:reply:"


def _rpc_request_channel(command: str) -> str:
    return f"{_RPC_REQUEST_PREFIX}{command}"


def _rpc_reply_channel(request_id: str) -> str:
    return f"{_RPC_REPLY_PREFIX}{request_id}"


def _assert_json_serializable(payload: dict[str, Any], *, context: str) -> None:
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise TransportError(f"{context} payload is not JSON-serializable: {exc}") from exc


class RedisTransport:
    """v0.1 Redis-backed Transport for multi-process deployments: bot and
    web run as separate processes/machines, sharing state only through
    Redis and whatever `Storage` backend they're both pointed at.

    Deliberately simple: plain Redis Pub/Sub for both events and RPC, no
    Streams/consumer-groups. That means exactly one process should
    `register_handler()` for a given command — if two processes both
    register the same command, both receive every request and both will
    try to reply, which is undefined for the caller (first reply wins,
    second is dropped). Competing-consumer semantics for multi-instance/
    shard deployments are a deliberate v0.2 upgrade (see the architecture
    plan's risk notes) built behind this same `register_handler`/`request`
    signature — no caller code will need to change.

    `register_handler()` is called before `start()` in every deployment
    this library wires up itself (the bot-side RPC handlers are registered
    during `DiscordWebAPI.__init__`, before the FastAPI lifespan calls
    `start()`), which is the case this class optimizes for: `start()`
    subscribes to every already-registered command's channel in one batch.
    Calling `register_handler()` again after `start()` still works, but
    only from within a running event loop (it subscribes via a background
    task) — see the raised `TransportError` otherwise.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379", **redis_kwargs: Any) -> None:
        self._redis_url = redis_url
        self._redis_kwargs = redis_kwargs
        self._redis: Redis | None = None
        self._pubsub: PubSub | None = None
        self._reader_task: asyncio.Task[None] | None = None

        self._subscribers: dict[str, list[EventHandler]] = {}
        self._handlers: dict[str, RequestHandler] = {}
        self._pending_replies: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def start(self) -> None:
        self._redis = Redis.from_url(self._redis_url, **self._redis_kwargs)
        self._pubsub = self._redis.pubsub()
        channels = [EVENTS_CHANNEL, *(_rpc_request_channel(c) for c in self._handlers)]
        await self._pubsub.subscribe(*channels)
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._pubsub is not None:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]
            self._pubsub = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def _require_redis(self) -> Redis:
        if self._redis is None:
            raise TransportError("RedisTransport.start() must be called first")
        return self._redis

    async def _read_loop(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message["type"] != "message":
                continue
            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()
            data = message["data"]
            try:
                envelope = json.loads(data)
            except (TypeError, ValueError):
                logger.warning("Dropping non-JSON message on channel %r", channel)
                continue

            if channel == EVENTS_CHANNEL:
                await self._dispatch_event(envelope)
            elif channel.startswith(_RPC_REPLY_PREFIX):
                self._resolve_reply(channel, envelope)
            elif channel.startswith(_RPC_REQUEST_PREFIX):
                asyncio.create_task(self._handle_rpc_request(channel, envelope))

    async def _dispatch_event(self, envelope: dict[str, Any]) -> None:
        event = Event(
            type=envelope["type"], payload=envelope["payload"], source=envelope.get("source")
        )
        handlers = [
            *self._subscribers.get(event.type, ()),
            *self._subscribers.get(CATCH_ALL_EVENT_TYPE, ()),
        ]
        for handler in handlers:
            asyncio.create_task(self._run_handler_safely(handler, event))

    async def _run_handler_safely(self, handler: EventHandler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception("Unhandled error in subscriber for event type %r", event.type)

    def _resolve_reply(self, channel: str, envelope: dict[str, Any]) -> None:
        future = self._pending_replies.pop(channel, None)
        if future is not None and not future.done():
            future.set_result(envelope)

    async def _handle_rpc_request(self, channel: str, envelope: dict[str, Any]) -> None:
        command = channel.removeprefix(_RPC_REQUEST_PREFIX)
        handler = self._handlers.get(command)
        if handler is None:
            return  # not this process's command to answer

        request_id = envelope["request_id"]
        try:
            response: dict[str, Any] = await handler(envelope["payload"])
            error = None
        except Exception as exc:  # noqa: BLE001 - relayed to the caller, not swallowed
            response = {}
            error = str(exc)

        redis = self._require_redis()
        await redis.publish(
            _rpc_reply_channel(request_id), json.dumps({"response": response, "error": error})
        )

    async def publish(self, event: Event) -> None:
        redis = self._require_redis()
        _assert_json_serializable(event.payload, context=f"Event({event.type!r})")
        envelope = {"type": event.type, "payload": event.payload, "source": event.source}
        await redis.publish(EVENTS_CHANNEL, json.dumps(envelope))

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        # Only removes local in-process dispatch -- the shared EVENTS_CHANNEL
        # subscription itself stays open for this transport's whole lifetime,
        # since other event types may still be routed through it.
        handlers = self._subscribers.get(event_type)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)

    def register_handler(self, command: str, handler: RequestHandler) -> None:
        if command in self._handlers:
            raise TransportError(
                f"A handler for command {command!r} is already registered on this process."
            )
        self._handlers[command] = handler

        if self._pubsub is None:
            return  # picked up in one batch by start()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise TransportError(
                f"register_handler({command!r}) was called after start() but outside a running "
                "event loop, so the Redis channel subscription can't be scheduled. Register "
                "handlers before start(), or from within an async context."
            ) from None
        loop.create_task(self._pubsub.subscribe(_rpc_request_channel(command)))

    async def request(
        self, command: str, payload: dict[str, Any], *, timeout: float = 5.0
    ) -> dict[str, Any]:
        redis = self._require_redis()
        assert self._pubsub is not None
        _assert_json_serializable(payload, context=f"Request({command!r})")

        request_id = uuid.uuid4().hex
        reply_channel = _rpc_reply_channel(request_id)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_replies[reply_channel] = future

        # Subscribe before publish: avoids the race where a reply arrives
        # before we're listening for it.
        await self._pubsub.subscribe(reply_channel)
        try:
            await redis.publish(
                _rpc_request_channel(command),
                json.dumps({"request_id": request_id, "payload": payload}),
            )
            try:
                envelope = await asyncio.wait_for(future, timeout=timeout)
            except TimeoutError as exc:
                raise TransportTimeoutError(
                    f"Request {command!r} timed out after {timeout}s"
                ) from exc
        finally:
            self._pending_replies.pop(reply_channel, None)
            await self._pubsub.unsubscribe(reply_channel)

        if envelope.get("error"):
            raise TransportError(f"Remote handler for {command!r} raised: {envelope['error']}")

        response: dict[str, Any] = envelope["response"]
        _assert_json_serializable(response, context=f"Response({command!r})")
        return response
