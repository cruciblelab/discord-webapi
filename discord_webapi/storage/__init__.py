from typing import TYPE_CHECKING

from discord_webapi.storage.base import AuthzStore, CommandConfigStore, Session, SessionStore
from discord_webapi.storage.memory import (
    MemoryAuthzStore,
    MemoryCommandConfigStore,
    MemorySessionStore,
)

if TYPE_CHECKING:
    from discord_webapi.storage.sql import SQLAuthzStore, SQLCommandConfigStore, SQLSessionStore

__all__ = [
    "AuthzStore",
    "CommandConfigStore",
    "MemoryAuthzStore",
    "MemoryCommandConfigStore",
    "MemorySessionStore",
    "SQLAuthzStore",
    "SQLCommandConfigStore",
    "SQLSessionStore",
    "Session",
    "SessionStore",
]


def __getattr__(name: str) -> object:
    # SQL* stores need the optional `sql` extra (`discord-webapi[sql]`) --
    # imported lazily so the base package never requires SQLAlchemy.
    if name in ("SQLSessionStore", "SQLCommandConfigStore", "SQLAuthzStore"):
        from discord_webapi.storage import sql

        return getattr(sql, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
