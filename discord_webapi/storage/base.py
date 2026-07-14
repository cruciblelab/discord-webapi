from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from discord_webapi.commands.models import CommandOverride


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
