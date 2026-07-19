from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from discord_webapi.escalation.memory import MemoryEscalationRuleStore, MemoryViolationStore
from discord_webapi.escalation.models import EscalationAction, EscalationRule, ViolationRecord
from discord_webapi.escalation.sql import SQLEscalationRuleStore, SQLViolationStore


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


def _make_rule(
    guild_id: int = 1,
    key: str = "warn",
    threshold: int = 3,
    action: EscalationAction = EscalationAction.TIMEOUT,
) -> EscalationRule:
    return EscalationRule(
        guild_id=guild_id,
        key=key,
        threshold=threshold,
        action=action,
        action_minutes=10,
        reason="too many warnings",
        updated_at=datetime.now(UTC),
        updated_by_user_id=42,
    )


def _make_violation(guild_id: int = 1, user_id: int = 100, key: str = "warn") -> ViolationRecord:
    return ViolationRecord(
        guild_id=guild_id,
        user_id=user_id,
        key=key,
        source="manual",
        reason="spam",
        created_at=datetime.now(UTC),
    )


# -- MemoryEscalationRuleStore --


async def test_memory_rule_store_set_and_get() -> None:
    store = MemoryEscalationRuleStore()
    await store.set_rule(_make_rule())

    rules = await store.get_rules(1, "warn")
    assert len(rules) == 1
    assert rules[0].threshold == 3
    assert rules[0].action == EscalationAction.TIMEOUT


async def test_memory_rule_store_get_missing_returns_empty() -> None:
    store = MemoryEscalationRuleStore()
    assert await store.get_rules(1, "does-not-exist") == []


async def test_memory_rule_store_sorted_by_threshold() -> None:
    store = MemoryEscalationRuleStore()
    await store.set_rule(_make_rule(threshold=5, action=EscalationAction.BAN))
    await store.set_rule(_make_rule(threshold=1, action=EscalationAction.NONE))
    await store.set_rule(_make_rule(threshold=3, action=EscalationAction.TIMEOUT))

    rules = await store.get_rules(1, "warn")
    assert [r.threshold for r in rules] == [1, 3, 5]


async def test_memory_rule_store_get_all_rules_across_keys() -> None:
    store = MemoryEscalationRuleStore()
    await store.set_rule(_make_rule(key="warn", threshold=3))
    await store.set_rule(_make_rule(key="automod.spam", threshold=2, action=EscalationAction.KICK))

    rules = await store.get_all_rules(1)
    assert {r.key for r in rules} == {"warn", "automod.spam"}


async def test_memory_rule_store_upserts() -> None:
    store = MemoryEscalationRuleStore()
    await store.set_rule(_make_rule(threshold=3, action=EscalationAction.TIMEOUT))
    await store.set_rule(_make_rule(threshold=3, action=EscalationAction.KICK))

    rules = await store.get_rules(1, "warn")
    assert len(rules) == 1
    assert rules[0].action == EscalationAction.KICK


async def test_memory_rule_store_delete() -> None:
    store = MemoryEscalationRuleStore()
    await store.set_rule(_make_rule(threshold=3))
    await store.delete_rule(1, "warn", 3)

    assert await store.get_rules(1, "warn") == []


async def test_memory_rule_store_delete_missing_is_noop() -> None:
    store = MemoryEscalationRuleStore()
    await store.delete_rule(1, "warn", 99)


# -- MemoryViolationStore --


async def test_memory_violation_store_count() -> None:
    store = MemoryViolationStore()
    await store.add(_make_violation())
    await store.add(_make_violation())

    assert await store.count(1, 100, "warn") == 2


async def test_memory_violation_store_scoped_by_guild_user_key() -> None:
    store = MemoryViolationStore()
    await store.add(_make_violation(guild_id=1, user_id=100, key="warn"))
    await store.add(_make_violation(guild_id=1, user_id=200, key="warn"))
    await store.add(_make_violation(guild_id=2, user_id=100, key="warn"))
    await store.add(_make_violation(guild_id=1, user_id=100, key="automod.spam"))

    assert await store.count(1, 100, "warn") == 1


async def test_memory_violation_store_count_missing_is_zero() -> None:
    store = MemoryViolationStore()
    assert await store.count(1, 100, "warn") == 0


# -- SQLEscalationRuleStore --


async def test_sql_rule_store_set_and_get(engine: AsyncEngine) -> None:
    store = SQLEscalationRuleStore(engine)
    await store.create_all()
    await store.set_rule(_make_rule())

    rules = await store.get_rules(1, "warn")
    assert len(rules) == 1
    assert rules[0].threshold == 3
    assert rules[0].updated_by_user_id == 42


async def test_sql_rule_store_upserts(engine: AsyncEngine) -> None:
    store = SQLEscalationRuleStore(engine)
    await store.create_all()
    await store.set_rule(_make_rule(threshold=3, action=EscalationAction.TIMEOUT))
    await store.set_rule(_make_rule(threshold=3, action=EscalationAction.BAN))

    rules = await store.get_rules(1, "warn")
    assert len(rules) == 1
    assert rules[0].action == EscalationAction.BAN


async def test_sql_rule_store_get_all_rules(engine: AsyncEngine) -> None:
    store = SQLEscalationRuleStore(engine)
    await store.create_all()
    await store.set_rule(_make_rule(key="warn", threshold=3))
    await store.set_rule(_make_rule(key="automod.spam", threshold=2, action=EscalationAction.KICK))

    rules = await store.get_all_rules(1)
    assert {r.key for r in rules} == {"warn", "automod.spam"}


async def test_sql_rule_store_delete(engine: AsyncEngine) -> None:
    store = SQLEscalationRuleStore(engine)
    await store.create_all()
    await store.set_rule(_make_rule(threshold=3))
    await store.delete_rule(1, "warn", 3)

    assert await store.get_rules(1, "warn") == []


async def test_sql_rule_store_delete_missing_is_noop(engine: AsyncEngine) -> None:
    store = SQLEscalationRuleStore(engine)
    await store.create_all()
    await store.delete_rule(1, "warn", 99)


# -- SQLViolationStore --


async def test_sql_violation_store_count(engine: AsyncEngine) -> None:
    store = SQLViolationStore(engine)
    await store.create_all()
    await store.add(_make_violation())
    await store.add(_make_violation())

    assert await store.count(1, 100, "warn") == 2


async def test_sql_violation_store_scoped_by_guild_user_key(engine: AsyncEngine) -> None:
    store = SQLViolationStore(engine)
    await store.create_all()
    await store.add(_make_violation(guild_id=1, user_id=100, key="warn"))
    await store.add(_make_violation(guild_id=1, user_id=200, key="warn"))
    await store.add(_make_violation(guild_id=2, user_id=100, key="warn"))
    await store.add(_make_violation(guild_id=1, user_id=100, key="automod.spam"))

    assert await store.count(1, 100, "warn") == 1


async def test_sql_violation_store_count_missing_is_zero(engine: AsyncEngine) -> None:
    store = SQLViolationStore(engine)
    await store.create_all()
    assert await store.count(1, 100, "warn") == 0
