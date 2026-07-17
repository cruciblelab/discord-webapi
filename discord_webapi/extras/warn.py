"""A fully-configurable warn command with its own persistent state.

Unlike `ban.py`/`kick.py`/`timeout.py` (stateless -- they just call a
Discord API and reply), a warn system has to remember something across
calls, so this file follows the same shape the rest of the library uses
for its own persistent data (`AuditStore`, `ConsentStore`, ...): a
`WarnStore` Protocol with a Memory implementation (zero infrastructure,
the default) and an optional SQL one. **This is its own store, not bolted
onto `CommandConfigStore` or any core storage protocol** -- if you never
import `discord_webapi.extras.warn`, nothing about warnings exists in
your schema or your process. `SQLWarnStore.create_all()` is independent
of `discord_webapi.storage.sql.create_all()`, so adopting it never
creates a table for people who didn't ask for it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import discord
from discord import app_commands
from discord.ext import commands
from pydantic import BaseModel

from discord_webapi.extras._shared import check_role_hierarchy, notify_member_best_effort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from discord_webapi.audit.logger import AuditLogger


class WarnRecord(BaseModel):
    guild_id: int
    user_id: int
    moderator_id: int
    reason: str | None
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
    require_reason: bool = True,
    dm_before_warn: bool = False,
    auto_timeout_after: int | None = None,
    auto_timeout_minutes: int = 10,
    audit_logger: AuditLogger | None = None,
) -> Any:
    """Registers a warn command on `bot` and returns it.

    `store` defaults to a fresh `MemoryWarnStore` -- warnings are lost on
    restart unless you pass a `SQLWarnStore(engine)` (see
    `discord_webapi.extras.warn.SQLWarnStore`, needs `discord-webapi[sql]`)
    or your own `WarnStore` implementation.

    `require_reason` (default `True`, same as `extras.ban`/`kick`/`timeout`)
    -- warn's entire purpose is behavioral correction, so a reason is
    required unless you opt out.

    `dm_before_warn` (default `False`, unlike `ban`/`kick`'s `True` -- a
    warning is common/low-stakes enough that many bots don't want an
    automatic DM for every one): best-effort heads-up DM, same as
    `notify_member_best_effort` everywhere else in this package.

    `auto_timeout_after`: if set, a member's `N`th warning in this guild
    automatically applies a `Member.timeout` of `auto_timeout_minutes` --
    escalation is opt-in, never assumed. This is its own independent
    counter (`WarnStore.list_for_user`'s length), separate from
    `discord_webapi.escalation.EscalationEngine`'s violation counts. If you
    ALSO wire `automod`'s `on_violation` hook (or your own code) into
    `EscalationEngine.record_violation(member, key)` for a `key` that
    overlaps conceptually with "warnings", the two thresholds don't share
    a count and can trigger independently of each other -- pick one
    mechanism per concept, or be deliberate about running both.

    `audit_logger`: opt-in. Pass an `AuditLogger` (e.g. `api.audit_logger`,
    non-None only when `enable_audit_log=True`) to record each warning to
    the audit trail; omit it and nothing is audited.
    """
    warn_store = store or MemoryWarnStore()
    # Per (guild_id, user_id) lock -- see the comment at its use below.
    warn_locks: dict[tuple[int, int], asyncio.Lock] = {}

    @bot.hybrid_command(  # type: ignore[arg-type]
        name=command_name, description="Warn a member"
    )
    @app_commands.describe(member="The member to warn", reason="Why this member is being warned")
    @commands.has_permissions(moderate_members=True)
    async def warn(
        ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None
    ) -> None:
        if require_reason and not reason:
            await ctx.reply("A reason is required to warn this member.", ephemeral=True)
            return
        if ctx.guild is None:
            return

        hierarchy_error = check_role_hierarchy(ctx, member)
        if hierarchy_error is not None:
            await ctx.reply(hierarchy_error, ephemeral=True)
            return

        if dm_before_warn:
            notice = f"You have been warned in **{ctx.guild.name}**."
            if reason:
                notice += f"\nReason: {reason}"
            await notify_member_best_effort(member, notice)

        # The add-then-count-then-maybe-timeout sequence below runs under
        # a per-(guild, user) lock: `warn_store.add()`/`list_for_user()`
        # are two separate store calls, so two concurrent warnings for
        # the same member (two moderators warning at once, or a double
        # click) could both land their `add()` before either counted --
        # both would then read the *same* post-add count, and if it
        # matches `auto_timeout_after`, both would fire the auto-timeout
        # (and both audit-log it) for what should have been a single
        # threshold crossing. Same class of fix as
        # `EscalationEngine.record_violation`'s per-(guild, user, key)
        # lock.
        lock_key = (ctx.guild.id, member.id)
        lock = warn_locks.setdefault(lock_key, asyncio.Lock())
        try:
            async with lock:
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

                if audit_logger is not None:
                    await audit_logger.record(
                        guild_id=ctx.guild.id,
                        actor_user_id=ctx.author.id,
                        action="warn",
                        target=str(member.id),
                        detail={"reason": reason, "count": count},
                    )

                confirmation = f"Warned **{member}** ({count} total warning(s))."
                if reason:
                    confirmation += f"\nReason: {reason}"

                if auto_timeout_after is not None and count == auto_timeout_after:
                    # Bot-permission check is deliberately runtime/best-effort,
                    # not a blanket
                    # @commands.bot_has_permissions(moderate_members=True)
                    # decorator -- that would require every bot using warn()
                    # to grant moderate_members even when auto_timeout_after
                    # is never configured, when the bot never calls
                    # Member.timeout at all.
                    until = discord.utils.utcnow() + timedelta(minutes=auto_timeout_minutes)
                    try:
                        await member.timeout(until, reason=f"Reached {count} warnings")
                        confirmation += (
                            f"\nAuto-timed out for {auto_timeout_minutes} minute(s)."
                        )
                    except discord.Forbidden:
                        confirmation += (
                            "\nReached the auto-timeout threshold, but I don't have "
                            "permission to time this member out."
                        )
                    except discord.NotFound:
                        confirmation += (
                            "\nReached the auto-timeout threshold, but that member is "
                            "no longer in the server."
                        )
        finally:
            warn_locks.pop(lock_key, None)

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
