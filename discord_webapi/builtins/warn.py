"""A fully-configurable warn command with its own persistent state.

Unlike `ban.py`/`kick.py`/`timeout.py` (stateless -- they just call a
Discord API and reply), a warn system has to remember something across
calls, so this file follows the same shape the rest of the library uses
for its own persistent data (`AuditStore`, `ConsentStore`, ...): a
`WarnStore` Protocol with a Memory implementation (zero infrastructure,
the default) and an optional SQL one. **This is its own store, not bolted
onto `CommandConfigStore` or any core storage protocol** -- if you never
import `discord_webapi.builtins.warn`, nothing about warnings exists in
your schema or your process. `SQLWarnStore.create_all()` is independent
of `discord_webapi.storage.sql.create_all()`, so adopting it never
creates a table for people who didn't ask for it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import discord
from discord import app_commands
from discord.ext import commands
from pydantic import BaseModel

from discord_webapi.builtins._shared import check_role_hierarchy

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


class WarnRecord(BaseModel):
    guild_id: int
    user_id: int
    moderator_id: int
    reason: str
    created_at: datetime


class WarnStore(Protocol):
    """Storage for warn records. Implementations: `MemoryWarnStore` (dev/
    test, the default), `SQLWarnStore` (needs the `discord-webapi[sql]`
    extra, same as every other SQL-backed store in this library)."""

    async def add(self, record: WarnRecord) -> None: ...

    async def list_for_user(self, guild_id: int, user_id: int) -> list[WarnRecord]: ...


class MemoryWarnStore:
    """List-backed WarnStore. Zero infrastructure -- the default."""

    def __init__(self) -> None:
        self._records: list[WarnRecord] = []

    async def add(self, record: WarnRecord) -> None:
        self._records.append(record)

    async def list_for_user(self, guild_id: int, user_id: int) -> list[WarnRecord]:
        return [r for r in self._records if r.guild_id == guild_id and r.user_id == user_id]


def setup(
    bot: commands.Bot,
    *,
    store: WarnStore | None = None,
    command_name: str = "warn",
    auto_timeout_after: int | None = None,
    auto_timeout_minutes: int = 10,
) -> Any:
    """Registers a warn command on `bot` and returns it.

    `store` defaults to a fresh `MemoryWarnStore` -- warnings are lost on
    restart unless you pass a `SQLWarnStore(engine)` (see
    `discord_webapi.builtins.warn.SQLWarnStore`, needs `discord-webapi[sql]`)
    or your own `WarnStore` implementation.

    `auto_timeout_after`: if set, a member's `N`th warning in this guild
    automatically applies a `Member.timeout` of `auto_timeout_minutes` --
    escalation is opt-in, never assumed.
    """
    warn_store = store or MemoryWarnStore()

    @bot.hybrid_command(  # type: ignore[arg-type]
        name=command_name, description="Warn a member"
    )
    @app_commands.describe(member="The member to warn", reason="Why this member is being warned")
    @commands.has_permissions(moderate_members=True)
    async def warn(
        ctx: commands.Context[commands.Bot], member: discord.Member, reason: str
    ) -> None:
        if ctx.guild is None:
            return

        hierarchy_error = check_role_hierarchy(ctx, member)
        if hierarchy_error is not None:
            await ctx.reply(hierarchy_error, ephemeral=True)
            return

        await warn_store.add(
            WarnRecord(
                guild_id=ctx.guild.id,
                user_id=member.id,
                moderator_id=ctx.author.id,
                reason=reason,
                created_at=datetime.now(UTC),
            )
        )
        count = len(await warn_store.list_for_user(ctx.guild.id, member.id))

        confirmation = f"Warned **{member}** ({count} total warning(s)).\nReason: {reason}"

        if auto_timeout_after is not None and count >= auto_timeout_after:
            until = discord.utils.utcnow() + timedelta(minutes=auto_timeout_minutes)
            await member.timeout(until, reason=f"Reached {count} warnings")
            confirmation += f"\nAuto-timed out for {auto_timeout_minutes} minute(s)."

        await ctx.reply(confirmation)

    return warn


_WarnRow: type[Any] | None = None


def _ensure_sql_models() -> type[Any]:
    """Builds the SQLAlchemy Base/Row classes for `SQLWarnStore` on first
    use, so importing this module never requires SQLAlchemy -- only
    constructing a `SQLWarnStore` does."""
    global _WarnRow
    if _WarnRow is None:
        from sqlalchemy import BigInteger, Column, DateTime, Integer, Text
        from sqlalchemy.orm import DeclarativeBase

        class _Base(DeclarativeBase):
            pass

        class _Row(_Base):
            # Plain `Column(...)` (not the `Mapped[...]` annotation style)
            # deliberately -- this class is built dynamically inside a
            # module with `from __future__ import annotations`, so
            # `Mapped[int]`-style annotations would need to resolve as
            # strings against sqlalchemy's registry, which fails for a
            # class defined inside a function. `Column` has no such
            # requirement.
            __tablename__ = "dwa_builtin_warns"

            id = Column(Integer, primary_key=True, autoincrement=True)
            guild_id = Column(BigInteger, index=True)
            user_id = Column(BigInteger, index=True)
            moderator_id = Column(BigInteger)
            reason = Column(Text)
            created_at = Column(DateTime(timezone=True))

        _WarnRow = _Row
    return _WarnRow


class SQLWarnStore:
    """SQL-backed WarnStore. Needs the `discord-webapi[sql]` extra. Call
    `await store.create_all()` once at startup (or manage
    `dwa_builtin_warns` via your own migration tool) -- independent of
    `discord_webapi.storage.sql.create_all()`, so importing this never
    creates a table for people who only use the Memory store."""

    def __init__(self, engine: AsyncEngine) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        row_cls = _ensure_sql_models()
        async with self._engine.begin() as conn:
            await conn.run_sync(row_cls.metadata.create_all)

    async def add(self, record: WarnRecord) -> None:
        row_cls = _ensure_sql_models()
        async with self._sessionmaker() as db:
            db.add(
                row_cls(
                    guild_id=record.guild_id,
                    user_id=record.user_id,
                    moderator_id=record.moderator_id,
                    reason=record.reason,
                    created_at=record.created_at,
                )
            )
            await db.commit()

    async def list_for_user(self, guild_id: int, user_id: int) -> list[WarnRecord]:
        from sqlalchemy import select

        row_cls = _ensure_sql_models()
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(row_cls).where(row_cls.guild_id == guild_id, row_cls.user_id == user_id)
            )
            return [
                WarnRecord(
                    guild_id=row.guild_id,
                    user_id=row.user_id,
                    moderator_id=row.moderator_id,
                    reason=row.reason,
                    created_at=row.created_at,
                )
                for row in result.scalars()
            ]
