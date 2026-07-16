"""SessionStore / CommandConfigStore backed by SQLAlchemy 2.0 async.

Requires the `discord-webapi[sql]` extra (SQLAlchemy + a DBAPI driver,
e.g. `aiosqlite` for SQLite or `asyncpg` for Postgres).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    String,
    select,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from discord_webapi.audit.models import AuditLogEntry
from discord_webapi.authz.models import AppRole
from discord_webapi.commands.models import CommandOverride
from discord_webapi.consent.models import ConsentRecord
from discord_webapi.ratelimits.models import RateLimitRule
from discord_webapi.storage.base import Session

# MySQL/MariaDB's DATETIME defaults to 0 fractional-second precision --
# unlike Postgres/SQLite, it silently truncates microseconds on every
# round-trip unless told otherwise. `with_variant` only changes the type
# actually compiled for the mysql dialect; Postgres and SQLite keep using
# plain `DateTime(timezone=True)`.
_TIMESTAMP = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "dwa_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(128))
    global_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(128), nullable=True)
    guild_ids: Mapped[list[int]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(_TIMESTAMP)
    expires_at: Mapped[datetime] = mapped_column(_TIMESTAMP)
    encrypted_access_token: Mapped[bytes] = mapped_column(LargeBinary)
    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary)
    discord_token_expires_at: Mapped[datetime] = mapped_column(_TIMESTAMP)


class CommandOverrideRow(Base):
    __tablename__ = "dwa_command_overrides"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    command_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    cooldown_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    cooldown_uses: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    required_app_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(_TIMESTAMP)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AppRoleRow(Base):
    __tablename__ = "dwa_app_roles"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    discord_role_ids: Mapped[list[int]] = mapped_column(JSON)
    user_ids: Mapped[list[int]] = mapped_column(JSON)


class AuditLogRow(Base):
    __tablename__ = "dwa_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    actor_user_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(256))
    detail: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(_TIMESTAMP)


class ConsentRecordRow(Base):
    __tablename__ = "dwa_consent_records"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    consent_version: Mapped[str] = mapped_column(String(64))
    given_at: Mapped[datetime] = mapped_column(_TIMESTAMP)


class RateLimitRuleRow(Base):
    __tablename__ = "dwa_ratelimit_rules"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    max_calls: Mapped[int] = mapped_column(Integer)
    per_seconds: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(_TIMESTAMP)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


async def create_all(engine: AsyncEngine) -> None:
    """Create all tables (sessions, command overrides, app roles). Call once
    at startup, or manage schema via your own migration tool (e.g. Alembic)
    in production instead."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _as_utc(value: datetime) -> datetime:
    # SQLite (aiosqlite) doesn't actually preserve tzinfo across a
    # round-trip even with DateTime(timezone=True) -- it hands back a naive
    # datetime. Postgres (asyncpg) does preserve it. Normalizing here keeps
    # Session/CommandOverride's timestamps comparable against
    # datetime.now(UTC) regardless of which backend is configured.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _row_to_session(row: SessionRow) -> Session:
    return Session(
        session_id=row.session_id,
        user_id=row.user_id,
        username=row.username,
        global_name=row.global_name,
        avatar=row.avatar,
        guild_ids=row.guild_ids,
        created_at=_as_utc(row.created_at),
        expires_at=_as_utc(row.expires_at),
        encrypted_access_token=row.encrypted_access_token,
        encrypted_refresh_token=row.encrypted_refresh_token,
        discord_token_expires_at=_as_utc(row.discord_token_expires_at),
    )


def _row_to_app_role(row: AppRoleRow) -> AppRole:
    return AppRole(
        guild_id=row.guild_id,
        name=row.name,
        discord_role_ids=row.discord_role_ids,
        user_ids=row.user_ids,
    )


def _row_to_override(row: CommandOverrideRow) -> CommandOverride:
    return CommandOverride(
        guild_id=row.guild_id,
        command_name=row.command_name,
        enabled=row.enabled,
        cooldown_seconds=row.cooldown_seconds,
        cooldown_uses=row.cooldown_uses,
        required_app_role=row.required_app_role,
        updated_at=_as_utc(row.updated_at),
        updated_by_user_id=row.updated_by_user_id,
    )


def _row_to_audit_entry(row: AuditLogRow) -> AuditLogEntry:
    return AuditLogEntry(
        guild_id=row.guild_id,
        actor_user_id=row.actor_user_id,
        action=row.action,
        target=row.target,
        detail=row.detail,
        created_at=_as_utc(row.created_at),
    )


def _row_to_consent_record(row: ConsentRecordRow) -> ConsentRecord:
    return ConsentRecord(
        user_id=row.user_id,
        consent_version=row.consent_version,
        given_at=_as_utc(row.given_at),
    )


def _row_to_ratelimit_rule(row: RateLimitRuleRow) -> RateLimitRule:
    return RateLimitRule(
        guild_id=row.guild_id,
        key=row.key,
        max_calls=row.max_calls,
        per_seconds=row.per_seconds,
        updated_at=_as_utc(row.updated_at),
        updated_by_user_id=row.updated_by_user_id,
    )


_Row = TypeVar("_Row")


async def _commit_upsert(
    db: AsyncSession,
    *,
    is_new: bool,
    get_existing: Callable[[], Awaitable[_Row | None]],
    apply_fields: Callable[[_Row], None],
) -> None:
    """Commits a get-or-create write, tolerating a concurrent insert of the
    same row (two requests racing to set the same guild/command,
    guild/app-role, or user's consent record for the first time). Without
    this, the loser's commit raises an unhandled IntegrityError -- a 500
    for what should just be "apply my update after theirs". Only relevant
    for genuinely new rows: updates to an existing row have no such race
    since the row (and its lock, under the DB's own concurrency control)
    already exists.
    """
    if not is_new:
        await db.commit()
        return
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await get_existing()
        assert existing is not None, "IntegrityError implies the row now exists"
        apply_fields(existing)
        await db.commit()


class SQLSessionStore:
    """SessionStore backed by SQLAlchemy 2.0 async. Call `create_all()`
    once at startup to create its table (or manage it via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        await create_all(self._engine)

    async def create(self, session: Session) -> None:
        async with self._sessionmaker() as db:
            db.add(
                SessionRow(
                    session_id=session.session_id,
                    user_id=session.user_id,
                    username=session.username,
                    global_name=session.global_name,
                    avatar=session.avatar,
                    guild_ids=session.guild_ids,
                    created_at=session.created_at,
                    expires_at=session.expires_at,
                    encrypted_access_token=session.encrypted_access_token,
                    encrypted_refresh_token=session.encrypted_refresh_token,
                    discord_token_expires_at=session.discord_token_expires_at,
                )
            )
            await db.commit()

    async def get(self, session_id: str) -> Session | None:
        async with self._sessionmaker() as db:
            row = await db.get(SessionRow, session_id)
            return _row_to_session(row) if row is not None else None

    async def update(self, session: Session) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(SessionRow, session.session_id)
            if row is None:
                raise ValueError(f"Session {session.session_id!r} does not exist")
            row.user_id = session.user_id
            row.username = session.username
            row.global_name = session.global_name
            row.avatar = session.avatar
            row.guild_ids = session.guild_ids
            row.created_at = session.created_at
            row.expires_at = session.expires_at
            row.encrypted_access_token = session.encrypted_access_token
            row.encrypted_refresh_token = session.encrypted_refresh_token
            row.discord_token_expires_at = session.discord_token_expires_at
            await db.commit()

    async def delete(self, session_id: str) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(SessionRow, session_id)
            if row is not None:
                await db.delete(row)
                await db.commit()

    async def list_by_user(self, user_id: int) -> list[Session]:
        async with self._sessionmaker() as db:
            result = await db.execute(select(SessionRow).where(SessionRow.user_id == user_id))
            return [_row_to_session(row) for row in result.scalars()]


class SQLCommandConfigStore:
    """CommandConfigStore backed by SQLAlchemy 2.0 async. Call
    `create_all()` once at startup to create its table (or manage it via
    Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        await create_all(self._engine)

    async def get_override(self, guild_id: int, command_name: str) -> CommandOverride | None:
        async with self._sessionmaker() as db:
            row = await db.get(CommandOverrideRow, (guild_id, command_name))
            return _row_to_override(row) if row is not None else None

    async def get_all_overrides(self, guild_id: int) -> list[CommandOverride]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(CommandOverrideRow).where(CommandOverrideRow.guild_id == guild_id)
            )
            return [_row_to_override(row) for row in result.scalars()]

    async def set_override(self, override: CommandOverride) -> None:
        def _apply(row: CommandOverrideRow) -> None:
            row.enabled = override.enabled
            row.cooldown_seconds = override.cooldown_seconds
            row.cooldown_uses = override.cooldown_uses
            row.required_app_role = override.required_app_role
            row.updated_at = override.updated_at
            row.updated_by_user_id = override.updated_by_user_id

        key = (override.guild_id, override.command_name)
        async with self._sessionmaker() as db:
            row = await db.get(CommandOverrideRow, key)
            is_new = row is None
            if row is None:
                row = CommandOverrideRow(
                    guild_id=override.guild_id, command_name=override.command_name
                )
                db.add(row)
            _apply(row)
            await _commit_upsert(
                db,
                is_new=is_new,
                get_existing=lambda: db.get(CommandOverrideRow, key),
                apply_fields=_apply,
            )


class SQLAuthzStore:
    """AuthzStore backed by SQLAlchemy 2.0 async. Call `create_all()` once
    at startup to create its table (or manage it via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        await create_all(self._engine)

    async def get_all_app_roles(self, guild_id: int) -> list[AppRole]:
        async with self._sessionmaker() as db:
            result = await db.execute(select(AppRoleRow).where(AppRoleRow.guild_id == guild_id))
            return [_row_to_app_role(row) for row in result.scalars()]

    async def set_app_role(self, role: AppRole) -> None:
        def _apply(row: AppRoleRow) -> None:
            row.discord_role_ids = role.discord_role_ids
            row.user_ids = role.user_ids

        key = (role.guild_id, role.name)
        async with self._sessionmaker() as db:
            row = await db.get(AppRoleRow, key)
            is_new = row is None
            if row is None:
                row = AppRoleRow(guild_id=role.guild_id, name=role.name)
                db.add(row)
            _apply(row)
            await _commit_upsert(
                db, is_new=is_new, get_existing=lambda: db.get(AppRoleRow, key), apply_fields=_apply
            )

    async def delete_app_role(self, guild_id: int, name: str) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(AppRoleRow, (guild_id, name))
            if row is not None:
                await db.delete(row)
                await db.commit()


class SQLAuditStore:
    """AuditStore backed by SQLAlchemy 2.0 async. Call `create_all()` once
    at startup to create its table (or manage it via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        await create_all(self._engine)

    async def record(self, entry: AuditLogEntry) -> None:
        async with self._sessionmaker() as db:
            db.add(
                AuditLogRow(
                    guild_id=entry.guild_id,
                    actor_user_id=entry.actor_user_id,
                    action=entry.action,
                    target=entry.target,
                    detail=entry.detail,
                    created_at=entry.created_at,
                )
            )
            await db.commit()

    async def list_entries(self, guild_id: int, *, limit: int = 100) -> list[AuditLogEntry]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(AuditLogRow)
                .where(AuditLogRow.guild_id == guild_id)
                .order_by(AuditLogRow.created_at.desc())
                .limit(limit)
            )
            return [_row_to_audit_entry(row) for row in result.scalars()]


class SQLConsentStore:
    """ConsentStore backed by SQLAlchemy 2.0 async. Call `create_all()`
    once at startup to create its table (or manage it via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        await create_all(self._engine)

    async def get(self, user_id: int) -> ConsentRecord | None:
        async with self._sessionmaker() as db:
            row = await db.get(ConsentRecordRow, user_id)
            return _row_to_consent_record(row) if row is not None else None

    async def set(self, record: ConsentRecord) -> None:
        def _apply(row: ConsentRecordRow) -> None:
            row.consent_version = record.consent_version
            row.given_at = record.given_at

        async with self._sessionmaker() as db:
            row = await db.get(ConsentRecordRow, record.user_id)
            is_new = row is None
            if row is None:
                row = ConsentRecordRow(user_id=record.user_id)
                db.add(row)
            _apply(row)
            await _commit_upsert(
                db,
                is_new=is_new,
                get_existing=lambda: db.get(ConsentRecordRow, record.user_id),
                apply_fields=_apply,
            )


class SQLRateLimitStore:
    """RateLimitStore backed by SQLAlchemy 2.0 async. Call `create_all()`
    once at startup to create its table (or manage it via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        await create_all(self._engine)

    async def get_rule(self, guild_id: int, key: str) -> RateLimitRule | None:
        async with self._sessionmaker() as db:
            row = await db.get(RateLimitRuleRow, (guild_id, key))
            return _row_to_ratelimit_rule(row) if row is not None else None

    async def get_all_rules(self, guild_id: int) -> list[RateLimitRule]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(RateLimitRuleRow).where(RateLimitRuleRow.guild_id == guild_id)
            )
            return [_row_to_ratelimit_rule(row) for row in result.scalars()]

    async def set_rule(self, rule: RateLimitRule) -> None:
        def _apply(row: RateLimitRuleRow) -> None:
            row.max_calls = rule.max_calls
            row.per_seconds = rule.per_seconds
            row.updated_at = rule.updated_at
            row.updated_by_user_id = rule.updated_by_user_id

        key = (rule.guild_id, rule.key)
        async with self._sessionmaker() as db:
            row = await db.get(RateLimitRuleRow, key)
            is_new = row is None
            if row is None:
                row = RateLimitRuleRow(guild_id=rule.guild_id, key=rule.key)
                db.add(row)
            _apply(row)
            await _commit_upsert(
                db,
                is_new=is_new,
                get_existing=lambda: db.get(RateLimitRuleRow, key),
                apply_fields=_apply,
            )

    async def delete_rule(self, guild_id: int, key: str) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(RateLimitRuleRow, (guild_id, key))
            if row is not None:
                await db.delete(row)
                await db.commit()
