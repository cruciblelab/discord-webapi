from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from discord_webapi.commands.models import CommandOverride
from discord_webapi.storage.base import Session
from discord_webapi.storage.sql import SQLCommandConfigStore, SQLSessionStore


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    # StaticPool: a single shared connection, so the in-memory SQLite
    # database survives across the multiple short-lived sessions each
    # store method opens (a fresh `:memory:` connection per session would
    # otherwise mean a fresh, empty database every time).
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def _make_session(session_id: str = "sess-1") -> Session:
    now = datetime.now(UTC)
    return Session(
        session_id=session_id,
        user_id=123,
        username="testuser",
        guild_ids=[1, 2, 3],
        created_at=now,
        expires_at=now + timedelta(days=30),
        encrypted_access_token=b"enc-access",
        encrypted_refresh_token=b"enc-refresh",
        discord_token_expires_at=now + timedelta(minutes=10),
    )


async def test_sql_session_store_create_and_get_round_trips(engine: AsyncEngine) -> None:
    store = SQLSessionStore(engine)
    await store.create_all()
    session = _make_session()

    await store.create(session)
    fetched = await store.get(session.session_id)

    assert fetched == session


async def test_sql_session_store_get_missing_returns_none(engine: AsyncEngine) -> None:
    store = SQLSessionStore(engine)
    await store.create_all()

    assert await store.get("does-not-exist") is None


async def test_sql_session_store_update_overwrites_fields(engine: AsyncEngine) -> None:
    store = SQLSessionStore(engine)
    await store.create_all()
    session = _make_session()
    await store.create(session)

    updated = session.model_copy(update={"encrypted_access_token": b"new-access"})
    await store.update(updated)

    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert fetched.encrypted_access_token == b"new-access"


async def test_sql_session_store_update_missing_raises(engine: AsyncEngine) -> None:
    store = SQLSessionStore(engine)
    await store.create_all()

    with pytest.raises(ValueError, match="does not exist"):
        await store.update(_make_session("nonexistent"))


async def test_sql_session_store_delete_removes_row(engine: AsyncEngine) -> None:
    store = SQLSessionStore(engine)
    await store.create_all()
    session = _make_session()
    await store.create(session)

    await store.delete(session.session_id)

    assert await store.get(session.session_id) is None


async def test_sql_session_store_timestamps_stay_tz_aware_after_round_trip(
    engine: AsyncEngine,
) -> None:
    """SQLite doesn't preserve tzinfo on its own -- this guards the _as_utc
    normalization that makes comparisons like `expires_at < now(UTC)` work
    regardless of backend."""
    store = SQLSessionStore(engine)
    await store.create_all()
    session = _make_session()
    await store.create(session)

    fetched = await store.get(session.session_id)

    assert fetched is not None
    assert fetched.expires_at.tzinfo is not None
    assert fetched.expires_at > datetime.now(UTC)


def _make_override(guild_id: int = 1, command_name: str = "kick") -> CommandOverride:
    return CommandOverride(
        guild_id=guild_id,
        command_name=command_name,
        enabled=False,
        updated_at=datetime.now(UTC),
        updated_by_user_id=42,
    )


async def test_sql_command_config_store_set_and_get_override(engine: AsyncEngine) -> None:
    store = SQLCommandConfigStore(engine)
    await store.create_all()
    override = _make_override()

    await store.set_override(override)
    fetched = await store.get_override(1, "kick")

    assert fetched is not None
    assert fetched.enabled is False
    assert fetched.updated_by_user_id == 42


async def test_sql_command_config_store_set_override_upserts(engine: AsyncEngine) -> None:
    store = SQLCommandConfigStore(engine)
    await store.create_all()
    await store.set_override(_make_override())

    updated = _make_override().model_copy(update={"enabled": True})
    await store.set_override(updated)

    fetched = await store.get_override(1, "kick")
    assert fetched is not None
    assert fetched.enabled is True


async def test_sql_command_config_store_get_override_missing_returns_none(
    engine: AsyncEngine,
) -> None:
    store = SQLCommandConfigStore(engine)
    await store.create_all()

    assert await store.get_override(1, "does-not-exist") is None


async def test_sql_command_config_store_get_all_overrides_filters_by_guild(
    engine: AsyncEngine,
) -> None:
    store = SQLCommandConfigStore(engine)
    await store.create_all()
    await store.set_override(_make_override(guild_id=1, command_name="kick"))
    await store.set_override(_make_override(guild_id=1, command_name="ban"))
    await store.set_override(_make_override(guild_id=2, command_name="kick"))

    overrides = await store.get_all_overrides(1)

    assert {o.command_name for o in overrides} == {"kick", "ban"}
