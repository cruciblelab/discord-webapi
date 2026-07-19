from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from discord_webapi.authz.models import AppRole
from discord_webapi.commands.models import CommandOverride
from discord_webapi.exceptions import SessionExpiredError
from discord_webapi.storage.base import Session
from discord_webapi.storage.sql import SQLAuthzStore, SQLCommandConfigStore, SQLSessionStore


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    # StaticPool: a single shared connection, so the in-memory SQLite
    # database survives across the multiple short-lived sessions each
    # store method opens (a fresh `:memory:` connection per session would
    # otherwise mean a fresh, empty database every time).
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        yield eng
    finally:
        await eng.dispose()


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

    with pytest.raises(SessionExpiredError, match="does not exist"):
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


async def test_sql_session_store_list_by_user_returns_only_that_users_sessions(
    engine: AsyncEngine,
) -> None:
    store = SQLSessionStore(engine)
    await store.create_all()
    mine_1 = _make_session("sess-1")
    mine_2 = _make_session("sess-2")
    other = _make_session("sess-3").model_copy(update={"user_id": 456})
    await store.create(mine_1)
    await store.create(mine_2)
    await store.create(other)

    sessions = await store.list_by_user(123)

    assert {s.session_id for s in sessions} == {"sess-1", "sess-2"}


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


def _make_app_role(guild_id: int = 1, name: str = "moderator") -> AppRole:
    return AppRole(guild_id=guild_id, name=name, discord_role_ids=[10], user_ids=[42])


async def test_sql_authz_store_set_and_get_all(engine: AsyncEngine) -> None:
    store = SQLAuthzStore(engine)
    await store.create_all()

    await store.set_app_role(_make_app_role())
    roles = await store.get_all_app_roles(1)

    assert len(roles) == 1
    assert roles[0].discord_role_ids == [10]
    assert roles[0].user_ids == [42]


async def test_sql_authz_store_set_upserts(engine: AsyncEngine) -> None:
    store = SQLAuthzStore(engine)
    await store.create_all()
    await store.set_app_role(_make_app_role())

    updated = _make_app_role().model_copy(update={"user_ids": [999]})
    await store.set_app_role(updated)

    roles = await store.get_all_app_roles(1)
    assert len(roles) == 1
    assert roles[0].user_ids == [999]


async def test_sql_authz_store_filters_by_guild(engine: AsyncEngine) -> None:
    store = SQLAuthzStore(engine)
    await store.create_all()
    await store.set_app_role(_make_app_role(guild_id=1))
    await store.set_app_role(_make_app_role(guild_id=2))

    assert len(await store.get_all_app_roles(1)) == 1
    assert len(await store.get_all_app_roles(2)) == 1


async def test_sql_authz_store_delete(engine: AsyncEngine) -> None:
    store = SQLAuthzStore(engine)
    await store.create_all()
    await store.set_app_role(_make_app_role())

    await store.delete_app_role(1, "moderator")

    assert await store.get_all_app_roles(1) == []
