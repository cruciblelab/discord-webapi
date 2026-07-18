from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Coroutine
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from discord_webapi.exceptions import TransportError, TransportTimeoutError
from discord_webapi.observability import NOOP_METRICS, MetricsSink
from discord_webapi.transport.base import (
    CATCH_ALL_EVENT_TYPE,
    Event,
    EventHandler,
    RequestHandler,
)

logger = logging.getLogger("discord_webapi.transport.redis")

_RECONNECT_DELAY_SECONDS = 1.0

DEFAULT_NAMESPACE = "discord_webapi"


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

    **Multi-tenant Redis**: if multiple, otherwise-unrelated deployments
    (e.g. different customers' bots, in a hosted setup) share one Redis
    instance/cluster, pass a distinct `namespace=` to each -- channel names
    are namespaced (`{namespace}:events`, `{namespace}:rpc:...`), so two
    deployments with different namespaces never see each other's events or
    RPC traffic even on the same Redis. This does *not* add authentication
    (Redis itself still has to be treated as trusted infrastructure -- see
    `docs/GUVENLIK.md`); it only prevents accidental cross-talk between
    tenants that are otherwise isolated but happen to share a Redis
    instance for cost/ops reasons. For real isolation between mutually
    untrusted tenants, use separate Redis databases/ACL users, not just
    separate namespaces.

    **Connection pool sizing under heavy concurrent RPC traffic**: each
    `request()` call briefly holds a connection for its
    subscribe/publish/unsubscribe sequence. redis-py's default connection
    pool caps at 100 connections -- a dashboard issuing many dozens of
    concurrent `request()` calls at once can hit `MaxConnectionsError`.
    Pass `max_connections=` (forwarded via `**redis_kwargs` to
    `Redis.from_url`) if your deployment's concurrent RPC volume needs
    more headroom than that default.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        *,
        namespace: str = DEFAULT_NAMESPACE,
        metrics: MetricsSink = NOOP_METRICS,
        **redis_kwargs: Any,
    ) -> None:
        self._redis_url = redis_url
        self._redis_kwargs = redis_kwargs
        self._namespace = namespace
        self._metrics = metrics
        self._events_channel = f"{namespace}:events"
        # Sibling prefixes (neither a prefix of the other) on purpose --
        # `rpc:` used to be a prefix of `rpc:reply:`, so a command literally
        # named "reply:whatever" produced a request channel
        # (f"{namespace}:rpc:reply:whatever") that _read_loop_once's
        # startswith checks misclassified as a reply channel, silently
        # dropping every request for that command name. Not reachable by
        # construction anymore.
        self._rpc_request_prefix = f"{namespace}:rpc-cmd:"
        self._rpc_reply_prefix = f"{namespace}:rpc-reply:"
        self._redis: Redis | None = None
        self._pubsub: PubSub | None = None
        self._reader_task: asyncio.Task[None] | None = None

        self._subscribers: dict[str, list[EventHandler]] = {}
        self._handlers: dict[str, RequestHandler] = {}
        self._pending_replies: dict[str, asyncio.Future[dict[str, Any]]] = {}

    def _rpc_request_channel(self, command: str) -> str:
        return f"{self._rpc_request_prefix}{command}"

    def _rpc_reply_channel(self, request_id: str) -> str:
        return f"{self._rpc_reply_prefix}{request_id}"

    async def start(self) -> None:
        self._redis = Redis.from_url(self._redis_url, **self._redis_kwargs)
        self._pubsub = self._redis.pubsub()
        channels = [
            self._events_channel,
            *(self._rpc_request_channel(c) for c in self._handlers),
        ]
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
        # Without this outer retry, a dropped Redis connection (network
        # blip, Redis restart) would raise out of `listen()` and silently
        # kill this task forever -- no more events or RPC replies would
        # ever be delivered again until the whole process was restarted.
        while True:
            try:
                await self._read_loop_once()
            except asyncio.CancelledError:
                raise
            except RedisError:
                logger.exception(
                    "RedisTransport reader lost its connection; reconnecting in %.1fs",
                    _RECONNECT_DELAY_SECONDS,
                )
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
                await self._resubscribe_all()

    async def _read_loop_once(self) -> None:
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

            if channel == self._events_channel:
                # A malformed envelope (a shape mismatch from version skew
                # between deployed bot/web processes, a bug elsewhere on
                # the wire, hand-crafted traffic) must not kill this loop
                # -- `_dispatch_event` indexes `envelope["type"]`/
                # `["payload"]` directly, and an uncaught KeyError here
                # would propagate out of this whole read loop, silently
                # ending event delivery forever (only the RPC-request
                # branch below was already guarded, via
                # `_create_tracked_task`).
                try:
                    await self._dispatch_event(envelope)
                except (KeyError, TypeError) as exc:
                    logger.warning(
                        "Dropping malformed event envelope on channel %r: %s", channel, exc
                    )
            elif channel.startswith(self._rpc_reply_prefix):
                self._resolve_reply(channel, envelope)
            elif channel.startswith(self._rpc_request_prefix):
                self._create_tracked_task(
                    self._handle_rpc_request(channel, envelope),
                    description=f"RPC request handler for channel {channel!r}",
                )

    async def _resubscribe_all(self) -> None:
        # Re-establishes every channel this instance cares about after a
        # reconnect: the shared events channel, every registered RPC
        # command's request channel, and any reply channels an in-flight
        # `request()` call is still waiting on.
        assert self._pubsub is not None
        channels = [
            self._events_channel,
            *(self._rpc_request_channel(c) for c in self._handlers),
            *self._pending_replies.keys(),
        ]
        try:
            await self._pubsub.subscribe(*channels)
        except RedisError:
            logger.exception("Failed to resubscribe after Redis reconnect; will retry")

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

    def _create_tracked_task(self, coro: Coroutine[Any, Any, None], *, description: str) -> None:
        """`asyncio.create_task` without keeping the returned task anywhere
        silently swallows any exception it raises (it only ever surfaces as
        an "exception was never retrieved" warning at GC time) -- used for
        every fire-and-forget task this class creates so a failure is at
        least logged, not lost. In particular, a caller waiting on
        `request()` for this exact RPC would otherwise see a plain timeout
        with no indication the handler actually ran (or why its reply never
        arrived)."""
        task = asyncio.create_task(coro)
        task.add_done_callback(lambda t: self._log_task_exception(t, description=description))

    @staticmethod
    def _log_task_exception(task: asyncio.Task[None], *, description: str) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Unhandled error in %s", description, exc_info=exc)

    async def _handle_rpc_request(self, channel: str, envelope: dict[str, Any]) -> None:
        command = channel.removeprefix(self._rpc_request_prefix)
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

        try:
            redis = self._require_redis()
            await redis.publish(
                self._rpc_reply_channel(request_id),
                json.dumps({"response": response, "error": error}),
            )
        except RedisError:
            # The handler ran (successfully or not, per `error` above) but
            # the reply never made it back -- without this the caller just
            # sees a bare TransportTimeoutError with nothing in the logs to
            # explain that the command actually executed.
            logger.exception(
                "Failed to publish RPC reply for command %r (request_id=%s); the "
                "handler's own result (error=%r) is now unreachable, and the "
                "caller of request() will see a timeout instead.",
                command,
                request_id,
                error,
            )

    async def publish(self, event: Event) -> None:
        redis = self._require_redis()
        _assert_json_serializable(event.payload, context=f"Event({event.type!r})")
        envelope = {"type": event.type, "payload": event.payload, "source": event.source}
        await redis.publish(self._events_channel, json.dumps(envelope))

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
            asyncio.get_running_loop()
        except RuntimeError:
            raise TransportError(
                f"register_handler({command!r}) was called after start() but outside a running "
                "event loop, so the Redis channel subscription can't be scheduled. Register "
                "handlers before start(), or from within an async context."
            ) from None
        self._create_tracked_task(
            self._pubsub.subscribe(self._rpc_request_channel(command)),
            description=f"post-start subscribe for command {command!r}",
        )

    async def request(
        self, command: str, payload: dict[str, Any], *, timeout: float = 5.0
    ) -> dict[str, Any]:
        redis = self._require_redis()
        assert self._pubsub is not None
        _assert_json_serializable(payload, context=f"Request({command!r})")

        request_id = uuid.uuid4().hex
        reply_channel = self._rpc_reply_channel(request_id)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_replies[reply_channel] = future

        # Subscribe before publish: avoids the race where a reply arrives
        # before we're listening for it.
        await self._pubsub.subscribe(reply_channel)
        started_at = time.monotonic()
        try:
            await redis.publish(
                self._rpc_request_channel(command),
                json.dumps({"request_id": request_id, "payload": payload}),
            )
            try:
                envelope = await asyncio.wait_for(future, timeout=timeout)
            except TimeoutError as exc:
                self._metrics.increment(
                    "discord_webapi.transport.request_errors", tags={"command": command}
                )
                raise TransportTimeoutError(
                    f"Request {command!r} timed out after {timeout}s"
                ) from exc
        finally:
            self._metrics.observe(
                "discord_webapi.transport.request_seconds",
                time.monotonic() - started_at,
                tags={"command": command},
            )
            self._pending_replies.pop(reply_channel, None)
            await self._pubsub.unsubscribe(reply_channel)

        if envelope.get("error"):
            raise TransportError(f"Remote handler for {command!r} raised: {envelope['error']}")

        response: dict[str, Any] = envelope["response"]
        _assert_json_serializable(response, context=f"Response({command!r})")
        return response
