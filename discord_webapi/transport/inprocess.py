from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from discord_webapi.exceptions import TransportError, TransportTimeoutError
from discord_webapi.observability import NOOP_METRICS, MetricsSink
from discord_webapi.transport.base import (
    CATCH_ALL_EVENT_TYPE,
    Event,
    EventHandler,
    RequestHandler,
)

logger = logging.getLogger("discord_webapi.transport.inprocess")


def _assert_json_serializable(payload: dict[str, Any], *, context: str) -> None:
    """Round-trips `payload` through json to catch objects (e.g. a raw
    discord.Member) that would silently work in-process but break the moment
    a deployment switches to RedisTransport. See transport contract tests.
    """
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise TransportError(
            f"{context} payload is not JSON-serializable: {exc}. "
            "Transport payloads must stay JSON-serializable so InProcessTransport "
            "and RedisTransport behave identically."
        ) from exc


class InProcessTransport:
    """Default v0.1 transport: bot and web share one asyncio event loop.

    Zero extra infrastructure. Subscribers/handlers are plain in-memory
    dicts; publish() fans out via asyncio.create_task so one failing
    subscriber can never break the publisher or other subscribers.
    """

    def __init__(
        self, *, strict_serialization: bool = True, metrics: MetricsSink = NOOP_METRICS
    ) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._handlers: dict[str, RequestHandler] = {}
        self._strict_serialization = strict_serialization
        self._metrics = metrics

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish(self, event: Event) -> None:
        if self._strict_serialization:
            _assert_json_serializable(event.payload, context=f"Event({event.type!r})")

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

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        handlers = self._subscribers.get(event_type)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)

    def register_handler(self, command: str, handler: RequestHandler) -> None:
        if command in self._handlers:
            raise TransportError(
                f"A handler for command {command!r} is already registered. "
                "InProcessTransport supports exactly one handler per command."
            )
        self._handlers[command] = handler

    async def request(
        self, command: str, payload: dict[str, Any], *, timeout: float = 5.0
    ) -> dict[str, Any]:
        if self._strict_serialization:
            _assert_json_serializable(payload, context=f"Request({command!r})")

        handler = self._handlers.get(command)
        if handler is None:
            self._metrics.increment(
                "discord_webapi.transport.request_errors", tags={"command": command}
            )
            raise TransportError(f"No handler registered for command {command!r}")

        started_at = time.monotonic()
        try:
            response = await asyncio.wait_for(handler(payload), timeout=timeout)
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

        if self._strict_serialization:
            _assert_json_serializable(response, context=f"Response({command!r})")
        return response
