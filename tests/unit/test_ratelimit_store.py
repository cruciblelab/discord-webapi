from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from discord_webapi.ratelimits.models import RateLimitRule
from discord_webapi.storage.memory import MemoryRateLimitStore
from discord_webapi.storage.sql import SQLRateLimitStore


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        yield eng
    finally:
        await eng.dispose()


def _make_rule(guild_id: int = 1, key: str = "automod.spam") -> RateLimitRule:
    return RateLimitRule(
        guild_id=guild_id,
        key=key,
        max_calls=10,
        per_seconds=30.0,
        updated_at=datetime.now(UTC),
        updated_by_user_id=42,
    )


async def test_memory_store_set_and_get_rule() -> None:
    store = MemoryRateLimitStore()
    rule = _make_rule()

    await store.set_rule(rule)
    fetched = await store.get_rule(1, "automod.spam")

    assert fetched is not None
    assert fetched.max_calls == 10
    assert fetched.updated_by_user_id == 42


async def test_memory_store_get_missing_returns_none() -> None:
    store = MemoryRateLimitStore()

    assert await store.get_rule(1, "does-not-exist") is None


async def test_memory_store_set_rule_upserts() -> None:
    store = MemoryRateLimitStore()
    await store.set_rule(_make_rule())

    updated = _make_rule().model_copy(update={"max_calls": 99})
    await store.set_rule(updated)

    fetched = await store.get_rule(1, "automod.spam")
    assert fetched is not None
    assert fetched.max_calls == 99


async def test_memory_store_get_all_rules_filters_by_guild() -> None:
    store = MemoryRateLimitStore()
    await store.set_rule(_make_rule(guild_id=1, key="a"))
    await store.set_rule(_make_rule(guild_id=1, key="b"))
    await store.set_rule(_make_rule(guild_id=2, key="a"))

    rules = await store.get_all_rules(1)

    assert {r.key for r in rules} == {"a", "b"}


async def test_memory_store_delete_rule() -> None:
    store = MemoryRateLimitStore()
    await store.set_rule(_make_rule())

    await store.delete_rule(1, "automod.spam")

    assert await store.get_rule(1, "automod.spam") is None


async def test_sql_store_set_and_get_rule(engine: AsyncEngine) -> None:
    store = SQLRateLimitStore(engine)
    await store.create_all()
    rule = _make_rule()

    await store.set_rule(rule)
    fetched = await store.get_rule(1, "automod.spam")

    assert fetched is not None
    assert fetched.max_calls == 10
    assert fetched.updated_by_user_id == 42


async def test_sql_store_set_rule_upserts(engine: AsyncEngine) -> None:
    store = SQLRateLimitStore(engine)
    await store.create_all()
    await store.set_rule(_make_rule())

    updated = _make_rule().model_copy(update={"max_calls": 99})
    await store.set_rule(updated)

    fetched = await store.get_rule(1, "automod.spam")
    assert fetched is not None
    assert fetched.max_calls == 99


async def test_sql_store_get_missing_returns_none(engine: AsyncEngine) -> None:
    store = SQLRateLimitStore(engine)
    await store.create_all()

    assert await store.get_rule(1, "does-not-exist") is None


async def test_sql_store_get_all_rules_filters_by_guild(engine: AsyncEngine) -> None:
    store = SQLRateLimitStore(engine)
    await store.create_all()
    await store.set_rule(_make_rule(guild_id=1, key="a"))
    await store.set_rule(_make_rule(guild_id=1, key="b"))
    await store.set_rule(_make_rule(guild_id=2, key="a"))

    rules = await store.get_all_rules(1)

    assert {r.key for r in rules} == {"a", "b"}


async def test_sql_store_delete_rule(engine: AsyncEngine) -> None:
    store = SQLRateLimitStore(engine)
    await store.create_all()
    await store.set_rule(_make_rule())

    await store.delete_rule(1, "automod.spam")

    assert await store.get_rule(1, "automod.spam") is None
