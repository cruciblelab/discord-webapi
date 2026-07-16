from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from discord_webapi.audit.models import AuditLogEntry
    from discord_webapi.authz.models import AppRole
    from discord_webapi.commands.models import CommandOverride
    from discord_webapi.consent.models import ConsentRecord
    from discord_webapi.ratelimits.models import RateLimitRule


class Session(BaseModel):
    """A logged-in dashboard session.

    Discord's own access/refresh tokens never reach the browser — they are
    encrypted at rest (Fernet) and live only in this server-side row, keyed
    by the opaque `session_id` the browser holds in a single httpOnly cookie.
    Revocation is deleting this row; there is no separate JWT/refresh-token
    lifecycle to reconcile.
    """

    session_id: str
    user_id: int
    username: str
    global_name: str | None = None
    avatar: str | None = None
    guild_ids: list[int] = []

    created_at: datetime
    expires_at: datetime

    encrypted_access_token: bytes
    encrypted_refresh_token: bytes
    discord_token_expires_at: datetime


class SessionStore(Protocol):
    """Storage for dashboard sessions. Implementations: Memory (dev/test), SQL."""

    async def create(self, session: Session) -> None: ...

    async def get(self, session_id: str) -> Session | None: ...

    async def update(self, session: Session) -> None: ...

    async def delete(self, session_id: str) -> None: ...

    async def list_by_user(self, user_id: int) -> list[Session]: ...


class CommandConfigStore(Protocol):
    """Storage for per-guild command overrides (enabled/disabled, cooldowns, ...).

    The command registry's global-check runs this on the hot path of every
    command invocation across every guild, so implementations must be backed
    by an in-memory cache the caller keeps warm — see
    `discord_webapi.commands.registry.CommandRegistry`. This store is only
    ever hit on boot (seed) and on writes (dashboard PATCH), never per
    invocation.
    """

    async def get_override(self, guild_id: int, command_name: str) -> CommandOverride | None: ...

    async def get_all_overrides(self, guild_id: int) -> list[CommandOverride]: ...

    async def set_override(self, override: CommandOverride) -> None: ...


class AuthzStore(Protocol):
    """Storage for bot-owner-defined `AppRole`s. Unlike `GuildMemberCache`
    (which must ask the bot process for Discord's own Gateway-cached role
    data), this is data the library owns outright, so `AppRoleCache` reads
    it directly with a short TTL rather than routing through Transport.
    """

    async def get_all_app_roles(self, guild_id: int) -> list[AppRole]: ...

    async def set_app_role(self, role: AppRole) -> None: ...

    async def delete_app_role(self, guild_id: int, name: str) -> None: ...


class AuditStore(Protocol):
    """Storage for the (opt-in) audit trail of state-changing dashboard
    actions. Nothing writes here unless `enable_audit_log=True`."""

    async def record(self, entry: AuditLogEntry) -> None: ...

    async def list_entries(self, guild_id: int, *, limit: int = 100) -> list[AuditLogEntry]: ...


class ConsentStore(Protocol):
    """Storage for the (opt-in) cookie/privacy consent record. Nothing
    writes here unless `enable_cookie_consent=True`."""

    async def get(self, user_id: int) -> ConsentRecord | None: ...

    async def set(self, record: ConsentRecord) -> None: ...


class RateLimitStore(Protocol):
    """Storage for per-guild rate-limit rules, keyed by an arbitrary
    string (not necessarily a discord.py command name -- see
    `discord_webapi.ratelimits.GuildRateLimiter`, which is the hot-path
    caller and keeps its own in-memory cache warm the same way
    `CommandConfigStore`'s consumer, `CommandRegistry`, does). Only ever
    hit on first use per (guild, key) and on writes, never per
    `.check()` call.
    """

    async def get_rule(self, guild_id: int, key: str) -> RateLimitRule | None: ...

    async def get_all_rules(self, guild_id: int) -> list[RateLimitRule]: ...

    async def set_rule(self, rule: RateLimitRule) -> None: ...

    async def delete_rule(self, guild_id: int, key: str) -> None: ...
