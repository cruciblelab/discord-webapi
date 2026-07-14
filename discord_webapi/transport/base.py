from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

CATCH_ALL_EVENT_TYPE = "*"


@dataclasses.dataclass(frozen=True)
class Event:
    """A broadcast message published over a Transport.

    `payload` must be JSON-serializable — this is enforced even for
    InProcessTransport so behavior does not silently diverge once a
    deployment switches to RedisTransport (see transport contract tests).
    """

    type: str
    payload: dict[str, Any]
    source: str | None = None


EventHandler = Callable[[Event], Awaitable[None]]
RequestHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@runtime_checkable
class Transport(Protocol):
    """Bridges the discord.py bot process and the FastAPI web process.

    Two independent verbs, not to be conflated:
    - publish/subscribe: broadcast, fire-and-forget, any number of listeners.
    - register_handler/request: point-to-point RPC, exactly one handler answers.

    Auth, authz, and the command registry are written only against this
    interface, never against a concrete bot object or a concrete backend —
    that is what lets the same code run in-process or across a Redis-backed
    multi-process deployment.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def publish(self, event: Event) -> None: ...

    def subscribe(self, event_type: str, handler: EventHandler) -> None: ...

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None: ...

    def register_handler(self, command: str, handler: RequestHandler) -> None: ...

    async def request(
        self, command: str, payload: dict[str, Any], *, timeout: float = 5.0
    ) -> dict[str, Any]: ...
