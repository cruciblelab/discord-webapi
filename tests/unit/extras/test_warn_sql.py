from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from discord_webapi.extras.warn import SQLWarnStore, WarnRecord


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


async def test_sql_warn_store_add_and_list(engine: AsyncEngine) -> None:
    store = SQLWarnStore(engine)
    await store.create_all()

    await store.add(
        WarnRecord(
            guild_id=1, user_id=42, moderator_id=1, reason="spam", created_at=datetime.now(UTC)
        )
    )
    now = datetime.now(UTC)
    await store.add(
        WarnRecord(guild_id=1, user_id=42, moderator_id=1, reason="spam again", created_at=now)
    )
    # A different guild/user must not show up in the first user's list.
    await store.add(
        WarnRecord(guild_id=2, user_id=42, moderator_id=1, reason="other guild", created_at=now)
    )

    warnings = await store.list_for_user(1, 42)

    assert len(warnings) == 2
    assert {w.reason for w in warnings} == {"spam", "spam again"}
