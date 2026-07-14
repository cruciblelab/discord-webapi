from typing import TYPE_CHECKING

from discord_webapi.transport.base import (
    Event,
    EventHandler,
    RequestHandler,
    Transport,
)
from discord_webapi.transport.inprocess import InProcessTransport

if TYPE_CHECKING:
    from discord_webapi.transport.redis import RedisTransport

__all__ = [
    "Event",
    "EventHandler",
    "InProcessTransport",
    "RedisTransport",
    "RequestHandler",
    "Transport",
]


def __getattr__(name: str) -> object:
    # RedisTransport needs the optional `redis` extra (`discord-webapi[redis]`)
    # — imported lazily so the base package never requires it.
    if name == "RedisTransport":
        from discord_webapi.transport.redis import RedisTransport

        return RedisTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
