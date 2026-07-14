"""SessionStore / CommandConfigStore backed by SQLAlchemy 2.0 async.

Requires the `discord-webapi[sql]` extra (SQLAlchemy + a DBAPI driver,
e.g. `aiosqlite` for SQLite or `asyncpg` for Postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, LargeBinary, String, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from discord_webapi.authz.models import AppRole
from discord_webapi.commands.models import CommandOverride
from discord_webapi.storage.base import Session


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    encrypted_access_token: Mapped[bytes] = mapped_column(LargeBinary)
    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary)
    discord_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommandOverrideRow(Base):
    __tablename__ = "dwa_command_overrides"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    command_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    cooldown_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    cooldown_uses: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    required_app_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AppRoleRow(Base):
    __tablename__ = "dwa_app_roles"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    discord_role_ids: Mapped[list[int]] = mapped_column(JSON)
    user_ids: Mapped[list[int]] = mapped_column(JSON)


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
        async with self._sessionmaker() as db:
            row = await db.get(CommandOverrideRow, (override.guild_id, override.command_name))
            if row is None:
                row = CommandOverrideRow(
                    guild_id=override.guild_id, command_name=override.command_name
                )
                db.add(row)
            row.enabled = override.enabled
            row.cooldown_seconds = override.cooldown_seconds
            row.cooldown_uses = override.cooldown_uses
            row.required_app_role = override.required_app_role
            row.updated_at = override.updated_at
            row.updated_by_user_id = override.updated_by_user_id
            await db.commit()


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
        async with self._sessionmaker() as db:
            row = await db.get(AppRoleRow, (role.guild_id, role.name))
            if row is None:
                row = AppRoleRow(guild_id=role.guild_id, name=role.name)
                db.add(row)
            row.discord_role_ids = role.discord_role_ids
            row.user_ids = role.user_ids
            await db.commit()

    async def delete_app_role(self, guild_id: int, name: str) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(AppRoleRow, (guild_id, name))
            if row is not None:
                await db.delete(row)
                await db.commit()
