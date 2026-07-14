"""Proves discord_webapi.storage.sql is genuinely database-agnostic: the
exact same store classes, run against SQLite, Postgres, and MySQL/MariaDB
via nothing but a different SQLAlchemy connection string. Each backend is
skipped gracefully if unreachable (e.g. CI without those services) rather
than failing the whole suite.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from discord_webapi.authz.models import AppRole
from discord_webapi.commands.models import CommandOverride
from discord_webapi.storage.base import Session
from discord_webapi.storage.sql import (
    Base,
    SQLAuthzStore,
    SQLCommandConfigStore,
    SQLSessionStore,
    create_all,
)

POSTGRES_URL = os.environ.get(
    "DWA_TEST_POSTGRES_URL", "postgresql+asyncpg://dwa_test:dwa_test@localhost/dwa_test"
)
MYSQL_URL = os.environ.get(
    "DWA_TEST_MYSQL_URL", "mysql+aiomysql://dwa_test:dwa_test@localhost/dwa_test"
)

ENGINE_FACTORIES = {
    "sqlite": lambda: create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    ),
    "postgres": lambda: create_async_engine(POSTGRES_URL),
    "mysql": lambda: create_async_engine(MYSQL_URL),
}


@pytest_asyncio.fixture(params=list(ENGINE_FACTORIES))
async def engine(request: pytest.FixtureRequest) -> AsyncEngine:
    eng = ENGINE_FACTORIES[request.param]()
    try:
        async with eng.begin():
            pass  # just verifying connectivity
    except (SQLAlchemyError, OSError):
        await eng.dispose()
        pytest.skip(
            f"No {request.param} reachable for multi-DB storage tests "
            f"(set DWA_TEST_{request.param.upper()}_URL)"
        )
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


async def test_session_store_round_trip_across_backends(engine: AsyncEngine) -> None:
    await create_all(engine)
    store = SQLSessionStore(engine)
    now = datetime.now(UTC)
    session = Session(
        session_id="sess-1",
        user_id=123,
        username="testuser",
        guild_ids=[1, 2, 3],
        created_at=now,
        expires_at=now + timedelta(days=30),
        encrypted_access_token=b"enc-access",
        encrypted_refresh_token=b"enc-refresh",
        discord_token_expires_at=now + timedelta(minutes=10),
    )

    await store.create(session)
    fetched = await store.get(session.session_id)
    assert fetched == session

    await store.delete(session.session_id)
    assert await store.get(session.session_id) is None


async def test_command_config_store_round_trip_across_backends(engine: AsyncEngine) -> None:
    await create_all(engine)
    store = SQLCommandConfigStore(engine)
    override = CommandOverride(
        guild_id=1,
        command_name="kick",
        enabled=False,
        cooldown_seconds=60.0,
        cooldown_uses=3,
        updated_at=datetime.now(UTC),
    )

    await store.set_override(override)
    fetched = await store.get_override(1, "kick")

    assert fetched is not None
    assert fetched.enabled is False
    assert fetched.cooldown_seconds == 60.0
    assert fetched.cooldown_uses == 3


async def test_authz_store_round_trip_across_backends(engine: AsyncEngine) -> None:
    await create_all(engine)
    store = SQLAuthzStore(engine)
    role = AppRole(guild_id=1, name="moderator", discord_role_ids=[10, 20], user_ids=[42])

    await store.set_app_role(role)
    roles = await store.get_all_app_roles(1)

    assert len(roles) == 1
    assert roles[0].discord_role_ids == [10, 20]
    assert roles[0].user_ids == [42]
