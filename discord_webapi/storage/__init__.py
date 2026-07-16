from typing import TYPE_CHECKING

from discord_webapi.storage.base import (
    AuditStore,
    AuthzStore,
    CommandConfigStore,
    ConsentStore,
    RateLimitStore,
    Session,
    SessionStore,
)
from discord_webapi.storage.memory import (
    MemoryAuditStore,
    MemoryAuthzStore,
    MemoryCommandConfigStore,
    MemoryConsentStore,
    MemoryRateLimitStore,
    MemorySessionStore,
)

if TYPE_CHECKING:
    from discord_webapi.storage.sql import (
        SQLAuditStore,
        SQLAuthzStore,
        SQLCommandConfigStore,
        SQLConsentStore,
        SQLRateLimitStore,
        SQLSessionStore,
    )

__all__ = [
    "AuditStore",
    "AuthzStore",
    "CommandConfigStore",
    "ConsentStore",
    "MemoryAuditStore",
    "MemoryAuthzStore",
    "MemoryCommandConfigStore",
    "MemoryConsentStore",
    "MemoryRateLimitStore",
    "MemorySessionStore",
    "RateLimitStore",
    "SQLAuditStore",
    "SQLAuthzStore",
    "SQLCommandConfigStore",
    "SQLConsentStore",
    "SQLRateLimitStore",
    "SQLSessionStore",
    "Session",
    "SessionStore",
]


def __getattr__(name: str) -> object:
    # SQL* stores need the optional `sql` extra (`discord-webapi[sql]`) --
    # imported lazily so the base package never requires SQLAlchemy.
    if name in (
        "SQLSessionStore",
        "SQLCommandConfigStore",
        "SQLAuthzStore",
        "SQLAuditStore",
        "SQLConsentStore",
        "SQLRateLimitStore",
    ):
        from discord_webapi.storage import sql

        return getattr(sql, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
